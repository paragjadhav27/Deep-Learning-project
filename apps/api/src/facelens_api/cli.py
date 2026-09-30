"""Operator CLI: ``facelens-api {serve,migrate,sweep,check-config,fetch-models,export-openapi}``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="facelens-api")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="Run the API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    sub.add_parser("migrate", help="Apply database migrations")
    sub.add_parser("sweep", help="Run one retention sweep now")
    sub.add_parser("check-config", help="Validate configuration and exit")
    fetch_cmd = sub.add_parser("fetch-models", help="Download pinned model files, verify SHA-256")
    fetch_cmd.add_argument("--dir", type=Path, default=None, help="Defaults to FACELENS_MODEL_DIR")
    fetch_cmd.add_argument(
        "--only", default=None, help="Comma-separated artifact names (default: all)"
    )
    export = sub.add_parser("export-openapi", help="Write the OpenAPI schema (for web types)")
    export.add_argument("--out", type=Path, default=Path("openapi.json"))
    export.add_argument("--check", action="store_true", help="Fail if the file is out of date")
    args = parser.parse_args(argv)

    if args.cmd == "export-openapi":
        return _export_openapi(args.out, check=args.check)

    if args.cmd == "fetch-models":
        # Runs before configuration exists (e.g. in a Docker build), so it doesn't need it.
        import os

        from facelens_api.ml.artifacts import ALL_ARTIFACTS, fetch

        target = args.dir or Path(os.environ.get("FACELENS_MODEL_DIR", "./models"))
        wanted = set(args.only.split(",")) if args.only else {a.name for a in ALL_ARTIFACTS}
        unknown = wanted - {a.name for a in ALL_ARTIFACTS}
        if unknown:
            print(f"Unknown artifacts: {sorted(unknown)}", file=sys.stderr)
            return 2
        for artifact in (a for a in ALL_ARTIFACTS if a.name in wanted):
            path = fetch(artifact, target)
            print(f"{artifact.name}: {path} (sha256 verified, license {artifact.license})")
        return 0

    from facelens_api.config import get_settings

    try:
        settings = get_settings()
    except ValidationError as exc:
        print(f"Invalid configuration:\n{exc}", file=sys.stderr)
        return 2

    if args.cmd == "check-config":
        print(f"Configuration OK (environment={settings.environment})")
        return 0
    if args.cmd == "migrate":
        from facelens_api.db.migrate import upgrade_to_head

        upgrade_to_head(settings.database_url)
        print("Migrations applied")
        return 0
    if args.cmd == "sweep":
        from facelens_api.main import build_container
        from facelens_api.services.sessions import sweep

        c = build_container(settings)
        try:
            print(sweep(c))
        finally:
            c.job_runner.shutdown()
            c.inference_pool.shutdown()
        return 0

    import uvicorn

    uvicorn.run(
        "facelens_api.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        proxy_headers=True,
        access_log=False,
        timeout_graceful_shutdown=30,
    )
    return 0


def _export_openapi(out: Path, *, check: bool) -> int:
    import json

    from facelens_api.config import Settings
    from facelens_api.main import create_app

    # Schema generation doesn't touch the lifespan, so no database or models are needed.
    app = create_app(Settings(_env_file=None, face_detector="none"))
    text = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != text:
            print(f"{out} is out of date: run `facelens-api export-openapi`", file=sys.stderr)
            return 1
        print(f"{out} is up to date")
        return 0
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
