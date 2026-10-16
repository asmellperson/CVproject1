"""统一收集喇叭的真实引用，供删除确认、归属校验和提交后运行刷新复用。"""
from __future__ import annotations

import hashlib
import json

from AiVision.core.logger import logger
from AiVision.departments import DEPARTMENT_SPECS
from .schema import HornReference, HornUsage


def collect_references(session, horn_id: int, *, lock: bool = False) -> list[tuple[object, HornReference]]:
    """读取绑定本身，不以告警开关或页面可见性过滤，避免遗漏保留的旧配置。"""
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.features._shared.orm import FeatureConfigBase
    from AiVision.features.registry import all_specs
    from AiVision.features.logistics_channel.orm import LogisticsChannel
    from AiVision.features.guard_behavior.orm import GuardBehaviorAlarmPolicy, GuardBehaviorSite
    from AiVision.alarms.types import VIOLATION_TYPE_META

    specs = all_specs()
    result = []

    def rows(model):
        query = session.query(model).filter(model.horn_id == horn_id).order_by(model.id)
        return (query.with_for_update() if lock else query).all()

    def reference(row, *, kind, feature, resource_id, resource_name, department, enabled, alarm_label=None):
        spec = specs.get(feature)
        department_spec = DEPARTMENT_SPECS.get(department)
        item = HornReference(
            key=f"{row.__tablename__}:{row.id}", kind=kind, feature=feature,
            feature_label=spec.display_name if spec else feature,
            department=department, department_label=department_spec.display_name if department_spec else "未分配事业部",
            resource_id=resource_id, resource_name=resource_name,
            detection_enabled=enabled, horn_enabled=bool(row.horn_enable), audio_id=row.horn_event_id,
            alarm_label=alarm_label,
        )
        result.append((row, item))

    for spec in specs.values():
        if not issubclass(spec.orm_class, FeatureConfigBase):
            continue
        for row in rows(spec.orm_class):
            camera = session.get(AiCameraConfig, row.camera_id)
            reference(row, kind="camera", feature=spec.name, resource_id=row.camera_id,
                      resource_name=camera.name if camera else f"摄像头 #{row.camera_id}",
                      department=camera.department if camera else None,
                      enabled=bool(row.enable and camera and camera.enable))
    for row in rows(LogisticsChannel):
        reference(row, kind="logistics_channel", feature=row.feature_name, resource_id=row.id,
                  resource_name=row.name, department=row.department, enabled=bool(row.enabled))
    for row in rows(GuardBehaviorAlarmPolicy):
        site = session.get(GuardBehaviorSite, row.site_id)
        reference(row, kind="guard_site", feature="guard_behavior", resource_id=row.site_id,
                  resource_name=site.name if site else f"保安室 #{row.site_id}",
                  department=site.department if site else None, enabled=bool(site and site.enabled),
                  alarm_label=VIOLATION_TYPE_META.get(row.violation_type, {}).get("label"))
    return sorted(result, key=lambda pair: pair[1].key)


def usage_snapshot(horn, references) -> HornUsage:
    """版本包含影响范围及设备启停状态，确认期间有变化必须重新查看。"""
    values = {"horn_id": horn.id, "device_enabled": bool(horn.enable),
              "references": [reference.model_dump() for _, reference in references]}
    identity = {"department": horn.department, "name": horn.name, "url": horn.url}
    revision = hashlib.sha256(json.dumps({**values, "identity": identity}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return HornUsage(**values, revision=revision)


def notify_detached(references: list[HornReference]) -> None:
    """提交后定向刷新配置；单条刷新失败记录原因，不将已完成删除伪装成回滚。"""
    from AiVision.core.cache import config_cache
    from AiVision.core.events import ConfigChangeEvent, config_event_bus

    seen = set()
    for item in references:
        key = (item.kind, item.feature, item.resource_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            if item.kind == "camera":
                config_cache.refresh_function(item.resource_id, item.feature)
                config_event_bus.publish(ConfigChangeEvent(
                    change_type=f"{item.feature}_config_updated", camera_id=item.resource_id))
            elif item.kind == "logistics_channel":
                config_event_bus.publish(ConfigChangeEvent(
                    change_type="logistics_channel_updated",
                    new_value={"channel_id": item.resource_id, "feature_name": item.feature}))
            else:
                from AiVision.runtime.orchestrator import get_orchestrator
                try:
                    orchestrator = get_orchestrator()
                except RuntimeError:
                    logger.debug("[HornBinding] 运行服务未启动，保安室将在启动时读取配置")
                else:
                    orchestrator.refresh_guard_site(item.resource_id)
        except Exception as exc:
            logger.warning(f"[HornBinding] {item.kind} {item.resource_id} 解绑后刷新失败（{type(exc).__name__}）")
