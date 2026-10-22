"""严格任务分类、单次格式纠正与执行边界的回归验证，不连接模型或业务数据库。"""

import json
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import traceback

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1", "MYSQL_DB_USER": "test", "MYSQL_DB_PASSWORD": "unused",
        "MYSQL_DB_NAME": "test", "DATA_PATH": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)


def completion(content, *, finish_reason="stop"):
    return json.dumps({"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)},
                                   "finish_reason": finish_reason}]})


@pytest.mark.parametrize("payload", [
    {"mode": "chat", "operations": []}, {"mode": "query", "operations": []},
    {"mode": "change", "operations": ["update_configurations", "bind_camera"]},
    {"mode": "chat"},
])
def test_valid_plans_follow_the_existing_schema(payload):
    from AiVision.assistant.responses import parse_plan
    from AiVision.assistant.schema import RequestPlan

    assert parse_plan(completion(payload)) == RequestPlan.model_validate(payload)


@pytest.mark.parametrize("payload, location, code", [
    ({"operations": []}, ["mode"], "missing"),
    ({"mode": "unknown"}, ["mode"], "literal_error"),
    ({"mode": "change", "operations": []}, [], "value_error"),
    ({"mode": "change"}, [], "value_error"),
    ({"mode": "chat", "operations": ["delete_camera"]}, [], "value_error"),
    ({"mode": "query", "operations": ["add_camera"]}, [], "value_error"),
    ({"mode": "change", "operations": ["delete_camera", "delete_camera"]}, [], "value_error"),
    ({"mode": "change", "operations": ["run_sql"]}, ["operations", 0], "literal_error"),
    ({"mode": "chat", "operations": ""}, ["operations"], "list_type"),
    ({"mode": "chat", "answer": "你好"}, ["<额外字段>"], "extra_forbidden"),
    ([], [], "model_type"),
])
def test_schema_errors_keep_safe_field_locations_and_types(payload, location, code):
    from AiVision.assistant.responses import PlanFormatError, parse_plan

    with pytest.raises(PlanFormatError) as caught:
        parse_plan(completion(payload))
    assert caught.value.category == "plan_schema"
    assert any(issue["loc"] == location and issue["type"] == code for issue in caught.value.issues)


@pytest.mark.parametrize("content", ['{"mode":', '你好', '{"mode":"chat"} trailing'])
def test_invalid_planning_json_is_distinct_from_schema_validation(content):
    from AiVision.assistant.responses import PlanFormatError, parse_plan

    with pytest.raises(PlanFormatError) as caught:
        parse_plan(completion(content))
    assert caught.value.category == "plan_json"
    assert caught.value.issues[0]["type"] == "json_invalid"


@pytest.mark.parametrize("body, error_name", [
    ("not an envelope", "QwenResponseError"),
    (json.dumps({"choices": []}), "QwenResponseError"),
    (completion(""), "QwenResponseError"),
    (completion('{"mode":', finish_reason="length"), "QwenTruncatedError"),
    (completion("{}", finish_reason="error"), "QwenServiceError"),
    (json.dumps({"error": {"message": "private service detail"}}), "QwenServiceError"),
])
def test_bad_envelopes_truncation_and_model_service_failures_are_not_plan_format_errors(body, error_name):
    from AiVision.assistant.responses import PlanFormatError, parse_plan
    from AiVision.connectors.qwen import client

    with pytest.raises(getattr(client, error_name)) as caught:
        parse_plan(body)
    assert not isinstance(caught.value, PlanFormatError)


def test_complete_empty_thinking_and_json_fences_keep_working():
    from AiVision.assistant.responses import parse_plan

    assert parse_plan(completion('<think> </think>\n```json\n{"mode":"chat","operations":[]}\n```')).mode == "chat"


