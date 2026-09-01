# 文件说明：定义运行时的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
api/v2/runtime.py
运行状态、健康检查接口。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_admin
from api.deps import get_current_orchestrator
from core.settings import settings
from core.system_config import system_config_service


router = APIRouter(prefix="/api/v2/runtime", tags=["runtime"])


# 功能：定义 `ExceptionAlertSettings` 类，封装运行时相关的状态、约束与操作
# 参数：
#   - `wechat_enable`（bool）：`wechat_enable` 对应的业务输入值
#   - `wechat_user`（str）：`wechat_user` 对应的业务输入值
#   - `repeat_interval_minutes`（int）：`repeat_interval_minutes` 对应的时间间隔或时长
# 返回：ExceptionAlertSettings；返回新建的 `ExceptionAlertSettings` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ExceptionAlertSettings(BaseModel):
    wechat_enable: bool = False
    wechat_user: str = ""
    repeat_interval_minutes: int = 60


# 功能：健康检查端点；输入与输出详见下方说明
# 参数：
#   - `orchestrator`（未显式标注）：`orchestrator` 对应的业务输入值；默认值为 `Depends(get_current_orchestrator)`
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/health')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`orchestrator.runtime_status`、`bool`、`status.get`、`len`、`inference.get`、`worker_status.get`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/health")
def health(orchestrator=Depends(get_current_orchestrator)) -> dict:
    """健康检查端点。

    反映真实就绪状态供冷启动脚本与监控判定：
        ready = orchestrator 已 start 且至少 1 个推理模型在跑
    """
    status = orchestrator.runtime_status()
    started = bool(status.get("started", False))
    models = status.get("running_models") or []
    model_ready = len(models) > 0
    ready = started and model_ready
    inference = status.get("inference") or {}
    worker_status = inference.get("workers") or {}
    return {
        "ok": ready,
        "service": "AiVision",
        "started": started,
        "model_ready": model_ready,
        "running_models_count": len(models),
        "worker_watchdog_running": bool(worker_status.get("watchdog_running", False)),
        "model_workers": worker_status.get("models") or [],
        "database": settings.db.name,
    }


# 功能：实现 `runtime_status` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `orchestrator`（未显式标注）：`orchestrator` 对应的业务输入值；默认值为 `Depends(get_current_orchestrator)`
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/status')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`orchestrator.runtime_status`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/status")
def runtime_status(orchestrator=Depends(get_current_orchestrator)) -> dict:
    return orchestrator.runtime_status()


# 功能：读取或查询 `get_exception_alert` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/exception-alert')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`system_config_service.get_exception_alert`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/exception-alert")
def get_exception_alert() -> dict:
    return system_config_service.get_exception_alert()


# 功能：更新或保存 `update_exception_alert` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（ExceptionAlertSettings）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/exception-alert')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`system_config_service.save_exception_alert`、`payload.model_dump`、`HTTPException`、`str`、`router.put`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.put("/exception-alert")
def update_exception_alert(
    payload: ExceptionAlertSettings,
    _user: dict = Depends(require_admin),
) -> dict:
    try:
        return system_config_service.save_exception_alert(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
