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


def _database_error_code(exc: OperationalError) -> int | None:
    args = getattr(exc.orig, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


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


class CameraService:
    """摄像头主表的所有操作"""

    # ---------- Read ----------

    def list_cameras(self, department: Optional[str] = None) -> list[dict]:
        """返回摄像头列表(基础信息 + 各功能启用状态)，可选按部门过滤"""
        session = get_session()
        try:
            query = session.query(AiCameraConfig)
            if department:
                query = query.filter(AiCameraConfig.department == department)
            cameras = query.order_by(AiCameraConfig.id).all()
            specs = all_specs()
            function_states = _load_function_states(
                session,
                [cam.id for cam in cameras],
                specs,
            )
            return [
                self._to_dict(cam, function_states[cam.id])
                for cam in cameras
            ]
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
            functions = _load_function_states(session, [cam.id], specs)[cam.id]
            return self._to_dict(cam, functions)
        finally:
            session.close()

    # ---------- Write ----------

    def create_camera(self, payload: dict) -> dict:
        """新增摄像头 — 同时为每个已注册 feature 建一行默认空配置(enable=False)"""
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
            "department": cam.department,
            "functions": functions,
        }

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
