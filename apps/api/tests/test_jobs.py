"""Job lifecycle and the response contract for each feature."""

from __future__ import annotations

import io
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from facelens_api.domain.enums import TargetAgeGroup, Task
from facelens_api.ml.interfaces import AgeEstimate, FaceInput, InferenceError, ModelInfo
from facelens_api.ml.registry import ModelPolicyError, ModelRegistry

from conftest import container_of, new_session


def _job(client: TestClient, sid: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
    return client.post(f"/v1/sessions/{sid}/jobs", json=body, headers=headers)


def test_age_estimation_contract(client: TestClient) -> None:
    sid, h = new_session(client)
    r = _job(client, sid, h, {"task": "age_estimation"})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "succeeded"
    assert job["model"] == {"id": "mock-age-estimator", "version": "0.1.0", "is_mock": True}
    res = job["result"]
    assert set(res) == {"estimate_years", "range_years", "interval_coverage", "disclaimer_code"}
    low, high = res["range_years"]
    assert low <= res["estimate_years"] <= high
    assert res["disclaimer_code"] == "age_estimate_v1"
    # Polling returns the same view.
    again = client.get(f"/v1/jobs/{job['job_id']}", headers=h).json()
    assert again["result"] == res


def test_presentation_contract_uses_presentation_language(client: TestClient) -> None:
    sid, h = new_session(client)
    job = _job(client, sid, h, {"task": "presentation_estimation"}).json()
    assert job["status"] == "succeeded"
    res = job["result"]
    assert res["outcome"] in {"feminine_presenting", "masculine_presenting", "uncertain"}
    assert set(res["scores"]) == {"feminine_presenting", "masculine_presenting"}
    assert res["disclaimer_code"] == "presentation_estimate_v1"
    # No identity-style vocabulary anywhere in the payload.
    text = str(job).lower()
    for word in ("gender", "male", "female", "sex"):
        assert f"'{word}'" not in text
    assert job["model"]["is_mock"] is True


def test_age_transformation_contract_and_signed_image(client: TestClient) -> None:
    sid, h = new_session(client)
    body = {"task": "age_transformation", "params": {"target_age_group": "older_adult"}}
    job = _job(client, sid, h, body).json()
    assert job["status"] == "succeeded", job
    assert job["params"] == {"target_age_group": "older_adult"}
    res = job["result"]
    assert res["target_age_group"] == "older_adult"
    assert res["synthetic"] is True
    assert res["disclaimer_code"] == "synthetic_image_v1"

    img = client.get(res["image_url"])
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(img.content)) as im:
        assert im.format == "JPEG"


def test_regenerate_with_different_target_without_reupload(client: TestClient) -> None:
    sid, h = new_session(client)
    for group in ("young_adult", "middle_aged_adult", "older_adult"):
        body = {"task": "age_transformation", "params": {"target_age_group": group}}
        job = _job(client, sid, h, body).json()
        assert job["result"]["target_age_group"] == group
    assert len(client.get(f"/v1/sessions/{sid}", headers=h).json()["job_ids"]) == 3


@pytest.mark.parametrize("group", ["child", "teen"])
def test_minor_targets_disabled_by_default(client: TestClient, group: str) -> None:
    sid, h = new_session(client)
    r = _job(client, sid, h, {"task": "age_transformation", "params": {"target_age_group": group}})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "unsupported_target_age_group"
    assert "review" in err["message"]
    assert err["details"] == {"target_age_group": group}


def test_unknown_target_group_is_validation_error(client: TestClient) -> None:
    sid, h = new_session(client)
    r = _job(client, sid, h, {"task": "age_transformation", "params": {"target_age_group": "baby"}})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    assert "baby" not in r.text  # input values are never echoed


def test_unknown_task_rejected(client: TestClient) -> None:
    sid, h = new_session(client)
    r = _job(client, sid, h, {"task": "identify_person"})
    assert r.status_code == 422


def test_feature_flag_disables_task(app_factory) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_factory(feature_presentation_estimation=False)) as client:
        sid, h = new_session(client)
        r = _job(client, sid, h, {"task": "presentation_estimation"})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "feature_disabled"
        caps = client.get("/v1/models").json()
        feature = next(f for f in caps["features"] if f["task"] == "presentation_estimation")
        assert feature == {
            "task": "presentation_estimation",
            "enabled": False,
            "model": None,
            "candidate": None,
        }


