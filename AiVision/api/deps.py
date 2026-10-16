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


def get_inspection_service():
    """平台与外部接口共用安检持久化服务。"""
    from AiVision.features.security_inspection.service import InspectionService
    return InspectionService()


def get_inspection_consumer():
    """允许在检测尚未启动时查询配置、历史和不可用状态。"""
    orchestrator = get_optional_orchestrator()
    return orchestrator.consumers.get("security_inspection") if orchestrator is not None else None

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


def get_horn_audio_service():
    """取得受管服务器 AAC 素材库。"""
    from AiVision.alarms.devices.audio import horn_audio_service
    return horn_audio_service


def get_horn_sip_service():
    """取得平台共享的 SIP 配置与运行服务。"""
    from AiVision.alarms.devices.sip_service import horn_sip_service
    return horn_sip_service


def get_guard_behavior_service():
    """优先复用编排器服务，编排器尚未就绪时仍允许访问配置事务。"""
    from AiVision.features.guard_behavior.service import GuardBehaviorService
    orchestrator = get_optional_orchestrator()
    return orchestrator.guard_behavior_service if orchestrator is not None else GuardBehaviorService()


def get_optional_orchestrator():
    # 配置 API 在编排器启动前也可用；此时没有运行数据需要刷新。
    """尝试取得编排器，尚未创建时返回 None 供配置接口降级使用。"""
    from AiVision.runtime.orchestrator import get_orchestrator
    try:
        return get_orchestrator()
    except RuntimeError:
        return None


def get_guard_behavior_runtime():
    """提供可选保安室运行时，未启动阶段由接口返回不可用状态。"""
    orchestrator = get_optional_orchestrator()
    return orchestrator.guard_behavior_runtime if orchestrator is not None else None
