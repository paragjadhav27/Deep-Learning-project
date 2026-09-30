"""Structured logging with request IDs and payload redaction.

Policy: logs may contain identifiers, error codes, sizes and timings. They must
never contain image bytes, filenames, or inference outputs (ages, scores).
The redaction processor enforces this even if a call site slips.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Keys whose values are never logged, matched case-insensitively as substrings.
REDACTED_KEY_PARTS: tuple[str, ...] = (
    "image",
    "file",
    "bytes",
    "content",
    "payload",
    "result",
    "score",
    "estimate",
    "age_years",
    "token",
    "secret",
    "signature",
    "sig",
)
# Explicit allowlist for safe keys that would otherwise match the parts above.
SAFE_KEYS: frozenset[str] = frozenset({"image_width", "image_height", "file_size_bytes"})
REDACTED = "[redacted]"


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key in ("event", "level", "timestamp", "request_id", "logger") or key in SAFE_KEYS:
            continue
        lowered = key.lower()
        is_binary = isinstance(event_dict[key], bytes | bytearray | memoryview)
        if is_binary or any(part in lowered for part in REDACTED_KEY_PARTS):
            event_dict[key] = REDACTED
    return event_dict


def _add_request_id(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    rid = request_id_var.get()
    if rid is not None:
        event_dict.setdefault("request_id", rid)
    return event_dict


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_request_id,
            redact_sensitive,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    # Quiet the uvicorn access log: it would duplicate our request log, including query
    # strings that may carry signed-URL signatures.
    logging.getLogger("uvicorn.access").disabled = True
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(logger_name=name)
    return logger
