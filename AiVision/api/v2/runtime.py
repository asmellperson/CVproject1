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
    """健康检查端点。

    反映真实就绪状态供冷启动脚本与监控判定：
        ready = orchestrator 已 start 且至少 1 个推理模型在跑
    """
    status = orchestrator.runtime_status()
    started = bool(status.get("started", False))
    models = status.get("running_models") or []
    model_ready = len(models) > 0
    ready = started and model_ready
    return {
        "ok": ready,
        "service": "AiVision",
        "started": started,
        "model_ready": model_ready,
        "running_models_count": len(models),
        "database": settings.db.name,
    }


@router.get("/status")
def runtime_status(orchestrator=Depends(get_current_orchestrator)) -> dict:
    return orchestrator.runtime_status()
