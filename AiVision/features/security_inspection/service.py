"""安检设置与历史查询；摄像头配置由公共 FeatureConfigManager 管理。"""

from datetime import datetime, timedelta

from sqlalchemy import func

from AiVision.core.db import get_session, session_scope
from AiVision.core.logger import logger
from AiVision.core.config_revision import require_configuration_values
from AiVision.core.media_cleanup import CLEANUP_BATCH_SIZE
from AiVision.core.settings import settings
from AiVision.core.system_config import AiSystemConfig
from AiVision.cameras.orm import AiCameraConfig
from .orm import InspectionSession, InspectionSessionImage
from .evidence import EVIDENCE_MAX_BYTES
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

    def save_settings(self, settings: VlmSettings, *, expected_values: dict | None = None) -> None:
        """在事务内创建或替换公共模型设置，运行时重载由调用方负责。"""
        with session_scope() as session:
            row = session.get(AiSystemConfig, SETTINGS_KEY, with_for_update=True)
            if expected_values is not None:
                require_configuration_values(
                    VlmSettings.model_validate(row.value).model_dump() if row else VlmSettings().model_dump(),
                    expected_values,
                )
            if row is None:
                session.add(AiSystemConfig(key=SETTINGS_KEY, value=settings.model_dump()))
            else:
                row.value = settings.model_dump()

    def record(self, task, status: str, verdict=None, error=None, latency=None, *, image_data: bytes | None = None) -> None:
        """不合规会话和证据在同一事务提交，禁止保存没有图片的新不合规记录。"""
        if status == "non_compliant":
            if not isinstance(image_data, bytes) or not image_data or len(image_data) > EVIDENCE_MAX_BYTES:
                raise ValueError("不合规安检记录必须提供有效的证据图片")
        elif image_data is not None:
            raise ValueError("只有不合规安检记录保存证据图片")
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
            if image_data is not None:
                # 显式 flush 保证父记录先插入；图片失败时整个事务仍会回滚。
                session.flush()
                session.add(InspectionSessionImage(
                    session_id=task.session_id, image_data=image_data, media_type="image/jpeg",
                ))

    @staticmethod
    def retention_cutoff(now: datetime | None = None) -> datetime:
        """历史、图片读取与清理使用相同的本地时间和滚动保留窗口。"""
        return (now or datetime.now()) - timedelta(days=settings.storage.alarm_media_retention_days)

    def cleanup_history(self, now: datetime | None = None) -> int:
        """按时间索引分批删除过期会话及图片，避免长期占用数据库事务。"""
        cutoff = self.retention_cutoff(now)
        deleted = 0
        while True:
            with session_scope() as session:
                ids = [row[0] for row in session.query(InspectionSession.session_id).filter(
                    InspectionSession.started_at < cutoff,
                ).order_by(InspectionSession.started_at, InspectionSession.session_id).limit(CLEANUP_BATCH_SIZE)]
                if not ids:
                    break
                session.query(InspectionSessionImage).filter(InspectionSessionImage.session_id.in_(ids)).delete(
                    synchronize_session=False,
                )
                count = session.query(InspectionSession).filter(InspectionSession.session_id.in_(ids)).delete(
                    synchronize_session=False,
                )
            deleted += count
        logger.info(f"[security_inspection] 过期会话与证据清理完成 sessions={deleted} cutoff={cutoff.isoformat()}")
        return deleted

    def image(self, department: str, session_id: str) -> tuple[bytes, str] | None:
        """只返回获准事业部、保留窗口内的不合规证据，不依赖磁盘报警文件。"""
        with get_session() as session:
            row = session.query(InspectionSessionImage.image_data, InspectionSessionImage.media_type).join(
                InspectionSession, InspectionSession.session_id == InspectionSessionImage.session_id,
            ).filter(
                InspectionSession.session_id == session_id, InspectionSession.department == department,
                InspectionSession.status == "non_compliant", InspectionSession.started_at >= self.retention_cutoff(),
            ).first()
            return (row.image_data, row.media_type) if row is not None else None

    def history(self, department: str, *, camera_id: int | None, limit: int, offset: int) -> dict:
        """安检总数只计有效判定，历史分页保留失败和取消会话且不加载图片内容。"""
        with get_session() as session:
            query = session.query(InspectionSession).filter(
                InspectionSession.department == department, InspectionSession.started_at >= self.retention_cutoff(),
            )
            if camera_id is not None:
                query = query.filter_by(camera_id=camera_id)
            counts = dict(
                query.with_entities(InspectionSession.status, func.count()).group_by(InspectionSession.status).all()
            )
            compliant, non_compliant = counts.get("compliant", 0), counts.get("non_compliant", 0)
            cancelled = counts.get("cancelled", 0)
            has_image = session.query(InspectionSessionImage.session_id).filter(
                InspectionSessionImage.session_id == InspectionSession.session_id,
            ).exists()
            rows = query.add_columns(has_image.label("has_image")).order_by(
                InspectionSession.started_at.desc(), InspectionSession.session_id,
            )
            return {
                "retention_days": settings.storage.alarm_media_retention_days,
                "stats": {
                    "total": compliant + non_compliant,
                    "compliant": compliant,
                    "non_compliant": non_compliant,
                    "error": counts.get("error", 0),
                    "cancelled": cancelled,
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
                        "has_image": bool(image_exists),
                    }
                    for row, image_exists in rows.offset(offset).limit(limit)
                ],
            }
