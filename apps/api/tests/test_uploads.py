"""Upload validation, sanitization, and consent enforcement."""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from facelens_api.domain.errors import AppError, ErrorCode
from facelens_api.imaging.sanitize import ImageLimits, sanitize_image, sniff_format

from conftest import container_of, make_image, upload

LIMITS = ImageLimits(max_bytes=1024 * 1024, min_side=64, max_side=1024)


def _exif_with_gps() -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"  # Make
    exif[0x0112] = 6  # Orientation: rotate 90 CW on display
    gps = {1: "N", 2: (51.0, 30.0, 0.0), 3: "W", 4: (0.0, 7.0, 0.0)}
    exif[0x8825] = gps  # GPS IFD
    return exif


def test_successful_upload_contract(client: TestClient) -> None:
    r = upload(client)
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"session_id", "session_token", "expires_at", "image", "face_check"}
    image = body["image"]
    assert {k: image[k] for k in ("width", "height", "format", "metadata_stripped")} == {
        "width": 256,
        "height": 256,
        "format": "jpeg",
        "metadata_stripped": True,
    }
    assert body["face_check"] == {"status": "not_checked"}
    assert r.headers["x-request-id"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]

    # The signed "before" link serves the sanitized image, and only while it's valid.
    before = client.get(image["url"])
    assert before.status_code == 200
    assert before.headers["content-type"] == "image/jpeg"
    assert client.get(image["url"].replace("sig=", "sig=0")).status_code == 404


@pytest.mark.parametrize(
    ("data", "code", "status"),
    [
        (b"hello, not an image", "invalid_file_type", 415),
        (make_image("GIF"), "invalid_file_type", 415),
        (make_image("BMP"), "invalid_file_type", 415),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "invalid_file_type", 415),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 64, "corrupt_image", 422),
        (make_image(size=(40, 40)), "image_too_small", 422),
        (make_image("PNG", size=(5000, 200)), "image_too_large", 422),
    ],
    ids=["text", "gif", "bmp", "svg", "truncated-jpeg", "too-small", "too-large-dims"],
)
def test_rejects_invalid_uploads(client: TestClient, data: bytes, code: str, status: int) -> None:
    r = upload(client, data)
    assert r.status_code == status, r.text
    err = r.json()["error"]
    assert err["code"] == code
    assert err["message"]
    assert err["request_id"] == r.headers["x-request-id"]


def test_content_type_header_is_not_trusted(client: TestClient) -> None:
    # A text payload claiming to be a JPEG is still rejected.
    assert upload(client, b"MZ\x90\x00 fake exe", content_type="image/jpeg").status_code == 415
    # A real PNG labelled as text is accepted (content is sniffed).
    assert upload(client, make_image("PNG"), content_type="text/plain").status_code == 201


def test_rejects_file_over_byte_limit(app_factory) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app_factory(max_upload_bytes=2048)) as client:
        big = make_image("PNG", size=(512, 512), compress_level=0)
        r = upload(client, big)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "file_too_large"


@pytest.mark.parametrize(
    "consent",
    [
        None,
        "not json",
        json.dumps({"has_permission": True, "is_adult": True}),
        json.dumps({"has_permission": True, "is_adult": False, "accepts_limitations": True}),
        json.dumps({"has_permission": False, "is_adult": True, "accepts_limitations": True}),
    ],
    ids=["missing", "malformed", "incomplete", "not-adult", "no-permission"],
)
def test_consent_required(client: TestClient, consent: str | None) -> None:
    r = upload(client, consent=consent)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "consent_required"


def test_metadata_is_stripped_and_orientation_applied(client: TestClient) -> None:
    raw = make_image("JPEG", size=(300, 200), exif=_exif_with_gps().tobytes())
    with Image.open(io.BytesIO(raw)) as original:
        assert original.getexif().get(0x8825) is not None  # precondition: GPS present

    r = upload(client, raw, filename="IMG_home_address.jpg")
    assert r.status_code == 201
    body = r.json()
    # Orientation 6 means the displayed image is portrait.
    assert (body["image"]["width"], body["image"]["height"]) == (200, 300)

    c = container_of(client)
    stored = c.blobs.get(f"sessions/{body['session_id']}/upload.jpg")
    assert b"SecretCameraMaker" not in stored
    assert b"IMG_home_address" not in stored
    with Image.open(io.BytesIO(stored)) as img:
        assert len(img.getexif()) == 0
        assert "icc_profile" not in img.info
        assert "exif" not in img.info


def test_png_with_alpha_is_flattened() -> None:
    raw = make_image("PNG", mode="RGBA", size=(128, 128))
    out = sanitize_image(raw, LIMITS)
    assert out.source_format == "png"
    with Image.open(io.BytesIO(out.data)) as img:
        assert img.mode == "RGB"
        assert img.format == "JPEG"


def test_webp_supported() -> None:
    out = sanitize_image(make_image("WEBP"), LIMITS)
    assert out.source_format == "webp"


def test_trailing_payload_is_dropped() -> None:
    raw = make_image() + b"<script>alert(1)</script>"
    out = sanitize_image(raw, LIMITS)
    assert b"<script>" not in out.data


def test_sniff_format() -> None:
    assert sniff_format(make_image("JPEG")) == "jpeg"
    assert sniff_format(make_image("PNG")) == "png"
    assert sniff_format(make_image("WEBP")) == "webp"
    assert sniff_format(b"RIFF\x00\x00\x00\x00WAVE") is None
    assert sniff_format(b"") is None


def test_dimension_check_happens_before_decode() -> None:
    # Claims huge dimensions in the header; must fail on the header, not by decoding.
    with pytest.raises(AppError) as exc:
        sanitize_image(make_image("PNG", size=(2000, 2000)), LIMITS)
    assert exc.value.code is ErrorCode.IMAGE_TOO_LARGE
