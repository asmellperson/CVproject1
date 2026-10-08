"""AGV 公开触发入口；参数维护沿用通用 Feature 配置 API。"""
import asyncio
import time
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from AiVision.api.deps import get_current_orchestrator
from AiVision.core.logger import logger
from AiVision.features.agv_person_check.consumer import AgvPersonCheckConsumer
from AiVision.features.agv_person_check.http_adapter import CallbackError, render_body, send_callback
from AiVision.features.agv_person_check.service import CheckRequest, PersonCheckError

router = APIRouter(prefix="/api/public/agv", tags=["AGV无人运货检测"])
_ERROR_STATUS = {"busy": 409, "not_found": 404, "cancelled": 409, "timeout": 504,
                 "unavailable": 503, "inference_failed": 503, "not_configured": 409}


def get_agv_consumer(orchestrator: Annotated[Any, Depends(get_current_orchestrator)]) -> AgvPersonCheckConsumer:
    """取得运行中的 AGV 消费者，未运行时返回 503。"""
    consumer = orchestrator.consumers.get("agv_person_check")
    if consumer is None or not consumer.running:
        raise HTTPException(status_code=503, detail="AGV 检测功能未运行")
    return consumer


async def _wait_result(request: CheckRequest):
    """在请求剩余期限内异步等待判定，不让客户端取消直接取消跨线程 Future。"""
    future = asyncio.wrap_future(request.future)
    try:
        result = await asyncio.wait_for(
            asyncio.shield(future), timeout=max(0, request.deadline - time.monotonic()),
        )
        if request.error is not None:
            raise request.error
        return result
    except asyncio.TimeoutError as exc:
        raise PersonCheckError("timeout", "检测超时，未获得有效结果") from exc
    finally:
        # 超时或客户端取消时，内部 Future 仍由 Service 统一结束，避免跨线程取消竞态。
        future.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)


async def _deliver_callback(consumer: AgvPersonCheckConsumer, request: CheckRequest):
    """等待成功判定后执行配置回调，并在成功或失败后统一释放请求容量。"""
    try:
        result = await _wait_result(request)
        body = render_body(request.config.http, result, camera_key=request.camera_key, request_id=request.request_id)
        await run_in_threadpool(send_callback, request.config.http, body)
        logger.info(f"[agv_person_check] 回调成功 request_id={request.request_id}")
    except PersonCheckError as exc:
        logger.warning(f"[agv_person_check] 检测未完成，不发送判定回调 request_id={request.request_id} 原因={exc.code}")
    except CallbackError as exc:
        logger.error(f"[agv_person_check] 回调失败 request_id={request.request_id} 原因={exc}")
    finally:
        consumer.service.release(request)


@router.post("/person-check/{camera_key}")
async def person_check(
    camera_key: str, background_tasks: BackgroundTasks,
    consumer: Annotated[AgvPersonCheckConsumer, Depends(get_agv_consumer)],
):
    """无需请求体；同步返回配置模板，回调模式返回 202 和服务端请求标识。"""
    request = None
    callback_scheduled = False
    try:
        submission = asyncio.create_task(run_in_threadpool(consumer.submit, camera_key))
        try:
            request = await asyncio.shield(submission)
        except asyncio.CancelledError:
            # 等待已进入线程池的提交结束，使 finally 能释放它创建的请求。
            request = await submission
            raise
        if request.config.http.mode == "callback":
            background_tasks.add_task(_deliver_callback, consumer, request)
            callback_scheduled = True
            return JSONResponse(status_code=202, content={"request_id": request.request_id, "status": "accepted"})
        result = await _wait_result(request)
        return JSONResponse(content=render_body(
            request.config.http, result, camera_key=camera_key, request_id=request.request_id,
        ))
    except PersonCheckError as exc:
        raise HTTPException(status_code=_ERROR_STATUS[exc.code], detail=str(exc)) from exc
    finally:
        if request is not None and not callback_scheduled:
            consumer.service.release(request)
