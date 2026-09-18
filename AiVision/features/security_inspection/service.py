"""安检设置与历史查询；摄像头配置由公共 FeatureConfigManager 管理。"""

from datetime import datetime

from sqlalchemy import func

from AiVision.core.db import get_session, session_scope
from AiVision.core.system_config import AiSystemConfig
from AiVision.cameras.orm import AiCameraConfig
from .orm import InspectionSession
from .schema import VlmSettings

SETTINGS_KEY = "security_inspection"


class InspectionService:
    def get_settings(self) -> VlmSettings:
        with get_session() as session:
            row = session.get(AiSystemConfig, SETTINGS_KEY)
            return VlmSettings() if row is None else VlmSettings.model_validate(row.value)

    def save_settings(self, settings: VlmSettings) -> None:
        with session_scope() as session:
            row = session.get(AiSystemConfig, SETTINGS_KEY)
            if row is None:
                session.add(AiSystemConfig(key=SETTINGS_KEY, value=settings.model_dump()))
            else:
                row.value = settings.model_dump()

    def record(self, task, status: str, verdict=None, error=None, latency=None) -> None:
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
