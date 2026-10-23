"""有限业务工具：模型负责理解意图，服务负责权限、校验、事务和审计。"""
import json

from fastapi import HTTPException
from pydantic import Field, ValidationError
from pydantic_core import to_jsonable_python

from AiVision.cameras.config_manager import camera_config_manager
from AiVision.core.config_revision import ConfigurationConflict
from AiVision.core.settings import settings
from AiVision.features.registry import get_spec
from .native_resources import GUARD_SERVICE, LOGISTICS_FEATURE, logistics_channel_service
from .resources import ConfigurationCatalog, public_configuration
from .schema import ConfigurationChange, ResourceReference, StrictModel
from .secrets import DEFAULT_RTSP_PATH, DEFAULT_RTSP_PORT
from .service import assistant_service


class EmptyArguments(StrictModel):
    pass


class ListArguments(StrictModel):
    kind: str = Field(description="能力目录中的资源类别；普通检测参数使用 feature，摄像头基础信息使用 camera")
    department: str | None = Field(default=None, description="能力目录中的部门编码或完整名称，部门条件单独填写，不放入 query")
    feature: str | None = Field(default=None, description="kind=feature 时填写能力目录中的功能标识，例如 tailgating；不是参数名")
    query: str = Field(default="", description="仅筛选资源名称或标识；参数名、配置值和功能名称不放在这里。用户未指定摄像头名称或标识时留空")
    parent_key: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=50)


class ReadArguments(StrictModel):
    resource_keys: list[str] = Field(min_length=1, max_length=5)


class UpdateArguments(StrictModel):
    changes: list[ConfigurationChange] = Field(min_length=1, max_length=10)


class UndoArguments(StrictModel):
    action_id: str


