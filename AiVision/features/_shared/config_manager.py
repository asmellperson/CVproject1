"""普通摄像头功能的配置读取、保存和展示顺序管理。

通过 FeatureSpec 定位 ORM 与 Schema；保存完整校验后的配置，在事务
提交后刷新缓存并发布事件。物流通道和保安室的成员、策略及 ROI 使用
各自专用接口，避免通用入口绕过其业务约束。
"""
from __future__ import annotations
from typing import Optional

from AiVision.core.db import session_scope, get_session
from AiVision.core.events import config_event_bus, ConfigChangeEvent
from AiVision.core.cache import config_cache
from AiVision.features._shared.spec import FeatureSpec
from AiVision.features._shared.orm import FeatureConfigBase
from AiVision.alarms.devices.binding import validate_horn_binding
from AiVision.cameras.orm import AiCameraConfig, get_camera_by_key
from AiVision.departments.department_registry import require_department


class FeatureCameraOrderConflict(ValueError):
    """功能摄像头集合变化，需重新加载后再排序。"""


class FeatureCameraScopeConflict(ValueError):
    """授权检查后摄像头归属变化，必须重新读取资源再保存。"""


class FeatureConfigManager:
    """所有功能配置的 CRUD 入口。
    
    通过 FeatureSpec.orm_class 反射目标表,所以一份代码服务所有功能。
    """

    # ---------- Read ----------
    def get_config(self, spec: FeatureSpec, shm_name: str | int) -> Optional[dict]:
        """读取指定摄像头的指定功能配置。
        
        返回前端需要的统一格式:
            {
                "camera": {"id", "name", "shm_name", "enable"},
                "feature": "blocks",
                "config": {"enable", "value"}，直接告警的功能另含 alarm
            }
        """
        session = get_session()
        try:
            # 先是找摄像头
            camera = self._get_camera_by_key(session, shm_name)
            if camera is None:
                return None
            # 查摄像头的功能配置
            cfg = (
                session.query(spec.orm_class)
                .filter_by(camera_id=camera.id)
                .first()
            )
            # 没有记录时返回后端完整默认配置。
            if cfg is None:
                return {
                    "camera": self._camera_to_dict(camera),
                    "feature": spec.name,
                    "config": spec.config_schema().model_dump(),
                }

            return {
                "camera": self._camera_to_dict(camera),
                "feature": spec.name,
                "config": spec.config_schema.model_validate(cfg.to_config_dict()).model_dump(),
            }
        finally:
            session.close()

    # ---------- Write ----------
    def reorder_cameras(self, spec: FeatureSpec, department: str, camera_ids: list[int]) -> None:
        """只更新当前功能已启用摄像头的展示顺序，不触发检测配置热更新。"""
        if "sort_order" not in spec.orm_class.__table__.columns:
            raise ValueError("此功能请通过成员排序接口调整顺序")
        department = require_department(department)
        if any(type(camera_id) is not int or camera_id <= 0 for camera_id in camera_ids):
            raise ValueError("camera_ids 必须只包含正整数摄像头主键")
        if len(camera_ids) != len(set(camera_ids)):
            raise ValueError("camera_ids 不允许重复")
        with session_scope() as session:
            # 与功能启停保持先锁摄像头、再锁配置的顺序，避免排序覆盖并发停用。
            cameras = (session.query(AiCameraConfig)
                       .filter_by(department=department)
                       .order_by(AiCameraConfig.id).with_for_update().all())
            configs = (session.query(spec.orm_class)
                       .filter(spec.orm_class.camera_id.in_([camera.id for camera in cameras]),
                               spec.orm_class.enable.is_(True))
                       .order_by(spec.orm_class.camera_id).with_for_update().all())
            by_id = {config.camera_id: config for config in configs}
            if set(camera_ids) != set(by_id):
                raise FeatureCameraOrderConflict("当前功能的摄像头集合已变化，请重新加载后排序")
            for position, camera_id in enumerate(camera_ids):
                by_id[camera_id].sort_order = position

    def save_config(
        self,
        spec: FeatureSpec,
        shm_name: str | int,
        payload: dict,
        *,
        expected_department: str | None = None,
    ) -> Optional[dict]:
        """校验并保存普通功能的完整配置，缺失参数按对应 Schema 补齐默认值。

        Args:
            spec: 指定功能的声明，提供 ORM 和配置校验模型。
            shm_name: 摄像头查询键，通常为共享内存标识。
            payload: enable/value 配置；直接告警功能还包含 alarm。
            expected_department: 外部授权通过的事业部，在锁定资源后复核归属。

        Returns:
            保存后重新读取的配置；摄像头不存在时返回 None。

        Raises:
            ValueError: 配置非法、启用前置条件不满足、喇叭绑定无效，或功能
                必须通过专用业务接口修改。

        数据库提交成功后才重载缓存并发出配置及启停事件；此阶段失败不代表
        已经提交的数据库配置被回滚。
        """
        from AiVision.features.logistics_channel.constants import LOGISTICS_FEATURES
        if spec.name == "guard_behavior":
            raise ValueError("保安室摄像头配置仅通过成员和 ROI 接口修改")
        if spec.name in LOGISTICS_FEATURES:
            raise ValueError("物流摄像头仅通过通道 ROI 接口修改，Feature 生命周期由成员绑定维护")
        payload = spec.config_schema.model_validate(payload).model_dump()
        with session_scope() as session:
            camera = self._get_camera_by_key(session, shm_name)
            if camera is None:
                return None

            # 锁住摄像头，保证启用期间事业部归属有效。
            session.refresh(camera, with_for_update=True)
            if expected_department is not None and camera.department != expected_department:
                raise FeatureCameraScopeConflict("摄像头所属事业部已变化，请重新读取配置")
            cfg = (
                session.query(spec.orm_class)
                .filter_by(camera_id=camera.id)
                .with_for_update()
                .first()
            )
            # 保存前先记住旧的enable，功能发生启停变化需要发detect_human_enabled.如果只是修改阈值，只发config_updated
            old_enable = bool(cfg.enable) if cfg is not None else False
            new_enable = bool(payload.get("enable", False))
            if new_enable and not old_enable and not camera.enable:
                raise ValueError("请先在平台启用该摄像头")
            if new_enable:
                try:
                    require_department(camera.department)
                except ValueError as exc:
                    raise ValueError("摄像头必须先设置所属事业部/子公司") from exc
            # 配置不存在就创建
            if cfg is None:
                cfg = spec.orm_class(camera_id=camera.id)
                session.add(cfg)
                session.flush()
            cfg.apply_config_dict(payload)
            if isinstance(cfg, FeatureConfigBase):
                validate_horn_binding(session, cfg.horn_enable, cfg.horn_id, cfg.horn_event_id, department=camera.department)

            # 提交后刷新缓存 + 发事件
            camera_id = camera.id
            camera_shm = camera.shm_name
            session.flush()  # 确保 ORM 字段都已落库

        # session_scope 已 commit,这里从数据库重载配置缓存后再发热更新事件。
        # 前端按功能添加/删除摄像头本质是更新 enable,consumer 收到事件时必须读到最新数据库值。
        config_cache.reload()
        # 任何配置修改都发配置变化事件，Runtime收到后刷新配置即可
        config_event_bus.publish(ConfigChangeEvent(
            change_type=f"{spec.name}_config_updated",
            camera_id=camera_id,
            camera_name=camera_shm,
        ))
        # 只有enable真变化发如detect_human_enabled这样的变化事件，orchetrator可能要启Consumer、停Consumer、启动Camera运行链、停止Camera对应处理
        if old_enable != new_enable:
            action = "enabled" if new_enable else "disabled"
            config_event_bus.publish(ConfigChangeEvent(
                change_type=f"{spec.name}_{action}",
                camera_id=camera_id,
                camera_name=camera_shm,
            ))

        # 重新读一次返回（确保前端拿到数据库的最终状态）
        return self.get_config(spec, shm_name)

    # ---------- Helpers ----------
    @staticmethod
    def _get_camera_by_key(session, key: str | int) -> Optional[AiCameraConfig]:
        """字符串按 shm_name / name / 数字 id 或 'camera_{id}' 的优先级查询"""
        return get_camera_by_key(session, key)

    @staticmethod
    def _camera_to_dict(camera: AiCameraConfig) -> dict:
        """把摄像头ORM转成前端需要的最小信息"""
        return {
            "id": camera.id,
            "name": camera.name,
            "shm_name": camera.shm_name or f"camera_{camera.id}",
            "enable": bool(camera.enable),
        }


# 单例,API 层和 Orchestrator 共用
feature_config_manager = FeatureConfigManager()
