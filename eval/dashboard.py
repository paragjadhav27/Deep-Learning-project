"""Build the evaluation dashboard data that the API serves at ``GET /v1/evaluations``.

Reads the committed reports in eval/results/ and writes one summary file into the API
package (so it ships in the wheel and the Docker image):

    python eval/dashboard.py            # also run automatically by `analyze` / the aging eval
    python eval/dashboard.py --check    # CI: fail if the packaged file is out of date

The summary restates each pre-registered gate (docs/PLAN.md section 7.3) as criteria
with a limit, the measured worst case per group family, and the group responsible.
A model with no report is listed as "not_evaluated" with its criteria still shown.
It needs only the standard library; the limits come from the evaluation scripts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
MIVOLO_REPORT = ROOT / "results" / "mivolo_v2_fairface.json"
SAM_REPORT = ROOT / "results" / "sam_ffhq_aging_fairface.json"
OUT = REPO / "apps/api/src/facelens_api/ml/evaluations.json"

# Mirrors the GATE_* constants in run_eval.py and the thresholds in run_aging_eval.py.
# They're repeated here so this script runs without numpy; test_evaluations.py checks
# they match.
GATE_DETECTION_GAP = 0.03
GATE_AGE_MAE_RATIO = 1.5
GATE_AGE_MIN_COVERAGE = 0.70
GATE_AGE_MAX_FALSE_BLOCK = 0.01
GATE_PRES_ACC_GAP = 0.05
GATE_PRES_ABSTAIN_RATIO = 2.0
AGING = {
    "older_min_mean": 55.0,
    "young_range": (18.0, 40.0),
    "attain_gap": 10.0,
    "max_delta_e": 8.0,
    "max_abs_dL": 5.0,
    "dL_gap": 3.0,
    "min_integrity": 0.95,
}

FAMILY_LABELS = {"race": "Annotated race", "gender": "Annotated gender", "age_bin": "Annotated age"}
GROUP_LABELS = {"Latino_Hispanic": "Latino/Hispanic"}


def _group(name: str) -> str:
    return GROUP_LABELS.get(name, name)


def _families(metric: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        {
            "family": family,
            "label": FAMILY_LABELS[family],
            "groups": [
                {"group": _group(name), "n": g["n"], "value": g["value"], "ci95": g.get("ci95")}
                for name, g in groups.items()
            ],
        }
        for family, groups in metric.items()
    ]


def _metric(
    id_: str,
    label: str,
    fmt: str,
    higher_is_better: bool,
    overall: float | None,
    groups: dict[str, Any],
    gate_threshold: float | None = None,
) -> dict[str, Any]:
    """``gate_threshold``: the value no group may cross, in this metric's units (if a gate has one)."""
    return {
        "id": id_,
        "label": label,
        "format": fmt,
        "higher_is_better": higher_is_better,
        "overall": overall,
        "gate_threshold": gate_threshold,
        "families": _families(groups),
    }


def _extreme(groups: dict[str, dict[str, Any]], worst_is_max: bool) -> tuple[str, float]:
    pick = max if worst_is_max else min
    name = pick(groups, key=lambda k: float(groups[k]["value"]))
    return _group(name), float(groups[name]["value"])


