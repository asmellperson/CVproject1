"""安检设置与历史查询；摄像头配置由公共 FeatureConfigManager 管理。"""

from datetime import datetime

from sqlalchemy import func

from AiVision.core.db import get_session, session_scope
from AiVision.core.system_config import AiSystemConfig
from AiVision.cameras.orm import AiCameraConfig
from .orm import InspectionSession
from .schema import StatusResponse, VlmHealth, VlmSettings
from .vlm import VlmClient

SETTINGS_KEY = "security_inspection"


class InspectionService:
    """持久化模型设置和安检历史，提供按事业部隔离的查询。"""
    @staticmethod
    def runtime_status(department: str, consumer) -> StatusResponse:
        """两类 API 使用相同的状态口径，未启动时仍可明确返回状态。"""
        if consumer is None:
            return StatusResponse(
                running=False, queue=0, active=0,
                error="安检处理器未运行，请检查人体模型状态", vlm=VlmHealth(),
            )
        result = dict(consumer.vlm_runtime.status(department))
        if not consumer.running:
            result.update(running=False, error="安检处理器未运行，请检查人体模型状态")
        return StatusResponse.model_validate(result)

    def check_model(self, settings: VlmSettings) -> VlmHealth:
        """执行接口与模型存在性探测，不生成安检内容。"""
        return VlmClient().check_health(settings)

    def get_settings(self) -> VlmSettings:
        """读取已保存设置，尚未配置时返回模型默认设置。"""
        with get_session() as session:
            row = session.get(AiSystemConfig, SETTINGS_KEY)
            return VlmSettings() if row is None else VlmSettings.model_validate(row.value)

    def save_settings(self, settings: VlmSettings) -> None:
        """在事务内创建或替换公共模型设置，运行时重载由调用方负责。"""
        with session_scope() as session:
            row = session.get(AiSystemConfig, SETTINGS_KEY)
            if row is None:
                session.add(AiSystemConfig(key=SETTINGS_KEY, value=settings.model_dump()))
            else:
                row.value = settings.model_dump()

    def record(self, task, status: str, verdict=None, error=None, latency=None) -> None:
        """保存会话身份和判定快照；摄像头已删除时仍保留历史名称和事业部。"""
        with session_scope() as session:
            session.add(
                InspectionSession(
                    session_id=task.session_id,
                    camera_id=task.camera_id if session.get(AiCameraConfig, task.camera_id) is not None else None,
                    camera_name=task.camera_name,
                    department=task.department,
                    roi_name=task.roi_name,
                    started_at=datetime.fromtimestamp(task.start_ts),
                    ended_at=datetime.fromtimestamp(task.end_ts),
                    status=status,
                    verdict=verdict.model_dump() if verdict is not None else None,
                    error=error,
                    latency_sec=latency,
                )
            )

    def history(self, department: str, *, camera_id: int | None, limit: int, offset: int) -> dict:
        """按事业部及可选摄像头返回历史与统计，合格率只基于成功判定计算。"""
        with get_session() as session:
            query = session.query(InspectionSession).filter_by(department=department)
            if camera_id is not None:
                query = query.filter_by(camera_id=camera_id)
            counts = dict(
                query.with_entities(InspectionSession.status, func.count()).group_by(InspectionSession.status).all()
            )
            compliant, non_compliant = counts.get("compliant", 0), counts.get("non_compliant", 0)
            rows = query.order_by(InspectionSession.started_at.desc(), InspectionSession.session_id)
            return {
                "stats": {
                    "total": sum(counts.values()),
                    "compliant": compliant,
                    "non_compliant": non_compliant,
                    "error": counts.get("error", 0),
                    "cancelled": counts.get("cancelled", 0),
                    "rate": round(compliant * 100 / (compliant + non_compliant), 1)
                    if compliant + non_compliant
                    else 0.0,
                },
                "items": [
                    {
                        "session_id": row.session_id,
                        "camera_id": row.camera_id,
                        "camera_name": row.camera_name,
                        "roi_name": row.roi_name,
                        "started_at": row.started_at.isoformat(),
                        "ended_at": row.ended_at.isoformat(),
                        "duration_sec": (row.ended_at - row.started_at).total_seconds(),
                        "status": row.status,
                        "verdict": row.verdict,
                        "error": row.error,
                        "latency_sec": row.latency_sec,
                    }
                    for row in rows.offset(offset).limit(limit)
                ],
            }
