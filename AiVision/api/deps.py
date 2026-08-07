"""
api/deps.py
FastAPI 依赖注入入口。

API 层只通过 service / orchestrator 暴露能力，不持有业务状态。
"""
from __future__ import annotations

from fastapi import HTTPException, status


def get_current_orchestrator():
    """返回已由 main.py 初始化的 Orchestrator。"""
    try:
        from platform.orchestrator import get_orchestrator
        return get_orchestrator()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def get_camera_service():
    from platform.camera.service import camera_service
    return camera_service


def get_feature_config_service():
    from features._base.service import feature_config_service
    return feature_config_service


def get_model_service():
    from platform.inference.service import model_service
    return model_service


def get_department_service():
    from platform.department.service import department_service
    return department_service


def get_logistics_channel_service():
    from platform.logistics_channel.service import logistics_channel_service
    return logistics_channel_service
