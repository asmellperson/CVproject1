"""保安室数据事务；不启动检测，也不修改物理摄像头属性。"""
from contextlib import closing, contextmanager

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from AiVision.alarms.devices.binding import validate_horn_binding
from AiVision.cameras.orm import AiCameraConfig
from AiVision.core import db
from AiVision.departments.department_registry import require_department
from .constants import GUARD_ALARM_TYPES, MAX_CAMERAS_PER_SITE, SITE_POLICY_DEFAULTS, require_alarm_type
from .orm import (
    GuardBehaviorAlarmPolicy, GuardBehaviorCameraConfig, GuardBehaviorSite,
    GuardBehaviorSiteCamera, GuardBehaviorSitePolicy,
)
from .schema import (
    GuardBehaviorAlarmPolicyResponse, GuardBehaviorAlarmPolicyUpdate,
    GuardBehaviorCameraRoiResponse, GuardBehaviorCameraRoiUpdate,
    GuardBehaviorMemberCreate, GuardBehaviorMemberEnabledUpdate, GuardBehaviorMemberOrder,
    GuardBehaviorMemberResponse, GuardBehaviorSiteCreate, GuardBehaviorSitePolicyResponse,
    GuardBehaviorSitePolicySchema, GuardBehaviorSitePolicyUpdate,
    GuardBehaviorSiteResponse, GuardBehaviorSiteUpdate,
    GuardBehaviorRuntimeCameraConfig, GuardBehaviorRuntimePolicy,
    GuardBehaviorRuntimeAlarmPolicy, GuardBehaviorRuntimeMember, GuardBehaviorRuntimeSiteConfig,
)


@contextmanager
def _write_session():
    """统一事务边界，将提交或刷新时的完整性冲突转换为可读业务错误。"""
    try:
        with db.session_scope() as session:
            yield session
    except IntegrityError:
        # 包含 flush 和 commit 失败；公共事务已回滚并关闭会话。
        raise ValueError("配置写入冲突：名称或摄像头成员已存在，或关联记录已失效") from None


def _positive_id(value: int) -> int:
    """拒绝布尔值、非整数及非正 ID。"""
    if type(value) is not int or value <= 0:
        raise ValueError("ID 必须为正整数")
    return value


