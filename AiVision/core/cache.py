"""
core/cache.py
功能配置内存缓存 — 避免每次推理/告警循环反复查数据库。

旧代码硬编码了 5 个 ORM 表:
    for fc in session.query(AiCameraConfigBlocks).all(): ...
    for fc in session.query(AiCameraConfigDetectFace).all(): ...
    ...

新代码通过 features 注册表反射,加新功能时缓存自动覆盖。
"""
from __future__ import annotations
import threading
from typing import Optional

from core.db import get_session
from core.logger import logger


class ConfigCache:
    """摄像头基础信息 + 功能配置内存缓存"""

    def __init__(self):
        self._camera_cache: dict[int, dict] = {}
        self._function_cache: dict[tuple[int, str], dict] = {}
        self._lock = threading.Lock()
        self._initialized = False

    def init(self):
        """启动时一次性加载,需在 features 注册完成后调用"""
        if self._initialized:
            return
        logger.info("[ConfigCache] 正在初始化缓存...")
        self._load_cameras()
        self._load_function_configs()
        self._initialized = True
        logger.info(
            f"[ConfigCache] 缓存初始化完成 - {len(self._camera_cache)} 个摄像头, "
            f"{len(self._function_cache)} 个功能配置"
        )

    def reload(self):
        """全量重载"""
        with self._lock:
            self._camera_cache.clear()
            self._function_cache.clear()
            self._initialized = False
        self.init()

    # ---------- Camera ----------

    def _load_cameras(self):
        from platform.camera.orm import AiCameraConfig
        session = get_session()
        try:
            for cam in session.query(AiCameraConfig).all():
                self._camera_cache[cam.id] = self._orm_to_dict(cam)
        finally:
            session.close()

    def get_camera_config(self, camera_id: int) -> Optional[dict]:
        return self._camera_cache.get(camera_id)

    def refresh_camera(self, camera_id: int):
        from platform.camera.orm import AiCameraConfig
        session = get_session()
        try:
            cam = session.query(AiCameraConfig).get(camera_id)
            with self._lock:
                if cam is None:
                    self._camera_cache.pop(camera_id, None)
                else:
                    self._camera_cache[camera_id] = self._orm_to_dict(cam)
            logger.info(f"[ConfigCache] 刷新摄像头: camera_id={camera_id}")
        finally:
            session.close()

    # ---------- Functions ----------

    def _load_function_configs(self):
        """通过 features 注册表反射加载所有功能配置"""
        from features import all_specs
        session = get_session()
        try:
            for spec in all_specs().values():
                for cfg in session.query(spec.orm_class).all():
                    self._function_cache[(cfg.camera_id, spec.name)] = self._enrich_function_config(
                        self._orm_to_dict(cfg)
                    )
        finally:
            session.close()

    def get_function_config(self, camera_id: int, feature_name: str) -> Optional[dict]:
        return self._function_cache.get((camera_id, feature_name))

    def get_all_function_configs(self) -> dict:
        """返回浅拷贝,外部可安全遍历"""
        return dict(self._function_cache)

    def refresh_function(self, camera_id: int, feature_name: str):
        from features import get_spec
        spec = get_spec(feature_name)
        if spec is None:
            return
        session = get_session()
        try:
            cfg = session.query(spec.orm_class).filter_by(camera_id=camera_id).first()
            with self._lock:
                key = (camera_id, feature_name)
                if cfg is None:
                    self._function_cache.pop(key, None)
                    logger.info(f"[ConfigCache] 删除功能配置: {key}")
                else:
                    self._function_cache[key] = self._enrich_function_config(self._orm_to_dict(cfg))
                    logger.info(f"[ConfigCache] 刷新功能配置: {key}")
        finally:
            session.close()

    # ---------- Helpers ----------

    @staticmethod
    def _orm_to_dict(obj) -> dict:
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}

    def _enrich_function_config(self, cfg: dict) -> dict:
        """给功能配置补摄像头基础信息,consumer 运行时按 shm_name 找帧。"""
        camera = self._camera_cache.get(cfg.get("camera_id")) or {}
        if camera:
            cfg = dict(cfg)
            cfg["name"] = camera.get("name")
            cfg["shm_name"] = camera.get("shm_name") or f"camera_{cfg.get('camera_id')}"
            cfg["camera_enable"] = camera.get("enable")
        return cfg


# 全局单例
config_cache = ConfigCache()
