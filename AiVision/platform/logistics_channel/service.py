# 文件说明：封装业务服务的业务规则与持久化访问。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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
from platform.camera.config_manager import (
    _camera_integrity_value_error,
    _database_error_code,
    camera_config_manager,
)

from .constants import (
    DEFAULT_PERSON_CONFIDENCE_THRESHOLD,
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


# 功能：非锁定预读后的成员归属已变化，需要用新事务重新确定锁集合；输入与输出详见下方说明
# 参数：无。
# 返回：_MembershipLockSetChanged；返回新建的 `_MembershipLockSetChanged` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/service.py` 的
#         `LogisticsChannelService::migrate_existing_feature_cameras::migrate_one`
#         实例化本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_lock_membership_state` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class _MembershipLockSetChanged(RuntimeError):
    """非锁定预读后的成员归属已变化，需要用新事务重新确定锁集合。"""


# 功能：定义 `_DiscoveredMembership` 类，封装业务服务相关的状态、约束与操作
# 参数：
#   - `member_id`（int）：`member_id` 对应业务对象的唯一标识
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `camera_id`（int）：摄像头唯一标识
#   - `feature_name`（str）：`feature_name` 对应的业务输入值
# 返回：_DiscoveredMembership；返回新建的 `_DiscoveredMembership` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_discover_memberships` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _DiscoveredMembership:
    member_id: int
    channel_id: int
    camera_id: int
    feature_name: str


# 功能：定义 `_MembershipDiscovery` 类，封装业务服务相关的状态、约束与操作
# 参数：
#   - `members`（tuple[_DiscoveredMembership, ...]）：`members` 对应的业务输入值
#   - `camera_scope`（tuple[int, ...]）：`camera_scope` 对应的业务输入值
#   - `channel_scope`（tuple[int, ...]）：`channel_scope` 对应的业务输入值
# 返回：_MembershipDiscovery；返回新建的 `_MembershipDiscovery` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_discover_memberships` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _MembershipDiscovery:
    members: tuple[_DiscoveredMembership, ...]
    camera_scope: tuple[int, ...]
    channel_scope: tuple[int, ...]

    # 功能：实现 `member_ids` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：tuple[int, ...]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`tuple`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def member_ids(self) -> tuple[int, ...]:
        return tuple(member.member_id for member in self.members)

    # 功能：实现 `member_channel_ids` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：tuple[int, ...]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`tuple`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def member_channel_ids(self) -> tuple[int, ...]:
        return tuple(member.channel_id for member in self.members)

    # 功能：实现 `member_camera_ids` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：tuple[int, ...]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`tuple`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def member_camera_ids(self) -> tuple[int, ...]:
        return tuple(member.camera_id for member in self.members)

    # 功能：实现 `expected_pairs` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：set[tuple[int, int]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def expected_pairs(self) -> set[tuple[int, int]]:
        return {(member.member_id, member.channel_id) for member in self.members}


# 功能：定义 `_LockedMembershipState` 类，封装业务服务相关的状态、约束与操作
# 参数：
#   - `channels`（dict[int, LogisticsChannel]）：`channels` 对应的业务输入值
#   - `cameras`（dict[int, AiCameraConfig]）：`cameras` 对应的业务输入值
#   - `members`（list[LogisticsChannelCamera]）：`members` 对应的业务输入值
# 返回：_LockedMembershipState；返回新建的 `_LockedMembershipState` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_lock_membership_state` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _LockedMembershipState:
    channels: dict[int, LogisticsChannel]
    cameras: dict[int, AiCameraConfig]
    members: list[LogisticsChannelCamera]


# 功能：定义 `_CameraRef` 类，封装业务服务相关的状态、约束与操作
# 参数：
#   - `camera_id`（int）：摄像头唯一标识
#   - `shm_name`（str）：摄像头共享内存名称
# 返回：_CameraRef；返回新建的 `_CameraRef` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::delete_channel::delete`
#         实例化本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::add_existing_camera::add`
#         实例化本符号；`AiVision/platform/logistics_channel/service.py` 的
#         `LogisticsChannelService::create_camera_and_bind::create_and_bind` 实例化本符号；`AiVision/platform/logistics_channel/service.py`
#         的 `LogisticsChannelService::move_camera::move` 实例化本符号；另有 2 处静态调用
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _CameraRef:
    camera_id: int
    shm_name: str


# 功能：定义 `_PendingNotification` 类，封装业务服务相关的状态、约束与操作
# 参数：
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `feature_name`（str）：`feature_name` 对应的业务输入值
#   - `camera_refs`（tuple[_CameraRef, ...]）：`camera_refs` 对应的业务输入值
#   - `feature_action`（str | None）：`feature_action` 对应的业务输入值
#   - `camera_added`（_CameraRef | None）：`camera_added` 对应的业务输入值
# 返回：_PendingNotification；返回新建的 `_PendingNotification` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::move_camera`
#         实例化本符号；`AiVision/platform/logistics_channel/service.py` 的
#         `LogisticsChannelService::migrate_existing_feature_cameras::migrate_one`
#         实例化本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_notify_channel_changed` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class _PendingNotification:
    channel_id: int
    feature_name: str
    camera_refs: tuple[_CameraRef, ...] = ()
    feature_action: str | None = None
    camera_added: _CameraRef | None = None


# 功能：定义 `MigrationSummary` 类，封装业务服务相关的状态、约束与操作
# 参数：
#   - `created`（int）：`created` 对应的业务输入值
#   - `skipped`（int）：`skipped` 对应的业务输入值
#   - `failed`（int）：`failed` 对应的业务输入值
#   - `errors`（tuple[str, ...]）：`errors` 对应的业务输入值
# 返回：MigrationSummary；返回新建的 `MigrationSummary` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::migrate_existing_feature_cameras` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class MigrationSummary:
    created: int
    skipped: int
    failed: int
    errors: tuple[str, ...] = ()


# 功能：物流通道配置与摄像头成员管理入口；输入与输出详见下方说明
# 参数：无。
# 返回：LogisticsChannelService；返回新建的 `LogisticsChannelService` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的 `service_db` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelService:
    """物流通道配置与摄像头成员管理入口。"""

    # 功能：读取或查询 `list_channels` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`get_session`、`session.query(LogisticsChannel).filter_by(feature_name=feature_name).order_by(LogisticsChannel.sort_order,
    #          LogisticsChannel.id).all`、`session.query(LogisticsChannel).filter_by(feature_name=feature_name).order_by`、`session.query(LogisticsChannel).filter_by`、`session.query`、`LogisticsChannelListResponse.model_validate({'items':
    #          channels}).model_dump`、`LogisticsChannelListResponse.model_validate`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：批量读取指定物流功能的全部通道成员，按物理摄像头 ID 去重并生成安全清单。
    # 参数：
    #   - `self`（LogisticsChannelService）：当前物流通道服务实例
    #   - `feature_names`（list[str] | tuple[str, ...]）：已完成上层权限裁剪的物流功能标识
    # 返回：list[dict]；返回摄像头基础信息及其通道成员关系，不包含连接地址。
    # 调用关系：
    #   - 调用方：`api/logistics_channels.py` 的 `list_logistics_camera_inventory` 调用本方法
    #   - 内部调用：`require_logistics_feature`、`get_session`、`selectinload`、`session.query`、`dict.setdefault`、`list.sort`、`session.close`。
    # 副作用/注意事项：只读数据库；通过 eager loading 固定查询次数，同一摄像头跨通道或跨功能时只返回一个清单项。
    def list_camera_inventory(
        self,
        feature_names: list[str] | tuple[str, ...],
    ) -> list[dict]:
        features = tuple(dict.fromkeys(
            require_logistics_feature(feature)
            for feature in feature_names
        ))
        if not features:
            return []
        session = get_session()
        try:
            channels = (
                session.query(LogisticsChannel)
                .options(
                    selectinload(LogisticsChannel.cameras)
                    .selectinload(LogisticsChannelCamera.camera)
                )
                .filter(LogisticsChannel.feature_name.in_(features))
                .order_by(
                    LogisticsChannel.feature_name,
                    LogisticsChannel.sort_order,
                    LogisticsChannel.id,
                )
                .all()
            )
            inventory: dict[int, dict] = {}
            for channel in channels:
                for member in channel.cameras:
                    camera = member.camera
                    if camera is None:
                        continue
                    item = inventory.setdefault(camera.id, {
                        "camera_id": camera.id,
                        "name": camera.name,
                        "shm_name": camera.shm_name,
                        "department": (
                            camera.department
                            or LOGISTICS_FEATURE_DEPARTMENTS[channel.feature_name]
                        ),
                        "enabled": bool(camera.enable),
                        "memberships": [],
                    })
                    item["memberships"].append({
                        "feature_name": channel.feature_name,
                        "channel_id": channel.id,
                        "channel_name": channel.name,
                        "enabled": bool(channel.enabled and member.enabled),
                    })
            items = list(inventory.values())
            for item in items:
                item["memberships"].sort(key=lambda membership: (
                    membership["feature_name"],
                    membership["channel_id"],
                ))
            items.sort(key=lambda item: item["camera_id"])
            return items
        finally:
            session.close()

    # 功能：读取或查询 `get_channel` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::create_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_config`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel_and_config` 调用本符号；另有
    #         5 处静态调用
    #   - 内部调用：`require_logistics_feature`、`get_session`、`self._query_channel`、`self._detail`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_channel(self, feature_name: str, channel_id: int) -> dict | None:
        feature_name = require_logistics_feature(feature_name)
        session = get_session()
        try:
            channel = self._query_channel(session, feature_name, channel_id)
            return self._detail(channel) if channel is not None else None
        finally:
            session.close()

    # 功能：创建或构建 `create_channel` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `name`（str）：业务对象名称
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`(name or
    #          '').strip`、`ValueError`、`self._run_write_transaction`、`self._channel_integrity_value_error`、`logger.warning`、`self._notify_channel_changed`、`self.get_channel`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    def create_channel(self, feature_name: str, name: str) -> dict:
        feature_name = require_logistics_feature(feature_name)
        normalized_name = (name or "").strip()
        if not normalized_name:
            raise ValueError("通道名称不能为空")

        # 功能：创建或构建 `create` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`session.query(LogisticsChannel).filter_by(feature_name=feature_name,
        #          name=normalized_name).first`、`session.query(LogisticsChannel).filter_by`、`session.query`、`ValueError`、`LogisticsChannel`、`session.add`、`session.flush`。
        # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
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

    # 功能：更新或保存 `update_channel` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    #   - `payload`（Any）：接口或事件携带的业务数据
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._payload_dict`、`self._reject_none`、`self._run_write_transaction`、`self._channel_integrity_value_error`、`logger.warning`、`self._notify_channel_changed`、`self.get_channel`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    def update_channel(self, feature_name: str, channel_id: int, payload: Any) -> dict | None:
        feature_name = require_logistics_feature(feature_name)
        values = self._payload_dict(payload)
        self._reject_none(values, ("enabled", "sort_order"))

        # 功能：更新或保存 `update` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._lock_channels`、`channels.get`、`self._apply_channel_values`、`session.flush`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def update(session):
            channels = self._lock_channels(session, [channel_id])
            channel = channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                return False
            self._apply_channel_values(session, channel, feature_name, channel_id, values)
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

    # 功能：删除或清理 `delete_channel` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._run_membership_transaction`、`self._notify_channel_changed`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def delete_channel(self, feature_name: str, channel_id: int) -> bool:
        feature_name = require_logistics_feature(feature_name)

        # 功能：实现 `discover` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._discover_memberships`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def discover():
            return self._discover_memberships(channel_ids=(channel_id,))

        # 功能：删除或清理 `delete` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        #   - `discovery`（未显式标注）：`discovery` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._lock_membership_state`、`state.channels.get`、`tuple`、`_CameraRef`、`sorted`、`self._set_feature_enabled`、`session.delete`。
        # 副作用/注意事项：可能读取或修改数据库事务。
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

    # 功能：更新或保存 `update_config` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    #   - `payload`（Any）：接口或事件携带的业务数据
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._payload_dict`、`self._reject_none`、`self._run_write_transaction`、`ValueError`、`logger.warning`、`self._notify_channel_changed`、`self.get_channel`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    def update_config(self, feature_name: str, channel_id: int, payload: Any) -> dict | None:
        feature_name = require_logistics_feature(feature_name)
        values = self._payload_dict(payload)
        self._reject_none(values, (
            "detection_start",
            "detection_end",
            "confidence_threshold",
            "empty_grace_seconds",
            "multi_grace_seconds",
            "alarm_interval",
        ))

        # 功能：更新或保存 `update` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._lock_channels`、`channels.get`、`self._apply_config_values`、`session.flush`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def update(session):
            channels = self._lock_channels(session, [channel_id])
            channel = channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                return False
            self._apply_config_values(channel, values)
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

    # 功能：在单事务内更新通道元数据和检测配置，并只发布一次刷新事件；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    #   - `channel_payload`（Any）：`channel_payload` 对应的业务输入值
    #   - `config_payload`（Any | None）：`config_payload` 对应的业务输入值
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._payload_dict`、`self._reject_none`、`self._run_write_transaction`、`self._channel_integrity_value_error`、`logger.warning`、`self._notify_channel_changed`、`self.get_channel`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    def update_channel_and_config(
        self,
        feature_name: str,
        channel_id: int,
        channel_payload: Any,
        config_payload: Any | None,
    ) -> dict | None:
        """在单事务内更新通道元数据和检测配置，并只发布一次刷新事件。"""
        feature_name = require_logistics_feature(feature_name)
        channel_values = self._payload_dict(channel_payload)
        config_values = self._payload_dict(config_payload)
        self._reject_none(channel_values, ("enabled", "sort_order"))
        self._reject_none(config_values, (
            "detection_start",
            "detection_end",
            "confidence_threshold",
            "empty_grace_seconds",
            "multi_grace_seconds",
            "alarm_interval",
        ))

        # 功能：更新或保存 `update` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._lock_channels`、`channels.get`、`self._apply_channel_values`、`self._apply_config_values`、`session.flush`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def update(session):
            channels = self._lock_channels(session, [channel_id])
            channel = channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                return False
            self._apply_channel_values(
                session,
                channel,
                feature_name,
                channel_id,
                channel_values,
            )
            self._apply_config_values(channel, config_values)
            session.flush()
            return True

        try:
            updated = self._run_write_transaction(update)
        except IntegrityError as exc:
            error = self._channel_integrity_value_error(exc)
            logger.warning(f"[LogisticsChannelService] 原子更新通道约束冲突: {error}")
            raise error from exc
        if not updated:
            return None
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    # 功能：创建或构建 `add_existing_camera` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._run_membership_transaction`、`self._notify_channel_changed`、`self.get_channel`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def add_existing_camera(
        self,
        feature_name: str,
        channel_id: int,
        camera_id: int,
    ) -> dict:
        feature_name = require_logistics_feature(feature_name)

        # 功能：实现 `discover` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._discover_memberships`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def discover():
            return self._discover_memberships(
                camera_ids=(camera_id,),
                channel_ids=(channel_id,),
            )

        # 功能：创建或构建 `add` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        #   - `discovery`（未显式标注）：`discovery` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的 `FakeRuntimeManager::start`
        #         调用本符号；`AiVision/platform/logistics_channel/runtime.py` 的 `LogisticsChannelRuntime::_install_feature_locked`
        #         调用本符号；`scripts/.comment_annotator.py` 的 `dependencies` 调用本符号；`scripts/.comment_annotator.py` 的 `order` 调用本符号；另有 5
        #         处静态调用
        #   - 内部调用：`self._lock_membership_state`、`state.channels.get`、`ValueError`、`state.cameras.get`、`self._insert_locked_member`、`_CameraRef`。
        # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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

    # 功能：创建或构建 `create_camera_and_bind` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    #   - `payload`（Any）：接口或事件携带的业务数据
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._payload_dict`、`values.get`、`ValueError`、`self._run_membership_transaction`、`self._binding_integrity_value_error`、`logger.warning`、`self._notify_channel_changed`、`self.get_channel`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
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

        # 功能：实现 `discover` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._discover_memberships`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def discover():
            return self._discover_memberships(channel_ids=(channel_id,))

        # 功能：创建或构建 `create_and_bind` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        #   - `discovery`（未显式标注）：`discovery` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._lock_membership_state`、`state.channels.get`、`ValueError`、`self._require_capacity`、`camera_config_manager.create_camera_record`、`self._insert_locked_member`、`_CameraRef`。
        # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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
            camera = camera_config_manager.create_camera_record(session, values)
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

    # 功能：实现 `move_camera` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `target_channel_id`（int）：`target_channel_id` 对应业务对象的唯一标识
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._run_membership_transaction`、`_PendingNotification`、`notifications.append`、`self._publish_notifications`、`self.get_channel`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def move_camera(
        self,
        feature_name: str,
        camera_id: int,
        target_channel_id: int,
    ) -> dict:
        feature_name = require_logistics_feature(feature_name)

        # 功能：实现 `discover` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._discover_memberships`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def discover():
            return self._discover_memberships(
                camera_ids=(camera_id,),
                channel_ids=(target_channel_id,),
            )

        # 功能：实现 `move` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        #   - `discovery`（未显式标注）：`discovery` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._lock_membership_state`、`state.channels.get`、`ValueError`、`state.cameras.get`、`len`、`self._require_capacity`、`self._next_sort_order`、`bool`、`session.delete`、`session.flush`
        #          等共 14 个调用。
        # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
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

    # 功能：实现 `reorder_members` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    #   - `camera_ids`（list[int]）：`camera_ids` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`list`、`len`、`set`、`ValueError`、`self._run_membership_transaction`、`self._notify_channel_changed`、`self.get_channel`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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

        # 功能：实现 `discover` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._discover_memberships`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def discover():
            return self._discover_memberships(channel_ids=(channel_id,))

        # 功能：实现 `reorder` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        #   - `discovery`（未显式标注）：`discovery` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._lock_membership_state`、`state.channels.get`、`ValueError`、`len`、`set`、`enumerate`、`session.flush`。
        # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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

    # 功能：原子更新成员参与状态，并只发布一次通道刷新事件；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `enabled`（bool）：是否启用相应能力
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._run_membership_transaction`、`self._notify_channel_changed`、`self.get_channel`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def set_member_enabled(
        self,
        feature_name: str,
        channel_id: int,
        camera_id: int,
        enabled: bool,
    ) -> dict:
        """原子更新成员参与状态，并只发布一次通道刷新事件。"""
        feature_name = require_logistics_feature(feature_name)

        # 功能：实现 `discover` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._discover_memberships`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def discover():
            return self._discover_memberships(
                camera_ids=(camera_id,),
                channel_ids=(channel_id,),
            )

        # 功能：更新或保存 `update` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        #   - `discovery`（未显式标注）：`discovery` 对应的业务输入值
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._lock_membership_state`、`state.channels.get`、`ValueError`、`next`、`bool`、`session.flush`。
        # 副作用/注意事项：校验或执行失败时会主动抛出异常。
        def update(session, discovery):
            state = self._lock_membership_state(
                session,
                discovery,
                required_channel_ids=(channel_id,),
                required_camera_ids=(camera_id,),
            )
            channel = state.channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                raise ValueError(f"物流通道不存在: {channel_id}")
            member = next(
                (
                    row
                    for row in state.members
                    if row.channel_id == channel_id and row.camera_id == camera_id
                ),
                None,
            )
            if member is None:
                raise ValueError("通道摄像头成员不存在")
            member.enabled = bool(enabled)
            session.flush()

        self._run_membership_transaction(discover, update)
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    # 功能：删除或清理 `remove_camera` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_logistics_feature`、`self._run_membership_transaction`、`self._notify_channel_changed`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def remove_camera(
        self,
        feature_name: str,
        channel_id: int,
        camera_id: int,
    ) -> bool:
        feature_name = require_logistics_feature(feature_name)

        # 功能：实现 `discover` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._discover_memberships`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def discover():
            return self._discover_memberships(
                camera_ids=(camera_id,),
                channel_ids=(channel_id,),
            )

        # 功能：删除或清理 `remove` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `session`（未显式标注）：数据库会话或运行会话
        #   - `discovery`（未显式标注）：`discovery` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self._lock_membership_state`、`state.channels.get`、`state.cameras.get`、`next`、`session.delete`、`self._set_feature_enabled`、`_CameraRef`。
        # 副作用/注意事项：可能读取或修改数据库事务。
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

    # 功能：实现 `migrate_existing_feature_cameras` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：MigrationSummary；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`get_session`、`sorted`、`all_specs`、`read_session.query(spec.orm_class.camera_id).filter(spec.orm_class.enable.is_(True)).order_by(spec.orm_class.camera_id).all`、`read_session.query(spec.orm_class.camera_id).filter(spec.orm_class.enable.is_(True)).order_by`、`read_session.query(spec.orm_class.camera_id).filter`、`read_session.query`、`spec.orm_class.enable.is_`、`candidates.extend`、`read_session.close`
    #          等共 17 个调用。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
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
                        confidence_threshold=(
                            cfg.CONF_THRESHOLD
                            if cfg.CONF_THRESHOLD is not None
                            else DEFAULT_PERSON_CONFIDENCE_THRESHOLD
                        ),
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

    # 功能：实现 `_payload_dict` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `payload`（Any）：接口或事件携带的业务数据
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_config`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel_and_config`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::create_camera_and_bind` 调用本符号；另有 1
    #         处静态调用
    #   - 内部调用：`isinstance`、`dict`、`hasattr`、`payload.model_dump`、`TypeError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @staticmethod
    def _payload_dict(payload: Any) -> dict:
        if payload is None:
            return {}
        if isinstance(payload, dict):
            return dict(payload)
        if hasattr(payload, "model_dump"):
            return payload.model_dump(exclude_unset=True)
        raise TypeError("payload 必须是 dict 或 Pydantic model")

    # 功能：实现 `_apply_channel_values` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `channel`（LogisticsChannel）：`channel` 对应的业务输入值
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    #   - `values`（dict）：`values` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel::update`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel_and_config::update`
    #         调用本符号
    #   - 内部调用：`(values['name'] or '').strip`、`ValueError`、`session.query(LogisticsChannel).filter(LogisticsChannel.feature_name ==
    #          feature_name, LogisticsChannel.name == name, LogisticsChannel.id !=
    #          channel_id).first`、`session.query(LogisticsChannel).filter`、`session.query`、`setattr`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def _apply_channel_values(
        self,
        session,
        channel: LogisticsChannel,
        feature_name: str,
        channel_id: int,
        values: dict,
    ) -> None:
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

    # 功能：实现 `_apply_config_values` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `channel`（LogisticsChannel）：`channel` 对应的业务输入值
    #   - `values`（dict）：`values` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_config::update`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel_and_config::update`
    #         调用本符号
    #   - 内部调用：`setattr`、`values.get`、`self._payload_dict`、`bool`、`alarm.get`、`horn.get`、`wechat.get`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    def _apply_config_values(self, channel: LogisticsChannel, values: dict) -> None:
        for field in (
            "detection_start",
            "detection_end",
            "confidence_threshold",
            "empty_grace_seconds",
            "multi_grace_seconds",
            "alarm_interval",
        ):
            if field in values:
                setattr(channel, field, values[field])
        alarm = values.get("alarm")
        if alarm is None:
            return
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

    # 功能：读取或查询 `_query_channel` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::get_channel` 调用本符号
    #   - 内部调用：`session.query(LogisticsChannel).options(selectinload(LogisticsChannel.cameras)).filter_by(feature_name=feature_name,
    #          id=channel_id).first`、`session.query(LogisticsChannel).options(selectinload(LogisticsChannel.cameras)).filter_by`、`session.query(LogisticsChannel).options`、`session.query`、`selectinload`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _query_channel(session, feature_name: str, channel_id: int):
        return (
            session.query(LogisticsChannel)
            .options(selectinload(LogisticsChannel.cameras))
            .filter_by(feature_name=feature_name, id=channel_id)
            .first()
        )

    # 功能：每次尝试都创建新 session，并完整重跑锁定与业务校验；输入与输出详见下方说明
    # 参数：
    #   - `operation`（未显式标注）：`operation` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::create_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_config`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel_and_config` 调用本符号
    #   - 内部调用：`range`、`session_scope`、`operation`、`_database_error_code`、`logger.warning`、`sleep`、`RuntimeError`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
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

    # 功能：每次尝试先用已关闭短 session discovery，再开启全新正式事务；输入与输出详见下方说明
    # 参数：
    #   - `discover`（未显式标注）：`discover` 对应的业务输入值
    #   - `operation`（未显式标注）：`operation` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::delete_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::add_existing_camera`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::create_camera_and_bind`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::move_camera` 调用本符号；另有 6 处静态调用
    #   - 内部调用：`range`、`discover`、`session_scope`、`operation`、`_database_error_code`、`logger.warning`、`sleep`、`RuntimeError`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
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

    # 功能：实现 `_channel_integrity_value_error` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `exc`（IntegrityError）：`exc` 对应的业务输入值
    # 返回：ValueError；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::create_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel_and_config`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_binding_integrity_value_error`
    #         调用本符号
    #   - 内部调用：`str(exc.orig or exc).lower`、`str`、`ValueError`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：实现 `_binding_integrity_value_error` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `exc`（IntegrityError）：`exc` 对应的业务输入值
    # 返回：ValueError；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::create_camera_and_bind` 调用本符号
    #   - 内部调用：`str(exc.orig or exc).lower`、`str`、`_camera_integrity_value_error`、`cls._channel_integrity_value_error`、`ValueError`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @classmethod
    def _binding_integrity_value_error(cls, exc: IntegrityError) -> ValueError:
        message = str(exc.orig or exc).lower()
        if "ai_camera_config" in message or "shm_name" in message:
            return _camera_integrity_value_error(exc)
        channel_error = cls._channel_integrity_value_error(exc)
        if "已存在" in str(channel_error):
            return channel_error
        return ValueError("物流通道绑定数据约束冲突")

    # 功能：实现 `_reject_none` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `values`（dict）：`values` 对应的业务输入值
    #   - `fields`（tuple[str, ...]）：`fields` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_config`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel_and_config` 调用本符号
    #   - 内部调用：`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @staticmethod
    def _reject_none(values: dict, fields: tuple[str, ...]) -> None:
        for field in fields:
            if field in values and values[field] is None:
                raise ValueError(f"{field} 不可为 None")

    # 功能：锁层级 1：所有既有 channel 必须按 ID 升序先锁定；输入与输出详见下方说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `channel_ids`（未显式标注）：`channel_ids` 对应的业务输入值
    # 返回：dict[int, LogisticsChannel]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel::update`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_config::update`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel_and_config::update`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_lock_membership_state` 调用本符号；另有 1
    #         处静态调用
    #   - 内部调用：`sorted`、`set`、`session.query(LogisticsChannel).filter(LogisticsChannel.id.in_(ids)).order_by(LogisticsChannel.id).with_for_update().all`、`session.query(LogisticsChannel).filter(LogisticsChannel.id.in_(ids)).order_by(LogisticsChannel.id).with_for_update`、`session.query(LogisticsChannel).filter(LogisticsChannel.id.in_(ids)).order_by`、`session.query(LogisticsChannel).filter`、`session.query`、`LogisticsChannel.id.in_`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：锁层级 2：channel 全部锁定后，再按 ID 升序锁 camera；输入与输出详见下方说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `camera_ids`（未显式标注）：`camera_ids` 对应的业务输入值
    # 返回：dict[int, AiCameraConfig]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_lock_membership_state` 调用本符号
    #   - 内部调用：`sorted`、`set`、`session.query(AiCameraConfig).filter(AiCameraConfig.id.in_(ids)).order_by(AiCameraConfig.id).with_for_update().all`、`session.query(AiCameraConfig).filter(AiCameraConfig.id.in_(ids)).order_by(AiCameraConfig.id).with_for_update`、`session.query(AiCameraConfig).filter(AiCameraConfig.id.in_(ids)).order_by`、`session.query(AiCameraConfig).filter`、`session.query`、`AiCameraConfig.id.in_`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：迁移专用例外：锁 camera 后只写新 channel，不获取既有 channel 锁；输入与输出详见下方说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的
    #         `LogisticsChannelService::migrate_existing_feature_cameras::migrate_one` 调用本符号
    #   - 内部调用：`session.query(AiCameraConfig).filter_by(id=camera_id).with_for_update().first`、`session.query(AiCameraConfig).filter_by(id=camera_id).with_for_update`、`session.query(AiCameraConfig).filter_by`、`session.query`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _lock_migration_camera(session, camera_id: int):
        """迁移专用例外：锁 camera 后只写新 channel，不获取既有 channel 锁。"""
        return (
            session.query(AiCameraConfig)
            .filter_by(id=camera_id)
            .with_for_update()
            .first()
        )

    # 功能：在独立短 session 中发现锁集合；返回前一定关闭该 session；输入与输出详见下方说明
    # 参数：
    #   - `camera_ids`（未显式标注）：`camera_ids` 对应的业务输入值；默认值为 `()`
    #   - `channel_ids`（未显式标注）：`channel_ids` 对应的业务输入值；默认值为 `()`
    # 返回：_MembershipDiscovery；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::delete_channel::discover`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::add_existing_camera::discover`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::create_camera_and_bind::discover`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::move_camera::discover` 调用本符号；另有 4
    #         处静态调用
    #   - 内部调用：`tuple`、`sorted`、`set`、`get_session`、`conditions.append`、`LogisticsChannelCamera.camera_id.in_`、`LogisticsChannelCamera.channel_id.in_`、`_MembershipDiscovery`、`session.query(LogisticsChannelCamera).filter(or_(*conditions)).order_by(LogisticsChannelCamera.id).all`、`session.query(LogisticsChannelCamera).filter(or_(*conditions)).order_by`
    #          等共 19 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：仅锁 membership 表；MySQL 编译结果不得包含 JOIN；输入与输出详见下方说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `member_ids`（未显式标注）：`member_ids` 对应的业务输入值；默认值为 `()`
    #   - `camera_ids`（未显式标注）：`camera_ids` 对应的业务输入值；默认值为 `()`
    #   - `channel_ids`（未显式标注）：`channel_ids` 对应的业务输入值；默认值为 `()`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的
    #         `LogisticsChannelService::migrate_existing_feature_cameras::migrate_one`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_lock_membership_state`
    #         调用本符号；`AiVision/tests/test_logistics_channel_service.py` 的
    #         `test_membership_locking_sql_is_current_read_without_channel_join` 调用本符号
    #   - 内部调用：`conditions.append`、`LogisticsChannelCamera.id.in_`、`tuple`、`LogisticsChannelCamera.camera_id.in_`、`LogisticsChannelCamera.channel_id.in_`、`session.query`、`query.filter`、`or_`、`query.order_by(LogisticsChannelCamera.id).with_for_update`、`query.order_by`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：MySQL RR 正式事务：channels→cameras→memberships 全部 current read；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `discovery`（_MembershipDiscovery）：`discovery` 对应的业务输入值
    #   - `required_channel_ids`（未显式标注）：`required_channel_ids` 对应的业务输入值；默认值为 `()`
    #   - `required_camera_ids`（未显式标注）：`required_camera_ids` 对应的业务输入值；默认值为 `()`
    # 返回：_LockedMembershipState；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::delete_channel::delete`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::add_existing_camera::add`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的
    #         `LogisticsChannelService::create_camera_and_bind::create_and_bind`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::move_camera::move` 调用本符号；另有 3 处静态调用
    #   - 内部调用：`sorted`、`self._lock_channels`、`self._lock_cameras`、`self._build_membership_lock_query(session,
    #          member_ids=discovery.member_ids, camera_ids=discovery.camera_scope,
    #          channel_ids=discovery.channel_scope).all`、`self._build_membership_lock_query`、`_MembershipLockSetChanged`、`_LockedMembershipState`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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

    # 功能：实现 `_detail` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `channel`（LogisticsChannel）：`channel` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::get_channel` 调用本符号
    #   - 内部调用：`LogisticsChannelDetailResponse.model_validate(channel).model_dump`、`LogisticsChannelDetailResponse.model_validate`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _detail(channel: LogisticsChannel) -> dict:
        return LogisticsChannelDetailResponse.model_validate(channel).model_dump(mode="python")

    # 功能：实现 `_require_capacity` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `members`（list[LogisticsChannelCamera]）：`members` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::create_camera_and_bind::create_and_bind`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::move_camera::move`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_insert_locked_member` 调用本符号
    #   - 内部调用：`sum`、`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @staticmethod
    def _require_capacity(members: list[LogisticsChannelCamera], channel_id: int) -> None:
        member_count = sum(member.channel_id == channel_id for member in members)
        if member_count >= MAX_CAMERAS_PER_CHANNEL:
            raise ValueError(f"每个物流通道最多绑定 {MAX_CAMERAS_PER_CHANNEL} 路摄像头")

    # 功能：实现 `_next_sort_order` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `members`（list[LogisticsChannelCamera]）：`members` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::move_camera::move`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_insert_locked_member` 调用本符号
    #   - 内部调用：`max`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _next_sort_order(members: list[LogisticsChannelCamera], channel_id: int) -> int:
        sort_orders = [
            member.sort_order
            for member in members
            if member.channel_id == channel_id
        ]
        return 0 if not sort_orders else max(sort_orders) + 1

    # 功能：实现 `_insert_locked_member` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
    #   - `channel`（未显式标注）：`channel` 对应的业务输入值
    #   - `camera`（未显式标注）：摄像头配置或实体
    #   - `members`（未显式标注）：`members` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::add_existing_camera::add`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的
    #         `LogisticsChannelService::create_camera_and_bind::create_and_bind` 调用本符号
    #   - 内部调用：`self._require_capacity`、`session.add`、`LogisticsChannelCamera`、`self._next_sort_order`、`self._set_feature_enabled`、`session.flush`。
    # 副作用/注意事项：可能读取或修改数据库事务。
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

    # 功能：更新或保存 `_set_feature_enabled` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `enabled`（bool）：是否启用相应能力
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::delete_channel::delete`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::move_camera::move`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::remove_camera::remove`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_insert_locked_member` 调用本符号
    #   - 内部调用：`all_specs`、`session.query(spec.orm_class).filter_by(camera_id=camera_id).first`、`session.query(spec.orm_class).filter_by`、`session.query`、`spec.orm_class`、`session.add`。
    # 副作用/注意事项：可能读取或修改数据库事务。
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

    # 功能：仅在事务提交后调用；通知异常记录告警但不破坏已提交事务；输入与输出详见下方说明
    # 参数：
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `camera_refs`（tuple[_CameraRef, ...]）：`camera_refs` 对应的业务输入值；默认值为 `()`
    #   - `feature_action`（str | None）：`feature_action` 对应的业务输入值；默认值为 `None`
    #   - `camera_added`（_CameraRef | None）：`camera_added` 对应的业务输入值；默认值为 `None`
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::create_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::delete_channel`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_config` 调用本符号；另有 7 处静态调用
    #   - 内部调用：`LogisticsChannelService._publish_notifications`、`_PendingNotification`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：一次重载缓存后发布一批已提交事务的事件；输入与输出详见下方说明
    # 参数：
    #   - `notifications`（list[_PendingNotification]）：`notifications` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::move_camera`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::migrate_existing_feature_cameras`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_notify_channel_changed` 调用本符号
    #   - 内部调用：`config_cache.reload`、`config_event_bus.publish`、`ConfigChangeEvent`、`logger.warning`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
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
