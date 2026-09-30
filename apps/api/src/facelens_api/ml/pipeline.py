"""Shared face-preparation step used at upload time and before every inference."""

from __future__ import annotations

from PIL import Image

from facelens_api.ml.face import FaceDetector, align_crop, require_single_face
from facelens_api.ml.interfaces import FaceInput

ALIGNED_SIZE = 256


def prepare_face(
    detector: FaceDetector | None, image: Image.Image, min_face_side: int
) -> FaceInput:
    """Detect exactly one face and produce the aligned crop.

    Raises AppError (no_face_detected / multiple_faces_detected / face_too_small).
    With detection disabled (development only) the whole image is used.
    """
    rgb = image.convert("RGB")
    if detector is None:
        return FaceInput(image=rgb, aligned=rgb.resize((ALIGNED_SIZE, ALIGNED_SIZE)), face=None)
    face = require_single_face(detector.detect(rgb), min_face_side)
    aligned = align_crop(rgb, face, ALIGNED_SIZE, detector=detector)
    return FaceInput(image=rgb, aligned=aligned, face=face)
