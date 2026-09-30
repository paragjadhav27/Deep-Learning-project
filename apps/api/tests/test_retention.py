"""Deletion, retention expiry, signed-URL expiry, and metadata purge."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select

from facelens_api.db.models import JobRecord, SessionRecord
from facelens_api.services.sessions import sweep

from conftest import FULL_CONSENT, FakeClock, container_of, make_image, new_session


def _aging_job(client: TestClient, sid: str, h: dict[str, str]) -> dict[str, object]:
    body = {"task": "age_transformation", "params": {"target_age_group": "older_adult"}}
    job: dict[str, object] = client.post(f"/v1/sessions/{sid}/jobs", json=body, headers=h).json()
    return job


def _blob_count(client: TestClient, sid: str) -> int:
    root = container_of(client).blobs.root  # type: ignore[attr-defined]
    d = root / "sessions" / sid
    return sum(1 for p in d.rglob("*") if p.is_file()) if d.exists() else 0


def test_delete_session_removes_everything(client: TestClient) -> None:
    sid, h = new_session(client)
    job = _aging_job(client, sid, h)
    image_url = job["result"]["image_url"]  # type: ignore[index]
    assert _blob_count(client, sid) == 2  # upload + generated image

    r = client.delete(f"/v1/sessions/{sid}", headers=h)
    assert r.status_code == 204
    assert _blob_count(client, sid) == 0
    assert client.get(f"/v1/sessions/{sid}", headers=h).status_code == 404
    assert client.get(f"/v1/jobs/{job['job_id']}", headers=h).status_code == 404
    assert client.get(image_url).status_code == 404
    # Deleting twice is safe and reveals nothing.
    assert client.delete(f"/v1/sessions/{sid}", headers=h).status_code == 404

    c = container_of(client)
    with c.db() as db:
        rec = db.get(SessionRecord, sid)
        assert rec is not None
        assert rec.status == "deleted"
        assert rec.image_key is None
        jobrec = db.scalars(select(JobRecord).where(JobRecord.session_id == sid)).one()
        # Results are scrubbed; debugging metadata remains.
        assert jobrec.result is None
        assert jobrec.result_key is None
        assert jobrec.model_id == "mock-age-transformer"
        assert jobrec.latency_ms is not None


def test_delete_requires_token(client: TestClient) -> None:
    sid, _h = new_session(client)
    assert client.delete(f"/v1/sessions/{sid}").status_code == 404
    assert _blob_count(client, sid) == 1


def test_sessions_expire_after_ttl(client: TestClient, clock: FakeClock) -> None:
    sid, h = new_session(client)
    _aging_job(client, sid, h)
    clock.advance(seconds=3599)
    assert client.get(f"/v1/sessions/{sid}", headers=h).status_code == 200

    clock.advance(seconds=2)
    # Access is refused the moment the TTL elapses, even before the sweeper runs.
    assert client.get(f"/v1/sessions/{sid}", headers=h).status_code == 404
    assert _blob_count(client, sid) == 2

    report = sweep(container_of(client))
    assert report.expired_sessions == 1
    assert _blob_count(client, sid) == 0
    with container_of(client).db() as db:
        rec = db.get(SessionRecord, sid)
        assert rec is not None
        assert rec.status == "expired"


def test_signed_url_expires_and_rejects_tampering(client: TestClient, clock: FakeClock) -> None:
    sid, h = new_session(client)
    url = _aging_job(client, sid, h)["result"]["image_url"]  # type: ignore[index]
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    tampered = f"{parsed.path}?exp={int(q['exp'][0]) + 3600}&sig={q['sig'][0]}"
    assert client.get(tampered).status_code == 404
    assert client.get(f"{parsed.path}?exp={q['exp'][0]}&sig={'0' * 64}").status_code == 404
    assert client.get(url).status_code == 200
    clock.advance(seconds=301)
    assert client.get(url).status_code == 404


def test_metadata_purged_after_retention_window(client: TestClient, clock: FakeClock) -> None:
    sid, h = new_session(client)
    client.post(f"/v1/sessions/{sid}/jobs", json={"task": "age_estimation"}, headers=h)
    client.delete(f"/v1/sessions/{sid}", headers=h)
    c = container_of(client)

    clock.advance(days=29)
    assert sweep(c).metadata_rows_purged == 0
    clock.advance(days=2)
    assert sweep(c).metadata_rows_purged == 1
    with c.db() as db:
        assert db.get(SessionRecord, sid) is None
        assert db.scalars(select(JobRecord)).all() == []


def test_active_sessions_not_swept(client: TestClient) -> None:
    sid, h = new_session(client)
    report = sweep(container_of(client))
    assert report.expired_sessions == 0
    assert client.get(f"/v1/sessions/{sid}", headers=h).status_code == 200


def test_expired_but_unswept_session_can_still_be_deleted(
    client: TestClient, clock: FakeClock
) -> None:
    sid, h = new_session(client)
    clock.advance(seconds=3601)  # past TTL; sweeper hasn't run
    assert _blob_count(client, sid) == 1
    assert client.delete(f"/v1/sessions/{sid}", headers=h).status_code == 204
    assert _blob_count(client, sid) == 0
    assert client.delete(f"/v1/sessions/{sid}").status_code == 404  # still needs the token


def test_upload_image_link_dies_with_the_session(client: TestClient) -> None:
    r = client.post(
        "/v1/sessions",
        files={"image": ("a.jpg", make_image(), "image/jpeg")},
        data={"consent": FULL_CONSENT},
    ).json()
    url, h = r["image"]["url"], {"X-Session-Token": r["session_token"]}
    assert client.get(url).status_code == 200
    client.delete(f"/v1/sessions/{r['session_id']}", headers=h)
    assert client.get(url).status_code == 404