class AddCameraArguments(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    department: str
    source_id: str = Field(description="用户消息中受保护的摄像头源或凭据引用，不得编造")
    host: str | None = Field(default=None, description="仅账号密码模式需要，必须来自用户提供的 IP")
    port: int = Field(default=DEFAULT_RTSP_PORT, ge=1, le=65535)
    path: str = DEFAULT_RTSP_PATH
    fps: int = Field(default=5, gt=0, le=120)
    feature: str | None = Field(default=None, description="普通检测功能标识；不指定则只在平台建档")
    channel_key: str | None = Field(default=None, description="物流通道资源 key，与 feature 互斥")


class BindCameraArguments(StrictModel):
    camera_key: str
    parent_key: str = Field(description="已读取的物流通道或保安室 key")


class DeleteCameraArguments(StrictModel):
    camera_key: str = Field(pattern=r"^camera:[1-9][0-9]*$")
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class AskUserArguments(StrictModel):
    question: str = Field(min_length=1, max_length=1000)


TOOL_MODELS = {
    "capabilities": (EmptyArguments, "查询可操作类别、功能、部门及一厂二厂别名"),
    "list_resources": (ListArguments, "按部门和功能搜索真实资源；普通检测同时返回配置作用范围和脱敏 Schema，参数名不作为资源名称搜索；支持分页"),
    "read_configurations": (ReadArguments, "读取当前值、版本及严格字段 Schema，修改前必须读取"),
    "update_configurations": (UpdateArguments, "按已读取版本局部修改，保留其他字段；每项独立事务，结果逐项报告"),
    "undo_configuration": (UndoArguments, "撤销当前会话的一次已成功参数修改；被别人改过则拒绝覆盖，不撤销创建、绑定或删除"),
    "add_camera": (AddCameraArguments, "新建摄像头，自动生成 camera_数字；凭据引用仅有效30分钟，普通功能或物流通道可同事务启用"),
    "bind_camera": (BindCameraArguments, "把平台已有摄像头加入同部门物流通道或保安室；保安室可先新建再绑定"),
    "delete_camera": (DeleteCameraArguments, "仅在用户明确删除摄像头时使用；先读取并提供版本，删除摄像头及其检测配置，不可撤销"),
    "ask_user": (AskUserArguments, "目标有歧义、缺少参数或需要用户选择时询问；不会执行配置操作，不能当作操作完成报告"),
}


def configuration_diff(before: dict, after: dict) -> dict:
    result = {}
    for key, value in after.items():
        if key not in before or before[key] != value:
            result[key] = configuration_diff(before.get(key, {}), value) if isinstance(value, dict) and isinstance(before.get(key), dict) else value
    return result


def tool_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return json.dumps(exc.errors(include_input=False, include_context=False, include_url=False), ensure_ascii=False)
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    if isinstance(exc, (ValueError, KeyError, ConfigurationConflict)):
        return str(exc)
    # 数据库及网络异常的字符串可能含连接凭据，不进入模型、日志和聊天记录。
    return f"业务服务暂时无法完成操作（{type(exc).__name__}），请核对实际状态"


class AssistantTools:
    def __init__(self, *, turn_id, session_id, department, load_user, sources, orchestrator, check_cancel):
        self.turn_id, self.session_id, self.department = turn_id, session_id, department
        self.load_user, self.sources, self.orchestrator, self.check_cancel = load_user, sources, orchestrator, check_cancel
        self.read_versions = {}
        self.change_count = 0
        self.target_policy = None
        self.change_policy = None
        self.task_index = 1

    def begin_task(self, task_index=1):
        # 专家交接不能复用上一子任务的写入版本；整轮变更计数和审计保持共享。
        self.check_cancel()
        self.read_versions.clear()
        self.task_index = task_index

    def catalog(self, *, write=False):
        self.check_cancel()
        user = self.load_user()
        if write and user.get("role") != "admin":
            raise HTTPException(403, "当前账号只能查询，配置修改需要管理员权限")
        return ConfigurationCatalog(user, self.department, self.orchestrator)

    def run(self, name: str, arguments: dict) -> dict:
        if name not in TOOL_MODELS:
            raise ValueError("未知工具，请按工具目录选择")
        args = TOOL_MODELS[name][0].model_validate_json(json.dumps(arguments))
        catalog = self.catalog()
        if self.target_policy is not None:
            self.target_policy.check(name, args)
        if name == "capabilities":
            return catalog.capabilities()
        if name == "ask_user":
            return {"question": args.question}
        if name == "list_resources":
            result = catalog.find(**args.model_dump())
            if self.target_policy is not None:
                self.target_policy.observe(name, result)
            if self.change_policy is not None:
                self.change_policy.observe(name, result, args.model_dump())
            return result
        if name == "read_configurations":
            resources = [catalog.resolve(key) for key in args.resource_keys]
            for resource in resources:
                self.read_versions[resource.reference.key] = resource.revision
            result = {"items": [resource.response().model_dump(mode="json") for resource in resources]}
            if self.target_policy is not None:
                self.target_policy.observe(name, result)
            if self.change_policy is not None:
                self.change_policy.observe(name, result, args.model_dump())
            return result
        if name == "update_configurations":
            return self.update(args.changes)
        if name == "undo_configuration":
            previous = assistant_service.action(args.action_id, self.session_id, self.load_user())
            if previous.status != "saved" or previous.after is None or previous.resource.kind in {"camera_creation", "camera_binding", "camera_deletion"}:
                raise ValueError("此记录不是可撤销的已保存参数修改")
            resource = self.catalog(write=True).resolve(previous.resource.key)
            if self.target_policy is not None:
                self.target_policy.check_audited_resource(resource.reference.model_dump())
            if resource.config != previous.after:
                raise ConfigurationConflict("配置在该操作之后已经变化，不能覆盖，请读取后明确指定新值")
            self.read_versions[resource.reference.key] = resource.revision
            return self.update([ConfigurationChange(resource_key=resource.reference.key, expected_revision=resource.revision,
                                                    patch=configuration_diff(previous.after, previous.before))])
        if name == "add_camera":
            return self.add_camera(args)
        if name == "delete_camera":
            return self.delete_camera(args)
        return self.bind_camera(args)

    def count_changes(self, count):
        if self.change_count + count > settings.runtime.assistant_max_changes:
            raise ValueError("本次配置操作数量达到上限，请分次发起")
        self.change_count += count

    def update(self, changes):
        self.count_changes(len(changes))
        if len({change.resource_key for change in changes}) != len(changes):
            raise ValueError("一批修改中同一资源只能出现一次")
        prepared = []
        for change in changes:
            resource = self.catalog(write=True).resolve(change.resource_key)
            if self.read_versions.get(change.resource_key) != change.expected_revision or resource.revision != change.expected_revision:
                raise ConfigurationConflict("必须先读取当前配置，且读取后的版本不能发生变化")
            resource.prepare(change.patch)
            if self.change_policy is not None:
                self.change_policy.check_patch(resource, change.patch)
            prepared.append((change, resource))
        if self.change_policy is not None:
            self.change_policy.check_targets(changes)
        results = []
        for change, previous in prepared:
            resource = self.catalog(write=True).resolve(change.resource_key)
            if resource.revision != previous.revision:
                results.append({"resource_key": change.resource_key, "error": "配置已变化，本项未执行"})
                continue
            # 脱敏字段不参与公开版本号，必须基于事务前最新完整值重新合并，保留刚更新的凭据。
            full = resource.prepare(change.patch)
            desired = public_configuration(to_jsonable_python(full))
            delta = configuration_diff(resource.config, desired)
            if not delta:
                results.append({"resource_key": change.resource_key, "resource_name": resource.reference.name,
                                "status": "unchanged", "detail": "配置已是目标值"})
                continue
            action, execute = assistant_service.begin_action(self.turn_id, resource.reference, resource.config, delta)
            if not execute:
                results.append(action.model_dump(mode="json"))
                continue
            try:
                self.catalog(write=True)
                detail = resource.save(full, change.patch, resource.raw_config)
                actual = ConfigurationCatalog(self.load_user(), self.department, self.orchestrator).resolve(change.resource_key).config
                status = "saved" if actual == desired else "changed"
                if status != "saved":
                    detail += "；保存后的配置已有变化，请核对实际值"
            except Exception as exc:
                detail, actual, status = tool_error(exc), None, "failed"
                try:
                    actual = ConfigurationCatalog(self.load_user(), self.department, self.orchestrator).resolve(change.resource_key).config
                    if actual == desired:
                        status, detail = "saved", "配置已保存，运行时刷新未确认：" + detail
                except Exception as read_error:
                    detail += "；结果核对失败：" + tool_error(read_error)
                    status = "unknown"
            action = assistant_service.finish_action(action.id, status, actual, detail)
            results.append(action.model_dump(mode="json"))
        return {"results": results}

    def add_camera(self, args):
        catalog = self.catalog(write=True)
        departments = catalog.matching_departments(args.department)
        if len(departments) != 1:
            raise ValueError("新增摄像头必须指定唯一事业部；一厂请明确通用电气或新材院")
        department = departments[0]
        catalog.require_department(department, args.feature)
        if args.feature and (get_spec(args.feature) is None or args.feature in {"guard_behavior", LOGISTICS_FEATURE}):
            raise ValueError("普通功能请使用已注册标识；保安室先建档再绑定，物流请指定 channel_key")
        if args.channel_key and args.feature:
            raise ValueError("feature 和 channel_key 不能同时指定")
        channel = catalog.resolve(args.channel_key) if args.channel_key else None
        if channel and (channel.reference.kind != "logistics" or channel.reference.department != department):
            raise ValueError("目标必须是同部门物流通道")
        source = self.sources.get(self.session_id, args.source_id)
        url = source.resolve(args.host, args.port, args.path)
        if len(url) > 500:
            raise ValueError("RTSP 地址过长，请控制在500字符以内")
        self.count_changes(1)
        ref = ResourceReference(key="create_camera:" + args.source_id, kind="camera_creation", name=args.name,
                                department=department, feature=args.feature or (LOGISTICS_FEATURE if channel else None))
        proposed = {"name": args.name, "department": department, "fps": args.fps,
                    "feature": args.feature, "channel_key": args.channel_key}
        action, execute = assistant_service.begin_action(self.turn_id, ref, {}, proposed)
        if not execute:
            return action.model_dump(mode="json")
        try:
            self.catalog(write=True).require_department(department, ref.feature)
            payload = {"name": args.name, "url": url, "department": department, "fps": args.fps}
            if channel:
                channel_id = catalog.positive_id(args.channel_key.split(":")[1])
                logistics_channel_service.create_camera_and_bind(LOGISTICS_FEATURE, channel_id,
                                                                {"name": args.name, "url": url, "fps": args.fps})
                camera = camera_config_manager.get_camera(args.name)
            elif args.feature:
                camera = camera_config_manager.create_camera_for_feature(args.feature, payload)
            else:
                camera = camera_config_manager.create_camera(payload)
            after = {**public_configuration(camera), "resource_key": f"camera:{camera['camera_id']}",
                     "feature": args.feature, "channel_key": args.channel_key}
            return assistant_service.finish_action(action.id, "saved", after,
                "摄像头已建档并发出热更新事件；连接状态请查看监控画面，尚未配置 ROI 的检测需继续配置").model_dump(mode="json")
        except Exception as exc:
            # 创建的提交结果可能已经成功，禁止模型凭异常直接再次创建。
            detail = f"创建未完成结果确认（{type(exc).__name__}），请查询摄像头列表核对，禁止直接重试"
            return assistant_service.finish_action(action.id, "unknown", None, detail).model_dump(mode="json")

    def delete_camera(self, args):
        catalog = self.catalog(write=True)
        if self.read_versions.get(args.camera_key) != args.expected_revision:
            raise ConfigurationConflict("删除前必须先读取当前摄像头配置")
        action_key = "delete:" + args.camera_key
        previous = assistant_service.find_action(self.turn_id, action_key)
        if previous is not None:
            catalog.require_department(previous.resource.department)
            return previous.model_dump(mode="json")
        resource = catalog.resolve(args.camera_key)
        if resource.revision != args.expected_revision:
            raise ConfigurationConflict("摄像头配置已变化，删除前请重新读取")
        self.count_changes(1)
        ref = resource.reference.model_copy(update={"key": action_key, "kind": "camera_deletion"})
        action, execute = assistant_service.begin_action(self.turn_id, ref,
            {**resource.config, "state": "存在"}, {"state": "已删除"})
        if not execute:
            return action.model_dump(mode="json")
        camera_id = int(args.camera_key.split(":")[1])
        actual, status = None, "failed"
        try:
            self.catalog(write=True).require_department(ref.department)
            deleted = camera_config_manager.delete_camera(camera_id, expected_values=resource.raw_config,
                                                         expected_department=ref.department)
            if not deleted:
                raise ConfigurationConflict("摄像头已被其他操作删除，本次未执行删除")
            if camera_config_manager.get_camera(camera_id) is not None:
                raise ConfigurationConflict("删除后核对失败：摄像头仍然存在，不能报告删除成功")
            actual, status, detail = {"state": "已删除"}, "saved", "摄像头及其检测配置已删除，并发出热更新事件；此操作不可撤销"
        except Exception as exc:
            detail = tool_error(exc)
            try:
                # 提交后通知失败也可能已经删除，回读实际状态，避免重复执行。
                catalog = ConfigurationCatalog(self.load_user(), self.department, self.orchestrator)
                camera = camera_config_manager.get_camera(camera_id)
                if camera is None:
                    actual = {"state": "已删除"}
                    if not isinstance(exc, (ValueError, HTTPException)):
                        status, detail = "saved", "摄像头已删除，运行时刷新未确认：" + detail
                else:
                    catalog.require_department(camera["department"])
                    actual = {**public_configuration(camera), "state": "存在"}
            except Exception as read_error:
                status = "unknown"
                detail += "；结果核对失败：" + tool_error(read_error)
        return assistant_service.finish_action(action.id, status, actual, detail).model_dump(mode="json")

    def bind_camera(self, args):
        catalog = self.catalog(write=True)
        camera, parent = catalog.resolve(args.camera_key), catalog.resolve(args.parent_key)
        if camera.reference.kind != "camera" or parent.reference.kind not in {"logistics", "guard"}:
            raise ValueError("请使用真实摄像头及物流通道或保安室资源")
        if camera.reference.department != parent.reference.department:
            raise ValueError("摄像头与目标必须属于同一部门")
        if parent.reference.key not in self.read_versions or camera.reference.key not in self.read_versions:
            raise ValueError("绑定前请读取摄像头及目标配置")
        self.count_changes(1)
        ref = ResourceReference(key=f"bind:{args.parent_key}:{args.camera_key}", kind="camera_binding",
                                name=parent.reference.name + " · " + camera.reference.name,
                                department=parent.reference.department, feature=parent.reference.feature)
        action, execute = assistant_service.begin_action(self.turn_id, ref, {"bound": False}, {"bound": True})
        if not execute:
            return action.model_dump(mode="json")
        try:
            self.catalog(write=True).require_department(ref.department, ref.feature)
            parent_id, camera_id = int(args.parent_key.split(":")[1]), int(args.camera_key.split(":")[1])
            if parent.reference.kind == "logistics":
                logistics_channel_service.add_existing_camera(LOGISTICS_FEATURE, parent_id, camera_id)
            else:
                GUARD_SERVICE.add_camera(parent_id, camera_id)
                if self.orchestrator:
                    self.orchestrator.refresh_guard_site(parent_id, (camera_id,))
            return assistant_service.finish_action(action.id, "saved", {"bound": True}, "成员已绑定并请求刷新检测运行时").model_dump(mode="json")
        except Exception as exc:
            return assistant_service.finish_action(action.id, "unknown", None,
                "绑定结果需核对：" + tool_error(exc)).model_dump(mode="json")
