"""物流通道配置和成员管理的事务入口。

统一校验事业部、成员容量及唯一归属；成员变更通过专用事务层固定
加锁顺序并处理并发重试。只有数据库提交成功后才刷新缓存和通知运行时。
"""
from __future__ import annotations
from AiVision.departments.department_registry import require_department

from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError      # 数据库完整性错误，数据库运行错误
from sqlalchemy.orm import selectinload, with_loader_criteria                          # SQLAlchemy 的预加载关联数据

from AiVision.core.cache import config_cache
from AiVision.core.db import get_session
from AiVision.core.events import ConfigChangeEvent, config_event_bus
from AiVision.core.logger import logger
from AiVision.features.registry import all_specs
from AiVision.features._shared.orm import CameraFeatureConfigBase
from AiVision.alarms.devices.binding import validate_horn_binding
from AiVision.cameras.orm import AiCameraConfig
from AiVision.cameras.config_manager import (
    _camera_integrity_value_error,
    camera_config_manager,
)                                                     # 摄像头配置与采集由 cameras/ 管理

from .constants import (
    MAX_CAMERAS_PER_CHANNEL,
    require_logistics_feature,
)
from .membership_transaction import MembershipTransaction
from .orm import LogisticsChannel, LogisticsChannelCamera
from .schema import (
    LogisticsChannelDetailResponse, LogisticsChannelListResponse,
    LogisticsChannelUpdate, LogisticsChannelConfigUpdate, LogisticsChannelMemberCreate,
    LogisticsChannelConfigResponse, LogisticsCameraRoiResponse, LogisticsCameraRoiUpdate,
)

@dataclass(frozen=True)
class _CameraRef:
    """事务提交以后的再发事件"""
    camera_id: int
    shm_name: str

@dataclass(frozen=True)
class _PendingNotification:
    """数据库事务成功以后，准备发什么通知"""
    channel_id: int
    feature_name: str
    camera_refs: tuple[_CameraRef, ...] = ()
    feature_action: str | None = None
    camera_added: _CameraRef | None = None


