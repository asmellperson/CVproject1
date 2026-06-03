"""platform/inference/service.py — 模型 CRUD"""
from __future__ import annotations
from typing import Optional

from core.db import session_scope, get_session
from core.logger import logger
from .orm import AiModel
from .model_paths import resolve_model_path


YOLO_DETECTOR_WORKER = "platform.inference.workers.yolo_detector.YoloDetectorWorker"


class ModelService:

    def list_models(self, enabled_only: bool = False) -> list[dict]:
        session = get_session()
        try:
            q = session.query(AiModel)
            if enabled_only:
                q = q.filter(AiModel.enable.is_(True))
            return [self._to_dict(m) for m in q.all()]
        finally:
            session.close()

    def get_model(self, model_id: int) -> Optional[dict]:
        session = get_session()
        try:
            m = session.query(AiModel).get(model_id)
            return self._to_dict(m) if m else None
        finally:
            session.close()

    def get_model_by_name(self, name: str) -> Optional[dict]:
        session = get_session()
        try:
            m = session.query(AiModel).filter_by(name=name).first()
            return self._to_dict(m) if m else None
        finally:
            session.close()

    def create_model(self, payload: dict) -> dict:
        with session_scope() as session:
            m = AiModel(
                name=payload["name"],
                type=payload.get("type", "yolo"),
                path=payload["path"],
                import_path=payload.get("import_path"),
                description=payload.get("description"),
                enable=bool(payload.get("enable", True)),
            )
            session.add(m)
            session.flush()
            return self._to_dict(m)

    def update_model(self, model_id: int, payload: dict) -> Optional[dict]:
        with session_scope() as session:
            m = session.query(AiModel).get(model_id)
            if m is None:
                return None
            for f in ("name", "type", "path", "import_path", "description"):
                if f in payload:
                    setattr(m, f, payload[f])
            if "enable" in payload:
                m.enable = bool(payload["enable"])
            return self._to_dict(m)

    def delete_model(self, model_id: int) -> bool:
        with session_scope() as session:
            m = session.query(AiModel).get(model_id)
            if m is None:
                return False
            session.delete(m)
            return True

    def normalize_builtin_models(self) -> int:
        """修正常见内置模型的旧版运行配置。

        旧库里的 yolo_face 可能仍指向已不存在的旧 worker,且处于禁用状态。
        这里只修已有模型行,不创建新模型,避免覆盖现场自定义模型清单。
        """
        patched = 0
        with session_scope() as session:
            face_model = session.query(AiModel).filter_by(name="yolo_face").first()
            if face_model is None:
                return 0

            if face_model.import_path != YOLO_DETECTOR_WORKER:
                face_model.import_path = YOLO_DETECTOR_WORKER
                patched += 1
            if not bool(face_model.enable):
                face_model.enable = True
                patched += 1

        if patched:
            logger.info("[ModelService] 已修正内置模型 yolo_face 的运行配置")
        return patched

    @staticmethod
    def _to_dict(m: AiModel) -> dict:
        resolution = resolve_model_path({
            "name": m.name,
            "path": m.path,
        })
        return {
            "id": m.id,
            "name": m.name,
            "type": m.type,
            "path": resolution.path,
            "effective_path": resolution.path,
            "path_source": resolution.source,
            "database_path": resolution.database_path,
            "import_path": m.import_path,
            "description": m.description,
            "enable": bool(m.enable),
        }


model_service = ModelService()
