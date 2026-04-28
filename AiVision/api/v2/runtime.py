"""
api/v2/runtime.py
运行状态、健康检查接口。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_current_orchestrator
from core.settings import settings


router = APIRouter(prefix="/api/v2/runtime", tags=["runtime"])


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
