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
        from AiVision.runtime.orchestrator import get_orchestrator
        return get_orchestrator()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,           # orchestrator还不存在，转成HTTP 503
            detail=str(exc),
        ) from exc

# ---------------获取各种配置服务------------------------------
def get_camera_config_manager():
    """获取摄像头配置服务"""
    from AiVision.cameras.config_manager import camera_config_manager
    return camera_config_manager

def get_inference_runtime_manager():
    """获取本机模型运行服务"""
    from AiVision.inference.runtime_manager import inference_runtime_manager
    return inference_runtime_manager

def get_department_service():
    """获取部门管理服务"""
    from AiVision.departments.service import department_service
    return department_service

def get_logistics_channel_service():
    """获取物流通道配置服务"""
    from AiVision.features.logistics_channel.service import logistics_channel_service
    return logistics_channel_service


def get_horn_service():
    """获取喇叭配置服务。"""
    from AiVision.alarms.devices.service import horn_service
    return horn_service


def get_horn_runtime_manager():
    """获取与 Orchestrator 共用的喇叭运行管理器。"""
    from AiVision.alarms.devices.runtime_manager import horn_runtime_manager
    return horn_runtime_manager


def get_guard_behavior_service():
    from AiVision.features.guard_behavior.service import GuardBehaviorService
    orchestrator = get_guard_behavior_orchestrator()
    return orchestrator.guard_behavior_service if orchestrator is not None else GuardBehaviorService()


def get_guard_behavior_orchestrator():
    # 配置 API 在编排器启动前也可用；此时没有运行数据需要刷新。
    from AiVision.runtime.orchestrator import get_orchestrator
    try:
        return get_orchestrator()
    except RuntimeError:
        return None


def get_guard_behavior_runtime():
    orchestrator = get_guard_behavior_orchestrator()
    return orchestrator.guard_behavior_runtime if orchestrator is not None else None
