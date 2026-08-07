"""物流通道配置、成员绑定与旧配置迁移服务。"""
from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import selectinload

from core.cache import config_cache
from core.db import get_session, session_scope
from core.events import ConfigChangeEvent, config_event_bus
from core.logger import logger
from features import all_specs
from platform.camera.orm import AiCameraConfig
from platform.camera.service import (
    _camera_integrity_value_error,
    _database_error_code,
    camera_service,
)

from .constants import (
    LOGISTICS_FEATURE_DEPARTMENTS,
    LOGISTICS_FEATURES,
    MAX_CAMERAS_PER_CHANNEL,
    require_logistics_feature,
)
from .orm import LogisticsChannel, LogisticsChannelCamera
from .schema import LogisticsChannelDetailResponse, LogisticsChannelListResponse


_MYSQL_RETRYABLE_LOCK_ERRORS = frozenset({1205, 1213})
_MAX_WRITE_ATTEMPTS = 3
_WRITE_RETRY_BACKOFF_SECONDS = 0.02


class _MembershipLockSetChanged(RuntimeError):
    """非锁定预读后的成员归属已变化，需要用新事务重新确定锁集合。"""


@dataclass(frozen=True)
class _CameraRef:
    camera_id: int
    shm_name: str


@dataclass(frozen=True)
class _PendingNotification:
    channel_id: int
    feature_name: str
    camera_refs: tuple[_CameraRef, ...] = ()
    feature_action: str | None = None
    camera_added: _CameraRef | None = None


@dataclass(frozen=True)
class MigrationSummary:
    created: int
    skipped: int
    failed: int
    errors: tuple[str, ...] = ()


