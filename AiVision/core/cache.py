# 文件说明：实现`cache` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：摄像头基础信息 + 功能配置的进程内内存缓存；输入与输出详见下方说明
# 参数：无。
# 返回：ConfigCache；返回新建的 `ConfigCache` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
        写操作（init/reload/refresh_*）通过 _lock 保护；
        读操作（get_*）不加锁，依赖 CPython GIL 保证字典读取的原子性。
    """

    # 功能：初始化或配置 `__init__` 对应的`cache` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`threading.Lock`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(self):
        # {camera_id: dict} — 摄像头基础信息，由 _load_cameras() 填充
        self._camera_cache: dict[int, dict] = {}
        # {(camera_id, feature_name): dict} — 功能配置，由 _load_function_configs() 填充
        self._function_cache: dict[tuple[int, str], dict] = {}
        self._lock = threading.Lock()   # 保护缓存字典的写操作
        self._initialized = False       # 防止 init() 被重复调用

    # 功能：启动时一次性全量加载，须在 features 注册表初始化完成后调用；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/core/cache.py` 的 `ConfigCache::reload` 调用本符号；`AiVision/platform/orchestrator.py` 的 `Orchestrator::start`
    #         调用本符号
    #   - 内部调用：`logger.info`、`self._load_cameras`、`self._load_function_configs`、`len`。
    # 副作用/注意事项：会更新当前实例的运行状态；会向日志系统输出运行或异常信息。
    def init(self):
        """
        启动时一次性全量加载，须在 features 注册表初始化完成后调用。

        _load_function_configs() 依赖 features.all_specs() 做反射，
        若在注册完成前调用将漏载部分功能配置。
        重复调用时幂等（_initialized 守护）。
        """
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

    # 功能：清空并全量重载所有缓存；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._camera_cache.clear`、`self._function_cache.clear`、`self.init`。
    # 副作用/注意事项：会更新当前实例的运行状态。
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

    # 功能：从数据库全量加载摄像头基础配置到 _camera_cache；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/core/cache.py` 的 `ConfigCache::init` 调用本符号
    #   - 内部调用：`get_session`、`session.query(AiCameraConfig).all`、`session.query`、`self._orm_to_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _load_cameras(self):
        """从数据库全量加载摄像头基础配置到 _camera_cache。"""
        from platform.camera.orm import AiCameraConfig
        session = get_session()
        try:
            for cam in session.query(AiCameraConfig).all():
                self._camera_cache[cam.id] = self._orm_to_dict(cam)
        finally:
            session.close()

    # 功能：按 camera_id 查询摄像头配置，未命中时返回 None；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：Optional[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._camera_cache.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_camera_config(self, camera_id: int) -> Optional[dict]:
        """按 camera_id 查询摄像头配置，未命中时返回 None。"""
        return self._camera_cache.get(camera_id)

    # 功能：单条热更新摄像头缓存；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`get_session`、`session.query(AiCameraConfig).get`、`session.query`、`self._camera_cache.pop`、`self._orm_to_dict`、`logger.info`、`session.close`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def refresh_camera(self, camera_id: int):
        """
        单条热更新摄像头缓存。

        数据库中该摄像头已删除时，同步从缓存中移除；
        存在时重新读取最新值并覆盖。
        注意：摄像头更新后其关联的功能配置缓存（_function_cache）不会自动
        同步 name/shm_name 等注入字段，必要时需同步调用 refresh_function()。
        """
        from platform.camera.orm import AiCameraConfig
        session = get_session()
        try:
            cam = session.query(AiCameraConfig).get(camera_id)
            with self._lock:
                if cam is None:
                    self._camera_cache.pop(camera_id, None)  # 已删除，移出缓存
                else:
                    self._camera_cache[camera_id] = self._orm_to_dict(cam)
            logger.info(f"[ConfigCache] 刷新摄像头: camera_id={camera_id}")
        finally:
            session.close()

    # ------------------------------------------------------------------ #
    #  功能配置缓存                                                         #
    # ------------------------------------------------------------------ #

    # 功能：通过 features 注册表反射，全量加载所有功能的摄像头配置；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/core/cache.py` 的 `ConfigCache::init` 调用本符号
    #   - 内部调用：`get_session`、`all_specs().values`、`all_specs`、`session.query(spec.orm_class).all`、`session.query`、`self._enrich_function_config`、`self._orm_to_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _load_function_configs(self):
        """
        通过 features 注册表反射，全量加载所有功能的摄像头配置。

        遍历 all_specs() 中每个已注册功能的 orm_class，无需硬编码具体表名。
        每条配置经 _enrich_function_config() 注入摄像头基础字段后存入缓存。
        新增功能只需在 features 注册表中注册，此处自动覆盖，无需修改本文件。
        """
        from features import all_specs
        session = get_session()
        try:
            for spec in all_specs().values():
                for cfg in session.query(spec.orm_class).all():
                    key = (cfg.camera_id, spec.name)
                    self._function_cache[key] = self._enrich_function_config(
                        self._orm_to_dict(cfg)
                    )
        finally:
            session.close()

    # 功能：按 (camera_id, feature_name) 查询功能配置，未命中时返回 None；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：Optional[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._function_cache.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_function_config(self, camera_id: int, feature_name: str) -> Optional[dict]:
        """按 (camera_id, feature_name) 查询功能配置，未命中时返回 None。"""
        return self._function_cache.get((camera_id, feature_name))

    # 功能：返回 _function_cache 的浅拷贝；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_load_initial_configs`
    #         调用本符号；`AiVision/platform/inference/runtime_manager.py` 的 `InferenceRuntimeManager::_collect_initial_configs` 调用本符号
    #   - 内部调用：`dict`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_all_function_configs(self) -> dict:
        """
        返回 _function_cache 的浅拷贝。

        调用方可安全遍历返回值而不持有内部锁；
        但字典中的配置 dict 仍为同一引用，不应被修改。
        """
        return dict(self._function_cache)

    # 功能：单条热更新功能配置缓存；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`get_spec`、`get_session`、`session.query(spec.orm_class).filter_by(camera_id=camera_id).first`、`session.query(spec.orm_class).filter_by`、`session.query`、`self._function_cache.pop`、`logger.info`、`self._enrich_function_config`、`self._orm_to_dict`、`session.close`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def refresh_function(self, camera_id: int, feature_name: str):
        """
        单条热更新功能配置缓存。

        feature_name 未在 features 注册表中注册时静默返回。
        数据库中该配置已删除时，从缓存中移除对应条目；
        存在时重新读取并重新注入摄像头基础字段后覆盖。
        """
        from features import get_spec
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
                    self._function_cache[key] = self._enrich_function_config(self._orm_to_dict(cfg))
                    logger.info(f"[ConfigCache] 刷新功能配置: {key}")
        finally:
            session.close()

    # ------------------------------------------------------------------ #
    #  工具方法                                                             #
    # ------------------------------------------------------------------ #

    # 功能：将 SQLAlchemy ORM 实例转为普通字典，仅包含表列字段；输入与输出详见下方说明
    # 参数：
    #   - `obj`（未显式标注）：`obj` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/core/cache.py` 的 `ConfigCache::_load_cameras` 调用本符号；`AiVision/core/cache.py` 的 `ConfigCache::refresh_camera`
    #         调用本符号；`AiVision/core/cache.py` 的 `ConfigCache::_load_function_configs` 调用本符号；`AiVision/core/cache.py` 的
    #         `ConfigCache::refresh_function` 调用本符号
    #   - 内部调用：`getattr`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _orm_to_dict(obj) -> dict:
        """将 SQLAlchemy ORM 实例转为普通字典，仅包含表列字段。"""
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}

    # 功能：将摄像头基础信息注入功能配置字典，避免 Consumer 运行时二次查表；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `cfg`（dict）：运行配置对象
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/core/cache.py` 的 `ConfigCache::_load_function_configs` 调用本符号；`AiVision/core/cache.py` 的
    #         `ConfigCache::refresh_function` 调用本符号
    #   - 内部调用：`self._camera_cache.get`、`cfg.get`、`dict`、`camera.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
            cfg["shm_name"]      = camera.get("shm_name") or f"camera_{cfg.get('camera_id')}"
            cfg["camera_enable"] = camera.get("enable")
        return cfg


# 模块级全局单例
# 系统启动时由 Orchestrator 调用 config_cache.init()；
# 运行时各模块直接 `from core.cache import config_cache` 使用。
config_cache = ConfigCache()
