"""FaceLens model evaluation: calibration, per-group metrics, and release gates.

Runs the *production* code path (YuNet face policy -> crop -> provider) over the FairFace
validation split (CC BY 4.0, HuggingFaceM4/FairFace @ pinned revision, padding 1.25).

    python eval/run_eval.py predict            # slow: runs the models, caches outputs
    python eval/run_eval.py analyze --write-calibration

Only labels and model outputs are cached (eval/.data/, git-ignored), never images.
FairFace race/gender labels are *annotator-perceived* and are used solely to slice
fairness metrics; FaceLens never predicts race.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DATA = ROOT / ".data"
DATASET_FILE = DATA / "fairface_val_1.25.parquet"
DATASET_ID = "HuggingFaceM4/FairFace@54d573cd (validation, padding 1.25)"
DATASET_SHA256 = "ce47863c011f355ef7ab63d70420d9d4b36fce03cf1621a26597955da21968bb"
PREDICTIONS = DATA / "predictions_mivolo_v2.jsonl"
RESULTS = ROOT / "results" / "mivolo_v2_fairface.json"
CALIBRATION_OUT = REPO / "apps/api/src/facelens_api/ml/calibration/mivolo_v2.json"

AGE_BINS = ["0-2", "3-9", "10-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70+"]
BIN_RANGE = [(0, 3), (3, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 101)]
ADULT_BINS = set(range(3, 9))
GENDERS = ["Male", "Female"]  # annotator-perceived
RACES = ["East Asian", "Indian", "Black", "White", "Middle Eastern", "Latino_Hispanic", "Southeast Asian"]

SEED = 20260925
CAL_FRACTION = 0.4
COVERAGE_TARGET = 0.8
PRESENTATION_THRESHOLD = 0.75  # fixed product threshold; never tuned on this data
ADULT_AGE = 18
BOOTSTRAP = 1000

# Pre-registered gates (docs/PLAN.md section 7.3).
GATE_DETECTION_GAP = 0.03
GATE_AGE_MAE_RATIO = 1.5
GATE_AGE_MIN_COVERAGE = 0.70
GATE_AGE_MAX_FALSE_BLOCK = 0.01
GATE_PRES_ACC_GAP = 0.05
GATE_PRES_ABSTAIN_RATIO = 2.0


# ---- data ----------------------------------------------------------------------------


def load_labels() -> tuple[list[dict[str, int]], object]:
    import pyarrow.parquet as pq

    if not DATASET_FILE.is_file():
        sys.exit(f"Missing {DATASET_FILE}. See eval/README.md for the pinned download.")
    table = pq.read_table(DATASET_FILE)
    labels = table.select(["age", "gender", "race"]).to_pylist()
    return labels, table.column("image")


def split(labels: list[dict[str, int]]) -> np.ndarray:
    """Stratified by race x age bin; True = calibration, False = test. Deterministic."""
    rng = np.random.default_rng(SEED)
    is_cal = np.zeros(len(labels), dtype=bool)
    strata: dict[tuple[int, int], list[int]] = {}
    for i, lab in enumerate(labels):
        strata.setdefault((lab["race"], lab["age"]), []).append(i)
    for idx in strata.values():
        idx = list(idx)
        rng.shuffle(idx)
        is_cal[idx[: round(len(idx) * CAL_FRACTION)]] = True
    return is_cal


# ---- predict (production code path) ------------------------------------------------------


def predict(limit: int | None, threads: int, batch: int) -> None:
    sys.path.insert(0, str(REPO / "apps/api/src"))
    from PIL import Image

    from facelens_api.domain.errors import AppError
    from facelens_api.ml.artifacts import YUNET_2026MAY, resolve
    from facelens_api.ml.face import YuNetDetector
    from facelens_api.ml.pipeline import prepare_face
    from facelens_api.ml.providers.mivolo import MiVOLORunner

    from facelens_api.config import Settings

    settings = Settings(_env_file=None)  # production defaults: threshold, min face size
    model_dir = REPO / "apps/api/models"
    detector = YuNetDetector(resolve(YUNET_2026MAY, model_dir), settings.face_score_threshold)
    runner = MiVOLORunner(model_dir, threads)

    labels, images = load_labels()
    n = len(labels) if limit is None else min(limit, len(labels))
    done = _done_indices()
    todo = [i for i in range(n) if i not in done]
    print(f"{len(done)} cached, {len(todo)} to run", flush=True)

    started = time.perf_counter()
    processed = 0
    with PREDICTIONS.open("a", encoding="utf-8") as out:
        for chunk in _chunks(todo, batch):
            faces, rows = [], []
            for i in chunk:
                raw = images[i].as_py()["bytes"]
                with Image.open(io.BytesIO(raw)) as im:
                    img = im.convert("RGB")
                row = {"i": i, **labels[i]}
                try:
                    faces.append(prepare_face(detector, img, settings.min_face_side))
                    row["face"] = "ok"
                except AppError as err:
                    row["face"] = err.code.value
                rows.append(row)
            outputs = iter(runner.predict_batch(faces)) if faces else iter(())
            for row in rows:
                if row["face"] == "ok":
                    o = next(outputs)
                    row |= {
                        "age_pred": round(o.age_years, 3),
                        "p_masc": round(o.masculine_presenting, 5),
                        "p_fem": round(o.feminine_presenting, 5),
                    }
                out.write(json.dumps(row) + "\n")
            out.flush()
            processed += len(chunk)
            rate = (time.perf_counter() - started) / processed
            eta_min = rate * (len(todo) - processed) / 60
            print(f"  {len(done) + processed}/{n}  {rate:.2f} s/img  ~{eta_min:.0f} min left", flush=True)


def _done_indices() -> set[int]:
    if not PREDICTIONS.is_file():
        return set()
    return {json.loads(line)["i"] for line in PREDICTIONS.read_text(encoding="utf-8").splitlines() if line}


def _chunks(items: list[int], size: int) -> Iterable[list[int]]:
    for k in range(0, len(items), size):
        yield items[k : k + size]


# ---- analysis ----------------------------------------------------------------------------


@dataclass
class Rows:
    race: np.ndarray
    gender: np.ndarray
    age_bin: np.ndarray
    face_ok: np.ndarray
    face: np.ndarray
    age_pred: np.ndarray
    p_masc: np.ndarray
    p_fem: np.ndarray
    is_cal: np.ndarray

    def where(self, mask: np.ndarray) -> Rows:
        return Rows(**{k: v[mask] for k, v in self.__dict__.items()})


def load_rows() -> Rows:
    labels, _ = load_labels()
    is_cal = split(labels)
    recs = [json.loads(x) for x in PREDICTIONS.read_text(encoding="utf-8").splitlines() if x]
    recs.sort(key=lambda r: r["i"])
    idx = np.array([r["i"] for r in recs])
    f = lambda k, d=np.nan: np.array([r.get(k, d) for r in recs], dtype=float)  # noqa: E731
    return Rows(
        race=f("race").astype(int),
        gender=f("gender").astype(int),
        age_bin=f("age").astype(int),
        face_ok=np.array([r["face"] == "ok" for r in recs]),
        face=np.array([r["face"] for r in recs]),
        age_pred=f("age_pred"),
        p_masc=f("p_masc"),
        p_fem=f("p_fem"),
        is_cal=is_cal[idx],
    )


def bin_distance(pred: np.ndarray, bins: np.ndarray) -> np.ndarray:
    lo = np.array([BIN_RANGE[b][0] for b in bins], dtype=float)
    hi = np.array([BIN_RANGE[b][1] for b in bins], dtype=float)  # exclusive
    return np.maximum.reduce([lo - pred, np.zeros_like(pred), pred - hi])


def conformal_half_width(scores: np.ndarray, coverage: float) -> float:
    n = len(scores)
    level = min(1.0, math.ceil((n + 1) * coverage) / n)
    return float(np.quantile(scores, level, method="higher"))


def bootstrap_ci(values: np.ndarray, stat: Callable[[np.ndarray], float], rng: np.random.Generator) -> list[float]:
    if len(values) == 0:
        return [math.nan, math.nan]
    boots = [stat(values[rng.integers(0, len(values), len(values))]) for _ in range(BOOTSTRAP)]
    return [round(float(np.nanpercentile(boots, 2.5)), 4), round(float(np.nanpercentile(boots, 97.5)), 4)]


def by_group(
    rows: Rows, value: Callable[[Rows], np.ndarray], rng: np.random.Generator, families: dict[str, tuple[str, list[str]]]
) -> dict[str, dict[str, dict[str, object]]]:
    """Metric = mean(value) per group, with n and a bootstrap CI."""
    out: dict[str, dict[str, dict[str, object]]] = {}
    for family, (attr, names) in families.items():
        out[family] = {}
        codes = getattr(rows, attr)
        for code, name in enumerate(names):
            sub = rows.where(codes == code)
            vals = value(sub)
            vals = vals[~np.isnan(vals)]
            if len(vals) == 0:
                continue
            out[family][name] = {
                "n": int(len(vals)),
                "value": round(float(vals.mean()), 4),
                "ci95": bootstrap_ci(vals, np.mean, rng),
            }
    return out


def spread(groups: dict[str, dict[str, dict[str, object]]]) -> dict[str, dict[str, object]]:
    res = {}
    for family, g in groups.items():
        vals = {k: float(v["value"]) for k, v in g.items()}  # type: ignore[arg-type]
        lo, hi = min(vals, key=vals.get), max(vals, key=vals.get)  # type: ignore[arg-type]
        res[family] = {"min": [lo, vals[lo]], "max": [hi, vals[hi]], "gap": round(vals[hi] - vals[lo], 4)}
    return res


def analyze(write_calibration: bool) -> None:
    rng = np.random.default_rng(SEED)
    rows = load_rows()
    n_total = len(rows.race)
    adult = np.isin(rows.age_bin, list(ADULT_BINS))
    families_all = {"race": ("race", RACES), "gender": ("gender", GENDERS)}
    families_adult = {**families_all, "age_bin": ("age_bin", AGE_BINS)}

    test = rows.where(~rows.is_cal)
    test_adult = test.where(np.isin(test.age_bin, list(ADULT_BINS)))

    # 1. Face detection (test, adults). Gate on the MISS rate; other rejections are policy.
    detection = by_group(test_adult, lambda r: (r.face == "no_face_detected").astype(float), rng, families_adult)
    detection_overall = float((test_adult.face == "no_face_detected").mean())
    rejections = {
        code: by_group(test_adult, lambda r, c=code: (r.face == c).astype(float), rng, families_all)
        for code in ("multiple_faces_detected", "face_too_small")
    }

    # 2. Age: conformal half-width from the calibration split (adults, face found).
    cal = rows.where(rows.is_cal & adult & rows.face_ok)
    cal_scores = bin_distance(cal.age_pred, cal.age_bin)
    q = conformal_half_width(cal_scores, COVERAGE_TARGET)

    ta = test_adult.where(test_adult.face_ok)
    dist = lambda r: bin_distance(r.age_pred, r.age_bin)  # noqa: E731
    age_mae = by_group(ta, dist, rng, families_adult)
    age_cov = by_group(ta, lambda r: (dist(r) <= q).astype(float), rng, families_adult)
    age_hit = by_group(ta, lambda r: (dist(r) == 0).astype(float), rng, families_adult)
    blocked = lambda r: ((r.age_pred + q) < ADULT_AGE).astype(float)  # noqa: E731
    false_block = by_group(ta, blocked, rng, families_adult)
    overall_mae = float(dist(ta).mean())

    # Minors: how often the adults-only guard fires (it should, for young children).
    tm = test.where(test.face_ok)
    guard_minors = {
        AGE_BINS[b]: round(float(blocked(tm.where(tm.age_bin == b)).mean()), 4)
        for b in (0, 1, 2)
        if (tm.age_bin == b).any()
    }

    # 3. Presentation at the fixed threshold (adults, face found).
    conf = lambda r: np.maximum(r.p_masc, r.p_fem)  # noqa: E731
    abstain = lambda r: (conf(r) < PRESENTATION_THRESHOLD).astype(float)  # noqa: E731

    def selective_correct(r: Rows) -> np.ndarray:
        pred_fem = r.p_fem > r.p_masc
        correct = (pred_fem == (r.gender == 1)).astype(float)
        correct[conf(r) < PRESENTATION_THRESHOLD] = np.nan  # abstained: not scored
        return correct

    pres_acc = by_group(ta, selective_correct, rng, families_adult)
    pres_abstain = by_group(ta, abstain, rng, families_adult)
    overall_abstain = float(abstain(ta).mean())
    sc = selective_correct(ta)
    overall_sel_acc = float(np.nanmean(sc))

    # 4. Gates.
    gates: dict[str, dict[str, object]] = {}
    det_spread = spread(detection)
    gates["detection"] = {
        "rule": f"miss-rate (no_face_detected) gap <= {GATE_DETECTION_GAP}",
        "passed": all(float(s["gap"]) <= GATE_DETECTION_GAP for s in det_spread.values()),  # type: ignore[arg-type]
        "detail": det_spread,
    }
    mae_spread = spread(age_mae)
    cov_min = {f: min(float(v["value"]) for v in g.values()) for f, g in age_cov.items()}  # type: ignore[arg-type]
    fb_max = {f: max(float(v["value"]) for v in g.values()) for f, g in false_block.items()}  # type: ignore[arg-type]
    age_checks = {
        "worst_mae_ratio": {
            f: round(float(s["max"][1]) / overall_mae, 3) if overall_mae else math.inf  # type: ignore[index]
            for f, s in mae_spread.items()
        },
        "worst_coverage": cov_min,
        "max_false_block": fb_max,
    }
    gates["age_estimation"] = {
        "rule": (
            f"worst MAE <= {GATE_AGE_MAE_RATIO}x overall; worst coverage >= {GATE_AGE_MIN_COVERAGE}; "
            f"false block <= {GATE_AGE_MAX_FALSE_BLOCK}"
        ),
        "passed": all(v <= GATE_AGE_MAE_RATIO for v in age_checks["worst_mae_ratio"].values())
        and all(v >= GATE_AGE_MIN_COVERAGE for v in cov_min.values())
        and all(v <= GATE_AGE_MAX_FALSE_BLOCK for v in fb_max.values()),
        "detail": age_checks,
    }
    acc_spread = spread(pres_acc)
    abstain_ratio = {
        f: round(max(float(v["value"]) for v in g.values()) / overall_abstain, 3) if overall_abstain else 0.0  # type: ignore[arg-type]
        for f, g in pres_abstain.items()
    }
    gates["presentation_estimation"] = {
        "rule": f"selective-accuracy gap <= {GATE_PRES_ACC_GAP}; worst abstention <= {GATE_PRES_ABSTAIN_RATIO}x overall",
        "passed": all(float(s["gap"]) <= GATE_PRES_ACC_GAP for s in acc_spread.values())  # type: ignore[arg-type]
        and all(v <= GATE_PRES_ABSTAIN_RATIO for v in abstain_ratio.values()),
        "detail": {"accuracy_spread": acc_spread, "worst_abstain_ratio": abstain_ratio},
    }
    # A tool also depends on detection: it can't pass if the detector gate fails.
    for task in ("age_estimation", "presentation_estimation"):
        gates[task]["passed"] = bool(gates[task]["passed"]) and bool(gates["detection"]["passed"])

    report = {
        "model": "mivolo-v2-face@53393526",
        "detector": "yunet@2026may",
        "dataset": DATASET_ID,
        "dataset_sha256": DATASET_SHA256,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "split": {
            "seed": SEED,
            "calibration_fraction": CAL_FRACTION,
            "n_total": n_total,
            "n_calibration_adult_faces": int(len(cal_scores)),
            "n_test_adult": int(len(test_adult.race)),
            "n_test_adult_faces": int(len(ta.race)),
        },
        "detection": {
            "overall_miss_rate": round(detection_overall, 4),
            "miss_rate": detection,
            "policy_rejections": rejections,
        },
        "age": {
            "coverage_target": COVERAGE_TARGET,
            "half_width_years": round(q, 3),
            "overall": {
                "mae_to_bin": round(overall_mae, 3),
                "bin_accuracy": round(float((dist(ta) == 0).mean()), 4),
                "coverage": round(float((dist(ta) <= q).mean()), 4),
                "false_adult_block": round(float(blocked(ta).mean()), 5),
            },
            "mae_to_bin": age_mae,
            "coverage": age_cov,
            "bin_accuracy": age_hit,
            "false_adult_block": false_block,
            "guard_fire_rate_minor_bins": guard_minors,
        },
        "presentation": {
            "threshold": PRESENTATION_THRESHOLD,
            "overall": {
                "abstention": round(overall_abstain, 4),
                "selective_accuracy": round(overall_sel_acc, 4),
            },
            "selective_accuracy": pres_acc,
            "abstention": pres_abstain,
        },
        "gates": gates,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("split", "gates")}, indent=2))
    print(f"age: q={q:.2f}y overall={report['age']['overall']}")
    print(f"presentation overall={report['presentation']['overall']}  miss rate={detection_overall:.4f}")

    if write_calibration:
        CALIBRATION_OUT.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_OUT.write_text(
            json.dumps(
                {
                    "half_width_years": round(q, 3),
                    "coverage_target": COVERAGE_TARGET,
                    "dataset": DATASET_ID,
                    "n_calibration": int(len(cal_scores)),
                    "eval_report": "eval/results/mivolo_v2_fairface.json",
                    "gates": {t: bool(gates[t]["passed"]) for t in ("age_estimation", "presentation_estimation")},
                    "generated_at": report["generated_at"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {CALIBRATION_OUT.relative_to(REPO)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("predict")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--batch", type=int, default=16)
    a = sub.add_parser("analyze")
    a.add_argument("--write-calibration", action="store_true")
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    if args.cmd == "predict":
        predict(args.limit, args.threads, args.batch)
    else:
        analyze(args.write_calibration)


if __name__ == "__main__":
    main()