def _criterion(
    id_: str,
    label: str,
    fmt: str,
    comparator: str,
    limit: float,
    by_family: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """``by_family`` rows hold the measured value for each group family (None: not evaluated)."""
    ok = (lambda v: v <= limit) if comparator == "max" else (lambda v: v >= limit)
    rows = [{**r, "passed": ok(r["measured"])} for r in by_family or []]
    worst = None
    if rows:
        worst = (max if comparator == "max" else min)(rows, key=lambda r: r["measured"])
    return {
        "id": id_,
        "label": label,
        "format": fmt,
        "comparator": comparator,
        "limit": limit,
        "measured": worst["measured"] if worst else None,
        "worst_family": worst["family"] if worst else None,
        "worst_group": worst["group"] if worst else None,
        "passed": all(r["passed"] for r in rows) if rows else None,
        "by_family": rows,
    }


def _status(criteria: list[dict[str, Any]]) -> str:
    if any(c["passed"] is None for c in criteria):
        return "not_evaluated"
    return "passed" if all(c["passed"] for c in criteria) else "failed"


def mivolo(report: dict[str, Any]) -> list[dict[str, Any]]:
    meta = {
        "report": "eval/results/mivolo_v2_fairface.json",
        "dataset": report["dataset"],
        "evaluated_at": report["generated_at"],
    }
    det, age, pres = report["detection"], report["age"], report["presentation"]
    n = report["split"]

    gates = report["gates"]

    def measured(values: dict[str, float], metric: dict[str, Any], worst_is_max: bool) -> list[dict[str, Any]]:
        """Measured values come from the report's gate detail; the group named is the one driving it."""
        return [
            {"family": f, "group": _extreme(metric[f], worst_is_max)[0], "measured": float(v)}
            for f, v in values.items()
        ]

    def gap_values(spread: dict[str, Any]) -> dict[str, float]:
        return {f: float(s["gap"]) for f, s in spread.items()}

    detection = {
        "task": "face_detection",
        "model_id": report["detector"],
        "model_name": "YuNet",
        **meta,
        "n": n["n_test_adult"],
        "criteria": [
            _criterion(
                "miss_rate_gap",
                "Gap in miss rate between groups",
                "pp",
                "max",
                GATE_DETECTION_GAP,
                measured(gap_values(gates["detection"]["detail"]), det["miss_rate"], True),
            )
        ],
        "metrics": [
            _metric("miss_rate", "Miss rate (no face found)", "percent", False, det["overall_miss_rate"], det["miss_rate"])
        ],
    }
    age_eval = {
        "task": "age_estimation",
        "model_id": report["model"],
        "model_name": "MiVOLO v2",
        **meta,
        "n": n["n_test_adult_faces"],
        "criteria": [
            _criterion(
                "mae_ratio",
                "Worst group's error vs. overall (MAE-to-bin)",
                "ratio",
                "max",
                GATE_AGE_MAE_RATIO,
                measured(gates["age_estimation"]["detail"]["worst_mae_ratio"], age["mae_to_bin"], True),
            ),
            _criterion(
                "coverage",
                "Worst group's range coverage",
                "percent",
                "min",
                GATE_AGE_MIN_COVERAGE,
                measured(gates["age_estimation"]["detail"]["worst_coverage"], age["coverage"], False),
            ),
            _criterion(
                "false_block",
                "Adults wrongly blocked as under 18",
                "percent",
                "max",
                GATE_AGE_MAX_FALSE_BLOCK,
                measured(gates["age_estimation"]["detail"]["max_false_block"], age["false_adult_block"], True),
            ),
        ],
        "metrics": [
            _metric("mae_to_bin", "Error: years outside the annotated bin (MAE-to-bin)", "years", False, age["overall"]["mae_to_bin"], age["mae_to_bin"],
                    round(GATE_AGE_MAE_RATIO * age["overall"]["mae_to_bin"], 4)),
            _metric("coverage", f"Range coverage (target {age['coverage_target']:.0%})", "percent", True, age["overall"]["coverage"], age["coverage"],
                    GATE_AGE_MIN_COVERAGE),
            _metric("bin_accuracy", "Estimate inside the annotated bin", "percent", True, age["overall"]["bin_accuracy"], age["bin_accuracy"]),
            _metric("false_adult_block", "Adults wrongly blocked as under 18", "percent", False, age["overall"]["false_adult_block"], age["false_adult_block"],
                    GATE_AGE_MAX_FALSE_BLOCK),
        ],
    }
    pres_eval = {
        "task": "presentation_estimation",
        "model_id": report["model"],
        "model_name": "MiVOLO v2",
        **meta,
        "n": n["n_test_adult_faces"],
        "criteria": [
            _criterion(
                "accuracy_gap",
                "Gap in selective accuracy between groups",
                "pp",
                "max",
                GATE_PRES_ACC_GAP,
                measured(gap_values(gates["presentation_estimation"]["detail"]["accuracy_spread"]), pres["selective_accuracy"], False),
            ),
            _criterion(
                "abstention_ratio",
                "Worst group's \"uncertain\" rate vs. overall",
                "ratio",
                "max",
                GATE_PRES_ABSTAIN_RATIO,
                measured(gates["presentation_estimation"]["detail"]["worst_abstain_ratio"], pres["abstention"], True),
            ),
        ],
        "metrics": [
            _metric("selective_accuracy", "Selective accuracy (vs. annotated perceived gender)", "percent", True, pres["overall"]["selective_accuracy"], pres["selective_accuracy"]),
            _metric("abstention", "Answered \"uncertain\"", "percent", False, pres["overall"]["abstention"], pres["abstention"],
                    round(GATE_PRES_ABSTAIN_RATIO * pres["overall"]["abstention"], 5)),
        ],
    }
    out = [detection, age_eval, pres_eval]
    for e in out:
        e["status"] = _status(e["criteria"])
    # A tool can't pass if the detector it depends on fails (same rule as run_eval.py).
    if detection["status"] != "passed":
        for e in out[1:]:
            if e["status"] == "passed":
                e["status"] = "failed"
    # The registry reads the calibration file's gate verdicts; they must agree with this summary.
    for e in out:
        verdict = gates["detection" if e["task"] == "face_detection" else e["task"]]["passed"]
        if verdict != (e["status"] == "passed"):
            raise SystemExit(f"{e['task']}: report gate verdict {verdict} disagrees with criteria")
    return out


def sam(report: dict[str, Any] | None) -> dict[str, Any]:
    t = AGING
    by_target: dict[str, dict[str, Any]] = (report or {}).get("targets", {})

    def rows(fn: Any, targets: tuple[str, ...] = ("young_adult", "older_adult")) -> list[dict[str, Any]] | None:
        if report is None:
            return None
        out = []
        for target in targets:
            if target in by_target:
                group, value = fn(by_target[target])
                out.append({"family": target, "group": group, "measured": round(float(value), 3)})
        return out

    def per_race(key: str, worst_is_max: bool) -> Any:
        def fn(tv: dict[str, Any]) -> tuple[str | None, float]:
            g = {k: v for k, v in tv["by_race"].items() if v.get(key) is not None}
            return _extreme({k: {"value": v[key]} for k, v in g.items()}, worst_is_max)

        return fn

    criteria = [
        _criterion("older_attained", "Older adult: lowest group's mean attained age", "years", "min", t["older_min_mean"],
                   rows(per_race("attained_age_mean", False), ("older_adult",))),
        _criterion("young_attained_low", "Young adult: lowest group's mean attained age", "years", "min", t["young_range"][0],
                   rows(per_race("attained_age_mean", False), ("young_adult",))),
        _criterion("young_attained_high", "Young adult: highest group's mean attained age", "years", "max", t["young_range"][1],
                   rows(per_race("attained_age_mean", True), ("young_adult",))),
        _criterion("attained_gap", "Gap in mean attained age between groups", "years", "max", t["attain_gap"],
                   rows(lambda tv: (None, tv["attained_gap_years"]))),
        _criterion("delta_e", "Skin-tone change, worst group (mean ΔE76)", "number", "max", t["max_delta_e"],
                   rows(per_race("dE_mean", True))),
        _criterion("abs_dl", "Lightness change, worst group (mean |ΔL*|)", "number", "max", t["max_abs_dL"],
                   rows(per_race("abs_dL_mean", True))),
        _criterion("dl_gap", "Gap in signed lightness change between groups (ΔL*)", "number", "max", t["dL_gap"],
                   rows(lambda tv: (None, tv["dL_gap"]))),
        _criterion("integrity", "Output still shows one detectable face, worst group", "percent", "min", t["min_integrity"],
                   rows(per_race("integrity", False))),
    ]
    metrics = []
    for target, label in (("older_adult", "older adult"), ("young_adult", "young adult")):
        if target in by_target:
            race = {k: {"n": v["n"], "value": v["attained_age_mean"], "ci95": v.get("attained_age_ci95")}
                    for k, v in by_target[target]["by_race"].items() if v["attained_age_mean"] is not None}
            metrics.append(_metric(f"attained_{target}", f"Mean attained age, target {label}", "years", True, None, {"race": race}))
    return {
        "task": "age_transformation",
        "model_id": report["model"] if report else "sam-ffhq-aging@c1895ae",
        "model_name": "SAM",
        "report": "eval/results/sam_ffhq_aging_fairface.json" if report else None,
        "dataset": report["dataset"] if report else None,
        "evaluated_at": report["generated_at"] if report else None,
        "n": report["n_runs"] if report else None,
        "status": _status(criteria),
        "criteria": criteria,
        "metrics": metrics,
    }


def build() -> dict[str, Any]:
    report = json.loads(MIVOLO_REPORT.read_text(encoding="utf-8"))
    aging = json.loads(SAM_REPORT.read_text(encoding="utf-8")) if SAM_REPORT.exists() else None
    return {
        "source": "eval/dashboard.py",
        "evaluations": [*mivolo(report), sam(aging)],
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def write() -> None:
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="fail if the packaged summary is out of date")
    args = p.parse_args()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != render():
            print(f"{OUT.relative_to(REPO)} is out of date: run `python eval/dashboard.py`", file=sys.stderr)
            return 1
        return 0
    write()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
