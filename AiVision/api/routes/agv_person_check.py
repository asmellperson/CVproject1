"""AGV 公开触发入口与登录会话下的请求状态查询。"""
import asyncio
import time
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from auth.auth import get_current_user
from auth.feature_permissions import require_feature_access
from AiVision.api.deps import get_camera_config_manager, get_current_orchestrator, get_optional_orchestrator
from AiVision.api.routes.cameras import get_camera_for_user
from AiVision.core.logger import logger
from AiVision.features.agv_person_check.consumer import AgvPersonCheckConsumer
from AiVision.features.agv_person_check.http_adapter import CallbackError, render_body, send_callback
from AiVision.features.agv_person_check.schema import AgvMonitorStatus
from AiVision.features.agv_person_check.service import CheckRequest, PersonCheckError

router = APIRouter(prefix="/api/public/agv", tags=["AGV无人运货检测"])
status_router = APIRouter(prefix="/api/agv-person-check", tags=["AGV无人运货检测"])
_ERROR_STATUS = {"busy": 409, "not_found": 404, "cancelled": 409, "timeout": 504,
                 "unavailable": 503, "inference_failed": 503, "not_configured": 409}


def get_agv_consumer(orchestrator: Annotated[Any, Depends(get_current_orchestrator)]) -> AgvPersonCheckConsumer:
    """取得运行中的 AGV 消费者，未运行时返回 503。"""
    consumer = orchestrator.consumers.get("agv_person_check")
    if consumer is None or not consumer.running:
        raise HTTPException(status_code=503, detail="AGV 检测功能未运行")
    return consumer


@status_router.get("/cameras/{key}/status", response_model=AgvMonitorStatus)
def status(key: str, user=Depends(get_current_user), manager=Depends(get_camera_config_manager),
           orchestrator=Depends(get_optional_orchestrator)):
    """复用摄像头及功能权限，只读取请求快照，不取图或触发采样。"""
    camera = get_camera_for_user(manager, key, user)
    require_feature_access(user, "agv_person_check", camera["department"])
    consumer = orchestrator.consumers.get("agv_person_check") if orchestrator is not None else None
    active, latest = consumer.service.monitor.status(camera["camera_id"]) if consumer is not None else (None, None)
    result = AgvMonitorStatus(camera_key=key, state="waiting", active_request=active, latest_result=latest)
    if not camera["enabled"] or not camera["functions"].get("agv_person_check", False):
        result.state = "disabled"
    elif consumer is None or not consumer.running:
        result.state = "unavailable"
    elif not consumer.is_camera_active(key):
        result.state = "offline"
    elif active is not None:
        result.state = "detecting" if active.state == "detecting" else "returning"
    return result


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
        consumer.service.monitor.delivery(request, state="sending", body=body)
        status_code = await run_in_threadpool(send_callback, request.config.http, body)
        consumer.service.monitor.delivery(request, state="succeeded", status_code=status_code)
        logger.info(f"[agv_person_check] 回调成功 request_id={request.request_id}")
    except PersonCheckError as exc:
        consumer.service.fail(request, exc)
        logger.warning(f"[agv_person_check] 检测未完成，不发送判定回调 request_id={request.request_id} 原因={exc.code}")
    except CallbackError as exc:
        consumer.service.monitor.delivery(request, state="failed", status_code=exc.status_code, error=str(exc))
        logger.error(f"[agv_person_check] 回调失败 request_id={request.request_id} 原因={exc}")
    except asyncio.CancelledError:
        consumer.service.monitor.delivery(request, state="failed", error="回调任务已取消，回传状态未确认")
        raise
    except Exception as exc:  # noqa: BLE001 -- 回调线程异常不能让监控永久停留在发送中。
        consumer.service.monitor.delivery(request, state="failed", error=f"回调处理异常：{type(exc).__name__}")
        logger.exception(f"[agv_person_check] 回调处理异常 request_id={request.request_id}")
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
        body = render_body(
            request.config.http, result, camera_key=camera_key, request_id=request.request_id,
        )
        response = JSONResponse(content=body)
        consumer.service.monitor.delivery(request, state="ready", body=body, status_code=response.status_code)
        return response
    except PersonCheckError as exc:
        if request is not None:
            consumer.service.fail(request, exc)
            consumer.service.monitor.delivery(request, state="ready", body={"detail": str(exc)},
                                              status_code=_ERROR_STATUS[exc.code])
        raise HTTPException(status_code=_ERROR_STATUS[exc.code], detail=str(exc)) from exc
    finally:
        if request is not None and not callback_scheduled:
            consumer.service.release(request)
