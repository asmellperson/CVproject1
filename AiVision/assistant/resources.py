"""配置能力目录：复用业务 Schema 和保存服务，不向模型开放 SQL 或文件操作。"""
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Callable

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from pydantic_core import to_jsonable_python

from auth.feature_permissions import feature_departments
from AiVision.cameras.config_manager import camera_config_manager
from AiVision.core.config_revision import configuration_revision
from AiVision.departments.department_registry import DEPARTMENT_SPECS
from AiVision.features._shared.config_manager import feature_config_manager
from AiVision.features.registry import all_specs, get_spec
from .schema import ConfigurationResponse, ResourceReference


RESOURCE_KINDS = {
    "feature": "按摄像头分别保存的普通检测参数、启停、ROI 和报警设置，需指定 feature；参数名称不是资源名称",
    "camera": "平台摄像头的名称、采集帧率、重连次数和启停；删除使用 delete_camera",
    "logistics": "物流通道检测参数、检测时段、报警日历、通知和宽限时间",
    "logistics_roi": "物流通道成员的 ROI，需指定物流通道 parent_key",
    "logistics_member": "物流摄像头是否参与通道检测，需指定 parent_key",
    "guard": "保安室基本参数和启停",
    "guard_policy": "保安室人体、手机、趴睡和车辆检查规则，需指定保安室 parent_key",
    "guard_alarm": "保安室各类报警的冷却及通知，需指定 parent_key",
    "guard_roi": "保安室摄像头车辆 ROI，需指定 parent_key",
    "guard_member": "保安室成员参与状态，需指定 parent_key",
    "horn": "喇叭名称、启停和说明",
    "inspection_settings": "安检福达AI连接、生成、采样和队列设置，管理员全局配置",
    "assistant_settings": "福达AI助手的模型连接和生成设置，管理员全局配置",
    "exception_alerts": "系统异常企微开关、接收对象和重复通知间隔，管理员全局配置",
    "model_path": "本机模型权重路径，保存后异步加载，管理员全局配置",
    "department_features": "事业部允许访问的检测功能列表，管理员配置",
    "horn_sip": "平台 SIP 服务的启停、公告地址和端口，管理员全局配置",
}
FACTORY_DEPARTMENTS = {
    "一厂": ("general_electric", "research_institute"), "二厂": ("electronics_electrician",),
    "三厂": ("electrical_components",), "四厂": ("precious_metal_recycling",),
    "伟达四厂": ("precious_metal_recycling",),
}
PRIVATE_FIELDS = frozenset({"password", "password_hash", "username", "api_key", "secret", "token",
                            "url", "rtsp_url", "callback_url", "auth_version"})


def private_field(name: str) -> bool:
    return name.lower() in PRIVATE_FIELDS or name.lower().endswith(("_password", "_secret", "_token"))


def public_configuration(value):
    if isinstance(value, dict):
        return {key: public_configuration(item) for key, item in value.items() if not private_field(key)}
    if isinstance(value, list):
        return [public_configuration(item) for item in value]
    return value


def public_schema(value):
    if isinstance(value, list):
        return [public_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: public_schema(item) for key, item in value.items()}
    if "properties" in result:
        result["properties"] = {key: item for key, item in result["properties"].items() if not private_field(key)}
        if "required" in result:
            result["required"] = [key for key in result["required"] if key in result["properties"]]
    return result


def merge_configuration(current: dict, patch: dict, depth: int = 0) -> dict:
    if depth > 12:
        raise ValueError("配置嵌套层数过多")
    result = deepcopy(current)
    for key, value in patch.items():
        if private_field(key):
            raise ValueError("凭据和设备连接地址请通过原管理页面设置")
        result[key] = (merge_configuration(result.get(key, {}), value, depth + 1)
                       if isinstance(value, dict) and isinstance(result.get(key, {}), dict) else value)
    return result


def require_patch_fields(value, patch, prefix="") -> None:
    """防止宽松的旧业务 Schema 静默丢弃模型提交的未知字段。"""
    if isinstance(patch, dict):
        for key, item in patch.items():
            if not isinstance(value, dict) or key not in value:
                raise ValueError(f"未知配置字段：{prefix}{key}")
            require_patch_fields(value[key], item, f"{prefix}{key}.")
    elif isinstance(patch, list) and isinstance(value, list):
        for index, item in enumerate(patch):
            if index < len(value):
                require_patch_fields(value[index], item, f"{prefix}{index}.")


