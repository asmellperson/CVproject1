"""platform/inference/service.py — 模型 CRUD"""
from __future__ import annotations
from typing import Optional

from core.db import session_scope, get_session
from core.logger import logger
from .orm import AiModel


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

    @staticmethod
    def _to_dict(m: AiModel) -> dict:
        return {
            "id": m.id,
            "name": m.name,
            "type": m.type,
            "path": m.path,
            "import_path": m.import_path,
            "description": m.description,
            "enable": bool(m.enable),
        }


model_service = ModelService()
