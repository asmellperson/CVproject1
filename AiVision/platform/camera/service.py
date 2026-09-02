# 文件说明：封装业务服务的业务规则与持久化访问。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
platform/camera/service.py
摄像头 CRUD 服务 — 替代旧 SQL 类里的 get_all_camera / get_camera_by_key /
save_to_database / save_camera_with_function_config 等方法。

新版本职责更窄:只管摄像头主表(ai_camera_config),功能配置由 features/_base/service.py 管。
"""
from __future__ import annotations
from time import sleep
from typing import Optional
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, OperationalError

from core.db import session_scope, get_session
from core.events import config_event_bus, ConfigChangeEvent
from core.cache import config_cache
from core.logger import logger
from features import all_specs
from .orm import AiCameraConfig


_MYSQL_RETRYABLE_LOCK_ERRORS = frozenset({1205, 1213})
_MAX_WRITE_ATTEMPTS = 3
_WRITE_RETRY_BACKOFF_SECONDS = 0.02


# 功能：解析摄像头所属的有效事业部；显式归属优先，历史空归属摄像头按已启用功能的事业部声明推导。
# 参数：
#   - `camera`（dict）：摄像头响应对象，包含 `department` 与 `functions` 字段
#   - `specs`（dict | None）：功能注册表；默认读取 `all_specs()`
# 返回：set[str]；返回该摄像头允许归属的事业部标识集合。
# 调用关系：
#   - 调用方：`CameraService.list_cameras`、`api/cameras.py` 的摄像头列表与详情权限校验调用本符号
#   - 内部调用：`camera.get`、`str`、`strip`、`isinstance`、`all_specs`、`getattr`、`set.add`。
# 副作用/注意事项：不修改摄像头或数据库；仅在显式归属为空时启用历史兼容推导，未启用任何功能时返回空集合。
def camera_access_departments(
    camera: dict,
    specs: dict | None = None,
) -> set[str]:
    explicit_department = str(camera.get("department") or "").strip()
    if explicit_department:
        return {explicit_department}

    functions = camera.get("functions")
    if isinstance(functions, dict):
        enabled_features = {
            str(feature_name)
            for feature_name, enabled in functions.items()
            if enabled
        }
    elif isinstance(functions, (list, tuple, set)):
        enabled_features = {str(feature_name) for feature_name in functions}
    else:
        enabled_features = set()

    feature_specs = specs if specs is not None else all_specs()
    departments: set[str] = set()
    for feature_name in enabled_features:
        spec = feature_specs.get(feature_name)
        if spec is None:
            continue
        for department in getattr(spec, "departments", ()):
            normalized = str(department or "").strip()
            if normalized:
                departments.add(normalized)
    return departments


# 功能：按功能表批量读取摄像头启用状态，查询次数只随功能数量增长；输入与输出详见下方说明
# 参数：
#   - `session`（未显式标注）：数据库会话或运行会话
#   - `camera_ids`（list[int]）：`camera_ids` 对应的业务输入值
#   - `specs`（dict）：`specs` 对应的业务输入值
# 返回：dict[int, dict[str, bool]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/camera/service.py` 的 `CameraService::list_cameras` 调用本符号；`AiVision/platform/camera/service.py` 的
#         `CameraService::get_camera` 调用本符号
#   - 内部调用：`specs.items`、`session.query(spec.orm_class.camera_id,
#          spec.orm_class.enable).filter(spec.orm_class.camera_id.in_(camera_ids)).all`、`session.query(spec.orm_class.camera_id,
#          spec.orm_class.enable).filter`、`session.query`、`spec.orm_class.camera_id.in_`、`bool`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _load_function_states(session, camera_ids: list[int], specs: dict) -> dict[int, dict[str, bool]]:
    """按功能表批量读取摄像头启用状态，查询次数只随功能数量增长。"""
    states = {
        camera_id: {feature_name: False for feature_name in specs}
        for camera_id in camera_ids
    }
    if not camera_ids:
        return states

    for feature_name, spec in specs.items():
        rows = (
            session.query(spec.orm_class.camera_id, spec.orm_class.enable)
            .filter(spec.orm_class.camera_id.in_(camera_ids))
            .all()
        )
        for camera_id, enabled in rows:
            states[camera_id][feature_name] = bool(enabled)
    return states


# 功能：实现 `_database_error_code` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `exc`（OperationalError）：`exc` 对应的业务输入值
# 返回：int | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/camera/service.py` 的 `CameraService::_run_write_transaction` 调用本符号
#   - 内部调用：`getattr`、`isinstance`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _database_error_code(exc: OperationalError) -> int | None:
    args = getattr(exc.orig, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


# 功能：只把可识别的摄像头唯一键冲突映射为对应字段冲突；输入与输出详见下方说明
# 参数：
#   - `exc`（IntegrityError）：`exc` 对应的业务输入值
# 返回：ValueError；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/camera/service.py` 的 `CameraService::create_camera` 调用本符号；`AiVision/platform/camera/service.py` 的
#         `CameraService::create_camera_for_feature` 调用本符号
#   - 内部调用：`str(exc.orig or exc).lower`、`str`、`ValueError`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _camera_integrity_value_error(exc: IntegrityError) -> ValueError:
    """只把可识别的摄像头唯一键冲突映射为对应字段冲突。"""
    message = str(exc.orig or exc).lower()
    if (
        "ai_camera_config.shm_name" in message
        or "ai_camera_config_shm_name" in message
        or "shm_name" in message
    ):
        return ValueError("shm_name 已存在")
    if "ai_camera_config.name" in message or "ai_camera_config_name" in message:
        return ValueError("name 已存在")
    return ValueError("摄像头数据约束冲突")


# 功能：摄像头主表的所有操作；输入与输出详见下方说明
# 参数：无。
# 返回：CameraService；返回新建的 `CameraService` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class CameraService:
    """摄像头主表的所有操作"""

    # ---------- Read ----------

    # 功能：返回摄像头列表(基础信息 + 各功能启用状态)，可选按部门过滤；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（Optional[str]）：业务部门名称或标识；默认值为 `None`
    # 返回：list[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`get_session`、`session.query`、`query.filter`、`or_`、`query.order_by(AiCameraConfig.id).all`、`all_specs`、`_load_function_states`、`self._to_dict`、`camera_access_departments`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_cameras(self, department: Optional[str] = None) -> list[dict]:
        """返回摄像头列表(基础信息 + 各功能启用状态)，可选按部门过滤"""
        session = get_session()
        try:
            query = session.query(AiCameraConfig)
            if department:
                query = query.filter(or_(
                    AiCameraConfig.department == department,
                    AiCameraConfig.department.is_(None),
                    AiCameraConfig.department == "",
                ))
            cameras = query.order_by(AiCameraConfig.id).all()
            specs = all_specs()
            function_states = _load_function_states(
                session,
                [cam.id for cam in cameras],
                specs,
            )
            items = [
                self._to_dict(cam, function_states[cam.id])
                for cam in cameras
            ]
            if department:
                items = [
                    camera for camera in items
                    if department in camera_access_departments(camera, specs)
                ]
            return items
        finally:
            session.close()

    # 功能：按 shm_name / name / id / 'camera_{id}' 任一格式查询；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：Optional[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/service.py` 的 `CameraService::create_camera` 调用本符号；`AiVision/platform/camera/service.py` 的
    #         `CameraService::create_camera_for_feature` 调用本符号；`AiVision/platform/camera/service.py` 的
    #         `CameraService::update_camera` 调用本符号
    #   - 内部调用：`get_session`、`self._get_orm_by_key`、`all_specs`、`_load_function_states`、`self._to_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_camera(self, key: str) -> Optional[dict]:
        """按 shm_name / name / id / 'camera_{id}' 任一格式查询"""
        session = get_session()
        try:
            cam = self._get_orm_by_key(session, key)
            if cam is None:
                return None
            specs = all_specs()
            functions = _load_function_states(session, [cam.id], specs)[cam.id]
            return self._to_dict(cam, functions)
        finally:
            session.close()

    # ---------- Write ----------

    # 功能：新增摄像头 — 同时为每个已注册 feature 建一行默认空配置(enable=False)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `payload`（dict）：接口或事件携带的业务数据
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._run_write_transaction`、`_camera_integrity_value_error`、`logger.warning`、`self.notify_camera_created`、`self.get_camera`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    def create_camera(self, payload: dict) -> dict:
        """新增摄像头 — 同时为每个已注册 feature 建一行默认空配置(enable=False)"""
        # 功能：创建或构建 `create_record` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self.create_camera_record`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def create_record(session):
            cam = self.create_camera_record(session, payload)
            return cam.id, cam.shm_name

        try:
            cam_id, cam_shm = self._run_write_transaction(create_record)
        except IntegrityError as exc:
            error = _camera_integrity_value_error(exc)
            logger.warning(f"[CameraService] 摄像头创建约束冲突: {error}")
            raise error from exc

        self.notify_camera_created(cam_id, cam_shm)
        return self.get_camera(cam_shm)

    # 功能：在同一事务中新增摄像头并启用指定普通检测功能；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `payload`（dict）：接口或事件携带的业务数据
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`ValueError`、`all_specs().get`、`all_specs`、`dict`、`tuple`、`values.get`、`len`、`',
    #          '.join`、`self._run_write_transaction`、`_camera_integrity_value_error` 等共 15 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    def create_camera_for_feature(self, feature_name: str, payload: dict) -> dict:
        """在同一事务中新增摄像头并启用指定普通检测功能。"""
        from platform.logistics_channel.constants import LOGISTICS_FEATURES

        if feature_name in LOGISTICS_FEATURES:
            raise ValueError("物流通道摄像头必须通过通道接口新建并绑定")
        spec = all_specs().get(feature_name)
        if spec is None:
            raise ValueError(f"unknown feature: {feature_name}")

        values = dict(payload)
        allowed_departments = tuple(spec.departments)
        requested_department = values.get("department")
        if allowed_departments:
            if not requested_department:
                if len(allowed_departments) != 1:
                    raise ValueError("department 是必填项")
                requested_department = allowed_departments[0]
            if requested_department not in allowed_departments:
                raise ValueError(
                    f"department 必须属于当前功能: {', '.join(allowed_departments)}"
                )
            values["department"] = requested_department

        # 功能：创建或构建 `create_record` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self.create_camera_record`、`session.query(spec.orm_class).filter_by(camera_id=cam.id).one`、`session.query(spec.orm_class).filter_by`、`session.query`、`session.flush`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def create_record(session):
            cam = self.create_camera_record(session, values)
            config = (
                session.query(spec.orm_class)
                .filter_by(camera_id=cam.id)
                .one()
            )
            config.enable = True
            session.flush()
            return cam.id, cam.shm_name

        try:
            cam_id, cam_shm = self._run_write_transaction(create_record)
        except IntegrityError as exc:
            error = _camera_integrity_value_error(exc)
            logger.warning(f"[CameraService] 摄像头创建约束冲突: {error}")
            raise error from exc

        self.notify_camera_created(cam_id, cam_shm)
        try:
            config_event_bus.publish(ConfigChangeEvent(
                change_type=f"{feature_name}_enabled",
                camera_id=cam_id,
                camera_name=cam_shm,
            ))
        except Exception as exc:
            logger.warning(
                f"[CameraService] 功能启用通知失败 feature={feature_name} "
                f"camera_id={cam_id}: {exc}"
            )
        return self.get_camera(cam_shm)

    # 功能：死锁/锁等待超时时使用全新 session 完整重跑，最多三次；输入与输出详见下方说明
    # 参数：
    #   - `operation`（未显式标注）：`operation` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/service.py` 的 `CameraService::create_camera` 调用本符号；`AiVision/platform/camera/service.py` 的
    #         `CameraService::create_camera_for_feature` 调用本符号
    #   - 内部调用：`range`、`session_scope`、`operation`、`_database_error_code`、`logger.warning`、`sleep`、`RuntimeError`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    @staticmethod
    def _run_write_transaction(operation):
        """死锁/锁等待超时时使用全新 session 完整重跑，最多三次。"""
        for attempt in range(1, _MAX_WRITE_ATTEMPTS + 1):
            try:
                with session_scope() as session:
                    return operation(session)
            except OperationalError as exc:
                code = _database_error_code(exc)
                if code not in _MYSQL_RETRYABLE_LOCK_ERRORS or attempt >= _MAX_WRITE_ATTEMPTS:
                    raise
                logger.warning(
                    f"[CameraService] 写事务锁冲突 code={code}, "
                    f"准备第 {attempt + 1}/{_MAX_WRITE_ATTEMPTS} 次尝试"
                )
                sleep(_WRITE_RETRY_BACKOFF_SECONDS * attempt)
        raise RuntimeError("unreachable")

    # 功能：在调用方事务内创建摄像头及所有默认功能配置，不提交或发事件；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `payload`（dict）：接口或事件携带的业务数据
    # 返回：AiCameraConfig；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/service.py` 的 `CameraService::create_camera::create_record`
    #         调用本符号；`AiVision/platform/camera/service.py` 的 `CameraService::create_camera_for_feature::create_record` 调用本符号
    #   - 内部调用：`(payload.get('name') or '').strip`、`payload.get`、`(payload.get('url') or '').strip`、`(payload.get('shm_name') or
    #          '').strip`、`int`、`bool`、`ValueError`、`session.query(AiCameraConfig).filter_by(name=name).first`、`session.query(AiCameraConfig).filter_by`、`session.query`
    #          等共 22 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
    def create_camera_record(self, session, payload: dict) -> AiCameraConfig:
        """在调用方事务内创建摄像头及所有默认功能配置，不提交或发事件。"""
        name = (payload.get("name") or "").strip()
        url = (payload.get("url") or "").strip()
        shm_name = (payload.get("shm_name") or "").strip()
        fps = int(payload.get("fps", 5))
        max_restart = int(payload.get("max_restart", 10))
        enable = bool(payload.get("enabled", payload.get("enable", True)))
        department = payload.get("department")

        if not (name and url):
            raise ValueError("name, url 都是必填")
        if fps <= 0:
            raise ValueError("fps must be > 0")
        if max_restart < 0:
            raise ValueError("max_restart must be >= 0")

        if session.query(AiCameraConfig).filter_by(name=name).first():
            raise ValueError(f"name 已存在: {name}")
        if shm_name and session.query(AiCameraConfig).filter_by(shm_name=shm_name).first():
            raise ValueError(f"shm_name 已存在: {shm_name}")

        # shm_name 非空且唯一，先用随机内部标识拿到自增 ID，再稳定替换为 camera_<id>。
        pending_shm = shm_name or f"__pending_camera_{uuid4().hex}"
        cam = AiCameraConfig(
            name=name, url=url, shm_name=pending_shm,
            fps=fps, max_restart=max_restart, enable=enable,
            function_config={},
            department=department,
        )
        session.add(cam)
        session.flush()
        if not shm_name:
            stable_shm = f"camera_{cam.id}"
            conflict = (
                session.query(AiCameraConfig)
                .filter(AiCameraConfig.shm_name == stable_shm, AiCameraConfig.id != cam.id)
                .first()
            )
            if conflict is not None:
                raise ValueError(f"shm_name 已存在: {stable_shm}")
            cam.shm_name = stable_shm

        for spec in all_specs().values():
            existing = session.query(spec.orm_class).filter_by(camera_id=cam.id).first()
            if existing is None:
                session.add(spec.orm_class(camera_id=cam.id, enable=False))
        session.flush()
        return cam

    # 功能：事务提交后刷新缓存并发布新增事件；通知失败不回滚已提交数据；输入与输出详见下方说明
    # 参数：
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `shm_name`（str）：摄像头共享内存名称
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/service.py` 的 `CameraService::create_camera` 调用本符号；`AiVision/platform/camera/service.py` 的
    #         `CameraService::create_camera_for_feature` 调用本符号
    #   - 内部调用：`config_cache.refresh_camera`、`all_specs`、`config_cache.refresh_function`、`config_event_bus.publish`、`ConfigChangeEvent`、`logger.warning`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    @staticmethod
    def notify_camera_created(camera_id: int, shm_name: str) -> None:
        """事务提交后刷新缓存并发布新增事件；通知失败不回滚已提交数据。"""
        try:
            config_cache.refresh_camera(camera_id)
            for feature_name in all_specs():
                config_cache.refresh_function(camera_id, feature_name)
            config_event_bus.publish(ConfigChangeEvent(
                change_type="camera_added",
                camera_id=camera_id,
                camera_name=shm_name,
            ))
        except Exception as exc:
            logger.warning(f"[CameraService] 摄像头新增通知失败 camera_id={camera_id}: {exc}")

    # 功能：更新摄像头基础信息 — 不动功能配置；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    #   - `payload`（dict）：接口或事件携带的业务数据
    # 返回：Optional[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`self._get_orm_by_key`、`self._event_snapshot`、`setattr`、`bool`、`session.flush`、`config_cache.refresh_camera`、`all_specs`、`config_cache.refresh_function`、`config_event_bus.publish`
    #          等共 12 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_camera(self, key: str, payload: dict) -> Optional[dict]:
        """更新摄像头基础信息 — 不动功能配置"""
        with session_scope() as session:
            cam = self._get_orm_by_key(session, key)
            if cam is None:
                return None
            old_value = self._event_snapshot(cam)
            for field in ("name", "url", "fps", "max_restart", "department"):
                if field in payload:
                    setattr(cam, field, payload[field])
            if "enabled" in payload:
                cam.enable = bool(payload["enabled"])
            elif "enable" in payload:
                cam.enable = bool(payload["enable"])
            session.flush()
            new_value = self._event_snapshot(cam)
            cam_id, cam_shm = cam.id, cam.shm_name

        config_cache.refresh_camera(cam_id)
        for fname in all_specs():
            config_cache.refresh_function(cam_id, fname)
        config_event_bus.publish(ConfigChangeEvent(
            change_type="camera_updated",
            camera_id=cam_id,
            camera_name=cam_shm,
            old_value=old_value,
            new_value=new_value,
        ))
        return self.get_camera(cam_shm)

    # 功能：删除或清理 `delete_camera` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`self._get_orm_by_key`、`session.delete`、`config_event_bus.publish`、`ConfigChangeEvent`、`config_cache.reload`。
    # 副作用/注意事项：可能读取或修改数据库事务。
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

    # 功能：补齐空 shm_name(用 camera_{id})；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`session.query(AiCameraConfig).all`、`session.query`、`(c.shm_name or '').strip`、`(cam.shm_name or
    #          '').strip`、`used.add`、`logger.info`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
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

    # 功能：为每个摄像头补齐所有 feature 的配置行(若不存在)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `enable_all`（bool）：`enable_all` 对应的业务输入值；默认值为 `False`
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`session.query(AiCameraConfig).all`、`session.query`、`list`、`all_specs().values`、`all_specs`、`session.query(spec.orm_class).filter_by(camera_id=cam.id).first`、`session.query(spec.orm_class).filter_by`、`session.add`、`spec.orm_class`
    #          等共 11 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务；会向日志系统输出运行或异常信息。
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

    # 功能：读取或查询 `_get_orm_by_key` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：Optional[AiCameraConfig]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/service.py` 的 `CameraService::get_camera` 调用本符号；`AiVision/platform/camera/service.py` 的
    #         `CameraService::update_camera` 调用本符号；`AiVision/platform/camera/service.py` 的 `CameraService::delete_camera` 调用本符号
    #   - 内部调用：`(key or
    #          '').strip`、`key.isdigit`、`filters.append`、`int`、`key.startswith`、`key.removeprefix('camera_').isdigit`、`key.removeprefix`、`session.query(AiCameraConfig).filter(or_(*filters)).first`、`session.query(AiCameraConfig).filter`、`session.query`
    #          等共 11 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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

    # 功能：转换或规范化 `_to_dict` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cam`（AiCameraConfig）：`cam` 对应的业务输入值
    #   - `functions`（dict[str, bool]）：`functions` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/service.py` 的 `CameraService::list_cameras` 调用本符号；`AiVision/platform/camera/service.py` 的
    #         `CameraService::get_camera` 调用本符号
    #   - 内部调用：`bool`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
            "department": cam.department,
            "functions": functions,
        }

    # 功能：实现 `_event_snapshot` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cam`（AiCameraConfig）：`cam` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/service.py` 的 `CameraService::update_camera` 调用本符号
    #   - 内部调用：`bool`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _event_snapshot(cam: AiCameraConfig) -> dict:
        return {
            "id": cam.id,
            "name": cam.name,
            "shm_name": cam.shm_name or f"camera_{cam.id}",
            "url": cam.url,
            "fps": cam.fps,
            "max_restart": cam.max_restart,
            "enabled": bool(cam.enable),
            "department": cam.department,
        }


camera_service = CameraService()
