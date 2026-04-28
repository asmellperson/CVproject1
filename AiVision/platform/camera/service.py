"""
platform/camera/service.py
摄像头 CRUD 服务 — 替代旧 SQL 类里的 get_all_camera / get_camera_by_key /
save_to_database / save_camera_with_function_config 等方法。

新版本职责更窄:只管摄像头主表(ai_camera_config),功能配置由 features/_base/service.py 管。
"""
from __future__ import annotations
from typing import Optional

from sqlalchemy import or_

from core.db import session_scope, get_session
from core.events import config_event_bus, ConfigChangeEvent
from core.cache import config_cache
from core.logger import logger
from features import all_specs
from .orm import AiCameraConfig


class CameraService:
    """摄像头主表的所有操作"""

    # ---------- Read ----------

    def list_cameras(self) -> list[dict]:
        """返回所有摄像头列表(基础信息 + 各功能启用状态)"""
        session = get_session()
        try:
            cameras = session.query(AiCameraConfig).order_by(AiCameraConfig.id).all()
            specs = all_specs()
            results = []
            for cam in cameras:
                # 收集每个功能在此摄像头上是否启用
                functions = {}
                for fname, spec in specs.items():
                    cfg = (
                        session.query(spec.orm_class)
                        .filter_by(camera_id=cam.id)
                        .first()
                    )
                    functions[fname] = bool(cfg.enable) if cfg is not None else False
                results.append(self._to_dict(cam, functions))
            return results
        finally:
            session.close()

    def get_camera(self, key: str) -> Optional[dict]:
        """按 shm_name / name / id / 'camera_{id}' 任一格式查询"""
        session = get_session()
        try:
            cam = self._get_orm_by_key(session, key)
            if cam is None:
                return None
            specs = all_specs()
            functions = {}
            for fname, spec in specs.items():
                cfg = (
                    session.query(spec.orm_class)
                    .filter_by(camera_id=cam.id)
                    .first()
                )
                functions[fname] = bool(cfg.enable) if cfg is not None else False
            return self._to_dict(cam, functions)
        finally:
            session.close()

    # ---------- Write ----------

    def create_camera(self, payload: dict) -> dict:
        """新增摄像头 — 同时为每个已注册 feature 建一行默认空配置(enable=False)"""
        name = (payload.get("name") or "").strip()
        url = (payload.get("url") or "").strip()
        shm_name = (payload.get("shm_name") or "").strip()
        fps = int(payload.get("fps", 5))
        max_restart = int(payload.get("max_restart", 10))
        enable = bool(payload.get("enabled", payload.get("enable", True)))

        if not (name and url and shm_name):
            raise ValueError("name, url, shm_name 都是必填")
        if fps <= 0:
            raise ValueError("fps must be > 0")
        if max_restart < 0:
            raise ValueError("max_restart must be >= 0")

        with session_scope() as session:
            # 唯一性校验
            if session.query(AiCameraConfig).filter_by(name=name).first():
                raise ValueError(f"name 已存在: {name}")
            if session.query(AiCameraConfig).filter_by(shm_name=shm_name).first():
                raise ValueError(f"shm_name 已存在: {shm_name}")

            cam = AiCameraConfig(
                name=name, url=url, shm_name=shm_name,
                fps=fps, max_restart=max_restart, enable=enable,
                function_config={},
            )
            session.add(cam)
            session.flush()

            # 为每个 feature 创建默认配置(enable=False)
            for spec in all_specs().values():
                session.add(spec.orm_class(camera_id=cam.id, enable=False))

            cam_id = cam.id
            cam_shm = cam.shm_name

        # 缓存 + 事件
        config_cache.refresh_camera(cam_id)
        for fname in all_specs():
            config_cache.refresh_function(cam_id, fname)
        config_event_bus.publish(ConfigChangeEvent(
            change_type="camera_added",
            camera_id=cam_id, camera_name=cam_shm,
        ))

        return self.get_camera(cam_shm)

    def update_camera(self, key: str, payload: dict) -> Optional[dict]:
        """更新摄像头基础信息 — 不动功能配置"""
        with session_scope() as session:
            cam = self._get_orm_by_key(session, key)
            if cam is None:
                return None
            for field in ("name", "url", "fps", "max_restart"):
                if field in payload:
                    setattr(cam, field, payload[field])
            if "enabled" in payload:
                cam.enable = bool(payload["enabled"])
            elif "enable" in payload:
                cam.enable = bool(payload["enable"])
            cam_id, cam_shm = cam.id, cam.shm_name

        config_cache.refresh_camera(cam_id)
        config_event_bus.publish(ConfigChangeEvent(
            change_type="camera_updated",
            camera_id=cam_id, camera_name=cam_shm,
        ))
        return self.get_camera(cam_shm)

    def delete_camera(self, key: str) -> bool:
        with session_scope() as session:
            cam = self._get_orm_by_key(session, key)
            if cam is None:
                return False
            cam_id, cam_shm = cam.id, cam.shm_name
            session.delete(cam)  # CASCADE 会清理所有 feature 配置

        config_event_bus.publish(ConfigChangeEvent(
            change_type="camera_removed",
            camera_id=cam_id, camera_name=cam_shm,
        ))
        config_cache.reload()
        return True

    # ---------- Maintenance ----------

    def normalize_shm_names(self) -> int:
        """补齐空 shm_name(用 camera_{id})"""
        updated = 0
        with session_scope() as session:
            cameras = session.query(AiCameraConfig).all()
            used = {(c.shm_name or "").strip() for c in cameras if (c.shm_name or "").strip()}
            for cam in cameras:
                if (cam.shm_name or "").strip():
                    continue
                candidate = f"camera_{cam.id}"
                suffix = 1
                while candidate in used:
                    candidate = f"camera_{cam.id}_{suffix}"
                    suffix += 1
                cam.shm_name = candidate
                used.add(candidate)
                updated += 1
        if updated:
            logger.info(f"[CameraService] 已补齐 {updated} 个 shm_name")
        return updated

    def ensure_feature_configs(self, enable_all: bool = False) -> int:
        """
        为每个摄像头补齐所有 feature 的配置行(若不存在)。
        enable_all=True 时把它们全部置为启用 — 用于初次部署。
        """
        changed = 0
        with session_scope() as session:
            cameras = session.query(AiCameraConfig).all()
            specs = list(all_specs().values())
            for cam in cameras:
                for spec in specs:
                    cfg = session.query(spec.orm_class).filter_by(camera_id=cam.id).first()
                    if cfg is None:
                        session.add(spec.orm_class(camera_id=cam.id, enable=enable_all))
                        changed += 1
                    elif enable_all and not cfg.enable:
                        cfg.enable = True
                        changed += 1
        if changed:
            logger.info(f"[CameraService] 已补齐/启用 {changed} 条功能配置")
        return changed

    # ---------- Helpers ----------

    @staticmethod
    def _get_orm_by_key(session, key: str) -> Optional[AiCameraConfig]:
        key = (key or "").strip()
        if not key:
            return None
        filters = [AiCameraConfig.shm_name == key, AiCameraConfig.name == key]
        if key.isdigit():
            filters.append(AiCameraConfig.id == int(key))
        elif key.startswith("camera_") and key.removeprefix("camera_").isdigit():
            filters.append(AiCameraConfig.id == int(key.removeprefix("camera_")))
        return session.query(AiCameraConfig).filter(or_(*filters)).first()

    @staticmethod
    def _to_dict(cam: AiCameraConfig, functions: dict[str, bool]) -> dict:
        return {
            "id": cam.shm_name or f"camera_{cam.id}",  # 前端用作 key
            "camera_id": cam.id,
            "name": cam.name,
            "shm_name": cam.shm_name or f"camera_{cam.id}",
            "url": cam.url,
            "fps": cam.fps,
            "max_restart": cam.max_restart,
            "enabled": bool(cam.enable),
            "shape": cam.shape,
            "functions": functions,
        }


camera_service = CameraService()
