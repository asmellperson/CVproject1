"""
platform/camera/config_manager.py
CameraConfigManager管理摄像头的配置数据，并在数据发生变化以后把变化传播到Cache和Runtime
查询：
    list_cameras()
    get_camera()
创建：
    create_camera()
    create_camera_for_feature()
    create_camera_recode()
修改：
    update_camera()
删除：
    delete_camera()
历史数据维护： 
    normalize_shm_names()
    ensure_feature_configs()
Helper:
    _get_orm_by_key()
    _to_dict()
    _event_snapshot()

"""
from __future__ import annotations
from time import sleep
from typing import Optional
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, OperationalError

from AiVision.core.db import session_scope, get_session     # 查数据库，写数据库
from AiVision.core.events import config_event_bus, ConfigChangeEvent      # configChangeEvent：告诉Orchestrator配置变了
from AiVision.core.cache import config_cache         # 摄像头配置改完后刷新内存缓存
from AiVision.core.logger import logger
from AiVision.features import all_specs
from AiVision.platform.department.department_registry import require_department
from AiVision.features.detect_logistics_single_person.constants import LOGISTICS_FEATURE_NAME
from .orm import AiCameraConfig, get_camera_by_key             # 摄像头数据库表

# 数据库写入时碰到1205/1213要稍微等一下会进行重启并且重试3次，1205：Lock wait timeout等数据库锁超时。1213：Deadlock数据库死锁。
_MYSQL_RETRYABLE_LOCK_ERRORS = frozenset({1205, 1213})
_MAX_WRITE_ATTEMPTS = 3
_WRITE_RETRY_BACKOFF_SECONDS = 0.02

def camera_access_departments(
    camera: dict,
    specs: dict | None = None,
) -> set[str]:
    """判断当前摄像头应该被哪些事业部看到"""
    # 返回的是多个部门的集合
    explicit_department = str(camera.get("department") or "").strip()
    if explicit_department:
        return {explicit_department}
    # 这个摄像头分别开了哪些功能
    functions = camera.get("functions")
    # 如果是字典，只取enable=True的Feature
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
    
    # 把启用的Feature对应部门全部收集起来
    feature_specs = specs if specs is not None else all_specs()
    departments: set[str] = set()
    for feature_name in enabled_features:
        # 统一物流 Feature 覆盖四个事业部，不能用它推断空归属 Camera 的可见范围。
        if feature_name == LOGISTICS_FEATURE_NAME:
            continue
        spec = feature_specs.get(feature_name)
        if spec is None:
            continue
        for department in getattr(spec, "departments", ()):
            normalized = str(department or "").strip()
            if normalized:
                departments.add(normalized)
    return departments

def _load_function_states(session, camera_ids: list[int], specs: dict) -> dict[int, dict[str, bool]]:
    """批量查出每台摄像头分别开启了哪些Feature。"""
    # 先全部设为False（即使某个Feature表里没有这台摄像头的记录，默认也是False）
    states = {
        camera_id: {feature_name: False for feature_name in specs}
        for camera_id in camera_ids
    }
    if not camera_ids:
        return states
    # 逐个Feature表查询
    for feature_name, spec in specs.items():
        rows = (
            session.query(spec.orm_class.camera_id, spec.orm_class.enable)
            .filter(spec.orm_class.camera_id.in_(camera_ids))
            .all()
        )
        for camera_id, enabled in rows:
            states[camera_id][feature_name] = bool(enabled)
    return states