@pytest.mark.parametrize("text, expected", [
    ("你好", True), (" 您好！ ", True), ("Hello!", True), ("hi?", True),
    ("你好哇", True), ("你好呀！", True), ("您好啊", True), ("哈喽呀～", True),
    ("你好啊啊啊！", True), ("你好 哇", True),
    ("你好，帮我修改摄像头 FPS", False), ("你好\n删除一号摄像头", False),
    ("你好哇，帮我删除摄像头", False), ("你好呀！查询当前摄像头", False),
    ("你好啊\n请停用报警", False), ("继续删", False), ("确认删除", False),
    ("你好! 请关闭报警", False), ("把摄像头名称改为你好", False), ("查询当前配置", False),
    ("‘你好’", False), ("", False),
])
def test_greeting_rule_only_matches_the_whole_message(text, expected):
    from AiVision.assistant.responses import is_simple_greeting

    assert is_simple_greeting(text) is expected


@pytest.fixture
def runtime_case(monkeypatch):
    from AiVision.assistant import runtime as module
    from AiVision.assistant.schema import AssistantSettings

    service = Mock()
    service.settings.return_value = AssistantSettings(api_timeout_sec=10.0)
    service.cancelled.return_value = False
    service.has_actions.return_value = False
    service.actions.return_value = []
    current = SimpleNamespace(id=1, question="请介绍安检规则", status="queued", answer="", actions=[])
    service.conversation.return_value = SimpleNamespace(turns=[current], session=SimpleNamespace(department="general_electric"))
    monkeypatch.setattr(module, "assistant_service", service)
    tools = Mock()

    def tool_result(name, _arguments):
        if name == "capabilities":
            return {"departments": [{"name": "通用电气"}], "features": []}
        if name == "list_resources":
            return {"items": [{"key": "camera:1", "name": "一号摄像头", "identifier": "camera_1"}]}
        return {"status": "saved", "after": {"fps": 8}}

    tools.run.side_effect = tool_result
    monkeypatch.setattr(module, "AssistantTools", Mock(return_value=tools))
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    client = Mock()
    runtime = module.AssistantRuntime(client=client)
    yield SimpleNamespace(
        module=module, runtime=runtime, service=service, tools=tools, client=client, current=current, clock=clock,
        execute=lambda: runtime._execute("session-1", 1, lambda: {"role": "admin"}, None),
        plan=lambda **kwargs: runtime._plan_request(
            question=current.question, history=[], model=service.settings(),
            check_cancel=lambda: None, turn_id=1, **kwargs,
        ),
    )
    runtime.close()


@pytest.mark.parametrize("invalid", [{"operations": []}, '{"mode":'])
def test_planning_corrects_once_with_validation_errors_and_the_complete_schema(runtime_case, invalid):
    case = runtime_case
    case.client.complete.side_effect = [(completion(invalid), 0.1), (completion({"mode": "chat"}), 0.1)]
    assert case.plan().mode == "chat"
    assert case.client.complete.call_count == 2
    first, second = [call.kwargs for call in case.client.complete.call_args_list]
    assert len(first["messages"]) == 2 and len(second["messages"]) == 3
    assert '"required": ["mode"]' in second["messages"][0]["content"]
    correction = second["messages"][-1]["content"]
    assert "校验错误" in correction and "完整 JSON" in correction
    assert ("json_invalid" if isinstance(invalid, str) else "missing") in correction
    assert first["json_mode"] and second["json_mode"]
    assert first["max_tokens"] == second["max_tokens"] == case.module.PLAN_MAX_TOKENS
    case.tools.run.assert_not_called()


def test_failed_correction_stops_before_any_business_tool(runtime_case):
    from AiVision.assistant.responses import PlanFormatError

    case = runtime_case
    case.client.complete.side_effect = [(completion({"mode": "bad"}), 0.1)] * 3
    with pytest.raises(PlanFormatError) as caught:
        case.execute()
    assert caught.value.category == "plan_schema"
    assert case.client.complete.call_count == 2
    case.tools.run.assert_not_called()
    case.tools.catalog.assert_not_called()


