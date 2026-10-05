"""Evaluation dashboard data: served results agree with the reports and the enforced gates."""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from facelens_api.ml.evaluations import EVALUATIONS_FILE, load_evaluations

CALIBRATION = EVALUATIONS_FILE.parent / "calibration"
REPO = Path(__file__).resolve().parents[3]
EVAL = REPO / "eval"


def _dashboard() -> ModuleType:
    if not (EVAL / "dashboard.py").exists():
        pytest.skip("eval/ is not available (installed package)")
    spec = importlib.util.spec_from_file_location("eval_dashboard", EVAL / "dashboard.py")
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constants(path: Path) -> dict[str, object]:
    """Module-level constants, read without importing (the eval scripts need numpy/torch)."""
    out: dict[str, object] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            with contextlib.suppress(ValueError):
                out[node.targets[0].id] = ast.literal_eval(node.value)
    return out


def test_evaluations_endpoint_reports_every_tool(client: TestClient) -> None:
    body = client.get("/v1/evaluations").json()
    status = {e["task"]: e["status"] for e in body["evaluations"]}
    assert status == {
        "face_detection": "passed",
        "age_estimation": "failed",
        "presentation_estimation": "failed",
        "age_transformation": "not_evaluated",
    }
    age = next(e for e in body["evaluations"] if e["task"] == "age_estimation")
    failed = {
        c["id"]: (c["worst_group"], c["measured"]) for c in age["criteria"] if c["passed"] is False
    }
    assert failed == {
        "mae_ratio": ("40-49", 1.551),
        "coverage": ("40-49", 0.6785),
        "false_block": ("Black", 0.0279),
    }
    families = {f["family"] for m in age["metrics"] for f in m["families"]}
    assert families == {"race", "gender", "age_bin"}
    aging = next(e for e in body["evaluations"] if e["task"] == "age_transformation")
    assert aging["criteria"]
    assert all(c["measured"] is None and c["passed"] is None for c in aging["criteria"])


def test_capabilities_explain_why_tools_run_on_mocks(client: TestClient) -> None:
    caps = client.get("/v1/models").json()
    by_task = {f["task"]: f for f in caps["features"]}
    for task, model_id, status in (
        ("age_estimation", "mivolo-v2-face@53393526", "failed"),
        ("presentation_estimation", "mivolo-v2-face@53393526", "failed"),
        ("age_transformation", "sam-ffhq-aging@c1895ae", "not_evaluated"),
    ):
        feature = by_task[task]
        assert feature["model"]["is_mock"] is True
        assert feature["candidate"]["model_id"] == model_id
        assert feature["candidate"]["status"] == status
        assert "metrics" not in feature["candidate"]  # the compact summary only


def test_reported_status_matches_the_gates_the_registry_enforces() -> None:
    gates = json.loads((CALIBRATION / "mivolo_v2.json").read_text(encoding="utf-8"))["gates"]
    status = {e.task: e.status for e in load_evaluations().evaluations}
    for task, passed in gates.items():
        assert (status[task] == "passed") is passed
    sam_gate = CALIBRATION / "sam_ffhq_aging.json"
    if sam_gate.exists():
        passed = json.loads(sam_gate.read_text(encoding="utf-8"))["gates"]["age_transformation"]
        assert (status["age_transformation"] == "passed") is passed
    else:
        assert status["age_transformation"] == "not_evaluated"


def test_packaged_summary_is_up_to_date_with_the_reports() -> None:
    dashboard = _dashboard()
    assert EVALUATIONS_FILE.read_text(encoding="utf-8") == dashboard.render(), (
        "run `python eval/dashboard.py`"
    )


def test_dashboard_limits_match_the_preregistered_gates() -> None:
    dashboard = _dashboard()
    run_eval = _constants(EVAL / "run_eval.py")
    for name in (
        "GATE_DETECTION_GAP",
        "GATE_AGE_MAE_RATIO",
        "GATE_AGE_MIN_COVERAGE",
        "GATE_AGE_MAX_FALSE_BLOCK",
        "GATE_PRES_ACC_GAP",
        "GATE_PRES_ABSTAIN_RATIO",
    ):
        assert getattr(dashboard, name) == run_eval[name], name
    aging = _constants(EVAL / "run_aging_eval.py")
    expected = {
        "older_min_mean": aging["OLDER_MIN_MEAN"],
        "young_range": aging["YOUNG_RANGE"],
        "attain_gap": aging["ATTAIN_GAP"],
        "max_delta_e": aging["MAX_DELTA_E"],
        "max_abs_dL": aging["MAX_ABS_DL"],
        "dL_gap": aging["DL_GAP"],
        "min_integrity": aging["MIN_INTEGRITY"],
    }
    assert expected == dashboard.AGING


def test_aging_summary_from_a_report(tmp_path: Path) -> None:
    """When the aging evaluation has run, its criteria carry measured values and verdicts."""
    dashboard = _dashboard()
    group = {
        "n": 20,
        "integrity": 1.0,
        "attained_age_mean": 60.0,
        "attained_age_ci95": [55.0, 65.0],
        "dL_mean": 1.0,
        "abs_dL_mean": 2.0,
        "dE_mean": 4.0,
    }
    young = {**group, "attained_age_mean": 30.0}
    report = {
        "model": "sam-ffhq-aging@c1895ae",
        "dataset": "d",
        "generated_at": "2026-10-01T00:00:00+00:00",
        "n_runs": 80,
        "targets": {
            "young_adult": {
                "by_race": {"A": young, "B": {**young, "dE_mean": 9.0}},
                "attained_gap_years": 0.0,
                "dL_gap": 0.0,
            },
            "older_adult": {
                "by_race": {"A": group, "B": group},
                "attained_gap_years": 0.0,
                "dL_gap": 0.0,
            },
        },
    }
    out = dashboard.sam(report)
    assert out["status"] == "failed"
    delta_e = next(c for c in out["criteria"] if c["id"] == "delta_e")
    assert (delta_e["passed"], delta_e["measured"], delta_e["worst_group"]) == (False, 9.0, "B")
    assert all(c["passed"] for c in out["criteria"] if c["id"] != "delta_e")
    assert [m["id"] for m in out["metrics"]] == ["attained_older_adult", "attained_young_adult"]
