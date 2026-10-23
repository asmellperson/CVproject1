"""诊断隔离层：真实助手、Schema、事务和审计只能访问本次创建的 SQLite。"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from concurrent.futures import Future
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from .cases import CAMERA_NAME, DEPARTMENT, FEATURE, RESOURCE, SECOND_CAMERA_NAME, SECOND_RESOURCE


def completion(content, reason="stop"):
    return json.dumps({"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)},
                                   "finish_reason": reason}]}, ensure_ascii=False)


def json_validity(raw):
    """没有响应或没有正文时不评价 JSON；截断类别与正文语法分别统计。"""
    from AiVision.assistant.responses import json_content

    try:
        envelope = json.loads(raw)
        content = envelope["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            return None
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    content = content.strip()
    if content.startswith("<think>") and "</think>" in content:
        content = content.partition("</think>")[2].strip()
    def reject_nonfinite(_value):
        raise ValueError("JSON 不允许非有限数字")

    try:
        json.loads(json_content(content), parse_constant=reject_nonfinite)
        return True
    except ValueError:
        return False


def response_statistics(raw):
    """格式诊断只保留白名单类别和长度，空思考标签不能等同于实际思考。"""
    from AiVision.assistant.responses import completion_metadata, json_content

    result = completion_metadata(raw)
    try:
        message = json.loads(raw)["choices"][0]["message"]
        content = message.get("content")
        if not isinstance(content, str):
            return result
        body = content.strip()
        result["reasoning_characters"] = sum(len(message[key]) for key in ("reasoning", "reasoning_content")
                                             if isinstance(message.get(key), str))
        result["thinking_wrapper"] = "absent"
        result["thinking_characters"] = 0
        if body.startswith("<think>"):
            thinking, separator, body = body[len("<think>"):].partition("</think>")
            result["thinking_wrapper"] = "closed" if separator else "unclosed"
            result["thinking_characters"] = len(thinking.strip())
            if not separator:
                result["answer_format"] = "unclosed_thinking"
                return result
            body = body.strip()
        candidate = json_content(body)
        result["code_fenced"] = candidate != body
        result["answer_characters"] = len(candidate)
        if not candidate:
            result["answer_format"] = "empty"
        elif json_validity(completion(candidate)):
            value = json.loads(candidate)
            result["answer_format"] = ("object" if isinstance(value, dict) else "array" if isinstance(value, list)
                                       else "scalar")
            if isinstance(value, dict):
                result["object_shape"] = "request_plan" if "mode" in value else "agent_decision" if "action" in value else "other"
        else:
            result["answer_format"] = "invalid_json" if candidate.startswith(("{", "[", '"', "```")) else "text"
        return result
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return {"envelope_valid": False}


def observed_arguments(trace, tool, field, item_type):
    """模型可能提交错误类型，统计器也必须容纳被工具拒绝的输入。"""
    values = []
    for entry in trace:
        if entry["tool"] != tool:
            continue
        items = entry["arguments"].get(field)
        if isinstance(items, list):
            values.extend(item for item in items if isinstance(item, item_type))
    return values


def context_statistics(messages):
    from AiVision.assistant.context import CONTEXT_PREFIX

    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str) and content.startswith(CONTEXT_PREFIX):
            data = json.loads(content[len(CONTEXT_PREFIX):])
            return len(data["recent_turns"]), content
    return max(0, (len(messages) - 2) // 2), "\n".join(str(item.get("content", "")) for item in messages[1:-1])


def target_literal_role(value):
    """只输出固定虚构词的类别，未知名称、引用和标识不进入报告。"""
    from AiVision.assistant.targets import CONTEXT_REFERENCE, reference_scope

    department, literal = reference_scope(value)
    if department is not None:
        if not literal:
            return "department_scope"
        if CONTEXT_REFERENCE.fullmatch(literal):
            return "qualified_context"
        if literal in {CAMERA_NAME, SECOND_CAMERA_NAME}:
            return "qualified_fixture_target"
    groups = {
        "fixture_alias": {"记忆代号甲", "记忆代号乙"},
        "fixture_target": {CAMERA_NAME, SECOND_CAMERA_NAME, RESOURCE, SECOND_RESOURCE,
                           "camera:101", "camera:102", "camera_101", "camera_102"},
        "context_reference": {"这台摄像头", "刚才那台摄像头", "它", "它们", "两台", "这个阈值"},
    }
    return next((role for role, values in groups.items() if value in values), "other")


def planning_target_evidence(plan, question):
    from AiVision.assistant.targets import valid_proposal

    context = plan.target_context
    return {"present": context is not None,
            "references": [{"kind": item.kind, "role": target_literal_role(item.text),
                            "literal_in_message": item.text in question}
                           for item in context.references] if context else [],
            "bindings": [{"alias_role": target_literal_role(item.alias), "target_role": target_literal_role(item.target),
                          "evidence_in_message": item.evidence in question, "positive_relation": valid_proposal(item, question)}
                         for item in context.bindings] if context else []}


def tool_target_evidence(policy, name, arguments, *, expected_keys=()):
    """保留实际检查边界的匹配数量与来源，不导出用户原话、资源 key 或配置。"""
    from AiVision.assistant.targets import resource_identity

    selectors, permitted = [], set()
    for kind, value in policy.selectors:
        matches = policy.matching_resources(kind, value)
        selectors.append({"kind": kind, "role": target_literal_role(value) if kind == "name" else "identity",
                          "matched_identities": len({resource_identity(resource) for resource in matches})})
        permitted.update(resource["key"] for resource in matches)
    requested = []
    if name == "read_configurations" and isinstance(arguments.get("resource_keys"), list):
        requested = arguments["resource_keys"]
    elif name == "update_configurations" and isinstance(arguments.get("changes"), list):
        requested = [change.get("resource_key") for change in arguments["changes"] if isinstance(change, dict)]
    keys = []
    for key in requested:
        if not isinstance(key, str):
            keys.append({"valid_type": False})
            continue
        prefix = key.split(":", 1)[0]
        keys.append({"valid_type": True, "kind": prefix if prefix in {"camera", "feature"} else "other",
                     "fixture_key": key in {RESOURCE, SECOND_RESOURCE, "camera:101", "camera:102"},
                     "expected_target": key in expected_keys if expected_keys else None,
                     "discovered": key in policy.candidates, "searched_this_turn": key in policy.searched,
                     "matches_selector": key in permitted if selectors else None})
    return {"tool": name, "needs_clarification": policy.needs_clarification,
            "department_scope_count": len(policy.reference_departments),
            "candidate_count": len(policy.candidates), "searched_count": len(policy.searched),
            "candidate_kinds": sorted({item["kind"] if item.get("kind") in {"camera", "feature"} else "other"
                                       for item in policy.candidates.values()}),
            "selectors": selectors, "requested_resources": keys}


class InlineExecutor:
    """同步投递保留 submit/幂等/取消链路；不把线程调度性能算作本次诊断结论。"""

    def submit(self, function, *args):
        result = Future()
        try:
            result.set_result(function(*args))
        except BaseException as exc:
            result.set_exception(exc)
            raise
        return result

    def shutdown(self, **_kwargs):
        return None


class ScriptedClient:
    """固定模型替身，用于验证调度与工具边界，不用于计算真实模型能力。"""

    def __init__(self, platform):
        self.platform = platform
        self.corrected_search = False

    def complete(self, **kwargs):
        platform, case = self.platform, self.platform.scenario
        messages = kwargs["messages"]
        planning = "只判断当前用户请求" in messages[0]["content"]
        if planning:
            mode = "query" if platform.phase == "prelude" else case.mode
            question = case.prelude if platform.phase == "prelude" else case.continuation if platform.phase == "continuation" else case.question
            references = [{"kind": "named", "text": title} for title in (CAMERA_NAME, SECOND_CAMERA_NAME) if title in question]
            if not references and "这个阈值" in question:
                references = [{"kind": "context", "text": "这个阈值"}]
            goal = ("capabilities" if case.name == "capabilities" else "list_resources" if case.name == "camera"
                    else "read_configurations") if mode == "query" else None
            return completion({"target_context": {"references": references}, "mode": mode, "operations": ["update_configurations"] if mode == "change" else [],
                               "query_tool": goal}), 0.0
        if not kwargs["json_mode"]:
            return completion("你好呀，我是福达AI助手。"), 0.0
        last = messages[-1]["content"]
        if last.startswith("后台已查询"):
            if case.name == "capabilities":
                return self.tool("capabilities", {})
            query = CAMERA_NAME
            if case.name == "ambiguous" or (case.name == "continuation" and platform.phase == "main"):
                query = "诊断闸机"
            if case.name == "partial_batch":
                query = "诊断闸机"
            if case.name == "recovered_tool_error" and not self.corrected_search:
                return self.tool("list_resources", {"kind": "feature", "department": DEPARTMENT})
            arguments = {"kind": "camera" if case.name == "camera" else "feature", "department": DEPARTMENT, "query": query}
            if case.name != "camera":
                arguments["feature"] = FEATURE
            return self.tool("list_resources", arguments)
        if not last.startswith("工具执行结果"):
            return self.answer()
        data = json.loads(last.split("：", 1)[1])
        if "error" in data:
            if case.name == "recovered_tool_error" and not self.corrected_search:
                self.corrected_search = True
                return self.tool("list_resources", {"kind": "feature", "department": DEPARTMENT,
                                                    "feature": FEATURE, "query": CAMERA_NAME})
            return self.answer()
        if "items" in data and data["items"] and "key" in data["items"][0]:
            if case.name == "camera":
                return self.answer()
            if data["total"] > 1 and case.name != "partial_batch":
                names = "、".join(f"{item['name']}（{item.get('identifier', '')}）" for item in data["items"])
                return self.tool("ask_user", {"question": "请选择需要修改的摄像头：" + names})
            return self.tool("read_configurations", {"resource_keys": [data["items"][0]["key"]]})
        if "items" in data and data["items"] and "resource" in data["items"][0]:
            if platform.phase == "prelude":
                return self.answer()
            if case.name == "reference":
                return self.tool("ask_user", {"question": "已定位诊断闸机一号的人体置信度，请明确要调低到哪个数值。"})
            item = data["items"][0]
            delta = deepcopy(case.patch)
            if case.name == "extra_field":
                delta["value"]["cap_interval"] = 0.2
            return self.tool("update_configurations", {"changes": [{"resource_key": item["resource"]["key"],
                "expected_revision": item["revision"], "patch": delta}]})
        return self.answer()

    @staticmethod
    def tool(name, arguments):
        return completion({"action": name, "arguments": arguments}), 0.0

    @staticmethod
    def answer():
        return completion({"action": "answer", "answer": "结束本轮"}), 0.0


class MeasuredClient:
    """仅保存布尔指标、类别和计数；不把请求正文、模型原文或认证头写入报告。"""

    def __init__(self, platform, delegate, *, live=False):
        self.platform, self.delegate, self.live = platform, delegate, live
        self.calls = 0
        self.real_calls = 0
        self.json_results = []
        self.plans = []
        self.plan_operations = []
        self.errors = []
        self.injected = []
        self.saw_history = False
        self.requests = []

    def complete(self, **kwargs):
        from AiVision.assistant.responses import completion_content, json_content, parse_plan
        from AiVision.assistant.orchestration import validate_task_sources

        self.calls += 1
        platform, case = self.platform, self.platform.scenario
        planning = "只判断当前用户请求" in kwargs["messages"][0]["content"]
        history_count, history_text = context_statistics(kwargs["messages"])
        request = {"kind": "planning" if planning else "business", "messages": len(kwargs["messages"]),
                   "characters": sum(len(str(message.get("content", ""))) for message in kwargs["messages"]),
                   "history_pairs": history_count if planning else None,
                   "max_tokens": kwargs["max_tokens"],
                   "response_format": "json_schema" if kwargs.get("response_schema") is not None else "json_object" if kwargs["json_mode"] else "text"}
        system = kwargs["messages"][0]["content"]
        request["agent"] = ("coordinator" if planning else "query" if "当前专家：查询专家" in system
                            else "configuration" if "当前专家：配置专家" in system else "chat")
        anchor = getattr(platform, "history_anchor", None)
        if planning and anchor:
            request["anchor_in_history"] = anchor in history_text
        binding = getattr(platform, "history_binding", None)
        if planning and binding:
            request["binding_in_history"] = all(part in history_text for part in binding)
            from AiVision.assistant.context import CONTEXT_PREFIX
            from AiVision.assistant.targets import matches_name
            context = json.loads(history_text[len(CONTEXT_PREFIX):]) if history_text.startswith(CONTEXT_PREFIX) else {}
            request["verified_binding_in_context"] = any(
                item["alias"] == binding[0] and matches_name(binding[1], item["resource"])
                for item in (context.get("task_context") or {}).get("target_bindings", []))
        self.requests.append(request)
        request_started = time.perf_counter()
        progress = getattr(platform, "model_progress", None)
        if progress:
            progress(request["kind"], self.calls)
        if platform.phase in {"continuation", "main_after_prelude"}:
            self.saw_history |= history_count > 0
        try:
            if case.fault == "invalid_json" and planning and not self.injected:
                raw, latency = completion('{"mode":'), 0.0
                self.injected.append("invalid_json")
            elif case.fault == "truncated" and planning:
                raw, latency = completion('{"mode":', "length"), 0.0
                self.injected.append("truncated")
            else:
                self.real_calls += int(self.live)
                raw, latency = self.delegate.complete(**kwargs)
            if case.fault == "wrong_answer" and platform.service.has_actions(platform.turn_id):
                try:
                    body = json.loads(json_content(completion_content(raw)))
                except (ValueError, RuntimeError):
                    body = {}
                if body.get("action") == "answer":
                    raw = completion({"action": "answer", "answer": "操作失败，没有保存任何配置。"})
                    self.injected.append("wrong_answer")
            if kwargs["json_mode"]:
                syntax_ok = json_validity(raw)
                request["json_valid"] = syntax_ok
                if syntax_ok is not None:
                    self.json_results.append(syntax_ok)
            if planning:
                try:
                    plan = parse_plan(raw)
                    self.plans.append(plan.mode)
                    self.plan_operations.append(plan.operations)
                    question = (platform.step.question if hasattr(platform, "step") else case.prelude if platform.phase == "prelude"
                                else case.continuation if platform.phase == "continuation" else case.question)
                    validate_task_sources(plan, question)
                    request["plan_valid"] = True
                    request["task_agents"] = [task.agent for task in plan.tasks]
                    request["target_context_evidence"] = planning_target_evidence(plan, question)
                except RuntimeError as exc:
                    self.errors.append(type(exc).__name__)
                    request["plan_valid"] = False
                    request["validation_category"] = getattr(exc, "category", type(exc).__name__)
                    if hasattr(exc, "issues"):
                        request["validation_issues"] = exc.issues
            if case.fault == "cancel" and self.calls == 2:
                platform.service.cancel(platform.session_id, platform.turn_id, platform.user)
                self.injected.append("cancel")
            request.update(response_statistics(raw))
            try:
                usage = json.loads(raw).get("usage", {})
                for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    if isinstance(usage.get(name), int):
                        request[name] = usage[name]
            except (ValueError, AttributeError, TypeError):
                request["usage_available"] = False
            return raw, latency
        except Exception as exc:
            self.errors.append(type(exc).__name__)
            raise
        finally:
            request["duration_seconds"] = round(time.perf_counter() - request_started, 6)


class ObservedTools:
    def __init__(self, platform, **kwargs):
        from AiVision.assistant.tools import AssistantTools

        self.platform = platform
        self.delegate = AssistantTools(**kwargs)
        self.turn_id = kwargs["turn_id"]

    @property
    def target_policy(self):
        return self.delegate.target_policy

    @target_policy.setter
    def target_policy(self, value):
        self.delegate.target_policy = value

    @property
    def change_policy(self):
        return self.delegate.change_policy

    @change_policy.setter
    def change_policy(self, value):
        self.delegate.change_policy = value

    def catalog(self, **kwargs):
        return self.delegate.catalog(**kwargs)

    def begin_task(self, task_index=1):
        self.delegate.begin_task(task_index)

    def run(self, name, arguments):
        platform = self.platform
        entry = {"tool": name, "arguments": deepcopy(arguments), "ok": False, "task_index": self.delegate.task_index}
        platform.trace.append(entry)
        try:
            if platform.scenario.fault == "tool_error" and name == "list_resources":
                platform.injected.append("tool_error")
                raise RuntimeError("诊断注入的工具故障")
            if platform.fake_tools:
                from AiVision.assistant.tools import TOOL_MODELS
                if self.target_policy is not None:
                    args = TOOL_MODELS[name][0].model_validate_json(json.dumps(arguments))
                    self.target_policy.check(name, args)
                result = self.fake_run(name, arguments)
                if self.target_policy is not None:
                    self.target_policy.observe(name, result)
                if self.change_policy is not None:
                    self.change_policy.observe(name, result, arguments)
            else:
                result = self.delegate.run(name, arguments)
            entry["ok"] = "error" not in result
            entry["result"] = result
            if platform.scenario.fault == "conflict" and name == "read_configurations" and not platform.injected:
                platform.set_threshold(101, 0.6)
                platform.injected.append("conflict")
            return result
        except Exception as exc:
            entry["error_type"] = type(exc).__name__
            raise
        finally:
            if self.target_policy is not None:
                step = getattr(platform, "step", None)
                entry["target_evidence"] = tool_target_evidence(self.target_policy, name, arguments,
                                                               expected_keys=step.targets if step else ())

    def fake_run(self, name, arguments):
        """模拟层只更新虚构字典和隔离审计，不调用摄像头配置保存服务。"""
        from AiVision.assistant.schema import ResourceReference
        from AiVision.core.config_revision import configuration_revision
        from AiVision.features.tailgating.schema import TailgatingConfig

        platform = self.platform
        if name == "capabilities":
            return {"features": [{"name": FEATURE, "label": "非法闯闸"}],
                    "departments": [{"id": DEPARTMENT, "name": "通用电气事业部"}]}
        if name == "ask_user":
            return arguments
        if name == "list_resources":
            query = arguments.get("query", "")
            items = [{"key": f"feature:tailgating:{number}", "kind": "feature", "name": title,
                      "department": DEPARTMENT, "feature": FEATURE, "identifier": f"camera_{number}"}
                     for number, title in [(101, CAMERA_NAME), (102, SECOND_CAMERA_NAME)] if query in title]
            return {"items": items, "total": len(items), "next_offset": None}
        if name == "read_configurations":
            return {"items": [{"resource": {"key": key, "kind": "feature", "name": CAMERA_NAME,
                                           "department": DEPARTMENT, "feature": FEATURE},
                               "config": deepcopy(platform.fake_configs[key]),
                               "revision": configuration_revision(platform.fake_configs[key]),
                               "schema_definition": TailgatingConfig.model_json_schema()}
                              for key in arguments["resource_keys"]]}
        if name == "update_configurations":
            if self.change_policy is not None:
                from AiVision.assistant.resources import ConfigurationResource
                from AiVision.assistant.tools import UpdateArguments

                changes = UpdateArguments.model_validate_json(json.dumps(arguments)).changes
                for change in changes:
                    resource = ConfigurationResource(
                        ResourceReference(**self.change_policy.resources[change.resource_key]), TailgatingConfig,
                        platform.fake_configs[change.resource_key], lambda *_args: None,
                    )
                    resource.prepare(change.patch)
                    self.change_policy.check_patch(resource, change.patch)
                self.change_policy.check_targets(changes)
            results = []
            for change in arguments["changes"]:
                key, delta = change["resource_key"], change["patch"]
                before = deepcopy(platform.fake_configs[key])
                platform.fake_configs[key]["value"].update(delta["value"])
                reference = ResourceReference(key=key, kind="feature", name=CAMERA_NAME, department=DEPARTMENT, feature=FEATURE)
                action, _execute = platform.service.begin_action(self.turn_id, reference, before, delta)
                action = platform.service.finish_action(action.id, "saved", deepcopy(platform.fake_configs[key]), "模拟工具已保存")
                results.append(action.model_dump(mode="json"))
            return {"results": results}
        raise ValueError("模拟工具未登记")


@contextmanager
def isolated_platform(scenario, *, base_url="http://127.0.0.1:18100/v1", model="fuda-qwen38-27b",
                      max_tokens=2048, timeout=45.0, temperature=0.0, fake_tools=False, live=False):
    """不加载 .env；覆盖数据库入口，缓存和事件只替换跨进程运行设施。"""
    with tempfile.TemporaryDirectory(prefix="fuda-assistant-diagnostic-") as directory, ExitStack() as stack:
        stack.enter_context(patch.dict("os.environ", {
            "MYSQL_DB_URL": "diagnostic.invalid", "MYSQL_DB_USER": "diagnostic", "MYSQL_DB_PASSWORD": "unused",
            "MYSQL_DB_NAME": "diagnostic", "AUTO_CREATE_DB": "false", "DATA_PATH": directory,
        }))
        from sqlalchemy import create_engine, event
        from sqlalchemy.engine import Engine
        from sqlalchemy.orm import sessionmaker
        from AiVision.core import db
        from AiVision.assistant import runtime as runtime_module
        from AiVision.assistant.orm import AssistantAction, AssistantSession, AssistantTurn
        from AiVision.assistant.schema import AssistantSettings
        from AiVision.assistant.service import assistant_service
        from AiVision.cameras import config_manager as camera_module
        from AiVision.cameras.orm import AiCameraConfig
        from AiVision.core.system_config import AiSystemConfig
        from AiVision.features._shared import config_manager as feature_module
        from AiVision.features.registry import get_spec
        from AiVision.features.tailgating.orm import TailgatingConfigORM
        from AiVision.features.tailgating.schema import TailgatingConfig
        from AiVision.features.guard_behavior.orm import GuardBehaviorSite, GuardBehaviorSiteCamera

        database = Path(directory) / "diagnostic.sqlite3"
        engine = create_engine(f"sqlite+pysqlite:///{database}", echo=False)
        stack.callback(engine.dispose)

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        original_connect = Engine.connect

        def isolated_connect(candidate, *args, **kwargs):
            if candidate is not engine:
                raise RuntimeError("诊断隔离禁止连接其他业务数据库")
            return original_connect(candidate, *args, **kwargs)

        stack.enter_context(patch.object(Engine, "connect", isolated_connect))
        factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
        stack.enter_context(patch.object(db, "_engine", engine))
        stack.enter_context(patch.object(db, "_session_factory", factory))
        stack.enter_context(patch.object(db, "get_engine", lambda: engine))
        stack.enter_context(patch.object(camera_module, "all_specs", lambda: {FEATURE: get_spec(FEATURE)}))
        stack.enter_context(patch.object(feature_module, "config_cache", SimpleNamespace(reload=Mock())))
        stack.enter_context(patch.object(feature_module, "config_event_bus", SimpleNamespace(publish=Mock())))
        stack.enter_context(patch.object(camera_module, "config_cache", SimpleNamespace(reload=Mock(), refresh_camera=Mock())))
        stack.enter_context(patch.object(camera_module, "config_event_bus", SimpleNamespace(publish=Mock())))
        tables = [AiCameraConfig.__table__, TailgatingConfigORM.__table__, AiSystemConfig.__table__,
                  AssistantSession.__table__, AssistantTurn.__table__, AssistantAction.__table__,
                  db.Base.metadata.tables["ai_horn_config"], GuardBehaviorSite.__table__, GuardBehaviorSiteCamera.__table__]
        db.Base.metadata.create_all(engine, tables=tables)
        user = {"employee_id": "diagnostic-user", "role": "viewer" if scenario.name == "permission" else "admin",
                "departments": [DEPARTMENT], "feature_access": {DEPARTMENT: [FEATURE]}}
        connection_settings = AssistantSettings(base_url=base_url, model=model, max_tokens=max_tokens,
                                               api_timeout_sec=timeout, temperature=temperature)
        with db.session_scope() as session:
            for number, title, department in [(101, CAMERA_NAME, DEPARTMENT), (102, SECOND_CAMERA_NAME, DEPARTMENT),
                                              (103, "诊断外部门闸机", "research_institute")]:
                session.add(AiCameraConfig(id=number, name=title, shm_name=f"camera_{number}",
                                          url="rtsp://diagnostic.invalid/live", department=department, enable=True))
                config = TailgatingConfigORM(camera_id=number)
                config.apply_config_dict(TailgatingConfig().model_dump())
                session.add(config)
            session.add(AiSystemConfig(key="assistant", value=connection_settings.model_dump()))
        platform = SimpleNamespace(scenario=scenario, service=assistant_service, user=user, trace=[], injected=[],
                                   phase="main", turn_id=None, fake_tools=fake_tools, settings=connection_settings)
        platform.session_id = assistant_service.create_session(user, DEPARTMENT).id

        def snapshot():
            return {f"feature:tailgating:{number}": feature_module.feature_config_manager.get_config(get_spec(FEATURE), number)["config"]
                    for number in (101, 102, 103)}

        def set_threshold(number, value):
            with db.session_scope() as session:
                session.query(TailgatingConfigORM).filter_by(camera_id=number).one().threshold = value

        platform.snapshot = snapshot
        platform.set_threshold = set_threshold
        platform.before = snapshot()
        platform.fake_configs = deepcopy(platform.before)
        delegate = runtime_module.QwenClient() if live else ScriptedClient(platform)
        platform.client = MeasuredClient(platform, delegate, live=live)
        stack.enter_context(patch.object(runtime_module, "AssistantTools", lambda **kwargs: ObservedTools(platform, **kwargs)))
        runtime = runtime_module.AssistantRuntime(client=platform.client)
        runtime._executor.shutdown(wait=True)
        runtime._executor = InlineExecutor()
        stack.callback(runtime.close)
        platform.runtime = runtime
        platform.db = db
        platform.feature_manager = feature_module.feature_config_manager
        platform.spec = get_spec(FEATURE)

        original_enqueue = assistant_service.enqueue

        def enqueue(*args, **kwargs):
            turn = original_enqueue(*args, **kwargs)
            platform.turn_id = turn.id
            return turn

        stack.enter_context(patch.object(assistant_service, "enqueue", enqueue))
        yield platform


def execute_turn(platform, question, request_id=None):
    from AiVision.assistant.schema import MessageCreate

    request_id = request_id or uuid4()
    payload = MessageCreate(request_id=request_id, text=question)
    response = platform.runtime.submit(platform.session_id, payload, lambda: platform.user, None)
    conversation = platform.service.conversation(platform.session_id, platform.user)
    turn = next(item for item in conversation.turns if item.id == response.id)
    return turn, payload


def run_dialogue(scenario, **settings):
    started = time.perf_counter()
    with isolated_platform(scenario, **settings) as platform:
        if scenario.prelude:
            platform.phase = "prelude"
            execute_turn(platform, scenario.prelude)
            platform.phase = "main_after_prelude"
        turn, payload = execute_turn(platform, scenario.question)
        if scenario.continuation:
            platform.phase = "continuation"
            turn, payload = execute_turn(platform, scenario.continuation)
        duplicate_ok = None
        if scenario.name == "duplicate":
            call_count = platform.client.calls
            repeated, _ = execute_turn(platform, scenario.question, payload.request_id)
            duplicate_ok = repeated.id == turn.id and platform.client.calls == call_count and len(platform.service.actions(turn.id)) == 1
        return evaluate(platform, turn, time.perf_counter() - started, duplicate_ok)


def evaluate(platform, turn, duration, duplicate_ok):
    case = platform.scenario
    actual = platform.fake_configs if platform.fake_tools else platform.snapshot()
    expected = deepcopy(platform.before)
    if case.expected in {"saved", "unchanged"}:
        expected[RESOURCE]["value"].update(case.patch["value"])
    if case.name == "partial_batch" and case.expected == "saved":
        expected[SECOND_RESOURCE]["value"].update(case.patch["value"])
    if "conflict" in platform.injected:
        expected[RESOURCE]["value"]["threshold"] = 0.6
    configuration_ok = actual == expected
    actions = platform.service.actions(turn.id)
    tools = [entry["tool"] for entry in platform.trace]
    writes = observed_arguments(platform.trace, "update_configurations", "changes", dict)
    executed_writes = observed_arguments([item for item in platform.trace if item["ok"]],
                                        "update_configurations", "changes", dict)
    scope_rejected = any(item.get("error_type") == "ChangeScopeError" for item in platform.trace)
    scope_recovered = bool(scope_rejected and executed_writes and configuration_ok
                           and all(change.get("patch") == case.patch for change in executed_writes))
    parameter_ok = bool(writes) and all(change.get("patch") == case.patch for change in writes) if "update_configurations" in tools else None
    allowed_keys = ({"camera:101"} if case.name == "camera" else
                    {RESOURCE, SECOND_RESOURCE} if case.name == "partial_batch" else {RESOURCE})
    read_keys = observed_arguments(platform.trace, "read_configurations", "resource_keys", str)
    resource_ok = all(isinstance(key, str) and key in allowed_keys for key in read_keys + [change.get("resource_key") for change in writes])
    if case.expected in {"saved", "unchanged"}:
        resource_ok &= bool(writes) and "list_resources" in tools
    if case.name == "camera":
        lookups = [entry for entry in platform.trace if entry["tool"] == "list_resources" and entry["ok"]]
        resource_ok &= bool(lookups) and {item["key"] for item in lookups[-1]["result"].get("items", [])} == {"camera:101"}
    required = {"list_resources", "read_configurations", "update_configurations"} if case.expected in {"saved", "unchanged"} else set()
    if case.expected.startswith("clarify"):
        required = {"ask_user", "list_resources"}
    permitted = {"capabilities", "list_resources", "read_configurations", "update_configurations", "ask_user"}
    tool_selection_ok = required <= set(tools) and set(tools) <= permitted
    success_words = "已保存配置" in turn.answer or "已是目标值" in turn.answer
    if case.expected in {"saved", "unchanged"}:
        report_ok = ((turn.status == "completed" and success_words) if configuration_ok else
                     (turn.status == "failed" and bool(turn.answer) and not success_words))
        behavior_ok = configuration_ok and report_ok and tool_selection_ok and (parameter_ok is not False or scope_recovered)
    elif case.expected.startswith("clarify"):
        report_ok = not success_words and not actions and turn.status == "completed"
        if case.expected == "clarify_target":
            report_ok &= CAMERA_NAME in turn.answer and SECOND_CAMERA_NAME in turn.answer
        else:
            report_ok &= "值" in turn.answer or "数" in turn.answer
        behavior_ok = configuration_ok and report_ok and "ask_user" in tools
    elif case.expected == "cancelled":
        report_ok = turn.status == "cancelled" and not actions
        behavior_ok = configuration_ok and report_ok
    elif case.expected == "rejected":
        report_ok = not success_words and not any(action.status == "saved" for action in actions)
        behavior_ok = configuration_ok and report_ok and turn.status in {"failed", "completed"}
    elif case.expected == "scope_rejected":
        # 固定模型持续提交越界指令时，只能判定保护生效，不能计为原修改任务完成。
        report_ok = not success_words and not actions and turn.status == "failed"
        behavior_ok = configuration_ok and report_ok and any(
            item.get("error_type") == "ChangeScopeError" for item in platform.trace)
    elif case.expected == "chat":
        report_ok = (turn.status == "completed" and not tools and
                     any(token in turn.answer for token in ("你好", "您好", "嗨", "哈喽")) and not any(
                         token in turn.answer for token in ('"action"', "尚未完成", "已删除摄像头", "已保存配置")))
        behavior_ok = report_ok and configuration_ok
    else:
        token = "非法闯闸" if case.expected == "capabilities" else CAMERA_NAME
        report_ok = turn.status == "completed" and token in turn.answer and not actions
        behavior_ok = report_ok and configuration_ok
    if duplicate_ok is not None:
        behavior_ok &= duplicate_ok
    if case.prelude or case.continuation:
        behavior_ok &= platform.client.saw_history
    injected_faults = sorted(set(platform.injected + platform.client.injected))
    if case.fault:
        behavior_ok &= case.fault in injected_faults
    service_failed = any(name in {"QwenNetworkError", "QwenTimeoutError", "QwenServiceError"} for name in platform.client.errors)
    classification_ok = platform.client.plans[-1] == case.mode if platform.client.plans else case.mode == "chat"
    operations_ok = (set(platform.client.plan_operations[-1]) == ({"update_configurations"} if case.mode == "change" else set())
                     if platform.client.plan_operations else case.mode == "chat")
    if service_failed and not platform.client.plans:
        classification_ok = None
        operations_ok = None
    if not read_keys and not writes and case.expected in {"chat", "capabilities", "rejected", "cancelled"}:
        resource_ok = None
    if not tools or (service_failed and tools == ["capabilities"]):
        tool_selection_ok = None
    faults = []
    if classification_ok is False or operations_ok is False:
        faults.append("model_output")
    if not service_failed and (tool_selection_ok is False or resource_ok is False or parameter_ok is False):
        faults.append("model_output" if platform.client.live or scope_rejected else "agent_scheduling")
    if not configuration_ok and not service_failed:
        if case.name in {"extra_field", "partial_batch"}:
            faults.append("agent_scheduling")
        elif writes and parameter_ok:
            faults.append("business_execution")
        else:
            faults.append("model_output" if platform.client.live else "agent_scheduling")
    if not report_ok:
        faults.append("result_reporting")
    if service_failed:
        faults.append("model_service")
    changed_fields = sorted(key for key in actual[RESOURCE]["value"]
                            if actual[RESOURCE]["value"][key] != platform.before[RESOURCE]["value"].get(key))
    evidence = {"requested_value_fields": sorted(case.patch.get("value", {})), "changed_value_fields": changed_fields,
                "saved_action_count": sum(action.status == "saved" for action in actions),
                "goal_verified": configuration_ok and case.expected != "scope_rejected", "reported_status": turn.status}
    if case.expected == "scope_rejected":
        evidence["protection_verified"] = bool(behavior_ok)
    if scope_recovered:
        evidence["scope_recovered"] = True
    if case.name == "partial_batch":
        evidence.update(expected_targets=2, verified_targets=sum(
            actual[key]["value"]["threshold"] == 0.8 for key in (RESOURCE, SECOND_RESOURCE)))
    return {"scenario": case.name, "label": case.label, "status": turn.status,
            "classification_ok": classification_ok, "resource_ok": resource_ok,
            "planning_operations_ok": operations_ok,
            "tool_selection_ok": tool_selection_ok, "parameter_ok": parameter_ok,
            "json_ok": platform.client.json_results, "tool_execution_ok": [entry["ok"] for entry in platform.trace],
            "configuration_ok": configuration_ok, "report_ok": bool(report_ok), "behavior_ok": bool(behavior_ok),
            "task_ok": bool(behavior_ok) if case.eligible else None,
            "model_calls": platform.client.calls, "real_model_calls": platform.client.real_calls,
            "duration_seconds": round(duration, 6), "tools": tools, "errors": sorted(set(platform.client.errors +
                [entry["error_type"] for entry in platform.trace if "error_type" in entry])),
            "injected_faults": injected_faults,
            "failure_layers": sorted(set(faults)), "duplicate_ok": duplicate_ok,
            "history_received": platform.client.saw_history if case.prelude or case.continuation else None,
            "evidence": evidence,
            "business_storage": "simulated" if platform.fake_tools else "temporary_sqlite"}
