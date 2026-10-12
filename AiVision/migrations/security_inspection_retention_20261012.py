"""安检证据表、时间索引和留存原图回填；默认只读检查，应用时须停止服务。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import MetaData, func, inspect, select

from AiVision.core.logger import logger
from AiVision.core.schema import assert_table_matches
from AiVision.features.security_inspection.evidence import EVIDENCE_MAX_BYTES, encode_evidence_image

TIME_INDEX = "ix_inspection_started_at"
BACKFILL_BATCH_SIZE = 100


def check(engine) -> dict:
    """接受迁移前后两种索引状态，拒绝已有业务列、约束或图片表不兼容。"""
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.features.security_inspection.orm import InspectionSession, InspectionSessionImage
    from AiVision.features.security_inspection.service import InspectionService

    with engine.connect() as connection:
        inspector = inspect(connection)
        indexes = {item["name"] for item in inspector.get_indexes(InspectionSession.__tablename__)}
        metadata = MetaData()
        AiCameraConfig.__table__.to_metadata(metadata)
        expected = InspectionSession.__table__.to_metadata(metadata)
        if TIME_INDEX not in indexes:
            expected.indexes = {index for index in expected.indexes if index.name != TIME_INDEX}
        assert_table_matches(connection, expected)
        image_table_exists = inspector.has_table(InspectionSessionImage.__tablename__)
        if image_table_exists:
            assert_table_matches(connection, InspectionSessionImage.__table__)
        recent = select(func.count()).select_from(InspectionSession).where(
            InspectionSession.status == "non_compliant",
            InspectionSession.started_at >= InspectionService.retention_cutoff(),
        )
        if image_table_exists:
            recent = recent.where(~select(InspectionSessionImage.session_id).where(
                InspectionSessionImage.session_id == InspectionSession.session_id,
            ).exists())
        return {
            "needs_time_index": TIME_INDEX not in indexes,
            "needs_image_table": not image_table_exists,
            "recent_sessions_without_image": connection.scalar(recent),
        }


def read_legacy_image(raw_path: str, data_path: Path) -> bytes:
    """只回填受管安检目录内的真实图像，拒绝链接、目录越界和损坏文件。"""
    root = data_path.expanduser().resolve()
    path = Path(raw_path).expanduser().absolute()
    relative = path.relative_to(root)
    if not relative.parts or relative.parts[0] != "12" or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("报警图片不属于安检媒体目录")
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("报警图片路径含符号链接")
    # 防止回填异常文件时无限读取，正常关键帧拼图远小于该边界。
    with path.open("rb") as source:
        raw = source.read(EVIDENCE_MAX_BYTES + 1)
    if not raw or len(raw) > EVIDENCE_MAX_BYTES:
        raise ValueError("原图为空或超过读取上限")
    frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("报警原图解码失败")
    return encode_evidence_image(frame)


def backfill(engine, data_path: Path, now: datetime | None = None) -> dict:
    """按报警主键分批回填近期缺图会话，已有图片不覆盖，缺失图片如实统计。"""
    from AiVision.alarms.records.orm import AiAlarmEvent
    from AiVision.features.security_inspection.orm import InspectionSession, InspectionSessionImage
    from AiVision.features.security_inspection.service import InspectionService

    cutoff = InspectionService.retention_cutoff(now)
    cursor = 0
    copied, unavailable = 0, 0
    alarm = AiAlarmEvent.__table__
    history = InspectionSession.__table__
    images = InspectionSessionImage.__table__
    while True:
        with engine.begin() as connection:
            rows = connection.execute(select(alarm.c.id, alarm.c.image_path, history.c.session_id).join(
                history, alarm.c.event_metadata["session_id"].as_string() == history.c.session_id,
            ).where(
                alarm.c.id > cursor, alarm.c.violation_type == 12,
                alarm.c.feature_name == "security_inspection", alarm.c.department == history.c.department,
                history.c.status == "non_compliant", history.c.started_at >= cutoff,
                ~select(images.c.session_id).where(images.c.session_id == history.c.session_id).exists(),
            ).order_by(alarm.c.id).limit(BACKFILL_BATCH_SIZE)).all()
            if not rows:
                break
            for row in rows:
                cursor = row.id
                # 同批可能有重复报警；每个 session 始终只有一份证据。
                if connection.scalar(select(images.c.session_id).where(images.c.session_id == row.session_id)):
                    continue
                try:
                    data = read_legacy_image(row.image_path, data_path)
                except (OSError, ValueError, cv2.error) as exc:
                    logger.warning(f"[security_inspection] 历史图片未回填 alarm_id={row.id}: {type(exc).__name__}: {exc}")
                    unavailable += 1
                    continue
                connection.execute(images.insert().values(
                    session_id=row.session_id, image_data=data, media_type="image/jpeg",
                ))
                copied += 1
    return {"copied": copied, "unavailable_alarm_images": unavailable}


def apply(engine, data_path: Path) -> dict:
    """只增加表和索引并回填可用原图，不删除任何历史或媒体；重复执行安全。"""
    from AiVision.features.security_inspection.orm import InspectionSession, InspectionSessionImage

    result = check(engine)
    with engine.begin() as connection:
        if result["needs_time_index"]:
            next(index for index in InspectionSession.__table__.indexes if index.name == TIME_INDEX).create(connection)
        InspectionSessionImage.__table__.create(connection, checkfirst=True)
        assert_table_matches(connection, InspectionSession.__table__)
        assert_table_matches(connection, InspectionSessionImage.__table__)
    result.update(backfill(engine, data_path))
    result.update(check(engine))
    return result


def main() -> None:
    """使用部署配置执行只读检查，只有显式 apply/offline 才执行升级和图片回填。"""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--apply", action="store_true")
    parser.add_argument("--offline", action="store_true", help="服务和其他数据库写入均已停止")
    args = parser.parse_args()
    if args.apply and not args.offline:
        parser.error("应用升级前必须停止服务，并提供 --offline")
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from AiVision.core.db import get_engine
    from AiVision.core.settings import settings

    engine = get_engine()
    try:
        result = apply(engine, Path(settings.storage.data_path)) if args.apply else check(engine)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
