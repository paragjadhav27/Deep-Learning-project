"""Pure-ASGI middleware: request IDs, access logging, security headers, body-size guard."""

from __future__ import annotations

import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from facelens_api.api.errors import error_response
from facelens_api.domain.errors import AppError, ErrorCode
from facelens_api.log import get_logger, request_id_var

log = get_logger("facelens_api.access")
_RID_RE = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")
_MULTIPART_OVERHEAD = 64 * 1024

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-resource-policy", b"same-site"),
    (b"cache-control", b"no-store"),
    # JSON and images only: nothing here should ever execute or be framed.
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body = max_body_bytes + _MULTIPART_OVERHEAD
        self.limit_label = f"{max_body_bytes / (1024 * 1024):.0f} MB"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _RID_RE.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                raw = list(message.get("headers", []))
                present = {k.lower() for k, _ in raw}
                raw.append((b"x-request-id", rid.encode()))
                raw.extend((k, v) for k, v in SECURITY_HEADERS if k not in present)
                message["headers"] = raw
            await send(message)

        try:
            length = headers.get(b"content-length")
            if length is not None and length.isdigit() and int(length) > self.max_body:
                err = AppError(ErrorCode.FILE_TOO_LARGE, limit=self.limit_label)
                response = error_response(err.status_code, err.code.value, err.message, False)
                await response(scope, receive, send_wrapper)
                return
            await self.app(scope, receive, send_wrapper)
        finally:
            # Path only: query strings can hold signed-URL signatures.
            log.info(
                "http.request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_holder["status"],
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            request_id_var.reset(token)