@pytest.mark.parametrize("failure", ["envelope", "length", "network", "service", "timeout"])
def test_unrecoverable_errors_do_not_trigger_format_correction(runtime_case, failure):
    from AiVision.connectors.qwen.client import QwenError, QwenNetworkError, QwenServiceError, QwenTimeoutError

    case = runtime_case
    effects = {"envelope": ("bad", 0.1), "length": (completion("{", finish_reason="length"), 0.1),
               "network": QwenNetworkError("连接失败"), "service": QwenServiceError("HTTP 503"),
               "timeout": QwenTimeoutError("超时")}
    case.client.complete.side_effect = [effects[failure]]
    with pytest.raises(QwenError):
        case.plan()
    assert case.client.complete.call_count == 1
    case.tools.run.assert_not_called()


def test_correction_uses_only_the_remaining_planning_timeout(runtime_case):
    case = runtime_case

    def respond(**_kwargs):
        case.clock.now += 6 if case.client.complete.call_count == 1 else 1
        return completion({"mode": "wrong"} if case.client.complete.call_count == 1 else {"mode": "query"}), 1.0

    case.client.complete.side_effect = respond
    assert case.plan().mode == "query"
    assert [call.kwargs["timeout"] for call in case.client.complete.call_args_list] == [10.0, 4.0]


@pytest.mark.parametrize("valid_reply", [True, False])
def test_exhausted_planning_budget_does_not_issue_another_request(runtime_case, valid_reply):
    from AiVision.connectors.qwen.client import QwenTimeoutError

    case = runtime_case

    def late_reply(**_kwargs):
        case.clock.now += 10
        return completion({"mode": "chat" if valid_reply else "wrong"}), 10.0

    case.client.complete.side_effect = late_reply
    with pytest.raises(QwenTimeoutError):
        case.plan()
    assert case.client.complete.call_count == 1


@pytest.mark.parametrize("cancel_at", ["before", "after_response", "before_retry", "after_retry_response", "stopping"])
def test_cancellation_prevents_followup_requests_and_tools(runtime_case, cancel_at):
    case = runtime_case
    case.client.complete.return_value = (completion({"mode": "bad"}), 0.1)
    if cancel_at == "before":
        case.service.cancelled.return_value = True
    elif cancel_at == "after_response":
        def cancelled_reply(**_kwargs):
            case.service.cancelled.return_value = True
            return completion({"mode": "bad"}), 0.1
        case.client.complete.side_effect = cancelled_reply
    elif cancel_at == "after_retry_response":
        def cancelled_retry(**_kwargs):
            if case.client.complete.call_count == 2:
                case.service.cancelled.return_value = True
            return completion({"mode": "bad" if case.client.complete.call_count == 1 else "chat"}), 0.1
        case.client.complete.side_effect = cancelled_retry
    else:
        def cancel_on_correction(_turn_id, progress):
            if "纠正" in progress:
                if cancel_at == "stopping":
                    case.runtime._stopping.set()
                else:
                    case.service.cancelled.return_value = True
        case.service.progress.side_effect = cancel_on_correction
    with pytest.raises(case.module.TaskCancelled):
        case.execute()
    assert case.client.complete.call_count == (0 if cancel_at == "before" else 2 if cancel_at == "after_retry_response" else 1)
    case.tools.run.assert_not_called()


def test_standalone_greeting_skips_planning_but_still_uses_the_chat_model(runtime_case):
    case = runtime_case
    case.current.question = "你好"
    case.client.complete.return_value = (completion("你好，我是福达AI助手。"), 0.1)
    case.execute()
    assert case.client.complete.call_count == 1
    assert case.client.complete.call_args.kwargs["json_mode"] is False
    case.service.finish.assert_called_once_with(1, "completed", "你好，我是福达AI助手。")
    case.tools.run.assert_not_called()


