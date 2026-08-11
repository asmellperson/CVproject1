"""AiVision 统一视觉控制面中的隔离执行服务入口。"""
from __future__ import annotations

from platform.visual_services import (
    VisualWorkerClient,
    VisualWorkerRequestError,
    filtered_response_headers,
    stream_response_bytes,
)
from platform.visual_services.client import VisualWorkerName

from fastapi import APIRouter, HTTPException, Request
from starlette.background import BackgroundTask
from starlette.responses import Response, StreamingResponse

router = APIRouter(
    prefix="/api/v2/integrations",
    tags=["visual-services"],
)

_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def _request_headers(request: Request) -> dict[str, str]:
    excluded = {"host", "content-length", "connection", "transfer-encoding"}
    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in excluded
    }


async def _proxy_visual_worker(
    request: Request,
    worker: VisualWorkerName,
    upstream_path: str,
) -> Response:
    client: VisualWorkerClient = request.app.state.visual_worker_client
    body = await request.body()
    try:
        upstream = await client.send(
            worker=worker,
            method=request.method,
            upstream_path=upstream_path,
            query=request.url.query,
            body=body,
            headers=_request_headers(request),
        )
    except VisualWorkerRequestError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc

    return StreamingResponse(
        stream_response_bytes(upstream),
        status_code=upstream.status_code,
        headers=filtered_response_headers(upstream.headers),
        background=BackgroundTask(upstream.aclose),
    )


@router.api_route(
    "/guard-room",
    methods=_PROXY_METHODS,
    include_in_schema=False,
)
async def proxy_guard_room_root(request: Request) -> Response:
    return await _proxy_visual_worker(request, "guard_room", "/")


@router.api_route(
    "/guard-room/{path:path}",
    methods=_PROXY_METHODS,
    include_in_schema=False,
)
async def proxy_guard_room(path: str, request: Request) -> Response:
    return await _proxy_visual_worker(request, "guard_room", f"/{path}")


@router.api_route(
    "/security-vlm",
    methods=_PROXY_METHODS,
    include_in_schema=False,
)
async def proxy_security_vlm_root(request: Request) -> Response:
    return await _proxy_visual_worker(request, "security_vlm", "/")


@router.api_route(
    "/security-vlm/{path:path}",
    methods=_PROXY_METHODS,
    include_in_schema=False,
)
async def proxy_security_vlm(path: str, request: Request) -> Response:
    return await _proxy_visual_worker(request, "security_vlm", f"/{path}")
