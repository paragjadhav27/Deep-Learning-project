"""SAM age transformation (non-commercial; FFHQ-trained).

Pipeline: FFHQ-style alignment from YuNet's 5 landmarks -> SAM at 256 px input with the
target age channel -> 1024 px output -> warped back into the original photo with a
feathered mask, so before/after comparisons share the same framing.

The pipeline (not this provider) adds the "synthetic" watermark and file marker.
Requires the optional ``ml`` extra.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from facelens_api.domain.enums import TargetAgeGroup, Task
from facelens_api.ml.artifacts import SAM_FFHQ_AGING, resolve
from facelens_api.ml.interfaces import FaceInput, InferenceError, ModelInfo

CALIBRATION_DIR = Path(__file__).resolve().parent.parent / "calibration"
SAM_INPUT = 256
SOURCE_URL = "https://github.com/yuval-alaluf/SAM"

# Creative targets -> SAM's age conditioning (years). Minor groups exist for completeness
# but are disabled by product policy (aging_allow_young_targets=false).
TARGET_AGES: dict[TargetAgeGroup, int] = {
    TargetAgeGroup.CHILD: 8,
    TargetAgeGroup.TEEN: 16,
    TargetAgeGroup.YOUNG_ADULT: 25,
    TargetAgeGroup.MIDDLE_AGED_ADULT: 45,
    TargetAgeGroup.OLDER_ADULT: 70,
}


@dataclass(frozen=True, slots=True)
class AgingEvaluation:
    eval_report: str
    passed: bool

    @classmethod
    def load(cls, path: Path) -> AgingEvaluation | None:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            eval_report=str(data["eval_report"]), passed=bool(data["gates"]["age_transformation"])
        )


def ffhq_quad(landmarks: tuple[tuple[float, float], ...]) -> np.ndarray:
    """The FFHQ alignment quad (Karras et al.), from eyes and mouth corners.

    YuNet order: subject's right eye, left eye, nose, right mouth corner, left mouth corner,
    i.e. image-left eye first, matching FFHQ's `eye_left` / `mouth_left` (image-left).
    """
    lm = np.asarray(landmarks, dtype=np.float64)
    eye_left, eye_right, mouth_left, mouth_right = lm[0], lm[1], lm[3], lm[4]
    eye_avg = (eye_left + eye_right) * 0.5
    eye_to_eye = eye_right - eye_left
    mouth_avg = (mouth_left + mouth_right) * 0.5
    eye_to_mouth = mouth_avg - eye_avg
    x = eye_to_eye - np.flipud(eye_to_mouth) * [-1, 1]
    x /= np.hypot(*x)
    x *= max(np.hypot(*eye_to_eye) * 2.0, np.hypot(*eye_to_mouth) * 1.8)
    y = np.flipud(x) * [-1, 1]
    c = eye_avg + eye_to_mouth * 0.1
    # top-left, bottom-left, bottom-right, top-right (PIL QUAD order)
    return np.stack([c - x - y, c - x + y, c + x + y, c + x - y])


def align(image: Image.Image, quad: np.ndarray, size: int) -> Image.Image:
    """Warp the quad to a size x size square. Areas beyond the photo use edge reflection
    (as FFHQ does) rather than black, which the generator would otherwise try to explain."""
    w, h = image.size
    pad = int(np.ceil(max(0.0, -quad.min(), quad[:, 0].max() - w, quad[:, 1].max() - h))) + 4
    arr = np.pad(np.asarray(image.convert("RGB")), ((pad, pad), (pad, pad), (0, 0)), mode="reflect")
    padded = Image.fromarray(arr)
    q = (quad + pad + 0.5).flatten()
    return padded.transform((size, size), Image.Transform.QUAD, tuple(q), Image.Resampling.BILINEAR)


def paste_back(original: Image.Image, face: Image.Image, quad: np.ndarray) -> Image.Image:
    """Inverse-warp the generated square face into the original photo with a soft mask."""
    s = face.width
    tl, bl, _br, tr = quad
    # Face-space (u, v) -> source (x, y): p = tl + (u/s)(tr - tl) + (v/s)(bl - tl)
    m = np.column_stack([(tr - tl) / s, (bl - tl) / s])
    inv = np.linalg.inv(m)
    # PIL AFFINE maps output (source) pixel -> input (face) pixel.
    a, b = inv[0]
    d, e = inv[1]
    c = -(a * tl[0] + b * tl[1])
    f = -(d * tl[0] + e * tl[1])
    size = original.size
    warped = face.transform(
        size, Image.Transform.AFFINE, (a, b, c, d, e, f), Image.Resampling.BICUBIC
    )

    # Feathered ellipse over the inner face, in face space, then warped the same way.
    mask_face = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask_face).ellipse((s * 0.16, s * 0.12, s * 0.84, s * 0.95), fill=255)
    mask_face = mask_face.filter(ImageFilter.GaussianBlur(s * 0.04))
    mask = mask_face.transform(
        size, Image.Transform.AFFINE, (a, b, c, d, e, f), Image.Resampling.BILINEAR
    )
    return Image.composite(warped, original.convert("RGB"), mask)


class SAMRunner:
    def __init__(self, model_dir: Path, num_threads: int = 2) -> None:
        import torch
        from safetensors.torch import load_file

        from facelens_api.ml.vendor.sam.network import SAMNetwork

        self._torch = torch
        torch.set_num_threads(num_threads)
        state = load_file(str(resolve(SAM_FFHQ_AGING, model_dir)))  # SHA-256 verified
        net = SAMNetwork()
        net.load_state_dict(state, strict=True)
        net.eval()
        self._net = net
        self._lock = threading.Lock()

    def generate(self, aligned: Image.Image, target_age: int) -> Image.Image:
        torch = self._torch
        arr = np.asarray(
            aligned.resize((SAM_INPUT, SAM_INPUT), Image.Resampling.BILINEAR), dtype=np.float32
        )
        x = torch.from_numpy(arr.transpose(2, 0, 1).copy()) / 127.5 - 1.0
        age = torch.full((1, SAM_INPUT, SAM_INPUT), target_age / 100.0)
        x = torch.cat([x, age], 0).unsqueeze(0)
        try:
            with self._lock, torch.inference_mode():
                out = self._net(x)[0]
        except Exception as exc:
            raise InferenceError(type(exc).__name__) from None
        img = ((out.clamp(-1, 1) + 1) * 127.5).round().byte().permute(1, 2, 0).numpy()
        return Image.fromarray(img)


class SAMAgeTransformer:
    def __init__(self, runner: SAMRunner, evaluation: AgingEvaluation | None) -> None:
        self._runner = runner
        self.info = ModelInfo(
            id="sam-ffhq-aging",
            version="c1895ae",
            task=Task.AGE_TRANSFORMATION,
            is_mock=False,
            license="Code MIT; weights trained on FFHQ (CC BY-NC-SA 4.0): non-commercial only",
            license_approved=True,
            license_scope="non_commercial",
            source_url=SOURCE_URL,
            intended_use=(
                "Creative, clearly-labelled illustration of a face edited toward an age group."
            ),
            limitations=(
                "Trained on FFHQ, whose demographics are skewed; results can alter skin tone or "
                "features, measured per group in the evaluation report.",
                "Produces a synthetic image, not a prediction of anyone's appearance.",
                "Works best on frontal, well-lit faces; accessories and occlusions degrade "
                "results.",
            ),
            supported_target_age_groups=tuple(TargetAgeGroup),
            sha256=SAM_FFHQ_AGING.sha256,
            eval_report=evaluation.eval_report if evaluation else None,
            eval_passed=bool(evaluation and evaluation.passed),
        )

    def transform(self, face: FaceInput, target: TargetAgeGroup) -> Image.Image:
        if face.face is None:
            raise InferenceError("face landmarks required")
        quad = ffhq_quad(face.face.landmarks)
        aligned = align(face.image, quad, SAM_INPUT)
        generated = self._runner.generate(aligned, TARGET_AGES[target])
        return paste_back(face.image, generated, quad)


def build(model_dir: Path, num_threads: int) -> Any:
    evaluation = AgingEvaluation.load(CALIBRATION_DIR / "sam_ffhq_aging.json")
    return SAMAgeTransformer(SAMRunner(model_dir, num_threads), evaluation)