@pytest.mark.parametrize("question", ["你好", "你好哇", "你好呀！", "您好啊"])
@pytest.mark.parametrize("previous_task", ["failed_delete", "completed_delete", "name_question"])
def test_greeting_does_not_resume_or_include_a_previous_configuration_task(runtime_case, question, previous_task):
    case = runtime_case
    case.current.question = question
    action = Mock()
    action.model_dump.return_value = {"status": "saved", "target": "legacy_camera_marker"}
    previous = SimpleNamespace(
        id=0, question="请删除 legacy_camera_marker 摄像头", status="failed",
        answer="本轮没有执行配置变更，不能确认操作完成。尚未完成：删除摄像头。", actions=[],
    )
    if previous_task == "completed_delete":
        previous.status, previous.answer, previous.actions = "completed", "已删除 legacy_camera_marker", [action]
    elif previous_task == "name_question":
        previous.question, previous.answer = "重命名 legacy_camera_marker", "请输入摄像头新名称"
    case.service.conversation.return_value.turns.insert(0, previous)

    def reply(**kwargs):
        # 即使规划模型会错误延续删除任务，独立问候也不能进入该调用路径。
        content = {"mode": "change", "operations": ["delete_camera"]} if kwargs["json_mode"] else "你好呀，有什么可以帮你？"
        return completion(content), 0.1

    case.client.complete.side_effect = reply
    case.execute()
    assert case.client.complete.call_count == 1
    request = case.client.complete.call_args.kwargs
    assert request["json_mode"] is False
    assert len(request["messages"]) == 2
    assert "legacy_camera_marker" not in json.dumps(request["messages"], ensure_ascii=False)
    assert request["messages"][-1]["content"] == question
    case.tools.run.assert_not_called()
    case.tools.catalog.assert_not_called()
    action.model_dump.assert_not_called()
    case.service.finish.assert_called_once_with(1, "completed", "你好呀，有什么可以帮你？")


def test_greeting_cannot_authorize_a_delete_even_if_chat_model_returns_a_tool_call(runtime_case, monkeypatch):
    case = runtime_case
    case.current.question = "你好哇"
    monkeypatch.setattr(case.module.settings.runtime, "assistant_max_rounds", 1)
    case.client.complete.return_value = (completion({
        "action": "delete_camera", "arguments": {"camera_key": "camera:1", "expected_revision": "a" * 64},
    }), 0.1)
    case.execute()
    assert case.client.complete.call_args.kwargs["json_mode"] is False
    case.tools.run.assert_not_called()
    case.tools.catalog.assert_not_called()
    assert case.service.finish.call_args.args[1] == "failed"
    assert "尚未完成：删除摄像头" not in case.service.finish.call_args.args[2]


@pytest.mark.parametrize("question, operation", [
    ("你好哇，先查询当前摄像头", None),
    ("你好呀，帮我把摄像头 FPS 改成 8", "update_configurations"),
    ("你好啊，帮我删除 camera_1 摄像头", "delete_camera"),
    ("继续删", "delete_camera"),
])
def test_actual_operations_and_explicit_continuations_keep_their_planning_context(runtime_case, question, operation):
    case = runtime_case
    case.current.question = question
    case.service.conversation.return_value.turns.insert(0, SimpleNamespace(
        id=0, question="请核对 legacy_camera_marker 的配置", status="completed", answer="请明确接下来的操作", actions=[],
    ))
    if operation is None:
        plan = {"mode": "query", "operations": []}
        decision = {"action": "list_resources", "arguments": {"kind": "camera"}}
    else:
        plan = {"mode": "change", "operations": [operation]}
        arguments = {"camera_key": "camera:1", "expected_revision": "a" * 64} if operation == "delete_camera" else {
            "changes": [{"resource_key": "camera:1", "expected_revision": "a" * 64, "patch": {"fps": 8}}],
        }
        decision = {"action": operation, "arguments": arguments}
        case.service.actions.return_value = [SimpleNamespace(
            resource=SimpleNamespace(kind="camera_deletion" if operation == "delete_camera" else "camera",
                                     name="一号摄像头", identifier="camera_1"),
            status="saved", after={"fps": 8}, detail="数据库记录确认保存",
        )]
    case.client.complete.side_effect = [
        (completion(plan), 0.1), (completion(decision), 0.1),
        (completion({"action": "answer", "answer": "结束本轮"}), 0.1),
    ]
    case.execute()
    planning = case.client.complete.call_args_list[0].kwargs
    assert planning["json_mode"] is True
    assert "legacy_camera_marker" in json.dumps(planning["messages"], ensure_ascii=False)
    expected_tool = operation or "list_resources"
    assert any(call.args[0] == expected_tool for call in case.tools.run.call_args_list)
    assert case.service.finish.call_args.args[1] == "completed"


