"""Load test: N concurrent virtual users running the real flow against a FaceLens API.

Each iteration: upload (consent + photo) -> start a job -> poll to completion -> delete.
Reports latency percentiles per step and the error rate, and exits non-zero when the
thresholds are exceeded, so it can gate a deployment.

    python ops/loadtest.py --base http://127.0.0.1:8000 --users 10 --duration 60 \
        --task age_estimation --image apps/web/e2e/fixtures/portrait.jpg

Note: the API rate-limits per client IP. Run it against an environment configured with
high limits (as below), or it will measure the rate limiter rather than the service.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

CONSENT = json.dumps({"has_permission": True, "is_adult": True, "accepts_limitations": True})


async def user(
    client: httpx.AsyncClient, image: bytes, task: str, deadline: float, stats: dict[str, list[float]]
) -> None:
    body: dict[str, object] = {"task": task}
    if task == "age_transformation":
        body["params"] = {"target_age_group": "older_adult"}
    while time.perf_counter() < deadline:
        try:
            t0 = time.perf_counter()
            r = await client.post(
                "/v1/sessions",
                files={"image": ("p.jpg", image, "image/jpeg")},
                data={"consent": CONSENT},
            )
            stats["upload"].append(time.perf_counter() - t0)
            if r.status_code != 201:
                stats[f"error_upload_{r.status_code}"].append(1)
                continue
            s = r.json()
            h = {"X-Session-Token": s["session_token"]}

            t1 = time.perf_counter()
            r = await client.post(f"/v1/sessions/{s['session_id']}/jobs", json=body, headers=h)
            if r.status_code != 202:
                stats[f"error_job_{r.status_code}"].append(1)
                continue
            job = r.json()
            while job["status"] in ("queued", "running"):
                await asyncio.sleep(0.25)
                job = (await client.get(f"/v1/jobs/{job['job_id']}", headers=h)).json()
            stats["job_end_to_end"].append(time.perf_counter() - t1)
            if job["status"] != "succeeded":
                stats[f"error_job_{job.get('error', {}).get('code')}"].append(1)

            t2 = time.perf_counter()
            r = await client.delete(f"/v1/sessions/{s['session_id']}", headers=h)
            stats["delete"].append(time.perf_counter() - t2)
            if r.status_code != 204:
                stats[f"error_delete_{r.status_code}"].append(1)
            stats["iterations"].append(1)
        except httpx.HTTPError as exc:
            stats[f"error_transport_{type(exc).__name__}"].append(1)


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--users", type=int, default=10)
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--task", default="age_estimation")
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    ap.add_argument("--max-upload-p95", type=float, default=2.0, help="seconds")
    args = ap.parse_args()

    image = args.image.read_bytes()
    stats: dict[str, list[float]] = defaultdict(list)
    deadline = time.perf_counter() + args.duration
    limits = httpx.Limits(max_connections=args.users * 2)
    async with httpx.AsyncClient(base_url=args.base, timeout=120, limits=limits) as client:
        await asyncio.gather(*(user(client, image, args.task, deadline, stats) for _ in range(args.users)))

    iterations = len(stats["iterations"])
    errors = sum(len(v) for k, v in stats.items() if k.startswith("error_"))
    attempts = iterations + errors
    report: dict[str, object] = {
        "users": args.users,
        "duration_s": args.duration,
        "task": args.task,
        "iterations": iterations,
        "throughput_per_s": round(iterations / args.duration, 2),
        "error_rate": round(errors / attempts, 4) if attempts else 1.0,
        "errors": {k: len(v) for k, v in stats.items() if k.startswith("error_")},
    }
    for step in ("upload", "job_end_to_end", "delete"):
        v = stats[step]
        if v:
            report[step] = {
                "p50_ms": round(statistics.median(v) * 1000),
                "p95_ms": round(pct(v, 95) * 1000),
                "max_ms": round(max(v) * 1000),
            }
    print(json.dumps(report, indent=2))
    ok = report["error_rate"] <= args.max_error_rate and (  # type: ignore[operator]
        not stats["upload"] or pct(stats["upload"], 95) <= args.max_upload_p95
    )
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
