"""Face detection and alignment.

The detector only locates faces so we can (a) refuse images with no face or
several faces and (b) give models a consistent, aligned crop. It never
identifies anyone, and no face geometry is persisted.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from PIL import Image

from facelens_api.domain.errors import AppError, ErrorCode
from facelens_api.ml.artifacts import YUNET_2026MAY

Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class DetectedFace:
    x: float
    y: float
    w: float
    h: float
    score: float
    # YuNet order: right eye, left eye, nose tip, right mouth corner, left mouth corner
    # ("right"/"left" from the subject's point of view).
    landmarks: tuple[Point, Point, Point, Point, Point]

    @property
    def side(self) -> float:
        return min(self.w, self.h)

    @property
    def center(self) -> Point:
        return (self.x + self.w / 2, self.y + self.h / 2)


@dataclass(frozen=True, slots=True)
class DetectorInfo:
    id: str
    version: str
    license: str
    source_url: str


class FaceDetector(Protocol):
    info: DetectorInfo

    def detect(self, image: Image.Image) -> list[DetectedFace]: ...


class YuNetDetector:
    """OpenCV YuNet (MIT). Trained for faces of roughly 10-300 px, so large inputs are
    downscaled to ``max_side`` before detection and the boxes scaled back."""

    info = DetectorInfo(
        id="yunet",
        version="2026may",
        license=YUNET_2026MAY.license,
        source_url=YUNET_2026MAY.source,
    )

    def __init__(self, model_path: Path, score_threshold: float, max_side: int = 640) -> None:
        self._max_side = max_side
        self._lock = threading.Lock()  # FaceDetectorYN is stateful (input size)
        # Errors only: OpenCV 5 warns about unsupported DNN targets on every create().
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        self._detector = cv2.FaceDetectorYN.create(
            str(model_path), "", (320, 320), score_threshold, 0.3, 5000
        )

    def detect(self, image: Image.Image) -> list[DetectedFace]:
        rgb = image.convert("RGB")
        scale = min(1.0, self._max_side / max(rgb.size))
        if scale < 1.0:
            rgb = rgb.resize(
                (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))),
                Image.Resampling.BILINEAR,
            )
        bgr = np.ascontiguousarray(np.asarray(rgb)[:, :, ::-1])
        with self._lock:
            self._detector.setInputSize((rgb.width, rgb.height))
            _, rows = self._detector.detect(bgr)
        if rows is None:
            return []
        inv = 1.0 / scale
        faces = []
        for r in rows:
            v = [float(x) * inv for x in r[:14]]
            lm = tuple((v[i], v[i + 1]) for i in range(4, 14, 2))
            faces.append(
                DetectedFace(
                    x=v[0],
                    y=v[1],
                    w=v[2],
                    h=v[3],
                    score=float(r[14]),
                    landmarks=lm,  # type: ignore[arg-type]
                )
            )
        return faces


def require_single_face(faces: list[DetectedFace], min_face_side: int) -> DetectedFace:
    """Apply the product policy: exactly one face, large enough to be meaningful.

    Any second confident face, however small, is a rejection: the product never
    processes group photos or bystanders.
    """
    if not faces:
        raise AppError(ErrorCode.NO_FACE_DETECTED)
    if len(faces) > 1:
        raise AppError(ErrorCode.MULTIPLE_FACES_DETECTED)
    face = faces[0]
    if face.side < min_face_side:
        raise AppError(ErrorCode.FACE_TOO_SMALL)
    return face


def eye_tilt_degrees(face: DetectedFace) -> float:
    """In-plane roll of the eye line (positive = subject's left eye lower in the image)."""
    (rx, ry), (lx, ly) = face.landmarks[0], face.landmarks[1]
    return math.degrees(math.atan2(ly - ry, lx - rx))


def crop_rotated(
    image: Image.Image, center: Point, half: float, angle: float, size: int
) -> Image.Image:
    """Rotate about ``center`` by ``angle`` degrees (counter-clockwise), then square-crop.

    Areas outside the photo are filled with black rather than stretched.
    """
    cx, cy = center
    rotated = image.rotate(angle, resample=Image.Resampling.BICUBIC, center=(cx, cy))
    box = (round(cx - half), round(cy - half), round(cx + half), round(cy + half))
    return rotated.crop(box).resize((size, size), Image.Resampling.LANCZOS)


def align_crop(
    image: Image.Image,
    face: DetectedFace,
    size: int = 256,
    margin: float = 0.3,
    detector: FaceDetector | None = None,
    refine_steps: int = 2,
) -> Image.Image:
    """Eye-levelled square crop around ``face``.

    YuNet's 5-point landmarks underestimate roll on small faces (measured on the
    test portrait: a 30 degree roll reads as roughly 3-19 degrees depending on face size).
    With a detector we therefore refine: re-detect on the crop, where the face is
    large and landmarks are more accurate, and add the residual tilt.
    """
    half = max(face.w, face.h) * (0.5 + margin)
    angle = eye_tilt_degrees(face)
    crop = crop_rotated(image, face.center, half, angle, size)
    if detector is None:
        return crop
    for _ in range(refine_steps):
        found = detector.detect(crop)
        if len(found) != 1:
            break
        residual = eye_tilt_degrees(found[0])
        if abs(residual) < 1.0:
            break
        angle += residual
        crop = crop_rotated(image, face.center, half, angle, size)
    return crop