def test_query_results_still_come_from_tools(runtime_case):
    case = runtime_case
    case.current.question = "你好，查询摄像头"
    case.client.complete.side_effect = [
        (completion({"mode": "query"}), 0.1),
        (completion({"action": "list_resources", "arguments": {}}), 0.1),
        (completion({"action": "answer", "answer": "模型猜测的结果"}), 0.1),
    ]
    case.execute()
    assert "一号摄像头" in case.service.finish.call_args.args[2]
    assert "模型猜测" not in case.service.finish.call_args.args[2]
    case.tools.catalog.assert_not_called()


def test_change_keeps_write_permission_checks_and_audit_based_results(runtime_case):
    case = runtime_case
    case.current.question = "你好，帮我调整摄像头 FPS"
    case.service.actions.return_value = [SimpleNamespace(
        resource=SimpleNamespace(kind="camera", name="一号摄像头", identifier="camera_1"),
        status="saved", after={"fps": 8}, detail="数据库记录确认保存",
    )]
    case.client.complete.side_effect = [
        (completion({"mode": "change", "operations": ["update_configurations"]}), 0.1),
        (completion({"action": "update_configurations", "arguments": {"changes": []}}), 0.1),
        (completion({"action": "answer", "answer": "模型自行声称成功"}), 0.1),
    ]
    case.execute()
    case.tools.catalog.assert_called_once_with(write=True)
    case.service.actions.assert_called_once_with(1)
    assert "数据库记录确认保存" in case.service.finish.call_args.args[2]
    assert "模型自行声称成功" not in case.service.finish.call_args.args[2]


def test_query_cannot_execute_a_mutation_after_classification(runtime_case):
    case = runtime_case
    case.client.complete.side_effect = [
        (completion({"mode": "query"}), 0.1),
        (completion({"action": "delete_camera", "arguments": {}}), 0.1),
        (completion({"action": "answer", "answer": "已删除"}), 0.1),
    ]
    case.execute()
    assert all(call.args[0] != "delete_camera" for call in case.tools.run.call_args_list)
    assert case.service.finish.call_args.args[1] == "failed"


def test_classification_correction_does_not_expand_the_tool_round_budget(runtime_case, monkeypatch):
    case = runtime_case
    monkeypatch.setattr(case.module.settings.runtime, "assistant_max_rounds", 1)
    case.client.complete.side_effect = [
        (completion({"mode": "bad"}), 0.1), (completion({"mode": "query"}), 0.1),
        (completion({"action": "list_resources", "arguments": {}}), 0.1),
    ]
    case.execute()
    assert case.client.complete.call_count == 3
    assert case.service.finish.call_args.args[1] == "failed"
    assert "调用已达到上限" in case.service.finish.call_args.args[2]


def test_valid_change_classification_still_requires_real_write_permission(runtime_case, monkeypatch):
    from fastapi import HTTPException
    from AiVision.assistant.tools import AssistantTools

    case = runtime_case
    monkeypatch.setattr(case.module, "AssistantTools", AssistantTools)
    case.client.complete.return_value = (completion({"mode": "change", "operations": ["delete_camera"]}), 0.1)
    with pytest.raises(HTTPException) as caught:
        case.runtime._execute("session-1", 1, lambda: {"role": "viewer"}, None)
    assert caught.value.status_code == 403
    assert case.client.complete.call_count == 1
    case.service.actions.assert_not_called()