class LogisticsChannelService:
    """物流通道配置与摄像头成员管理入口。"""

    def list_channels(self, feature_name: str) -> dict:
        feature_name = require_logistics_feature(feature_name)
        session = get_session()
        try:
            channels = (
                session.query(LogisticsChannel)
                .filter_by(feature_name=feature_name)
                .order_by(LogisticsChannel.sort_order, LogisticsChannel.id)
                .all()
            )
            return LogisticsChannelListResponse.model_validate(
                {"items": channels}
            ).model_dump(mode="python")
        finally:
            session.close()

    def get_channel(self, feature_name: str, channel_id: int) -> dict | None:
        feature_name = require_logistics_feature(feature_name)
        session = get_session()
        try:
            channel = self._query_channel(session, feature_name, channel_id)
            return self._detail(channel) if channel is not None else None
        finally:
            session.close()

    def create_channel(self, feature_name: str, name: str) -> dict:
        feature_name = require_logistics_feature(feature_name)
        normalized_name = (name or "").strip()
        if not normalized_name:
            raise ValueError("通道名称不能为空")

        def create(session):
            duplicate = (
                session.query(LogisticsChannel)
                .filter_by(feature_name=feature_name, name=normalized_name)
                .first()
            )
            if duplicate is not None:
                raise ValueError(f"同一功能下通道名称已存在: {normalized_name}")
            channel = LogisticsChannel(name=normalized_name, feature_name=feature_name)
            session.add(channel)
            session.flush()
            return channel.id

        try:
            channel_id = self._run_write_transaction(create)
        except IntegrityError as exc:
            error = self._channel_integrity_value_error(exc)
            logger.warning(f"[LogisticsChannelService] 创建通道约束冲突: {error}")
            raise error from exc
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    def update_channel(self, feature_name: str, channel_id: int, payload: Any) -> dict | None:
        feature_name = require_logistics_feature(feature_name)
        values = self._payload_dict(payload)
        self._reject_none(values, ("enabled", "sort_order"))

        def update(session):
            channels = self._lock_channels(session, [channel_id])
            channel = channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                return False
            if "name" in values:
                name = (values["name"] or "").strip()
                if not name:
                    raise ValueError("通道名称不能为空")
                duplicate = (
                    session.query(LogisticsChannel)
                    .filter(
                        LogisticsChannel.feature_name == feature_name,
                        LogisticsChannel.name == name,
                        LogisticsChannel.id != channel_id,
                    )
                    .first()
                )
                if duplicate is not None:
                    raise ValueError(f"同一功能下通道名称已存在: {name}")
                channel.name = name
            for field in ("enabled", "sort_order"):
                if field in values:
                    setattr(channel, field, values[field])
            session.flush()
            return True

        try:
            updated = self._run_write_transaction(update)
        except IntegrityError as exc:
            error = self._channel_integrity_value_error(exc)
            logger.warning(f"[LogisticsChannelService] 更新通道约束冲突: {error}")
            raise error from exc
        if not updated:
            return None
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    def delete_channel(self, feature_name: str, channel_id: int) -> bool:
        feature_name = require_logistics_feature(feature_name)

        def delete(session):
            channels = self._lock_channels(session, [channel_id])
            channel = channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                return None
            camera_ids = [row[0] for row in (
                session.query(LogisticsChannelCamera.camera_id)
                .filter_by(channel_id=channel_id)
                .order_by(LogisticsChannelCamera.camera_id)
                .all()
            )]
            cameras = self._lock_cameras(session, camera_ids)
            members = self._lock_memberships(session, [channel_id])
            camera_refs = tuple(
                _CameraRef(camera_id, cameras[camera_id].shm_name)
                for camera_id in sorted({member.camera_id for member in members})
                if camera_id in cameras
            )
            for member in members:
                self._set_feature_enabled(session, feature_name, member.camera_id, False)
                session.delete(member)
            session.delete(channel)
            return camera_refs

        camera_refs = self._run_write_transaction(delete)
        if camera_refs is None:
            return False
        self._notify_channel_changed(
            channel_id,
            feature_name,
            camera_refs=camera_refs,
            feature_action="disabled",
        )
        return True

    def update_config(self, feature_name: str, channel_id: int, payload: Any) -> dict | None:
        feature_name = require_logistics_feature(feature_name)
        values = self._payload_dict(payload)
        self._reject_none(values, (
            "enabled",
            "detection_start",
            "detection_end",
            "empty_grace_seconds",
            "multi_grace_seconds",
            "alarm_interval",
        ))

        def update(session):
            channels = self._lock_channels(session, [channel_id])
            channel = channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                return False
            for field in (
                "enabled",
                "detection_start",
                "detection_end",
                "empty_grace_seconds",
                "multi_grace_seconds",
                "alarm_interval",
            ):
                if field in values:
                    setattr(channel, field, values[field])
            alarm = values.get("alarm")
            if alarm is not None:
                alarm = self._payload_dict(alarm)
                if "sql_enable" in alarm:
                    channel.sql_enable = bool(alarm["sql_enable"])
                horn = self._payload_dict(alarm.get("horn") or {})
                if horn:
                    channel.horn_enable = bool(horn.get("enabled", False))
                    channel.horn_id = horn.get("horn_id")
                    channel.horn_event_id = horn.get("horn_event_id")
                wechat = self._payload_dict(alarm.get("wechat") or {})
                if wechat:
                    channel.wechat_enable = bool(wechat.get("enabled", False))
                    channel.wechat_user = wechat.get("user", "")
            session.flush()
            return True

        try:
            updated = self._run_write_transaction(update)
        except IntegrityError as exc:
            error = ValueError("物流通道配置数据约束冲突")
            logger.warning(f"[LogisticsChannelService] 更新通道配置约束冲突: {exc}")
            raise error from exc
        if not updated:
            return None
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    def add_existing_camera(
        self,
        feature_name: str,
        channel_id: int,
        camera_id: int,
    ) -> dict:
        feature_name = require_logistics_feature(feature_name)

        def add(session):
            pre_read = self._find_feature_membership(session, feature_name, camera_id, lock=False)
            affected_channel_ids = [channel_id]
            if pre_read is not None:
                affected_channel_ids.append(pre_read.channel_id)
            channels = self._lock_channels(session, affected_channel_ids)
            channel = channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                raise ValueError(f"物流通道不存在: {channel_id}")
            cameras = self._lock_cameras(session, [camera_id])
            camera = cameras.get(camera_id)
            if camera is None:
                raise ValueError(f"摄像头不存在: {camera_id}")
            current = self._find_feature_membership(session, feature_name, camera_id, lock=True)
            if current is not None and current.channel_id not in channels:
                raise _MembershipLockSetChanged()
            if current is not None:
                raise ValueError("摄像头已绑定到该功能的其他物流通道")
            self._bind_locked_camera(session, feature_name, channel, camera)
            return _CameraRef(camera.id, camera.shm_name)

        camera_ref = self._run_write_transaction(add)
        self._notify_channel_changed(
            channel_id,
            feature_name,
            camera_refs=(camera_ref,),
            feature_action="enabled",
        )
        return self.get_channel(feature_name, channel_id)

    def create_camera_and_bind(
        self,
        feature_name: str,
        channel_id: int,
        payload: Any,
    ) -> dict:
        feature_name = require_logistics_feature(feature_name)
        values = self._payload_dict(payload)
        expected_department = LOGISTICS_FEATURE_DEPARTMENTS[feature_name]
        requested_department = values.get("department")
        if "department" in values and requested_department != expected_department:
            raise ValueError(
                f"department 必须与功能归属一致: {expected_department}"
            )
        values["department"] = expected_department

        def create_and_bind(session):
            channels = self._lock_channels(session, [channel_id])
            channel = channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                raise ValueError(f"物流通道不存在: {channel_id}")
            self._require_capacity(session, channel.id)
            camera = camera_service.create_camera_record(session, values)
            self._bind_locked_camera(session, feature_name, channel, camera)
            return _CameraRef(camera.id, camera.shm_name)

        try:
            camera_ref = self._run_write_transaction(create_and_bind)
        except IntegrityError as exc:
            error = self._binding_integrity_value_error(exc)
            logger.warning(f"[LogisticsChannelService] 创建摄像头并绑定约束冲突: {error}")
            raise error from exc

        self._notify_channel_changed(
            channel_id,
            feature_name,
            camera_refs=(camera_ref,),
            feature_action="enabled",
            camera_added=camera_ref,
        )
        return self.get_channel(feature_name, channel_id)

    def move_camera(
        self,
        feature_name: str,
        camera_id: int,
        target_channel_id: int,
    ) -> dict:
        feature_name = require_logistics_feature(feature_name)

        def move(session):
            pre_read = self._find_feature_membership(session, feature_name, camera_id, lock=False)
            if pre_read is None:
                raise ValueError("摄像头尚未绑定到该功能的通道")
            source_channel_id = pre_read.channel_id
            channels = self._lock_channels(session, [source_channel_id, target_channel_id])
            source = channels.get(source_channel_id)
            target = channels.get(target_channel_id)
            if (
                source is None
                or source.feature_name != feature_name
                or target is None
                or target.feature_name != feature_name
            ):
                raise ValueError(f"目标物流通道不存在: {target_channel_id}")
            cameras = self._lock_cameras(session, [camera_id])
            camera = cameras.get(camera_id)
            if camera is None:
                raise ValueError(f"摄像头不存在: {camera_id}")
            membership = self._find_feature_membership(session, feature_name, camera_id, lock=True)
            if membership is None:
                raise ValueError("摄像头尚未绑定到该功能的通道")
            if membership.channel_id != source_channel_id:
                raise _MembershipLockSetChanged()
            if source_channel_id != target_channel_id:
                self._require_capacity(session, target_channel_id)
                next_order = self._next_sort_order(session, target_channel_id)
                enabled = bool(membership.enabled)
                session.delete(membership)
                session.flush()
                session.add(LogisticsChannelCamera(
                    channel_id=target_channel_id,
                    camera_id=camera_id,
                    enabled=enabled,
                    sort_order=next_order,
                ))
            self._set_feature_enabled(session, feature_name, camera_id, True)
            session.flush()
            return source_channel_id, _CameraRef(camera.id, camera.shm_name)

        source_channel_id, camera_ref = self._run_write_transaction(move)
        notifications = [_PendingNotification(
            channel_id=target_channel_id,
            feature_name=feature_name,
            camera_refs=(camera_ref,),
            feature_action="enabled",
        )]
        if source_channel_id != target_channel_id:
            notifications.append(_PendingNotification(
                channel_id=source_channel_id,
                feature_name=feature_name,
            ))
        self._publish_notifications(notifications)
        return self.get_channel(feature_name, target_channel_id)

    def reorder_members(
        self,
        feature_name: str,
        channel_id: int,
        camera_ids: list[int],
    ) -> dict:
        feature_name = require_logistics_feature(feature_name)
        requested_ids = list(camera_ids)
        if len(requested_ids) != len(set(requested_ids)):
            raise ValueError("camera_ids 不可重复")

        def reorder(session):
            channels = self._lock_channels(session, [channel_id])
            channel = channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                raise ValueError(f"物流通道不存在: {channel_id}")
            current_camera_ids = [row[0] for row in (
                session.query(LogisticsChannelCamera.camera_id)
                .filter_by(channel_id=channel_id)
                .order_by(LogisticsChannelCamera.camera_id)
                .all()
            )]
            self._lock_cameras(session, current_camera_ids)
            members = self._lock_memberships(session, [channel_id])
            current_ids = [member.camera_id for member in members]
            if len(requested_ids) != len(current_ids) or set(requested_ids) != set(current_ids):
                raise ValueError("camera_ids 必须提供当前通道全部成员且不可缺失或多余")
            by_camera = {member.camera_id: member for member in members}
            for sort_order, camera_id in enumerate(requested_ids):
                by_camera[camera_id].sort_order = sort_order
            session.flush()
            return True

        self._run_write_transaction(reorder)
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    def remove_camera(
        self,
        feature_name: str,
        channel_id: int,
        camera_id: int,
    ) -> bool:
        feature_name = require_logistics_feature(feature_name)

        def remove(session):
            channels = self._lock_channels(session, [channel_id])
            channel = channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                return None
            cameras = self._lock_cameras(session, [camera_id])
            camera = cameras.get(camera_id)
            if camera is None:
                return None
            member = self._lock_membership(session, channel_id, camera_id)
            if member is None:
                return None
            session.delete(member)
            self._set_feature_enabled(session, feature_name, camera_id, False)
            return _CameraRef(camera.id, camera.shm_name)

        camera_ref = self._run_write_transaction(remove)
        if camera_ref is None:
            return False
        self._notify_channel_changed(
            channel_id,
            feature_name,
            camera_refs=(camera_ref,),
            feature_action="disabled",
        )
        return True

    def migrate_existing_feature_cameras(self) -> MigrationSummary:
        candidates: list[tuple[str, int]] = []
        read_session = get_session()
        try:
            for feature_name in sorted(LOGISTICS_FEATURES):
                spec = all_specs()[feature_name]
                camera_ids = (
                    read_session.query(spec.orm_class.camera_id)
                    .filter(spec.orm_class.enable.is_(True))
                    .order_by(spec.orm_class.camera_id)
                    .all()
                )
                candidates.extend((feature_name, row[0]) for row in camera_ids)
        finally:
            read_session.close()

        created = skipped = failed = 0
        errors: list[str] = []
        pending_notifications: list[_PendingNotification] = []
        for feature_name, camera_id in candidates:
            try:
                def migrate_one(session):
                    # 迁移只锁 camera/config，之后只插入新 channel；不再获取任何
                    # 已存在 channel 行锁，避免与 channels→cameras 层级形成环。
                    camera = self._lock_migration_camera(session, camera_id)
                    if camera is None:
                        raise ValueError(f"摄像头不存在: {camera_id}")
                    spec = all_specs()[feature_name]
                    cfg = (
                        session.query(spec.orm_class)
                        .filter_by(camera_id=camera_id)
                        .with_for_update()
                        .first()
                    )
                    if cfg is None or not cfg.enable:
                        return None
                    assigned = (
                        session.query(LogisticsChannelCamera.id)
                        .join(LogisticsChannel)
                        .filter(
                            LogisticsChannel.feature_name == feature_name,
                            LogisticsChannelCamera.camera_id == camera_id,
                        )
                        .first()
                    )
                    if assigned is not None:
                        return None
                    name = camera.name
                    collision = (
                        session.query(LogisticsChannel.id)
                        .filter_by(feature_name=feature_name, name=name)
                        .first()
                    )
                    if collision is not None:
                        name = f"{camera.name}-{camera.id}"
                    channel = LogisticsChannel(
                        name=name,
                        feature_name=feature_name,
                        empty_grace_seconds=cfg.empty_grace_seconds,
                        multi_grace_seconds=cfg.multi_grace_seconds,
                        alarm_interval=cfg.alarm_interval,
                        sql_enable=bool(cfg.sql_enable),
                        horn_enable=bool(cfg.horn_enable),
                        horn_id=cfg.horn_id,
                        horn_event_id=cfg.horn_event_id,
                        wechat_enable=bool(cfg.wechat_enable),
                        wechat_user=cfg.wechat_user,
                    )
                    session.add(channel)
                    session.flush()
                    session.add(LogisticsChannelCamera(
                        channel_id=channel.id,
                        camera_id=camera_id,
                        enabled=True,
                        sort_order=0,
                    ))
                    session.flush()
                    camera_ref = _CameraRef(camera.id, camera.shm_name)
                    return _PendingNotification(
                        channel_id=channel.id,
                        feature_name=feature_name,
                        camera_refs=(camera_ref,),
                        feature_action="enabled",
                    )

                notification = self._run_write_transaction(migrate_one)
                if notification is None:
                    skipped += 1
                    continue
                created += 1
                pending_notifications.append(notification)
            except Exception as exc:
                failed += 1
                message = f"{feature_name}/camera_id={camera_id}: {exc}"
                errors.append(message)
                logger.warning(f"[LogisticsChannelService] 迁移失败 {message}")
        if pending_notifications:
            self._publish_notifications(pending_notifications)
        return MigrationSummary(created, skipped, failed, tuple(errors))

    @staticmethod
    def _payload_dict(payload: Any) -> dict:
        if payload is None:
            return {}
        if isinstance(payload, dict):
            return dict(payload)
        if hasattr(payload, "model_dump"):
            return payload.model_dump(exclude_unset=True)
        raise TypeError("payload 必须是 dict 或 Pydantic model")

    @staticmethod
    def _query_channel(session, feature_name: str, channel_id: int):
        return (
            session.query(LogisticsChannel)
            .options(selectinload(LogisticsChannel.cameras))
            .filter_by(feature_name=feature_name, id=channel_id)
            .first()
        )

    @staticmethod
    def _run_write_transaction(operation):
        """每次尝试都创建新 session，并完整重跑锁定与业务校验。"""
        for attempt in range(1, _MAX_WRITE_ATTEMPTS + 1):
            try:
                with session_scope() as session:
                    return operation(session)
            except _MembershipLockSetChanged:
                if attempt >= _MAX_WRITE_ATTEMPTS:
                    raise
            except OperationalError as exc:
                code = _database_error_code(exc)
                if code not in _MYSQL_RETRYABLE_LOCK_ERRORS or attempt >= _MAX_WRITE_ATTEMPTS:
                    raise
                logger.warning(
                    f"[LogisticsChannelService] 写事务锁冲突 code={code}, "
                    f"准备第 {attempt + 1}/{_MAX_WRITE_ATTEMPTS} 次尝试"
                )
            sleep(_WRITE_RETRY_BACKOFF_SECONDS * attempt)
        raise RuntimeError("unreachable")

    @staticmethod
    def _channel_integrity_value_error(exc: IntegrityError) -> ValueError:
        message = str(exc.orig or exc).lower()
        if (
            "uq_logistics_channel_feature_name" in message
            or (
                "ai_logistics_channel.feature_name" in message
                and "ai_logistics_channel.name" in message
            )
        ):
            return ValueError("同一功能下通道名称已存在")
        return ValueError("物流通道数据约束冲突")

    @classmethod
    def _binding_integrity_value_error(cls, exc: IntegrityError) -> ValueError:
        message = str(exc.orig or exc).lower()
        if "ai_camera_config" in message or "shm_name" in message:
            return _camera_integrity_value_error(exc)
        channel_error = cls._channel_integrity_value_error(exc)
        if "已存在" in str(channel_error):
            return channel_error
        return ValueError("物流通道绑定数据约束冲突")

    @staticmethod
    def _reject_none(values: dict, fields: tuple[str, ...]) -> None:
        for field in fields:
            if field in values and values[field] is None:
                raise ValueError(f"{field} 不可为 None")

    @staticmethod
    def _lock_channels(session, channel_ids) -> dict[int, LogisticsChannel]:
        """锁层级 1：所有既有 channel 必须按 ID 升序先锁定。"""
        ids = sorted(set(channel_ids))
        if not ids:
            return {}
        rows = (
            session.query(LogisticsChannel)
            .filter(LogisticsChannel.id.in_(ids))
            .order_by(LogisticsChannel.id)
            .with_for_update()
            .all()
        )
        return {row.id: row for row in rows}

    @staticmethod
    def _lock_cameras(session, camera_ids) -> dict[int, AiCameraConfig]:
        """锁层级 2：channel 全部锁定后，再按 ID 升序锁 camera。"""
        ids = sorted(set(camera_ids))
        if not ids:
            return {}
        rows = (
            session.query(AiCameraConfig)
            .filter(AiCameraConfig.id.in_(ids))
            .order_by(AiCameraConfig.id)
            .with_for_update()
            .all()
        )
        return {row.id: row for row in rows}

    @staticmethod
    def _lock_migration_camera(session, camera_id: int):
        """迁移专用例外：锁 camera 后只写新 channel，不获取既有 channel 锁。"""
        return (
            session.query(AiCameraConfig)
            .filter_by(id=camera_id)
            .with_for_update()
            .first()
        )

    @staticmethod
    def _lock_memberships(session, channel_ids) -> list[LogisticsChannelCamera]:
        """锁层级 3：channels、cameras 均锁定后，最后锁 membership。"""
        ids = sorted(set(channel_ids))
        if not ids:
            return []
        return (
            session.query(LogisticsChannelCamera)
            .filter(LogisticsChannelCamera.channel_id.in_(ids))
            .order_by(
                LogisticsChannelCamera.channel_id,
                LogisticsChannelCamera.camera_id,
            )
            .with_for_update()
            .all()
        )

    @staticmethod
    def _lock_membership(session, channel_id: int, camera_id: int):
        return (
            session.query(LogisticsChannelCamera)
            .filter_by(channel_id=channel_id, camera_id=camera_id)
            .with_for_update()
            .first()
        )

    @staticmethod
    def _find_feature_membership(session, feature_name: str, camera_id: int, *, lock: bool):
        query = (
            session.query(LogisticsChannelCamera)
            .join(LogisticsChannel)
            .filter(
                LogisticsChannel.feature_name == feature_name,
                LogisticsChannelCamera.camera_id == camera_id,
            )
        )
        if lock:
            query = query.with_for_update()
        return query.first()

    @staticmethod
    def _detail(channel: LogisticsChannel) -> dict:
        return LogisticsChannelDetailResponse.model_validate(channel).model_dump(mode="python")

    @staticmethod
    def _require_capacity(session, channel_id: int) -> None:
        member_count = (
            session.query(func.count(LogisticsChannelCamera.id))
            .filter_by(channel_id=channel_id)
            .scalar()
        )
        if member_count >= MAX_CAMERAS_PER_CHANNEL:
            raise ValueError(f"每个物流通道最多绑定 {MAX_CAMERAS_PER_CHANNEL} 路摄像头")

    @staticmethod
    def _next_sort_order(session, channel_id: int) -> int:
        current = (
            session.query(func.max(LogisticsChannelCamera.sort_order))
            .filter_by(channel_id=channel_id)
            .scalar()
        )
        return 0 if current is None else current + 1

    def _bind_locked_camera(self, session, feature_name, channel, camera) -> None:
        self._require_capacity(session, channel.id)
        existing = self._find_feature_membership(
            session,
            feature_name,
            camera.id,
            lock=True,
        )
        if existing is not None:
            raise ValueError("摄像头已绑定到该功能的其他物流通道")
        session.add(LogisticsChannelCamera(
            channel_id=channel.id,
            camera_id=camera.id,
            enabled=True,
            sort_order=self._next_sort_order(session, channel.id),
        ))
        self._set_feature_enabled(session, feature_name, camera.id, True)
        session.flush()

    @staticmethod
    def _set_feature_enabled(session, feature_name: str, camera_id: int, enabled: bool):
        spec = all_specs()[feature_name]
        cfg = session.query(spec.orm_class).filter_by(camera_id=camera_id).first()
        if cfg is None:
            cfg = spec.orm_class(camera_id=camera_id, enable=enabled)
            session.add(cfg)
        else:
            cfg.enable = enabled
        return cfg

    @staticmethod
    def _notify_channel_changed(
        channel_id: int,
        feature_name: str,
        *,
        camera_refs: tuple[_CameraRef, ...] = (),
        feature_action: str | None = None,
        camera_added: _CameraRef | None = None,
    ) -> None:
        """仅在事务提交后调用；通知异常记录告警但不破坏已提交事务。"""
        LogisticsChannelService._publish_notifications([
            _PendingNotification(
                channel_id=channel_id,
                feature_name=feature_name,
                camera_refs=camera_refs,
                feature_action=feature_action,
                camera_added=camera_added,
            )
        ])

    @staticmethod
    def _publish_notifications(notifications: list[_PendingNotification]) -> None:
        """一次重载缓存后发布一批已提交事务的事件。"""
        try:
            config_cache.reload()
            for notification in notifications:
                if notification.camera_added is not None:
                    config_event_bus.publish(ConfigChangeEvent(
                        change_type="camera_added",
                        camera_id=notification.camera_added.camera_id,
                        camera_name=notification.camera_added.shm_name,
                    ))
                if notification.feature_action is not None:
                    for camera_ref in notification.camera_refs:
                        config_event_bus.publish(ConfigChangeEvent(
                            change_type=(
                                f"{notification.feature_name}_"
                                f"{notification.feature_action}"
                            ),
                            camera_id=camera_ref.camera_id,
                            camera_name=camera_ref.shm_name,
                        ))
                config_event_bus.publish(ConfigChangeEvent(
                    change_type="logistics_channel_updated",
                    new_value={
                        "channel_id": notification.channel_id,
                        "feature_name": notification.feature_name,
                    },
                ))
        except Exception as exc:
            logger.warning(
                f"[LogisticsChannelService] 通道通知失败(batch): {exc}"
            )


logistics_channel_service = LogisticsChannelService()
