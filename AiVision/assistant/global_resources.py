"""系统级配置适配：权限、版本和运行时行为与原管理入口一致。"""
from pydantic import Field, field_validator
from fastapi import HTTPException

from AiVision.alarms.devices.schema import SipServerConfig
from AiVision.alarms.devices.sip_service import horn_sip_service
from AiVision.core.config_revision import require_configuration_values
from AiVision.core.system_config import system_config_service
from AiVision.departments.service import department_service
from AiVision.features.registry import all_specs
from AiVision.features.security_inspection.schema import VlmSettings
from AiVision.features.security_inspection.service import InspectionService
from AiVision.inference.runtime_manager import inference_runtime_manager
from .resources import ConfigurationResource
from .schema import AssistantSettings, ResourceReference, StrictModel


LABELS = {"inspection_settings": "安检模型设置", "assistant_settings": "福达AI助手模型设置",
          "exception_alerts": "系统异常通知", "horn_sip": "平台 SIP 服务"}


class ExceptionParameters(StrictModel):
    wechat_enable: bool
    wechat_user: str
    repeat_interval_minutes: int = Field(ge=20, le=1440)


class ModelPathParameters(StrictModel):
    path: str = Field(min_length=1, max_length=4096)


class DepartmentParameters(StrictModel):
    features: list[str]

    @field_validator("features")
    @classmethod
    def registered_features(cls, value):
        if len(value) != len(set(value)) or set(value) - all_specs().keys():
            raise ValueError("功能列表包含重复或未注册的功能")
        return value


def find_global_resources(catalog, kind, departments):
    if kind == "department_features":
        if catalog.user.get("role") != "admin":
            raise HTTPException(403, "功能分配需要管理员权限")
        return [ResourceReference(key=f"{kind}:{item}", kind=kind, name=item + " · 功能分配", department=item)
                for item in departments]
    catalog.require_global()
    if kind == "model_path":
        return [ResourceReference(key=f"{kind}:{row['name']}", kind=kind, name=row["name"], department=None)
                for row in inference_runtime_manager.list_models()]
    if kind not in LABELS:
        raise ValueError("未知配置类别")
    return [ResourceReference(key=kind, kind=kind, name=LABELS[kind], department=None)]


def resolve_global_resource(catalog, parts):
    kind = parts[0]
    if kind == "department_features" and len(parts) == 2:
        if catalog.user.get("role") != "admin":
            raise HTTPException(403, "功能分配需要管理员权限")
        catalog.require_department(parts[1])
        row = next(item for item in department_service.assignments() if item.department == parts[1])
        ref = ResourceReference(key=":".join(parts), kind=kind, name=parts[1] + " · 功能分配", department=parts[1])

        def save(full, patch, previous):
            assignments = department_service.assignments()
            target = next(item for item in assignments if item.department == parts[1])
            require_configuration_values({"features": target.features}, previous)
            target.features = full["features"]
            department_service.save_feature_settings(assignments)
            return "事业部功能分配已保存，后续请求使用新权限"
        return ConfigurationResource(ref, DepartmentParameters, {"features": row.features}, save)
    catalog.require_global()
    if kind == "model_path" and len(parts) == 2:
        row = next((item for item in inference_runtime_manager.list_models() if item["name"] == parts[1]), None)
        if row is None:
            raise ValueError("未知模型")
        ref = ResourceReference(key=":".join(parts), kind=kind, name=row["name"], department=None)

        def save(full, patch, previous):
            result = inference_runtime_manager.update_model_path(parts[1], full["path"], expected_values=previous)
            return "模型路径已保存，正在异步加载" if result["load_status"] == "loading" else "模型路径已保存，推理运行时未启动"
        return ConfigurationResource(ref, ModelPathParameters, {"path": row["path"]}, save)
    if len(parts) != 1 or kind not in LABELS:
        raise ValueError("未知配置资源")
    ref = ResourceReference(key=kind, kind=kind, name=LABELS[kind], department=None)
    if kind == "inspection_settings":
        service = InspectionService()

        def save(full, patch, previous):
            value = VlmSettings.model_validate(full)
            service.save_settings(value, expected_values=previous)
            consumer = catalog.orchestrator.consumers.get("security_inspection") if catalog.orchestrator else None
            if consumer is not None:
                consumer.vlm_runtime.configure(value)
            return "安检模型设置已保存" + ("并重配运行时" if consumer else "，安检运行时未启动")
        return ConfigurationResource(ref, VlmSettings, service.get_settings().model_dump(), save)
    if kind == "assistant_settings":
        from .service import assistant_service

        def save(full, patch, previous):
            assistant_service.save_settings(AssistantSettings.model_validate(full), expected_values=previous)
            return "助手模型设置已保存，对后续任务生效"
        return ConfigurationResource(ref, AssistantSettings, assistant_service.settings().model_dump(), save)
    if kind == "exception_alerts":
        def save(full, patch, previous):
            system_config_service.save_exception_alert(full, expected_values=previous)
            return "系统异常通知参数已保存"
        return ConfigurationResource(ref, ExceptionParameters, system_config_service.get_exception_alert(), save)

    def save(full, patch, previous):
        horn_sip_service.save(SipServerConfig.model_validate(full), expected_values=previous)
        return "SIP 服务配置已保存并应用"
    return ConfigurationResource(ref, SipServerConfig, horn_sip_service.config().model_dump(), save)
