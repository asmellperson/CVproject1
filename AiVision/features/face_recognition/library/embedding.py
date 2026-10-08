"""增量生成注册人员特征：python -m AiVision.features.face_recognition.library.embedding。"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
from dotenv import load_dotenv

from AiVision.connectors.hikvision import HikvisionClient, HikvisionPersons, PersonPhoto
from AiVision.core.logger import logger

from . import HIKVISION_SOURCES, PersonSyncError
from .constants import MODEL_NAME
from .index import photo_signature
from .sync import HikvisionSyncSettings, _error_summary

if TYPE_CHECKING:
    from .service import FaceLibraryService
    from AiVision.inference.workers.face_recognizer import InsightFaceRecognizer


@dataclass
class EmbeddingCounts:
    """按海康来源累计特征生成、跳过和失败数量。"""
    total: int = 0
    generated: int = 0
    skipped: int = 0
    failed: int = 0


def generate_embeddings(
    service: FaceLibraryService, recognizer: InsightFaceRecognizer,
    persons: dict[str, HikvisionPersons], *, model_name: str = MODEL_NAME,
) -> dict[str, EmbeddingCounts]:
    """增量更新在用人员的特征，每张注册照片必须恰好包含一张人脸。

    模型和照片签名均未变化时跳过；单个人员失败会计入统计并继续处理
    其余人员，写入时由服务再次核对照片是否在生成期间发生变化。
    """
    counts = {source: EmbeddingCounts() for source in HIKVISION_SOURCES}
    for candidate in service.list_embedding_candidates():
        result = counts[candidate.hik_source]
        result.total += 1
        if not candidate.pic_uri or not candidate.server_index_code:
            result.skipped += 1
            continue
        signature = photo_signature(candidate.pic_uri, candidate.server_index_code)
        if candidate.embedding_model_name == model_name and candidate.embedding_photo_signature == signature:
            result.skipped += 1
            continue
        try:
            picture = persons[candidate.hik_source].get_picture(PersonPhoto(
                picUri=candidate.pic_uri, serverIndexCode=candidate.server_index_code,
            ))
            frame = cv2.imdecode(np.frombuffer(picture.content, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise PersonSyncError("注册照片解码失败")
            faces = recognizer.get_faces(frame)
            # 仅注册照片要求单脸。不得猜测当前人员对应哪张脸。
            if len(faces) != 1:
                raise PersonSyncError(f"注册照片检测到 {len(faces)} 张人脸，要求恰好 1 张")
            service.save_embedding(
                candidate.person_id, faces[0].normed_embedding, model_name=model_name, signature=signature,
            )
            result.generated += 1
        except Exception as exc:
            result.failed += 1
            logger.warning(
                f"[FaceEmbedding] {candidate.hik_source} 本地人员 {candidate.person_id} 生成失败：{_error_summary(exc)}"
            )
    return counts


def main() -> int:
    """校验数据库结构并加载模型及海康连接，运行特征生成并以退出码报告失败。"""
    load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)
    try:
        from AiVision.core.db import Base, get_engine
        from AiVision.core.schema import assert_table_matches
        from AiVision.core.settings import settings
        from AiVision.inference.model_paths import load_model_paths
        from AiVision.inference.workers.face_recognizer import InsightFaceRecognizer
        from .orm import FaceEmbedding, FacePerson
        from .service import FaceLibraryService

        if not settings.db.enable:
            raise PersonSyncError("SQL_ENABLE=false，未生成特征")
        # 模型加载和人员查询前核验两张正式表，不做补列或迁移。
        engine = get_engine()
        tables = [FacePerson.__table__, FaceEmbedding.__table__]
        Base.metadata.create_all(engine, tables=tables)
        with engine.connect() as connection:
            try:
                for table in tables:
                    assert_table_matches(connection, table)
            except ValueError as exc:
                raise PersonSyncError(str(exc)) from exc
        model_path = load_model_paths().get("insightface", "")
        recognizer = InsightFaceRecognizer(model_path)
        with ExitStack() as stack:
            persons = {}
            for source in HIKVISION_SOURCES:
                config = HikvisionSyncSettings(_env_prefix=f"HIKVISION_{source.upper()}_")
                client = stack.enter_context(HikvisionClient(config.client_config()))
                persons[source] = HikvisionPersons(client)
            counts = generate_embeddings(FaceLibraryService(), recognizer, persons)
        for source, result in counts.items():
            print(f"{source}: 总数 {result.total}，生成 {result.generated}，跳过 {result.skipped}，失败 {result.failed}")
        return int(any(result.failed for result in counts.values()))
    except Exception as exc:
        logger.error(f"[FaceEmbedding] 生成任务失败：{_error_summary(exc)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