def selected_schema(name: str, source: type[BaseModel], fields) -> type[BaseModel]:
    return create_model(name, __config__=ConfigDict(extra="forbid", strict=True, allow_inf_nan=False),
                        **{key: (source.model_fields[key].annotation, deepcopy(source.model_fields[key])) for key in fields})


@dataclass
class ConfigurationResource:
    reference: ResourceReference
    schema: type[BaseModel]
    raw_config: dict
    save: Callable[[dict, dict, dict], str]

    @property
    def config(self) -> dict:
        return public_configuration(to_jsonable_python(self.raw_config))

    @property
    def revision(self) -> str:
        return configuration_revision(self.config)

    def response(self) -> ConfigurationResponse:
        return ConfigurationResponse(resource=self.reference, config=self.config, revision=self.revision,
                                     schema_definition=public_schema(self.schema.model_json_schema()))

    def prepare(self, patch: dict) -> dict:
        if not patch:
            raise ValueError("修改内容不能为空")
        merged = merge_configuration(self.raw_config, patch)
        # JSON 模式允许合法的日期/时刻字符串，其他取值沿用正式 Schema 的校验。
        value = self.schema.model_validate_json(json.dumps(to_jsonable_python(merged), allow_nan=False)).model_dump()
        require_patch_fields(to_jsonable_python(value), patch)
        return value


class CameraParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=100)
    fps: int = Field(gt=0)
    max_restart: int = Field(ge=0)
    enabled: bool

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("摄像头名称不能为空")
        return value