@pytest.mark.parametrize("read, actual, expected", [
    (None, "a", "a"), ("a", "b", "a"), ("a", "a", "b"),
])
def test_configuration_updates_still_require_a_read_and_matching_revision(monkeypatch, read, actual, expected):
    from AiVision.assistant import tools as module
    from AiVision.assistant.schema import ConfigurationChange
    from AiVision.core.config_revision import ConfigurationConflict

    resource = Mock(revision=actual * 64)
    catalog = Mock()
    catalog.resolve.return_value = resource
    service = Mock()
    monkeypatch.setattr(module, "assistant_service", service)
    tools = module.AssistantTools(
        turn_id=1, session_id="session-1", department="general_electric", load_user=lambda: {"role": "admin"},
        sources=None, orchestrator=None, check_cancel=lambda: None,
    )
    monkeypatch.setattr(tools, "catalog", Mock(return_value=catalog))
    if read is not None:
        tools.read_versions["camera:1"] = read * 64
    with pytest.raises(ConfigurationConflict):
        tools.update([ConfigurationChange(resource_key="camera:1", expected_revision=expected * 64, patch={"fps": 8})])
    resource.prepare.assert_not_called()
    resource.save.assert_not_called()
    service.begin_action.assert_not_called()


def test_validation_details_and_failure_logs_exclude_original_content(runtime_case, caplog):
    from AiVision.assistant.responses import PlanFormatError, parse_plan

    case = runtime_case
    secret = "fixture-private-dialogue-and-credential"
    source = "rtsp://" + "fixture-user:" + secret + "@example.invalid/live"
    body = completion({"mode": secret, source: {"password": secret}})
    with pytest.raises(PlanFormatError) as caught:
        parse_plan(body)
    assert secret not in str(caught.value)
    assert secret not in caught.value.correction_message()
    assert source not in caught.value.correction_message()
    assert secret not in "".join(traceback.format_exception(caught.value))
    case.current.question = secret + source
    case.client.complete.side_effect = [(body, 0.1), (body, 0.1)]
    case.runtime._slots.acquire()
    case.runtime._work("session-1", 1, lambda: {"role": "admin"}, None)
    assert "plan_schema" in caplog.text and "literal_error" in caplog.text
    assert secret not in caplog.text and source not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert case.service.finish.call_args.args[1] == "failed"
    assert secret not in case.service.finish.call_args.args[2]
    assert case.runtime._slots._value == case.module.settings.runtime.assistant_workers + case.module.settings.runtime.assistant_queue_capacity


@pytest.fixture
def feature_catalog_case(monkeypatch):
    from AiVision.assistant import resources
    from AiVision.features.tailgating.schema import TailgatingConfig

    cameras = [
        {"camera_id": 101, "shm_name": "camera_101", "name": "一号闸机", "department": "general_electric"},
        {"camera_id": 102, "shm_name": "camera_102", "name": "二号闸机", "department": "general_electric"},
        {"camera_id": 103, "shm_name": "camera_103", "name": "外部门闸机", "department": "research_institute"},
    ]
    configurations = {camera["camera_id"]: TailgatingConfig(enable=True).model_dump(mode="json") for camera in cameras}
    manager = Mock()
    manager.list_cameras.side_effect = lambda department: [item for item in cameras if item["department"] == department]
    manager.get_camera.side_effect = lambda key: next(
        (item for item in cameras if key in (item["camera_id"], item["shm_name"])), None,
    )
    monkeypatch.setattr(resources, "camera_config_manager", manager)
    config_manager = Mock()
    config_manager.get_config.side_effect = lambda _spec, key: {
        "camera": next(item for item in cameras if item["camera_id"] == key),
        "config": deepcopy(configurations[key]),
    }

    def save(_spec, key, config, **_kwargs):
        camera = manager.get_camera(key)
        configurations[camera["camera_id"]] = deepcopy(config)

    config_manager.save_config.side_effect = save
    monkeypatch.setattr(resources, "feature_config_manager", config_manager)
    user = {"role": "admin", "feature_access": {"general_electric": ["tailgating"], "research_institute": ["tailgating"]}}
    catalog = resources.ConfigurationCatalog(user, "general_electric")
    return SimpleNamespace(module=resources, catalog=catalog, cameras=cameras, configurations=configurations,
                           config_manager=config_manager, user=user)


