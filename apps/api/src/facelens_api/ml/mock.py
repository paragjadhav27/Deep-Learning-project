"""MOCK providers: NOT real inference.

These exist so the product and UI can be built and tested before a licensed,
evaluated model is approved (see docs/PLAN.md section 7). Every output is marked
``is_mock=True`` in the API and must be labeled as a mock in the UI. Mocks are
refused in production by configuration validation.

Values are derived from a hash of the pixels only so that repeated calls are
deterministic and the UI can exercise different states (including "uncertain").
They carry no information about the person in the image.
"""

from __future__ import annotations

import hashlib

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from facelens_api.domain.enums import TargetAgeGroup, Task
from facelens_api.ml.interfaces import AgeEstimate, FaceInput, ModelInfo, PresentationEstimate

MOCK_LIMITATIONS = (
    "MOCK: returns placeholder values unrelated to the image content.",
    "For development and UI testing only.",
)


def _unit(image: Image.Image, salt: bytes) -> float:
    digest = hashlib.sha256(salt + image.tobytes()).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


class MockAgeEstimator:
    info = ModelInfo(
        id="mock-age-estimator",
        version="0.1.0",
        task=Task.AGE_ESTIMATION,
        is_mock=True,
        license="n/a (placeholder, no model)",
        license_approved=True,
        source_url=None,
        intended_use="Development placeholder.",
        limitations=MOCK_LIMITATIONS,
    )

    def estimate(self, face: FaceInput) -> AgeEstimate:
        center = 22 + round(_unit(face.aligned, b"age") * 45)
        return AgeEstimate(
            estimate_years=center,
            range_low_years=center - 6,
            range_high_years=center + 6,
            interval_coverage=0.8,
        )


class MockPresentationEstimator:
    info = ModelInfo(
        id="mock-presentation-estimator",
        version="0.1.0",
        task=Task.PRESENTATION_ESTIMATION,
        is_mock=True,
        license="n/a (placeholder, no model)",
        license_approved=True,
        source_url=None,
        intended_use="Development placeholder.",
        limitations=MOCK_LIMITATIONS,
    )

    def estimate(self, face: FaceInput) -> PresentationEstimate:
        f = round(0.2 + _unit(face.aligned, b"presentation") * 0.6, 3)
        return PresentationEstimate(feminine_presenting=f, masculine_presenting=round(1 - f, 3))


class MockAgeTransformer:
    """Returns a desaturated copy stamped 'MOCK', not an age transformation."""

    info = ModelInfo(
        id="mock-age-transformer",
        version="0.1.0",
        task=Task.AGE_TRANSFORMATION,
        is_mock=True,
        license="n/a (placeholder, no model)",
        license_approved=True,
        source_url=None,
        intended_use="Development placeholder.",
        limitations=(*MOCK_LIMITATIONS, "Does not alter apparent age in any way."),
        supported_target_age_groups=tuple(TargetAgeGroup),
    )

    def transform(self, face: FaceInput, target: TargetAgeGroup) -> Image.Image:
        out = ImageEnhance.Color(face.image.convert("RGB")).enhance(0.25)
        draw = ImageDraw.Draw(out)
        size = max(14, out.width // 22)
        font = ImageFont.load_default(size=size)
        label = f"MOCK - NOT A REAL TRANSFORMATION\ntarget: {target.value.replace('_', ' ')}"
        pad = size // 2
        box = draw.multiline_textbbox((pad, pad), label, font=font)
        draw.rectangle((box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad), fill=(0, 0, 0))
        draw.multiline_text((pad, pad), label, font=font, fill=(255, 255, 255))
        return out