class ConfigurationCatalog:
    def __init__(self, user: dict, department: str | None, orchestrator=None):
        self.user, self.department, self.orchestrator = user, department, orchestrator
        self.departments = (list(DEPARTMENT_SPECS) if user.get("role") == "admin" else
                            [item for item in user.get("departments", []) if item in DEPARTMENT_SPECS])
        if department is not None:
            if department not in self.departments:
                raise HTTPException(403, "没有当前事业部的访问权限")
            self.departments = [department]

    def require_department(self, department: str | None, feature: str | None = None) -> None:
        if department not in self.departments or (feature and department not in feature_departments(self.user, feature)):
            raise HTTPException(404, "资源不可访问或不存在")

    def require_global(self) -> None:
        if self.user.get("role") != "admin" or self.department is not None:
            raise HTTPException(403, "全局配置需要管理员在全部可访问部门的会话中操作")

    def matching_departments(self, requested: str | None) -> list[str]:
        if requested is None:
            return self.departments
        values = FACTORY_DEPARTMENTS.get(requested) or tuple(
            key for key, spec in DEPARTMENT_SPECS.items() if requested in {key, spec.display_name}
        )
        if not values:
            raise ValueError("未知部门，请使用能力目录中的部门编码或名称")
        return [item for item in self.departments if item in values]

    def capabilities(self) -> dict:
        features = [spec for spec in all_specs().values() if set(feature_departments(self.user, spec.name)) & set(self.departments)]
        return {"can_modify": self.user.get("role") == "admin", "resource_kinds": RESOURCE_KINDS,
                "features": [{"name": spec.name, "label": spec.display_name} for spec in features],
                "departments": [{"id": item, "name": DEPARTMENT_SPECS[item].display_name} for item in self.departments],
                "factory_names": {key: [item for item in values if item in self.departments]
                                  for key, values in FACTORY_DEPARTMENTS.items() if set(values) & set(self.departments)}}

    def find(self, *, kind: str, department: str | None = None, feature: str | None = None,
             query: str = "", parent_key: str | None = None, offset: int = 0, limit: int = 25) -> dict:
        departments = self.matching_departments(department)
        spec = get_spec(feature or "") if kind == "feature" else None
        if kind in {"feature", "camera"}:
            if kind == "feature" and spec is None:
                raise ValueError("查询功能配置需要提供能力目录中的 feature 标识")
            refs = []
            for scope in departments:
                if kind == "feature" and scope not in feature_departments(self.user, feature):
                    continue
                for camera in camera_config_manager.list_cameras(scope):
                    if kind == "feature" and feature in {"guard_behavior", "detect_logistics_single_person"}:
                        continue
                    refs.append(ResourceReference(
                        key=f"feature:{feature}:{camera['camera_id']}" if kind == "feature" else f"camera:{camera['camera_id']}",
                        kind=kind, name=camera["name"], department=scope, feature=feature if kind == "feature" else None,
                        identifier=camera["shm_name"], target_name=camera["name"],
                    ))
        else:
            from .native_resources import find_native_resources
            refs = find_native_resources(self, kind, departments, parent_key)
        needle = query.casefold().strip()
        matches = []
        for ref in refs:
            department_spec = DEPARTMENT_SPECS.get(ref.department)
            department_name = department_spec.display_name if department_spec else ""
            searchable = " ".join((ref.name, ref.key, ref.identifier or "", department_name + ref.name))
            if not needle or needle in searchable.casefold():
                matches.append(ref)
        refs = matches
        result = {"items": [ref.model_dump() for ref in refs[offset:offset + limit]], "total": len(refs),
                  "next_offset": offset + limit if offset + limit < len(refs) else None}
        if (spec is not None and feature not in {"guard_behavior", "detect_logistics_single_person"}
                and set(departments) & set(feature_departments(self.user, feature))):
            # 字段属于功能 Schema，摄像头名称搜索为空不能说明参数不存在。
            result["configuration_scope"] = "camera"
            result["schema_definition"] = public_schema(spec.config_schema.model_json_schema())
            if needle and not refs:
                result["search_hint"] = (
                    "query 仅匹配摄像头名称或标识，不匹配参数名；请从 schema_definition 识别字段。"
                    "用户未指定摄像头时，保留 department 和 feature，将 query 留空重新查询。"
                    "用户明确指定了摄像头但没有匹配时，应核对名称，不能擅自选择其他目标。"
                )
        return result

    def resolve(self, key: str) -> ConfigurationResource:
        parts = key.split(":")
        if parts[0] == "feature" and len(parts) == 3:
            spec = get_spec(parts[1])
            if spec is None or spec.name in {"guard_behavior", "detect_logistics_single_person"}:
                raise ValueError("该功能请使用专用业务配置类别")
            data = feature_config_manager.get_config(spec, self.positive_id(parts[2]))
            if data is None:
                raise HTTPException(404, "资源不可访问或不存在")
            camera = camera_config_manager.get_camera(data["camera"]["shm_name"])
            self.require_department(camera["department"], spec.name)
            ref = ResourceReference(key=key, kind="feature", name=camera["name"] + " · " + spec.display_name,
                                    department=camera["department"], feature=spec.name,
                                    identifier=camera["shm_name"], target_name=camera["name"])

            def save(full, patch, previous):
                feature_config_manager.save_config(spec, camera["shm_name"], full,
                                                   expected_department=ref.department, expected_values=previous)
                return "配置已保存并发出热更新事件"
            return ConfigurationResource(ref, spec.config_schema, data["config"], save)
        if parts[0] == "camera" and len(parts) == 2:
            camera = camera_config_manager.get_camera(self.positive_id(parts[1]))
            if camera is None:
                raise HTTPException(404, "资源不可访问或不存在")
            self.require_department(camera["department"])
            ref = ResourceReference(key=key, kind="camera", name=camera["name"], department=camera["department"],
                                    identifier=camera["shm_name"], target_name=camera["name"])
            raw = {field: camera[field] for field in CameraParameters.model_fields}

            def save(full, patch, previous):
                camera_config_manager.update_camera(camera["shm_name"], patch, expected_values=previous,
                                                    expected_department=ref.department)
                return "摄像头配置已保存并发出热更新事件"
            return ConfigurationResource(ref, CameraParameters, raw, save)
        from .native_resources import resolve_native_resource
        return resolve_native_resource(self, parts)

    @staticmethod
    def positive_id(value: str) -> int:
        if not value.isascii() or not value.isdecimal() or int(value) <= 0:
            raise ValueError("资源标识无效")
        return int(value)