def test_parameter_search_returns_schema_and_recovery_hint_without_changing_camera_matches(feature_catalog_case):
    case = feature_catalog_case
    result = case.catalog.find(kind="feature", department="通用电气事业部", feature="tailgating", query="人体置信度配置值")
    assert result["items"] == [] and result["total"] == 0
    assert result["configuration_scope"] == "camera"
    schema = result["schema_definition"]
    value_schema = schema["$defs"]["TailgatingValue"]
    field = value_schema["properties"]["threshold"]
    assert field["title"] == "人体检测置信度" and "人体置信度配置值" in field["description"]
    assert field["minimum"] == 0.01 and field["maximum"] == 1
    assert schema["additionalProperties"] is False and value_schema["additionalProperties"] is False
    assert "query" in result["search_hint"] and "摄像头" in result["search_hint"]
    assert "参数" in result["search_hint"]
    case.config_manager.get_config.assert_not_called()
    case.config_manager.save_config.assert_not_called()


def test_feature_discovery_keeps_department_feature_and_name_filters(feature_catalog_case):
    case = feature_catalog_case
    result = case.catalog.find(kind="feature", department="通用电气事业部", feature="tailgating")
    assert [item["key"] for item in result["items"]] == ["feature:tailgating:101", "feature:tailgating:102"]
    assert result["total"] == 2
    page = case.catalog.find(kind="feature", feature="tailgating", limit=1)
    assert len(page["items"]) == 1 and page["total"] == 2 and page["next_offset"] == 1
    named = case.catalog.find(kind="feature", department="general_electric", feature="tailgating", query="一号闸机")
    assert len(named["items"]) == 1 and named["items"][0]["identifier"] == "camera_101"
    outside = case.catalog.find(kind="feature", department="research_institute", feature="tailgating")
    assert outside["items"] == [] and "schema_definition" not in outside
    case.user["feature_access"]["general_electric"] = []
    forbidden = case.catalog.find(kind="feature", feature="tailgating")
    assert forbidden["items"] == [] and "schema_definition" not in forbidden


def test_schema_in_search_results_still_hides_credential_fields(feature_catalog_case, monkeypatch):
    from pydantic import BaseModel, Field

    class PrivateValue(BaseModel):
        threshold: float = 0.5
        api_key: str = "fixture-credential-sentinel"

    class PrivateConfig(BaseModel):
        value: PrivateValue = Field(default_factory=PrivateValue)
        password: str

    case = feature_catalog_case
    monkeypatch.setattr(case.module, "get_spec", lambda _name: SimpleNamespace(config_schema=PrivateConfig))
    result = case.catalog.find(kind="feature", feature="tailgating", query="人体置信度")
    schema = result["schema_definition"]
    assert "password" not in schema["properties"] and "password" not in schema.get("required", [])
    assert set(schema["$defs"]["PrivateValue"]["properties"]) == {"threshold"}
    assert "fixture-credential-sentinel" not in json.dumps(result)
    case.config_manager.get_config.assert_not_called()


@pytest.mark.parametrize("patch", [
    {"value": {"threshold": 0.0}}, {"value": {"threshold": 1.1}}, {"value": {"threshold": "0.8"}},
    {"value": {"threshold": float("nan")}}, {"value": {"人体置信度": 0.8}}, {"value.threshold": 0.8},
])
def test_parameter_metadata_keeps_strict_types_bounds_and_field_paths(feature_catalog_case, patch):
    from pydantic import ValidationError

    case = feature_catalog_case
    resource = case.catalog.resolve("feature:tailgating:101")
    before = deepcopy(resource.config)
    with pytest.raises((ValidationError, ValueError)):
        resource.prepare(patch)
    assert resource.config == before
    case.config_manager.save_config.assert_not_called()


def test_resource_search_contract_distinguishes_parameter_and_camera_name():
    from AiVision.assistant.tools import ListArguments

    fields = ListArguments.model_json_schema()["properties"]
    assert "参数名" in fields["query"]["description"] and "留空" in fields["query"]["description"]
    assert "feature" in fields["kind"]["description"]
    assert "能力目录" in fields["department"]["description"]