class GuardBehaviorService:
    """管理保安室配置事务，并提供脱离数据库会话的运行快照。"""
    @classmethod
    def _site_runtime_snapshot(cls, session, site) -> GuardBehaviorRuntimeSiteConfig:
        """一次读取成员及策略，校验事业部和功能配置后构造站点快照。"""
        rows = (session.query(GuardBehaviorSiteCamera, AiCameraConfig, GuardBehaviorCameraConfig)
                .join(AiCameraConfig, GuardBehaviorSiteCamera.camera_id == AiCameraConfig.id)
                .outerjoin(GuardBehaviorCameraConfig, GuardBehaviorCameraConfig.camera_id == AiCameraConfig.id)
                .filter(GuardBehaviorSiteCamera.site_id == site.id)
                .order_by(GuardBehaviorSiteCamera.sort_order, GuardBehaviorSiteCamera.id).all())
        if any(config is None or camera.department != site.department for _, camera, config in rows):
            raise ValueError("Site 成员缺少 Feature 配置或事业部不一致")
        policies = session.query(GuardBehaviorAlarmPolicy).filter_by(site_id=site.id).all()
        return GuardBehaviorRuntimeSiteConfig(
            site_id=site.id, site_name=site.name, department=site.department, enabled=site.enabled,
            members=tuple(GuardBehaviorRuntimeMember(
                camera_id=camera.id, camera_name=camera.name, shm_name=camera.shm_name,
                member_enabled=member.enabled, physical_enabled=camera.enable,
                feature_enabled=config.enable, sort_order=member.sort_order,
            ) for member, camera, config in rows),
            policy=GuardBehaviorRuntimePolicy.model_validate(cls._policy(session, site.id)),
            alarm_policies=tuple(GuardBehaviorRuntimeAlarmPolicy.model_validate(policy) for policy in policies),
        )

    def get_runtime_site_config(self, site_id: int) -> GuardBehaviorRuntimeSiteConfig | None:
        """读取指定站点运行配置，不存在时返回 None。"""
        with closing(db.get_session()) as session:
            site = session.get(GuardBehaviorSite, _positive_id(site_id))
            return None if site is None else self._site_runtime_snapshot(session, site)

    def list_runtime_site_configs(self) -> list[GuardBehaviorRuntimeSiteConfig]:
        """按展示顺序生成全部站点的完整运行快照。"""
        with closing(db.get_session()) as session:
            sites = session.query(GuardBehaviorSite).order_by(GuardBehaviorSite.sort_order, GuardBehaviorSite.id).all()
            return [self._site_runtime_snapshot(session, site) for site in sites]

    @staticmethod
    def _runtime_query(session):
        """联合成员、站点、物理摄像头及专用配置，建立单摄运行配置查询。"""
        return (session.query(GuardBehaviorSiteCamera, GuardBehaviorSite, AiCameraConfig,
                              GuardBehaviorCameraConfig, GuardBehaviorSitePolicy)
                .join(GuardBehaviorSite, GuardBehaviorSiteCamera.site_id == GuardBehaviorSite.id)
                .join(AiCameraConfig, GuardBehaviorSiteCamera.camera_id == AiCameraConfig.id)
                .join(GuardBehaviorCameraConfig, GuardBehaviorCameraConfig.camera_id == AiCameraConfig.id)
                .join(GuardBehaviorSitePolicy, GuardBehaviorSitePolicy.site_id == GuardBehaviorSite.id))

    @staticmethod
    def _runtime_snapshot(row) -> GuardBehaviorRuntimeCameraConfig:
        """将联合查询行转换为不可变单摄快照，ROI 不保留可变 ORM 引用。"""
        member, site, camera, config, policy = row
        roi = GuardBehaviorCameraRoiResponse.model_validate(config).vehicle_roi_pos
        return GuardBehaviorRuntimeCameraConfig(
            camera_id=camera.id, camera_name=camera.name, shm_name=camera.shm_name,
            fps=float(camera.fps), department=camera.department,
            site_id=site.id, site_name=site.name, site_enabled=site.enabled,
            member_enabled=member.enabled, feature_enabled=config.enable,
            vehicle_roi_pos=tuple(tuple(point) for point in roi),
            policy=GuardBehaviorRuntimePolicy.model_validate(policy),
        )

    def get_runtime_camera_config(self, camera_id: int) -> GuardBehaviorRuntimeCameraConfig | None:
        """按摄像头查询有效成员配置，无完整关联时返回 None。"""
        with closing(db.get_session()) as session:
            row = self._runtime_query(session).filter(AiCameraConfig.id == _positive_id(camera_id)).first()
            return None if row is None else self._runtime_snapshot(row)

    def list_runtime_camera_configs(self) -> list[GuardBehaviorRuntimeCameraConfig]:
        """按站点和成员顺序生成单摄配置快照。"""
        with closing(db.get_session()) as session:
            rows = self._runtime_query(session).order_by(
                GuardBehaviorSite.id, GuardBehaviorSiteCamera.sort_order, GuardBehaviorSiteCamera.id).all()
            return [self._runtime_snapshot(row) for row in rows]

    @staticmethod
    def _site(session, site_id: int, *, lock: bool = False):
        """获取必需的站点，可按写入场景加行锁。"""
        site = session.get(GuardBehaviorSite, _positive_id(site_id), with_for_update=lock)
        if site is None:
            raise ValueError("保安室不存在")
        return site

    @staticmethod
    def _camera(session, camera_id: int):
        """锁定必需的物理摄像头，序列化涉及该摄像头的成员修改。"""
        camera = session.get(AiCameraConfig, _positive_id(camera_id), with_for_update=True)
        if camera is None:
            raise ValueError("摄像头不存在")
        return camera

    @staticmethod
    def _member(session, site_id: int, camera_id: int, *, lock: bool = False):
        """验证摄像头确实属于目标站点，可锁定成员行。"""
        query = session.query(GuardBehaviorSiteCamera).filter_by(
            site_id=site_id, camera_id=_positive_id(camera_id))
        if lock:
            query = query.with_for_update()
        member = query.first()
        if member is None:
            raise ValueError("摄像头不属于当前保安室")
        return member

    @staticmethod
    def _policy(session, site_id: int, *, lock: bool = False):
        """取得必需的站点检测策略，缺失时显式报错。"""
        query = session.query(GuardBehaviorSitePolicy).filter_by(site_id=site_id)
        if lock:
            query = query.with_for_update()
        policy = query.first()
        if policy is None:
            raise ValueError("保安室缺少检测策略")
        return policy

    @staticmethod
    def _camera_config(session, camera_id: int, *, lock: bool = False):
        """取得专用摄像头配置，避免在缺失配置时使用隐式默认值。"""
        query = session.query(GuardBehaviorCameraConfig).filter_by(camera_id=camera_id)
        if lock:
            query = query.with_for_update()
        config = query.first()
        if config is None:
            raise ValueError("摄像头缺少保安行为配置")
        return config

    @classmethod
    def _protect_vehicle_camera(cls, session, site_id: int, camera_id: int):
        """阻止禁用或解绑正在承担车辆检查的摄像头。"""
        policy = cls._policy(session, site_id, lock=True)
        if policy.vehicle_inspection_enabled and policy.vehicle_camera_id == camera_id:
            raise ValueError("当前摄像头正在作为车辆出厂检查摄像头，请先关闭或修改车辆检查配置")

    def list_sites(self, department: str | None = None) -> list[dict]:
        """校验可选事业部过滤条件，按配置顺序返回站点。"""
        if department is not None:
            department = require_department(department)
        with closing(db.get_session()) as session:
            query = session.query(GuardBehaviorSite)
            if department is not None:
                query = query.filter_by(department=department)
            return [GuardBehaviorSiteResponse.model_validate(site).model_dump()
                    for site in query.order_by(GuardBehaviorSite.sort_order, GuardBehaviorSite.id).all()]

    def get_site(self, site_id: int) -> dict:
        """读取站点基础信息并转换为响应结构。"""
        with closing(db.get_session()) as session:
            return GuardBehaviorSiteResponse.model_validate(self._site(session, site_id)).model_dump()

    def create_site(self, name: str, department: str, *, enabled: bool = True, sort_order: int = 0) -> dict:
        """在同一事务中创建站点、默认检测策略和完整四类告警策略。"""
        values = GuardBehaviorSiteCreate(
            name=name, department=department, enabled=enabled, sort_order=sort_order,
        ).model_dump()
        with _write_session() as session:
            site = GuardBehaviorSite(**values)
            session.add(site)
            session.flush()
            session.add(GuardBehaviorSitePolicy(site_id=site.id))
            session.add_all(GuardBehaviorAlarmPolicy(site_id=site.id, violation_type=kind)
                            for kind in GUARD_ALARM_TYPES)
            session.flush()
            return GuardBehaviorSiteResponse.model_validate(site).model_dump()

    def update_site(self, site_id: int, payload: dict) -> dict:
        """锁定站点，合并局部字段后完整校验，再写入提交的变更。"""
        changes = GuardBehaviorSiteUpdate.model_validate(payload).model_dump(exclude_unset=True)
        with _write_session() as session:
            site = self._site(session, site_id, lock=True)
            values = {key: getattr(site, key) for key in GuardBehaviorSiteCreate.model_fields}
            values = GuardBehaviorSiteCreate.model_validate({**values, **changes}).model_dump()
            for key in changes:
                setattr(site, key, values[key])
            session.flush()
            return GuardBehaviorSiteResponse.model_validate(site).model_dump()

    def delete_site(self, site_id: int) -> bool:
        """关闭成员的保安功能并删除站点关联，不删除物理摄像头。"""
        with _write_session() as session:
            site = session.get(GuardBehaviorSite, _positive_id(site_id), with_for_update=True)
            if site is None:
                return False
            members = session.query(GuardBehaviorSiteCamera).filter_by(site_id=site_id).all()
            # 所有成员写操作先锁 Site，再按 ID 锁 Camera，最后修改成员与配置。
            for member in sorted(members, key=lambda item: item.camera_id):
                self._camera(session, member.camera_id)
                self._camera_config(session, member.camera_id, lock=True).enable = False
            session.flush()
            session.delete(site)
            return True

    def list_site_cameras(self, site_id: int) -> list[dict]:
        """按成员顺序返回摄像头及两层启用状态。"""
        with closing(db.get_session()) as session:
            self._site(session, site_id)
            members = (session.query(GuardBehaviorSiteCamera)
                       .options(joinedload(GuardBehaviorSiteCamera.camera))
                       .filter_by(site_id=site_id)
                       .order_by(GuardBehaviorSiteCamera.sort_order, GuardBehaviorSiteCamera.id).all())
            return [GuardBehaviorMemberResponse.model_validate(member).model_dump() for member in members]

    def add_camera(self, site_id: int, camera_id: int) -> dict:
        """校验事业部、唯一归属和容量，原子建立成员并启用专用功能配置。"""
        camera_id = GuardBehaviorMemberCreate(camera_id=camera_id).camera_id
        with _write_session() as session:
            site = self._site(session, site_id, lock=True)
            camera = self._camera(session, camera_id)
            if camera.department != site.department:
                raise ValueError("Camera department 必须与 Site department 一致")
            existing = session.query(GuardBehaviorSiteCamera).filter_by(camera_id=camera_id).with_for_update().first()
            if existing is not None:
                raise ValueError("摄像头已属于一个保安室，不能重复绑定或隐式移动")
            members = session.query(GuardBehaviorSiteCamera).filter_by(site_id=site_id)
            if members.count() >= MAX_CAMERAS_PER_SITE:
                raise ValueError(f"每个保安室最多允许 {MAX_CAMERAS_PER_SITE} 路摄像头")
            last_order = members.with_entities(func.max(GuardBehaviorSiteCamera.sort_order)).scalar()
            member = GuardBehaviorSiteCamera(site_id=site_id, camera=camera, enabled=True,
                                             sort_order=0 if last_order is None else last_order + 1)
            session.add(member)
            config = session.query(GuardBehaviorCameraConfig).filter_by(camera_id=camera_id).with_for_update().first()
            if config is None:
                config = GuardBehaviorCameraConfig(camera_id=camera_id)
                session.add(config)
            config.enable = True
            session.flush()
            return GuardBehaviorMemberResponse.model_validate(member).model_dump()

    def remove_camera(self, site_id: int, camera_id: int) -> None:
        """保护车辆检查绑定后移除成员，同时关闭该摄像头的保安功能。"""
        with _write_session() as session:
            self._site(session, site_id, lock=True)
            self._camera(session, camera_id)
            member = self._member(session, site_id, camera_id, lock=True)
            self._protect_vehicle_camera(session, site_id, camera_id)
            self._camera_config(session, camera_id, lock=True).enable = False
            session.delete(member)

    def set_camera_enabled(self, site_id: int, camera_id: int, enabled: bool) -> dict:
        """修改成员参与状态，关闭前保护正在使用的车辆检查摄像头。"""
        enabled = GuardBehaviorMemberEnabledUpdate(enabled=enabled).enabled
        with _write_session() as session:
            self._site(session, site_id, lock=True)
            self._camera(session, camera_id)
            member = self._member(session, site_id, camera_id, lock=True)
            if not enabled:
                self._protect_vehicle_camera(session, site_id, camera_id)
            member.enabled = enabled
            session.flush()
            return GuardBehaviorMemberResponse.model_validate(member).model_dump()

    def reorder_cameras(self, site_id: int, camera_ids: list[int]) -> None:
        """要求完整且相同的成员集合，在单个事务中重排展示顺序。"""
        camera_ids = GuardBehaviorMemberOrder(camera_ids=camera_ids).camera_ids
        with _write_session() as session:
            self._site(session, site_id, lock=True)
            members = session.query(GuardBehaviorSiteCamera).filter_by(site_id=site_id).with_for_update().all()
            by_camera = {member.camera_id: member for member in members}
            if set(camera_ids) != set(by_camera):
                raise ValueError("排序必须包含当前保安室完整的 camera_id 成员集合")
            for index, camera_id in enumerate(camera_ids):
                by_camera[camera_id].sort_order = index

    def get_policy(self, site_id: int) -> dict:
        """读取站点当前策略，包括物理摄像头删除后可能为空的引用。"""
        with closing(db.get_session()) as session:
            self._site(session, site_id)
            return GuardBehaviorSitePolicyResponse.model_validate(self._policy(session, site_id)).model_dump()

    def update_policy(self, site_id: int, payload: dict) -> dict:
        """合并并校验完整策略，车辆检查目标必须是同事业部已启用成员。"""
        changes = GuardBehaviorSitePolicyUpdate.model_validate(payload).model_dump(exclude_unset=True)
        with _write_session() as session:
            site = self._site(session, site_id, lock=True)
            policy = self._policy(session, site_id, lock=True)
            values = {key: getattr(policy, key) for key in SITE_POLICY_DEFAULTS}
            values = GuardBehaviorSitePolicySchema.model_validate({**values, **changes}).model_dump()
            if values["vehicle_inspection_enabled"]:
                camera = self._camera(session, values["vehicle_camera_id"])
                if camera.department != site.department:
                    raise ValueError("车辆检查 Camera department 必须与 Site department 一致")
                member = self._member(session, site_id, camera.id, lock=True)
                if not member.enabled:
                    raise ValueError("车辆检查摄像头成员必须启用")
            for key, value in values.items():
                setattr(policy, key, value)
            session.flush()
            return GuardBehaviorSitePolicyResponse.model_validate(policy).model_dump()

    def get_camera_roi(self, site_id: int, camera_id: int) -> dict:
        """验证成员归属后读取车辆 ROI。"""
        with closing(db.get_session()) as session:
            self._site(session, site_id)
            self._member(session, site_id, camera_id)
            config = self._camera_config(session, camera_id)
            return GuardBehaviorCameraRoiResponse.model_validate(config).model_dump()

    def update_camera_roi(self, site_id: int, camera_id: int, payload: dict) -> dict:
        """锁定站点与摄像头，将校验后的车辆 ROI 写入专用配置。"""
        values = GuardBehaviorCameraRoiUpdate.model_validate(payload)
        with _write_session() as session:
            self._site(session, site_id, lock=True)
            self._camera(session, camera_id)
            self._member(session, site_id, camera_id, lock=True)
            config = self._camera_config(session, camera_id, lock=True)
            config.vehicle_roi_pos = values.vehicle_roi_pos
            session.flush()
            return GuardBehaviorCameraRoiResponse.model_validate(config).model_dump()

    def list_alarm_policies(self, site_id: int) -> list[dict]:
        """读取并核对完整四类告警策略，配置缺失时显式失败。"""
        with closing(db.get_session()) as session:
            self._site(session, site_id)
            policies = (session.query(GuardBehaviorAlarmPolicy).filter_by(site_id=site_id)
                        .order_by(GuardBehaviorAlarmPolicy.violation_type).all())
            if tuple(policy.violation_type for policy in policies) != GUARD_ALARM_TYPES:
                raise ValueError("保安室必须具有完整的四类报警策略")
            return [GuardBehaviorAlarmPolicyResponse.model_validate(policy).model_dump() for policy in policies]

    def update_alarm_policy(self, site_id: int, violation_type: int, payload: dict) -> dict:
        """合并单类告警配置并验证喇叭绑定，在事务内保存最终策略。"""
        violation_type = require_alarm_type(violation_type)
        changes = GuardBehaviorAlarmPolicyUpdate.model_validate(payload).model_dump(exclude_unset=True)
        with _write_session() as session:
            self._site(session, site_id, lock=True)
            policy = (session.query(GuardBehaviorAlarmPolicy)
                      .filter_by(site_id=site_id, violation_type=violation_type).with_for_update().first())
            if policy is None:
                raise ValueError("保安室缺少该报警策略")
            values = {key: getattr(policy, key) for key in GuardBehaviorAlarmPolicyUpdate.model_fields}
            values = GuardBehaviorAlarmPolicyUpdate.model_validate({**values, **changes}).model_dump()
            validate_horn_binding(session, values["horn_enable"], values["horn_id"], values["horn_event_id"])
            for key, value in values.items():
                setattr(policy, key, value)
            session.flush()
            return GuardBehaviorAlarmPolicyResponse.model_validate(policy).model_dump()
