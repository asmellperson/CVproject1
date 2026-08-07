"""物流通道配置、成员绑定与旧配置迁移服务。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from core.cache import config_cache
from core.db import get_session, session_scope
from core.events import ConfigChangeEvent, config_event_bus
from core.logger import logger
from features import all_specs
from platform.camera.orm import AiCameraConfig
from platform.camera.service import camera_service

from .constants import (
    LOGISTICS_FEATURE_DEPARTMENTS,
    LOGISTICS_FEATURES,
    MAX_CAMERAS_PER_CHANNEL,
    require_logistics_feature,
)
from .orm import LogisticsChannel, LogisticsChannelCamera
from .schema import LogisticsChannelDetailResponse, LogisticsChannelListResponse


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
        try:
            with session_scope() as session:
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
                channel_id = channel.id
        except IntegrityError as exc:
            raise ValueError(f"同一功能下通道名称已存在: {normalized_name}") from exc
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    def update_channel(self, feature_name: str, channel_id: int, payload: Any) -> dict | None:
        feature_name = require_logistics_feature(feature_name)
        values = self._payload_dict(payload)
        try:
            with session_scope() as session:
                channel = self._locked_channel(session, feature_name, channel_id)
                if channel is None:
                    return None
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
        except IntegrityError as exc:
            raise ValueError("同一功能下通道名称已存在") from exc
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    def delete_channel(self, feature_name: str, channel_id: int) -> bool:
        feature_name = require_logistics_feature(feature_name)
        with session_scope() as session:
            channel = self._locked_channel(session, feature_name, channel_id)
            if channel is None:
                return False
            members = (
                session.query(LogisticsChannelCamera)
                .filter_by(channel_id=channel_id)
                .with_for_update()
                .all()
            )
            camera_ids = [member.camera_id for member in members]
            for camera_id in camera_ids:
                self._set_feature_enabled(session, feature_name, camera_id, False)
            for member in members:
                session.delete(member)
            session.delete(channel)
        self._notify_channel_changed(
            channel_id,
            feature_name,
            camera_ids=camera_ids,
            feature_action="disabled",
        )
        return True

    def update_config(self, feature_name: str, channel_id: int, payload: Any) -> dict | None:
        feature_name = require_logistics_feature(feature_name)
        values = self._payload_dict(payload)
        with session_scope() as session:
            channel = self._locked_channel(session, feature_name, channel_id)
            if channel is None:
                return None
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
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    def add_existing_camera(
        self,
        feature_name: str,
        channel_id: int,
        camera_id: int,
    ) -> dict:
        feature_name = require_logistics_feature(feature_name)
        with session_scope() as session:
            channel = self._locked_channel(session, feature_name, channel_id)
            if channel is None:
                raise ValueError(f"物流通道不存在: {channel_id}")
            camera = self._locked_camera(session, camera_id)
            if camera is None:
                raise ValueError(f"摄像头不存在: {camera_id}")
            self._bind_locked_camera(session, feature_name, channel, camera)
        self._notify_channel_changed(
            channel_id,
            feature_name,
            camera_ids=[camera_id],
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

        with session_scope() as session:
            channel = self._locked_channel(session, feature_name, channel_id)
            if channel is None:
                raise ValueError(f"物流通道不存在: {channel_id}")
            self._require_capacity(session, channel.id)
            camera = camera_service.create_camera_record(session, values)
            self._bind_locked_camera(session, feature_name, channel, camera)
            camera_id = camera.id
            camera_shm = camera.shm_name

        self._notify_channel_changed(
            channel_id,
            feature_name,
            camera_ids=[camera_id],
            feature_action="enabled",
            camera_added=(camera_id, camera_shm),
        )
        return self.get_channel(feature_name, channel_id)

    def move_camera(
        self,
        feature_name: str,
        camera_id: int,
        target_channel_id: int,
    ) -> dict:
        feature_name = require_logistics_feature(feature_name)
        with session_scope() as session:
            camera = self._locked_camera(session, camera_id)
            if camera is None:
                raise ValueError(f"摄像头不存在: {camera_id}")
            membership = (
                session.query(LogisticsChannelCamera)
                .join(LogisticsChannel)
                .filter(
                    LogisticsChannel.feature_name == feature_name,
                    LogisticsChannelCamera.camera_id == camera_id,
                )
                .with_for_update()
                .first()
            )
            if membership is None:
                raise ValueError("摄像头尚未绑定到该功能的通道")
            source_channel_id = membership.channel_id
            locked_channels = (
                session.query(LogisticsChannel)
                .filter(LogisticsChannel.id.in_({source_channel_id, target_channel_id}))
                .order_by(LogisticsChannel.id)
                .with_for_update()
                .all()
            )
            channels = {channel.id: channel for channel in locked_channels}
            target = channels.get(target_channel_id)
            if target is None or target.feature_name != feature_name:
                raise ValueError(f"目标物流通道不存在: {target_channel_id}")
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
        self._notify_channel_changed(
            target_channel_id,
            feature_name,
            camera_ids=[camera_id],
            feature_action="enabled",
        )
        if source_channel_id != target_channel_id:
            self._notify_channel_changed(source_channel_id, feature_name)
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
        with session_scope() as session:
            channel = self._locked_channel(session, feature_name, channel_id)
            if channel is None:
                raise ValueError(f"物流通道不存在: {channel_id}")
            members = (
                session.query(LogisticsChannelCamera)
                .filter_by(channel_id=channel_id)
                .with_for_update()
                .all()
            )
            current_ids = [member.camera_id for member in members]
            if len(requested_ids) != len(current_ids) or set(requested_ids) != set(current_ids):
                raise ValueError("camera_ids 必须提供当前通道全部成员且不可缺失或多余")
            by_camera = {member.camera_id: member for member in members}
            for sort_order, camera_id in enumerate(requested_ids):
                by_camera[camera_id].sort_order = sort_order
            session.flush()
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    def remove_camera(
        self,
        feature_name: str,
        channel_id: int,
        camera_id: int,
    ) -> bool:
        feature_name = require_logistics_feature(feature_name)
        with session_scope() as session:
            channel = self._locked_channel(session, feature_name, channel_id)
            if channel is None:
                return False
            camera = self._locked_camera(session, camera_id)
            if camera is None:
                return False
            member = (
                session.query(LogisticsChannelCamera)
                .filter_by(channel_id=channel_id, camera_id=camera_id)
                .with_for_update()
                .first()
            )
            if member is None:
                return False
            session.delete(member)
            self._set_feature_enabled(session, feature_name, camera_id, False)
        self._notify_channel_changed(
            channel_id,
            feature_name,
            camera_ids=[camera_id],
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
        for feature_name, camera_id in candidates:
            try:
                channel_id = None
                with session_scope() as session:
                    spec = all_specs()[feature_name]
                    cfg = (
                        session.query(spec.orm_class)
                        .filter_by(camera_id=camera_id)
                        .with_for_update()
                        .first()
                    )
                    if cfg is None or not cfg.enable:
                        skipped += 1
                        continue
                    camera = self._locked_camera(session, camera_id)
                    if camera is None:
                        raise ValueError(f"摄像头不存在: {camera_id}")
                    assigned = (
                        session.query(LogisticsChannelCamera.id)
                        .join(LogisticsChannel)
                        .filter(
                            LogisticsChannel.feature_name == feature_name,
                            LogisticsChannelCamera.camera_id == camera_id,
                        )
                        .with_for_update()
                        .first()
                    )
                    if assigned is not None:
                        skipped += 1
                        continue
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
                    channel_id = channel.id
                created += 1
                self._notify_channel_changed(
                    channel_id,
                    feature_name,
                    camera_ids=[camera_id],
                )
            except Exception as exc:
                failed += 1
                message = f"{feature_name}/camera_id={camera_id}: {exc}"
                errors.append(message)
                logger.warning(f"[LogisticsChannelService] 迁移失败 {message}")
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
    def _locked_channel(session, feature_name: str, channel_id: int):
        # 锁通道行，使同一通道的容量统计和新增成员在 MySQL/InnoDB 中串行化。
        return (
            session.query(LogisticsChannel)
            .filter_by(feature_name=feature_name, id=channel_id)
            .with_for_update()
            .first()
        )

    @staticmethod
    def _locked_camera(session, camera_id: int):
        # 锁摄像头行，使同一摄像头在同 feature 的归属检查和写入串行化。
        return (
            session.query(AiCameraConfig)
            .filter_by(id=camera_id)
            .with_for_update()
            .first()
        )

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
        existing = (
            session.query(LogisticsChannelCamera)
            .join(LogisticsChannel)
            .filter(
                LogisticsChannel.feature_name == feature_name,
                LogisticsChannelCamera.camera_id == camera.id,
            )
            .with_for_update()
            .first()
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
        camera_ids: list[int] | None = None,
        feature_action: str | None = None,
        camera_added: tuple[int, str] | None = None,
    ) -> None:
        """仅在事务提交后调用；通知异常记录告警但不破坏已提交事务。"""
        try:
            config_cache.reload()
            if camera_added is not None:
                camera_id, camera_shm = camera_added
                config_event_bus.publish(ConfigChangeEvent(
                    change_type="camera_added",
                    camera_id=camera_id,
                    camera_name=camera_shm,
                ))
            if feature_action is not None:
                for camera_id in camera_ids or []:
                    config_event_bus.publish(ConfigChangeEvent(
                        change_type=f"{feature_name}_{feature_action}",
                        camera_id=camera_id,
                    ))
            config_event_bus.publish(ConfigChangeEvent(
                change_type="logistics_channel_updated",
                new_value={
                    "channel_id": channel_id,
                    "feature_name": feature_name,
                },
            ))
        except Exception as exc:
            logger.warning(
                f"[LogisticsChannelService] 通道通知失败 "
                f"feature={feature_name} channel_id={channel_id}: {exc}"
            )


logistics_channel_service = LogisticsChannelService()