@pytest.mark.parametrize("camera_count", [1, 2])
def test_parameter_request_can_recover_then_update_unique_target_or_ask_about_real_candidates(
    runtime_case, feature_catalog_case, monkeypatch, camera_count,
):
    from AiVision.assistant import tools as tool_module
    from AiVision.assistant.schema import ActionResponse

    case, feature = runtime_case, feature_catalog_case
    if camera_count == 1:
        feature.cameras.pop(1)
    before = deepcopy(feature.configurations)
    case.current.question = "通用电气事业部、非法闯闸功能，人体置信度配置值，改为0.8"
    monkeypatch.setattr(case.module, "AssistantTools", tool_module.AssistantTools)
    monkeypatch.setattr(tool_module, "assistant_service", case.service)
    actions = []
    case.service.actions.side_effect = lambda _turn_id: actions

    def begin(_turn_id, reference, config, delta):
        action = ActionResponse(id="action-1", resource=reference, status="executing", before=config, after=None,
                                changes=delta, detail="", created_at=datetime.now(timezone.utc))
        actions.append(action)
        return action, True

    def finish(_action_id, status, actual, detail):
        action = actions[-1]
        action.status, action.after, action.detail = status, actual, detail
        return action

    case.service.begin_action.side_effect = begin
    case.service.finish_action.side_effect = finish
    observed_revisions = []

    def tool_reply(action, arguments):
        return completion({"action": action, "arguments": arguments}), 0.1

    def respond(**kwargs):
        messages = kwargs["messages"]
        if "只判断当前用户请求" in messages[0]["content"]:
            return completion({"mode": "change", "operations": ["update_configurations"]}), 0.1
        last = messages[-1]["content"]
        if last.startswith("后台已查询当前能力和部门"):
            # 复现模型把参数当成摄像头名称的第一步，随后检查工具反馈是否足够纠正。
            return tool_reply("list_resources", {"kind": "feature", "department": "general_electric",
                                                "feature": "tailgating", "query": "人体置信度配置值"})
        data = json.loads(last.split("：", 1)[1])
        if "items" in data and not data["items"]:
            assert "参数" in data["search_hint"]
            assert "人体检测置信度" in json.dumps(data["schema_definition"], ensure_ascii=False)
            return tool_reply("list_resources", {"kind": "feature", "department": "general_electric", "feature": "tailgating"})
        if "items" in data and "key" in data["items"][0]:
            if len(data["items"]) > 1:
                names = "、".join(item["name"] for item in data["items"])
                return tool_reply("ask_user", {"question": f"人体置信度按摄像头保存。请选择：{names}；或明确是否修改全部。"})
            return tool_reply("read_configurations", {"resource_keys": [data["items"][0]["key"]]})
        if "items" in data:
            item = data["items"][0]
            observed_revisions.append(item["revision"])
            return tool_reply("update_configurations", {"changes": [{"resource_key": item["resource"]["key"],
                "expected_revision": item["revision"], "patch": {"value": {"threshold": 0.8}}}]})
        return completion({"action": "answer", "answer": "结束本轮"}), 0.1

    case.client.complete.side_effect = respond
    case.runtime._execute("session-1", 1, lambda: feature.user, None)
    assert case.service.finish.call_args.args[1] == "completed"
    answer = case.service.finish.call_args.args[2]
    if camera_count == 1:
        feature.config_manager.save_config.assert_called_once()
        saved = feature.config_manager.save_config.call_args
        assert saved.args[1] == "camera_101"
        assert saved.kwargs["expected_department"] == "general_electric"
        assert saved.kwargs["expected_values"] == before[101]
        assert observed_revisions and actions[0].changes == {"value": {"threshold": 0.8}}
        expected = deepcopy(before[101])
        expected["value"]["threshold"] = 0.8
        assert feature.configurations[101] == expected
        assert feature.configurations[102] == before[102] and feature.configurations[103] == before[103]
        assert actions[0].status == "saved" and "已保存配置" in answer
    else:
        feature.config_manager.save_config.assert_not_called()
        feature.config_manager.get_config.assert_not_called()
        case.service.begin_action.assert_not_called()
        assert "一号闸机" in answer and "二号闸机" in answer and "外部门闸机" not in answer
        assert "对应的资源" not in answer