def _database_error_code(exc: OperationalError) -> int | None:
    """从SQLAIchemy的operationalError里面把MySQL错误码挖出来"""
    args = getattr(exc.orig, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None

def _camera_integrity_value_error(exc: IntegrityError) -> ValueError:
    """把数据库的唯一约束错误，转换成用户更容易理解的业务错误"""
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

class CameraConfigManager:
    """摄像头主表的所有操作"""

    # ---------- Read ----------
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

    def get_camera(self, key: str | int) -> Optional[dict]:
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
    def create_camera(self, payload: dict) -> dict:
        """新增摄像头 — 同时为每个已注册 feature 建一行默认空配置(enable=False)"""
        def create_record(session):
            # create_camera_record():真正往数据库里创建摄像头及默认Feature配置
            cam = self.create_camera_record(session, payload)
            return cam.id, cam.shm_name

        try:
            # 安全的执行数据库写事务，如果碰到MySQL死锁/锁等待，可以自动重新开事务重试
            cam_id, cam_shm = self._run_write_transaction(create_record)
        # 将数据库错误变成业务友好错误
        except IntegrityError as exc:
            error = _camera_integrity_value_error(exc)
            logger.warning(f"[CameraConfigManager] 摄像头创建约束冲突: {error}")
            raise error from exc
        # 数据库已经提交成功，将其通知到内存事件
        self.notify_camera_created(cam_id, cam_shm)
        # 重新从数据库查一次完整结果
        return self.get_camera(cam_shm)
    
    def create_camera_for_feature(self, feature_name: str, payload: dict) -> dict:
        """在具体功能页面里新增摄像头，新增后直接启用这个功能。"""
        from AiVision.features.detect_logistics_single_person.constants import LOGISTICS_FEATURES
        # 物流通道不走这里
        if feature_name in LOGISTICS_FEATURES:
            raise ValueError("物流通道摄像头必须通过通道接口新建并绑定")
        # 检查功能是否存在
        spec = all_specs().get(feature_name)
        if spec is None:
            raise ValueError(f"unknown feature: {feature_name}")

        values = dict(payload)
        # 但是新建的摄像头只能选一个部门
        values["department"] = spec.resolve_camera_department(values.get("department"))

        def create_record(session):
            # create_camera_record会同时给所有功能建默认配置
            cam = self.create_camera_record(session, values)
            # 当前指定功能的那一行配置
            config = (
                session.query(spec.orm_class)
                .filter_by(camera_id=cam.id)
                .one()
            )
            # 只将摄像头开启当前功能
            config.enable = True
            session.flush()
            return cam.id, cam.shm_name

        try:
            cam_id, cam_shm = self._run_write_transaction(create_record)
        except IntegrityError as exc:
            error = _camera_integrity_value_error(exc)
            logger.warning(f"[CameraConfigManager] 摄像头创建约束冲突: {error}")
            raise error from exc
        # 发布摄像头增加事件
        self.notify_camera_created(cam_id, cam_shm)
        try:
            config_event_bus.publish(ConfigChangeEvent(
                change_type=f"{feature_name}_enabled",
                camera_id=cam_id,
                camera_name=cam_shm,
            ))
        except Exception as exc:
            logger.warning(
                f"[CameraConfigManager] 功能启用通知失败 feature={feature_name} "
                f"camera_id={cam_id}: {exc}"
            )
        return self.get_camera(cam_shm)

    @staticmethod
    def _run_write_transaction(operation):
        """死锁/锁等待超时时使用全新 session 完整重跑，最多三次。"""
        # 最多三次
        for attempt in range(1, _MAX_WRITE_ATTEMPTS + 1):
            try:
                # session_scope():进入 -> 执行数据库逻辑 -> 成功commit -> 失败rollback -> 关闭
                with session_scope() as session:
                    return operation(session)
            # 如果MySQL出现锁问题。1205 → lock wait timeout；1213 → deadlock
            except OperationalError as exc:
                code = _database_error_code(exc)
                if code not in _MYSQL_RETRYABLE_LOCK_ERRORS or attempt >= _MAX_WRITE_ATTEMPTS:
                    raise
                logger.warning(
                    f"[CameraConfigManager] 写事务锁冲突 code={code}, "
                    f"准备第 {attempt + 1}/{_MAX_WRITE_ATTEMPTS} 次尝试"
                )
                sleep(_WRITE_RETRY_BACKOFF_SECONDS * attempt)
        raise RuntimeError("unreachable")

    def create_camera_record(self, session, payload: dict) -> AiCameraConfig:
        """真正的创建摄像头数据库记录。"""
        name = (payload.get("name") or "").strip()
        url = (payload.get("url") or "").strip()
        shm_name = (payload.get("shm_name") or "").strip()
        fps = int(payload.get("fps", 5))
        max_restart = int(payload.get("max_restart", 10))
        enable = bool(payload.get("enabled", True))
        department = payload.get("department")
        if department is not None and department != "":
            require_department(department)
        # 基础校验
        if not (name and url):
            raise ValueError("name, url 都是必填")
        if fps <= 0:
            raise ValueError("fps must be > 0")
        if max_restart < 0:
            raise ValueError("max_restart must be >= 0")
        # 主动检查重复
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
        # 把当前SQL发给数据库，让数据库生成ID等信息
        session.flush()
        # 自动生成稳定shm_name
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
        # 创建所有功能默认配置
        for spec in all_specs().values():
            defaults = spec.config_schema().model_dump()
            cfg = spec.orm_class(camera_id=cam.id, enable=defaults["enable"])
            cfg.apply_config_dict(defaults)
            session.add(cfg)
        session.flush()
        return cam

    @staticmethod
    def notify_camera_created(camera_id: int, shm_name: str) -> None:
        """通知内存的函数"""
        try:
            # 把新Camera加进Camera Cache
            config_cache.refresh_camera(camera_id)
            for feature_name in all_specs():
                config_cache.refresh_function(camera_id, feature_name)
            # 告诉其他订阅者，新增了一台摄像头
            config_event_bus.publish(ConfigChangeEvent(
                change_type="camera_added",
                camera_id=camera_id,
                camera_name=shm_name,
            ))
        except Exception as exc:
            logger.warning(f"[CameraConfigManager] 摄像头新增通知失败 camera_id={camera_id}: {exc}")

    def update_camera(self, key: str, payload: dict) -> Optional[dict]:
        """更新摄像头基础信息 — 不动功能配置"""
        with session_scope() as session:
            # 根据key找到真正的AiCameraConfig数据库对象
            cam = self._get_orm_by_key(session, key)
            if cam is None:
                return None
            # _event_snapshot:把当前摄像头的重要运行配置复制成一个普通dict
            old_value = self._event_snapshot(cam)
            # 修改字段
            for field in ("name", "url", "fps", "max_restart", "department"):
                if field in payload:
                    if field == "department" and payload[field] is not None and payload[field] != "":
                        require_department(payload[field])
                    setattr(cam, field, payload[field])
            if "enabled" in payload:
                cam.enable = bool(payload["enabled"])
            # 把update发给数据库，但session_scope还没退出，所以事务还没正式commit
            session.flush()
            # 记录修改后的配置
            new_value = self._event_snapshot(cam)
            # 保存
            cam_id, cam_shm = cam.id, cam.shm_name

        # 刷新当前摄像头，并同步已缓存的关联功能字段
        config_cache.refresh_camera(cam_id)
        # 发布camera_updated
        config_event_bus.publish(ConfigChangeEvent(
            change_type="camera_updated",
            camera_id=cam_id,
            camera_name=cam_shm,
            old_value=old_value,
            new_value=new_value,
        ))
        # 最后再重新查一次，最终返回数据库里的完整状态以及功能状态
        return self.get_camera(cam_shm)

    def delete_camera(self, key: str) -> bool:
        """删除一台摄像头"""
        with session_scope() as session:
            cam = self._get_orm_by_key(session, key)
            if cam is None:
                return False
            cam_id, cam_shm = cam.id, cam.shm_name
            for spec in all_specs().values():
                session.query(spec.orm_class).filter_by(camera_id=cam_id).delete(
                    synchronize_session=False,
                )
            # 删除摄像头
            session.delete(cam)  # feature 配置已在同一事务中显式删除，不依赖 CASCADE
        # 提交后定向清理该摄像头及其功能缓存，再发布事件
        config_cache.refresh_camera(cam_id)
        # 发布删除摄像头事件
        config_event_bus.publish(ConfigChangeEvent(
            change_type="camera_removed",
            camera_id=cam_id, camera_name=cam_shm,
        ))
        return True

    # ---------- 维护工具 ----------
    def normalize_shm_names(self) -> int:
        """补齐空 shm_name(用 camera_{id})"""
        # 新数据已经要求shm_name不能为空，正常情况下不应该需要，主要服务以前的旧数据（启动时仍会调用）
        updated = 0
        with session_scope() as session:
            cameras = session.query(AiCameraConfig).all()
            # 先拿到所有已经使用的shm_name
            used = {(c.shm_name or "").strip() for c in cameras if (c.shm_name or "").strip()}
            # 找到空shm_name,有值跳过，没值开始修
            for cam in cameras:
                if (cam.shm_name or "").strip():
                    continue
                # 默认补camera_{cam_id}
                candidate = f"camera_{cam.id}"
                suffix = 1
                # 如果cam_x被人使用，那么变成cam_x_y,直到找到唯一值
                while candidate in used:
                    candidate = f"camera_{cam.id}_{suffix}"
                    suffix += 1
                cam.shm_name = candidate
                used.add(candidate)
                updated += 1
        if updated:
            logger.info(f"[CameraConfigManager] 已补齐 {updated} 个 shm_name")
        # 最终返回修改数量
        return updated

    def ensure_feature_configs(self) -> int:
        """
        为每个摄像头补齐所有 feature 的配置行(若不存在)。
        缺失行默认 enable=False，不改变已有配置的启用状态。
        """
        changed = 0
        with session_scope() as session:
            cameras = session.query(AiCameraConfig).all()
            specs = list(all_specs().values())
            for cam in cameras:
                for spec in specs:
                    cfg = session.query(spec.orm_class).filter_by(camera_id=cam.id).first()
                    if cfg is None:
                        defaults = spec.config_schema().model_dump()
                        cfg = spec.orm_class(camera_id=cam.id, enable=defaults["enable"])
                        cfg.apply_config_dict(defaults)
                        session.add(cfg)
                        changed += 1
        if changed:
            logger.info(f"[CameraConfigManager] 已补齐/启用 {changed} 条功能配置")
        return changed

    # ---------- Helpers ----------

    @staticmethod
    def _get_orm_by_key(session, key: str | int) -> Optional[AiCameraConfig]:
        """允许用多种形式找到同一台Camera
        camera_<id> 同时匹配自定义 shm_name 和 ID alias 时，优先 shm_name
        """
        # 字符串key先尝试shm_name，再尝试name，最后尝试数字或camera_<id>别名
        # 整数key直接按数据库主键查询
        return get_camera_by_key(session, key)

    @staticmethod
    def _to_dict(cam: AiCameraConfig, functions: dict[str, bool]) -> dict:
        """ORM转成API/业务dict"""
        return {
            "id": cam.shm_name or f"camera_{cam.id}",  # 前端用作 key（前端历史上把id当成字符串key使用）
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

    @staticmethod
    def _event_snapshot(cam: AiCameraConfig) -> dict:
        """专门给camera_update事件准备新老数据"""
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

# API共用camera_config_manager
camera_config_manager = CameraConfigManager()
