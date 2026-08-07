"""物流通道配置、成员绑定与旧配置迁移服务。"""
from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Any

from sqlalchemy import or_
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
class _DiscoveredMembership:
    member_id: int
    channel_id: int
    camera_id: int
    feature_name: str


@dataclass(frozen=True)
class _MembershipDiscovery:
    members: tuple[_DiscoveredMembership, ...]
    camera_scope: tuple[int, ...]
    channel_scope: tuple[int, ...]

    @property
    def member_ids(self) -> tuple[int, ...]:
        return tuple(member.member_id for member in self.members)

    @property
    def member_channel_ids(self) -> tuple[int, ...]:
        return tuple(member.channel_id for member in self.members)

    @property
    def member_camera_ids(self) -> tuple[int, ...]:
        return tuple(member.camera_id for member in self.members)

    @property
    def expected_pairs(self) -> set[tuple[int, int]]:
        return {(member.member_id, member.channel_id) for member in self.members}


@dataclass(frozen=True)
class _LockedMembershipState:
    channels: dict[int, LogisticsChannel]
    cameras: dict[int, AiCameraConfig]
    members: list[LogisticsChannelCamera]


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

        def discover():
            return self._discover_memberships(channel_ids=(channel_id,))

        def delete(session, discovery):
            state = self._lock_membership_state(
                session,
                discovery,
                required_channel_ids=(channel_id,),
            )
            channel = state.channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                return None
            members = [
                member for member in state.members if member.channel_id == channel_id
            ]
            camera_refs = tuple(
                _CameraRef(camera_id, state.cameras[camera_id].shm_name)
                for camera_id in sorted({member.camera_id for member in members})
                if camera_id in state.cameras
            )
            for member in members:
                self._set_feature_enabled(session, feature_name, member.camera_id, False)
                session.delete(member)
            session.delete(channel)
            return camera_refs

        camera_refs = self._run_membership_transaction(discover, delete)
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

        def discover():
            return self._discover_memberships(
                camera_ids=(camera_id,),
                channel_ids=(channel_id,),
            )

        def add(session, discovery):
            state = self._lock_membership_state(
                session,
                discovery,
                required_channel_ids=(channel_id,),
                required_camera_ids=(camera_id,),
            )
            channel = state.channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                raise ValueError(f"物流通道不存在: {channel_id}")
            camera = state.cameras.get(camera_id)
            if camera is None:
                raise ValueError(f"摄像头不存在: {camera_id}")
            same_feature_members = [
                member
                for member in state.members
                if member.camera_id == camera_id
                and state.channels[member.channel_id].feature_name == feature_name
            ]
            if same_feature_members:
                raise ValueError("摄像头已绑定到该功能的其他物流通道")
            self._insert_locked_member(
                session,
                feature_name,
                channel,
                camera,
                state.members,
            )
            return _CameraRef(camera.id, camera.shm_name)

        camera_ref = self._run_membership_transaction(discover, add)
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

        def discover():
            return self._discover_memberships(channel_ids=(channel_id,))

        def create_and_bind(session, discovery):
            state = self._lock_membership_state(
                session,
                discovery,
                required_channel_ids=(channel_id,),
            )
            channel = state.channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                raise ValueError(f"物流通道不存在: {channel_id}")
            self._require_capacity(state.members, channel.id)
            camera = camera_service.create_camera_record(session, values)
            self._insert_locked_member(
                session,
                feature_name,
                channel,
                camera,
                state.members,
            )
            return _CameraRef(camera.id, camera.shm_name)

        try:
            camera_ref = self._run_membership_transaction(discover, create_and_bind)
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

        def discover():
            return self._discover_memberships(
                camera_ids=(camera_id,),
                channel_ids=(target_channel_id,),
            )

        def move(session, discovery):
            state = self._lock_membership_state(
                session,
                discovery,
                required_channel_ids=(target_channel_id,),
                required_camera_ids=(camera_id,),
            )
            target = state.channels.get(target_channel_id)
            if target is None or target.feature_name != feature_name:
                raise ValueError(f"目标物流通道不存在: {target_channel_id}")
            camera = state.cameras.get(camera_id)
            if camera is None:
                raise ValueError(f"摄像头不存在: {camera_id}")
            feature_memberships = [
                member
                for member in state.members
                if member.camera_id == camera_id
                and state.channels[member.channel_id].feature_name == feature_name
            ]
            if not feature_memberships:
                raise ValueError("摄像头尚未绑定到该功能的通道")
            if len(feature_memberships) != 1:
                raise ValueError("摄像头在该功能下存在多个通道绑定")
            membership = feature_memberships[0]
            source_channel_id = membership.channel_id
            if source_channel_id != target_channel_id:
                self._require_capacity(state.members, target_channel_id)
                next_order = self._next_sort_order(state.members, target_channel_id)
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

        source_channel_id, camera_ref = self._run_membership_transaction(discover, move)
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

        def discover():
            return self._discover_memberships(channel_ids=(channel_id,))

        def reorder(session, discovery):
            state = self._lock_membership_state(
                session,
                discovery,
                required_channel_ids=(channel_id,),
            )
            channel = state.channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                raise ValueError(f"物流通道不存在: {channel_id}")
            members = [
                member for member in state.members if member.channel_id == channel_id
            ]
            current_ids = [member.camera_id for member in members]
            if len(requested_ids) != len(current_ids) or set(requested_ids) != set(current_ids):
                raise ValueError("camera_ids 必须提供当前通道全部成员且不可缺失或多余")
            by_camera = {member.camera_id: member for member in members}
            for sort_order, camera_id in enumerate(requested_ids):
                by_camera[camera_id].sort_order = sort_order
            session.flush()
            return True

        self._run_membership_transaction(discover, reorder)
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    def remove_camera(
        self,
        feature_name: str,
        channel_id: int,
        camera_id: int,
    ) -> bool:
        feature_name = require_logistics_feature(feature_name)

        def discover():
            return self._discover_memberships(
                camera_ids=(camera_id,),
                channel_ids=(channel_id,),
            )

        def remove(session, discovery):
            state = self._lock_membership_state(
                session,
                discovery,
                required_channel_ids=(channel_id,),
                required_camera_ids=(camera_id,),
            )
            channel = state.channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                return None
            camera = state.cameras.get(camera_id)
            if camera is None:
                return None
            member = next(
                (
                    row
                    for row in state.members
                    if row.channel_id == channel_id and row.camera_id == camera_id
                ),
                None,
            )
            if member is None:
                return None
            session.delete(member)
            self._set_feature_enabled(session, feature_name, camera_id, False)
            return _CameraRef(camera.id, camera.shm_name)

        camera_ref = self._run_membership_transaction(discover, remove)
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
                def discover():
                    return self._discover_memberships(camera_ids=(camera_id,))

                def migrate_one(session, discovery):
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
                    current_members = self._build_membership_lock_query(
                        session,
                        member_ids=discovery.member_ids,
                        camera_ids=discovery.camera_scope,
                    ).all()
                    current_pairs = {
                        (member.id, member.channel_id) for member in current_members
                    }
                    if current_pairs != discovery.expected_pairs:
                        raise _MembershipLockSetChanged()
                    if any(
                        member.feature_name == feature_name
                        for member in discovery.members
                    ):
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

                notification = self._run_membership_transaction(discover, migrate_one)
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
    def _run_membership_transaction(discover, operation):
        """每次尝试先用已关闭短 session discovery，再开启全新正式事务。"""
        for attempt in range(1, _MAX_WRITE_ATTEMPTS + 1):
            discovery = discover()
            try:
                with session_scope() as session:
                    return operation(session, discovery)
            except _MembershipLockSetChanged:
                if attempt >= _MAX_WRITE_ATTEMPTS:
                    raise
            except OperationalError as exc:
                code = _database_error_code(exc)
                if code not in _MYSQL_RETRYABLE_LOCK_ERRORS or attempt >= _MAX_WRITE_ATTEMPTS:
                    raise
                logger.warning(
                    f"[LogisticsChannelService] 成员事务锁冲突 code={code}, "
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
    def _discover_memberships(
        *,
        camera_ids=(),
        channel_ids=(),
    ) -> _MembershipDiscovery:
        """在独立短 session 中发现锁集合；返回前一定关闭该 session。"""
        camera_scope = tuple(sorted(set(camera_ids)))
        channel_scope = tuple(sorted(set(channel_ids)))
        session = get_session()
        try:
            conditions = []
            if camera_scope:
                conditions.append(LogisticsChannelCamera.camera_id.in_(camera_scope))
            if channel_scope:
                conditions.append(LogisticsChannelCamera.channel_id.in_(channel_scope))
            if not conditions:
                return _MembershipDiscovery((), camera_scope, channel_scope)
            rows = (
                session.query(LogisticsChannelCamera)
                .filter(or_(*conditions))
                .order_by(LogisticsChannelCamera.id)
                .all()
            )
            discovered_channel_ids = sorted({row.channel_id for row in rows})
            feature_by_channel = {
                row.id: row.feature_name
                for row in (
                    session.query(LogisticsChannel)
                    .filter(LogisticsChannel.id.in_(discovered_channel_ids))
                    .all()
                )
            } if discovered_channel_ids else {}
            members = tuple(
                _DiscoveredMembership(
                    member_id=row.id,
                    channel_id=row.channel_id,
                    camera_id=row.camera_id,
                    feature_name=feature_by_channel.get(row.channel_id, ""),
                )
                for row in rows
            )
            return _MembershipDiscovery(members, camera_scope, channel_scope)
        finally:
            session.close()

    @staticmethod
    def _build_membership_lock_query(
        session,
        *,
        member_ids=(),
        camera_ids=(),
        channel_ids=(),
    ):
        """仅锁 membership 表；MySQL 编译结果不得包含 JOIN。"""
        conditions = []
        if member_ids:
            conditions.append(LogisticsChannelCamera.id.in_(tuple(member_ids)))
        if camera_ids:
            conditions.append(LogisticsChannelCamera.camera_id.in_(tuple(camera_ids)))
        if channel_ids:
            conditions.append(LogisticsChannelCamera.channel_id.in_(tuple(channel_ids)))
        query = session.query(LogisticsChannelCamera)
        if conditions:
            query = query.filter(or_(*conditions))
        else:
            query = query.filter(LogisticsChannelCamera.id.in_(()))
        return query.order_by(LogisticsChannelCamera.id).with_for_update()

    def _lock_membership_state(
        self,
        session,
        discovery: _MembershipDiscovery,
        *,
        required_channel_ids=(),
        required_camera_ids=(),
    ) -> _LockedMembershipState:
        """MySQL RR 正式事务：channels→cameras→memberships 全部 current read。"""
        channel_ids = sorted({
            *required_channel_ids,
            *discovery.channel_scope,
            *discovery.member_channel_ids,
        })
        camera_ids = sorted({
            *required_camera_ids,
            *discovery.camera_scope,
            *discovery.member_camera_ids,
        })
        channels = self._lock_channels(session, channel_ids)
        cameras = self._lock_cameras(session, camera_ids)
        members = self._build_membership_lock_query(
            session,
            member_ids=discovery.member_ids,
            camera_ids=discovery.camera_scope,
            channel_ids=discovery.channel_scope,
        ).all()
        actual_pairs = {(member.id, member.channel_id) for member in members}
        if actual_pairs != discovery.expected_pairs:
            raise _MembershipLockSetChanged()
        return _LockedMembershipState(channels, cameras, members)

    @staticmethod
    def _detail(channel: LogisticsChannel) -> dict:
        return LogisticsChannelDetailResponse.model_validate(channel).model_dump(mode="python")

    @staticmethod
    def _require_capacity(members: list[LogisticsChannelCamera], channel_id: int) -> None:
        member_count = sum(member.channel_id == channel_id for member in members)
        if member_count >= MAX_CAMERAS_PER_CHANNEL:
            raise ValueError(f"每个物流通道最多绑定 {MAX_CAMERAS_PER_CHANNEL} 路摄像头")

    @staticmethod
    def _next_sort_order(members: list[LogisticsChannelCamera], channel_id: int) -> int:
        sort_orders = [
            member.sort_order
            for member in members
            if member.channel_id == channel_id
        ]
        return 0 if not sort_orders else max(sort_orders) + 1

    def _insert_locked_member(self, session, feature_name, channel, camera, members) -> None:
        self._require_capacity(members, channel.id)
        session.add(LogisticsChannelCamera(
            channel_id=channel.id,
            camera_id=camera.id,
            enabled=True,
            sort_order=self._next_sort_order(members, channel.id),
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
