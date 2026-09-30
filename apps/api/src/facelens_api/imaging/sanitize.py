"""Upload validation and sanitization.

Pipeline: magic-byte sniff -> header-only dimension check (before decoding, so
decompression bombs are rejected cheaply) -> full decode -> apply EXIF orientation
-> re-encode from pixels only. Re-encoding drops EXIF (including GPS), XMP, IPTC,
ICC profiles and any trailing data appended to the file.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError

from facelens_api.domain.errors import AppError, ErrorCode

SniffedFormat = Literal["jpeg", "png", "webp"]
_PIL_FORMATS: dict[SniffedFormat, str] = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}
OUTPUT_FORMAT = "jpeg"
OUTPUT_CONTENT_TYPE = "image/jpeg"


@dataclass(frozen=True, slots=True)
class ImageLimits:
    max_bytes: int
    min_side: int
    max_side: int


@dataclass(frozen=True, slots=True)
class SanitizedImage:
    data: bytes
    width: int
    height: int
    source_format: SniffedFormat
    pixels: Image.Image  # decoded RGB, so callers don't decode the JPEG again
    content_type: str = OUTPUT_CONTENT_TYPE


def sniff_format(data: bytes) -> SniffedFormat | None:
    """Identify the format from magic bytes only. The client's Content-Type is never trusted."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _human_size(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB" if n >= 1024 * 1024 else f"{n // 1024} KB"


def sanitize_image(data: bytes, limits: ImageLimits) -> SanitizedImage:
    if len(data) > limits.max_bytes:
        raise AppError(ErrorCode.FILE_TOO_LARGE, limit=_human_size(limits.max_bytes))
    fmt = sniff_format(data)
    if fmt is None:
        raise AppError(ErrorCode.INVALID_FILE_TYPE)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=[_PIL_FORMATS[fmt]]) as probe:
                width, height = probe.size  # header only, no pixel decode yet
                _check_dimensions(width, height, limits)
                probe.verify()
            with Image.open(io.BytesIO(data), formats=[_PIL_FORMATS[fmt]]) as img:
                img.load()
                if getattr(img, "n_frames", 1) > 1:
                    img.seek(0)  # animated WebP/PNG: use the first frame only
                oriented = ImageOps.exif_transpose(img)
                rgb = _to_rgb(oriented)
    except AppError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        if isinstance(exc, Image.DecompressionBombError | Image.DecompressionBombWarning):
            raise AppError(ErrorCode.IMAGE_TOO_LARGE, max_side=limits.max_side) from None
        raise AppError(ErrorCode.CORRUPT_IMAGE) from None
    except (OSError, SyntaxError, ValueError, EOFError):
        raise AppError(ErrorCode.CORRUPT_IMAGE) from None

    # Orientation may swap width/height; re-check against the final pixels.
    _check_dimensions(rgb.width, rgb.height, limits)
    out = io.BytesIO()
    rgb.save(out, format="JPEG", quality=92, optimize=True)  # no exif/icc args -> none written
    return SanitizedImage(
        data=out.getvalue(),
        width=rgb.width,
        height=rgb.height,
        source_format=fmt,
        pixels=rgb,
    )


def _check_dimensions(width: int, height: int, limits: ImageLimits) -> None:
    if width > limits.max_side or height > limits.max_side:
        raise AppError(ErrorCode.IMAGE_TOO_LARGE, max_side=limits.max_side)
    if width < limits.min_side or height < limits.min_side:
        raise AppError(ErrorCode.IMAGE_TOO_SMALL, min_side=limits.min_side)


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")
