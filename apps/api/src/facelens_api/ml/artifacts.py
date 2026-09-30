"""Pinned model artifacts: source, license, and SHA-256.

Weights are never committed. ``facelens-api fetch-models`` downloads them and
verifies the checksum; at startup the service refuses a file whose checksum
doesn't match. Adding an artifact here is a reviewed change: record the license
and provenance in docs/MODEL_CARDS.md in the same PR.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class ModelArtifactError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Artifact:
    name: str
    filename: str
    url: str
    sha256: str
    license: str
    source: str
    # When set, the URL serves a *source* file (e.g. a PyTorch pickle) that is verified
    # against source_sha256, then converted to `filename` (verified against sha256).
    source_sha256: str | None = None
    convert: Callable[[Path, Path], None] | None = None
    # Google Drive files need a confirmation step for large downloads.
    gdrive_id: str | None = None


YUNET_2026MAY = Artifact(
    name="yunet-2026may",
    filename="face_detection_yunet_2026may.onnx",
    url=(
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
        "face_detection_yunet_2026may.onnx"
    ),
    # Pinned on 2026-09-24 from the URL above (opencv_zoo main).
    sha256="ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
    license="MIT",
    source="https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet",
)

MIVOLO_V2 = Artifact(
    name="mivolo-v2",
    filename="mivolo_v2.safetensors",
    # Pinned revision: weights can't change underneath us.
    url=(
        "https://huggingface.co/iitolstykh/mivolo_v2/resolve/"
        "53393526c220e34cdd7b722b36d22b6f9e5f4241/model.safetensors"
    ),
    # Pinned on 2026-09-25 from the URL above.
    sha256="96efb47051c038ebeec74b73b4253c5fd000433e5afcab7deee0bd8f3fa7bf18",
    license="Apache-2.0 (HF tag); see ml/vendor/mivolo/NOTICE.md",
    source="https://huggingface.co/iitolstykh/mivolo_v2",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve(artifact: Artifact, model_dir: Path) -> Path:
    path = model_dir / artifact.filename
    if not path.is_file():
        raise ModelArtifactError(
            f"Model file {path} is missing. Run `facelens-api fetch-models` first."
        )
    actual = sha256_file(path)
    if actual != artifact.sha256:
        raise ModelArtifactError(f"Checksum mismatch for {artifact.name}: refusing to load")
    return path


def _gdrive_url(file_id: str, timeout: float) -> str:
    """Large Google Drive files sit behind a confirmation page carrying a one-time uuid."""
    base = f"https://drive.usercontent.google.com/download?id={file_id}&export=download"
    req = urllib.request.Request(base, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        page = resp.read(200_000).decode("utf-8", "replace")
    match = re.search(r'name="uuid" value="([^"]+)"', page)
    return f"{base}&confirm=t" + (f"&uuid={match.group(1)}" if match else "")


def _download(url: str, dest: Path, timeout: float) -> None:
    if not url.startswith("https://"):
        raise ModelArtifactError("artifact URLs must be https")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})  # noqa: S310
    with dest.open("wb") as out, urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        while chunk := resp.read(1 << 20):
            out.write(chunk)


def fetch(artifact: Artifact, model_dir: Path, *, timeout: float = 60) -> Path:
    model_dir.mkdir(parents=True, exist_ok=True)
    target = model_dir / artifact.filename
    if target.is_file() and sha256_file(target) == artifact.sha256:
        return target
    fd, tmp_name = tempfile.mkstemp(dir=model_dir, prefix=".download-")
    os.close(fd)
    tmp = Path(tmp_name)
    converted = tmp.with_suffix(".converted")
    try:
        url = _gdrive_url(artifact.gdrive_id, timeout) if artifact.gdrive_id else artifact.url
        _download(url, tmp, timeout)
        if artifact.convert is not None:
            if sha256_file(tmp) != artifact.source_sha256:
                raise ModelArtifactError(f"Downloaded {artifact.name} failed checksum verification")
            artifact.convert(tmp, converted)
            produced = converted
        else:
            produced = tmp
        if sha256_file(produced) != artifact.sha256:
            raise ModelArtifactError(f"{artifact.name} failed checksum verification")
        os.replace(produced, target)
    finally:
        tmp.unlink(missing_ok=True)
        converted.unlink(missing_ok=True)
    return target


def convert_sam_checkpoint(src: Path, dst: Path) -> None:
    """SAM pickle -> safetensors, keeping only the tensors the inference network needs.

    ``weights_only=True`` refuses arbitrary pickled objects, so a tampered checkpoint
    can't execute code even before its checksum is checked.
    """
    import torch
    from safetensors.torch import save_file

    ckpt = torch.load(src, map_location="cpu", weights_only=True)
    state = ckpt["state_dict"]
    keep = ("encoder.", "pretrained_encoder.", "decoder.")
    tensors = {k: v.contiguous().clone() for k, v in state.items() if k.startswith(keep)}
    tensors["latent_avg"] = ckpt["latent_avg"].contiguous().clone()
    save_file(tensors, str(dst))


SAM_FFHQ_AGING = Artifact(
    name="sam-ffhq-aging",
    filename="sam_ffhq_aging.safetensors",
    url="https://drive.google.com/file/d/1XyumF6_fdAxFmxpFcmPf-q84LU_22EMC",  # SAM README link
    gdrive_id="1XyumF6_fdAxFmxpFcmPf-q84LU_22EMC",
    # Pinned on 2026-09-25: the authors' pickle, then our deterministic safetensors conversion.
    source_sha256="6fbd6085e2e6001f51f6dee896ae5ba7bd6c3fab5c06fadba75f2a12188ba143",
    sha256="5066dd4c1ca3609ae6b3b076f9da43834e811d46b09abea711ade57bf93b9ff1",
    license="Code MIT; weights trained on FFHQ (CC BY-NC-SA 4.0): non-commercial only",
    source="https://github.com/yuval-alaluf/SAM",
    convert=convert_sam_checkpoint,
)

ALL_ARTIFACTS: tuple[Artifact, ...] = (YUNET_2026MAY, MIVOLO_V2, SAM_FFHQ_AGING)
