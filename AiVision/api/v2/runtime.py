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


class ExceptionAlertSettings(BaseModel):
    wechat_enable: bool = False
    wechat_user: str = ""
    repeat_interval_minutes: int = 60


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


@router.get("/status")
def runtime_status(orchestrator=Depends(get_current_orchestrator)) -> dict:
    return orchestrator.runtime_status()


@router.get("/capabilities")
def list_capabilities(orchestrator=Depends(get_current_orchestrator)) -> dict:
    return {"items": orchestrator.list_feature_runtime_statuses()}


def _set_capability_state(feature: str, enabled: bool, orchestrator) -> dict:
    try:
        return orchestrator.set_feature_enabled(feature, enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/capabilities/{feature}/start")
def start_capability(
    feature: str,
    orchestrator=Depends(get_current_orchestrator),
    _user: dict = Depends(require_admin),
) -> dict:
    return _set_capability_state(feature, True, orchestrator)


@router.post("/capabilities/{feature}/stop")
def stop_capability(
    feature: str,
    orchestrator=Depends(get_current_orchestrator),
    _user: dict = Depends(require_admin),
) -> dict:
    return _set_capability_state(feature, False, orchestrator)


@router.get("/exception-alert")
def get_exception_alert() -> dict:
    return system_config_service.get_exception_alert()


@router.put("/exception-alert")
def update_exception_alert(
    payload: ExceptionAlertSettings,
    _user: dict = Depends(require_admin),
) -> dict:
    try:
        return system_config_service.save_exception_alert(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
