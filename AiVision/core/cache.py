"""摄像头与功能配置的进程内缓存，减少检测循环重复查询数据库。

通过 features.registry 的 FeatureSpec 查找各功能配置表，并把摄像头名称、共享内存名、
事业部和总开关注入运行配置。服务提交数据后需显式刷新；直接修改数据库不会自动更新缓存。
缓存不保存视频帧，也不是跨进程共享对象，读取到的内部字典不应由业务原地修改。
"""
from __future__ import annotations
import threading
from typing import Optional

from AiVision.core.db import get_session
from AiVision.core.logger import logger

class ConfigCache:
    """
    摄像头基础信息 + 功能配置的进程内内存缓存。

    设计动机:
        推理循环与告警分发每帧都需读取摄像头配置与功能配置，
        若每次直接查数据库会产生大量重复 I/O。
        本类在启动时一次性将全量配置加载到内存字典，
        运行时通过 refresh_* 方法做单条热更新，无需全量重载。

    数据结构:
        _camera_cache   : {camera_id → 摄像头配置字典}
        _function_cache : {(camera_id, feature_name) → 功能配置字典}
        功能配置字典已通过 _enrich_function_config() 注入摄像头基础字段，
        Consumer 可直接使用，无需二次查摄像头表。

    线程安全:
        单条刷新及 reload 清空缓存时通过 _lock 保护；init 全量加载不持锁；
        读操作（get_*）不加锁，依赖 CPython GIL 保证字典读取的原子性。
    """

    def __init__(self):
        # {camera_id: dict} — 摄像头基础信息，由 _load_cameras() 填充
        """准备摄像头和功能两级字典、写锁与初始化标记；首次查库由 init() 显式触发。"""
        self._camera_cache: dict[int, dict] = {}
        # {(camera_id, feature_name): dict} — 功能配置，由 _load_function_configs() 填充
        self._function_cache: dict[tuple[int, str], dict] = {}  # 缓存层将摄像头配置和Feature配置合并为完整运行配置
        self._lock = threading.Lock()   # 保护缓存字典的写操作
        self._initialized = False       # 防止 init() 被重复调用

    def init(self):
        """按注册表全量加载摄像头与功能配置，成功后标记已初始化；重复调用直接返回。

        功能元数据来自 features.registry.all_specs()，数据库读取异常继续传播。
        """
        if self._initialized:
            return
        logger.info("[ConfigCache] 正在初始化缓存...")
        # 先加载摄像头，再加载功能配置
        self._load_cameras()
        self._load_function_configs()
        self._initialized = True
        logger.info(
            f"[ConfigCache] 缓存初始化完成 - {len(self._camera_cache)} 个摄像头, "
            f"{len(self._function_cache)} 个功能配置"
        )

    def reload(self):
        """
        清空并全量重载所有缓存。

        适用场景：数据库发生批量变更（如导入配置、版本升级）时主动触发。
        单条变更请优先使用 refresh_camera() / refresh_function()，代价更低。
        """
        with self._lock:
            self._camera_cache.clear()
            self._function_cache.clear()
            self._initialized = False
        self.init()

    # ------------------------------------------------------------------ #
    #  摄像头缓存                                                           #
    # ------------------------------------------------------------------ #

    def _load_cameras(self):
        """从数据库全量加载摄像头基础配置到 _camera_cache。"""
        from AiVision.cameras.orm import AiCameraConfig
        session = get_session()
        try:
            for cam in session.query(AiCameraConfig).all():
                self._camera_cache[cam.id] = self._orm_to_dict(cam)
        finally:
            session.close()

    def get_camera_config(self, camera_id: int) -> Optional[dict]:
        """按 camera_id 查询摄像头配置，未命中时返回 None。"""
        return self._camera_cache.get(camera_id)

    def refresh_camera(self, camera_id: int):
        """
        单条热更新摄像头缓存。

        数据库中该摄像头已删除时，同步移除摄像头及其关联功能缓存；
        存在时重新读取最新值并覆盖。
        已缓存的关联功能配置会自动同步 name/shm_name/department 等注入字段；
        新增或修改功能自身配置时，仍需调用 refresh_function() 加载。
        """
        from AiVision.cameras.orm import AiCameraConfig
        session = get_session()
        try:
            cam = session.get(AiCameraConfig, camera_id)
            with self._lock:
                if cam is None:
                    self._camera_cache.pop(camera_id, None)  # 已删除，移出缓存
                    for key in [key for key in self._function_cache if key[0] == camera_id]:
                        self._function_cache.pop(key, None)
                else:
                    self._camera_cache[camera_id] = self._orm_to_dict(cam)  # 还存在，直接覆盖旧值
                    for key, cfg in list(self._function_cache.items()):
                        if key[0] == camera_id:
                            self._function_cache[key] = self._enrich_function_config(cfg)
            logger.info(f"[ConfigCache] 刷新摄像头: camera_id={camera_id}")
        finally:
            session.close()

    # ------------------------------------------------------------------ #
    #  功能配置缓存                                                         #
    # ------------------------------------------------------------------ #

    def _load_function_configs(self):
        """
        通过 features 注册表反射，全量加载所有功能的摄像头配置。

        遍历 all_specs() 中每个已注册功能的 orm_class，无需硬编码具体表名。
        每条配置经 _enrich_function_config() 注入摄像头基础字段后存入缓存。
        新增功能只需在 features 注册表中注册，此处自动覆盖，无需修改本文件。
        """
        from AiVision.features.registry import all_specs
        session = get_session()
        try:
            for spec in all_specs().values():
                for cfg in session.query(spec.orm_class).all():
                    key = (cfg.camera_id, spec.name)
                    # 每条配置经 _enrich_function_config() 注入摄像头基础字段后存入缓存。
                    self._function_cache[key] = self._enrich_function_config(
                        self._validated_function_dict(cfg, spec)
                    )
        finally:
            session.close()

    def get_function_config(self, camera_id: int, feature_name: str) -> Optional[dict]:
        """按 (camera_id, feature_name) 查询功能配置，未命中时返回 None。"""
        return self._function_cache.get((camera_id, feature_name))

    def get_all_function_configs(self) -> dict:
        """
        返回 _function_cache 的浅拷贝。

        调用方可安全遍历返回值而不持有内部锁；
        但字典中的配置 dict 仍为同一引用，不应被修改。
        """
        return dict(self._function_cache)

    def refresh_function(self, camera_id: int, feature_name: str):
        """
        单条热更新功能配置缓存。

        feature_name 未在 features 注册表中注册时静默返回。
        数据库中该配置已删除时，从缓存中移除对应条目；
        存在时重新读取并重新注入摄像头基础字段后覆盖。
        """
        from AiVision.features.registry import get_spec
        spec = get_spec(feature_name)
        if spec is None:
            return  # 未注册的功能，无法定位 ORM 表，跳过

        session = get_session()
        try:
            cfg = session.query(spec.orm_class).filter_by(camera_id=camera_id).first()
            with self._lock:
                key = (camera_id, feature_name)
                if cfg is None:
                    self._function_cache.pop(key, None)
                    logger.info(f"[ConfigCache] 删除功能配置: {key}")
                else:
                    # 覆盖内存
                    self._function_cache[key] = self._enrich_function_config(self._validated_function_dict(cfg, spec))
                    logger.info(f"[ConfigCache] 刷新功能配置: {key}")
        finally:
            session.close()

    # ------------------------------------------------------------------ #
    #  工具方法                                                             #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _validated_function_dict(cfg, spec) -> dict:
        """配置入口校验完整数据库记录；运行时只使用平铺字段，不接受另一种格式。"""
        validated = spec.config_schema.model_validate(cfg.to_config_dict()).model_dump()
        result = ConfigCache._orm_to_dict(cfg)
        result.update(validated["value"])
        return result

    @staticmethod
    def _orm_to_dict(obj) -> dict:
        """将 SQLAlchemy ORM 实例转为普通字典，仅包含表列字段。"""
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    
    def _enrich_function_config(self, cfg: dict) -> dict:
        """
        将摄像头基础信息注入功能配置字典，避免 Consumer 运行时二次查表。

        注入字段:
            name          : 摄像头展示名称，用于告警消息。
            shm_name      : 共享内存键名，Consumer 据此读取视频帧；
                            数据库中为空时回退到 "camera_{camera_id}"。
            camera_enable : 摄像头总开关，Consumer 可据此跳过已禁用的摄像头。

        摄像头信息缺失（_camera_cache 中无对应条目）时原样返回，不修改 cfg。
        """
        camera = self._camera_cache.get(cfg.get("camera_id")) or {}
        if camera:
            cfg = dict(cfg)  # 浅拷贝，避免修改调用方持有的原始字典
            cfg["name"]          = camera.get("name")
            cfg["shm_name"]      = camera.get("shm_name") or f"camera_{cfg.get('camera_id')}"   # 如果没有shm_name就自动使用camera_id作为共享内存的名字
            cfg["camera_enable"] = camera.get("enable")
            cfg["department"]    = camera.get("department")
        return cfg


# 模块级全局单例
# 系统启动时由 Orchestrator 调用 config_cache.init()；
# 运行时各模块直接 `from AiVision.core.cache import config_cache` 使用。
config_cache = ConfigCache()