def test_requires_session_token(client: TestClient) -> None:
    sid, h = new_session(client)
    assert _job(client, sid, {}, {"task": "age_estimation"}).status_code == 404
    bad = {"X-Session-Token": "wrong"}
    assert _job(client, sid, bad, {"task": "age_estimation"}).status_code == 404
    job = _job(client, sid, h, {"task": "age_estimation"}).json()
    assert client.get(f"/v1/jobs/{job['job_id']}", headers=bad).status_code == 404
    _other_sid, other_h = new_session(client)
    # One session's token can't read another session's jobs.
    assert client.get(f"/v1/jobs/{job['job_id']}", headers=other_h).status_code == 404


class _FailingAge:
    info = ModelInfo(
        id="failing",
        version="1",
        task=Task.AGE_ESTIMATION,
        is_mock=True,
        license="test",
        license_approved=True,
        source_url=None,
        intended_use="test",
        limitations=(),
    )

    def estimate(self, face: FaceInput) -> AgeEstimate:
        raise InferenceError("boom")


class _SlowAge(_FailingAge):
    def estimate(self, face: FaceInput) -> AgeEstimate:
        time.sleep(0.5)
        return AgeEstimate(30, 25, 35, 0.8)


@pytest.mark.parametrize(
    ("provider", "code", "overrides"),
    [
        (_FailingAge(), "model_error", {}),
        (_SlowAge(), "inference_timeout", {"inference_timeout_seconds": 0.05}),
    ],
    ids=["model-error", "timeout"],
)
def test_model_failures_are_reported_safely(
    app_factory,  # type: ignore[no-untyped-def]
    provider: Any,
    code: str,
    overrides: dict[str, Any],
) -> None:
    with TestClient(app_factory(**overrides)) as client:
        container_of(client).registry.age = provider
        sid, h = new_session(client)
        job = _job(client, sid, h, {"task": "age_estimation"}).json()
    assert job["status"] == "failed"
    assert job["result"] is None
    assert job["error"]["code"] == code
    assert job["error"]["retryable"] is True
    assert "boom" not in str(job)  # internal messages never leak


def test_cancel_queued_job(app_factory) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_factory()) as client:
        c = container_of(client)

        class _Hold:
            def submit(self, job_id: str) -> None:
                return None  # leave queued

            def shutdown(self) -> None:
                return None

        c.runner = _Hold()
        sid, h = new_session(client)
        job = _job(client, sid, h, {"task": "age_estimation"}).json()
        assert job["status"] == "queued"
        r = client.delete(f"/v1/jobs/{job['job_id']}", headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
        # Running the cancelled job is a no-op.
        from facelens_api.services.jobs import execute_job

        execute_job(c, job["job_id"])
        assert client.get(f"/v1/jobs/{job['job_id']}", headers=h).json()["status"] == "cancelled"
        again = client.delete(f"/v1/jobs/{job['job_id']}", headers=h)
        assert again.status_code == 409


def test_registry_refuses_unapproved_real_model() -> None:
    class _Unapproved(_FailingAge):
        info = ModelInfo(
            id="real-but-unreviewed",
            version="1",
            task=Task.AGE_ESTIMATION,
            is_mock=False,
            license="unknown",
            license_approved=False,
            source_url=None,
            intended_use="",
            limitations=(),
        )

    with pytest.raises(ModelPolicyError):
        ModelRegistry(age=_Unapproved(), presentation=None, aging=None, allow_young_targets=False)


def test_capabilities_expose_mock_status_and_targets(client: TestClient) -> None:
    caps = client.get("/v1/models").json()
    assert caps["api_version"] == "v1"
    assert all(f["enabled"] and f["model"]["is_mock"] for f in caps["features"])
    targets = {t["group"]: t for t in caps["target_age_groups"]}
    assert set(targets) == {g.value for g in TargetAgeGroup}
    assert targets["child"]["available"] is False
    assert targets["child"]["reason"]
    assert targets["older_adult"] == {"group": "older_adult", "available": True, "reason": None}
