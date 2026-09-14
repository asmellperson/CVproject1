"""
api/deps.py
dependencis: 依赖
FastAPI 依赖注入入口。

API 层只通过 service / orchestrator 暴露能力，不持有业务状态。
"""
from __future__ import annotations

from fastapi import HTTPException, status

def get_current_orchestrator():
    """获取全局Orchestrator"""
    try:
        from AiVision.platform.orchestrator import get_orchestrator
        return get_orchestrator()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,           # orchestrator还不存在，转成HTTP 503
            detail=str(exc),
        ) from exc

# ---------------获取各种配置服务------------------------------
def get_camera_config_manager():
    """获取摄像头配置服务"""
    from AiVision.platform.camera.config_manager import camera_config_manager
    return camera_config_manager

def get_feature_config_manager():
    """获取普通检测能力功能配置服务"""
    from AiVision.features._base.config_manager import feature_config_manager
    return feature_config_manager

def get_inference_runtime_manager():
    """获取本机模型运行服务"""
    from AiVision.platform.inference.runtime_manager import inference_runtime_manager
    return inference_runtime_manager

def get_department_service():
    """获取部门管理服务"""
    from AiVision.platform.department.service import department_service
    return department_service

def get_logistics_channel_service():
    """获取物流通道配置服务"""
    from AiVision.features.detect_logistics_single_person.service import logistics_channel_service
    return logistics_channel_service


def get_horn_service():
    """获取喇叭配置服务。"""
    from AiVision.platform.alarm_device.service import horn_service
    return horn_service


def get_horn_runtime_manager():
    """获取与 Orchestrator 共用的喇叭运行管理器。"""
    from AiVision.platform.alarm_device.runtime_manager import horn_runtime_manager
    return horn_runtime_manager
