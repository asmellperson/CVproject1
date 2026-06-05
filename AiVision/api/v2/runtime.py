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


@router.get("/health")
def health(orchestrator=Depends(get_current_orchestrator)) -> dict:
    status = orchestrator.runtime_status()
    return {
        "ok": True,
        "service": "AiVision",
        "started": status.get("started", False),
        "database": settings.db.name,
    }


@router.get("/status")
def runtime_status(orchestrator=Depends(get_current_orchestrator)) -> dict:
    return orchestrator.runtime_status()


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
