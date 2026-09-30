from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from facelens_api.container import Container
from facelens_api.domain.errors import AppError, ErrorCode


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_db(c: ContainerDep) -> Iterator[Session]:
    with c.db.begin() as db:
        yield db


DbDep = Annotated[Session, Depends(get_db)]
SessionToken = Annotated[str | None, Header(alias="X-Session-Token")]


def client_key(request: Request) -> str:
    # Behind a proxy, configure uvicorn --proxy-headers/--forwarded-allow-ips so this is
    # the real client address. Never trust X-Forwarded-For directly here.
    return request.client.host if request.client else "unknown"


def rate_limit(c: Container, request: Request, bucket: str, limit: int) -> None:
    retry_after = c.limiter.hit(f"{bucket}:{client_key(request)}", limit)
    if retry_after is not None:
        raise AppError(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(retry_after)})
