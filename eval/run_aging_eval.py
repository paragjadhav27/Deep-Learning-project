"""SAM aging evaluation: target attainment, skin-tone preservation, integrity (per race group).

Pre-registered gates: docs/PLAN.md section 7.3 ("Aging gates"). Uses the same FairFace
data, seed, and test split as run_eval.py, and the production code path for detection,
transformation, and age estimation of the outputs. Run after `run_eval.py predict`
(it picks images whose faces passed the detection policy).

    python eval/run_aging_eval.py [--per-group 20] [--write-gate]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval import (  # noqa: E402
    ADULT_BINS,
    DATASET_ID,
    PREDICTIONS,
    RACES,
    REPO,
    SEED,
    bootstrap_ci,
    load_labels,
    split,
)

RESULTS = Path(__file__).resolve().parent / "results" / "sam_ffhq_aging_fairface.json"
GATE_OUT = REPO / "apps/api/src/facelens_api/ml/calibration/sam_ffhq_aging.json"
CACHE = Path(__file__).resolve().parent / ".data" / "aging_rows.jsonl"

# Pre-registered thresholds.
OLDER_MIN_MEAN = 55.0
YOUNG_RANGE = (18.0, 40.0)
ATTAIN_GAP = 10.0
MAX_DELTA_E = 8.0
MAX_ABS_DL = 5.0
DL_GAP = 3.0
MIN_INTEGRITY = 0.95

# Cheek patches in the 256 px FFHQ-aligned face (x0, y0, x1, y1), as fractions.
CHEEKS = ((0.22, 0.52, 0.36, 0.68), (0.64, 0.52, 0.78, 0.68))


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0-255, ...x3) -> CIELAB (D65)."""
    c = rgb.astype(np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def cheek_lab(img: object) -> np.ndarray:
    arr = np.asarray(img.convert("RGB").resize((256, 256)))  # type: ignore[attr-defined]
    patches = [arr[int(y0 * 256) : int(y1 * 256), int(x0 * 256) : int(x1 * 256)].reshape(-1, 3) for x0, y0, x1, y1 in CHEEKS]
    return srgb_to_lab(np.concatenate(patches)).mean(0)


def run(per_group: int) -> list[dict[str, object]]:
    sys.path.insert(0, str(REPO / "apps/api/src"))
    from PIL import Image

    from facelens_api.config import Settings
    from facelens_api.domain.enums import TargetAgeGroup
    from facelens_api.domain.errors import AppError
    from facelens_api.ml.artifacts import YUNET_2026MAY, resolve
    from facelens_api.ml.face import YuNetDetector
    from facelens_api.ml.pipeline import prepare_face
    from facelens_api.ml.providers.mivolo import MiVOLORunner
    from facelens_api.ml.providers.sam import TARGET_AGES, SAMRunner, align, ffhq_quad

    settings = Settings(_env_file=None)
    model_dir = REPO / "apps/api/models"
    detector = YuNetDetector(resolve(YUNET_2026MAY, model_dir), settings.face_score_threshold)
    sam = SAMRunner(model_dir, 8)
    mivolo = MiVOLORunner(model_dir, 8)

    labels, images = load_labels()
    is_cal = split(labels)
    ok = {json.loads(x)["i"] for x in PREDICTIONS.read_text(encoding="utf-8").splitlines() if x and json.loads(x)["face"] == "ok"}
    rng = np.random.default_rng(SEED)
    chosen: list[int] = []
    for race in range(len(RACES)):
        pool = [i for i, lab in enumerate(labels) if lab["race"] == race and lab["age"] in ADULT_BINS and not is_cal[i] and i in ok]
        chosen += list(rng.choice(pool, size=min(per_group, len(pool)), replace=False))

    done = {}
    if CACHE.is_file():
        for line in CACHE.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[(r["i"], r["target"])] = r
    targets = [TargetAgeGroup.YOUNG_ADULT, TargetAgeGroup.OLDER_ADULT]
    started, n = time.perf_counter(), 0
    with CACHE.open("a", encoding="utf-8") as out:
        for i in chosen:
            with Image.open(io.BytesIO(images[int(i)].as_py()["bytes"])) as im:
                img = im.convert("RGB")
            face = prepare_face(detector, img, settings.min_face_side)
            assert face.face is not None
            quad = ffhq_quad(face.face.landmarks)
            aligned = align(img, quad, 256)
            lab_in = cheek_lab(aligned)
            for target in targets:
                if (int(i), target.value) in done:
                    continue
                generated = sam.generate(aligned, TARGET_AGES[target])
                row: dict[str, object] = {"i": int(i), "race": labels[int(i)]["race"], "target": target.value}
                lab_out = cheek_lab(generated)
                row["dL"] = round(float(lab_out[0] - lab_in[0]), 3)
                row["dE"] = round(float(np.linalg.norm(lab_out - lab_in)), 3)
                try:  # attainment + integrity, through the production path on the output
                    out_face = prepare_face(detector, generated, settings.min_face_side)
                    row["face_ok"] = True
                    row["age_out"] = round(mivolo.predict(out_face).age_years, 2)
                except AppError as err:
                    row["face_ok"] = False
                    row["error"] = err.code.value
                out.write(json.dumps(row) + "\n")
                out.flush()
                n += 1
                print(f"  {n} runs  {(time.perf_counter() - started) / n:.1f} s/run", flush=True)
    rows = [json.loads(x) for x in CACHE.read_text(encoding="utf-8").splitlines() if x]
    keep = {(int(i), t.value) for i in chosen for t in targets}
    return [r for r in rows if (r["i"], r["target"]) in keep]


def analyze(rows: list[dict[str, object]], write_gate: bool) -> None:
    rng = np.random.default_rng(SEED)
    report: dict[str, object] = {
        "model": "sam-ffhq-aging@c1895ae",
        "dataset": DATASET_ID,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_runs": len(rows),
    }
    per_target: dict[str, object] = {}
    checks: list[bool] = []
    for target in ("young_adult", "older_adult"):
        groups: dict[str, dict[str, object]] = {}
        for code, race in enumerate(RACES):
            rs = [r for r in rows if r["target"] == target and r["race"] == code]
            if not rs:
                continue
            ages = np.array([r["age_out"] for r in rs if r.get("face_ok")], dtype=float)
            dl = np.array([r["dL"] for r in rs], dtype=float)
            de = np.array([r["dE"] for r in rs], dtype=float)
            groups[race] = {
                "n": len(rs),
                "integrity": round(float(np.mean([bool(r.get("face_ok")) for r in rs])), 3),
                "attained_age_mean": round(float(ages.mean()), 2) if len(ages) else None,
                "attained_age_ci95": bootstrap_ci(ages, np.mean, rng),
                "dL_mean": round(float(dl.mean()), 2),
                "dL_ci95": bootstrap_ci(dl, np.mean, rng),
                "abs_dL_mean": round(float(np.abs(dl).mean()), 2),
                "dE_mean": round(float(de.mean()), 2),
            }
        att = {k: v["attained_age_mean"] for k, v in groups.items() if v["attained_age_mean"] is not None}
        dls = {k: float(v["dL_mean"]) for k, v in groups.items()}  # type: ignore[arg-type]
        gates = {
            "attainment": (
                all(v >= OLDER_MIN_MEAN for v in att.values())  # type: ignore[operator]
                if target == "older_adult"
                else all(YOUNG_RANGE[0] <= v <= YOUNG_RANGE[1] for v in att.values())  # type: ignore[operator]
            ),
            "attainment_gap": (max(att.values()) - min(att.values())) <= ATTAIN_GAP,  # type: ignore[operator]
            "delta_e": all(float(v["dE_mean"]) <= MAX_DELTA_E for v in groups.values()),  # type: ignore[arg-type]
            "abs_dL": all(float(v["abs_dL_mean"]) <= MAX_ABS_DL for v in groups.values()),  # type: ignore[arg-type]
            "dL_gap": (max(dls.values()) - min(dls.values())) <= DL_GAP,
            "integrity": all(float(v["integrity"]) >= MIN_INTEGRITY for v in groups.values()),  # type: ignore[arg-type]
        }
        checks += list(gates.values())
        per_target[target] = {
            "by_race": groups,
            "attained_gap_years": round(max(att.values()) - min(att.values()), 2),  # type: ignore[operator]
            "dL_gap": round(max(dls.values()) - min(dls.values()), 2),
            "gates": gates,
        }
    report["targets"] = per_target
    report["gates"] = {"age_transformation": all(checks)}
    report["thresholds"] = {
        "older_min_mean": OLDER_MIN_MEAN,
        "young_range": YOUNG_RANGE,
        "attain_gap": ATTAIN_GAP,
        "max_delta_e": MAX_DELTA_E,
        "max_abs_dL": MAX_ABS_DL,
        "dL_gap": DL_GAP,
        "min_integrity": MIN_INTEGRITY,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for t, v in per_target.items():
        print(t, json.dumps(v["gates"]), "gap", v["attained_gap_years"], "dL_gap", v["dL_gap"])  # type: ignore[index]
    print("PASSED" if all(checks) else "FAILED", "->", RESULTS.relative_to(REPO))
    if write_gate:
        GATE_OUT.write_text(
            json.dumps(
                {
                    "eval_report": "eval/results/sam_ffhq_aging_fairface.json",
                    "gates": {"age_transformation": all(checks)},
                    "generated_at": report["generated_at"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--per-group", type=int, default=20)
    p.add_argument("--write-gate", action="store_true")
    args = p.parse_args()
    analyze(run(args.per_group), args.write_gate)


if __name__ == "__main__":
    main()
