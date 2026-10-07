from __future__ import annotations

from fastapi import APIRouter, Response

from facelens_api.api.deps import ContainerDep
from facelens_api.db.engine import ping
from facelens_api.domain.enums import Task
from facelens_api.ml.evaluations import load_evaluations, summary_for
from facelens_api.schemas.api import (
    CapabilitiesView,
    EvaluationsView,
    FaceDetectionView,
    FeatureView,
    HealthView,
    ModelCard,
    TargetGroupView,
)

router = APIRouter(tags=["meta"])


@router.get("/", include_in_schema=False)
def index(c: ContainerDep) -> dict[str, object]:
    """Signpost for people who open the API root in a browser; the app itself is the web UI."""
    links: dict[str, str] = {
        "health": "/healthz",
        "readiness": "/readyz",
        "capabilities": "/v1/models",
    }
    if c.settings.is_dev_like:
        links["docs"] = "/docs"
    return {
        "service": "FaceLens API",
        "note": "This is the backend API. Open the web app (http://localhost:3000 in development).",
        "links": links,
    }


@router.get("/healthz", response_model=HealthView)
def healthz() -> HealthView:
    """Liveness: the process is up. No dependencies checked."""
    return HealthView(status="ok")


@router.get("/readyz", response_model=HealthView, responses={503: {"model": HealthView}})
def readyz(c: ContainerDep, response: Response) -> HealthView:
    """Readiness: database, storage and the retention sweeper are all healthy."""
    checks = {"database": ping(c.engine), "storage": c.blobs.healthcheck()}
    for name, probe in c.readiness.items():
        try:
            checks[name] = probe()
        except Exception:
            checks[name] = False
    if c.settings.sweeper_enabled:
        grace = c.settings.sweep_interval_seconds * 3
        last = c.sweeper_last_run or c.started_at
        checks["retention_sweeper"] = (c.clock() - last).total_seconds() <= grace
    ok = all(checks.values())
    if not ok:
        response.status_code = 503
    return HealthView(status="ok" if ok else "degraded", checks=checks)


@router.get("/v1/models", response_model=CapabilitiesView)
def capabilities(c: ContainerDep) -> CapabilitiesView:
    """Enabled features, model cards (incl. mock status) and target age group availability."""
    features = []
    for task in Task:
        info = c.registry.info_for(task)
        card = (
            ModelCard(
                id=info.id,
                version=info.version,
                is_mock=info.is_mock,
                license=info.license,
                source_url=info.source_url,
                intended_use=info.intended_use,
                limitations=list(info.limitations),
                eval_passed=info.eval_passed,
                eval_report=info.eval_report,
            )
            if info
            else None
        )
        features.append(
            FeatureView(
                task=task,
                enabled=info is not None,
                model=card,
                # Only a mock needs explaining: which real model was evaluated, and its outcome.
                candidate=summary_for(task.value) if info and info.is_mock else None,
            )
        )
    s = c.settings
    det = c.registry.detector
    return CapabilitiesView(
        face_detection=FaceDetectionView(
            enabled=det is not None,
            model_id=det.info.id if det else None,
            version=det.info.version if det else None,
            license=det.info.license if det else None,
            source_url=det.info.source_url if det else None,
            min_face_side=s.min_face_side,
        ),
        features=features,
        target_age_groups=[
            TargetGroupView(group=t.group, available=t.available, reason=t.reason)
            for t in c.registry.target_availability()
        ],
        presentation_uncertain_threshold=c.registry.presentation_uncertain_threshold,
        session_ttl_seconds=s.session_ttl_seconds,
        max_upload_bytes=s.max_upload_bytes,
        accepted_formats=["image/jpeg", "image/png", "image/webp"],
        min_image_side=s.min_image_side,
        max_image_side=s.max_image_side,
    )


@router.get("/v1/evaluations", response_model=EvaluationsView)
def evaluations() -> EvaluationsView:
    """Measured evaluation results and release-gate outcomes for every model (PLAN section 7.3)."""
    return load_evaluations()
