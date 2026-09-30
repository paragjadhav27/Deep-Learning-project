"""SAM aging: pure-PyTorch ops, FFHQ alignment geometry, paste-back, and the real model."""

from __future__ import annotations

import importlib.util
import math

import numpy as np
import pytest
from PIL import Image

from conftest import MODEL_DIR, portrait

torch_missing = importlib.util.find_spec("torch") is None
pytestmark = pytest.mark.skipif(torch_missing, reason="ml extra (torch) not installed")


def test_native_ops_match_reference_convolutions() -> None:
    import torch
    import torch.nn.functional as F  # noqa: N812

    from facelens_api.ml.vendor.sam.ops import fused_leaky_relu, upfirdn2d

    torch.manual_seed(0)
    x = torch.randn(2, 3, 16, 16)
    assert torch.allclose(upfirdn2d(x, torch.tensor([[1.0]])), x)
    k = torch.rand(3, 3)
    ref = F.conv2d(F.pad(x, (1, 1, 1, 1)), torch.flip(k, [0, 1]).expand(3, 1, 3, 3), groups=3)
    assert torch.allclose(upfirdn2d(x, k, pad=(1, 1)), ref, atol=1e-5)
    assert torch.allclose(upfirdn2d(x, k, down=2, pad=(1, 1)), ref[:, :, ::2, ::2], atol=1e-5)
    up = upfirdn2d(x, torch.tensor([[1.0]]), up=2)
    assert up.shape == (2, 3, 32, 32)
    assert torch.allclose(up[:, :, ::2, ::2], x)
    assert up[:, :, 1::2].abs().sum() == 0
    b = torch.randn(3)
    expected = F.leaky_relu(x + b.view(1, 3, 1, 1), 0.2) * math.sqrt(2)
    assert torch.allclose(fused_leaky_relu(x, b), expected)


def test_ffhq_quad_is_a_square_that_follows_head_roll() -> None:
    from facelens_api.ml.providers.sam import ffhq_quad

    upright = ((100.0, 100.0), (160.0, 100.0), (130.0, 130.0), (110.0, 160.0), (150.0, 160.0))
    q = ffhq_quad(upright)
    sides = [np.linalg.norm(q[i] - q[(i + 1) % 4]) for i in range(4)]
    assert max(sides) - min(sides) < 1e-6  # a square
    assert abs(q[3][1] - q[0][1]) < 1e-6  # top edge level for level eyes

    # Rotate all landmarks by 20 degrees: the quad's top edge rotates with them.
    t = math.radians(20)
    rot = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    rolled = tuple(tuple(rot @ np.array(p)) for p in upright)
    qr = ffhq_quad(rolled)  # type: ignore[arg-type]
    edge = qr[3] - qr[0]
    assert math.degrees(math.atan2(edge[1], edge[0])) == pytest.approx(20, abs=1e-6)


def test_paste_back_of_unchanged_face_reproduces_original() -> None:
    from facelens_api.ml.providers.sam import align, paste_back

    img = portrait(512)
    quad = np.array([[180.0, 60.0], [180.0, 300.0], [420.0, 300.0], [420.0, 60.0]])
    aligned = align(img, quad, 512)  # same scale: warping back is ~lossless
    restored = paste_back(img, aligned, quad)
    diff = np.abs(np.asarray(restored, dtype=float) - np.asarray(img, dtype=float))
    assert diff.mean() < 2.0  # interpolation only
    # Outside the face region the original is untouched.
    assert diff[:40, :].max() == 0


def test_real_sam_transform_end_to_end(require_models: None) -> None:
    from facelens_api.domain.enums import TargetAgeGroup
    from facelens_api.ml.artifacts import SAM_FFHQ_AGING, YUNET_2026MAY, resolve
    from facelens_api.ml.face import YuNetDetector
    from facelens_api.ml.pipeline import prepare_face
    from facelens_api.ml.providers.sam import SAMAgeTransformer, SAMRunner

    if not (MODEL_DIR / SAM_FFHQ_AGING.filename).is_file():
        pytest.skip("SAM weights not fetched (2.2 GB; fetch-models --only sam-ffhq-aging)")
    detector = YuNetDetector(resolve(YUNET_2026MAY, MODEL_DIR), 0.7)
    face = prepare_face(detector, portrait(512), 64)
    sam = SAMAgeTransformer(SAMRunner(MODEL_DIR, 4), None)
    assert sam.info.license_scope == "non_commercial"
    assert sam.info.eval_passed is False  # no evaluation file passed in

    out = sam.transform(face, TargetAgeGroup.OLDER_ADULT)
    assert out.size == face.image.size
    diff = np.abs(np.asarray(out, dtype=float) - np.asarray(face.image, dtype=float))
    # Outside the face square (the suit at the bottom of the frame) nothing changes; the
    # square itself extends above the hair, so the top rows may legitimately be edited.
    assert diff[-80:, :].max() == 0
    assert diff.mean() > 0.5  # the face region was actually edited
    # The edited photo still passes the one-face policy.
    prepare_face(detector, out, 64)
    assert isinstance(out, Image.Image)
