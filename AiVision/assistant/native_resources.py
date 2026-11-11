"""物流、保安室与喇叭配置适配，复用各自事务和运行时刷新入口。"""
import json
from fastapi import HTTPException
from auth.feature_permissions import feature_departments

from AiVision.alarms.devices.schema import HornUpdate
from AiVision.alarms.devices.service import horn_service
from AiVision.alarms.types import VIOLATION_TYPE_META
from AiVision.cameras.config_manager import camera_config_manager
from AiVision.core.config_revision import configuration_values
from AiVision.features.guard_behavior.service import GuardBehaviorService
from AiVision.features.guard_behavior.schema import (
    GuardBehaviorAlarmPolicyUpdate, GuardBehaviorCameraRoiUpdate, GuardBehaviorMemberEnabledUpdate,
    GuardBehaviorSitePolicyUpdate, GuardBehaviorSiteUpdate,
)
from AiVision.features.logistics_channel.service import logistics_channel_service
from AiVision.features.logistics_channel.schema import (
    LogisticsCameraRoiUpdate, LogisticsChannelMemberEnabledUpdate, LogisticsChannelPatchRequest,
)
from .resources import ConfigurationCatalog, ConfigurationResource, selected_schema
from .schema import ResourceReference


LOGISTICS_FEATURE = "detect_logistics_single_person"
GUARD_SERVICE = GuardBehaviorService()
HornParameters = selected_schema("AssistantHornParameters", HornUpdate, ("name", "enable", "description"))


def reference(kind: str, identifier, name: str, department: str, feature: str | None = None) -> ResourceReference:
    return ResourceReference(key=f"{kind}:{identifier}", kind=kind, name=name, department=department, feature=feature)


def find_native_resources(catalog: ConfigurationCatalog, kind: str, departments: list[str], parent_key: str | None):
    if kind == "logistics":
        # 功能分配对管理员同样生效，查询前先缩小数据库范围。
        scopes = [scope for scope in departments if scope in feature_departments(catalog.user, LOGISTICS_FEATURE)]
        return [reference(kind, row["id"], row["name"], row["department"], LOGISTICS_FEATURE)
                for row in logistics_channel_service.list_channels(LOGISTICS_FEATURE, departments=scopes)["items"]]
    if kind.startswith("logistics_"):
        parent = require_parent(catalog, parent_key, "logistics")
        if parent.reference.department not in departments:
            return []
        channel_id = catalog.positive_id(parent.reference.key.split(":")[1])
        channel = logistics_channel_service.get_channel(LOGISTICS_FEATURE, channel_id)
        names = {row["camera_id"]: row["name"] for row in camera_config_manager.list_cameras(parent.reference.department)}
        return [reference(kind, f"{channel_id}:{row['camera_id']}", names.get(row["camera_id"], f"camera_{row['camera_id']}"),
                          parent.reference.department, LOGISTICS_FEATURE) for row in channel["members"]]
    if kind == "guard":
        return [reference(kind, row["id"], row["name"], scope, "guard_behavior")
                for scope in departments if scope in feature_departments(catalog.user, "guard_behavior")
                for row in GUARD_SERVICE.list_sites(scope)]
    if kind.startswith("guard_"):
        parent = require_parent(catalog, parent_key, "guard")
        if parent.reference.department not in departments:
            return []
        site_id = catalog.positive_id(parent.reference.key.split(":")[1])
        if kind == "guard_policy":
            return [reference(kind, site_id, parent.reference.name + " · 检测规则", parent.reference.department, "guard_behavior")]
        if kind == "guard_alarm":
            return [reference(kind, f"{site_id}:{row['violation_type']}", VIOLATION_TYPE_META[row["violation_type"]]["label"],
                              parent.reference.department, "guard_behavior") for row in GUARD_SERVICE.list_alarm_policies(site_id)]
        return [reference(kind, f"{site_id}:{row['camera_id']}", row["name"], parent.reference.department, "guard_behavior")
                for row in GUARD_SERVICE.list_site_cameras(site_id)]
    if kind == "horn":
        if catalog.user.get("role") not in {"admin", "department_admin"}:
            raise HTTPException(403, "喇叭配置需要管理员权限")
        return [reference(kind, row["id"], row["name"], scope) for scope in departments
                for row in horn_service.list_horns(department=scope)]
    from .global_resources import find_global_resources
    return find_global_resources(catalog, kind, departments)


def require_parent(catalog: ConfigurationCatalog, key: str | None, kind: str) -> ConfigurationResource:
    if not key or not key.startswith(kind + ":"):
        raise ValueError(f"请先查询 {kind} 资源，并提供其 parent_key")
    return catalog.resolve(key)


def resolve_native_resource(catalog: ConfigurationCatalog, parts: list[str]) -> ConfigurationResource:
    kind = parts[0]
    if kind in {"logistics", "logistics_roi", "logistics_member"}:
        return resolve_logistics(catalog, parts)
    if kind in {"guard", "guard_policy", "guard_alarm", "guard_roi", "guard_member"}:
        return resolve_guard(catalog, parts)
    if kind == "horn" and len(parts) == 2:
        if catalog.user.get("role") not in {"admin", "department_admin"}:
            raise HTTPException(403, "喇叭配置需要管理员权限")
        horn_id = catalog.positive_id(parts[1])
        row = horn_service.get_horn(horn_id)
        if row is None:
            raise HTTPException(404, "资源不可访问或不存在")
        catalog.require_department(row["department"])
        ref = reference(kind, horn_id, row["name"], row["department"])

        def save(full, patch, previous):
            horn_service.update_horn(horn_id, patch, expected_department=ref.department, expected_values=previous)
            return "设备参数已保存并热同步"
        return ConfigurationResource(ref, HornParameters, configuration_values(row, HornParameters.model_fields), save)
    from .global_resources import resolve_global_resource
    return resolve_global_resource(catalog, parts)