class LogisticsChannelService(MembershipTransaction):
    """物流通道配置与摄像头成员管理入口。"""
    def list_channels(self, feature_name: str, departments: list[str] | tuple[str, ...] | None = None) -> dict:
        """按功能及可选事业部范围返回有序通道列表，并通过响应模型校验。"""
        feature_name = require_logistics_feature(feature_name)
        session = get_session()
        try:
            query = session.query(LogisticsChannel).filter_by(feature_name=feature_name)
            if departments is not None:
                query = query.filter(LogisticsChannel.department.in_(departments))
            channels = query.order_by(LogisticsChannel.sort_order, LogisticsChannel.id).all()
            # 用Pydantic Schema把ORM数据校验并转换成API允许返回的结构
            return LogisticsChannelListResponse.model_validate(
                {"items": channels}
            ).model_dump(mode="python")
        finally:
            session.close()

    def camera_inventory_status(self, departments, orchestrator) -> list[dict]:
        """同一份通道快照同时供总览与物流清单使用。"""
        from .constants import LOGISTICS_FEATURES

        items = self.list_camera_inventory(list(LOGISTICS_FEATURES), departments=departments)
        states = {}
        for item in items:
            for membership in item["memberships"]:
                key = (membership["feature_name"], membership["channel_id"])
                if key not in states:
                    states[key] = orchestrator.get_logistics_channel_status(*key) if orchestrator is not None else None
                camera_states = states[key]["camera_states"] if states[key] is not None else {}
                camera_state = camera_states.get(str(item["camera_id"]), {})
                membership["online"] = bool(membership["enabled"] and camera_state.get("online"))
            item["online"] = any(member["online"] for member in item["memberships"])
        return items

    def list_camera_inventory(
        self,
        feature_names: list[str] | tuple[str, ...],
        departments: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict]:
        """查看多个物流功能下，都有哪些摄像头，以及他们属于哪些通道"""
        # 校验、去重、以及保持原顺序
        features = tuple(dict.fromkeys(
            require_logistics_feature(feature)
            for feature in feature_names
        ))
        if not features:
            return []
        session = get_session()
        try:
            # 准备好：LogisticsChannel、LogisticsChannelCamera、AiCameraConfig
            query = (
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
            )
            if departments is not None:
                query = query.filter(LogisticsChannel.department.in_(departments)).options(
                    with_loader_criteria(AiCameraConfig, AiCameraConfig.department.in_(departments))
                )
            channels = query.all()
            inventory: dict[int, dict] = {}
            # 遍历每个通道
            for channel in channels:
                # 遍历每个通道里的每个摄像头
                for member in channel.cameras:
                    camera = member.camera
                    if camera is None:
                        continue
                    # setdefault:没有就创建，有就直接拿
                    item = inventory.setdefault(camera.id, {
                        "camera_id": camera.id,
                        "name": camera.name,
                        "shm_name": camera.shm_name,
                        "department": camera.department,
                        "enabled": bool(camera.enable),
                        "memberships": [],
                    })
                    item["memberships"].append({
                        "feature_name": channel.feature_name,
                        "channel_id": channel.id,
                        "channel_name": channel.name,
                        "enabled": bool(channel.enabled and member.enabled),      # 这台摄像头在当前通道里的物流检测关系是否实际启用
                    })
            # 先把inventory从dict转list
            items = list(inventory.values())
            # 每个摄像头内部的memberships按功能和通道id排序
            for item in items:
                item["memberships"].sort(key=lambda membership: (
                    membership["feature_name"],
                    membership["channel_id"],
                ))
            # 最后所有摄像头iD按照摄像头id排序
            items.sort(key=lambda item: item["camera_id"])
            return items
        finally:
            session.close()

    def get_channel(self, feature_name: str, channel_id: int) -> dict | None:
        """查询一个物流通道"""
        feature_name = require_logistics_feature(feature_name)
        session = get_session()
        try:
            channel = self._query_channel(session, feature_name, channel_id)
            return self._detail(channel) if channel is not None else None
        finally:
            session.close()

    def create_channel(self, feature_name: str, name: str, department: str) -> dict:
        """新建一个物流通道"""
        # 物流通道名不能为空
        feature_name = require_logistics_feature(feature_name)
        department = require_department(department)
        normalized_name = (name or "").strip()
        if not normalized_name:
            raise ValueError("通道名称不能为空")
        # 创建
        def create(session):
            """在写事务中核对名称唯一性并返回新通道 ID。"""
            duplicate = (
                session.query(LogisticsChannel)
                .filter_by(feature_name=feature_name, department=department, name=normalized_name)
                .first()
            )
            # 同一个功能、同一个事业部下，通道名称不能重复
            if duplicate is not None:
                raise ValueError(f"同一事业部下通道名称已存在: {normalized_name}")
            # 创建ORM对象
            channel = LogisticsChannel(name=normalized_name, feature_name=feature_name, department=department)
            session.add(channel)
            session.flush()
            return channel.id      # 拿到新创建的通道id

        try:
            # 真正的创建交给_run_writer_transaction
            channel_id = self._run_write_transaction(create)
        except IntegrityError as exc:
            error = self._channel_integrity_value_error(exc)
            logger.warning(f"[LogisticsChannelService] 创建通道约束冲突: {error}")
            raise error from exc
        # 创建成功后发事件
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    def delete_channel(self, feature_name: str, channel_id: int) -> bool:
        """
        删除一个物流通道
            删除物流通道还需要处理摄像头里面摄像头成员关系，摄像头对应物流功能的enable，以及Runtime刷新
        """
        feature_name = require_logistics_feature(feature_name)

        def discover():
            """_discover_membership:在真正锁数据库之前，先看看这个 Channel 牵涉哪些 Camera 和成员关系。"""
            return self._discover_memberships(channel_ids=(channel_id,))

        def delete(session, discovery):
            # 重新查询并锁住本次删除涉及的 Channel / Camera / Member
            """锁定关联后关闭成员功能、删除绑定与通道，返回提交后通知所需身份。"""
            state = self._lock_membership_state(
                session,
                discovery,
                required_channel_ids=(channel_id,),
            )
            # 从锁住后的通道字典里面拿channel_id → LogisticsChannel ORM
            channel = state.channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                return None
            # 找出这个物流通道里的所有成员
            members = [
                member for member in state.members if member.channel_id == channel_id
            ]
            # 先保存，因为Runtime还需要知道哪些摄像头受影响，所提前保存最小信息camera_id和shm_name
            camera_refs = tuple(
                _CameraRef(camera_id, state.cameras[camera_id].shm_name)
                for camera_id in sorted({member.camera_id for member in members})
                if camera_id in state.cameras
            )
            for member in members:
                # 把这台摄像头对应物流功能的配置：enable=True改成enable=False
                self._set_feature_enabled(session, feature_name, member.camera_id, False)
                # 删除通道摄像头的成员关系
                session.delete(member)
            # 删通道
            session.delete(channel)
            return camera_refs
        # discover：先找可能受影响的数据，开事务，锁 Channel / Camera / Membership，确认锁住后的数据仍和 discover 时一致，执行 delete()，commit，如果中间关系被其他请求改了就重新来
        camera_refs = self._run_membership_transaction(discover, delete)
        if camera_refs is None:
            return False
        # 告诉摄像头通道变了，哪些摄像头受影响，对应功能被disabled
        self._notify_channel_changed(
            channel_id,
            feature_name,
            camera_refs=camera_refs,
            feature_action="disabled",
        )
        return True

    def update_channel_and_config(
        self,
        feature_name: str,
        channel_id: int,
        channel_payload: Any,
        config_payload: Any | None,
    ) -> dict | None:
        """在单事务内更新通道元数据和检测配置，并只发布一次刷新事件。"""
        feature_name = require_logistics_feature(feature_name)
        channel_values = LogisticsChannelUpdate.model_validate(channel_payload).model_dump(exclude_unset=True)
        config_values = (
            LogisticsChannelConfigUpdate.model_validate(config_payload).model_dump(exclude_unset=True)
            if config_payload is not None else {}
        )
        # 如果调用方明确传了这些字段，就不能传None
        self._reject_none(channel_values, ("enabled", "sort_order"))

        def update(session):
            # 对目标通道做数据库锁
            """锁定通道，合并保存元数据及配置，并校验最终配置与喇叭绑定。"""
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
            if config_values:
                # 局部更新必须与数据库中保留的字段一起校验，失败时回滚整个事务。
                LogisticsChannelConfigResponse.model_validate(channel)
                validate_horn_binding(session, channel.horn_enable, channel.horn_id, channel.horn_event_id, department=channel.department)
            # 把ORM改动发送到数据库
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
        # 更新完成后只通知一次Runtime
        self._notify_channel_changed(channel_id, feature_name)
        return self.get_channel(feature_name, channel_id)

    def add_existing_camera(
        self,
        feature_name: str,
        channel_id: int,
        camera_id: int,
    ) -> dict:
        """已经存在的摄像头加入某个物流通道"""
        feature_name = require_logistics_feature(feature_name)

        def discover():
            """预查询目标通道和摄像头的全部关联，确定正式事务锁集合。"""
            return self._discover_memberships(
                camera_ids=(camera_id,),
                channel_ids=(channel_id,),
            )

        def add(session, discovery):
            """锁定后重查归属及事业部，建立成员并启用对应功能。"""
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
            self._require_camera_department(camera, channel)
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
        """新建摄像头，同时加入通道"""
        feature_name = require_logistics_feature(feature_name)
        values = LogisticsChannelMemberCreate.model_validate(payload).model_dump(exclude_unset=True)

        def discover():
            """发现目标通道成员范围，供新摄像头绑定时核对容量。"""
            return self._discover_memberships(channel_ids=(channel_id,))

        def create_and_bind(session, discovery):
            """在同一事务中新建同事业部摄像头并插入通道成员。"""
            state = self._lock_membership_state(
                session,
                discovery,
                required_channel_ids=(channel_id,),
            )
            channel = state.channels.get(channel_id)
            if channel is None or channel.feature_name != feature_name:
                raise ValueError(f"物流通道不存在: {channel_id}")
            self._require_capacity(state.members, channel.id)
            camera = camera_config_manager.create_camera_record(session, {**values, "department": channel.department})
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
        """摄像头从一个通道移到另一个通道"""
        feature_name = require_logistics_feature(feature_name)

        def discover():
            """发现源归属与目标通道，保证移动时两侧均纳入加锁范围。"""
            return self._discover_memberships(
                camera_ids=(camera_id,),
                channel_ids=(target_channel_id,),
            )

        def move(session, discovery):
            """锁定源目标关系后移动唯一成员，保留成员开关并追加到目标末尾。"""
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
            self._require_camera_department(camera, target)
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
        """调整通道内摄像头排列顺序"""
        feature_name = require_logistics_feature(feature_name)
        requested_ids = list(camera_ids)
        if len(requested_ids) != len(set(requested_ids)):
            raise ValueError("camera_ids 不可重复")

        def discover():
            """预查询通道完整成员集合，以发现排序期间发生的并发增删。"""
            return self._discover_memberships(channel_ids=(channel_id,))

        def reorder(session, discovery):
            """要求请求恰好覆盖当前成员集合，再按输入顺序写入排序值。"""
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

    def set_member_enabled(
        self,
        feature_name: str,
        channel_id: int,
        camera_id: int,
        enabled: bool,
    ) -> dict:
        """摄像头还在通道里但临时不参与检测"""
        feature_name = require_logistics_feature(feature_name)

        def discover():
            """确定成员开关修改涉及的通道与摄像头锁集合。"""
            return self._discover_memberships(
                camera_ids=(camera_id,),
                channel_ids=(channel_id,),
            )

        def update(session, discovery):
            """确认成员仍在目标通道后只修改成员参与开关。"""
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

    def remove_camera(
        self,
        feature_name: str,
        channel_id: int,
        camera_id: int,
    ) -> bool:
        """摄像头正式离开通道"""
        feature_name = require_logistics_feature(feature_name)

        def discover():
            """发现解绑涉及的全部关联，避免与移动等操作使用不同锁范围。"""
            return self._discover_memberships(
                camera_ids=(camera_id,),
                channel_ids=(channel_id,),
            )

        def remove(session, discovery):
            """删除成员并关闭对应功能，返回提交后清理运行状态所需身份。"""
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


    def get_camera_roi(self, feature_name: str, channel_id: int, camera_id: int) -> dict:
        """校验功能、通道成员及事业部后读取该摄像头唯一 ROI。"""
        feature_name = require_logistics_feature(feature_name)
        config_class = all_specs()[feature_name].orm_class
        session = get_session()
        try:
            row = (
                session.query(config_class, AiCameraConfig, LogisticsChannel)
                .select_from(config_class)
                .join(AiCameraConfig, AiCameraConfig.id == config_class.camera_id)
                .join(LogisticsChannelCamera, LogisticsChannelCamera.camera_id == AiCameraConfig.id)
                .join(LogisticsChannel, LogisticsChannel.id == LogisticsChannelCamera.channel_id)
                .filter(
                    LogisticsChannel.id == channel_id,
                    LogisticsChannel.feature_name == feature_name,
                    AiCameraConfig.id == camera_id,
                )
                .one_or_none()
            )
            if row is None:
                raise ValueError("物流通道成员或 ROI 配置不存在")
            config, camera, channel = row
            self._require_camera_department(camera, channel)
            return self._camera_roi_response(camera, config)
        finally:
            session.close()

    def update_camera_roi(self, feature_name: str, channel_id: int, camera_id: int, payload: dict) -> dict:
        """在成员事务内保存 ROI，提交后发布配置刷新通知。"""
        feature_name = require_logistics_feature(feature_name)
        values = LogisticsCameraRoiUpdate.model_validate(payload).model_dump()

        def discover():
            """预查询 ROI 保存期间需要保护的成员关系。"""
            return self._discover_memberships(camera_ids=(camera_id,), channel_ids=(channel_id,))

        def update(session, discovery):
            # 沿用成员写事务的锁顺序，防止 ROI 保存期间被解绑、移动或改变摄像头归属。
            """锁定并重新核对归属，再写 ROI，防止保存期间被解绑或移动。"""
            state = self._lock_membership_state(
                session, discovery,
                required_channel_ids=(channel_id,), required_camera_ids=(camera_id,),
            )
            channel = state.channels.get(channel_id)
            camera = state.cameras.get(camera_id)
            if channel is None or channel.feature_name != feature_name or camera is None or not any(
                member.channel_id == channel_id and member.camera_id == camera_id for member in state.members
            ):
                raise ValueError("物流通道成员不存在")
            self._require_camera_department(camera, channel)
            config = (
                session.query(all_specs()[feature_name].orm_class)
                .filter_by(camera_id=camera_id)
                .with_for_update()
                .one_or_none()
            )
            if config is None:
                raise ValueError("物流摄像头 ROI 配置不存在")
            config.roi_pos = values["roi_pos"]
            session.flush()
            return self._camera_roi_response(camera, config), _CameraRef(camera.id, camera.shm_name)

        response, camera_ref = self._run_membership_transaction(discover, update)
        self._notify_channel_changed(
            channel_id, feature_name, camera_refs=(camera_ref,), feature_action="config_updated",
        )
        return response

    @staticmethod
    def _camera_roi_response(camera: AiCameraConfig, config: CameraFeatureConfigBase) -> dict:
        """返回最小摄像头身份及校验后的归一化 ROI。"""
        return LogisticsCameraRoiResponse.model_validate({
            "camera": {"id": camera.id, "name": camera.name, "shm_name": camera.shm_name, "enable": camera.enable},
            "roi_pos": config.roi_pos,
        }).model_dump()

    # ---------------  helper -----------------
    def _apply_channel_values(
        self,
        session,
        channel: LogisticsChannel,
        feature_name: str,
        channel_id: int,
        values: dict,
    ) -> None:
        """负责修改通道基本属性"""
        if "name" in values:
            name = (values["name"] or "").strip()
            if not name:
                raise ValueError("通道名称不能为空")
            # 修改名字
            duplicate = (
                session.query(LogisticsChannel)
                .filter(
                    LogisticsChannel.feature_name == feature_name,
                    LogisticsChannel.department == channel.department,
                    LogisticsChannel.name == name,
                    LogisticsChannel.id != channel_id,
                )
                .first()
            )
            if duplicate is not None:
                raise ValueError(f"同一事业部下通道名称已存在: {name}")
            channel.name = name
        for field in ("enabled", "sort_order"):
            if field in values:
                # setattr：动态写属性
                setattr(channel, field, values[field])

    def _apply_config_values(self, channel: LogisticsChannel, values: dict) -> None:
        """仅写入已校验且明确提交的通道字段。"""
        for field in (
            "detection_start",
            "detection_end",
            "confidence_threshold",
            "model_iou_threshold",
            "min_box_area",
            "min_aspect_ratio",
            "max_aspect_ratio",
            "cap_interval",
            "empty_grace_seconds",
            "multi_grace_seconds",
            "alarm_interval",
        ):
            if field in values:
                setattr(channel, field, values[field])
        alarm = values.get("alarm")
        if alarm is None:
            return
        # 是否保留告警记录
        if "sql_enable" in alarm:
            channel.sql_enable = bool(alarm["sql_enable"])
        # 把前端配置映射到通道ORM
        horn = alarm.get("horn", {})
        if horn:
            channel.horn_enable = bool(horn.get("enabled", False))
            if "horn_id" in horn:
                channel.horn_id = horn["horn_id"]
            if "horn_event_id" in horn:
                channel.horn_event_id = horn["horn_event_id"]
        # 微信的配置
        wechat = alarm.get("wechat", {})
        if wechat:
            channel.wechat_enable = bool(wechat.get("enabled", False))
            channel.wechat_user = wechat.get("user", "")

    @staticmethod
    def _query_channel(session, feature_name: str, channel_id: int):
        """按功能和通道 ID 查询，并预加载成员供详情转换。"""
        return (
            session.query(LogisticsChannel)
            .options(selectinload(LogisticsChannel.cameras))
            .filter_by(feature_name=feature_name, id=channel_id)
            .first()
        )



    @staticmethod
    def _channel_integrity_value_error(exc: IntegrityError) -> ValueError:
        """把数据库名称唯一约束等冲突转换为稳定业务提示。"""
        message = str(exc.orig or exc).lower()
        if (
            "uq_logistics_channel_feature_department_name" in message
            or (
                "ai_logistics_channel.feature_name" in message
                and "ai_logistics_channel.name" in message
            )
        ):
            return ValueError("同一事业部下通道名称已存在")
        return ValueError("物流通道数据约束冲突")

    @classmethod
    def _binding_integrity_value_error(cls, exc: IntegrityError) -> ValueError:
        """区分摄像头资源冲突、通道重名和一般绑定约束错误。"""
        message = str(exc.orig or exc).lower()
        if "ai_camera_config" in message or "shm_name" in message:
            return _camera_integrity_value_error(exc)
        channel_error = cls._channel_integrity_value_error(exc)
        if "已存在" in str(channel_error):
            return channel_error
        return ValueError("物流通道绑定数据约束冲突")

    @staticmethod
    def _reject_none(values: dict, fields: tuple[str, ...]) -> None:
        """nullable=False但是却传了None值，在业务层报错"""
        for field in fields:
            if field in values and values[field] is None:
                raise ValueError(f"{field} 不可为 None")







    @staticmethod
    def _detail(channel: LogisticsChannel) -> dict:
        """将通道 ORM 与已加载成员转换为完整响应结构。"""
        return LogisticsChannelDetailResponse.model_validate(channel).model_dump(mode="python")

    @staticmethod
    def _require_capacity(members: list[LogisticsChannelCamera], channel_id: int) -> None:
        """按当前锁定成员数量检查通道容量，停用成员仍占用名额。"""
        member_count = sum(member.channel_id == channel_id for member in members)
        if member_count >= MAX_CAMERAS_PER_CHANNEL:
            raise ValueError(f"每个物流通道最多绑定 {MAX_CAMERAS_PER_CHANNEL} 路摄像头")

    @staticmethod
    def _next_sort_order(members: list[LogisticsChannelCamera], channel_id: int) -> int:
        """在现有最大排序值之后追加新成员。"""
        sort_orders = [
            member.sort_order
            for member in members
            if member.channel_id == channel_id
        ]
        return 0 if not sort_orders else max(sort_orders) + 1

    def _insert_locked_member(self, session, feature_name, channel, camera, members) -> None:
        """再次核对事业部和容量，建立启用成员并同步功能开关。"""
        self._require_camera_department(camera, channel)
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
    def _require_camera_department(camera: AiCameraConfig, channel: LogisticsChannel) -> None:
        """拒绝未指定事业部或与通道事业部不一致的摄像头。"""
        if not camera.department:
            raise ValueError("摄像头 department 为空，请先明确摄像头事业部")
        if camera.department != channel.department:
            raise ValueError("摄像头 department 必须与通道所属事业部一致")

    @staticmethod
    def _set_feature_enabled(session, feature_name: str, camera_id: int, enabled: bool):
        """创建缺失的逐摄像头配置或更新其功能开关，由外层事务提交。"""
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
