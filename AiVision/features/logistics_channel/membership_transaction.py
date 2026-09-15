"""物流成员事务：短会话 discovery、固定锁顺序和完整事务重试。"""
from __future__ import annotations

from dataclasses import dataclass
from time import sleep

from sqlalchemy import or_
from sqlalchemy.exc import OperationalError

from AiVision.core.db import get_session, session_scope
from AiVision.core.logger import logger
from AiVision.cameras.config_manager import _database_error_code
from AiVision.cameras.orm import AiCameraConfig
from .orm import LogisticsChannel, LogisticsChannelCamera

# 数据库重试参数，1205：数据库等太久，1213：死锁
_MYSQL_RETRYABLE_LOCK_ERRORS = frozenset({1205, 1213})
# 最多三次
_MAX_WRITE_ATTEMPTS = 3
# 第一次失败等20ms，第二次失败等40ms，第三次不用重试
_WRITE_RETRY_BACKOFF_SECONDS = 0.02

class _MembershipLockSetChanged(RuntimeError):
    """预先查到的摄像头和通道的关系，在真正加锁之前已经被别人改了，这个时候抛这个错误，并且准备重新查一遍，再重新开启事务"""

@dataclass(frozen=True)                # frozen:冻结，创建后不允许修改
class _DiscoveredMembership:
    """预查询阶段发现的一条物流摄像头的归属关系"""
    member_id: int                     # 成员关系ID
    channel_id: int                    # 通道id
    camera_id: int                     # 摄像头id
    feature_name: str

@dataclass(frozen=True)
class _MembershipDiscovery:
    """某次操作开始前，发现的完整关联范围，后面会用于判断：加锁以后看到的数据，和预查询的数据是不是同一批"""
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
    """真正锁住以后拿到的数据库对象"""
    channels: dict[int, LogisticsChannel]
    cameras: dict[int, AiCameraConfig]
    members: list[LogisticsChannelCamera]


class MembershipTransaction:
    """提供事务机制，业务校验由调用方在锁定后执行。"""
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