def resolve_logistics(catalog, parts):
    kind = parts[0]
    if len(parts) != (2 if kind == "logistics" else 3):
        raise ValueError("物流资源标识无效")
    channel_id = catalog.positive_id(parts[1])
    channel = logistics_channel_service.get_channel(LOGISTICS_FEATURE, channel_id)
    if channel is None:
        raise HTTPException(404, "资源不可访问或不存在")
    catalog.require_department(channel["department"], LOGISTICS_FEATURE)
    ref = reference(kind, ":".join(parts[1:]), channel["name"], channel["department"], LOGISTICS_FEATURE)
    if kind == "logistics":
        raw = configuration_values(channel, ("name", "enabled", "sort_order", "config"))

        def save(full, patch, previous):
            values = LogisticsChannelPatchRequest.model_validate_json(json.dumps(patch))
            logistics_channel_service.update_channel_and_config(
                LOGISTICS_FEATURE, channel_id, values.model_dump(exclude_unset=True, exclude={"config"}),
                values.config, expected_values=previous,
            )
            return "通道参数已保存并发出热更新事件"
        return ConfigurationResource(ref, LogisticsChannelPatchRequest, raw, save)
    camera_id = catalog.positive_id(parts[2])
    member = next((row for row in channel["members"] if row["camera_id"] == camera_id), None)
    if member is None:
        raise HTTPException(404, "资源不可访问或不存在")
    camera = camera_config_manager.get_camera(camera_id)
    ref.name = channel["name"] + " · " + camera["name"]
    if kind == "logistics_roi":
        data = logistics_channel_service.get_camera_roi(LOGISTICS_FEATURE, channel_id, camera_id)

        def save(full, patch, previous):
            logistics_channel_service.update_camera_roi(LOGISTICS_FEATURE, channel_id, camera_id, full, expected_values=previous)
            return "摄像头 ROI 已保存并热更新"
        return ConfigurationResource(ref, LogisticsCameraRoiUpdate, configuration_values(data, ("roi_pos",)), save)

    def save(full, patch, previous):
        logistics_channel_service.set_member_enabled(LOGISTICS_FEATURE, channel_id, camera_id, full["enabled"],
                                                    expected_values=previous)
        return "成员参与状态已保存并热更新"
    return ConfigurationResource(ref, LogisticsChannelMemberEnabledUpdate, {"enabled": member["enabled"]}, save)


def resolve_guard(catalog, parts):
    kind = parts[0]
    if len(parts) != (2 if kind in {"guard", "guard_policy"} else 3):
        raise ValueError("保安室资源标识无效")
    site_id = catalog.positive_id(parts[1])
    site = GUARD_SERVICE.get_site(site_id)
    catalog.require_department(site["department"], "guard_behavior")
    ref = reference(kind, ":".join(parts[1:]), site["name"], site["department"], "guard_behavior")

    def refresh(camera_ids=()):
        if catalog.orchestrator is not None:
            catalog.orchestrator.refresh_guard_site(site_id, camera_ids)
            return "保安室配置已保存并刷新运行时"
        return "配置已保存，检测运行时尚未启动"

    if kind in {"guard", "guard_policy"}:
        schema = GuardBehaviorSiteUpdate if kind == "guard" else GuardBehaviorSitePolicyUpdate
        data = site if kind == "guard" else GUARD_SERVICE.get_policy(site_id)

        def save(full, patch, previous):
            method = GUARD_SERVICE.update_site if kind == "guard" else GUARD_SERVICE.update_policy
            method(site_id, patch, expected_values=previous)
            return refresh()
        return ConfigurationResource(ref, schema, configuration_values(data, schema.model_fields), save)
    identifier = catalog.positive_id(parts[2])
    if kind == "guard_alarm":
        data = next((row for row in GUARD_SERVICE.list_alarm_policies(site_id) if row["violation_type"] == identifier), None)
        if data is None:
            raise ValueError("保安室报警类型不存在")
        ref.name += " · " + VIOLATION_TYPE_META[identifier]["label"]

        def save(full, patch, previous):
            GUARD_SERVICE.update_alarm_policy(site_id, identifier, patch, expected_values=previous)
            return refresh()
        return ConfigurationResource(ref, GuardBehaviorAlarmPolicyUpdate,
                                     configuration_values(data, GuardBehaviorAlarmPolicyUpdate.model_fields), save)
    members = GUARD_SERVICE.list_site_cameras(site_id)
    member = next((row for row in members if row["camera_id"] == identifier), None)
    if member is None:
        raise HTTPException(404, "资源不可访问或不存在")
    ref.name += " · " + member["name"]
    if kind == "guard_roi":
        data = GUARD_SERVICE.get_camera_roi(site_id, identifier)

        def save(full, patch, previous):
            GUARD_SERVICE.update_camera_roi(site_id, identifier, full, expected_values=previous)
            return refresh((identifier,))
        return ConfigurationResource(ref, GuardBehaviorCameraRoiUpdate,
                                     configuration_values(data, GuardBehaviorCameraRoiUpdate.model_fields), save)

    def save(full, patch, previous):
        GUARD_SERVICE.set_camera_enabled(site_id, identifier, full["enabled"], expected_values=previous)
        return refresh((identifier,))
    return ConfigurationResource(ref, GuardBehaviorMemberEnabledUpdate, {"enabled": member["member_enabled"]}, save)
