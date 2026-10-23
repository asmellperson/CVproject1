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
    {"target_context": {}, "mode": "chat", "operations": []}, {"target_context": {}, "mode": "query", "operations": [], "query_tool": "list_resources"},
    {"target_context": {}, "mode": "query", "query_tool": "capabilities"}, {"target_context": {}, "mode": "query", "query_tool": "read_configurations"},
    {"target_context": {}, "mode": "change", "operations": ["update_configurations", "bind_camera"]},
    {"target_context": {}, "mode": "chat"},
])
def test_valid_plans_follow_the_existing_schema(payload):
    from AiVision.assistant.responses import parse_plan
    from AiVision.assistant.schema import RequestPlan

    assert parse_plan(completion(payload)) == RequestPlan.model_validate(payload)


@pytest.mark.parametrize("payload, location, code", [
    ({"operations": []}, ["mode"], "missing"),
    ({"target_context": {}, "mode": "unknown"}, ["mode"], "literal_error"),
    ({"target_context": {}, "mode": "change", "operations": []}, [], "value_error"),
    ({"target_context": {}, "mode": "change"}, [], "value_error"),
    ({"target_context": {}, "mode": "chat", "operations": ["delete_camera"]}, [], "value_error"),
    ({"target_context": {}, "mode": "query", "operations": ["add_camera"]}, [], "value_error"),
    ({"target_context": {}, "mode": "change", "operations": ["delete_camera", "delete_camera"]}, [], "value_error"),
    ({"target_context": {}, "mode": "change", "operations": ["run_sql"]}, ["operations", 0], "literal_error"),
    ({"target_context": {}, "mode": "chat", "operations": ""}, ["operations"], "list_type"),
    ({"target_context": {}, "mode": "query"}, [], "value_error"),
    ({"target_context": {}, "mode": "query", "query_tool": "delete_camera"}, ["query_tool"], "literal_error"),
    ({"target_context": {}, "mode": "chat", "query_tool": "capabilities"}, [], "value_error"),
    ({"target_context": {}, "mode": "change", "operations": ["delete_camera"], "query_tool": "capabilities"}, [], "value_error"),
    ({"target_context": {}, "mode": "chat", "answer": "你好"}, ["<额外字段>"], "extra_forbidden"),
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
        return {"resource": {"key": "camera:1"}, "status": "saved", "after": {"fps": 8}}

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
    case.client.complete.side_effect = [(completion(invalid), 0.1), (completion({"target_context": {}, "mode": "chat"}), 0.1)]
    assert case.plan().mode == "chat"
    assert case.client.complete.call_count == 2
    first, second = [call.kwargs for call in case.client.complete.call_args_list]
    assert len(first["messages"]) == 2 and len(second["messages"]) == 3
    assert '"required": ["mode"]' in second["messages"][0]["content"]
    correction = second["messages"][-1]["content"]
    assert "校验错误" in correction and "完整 JSON" in correction
    assert ("json_invalid" if isinstance(invalid, str) else "missing") in correction
    assert first["json_mode"] and second["json_mode"]
    assert first["max_tokens"] == second["max_tokens"] == case.module.settings.runtime.assistant_plan_max_tokens
    assert first["response_schema"] == second["response_schema"]
    assert first["response_schema"]["additionalProperties"] is False
    case.tools.run.assert_not_called()


def test_failed_correction_stops_before_any_business_tool(runtime_case):
    from AiVision.assistant.responses import PlanFormatError

    case = runtime_case
    case.client.complete.side_effect = [(completion({"target_context": {}, "mode": "bad"}), 0.1)] * 3
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
        return completion({"target_context": {}, "mode": "wrong"} if case.client.complete.call_count == 1 else {"target_context": {},
            "mode": "query", "query_tool": "list_resources"}), 1.0

    case.client.complete.side_effect = respond
    assert case.plan().mode == "query"
    assert [call.kwargs["timeout"] for call in case.client.complete.call_args_list] == [10.0, 4.0]


@pytest.mark.parametrize("valid_reply", [True, False])
def test_exhausted_planning_budget_does_not_issue_another_request(runtime_case, valid_reply):
    from AiVision.connectors.qwen.client import QwenTimeoutError

    case = runtime_case

    def late_reply(**_kwargs):
        case.clock.now += 10
        return completion({"target_context": {}, "mode": "chat" if valid_reply else "wrong"}), 10.0

    case.client.complete.side_effect = late_reply
    with pytest.raises(QwenTimeoutError):
        case.plan()
    assert case.client.complete.call_count == 1


@pytest.mark.parametrize("cancel_at", ["before", "after_response", "before_retry", "after_retry_response", "stopping"])
def test_cancellation_prevents_followup_requests_and_tools(runtime_case, cancel_at):
    case = runtime_case
    case.client.complete.return_value = (completion({"target_context": {}, "mode": "bad"}), 0.1)
    if cancel_at == "before":
        case.service.cancelled.return_value = True
    elif cancel_at == "after_response":
        def cancelled_reply(**_kwargs):
            case.service.cancelled.return_value = True
            return completion({"target_context": {}, "mode": "bad"}), 0.1
        case.client.complete.side_effect = cancelled_reply
    elif cancel_at == "after_retry_response":
        def cancelled_retry(**_kwargs):
            if case.client.complete.call_count == 2:
                case.service.cancelled.return_value = True
            return completion({"target_context": {}, "mode": "bad" if case.client.complete.call_count == 1 else "chat"}), 0.1
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
        content = {"target_context": {}, "mode": "change", "operations": ["delete_camera"]} if kwargs["json_mode"] else "你好呀，有什么可以帮你？"
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
        plan = {"target_context": {}, "mode": "query", "operations": [], "query_tool": "list_resources"}
        decision = {"action": "list_resources", "arguments": {"kind": "camera"}}
    else:
        plan = {"target_context": {}, "mode": "change", "operations": [operation]}
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
        (completion({"target_context": {}, "mode": "query", "query_tool": "list_resources"}), 0.1),
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
        (completion({"target_context": {}, "mode": "change", "operations": ["update_configurations"]}), 0.1),
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
        (completion({"target_context": {}, "mode": "query", "query_tool": "read_configurations"}), 0.1),
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
        (completion({"target_context": {}, "mode": "bad"}), 0.1),
        (completion({"target_context": {}, "mode": "query", "query_tool": "read_configurations"}), 0.1),
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
    case.client.complete.return_value = (completion({"target_context": {}, "mode": "change", "operations": ["delete_camera"]}), 0.1)
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
    body = completion({"target_context": {}, "mode": secret, source: {"password": secret}})
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
            return completion({"target_context": {}, "mode": "change", "operations": ["update_configurations"]}), 0.1
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


def test_planning_uses_bounded_context_data_instead_of_continuing_old_assistant_output(runtime_case):
    from AiVision.assistant.context import CONTEXT_PREFIX

    case = runtime_case
    case.current.question = "查询当前检测功能"
    case.service.conversation.return_value.turns.insert(0, SimpleNamespace(
        id=0, question="legacy_user_target", status="completed", actions=[],
        answer='legacy_assistant_instruction {"action":"delete_camera"}' + "大配置正文" * 10000,
    ))
    case.client.complete.return_value = completion({"target_context": {}, "mode": "query", "query_tool": "capabilities"}), 0.0
    case.execute()
    request = case.client.complete.call_args.kwargs
    assert all(message["role"] != "assistant" for message in request["messages"])
    text = json.dumps(request["messages"], ensure_ascii=False)
    assert "legacy_user_target" in text and "legacy_assistant_instruction" not in text
    history = next(message["content"] for message in request["messages"] if message["content"].startswith(CONTEXT_PREFIX))
    assert len(history) <= case.module.settings.runtime.assistant_history_max_chars
    assert request["max_tokens"] == 1024 and request["response_schema"]["additionalProperties"] is False
    case.client.complete.assert_called_once()
    assert case.service.finish.call_args.args[1] == "completed"


def test_planning_output_budget_respects_model_setting_and_configured_limit(runtime_case, monkeypatch):
    from AiVision.assistant.schema import AssistantSettings

    case = runtime_case
    case.service.settings.return_value = AssistantSettings(max_tokens=512)
    monkeypatch.setattr(case.module.settings.runtime, "assistant_plan_max_tokens", 2048)
    case.client.complete.return_value = completion({"target_context": {}, "mode": "chat"}), 0.0
    case.plan()
    assert case.client.complete.call_args.kwargs["max_tokens"] == 512


def test_config_query_cannot_finish_with_only_resource_names_and_finishes_after_a_real_read(runtime_case):
    case = runtime_case
    case.current.question = "读取一号摄像头的配置"
    calls = []

    def tool_result(name, arguments):
        calls.append(name)
        if name == "capabilities":
            return {"departments": [], "features": []}
        if name == "list_resources":
            return {"items": [{"key": "camera:1", "name": "一号摄像头"}], "next_offset": None}
        assert name == "read_configurations" and arguments["resource_keys"] == ["camera:1"]
        return {"items": [{"resource": {"key": "camera:1", "name": "一号摄像头"}, "config": {"fps": 8}}]}

    case.tools.run.side_effect = tool_result
    case.client.complete.side_effect = [
        (completion({"target_context": {}, "mode": "query", "query_tool": "read_configurations"}), 0.0),
        (completion({"action": "list_resources", "arguments": {}}), 0.0),
        (completion({"action": "answer", "answer": "列出名字就结束"}), 0.0),
        (completion({"action": "read_configurations", "arguments": {"resource_keys": ["camera:1"]}}), 0.0),
    ]
    case.execute()
    assert calls == ["capabilities", "list_resources", "read_configurations"]
    reminder = case.client.complete.call_args_list[3].kwargs["messages"][-1]["content"]
    assert "实际配置" in reminder and "camera:1" in reminder
    status, answer = case.service.finish.call_args.args[1:]
    assert status == "completed" and '"fps": 8' in answer and "列出名字就结束" not in answer
    # 读取成功即可由后端返回，不再依赖一次可能超时或说错结果的模型收尾。
    assert case.client.complete.call_count == 4
    business_schema = case.client.complete.call_args.kwargs["response_schema"]
    assert "delete_camera" not in business_schema["properties"]["action"]["enum"]


def test_config_query_refuses_success_if_model_repeatedly_ends_before_reading(runtime_case):
    case = runtime_case
    case.client.complete.side_effect = [
        (completion({"target_context": {}, "mode": "query", "query_tool": "read_configurations"}), 0.0),
        (completion({"action": "list_resources", "arguments": {}}), 0.0),
        (completion({"action": "answer", "answer": "已查到配置"}), 0.0),
        (completion({"action": "answer", "answer": "已查到配置"}), 0.0),
    ]
    case.execute()
    assert case.client.complete.call_count == 4
    assert case.service.finish.call_args.args[1] == "failed"
    assert "已查到配置" not in case.service.finish.call_args.args[2]


def test_config_query_requires_all_found_targets_and_complete_pagination():
    from AiVision.assistant.outcomes import ExecutionOutcome
    from AiVision.assistant.schema import RequestPlan

    outcome = ExecutionOutcome(RequestPlan(mode="query", query_tool="read_configurations", target_context={}))
    outcome.record("list_resources", {"items": [{"key": "camera:1"}, {"key": "camera:2"}], "next_offset": 2})
    outcome.record("read_configurations", {"items": [
        {"resource": {"key": "camera:1", "name": "一号"}, "config": {"fps": 8}},
    ]})
    assert not outcome.query_ready and outcome.query_answer()[0] == "failed"
    outcome.record("list_resources", {"items": [], "next_offset": None})
    assert not outcome.query_ready and "camera:2" in outcome.query_requirement()
    outcome.record("read_configurations", {"items": [
        {"resource": {"key": "camera:2", "name": "二号"}, "config": {"fps": 10}},
    ]})
    assert outcome.query_ready and outcome.query_answer()[0] == "completed"


@pytest.mark.parametrize("cancel_after", ["capabilities", "read_configurations"])
def test_query_fast_return_still_checks_cancellation_after_the_tool(runtime_case, cancel_after):
    case = runtime_case

    def result(name, _arguments):
        if name == cancel_after:
            case.service.cancelled.return_value = True
        if name == "capabilities":
            return {"departments": [], "features": []}
        return {"items": [{"resource": {"key": "camera:1", "name": "一号"}, "config": {"fps": 8}}]}

    case.tools.run.side_effect = result
    case.client.complete.side_effect = [
        (completion({"target_context": {}, "mode": "query", "query_tool": cancel_after}), 0.0),
        (completion({"action": "read_configurations", "arguments": {"resource_keys": ["camera:1"]}}), 0.0),
    ]
    with pytest.raises(case.module.TaskCancelled):
        case.execute()
    case.service.finish.assert_not_called()
    assert case.runtime.memory.get("session-1", {1}) is None


def test_context_budget_keeps_whole_newest_requests_and_skips_audit_configuration_values():
    from AiVision.assistant.context import CONTEXT_PREFIX, context_messages
    from AiVision.assistant.schema import ResourceReference

    action = SimpleNamespace(resource=ResourceReference(key="camera:1", kind="camera", name="一号", department=None),
                             status="saved", before={"private_config_marker": "x" * 10000}, after={"fps": 8})
    turns = [SimpleNamespace(id=i, question=str(i) + "问" * 300, answer="答" * 3000,
                             status="completed", actions=[action]) for i in range(10)]
    messages = context_messages(turns, count=6, max_chars=1800)
    assert len(messages[0]["content"]) <= 1800
    data = json.loads(messages[0]["content"][len(CONTEXT_PREFIX):])
    assert data["history_truncated"] and data["recent_turns"][-1]["turn_id"] == 9
    assert all(len(item["request"]) == 301 for item in data["recent_turns"])
    assert "private_config_marker" not in messages[0]["content"]
    assert context_messages(turns, count=0, max_chars=1800) == []


def test_context_memory_requires_visible_anchor_and_expires_without_leaking_other_sessions(monkeypatch):
    from AiVision.assistant import context as module
    from AiVision.assistant.outcomes import ExecutionOutcome
    from AiVision.assistant.schema import RequestPlan

    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(module, "MAX_CONTEXT_SESSIONS", 2)
    outcome = ExecutionOutcome(RequestPlan(mode="query", query_tool="read_configurations", target_context={}))
    outcome.record("read_configurations", {"items": [{"resource": {"key": "camera:1", "name": "一号"},
        "revision": "version_must_not_be_reused", "config": {"private_marker": "fixture-only"}}]})
    memory = module.ConversationMemory()
    memory.remember("first", 1, "查询一号", outcome)
    state = memory.get("first", {1})
    assert state["last_read_resources"][0]["key"] == "camera:1"
    assert "private_marker" not in json.dumps(state) and "version_must_not_be_reused" not in json.dumps(state)
    assert memory.get("other", {1}) is None
    assert memory.get("first", set()) is None
    memory.remember("first", 1, "查询一号", outcome)
    clock.now += module.CONTEXT_TTL_SECONDS
    assert memory.get("first", {1}) is None
    for key in ("first", "second", "third"):
        memory.remember(key, 1, "查询一号", outcome)
    assert memory.get("first", {1}) is None and memory.get("third", {1}) is not None


@pytest.mark.parametrize("payload", [
    {"mode": "query", "query_tool": "read_configurations"},
    {"mode": "change", "operations": ["update_configurations"]},
    {"mode": "query", "query_tool": "read_configurations", "target_context": {
        "references": [{"kind": "alias", "text": "门口甲", "unregistered": True}]}},
    {"mode": "query", "query_tool": "read_configurations", "target_context": {
        "references": [{"kind": "guessed", "text": "门口甲"}]}},
])
def test_business_target_contract_is_required_and_does_not_accept_unregistered_fields(payload):
    from AiVision.assistant.responses import PlanFormatError, parse_plan

    with pytest.raises(PlanFormatError):
        parse_plan(completion(payload))


def target_plan(*, text=None, kind="alias", bindings=None):
    from AiVision.assistant.schema import RequestPlan

    return RequestPlan(mode="query", query_tool="read_configurations", target_context={
        "references": [{"kind": kind, "text": text}] if text is not None else [], "bindings": bindings or [],
    })


def target_resource(number=1, name=None, department="general_electric"):
    return {"key": f"feature:tailgating:{number}", "kind": "feature", "name": name or f"闸机{number}",
            "department": department, "feature": "tailgating", "identifier": f"camera_{number}"}


def target_outcome(plan, *resources):
    from AiVision.assistant.outcomes import ExecutionOutcome

    outcome = ExecutionOutcome(plan)
    outcome.record("read_configurations", {"items": [
        {"resource": resource, "config": {"private-value": "not-retained"}, "revision": "not-retained"}
        for resource in resources]})
    return outcome


def test_verified_alias_keeps_its_origin_across_target_switches_and_expires_independently(monkeypatch):
    from AiVision.assistant import context as module

    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock.now)
    memory = module.ConversationMemory()
    question = "请记住：门口甲对应闸机1。查询这台摄像头的配置"
    plan = target_plan(bindings=[{"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}])
    memory.remember("first", 1, question, target_outcome(plan, target_resource()))
    state = memory.get("first", {1})
    assert state["target_bindings"][0]["resource"] == target_resource()
    assert state["target_bindings"][0]["turn_id"] == 1
    assert "not-retained" not in json.dumps(state) and "evidence" not in json.dumps(state)
    clock.now += 50
    memory.remember("first", 2, "查询闸机2", target_outcome(target_plan(), target_resource(2)), previous=state)
    switched = memory.get("first", {1, 2})
    assert switched["last_read_resources"] == [target_resource(2)]
    assert switched["target_bindings"][0]["resource"] == target_resource()
    assert memory.get("other", {1, 2}) is None
    assert memory.get("first", {2})["target_bindings"] == []
    clock.now = 100 + module.CONTEXT_TTL_SECONDS
    assert memory.get("first", {1, 2})["target_bindings"] == []


@pytest.mark.parametrize("proposal, question, resources", [
    ({"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}, "查询闸机1", [target_resource()]),
    ({"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}, "不要把门口甲对应闸机1", [target_resource()]),
    ({"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}, "门口甲对应闸机1", [target_resource(2)]),
    ({"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}, "门口甲对应闸机1", [target_resource(), target_resource(2, "闸机1")]),
    ({"alias": "门口甲", "target": "闸机1", "evidence": "门口甲与闸机1无关"}, "门口甲与闸机1无关", [target_resource()]),
    ({"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}, "门口甲对应闸机1是错误的", [target_resource()]),
    ({"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}, "例如：门口甲对应闸机1", [target_resource()]),
    ({"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}, "门口甲对应闸机10", [target_resource()]),
    ({"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机10"}, "门口甲对应闸机10", [target_resource()]),
])
def test_alias_is_not_saved_from_fabricated_negated_missing_or_ambiguous_evidence(proposal, question, resources):
    from AiVision.assistant.context import ConversationMemory

    memory = ConversationMemory()
    memory.remember("first", 1, question, target_outcome(target_plan(bindings=[proposal]), *resources))
    assert memory.get("first", {1})["target_bindings"] == []


def test_alias_rebinding_requires_a_new_declaration_and_verified_read():
    from AiVision.assistant.context import ConversationMemory

    memory = ConversationMemory()
    first = target_plan(bindings=[{"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}])
    memory.remember("first", 1, "门口甲对应闸机1", target_outcome(first, target_resource()))
    second = target_plan(bindings=[{"alias": "门口甲", "target": "闸机2", "evidence": "门口甲对应闸机2"}])
    memory.remember("first", 2, "门口甲对应闸机2", target_outcome(second, target_resource(2)), previous=memory.get("first", {1}))
    state = memory.get("first", {1, 2})
    assert len(state["target_bindings"]) == 1
    assert state["target_bindings"][0]["resource"] == target_resource(2)
    assert state["target_bindings"][0]["turn_id"] == 2


def test_alias_cannot_be_substituted_with_the_most_recent_or_cross_department_target():
    from AiVision.assistant.targets import TargetClarification, TargetPolicy
    from AiVision.assistant.tools import ReadArguments

    state = {"last_read_resources": [target_resource(2)],
             "target_bindings": [{"alias": "门口甲", "resource": target_resource()}]}
    policy = TargetPolicy("读取门口甲的配置", target_plan(text="门口甲"), state)
    policy.check("read_configurations", ReadArguments(resource_keys=[target_resource()["key"]]))
    with pytest.raises(TargetClarification):
        policy.check("read_configurations", ReadArguments(resource_keys=[target_resource(2)["key"]]))
    other = target_resource(3, department="other")
    policy.observe("list_resources", {"items": [other]})
    with pytest.raises(TargetClarification):
        policy.check("read_configurations", ReadArguments(resource_keys=[other["key"]]))


@pytest.mark.parametrize("text, kind", [
    ("这台摄像头", "named"), ("通用电气事业部这台摄像头", "named"),
    ("通用电气事业部的这台摄像头", "named"), ("通用电气事业部这台摄像头", "context"),
    ("通用电气事业部", "named"), ("通用电气事业部闸机1", "named"),
    ("通用电气事业部的闸机1", "named"), ("门口甲", "named"),
    ("通用电气事业部门口甲", "alias"),
])
def test_literal_scope_and_context_resolve_to_the_current_declared_target(text, kind):
    from AiVision.assistant.targets import TargetClarification, TargetPolicy
    from AiVision.assistant.tools import ReadArguments

    declaration = {"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}
    plan = target_plan(text=text, kind=kind, bindings=[declaration])
    policy = TargetPolicy(f"门口甲对应闸机1。查询{text}的配置", plan,
                          {"last_read_resources": [target_resource(2)]})
    policy.observe("list_resources", {"items": [target_resource(), target_resource(2)]})
    policy.check("read_configurations", ReadArguments(resource_keys=[target_resource()["key"]]))
    with pytest.raises(TargetClarification):
        policy.check("read_configurations", ReadArguments(resource_keys=[target_resource(2)["key"]]))


def test_department_qualifier_disambiguates_identical_names_without_authorizing_other_departments():
    from AiVision.assistant.targets import TargetClarification, TargetPolicy
    from AiVision.assistant.tools import ReadArguments

    question = "门口甲对应闸机1。查询通用电气事业部这台摄像头的配置"
    plan = target_plan(text="通用电气事业部这台摄像头", kind="named", bindings=[
        {"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}])
    policy = TargetPolicy(question, plan)
    other = target_resource(3, "闸机1", "research_institute")
    policy.observe("list_resources", {"items": [target_resource(), other]})
    policy.check("read_configurations", ReadArguments(resource_keys=[target_resource()["key"]]))
    with pytest.raises(TargetClarification):
        policy.check("read_configurations", ReadArguments(resource_keys=[other["key"]]))


def test_a_recognized_department_does_not_make_an_unknown_name_or_singular_ambiguity_valid():
    from AiVision.assistant.targets import TargetClarification, TargetPolicy
    from AiVision.assistant.tools import ReadArguments

    for text in ("通用电气事业部未知门口", "福达新材院这台摄像头", "通用电气事业部这台摄像头"):
        declarations = [{"alias": "门口甲", "target": "闸机1", "evidence": "门口甲对应闸机1"}]
        question = f"门口甲对应闸机1。查询{text}的配置"
        if text == "通用电气事业部这台摄像头":
            declarations.append({"alias": "门口乙", "target": "闸机2", "evidence": "门口乙对应闸机2"})
            question = "门口乙对应闸机2。" + question
        policy = TargetPolicy(question, target_plan(text=text, kind="named", bindings=declarations))
        policy.observe("list_resources", {"items": [target_resource(), target_resource(2)]})
        with pytest.raises(TargetClarification):
            policy.check("read_configurations", ReadArguments(resource_keys=[target_resource()["key"]]))


def test_scope_only_metadata_cannot_authorize_cached_resources_without_a_target_or_search():
    from AiVision.assistant.targets import TargetClarification, TargetPolicy
    from AiVision.assistant.tools import ReadArguments

    policy = TargetPolicy("查询通用电气事业部的配置", target_plan(text="通用电气事业部", kind="named"),
                          {"last_read_resources": [target_resource()]})
    with pytest.raises(TargetClarification):
        policy.check("read_configurations", ReadArguments(resource_keys=[target_resource()["key"]]))


def test_scope_only_reference_still_uses_a_mentioned_verified_alias_instead_of_the_recent_target():
    from AiVision.assistant.targets import TargetClarification, TargetPolicy
    from AiVision.assistant.tools import ReadArguments

    policy = TargetPolicy("查询通用电气事业部门口甲的配置", target_plan(text="通用电气事业部", kind="named"),
                          {"last_read_resources": [target_resource(2)],
                           "target_bindings": [{"alias": "门口甲", "resource": target_resource()}]})
    policy.check("read_configurations", ReadArguments(resource_keys=[target_resource()["key"]]))
    with pytest.raises(TargetClarification):
        policy.check("read_configurations", ReadArguments(resource_keys=[target_resource(2)["key"]]))


def test_current_literal_target_takes_priority_when_context_reference_comes_first():
    from AiVision.assistant.schema import RequestPlan
    from AiVision.assistant.targets import TargetClarification, TargetPolicy
    from AiVision.assistant.tools import ReadArguments

    plan = RequestPlan(mode="query", query_tool="read_configurations", target_context={"references": [
        {"kind": "context", "text": "这台摄像头"}, {"kind": "named", "text": "闸机1"}]})
    policy = TargetPolicy("闸机1，查询这台摄像头的配置", plan, {"last_read_resources": [target_resource(2)]})
    policy.observe("list_resources", {"items": [target_resource(), target_resource(2)]})
    policy.check("read_configurations", ReadArguments(resource_keys=[target_resource()["key"]]))
    with pytest.raises(TargetClarification):
        policy.check("read_configurations", ReadArguments(resource_keys=[target_resource(2)["key"]]))


def test_singular_camera_reference_does_not_count_the_explicit_binding_parent_as_a_second_camera():
    from AiVision.assistant.schema import RequestPlan
    from AiVision.assistant.targets import TargetPolicy
    from AiVision.assistant.tools import BindCameraArguments

    plan = RequestPlan(mode="change", operations=["bind_camera"], target_context={"references": [
        {"kind": "named", "text": "闸机1"}, {"kind": "context", "text": "这台摄像头"},
        {"kind": "named", "text": "保安室甲"}]})
    policy = TargetPolicy("闸机1，把这台摄像头加入保安室甲", plan)
    policy.observe("list_resources", {"items": [
        {"key": "camera:1", "kind": "camera", "name": "闸机1", "department": "general_electric"},
        {"key": "guard:1", "kind": "guard", "name": "保安室甲", "department": "general_electric"}]})
    policy.check("bind_camera", BindCameraArguments(camera_key="camera:1", parent_key="guard:1"))


def test_single_native_camera_configuration_remains_a_valid_visible_context():
    from AiVision.assistant.targets import TargetPolicy
    from AiVision.assistant.tools import ReadArguments

    resource = {"key": "guard_roi:1:2", "kind": "guard_roi", "name": "闸机1 ROI", "department": "general_electric"}
    policy = TargetPolicy("查询这台摄像头的 ROI", target_plan(text="这台摄像头", kind="context"),
                          {"last_read_resources": [resource]})
    policy.check("read_configurations", ReadArguments(resource_keys=[resource["key"]]))


def test_undo_target_must_match_the_explicit_alias_even_with_a_valid_audit():
    from AiVision.assistant.targets import TargetClarification, TargetPolicy

    policy = TargetPolicy("撤销门口甲的配置修改", target_plan(text="门口甲"),
                          {"target_bindings": [{"alias": "门口甲", "resource": target_resource()}]})
    policy.check_audited_resource(target_resource())
    with pytest.raises(TargetClarification):
        policy.check_audited_resource(target_resource(2))


@pytest.mark.parametrize("kind", ["alias", "named", "context", "pending"])
def test_unverified_alias_is_not_authorized_by_relabelling_its_reference(kind):
    from AiVision.assistant.targets import TargetClarification, TargetPolicy
    from AiVision.assistant.tools import ReadArguments

    policy = TargetPolicy("查询未知甲的配置", target_plan(text="未知甲", kind=kind),
                          {"last_read_resources": [target_resource()]})
    with pytest.raises(TargetClarification):
        policy.check("read_configurations", ReadArguments(resource_keys=[target_resource()["key"]]))


def test_missing_reference_metadata_does_not_authorize_a_cached_target():
    from AiVision.assistant.targets import TargetClarification, TargetPolicy
    from AiVision.assistant.tools import ReadArguments

    policy = TargetPolicy("查询未知甲的配置", target_plan(), {"last_read_resources": [target_resource()]})
    with pytest.raises(TargetClarification):
        policy.check("read_configurations", ReadArguments(resource_keys=[target_resource()["key"]]))


@pytest.mark.parametrize("text, allowed", [("它", False), ("这台摄像头", False), ("它们", True)])
def test_singular_context_reference_does_not_choose_between_multiple_targets(text, allowed):
    from AiVision.assistant.targets import TargetClarification, TargetPolicy
    from AiVision.assistant.tools import ReadArguments

    policy = TargetPolicy(f"查询{text}的配置", target_plan(text=text, kind="context"),
                          {"last_read_resources": [target_resource(), target_resource(2)]})
    arguments = ReadArguments(resource_keys=[target_resource()["key"], target_resource(2)["key"]])
    if allowed:
        policy.check("read_configurations", arguments)
    else:
        with pytest.raises(TargetClarification):
            policy.check("read_configurations", arguments)


def test_binding_context_does_not_expose_internal_clock_or_configuration_values():
    from AiVision.assistant.context import CONTEXT_PREFIX, context_messages

    memory = {"target_bindings": [{"alias": "门口甲", "resource": target_resource(), "turn_id": 1, "confirmed_at": 100.0}]}
    encoded = context_messages([], count=6, max_chars=8000, memory=memory)[0]["content"]
    data = json.loads(encoded[len(CONTEXT_PREFIX):])
    assert data["task_context"]["target_bindings"][0]["alias"] == "门口甲"
    assert "confirmed_at" not in encoded
    assert memory["target_bindings"][0]["confirmed_at"] == 100.0


@pytest.mark.parametrize("evidence", ["门口甲对应闸机1", "闸机1的别名是门口甲", "把闸机1称为门口甲", "将闸机1叫作门口甲"])
def test_explicit_positive_naming_relations_can_be_verified(evidence):
    from AiVision.assistant.schema import TargetBindingProposal
    from AiVision.assistant.targets import verified_bindings

    proposal = TargetBindingProposal(alias="门口甲", target="闸机1", evidence=evidence)
    assert verified_bindings([proposal], evidence, [target_resource()]) == [{"alias": "门口甲", "resource": target_resource()}]


def test_context_budget_keeps_requested_alias_without_forwarding_all_other_bindings():
    from AiVision.assistant.context import CONTEXT_PREFIX, context_messages

    bindings = [{"alias": f"门口{number}", "resource": target_resource(number), "turn_id": number, "confirmed_at": 100.0}
                for number in range(10, 42)]
    message = context_messages([], count=6, max_chars=1500, memory={"target_bindings": bindings},
                               question="查询门口41的配置")[0]["content"]
    context = json.loads(message[len(CONTEXT_PREFIX):])
    assert len(message) <= 1500
    assert [item["alias"] for item in context["task_context"]["target_bindings"]] == ["门口41"]


def test_response_metadata_and_failure_logs_never_include_reasoning_or_response_content(runtime_case, caplog):
    from AiVision.assistant.responses import completion_metadata

    body = json.loads(completion("fixture-private-response", finish_reason="length"))
    body["choices"][0]["message"]["reasoning_content"] = "fixture-private-reasoning"
    body["usage"] = {"prompt_tokens": 550, "completion_tokens": 1024,
                     "completion_tokens_details": {"reasoning_tokens": 1000}}
    raw = json.dumps(body)
    metadata = completion_metadata(raw)
    assert metadata["finish_reason"] == "length" and metadata["has_thinking"]
    assert metadata["reasoning_tokens"] == 1000 and metadata["completion_tokens"] == 1024
    case = runtime_case
    case.client.complete.return_value = raw, 0.0
    with pytest.raises(case.module.QwenError):
        case.plan()
    assert "1024" in caplog.text and "length" in caplog.text
    assert "fixture-private-response" not in caplog.text and "fixture-private-reasoning" not in caplog.text


def change_policy(question, *, memory=None, references=()):
    from AiVision.assistant.changes import ChangePolicy
    from AiVision.assistant.schema import RequestPlan
    from AiVision.assistant.targets import TargetPolicy

    plan = RequestPlan(mode="change", operations=["update_configurations"],
                       target_context={"references": list(references)})
    return ChangePolicy(question, plan, TargetPolicy(question, plan, memory), memory)


def change_resource():
    from AiVision.assistant.resources import ConfigurationResource
    from AiVision.assistant.schema import ResourceReference
    from AiVision.features.tailgating.schema import TailgatingConfig

    return ConfigurationResource(ResourceReference(key="feature:tailgating:1", kind="feature", name="闸机1",
        department="general_electric", feature="tailgating"), TailgatingConfig, TailgatingConfig().model_dump(), Mock())


@pytest.mark.parametrize("question, patch", [
    ("闸机1的人体置信度改为0.8", {"value": {"threshold": 0.8}}),
    ("人体置信度配置值改为0.8，检测间隔改为0.2秒", {"value": {"threshold": 0.8, "cap_interval": 0.2}}),
    ("把 value.cap_interval 改为0.2", {"value": {"cap_interval": 0.2}}),
    ("人体置信度保持0.5", {"value": {"threshold": 0.5}}),
    ("当前人体置信度是0.5，检测间隔改为0.2", {"value": {"cap_interval": 0.2}}),
    ("当前人体置信度是0.5，只修改检测间隔为0.2", {"value": {"cap_interval": 0.2}}),
    ("人体置信度当前0.5，帮我调整检测间隔为0.2", {"value": {"cap_interval": 0.2}}),
])
def test_change_scope_accepts_only_explicit_requested_parameters(question, patch):
    change_policy(question).check_patch(change_resource(), patch)


@pytest.mark.parametrize("question, patch", [
    ("人体置信度改为0.8", {"value": {"threshold": 0.8, "cap_interval": 0.2}}),
    ("人体置信度改为0.8，不要改检测间隔", {"value": {"threshold": 0.8, "cap_interval": 0.2}}),
    ("人体置信度和检测间隔分别改为0.8和0.2", {"value": {"threshold": 0.8}}),
    ("把 max_threshold 改为0.8", {"value": {"threshold": 0.8}}),
    ("当前人体置信度是0.5，检测间隔改为0.2", {"value": {"threshold": 0.8, "cap_interval": 0.2}}),
    ("只修改检测间隔为0.2，别修改人体置信度", {"value": {"threshold": 0.8, "cap_interval": 0.2}}),
])
def test_change_scope_rejects_extra_missing_negated_or_unverified_parameters(question, patch):
    with pytest.raises(ValueError):
        change_policy(question).check_patch(change_resource(), patch)


def test_change_scope_uses_only_an_active_pending_request_for_a_short_reply():
    pending = {"pending_task": {"request": "人体置信度调低一点", "plan": {"mode": "change"}}}
    reference = [{"kind": "pending", "text": "就改为0.55"}]
    change_policy("就改为0.55", memory=pending, references=reference).check_patch(
        change_resource(), {"value": {"threshold": 0.55}})
    with pytest.raises(ValueError):
        change_policy("检测间隔改为0.2", memory=pending).check_patch(
            change_resource(), {"value": {"threshold": 0.8, "cap_interval": 0.2}})
    change_policy("检测间隔改为0.2", memory=pending,
                  references=[{"kind": "pending", "text": "检测间隔改为0.2"}]).check_patch(
                      change_resource(), {"value": {"cap_interval": 0.2}})


@pytest.mark.parametrize("question, submitted, next_offset, expected", [
    ("两台闸机的人体置信度都改为0.8", [1, 2], None, True),
    ("两台闸机的人体置信度都改为0.8", [1], None, False),
    ("全部闸机的人体置信度改为0.8", [1, 2], 2, False),
    ("全部闸机的人体置信度改为0.8", [1, 2], None, True),
])
def test_batch_scope_requires_complete_discovery_and_the_complete_target_set(question, submitted, next_offset, expected):
    policy = change_policy(question)
    items = [target_resource(number) for number in (1, 2)]
    policy.observe("list_resources", {"items": items, "total": 3 if next_offset else 2, "next_offset": next_offset},
                   {"kind": "feature", "feature": "tailgating", "query": "闸机", "offset": 0})
    changes = [SimpleNamespace(resource_key=target_resource(number)["key"]) for number in submitted]
    if expected:
        policy.check_targets(changes)
    else:
        with pytest.raises(ValueError):
            policy.check_targets(changes)


def test_batch_scope_does_not_treat_an_invented_narrow_search_as_all_targets():
    policy = change_policy("全部闸机的人体置信度改为0.8")
    policy.observe("list_resources", {"items": [target_resource()], "total": 1, "next_offset": None},
                   {"kind": "feature", "feature": "tailgating", "query": "闸机1"})
    with pytest.raises(ValueError):
        policy.check_targets([SimpleNamespace(resource_key=target_resource()["key"])])


def test_batch_scope_requires_continuous_pages_instead_of_only_the_last_page():
    policy = change_policy("所有闸机的人体置信度改为0.8")
    for offset, numbers, following in [(0, (1,), 1), (2, (3,), None)]:
        policy.observe("list_resources", {"items": [target_resource(number) for number in numbers],
            "total": 3, "next_offset": following}, {"kind": "feature", "feature": "tailgating", "query": "闸机", "offset": offset})
    changes = [SimpleNamespace(resource_key=target_resource(number)["key"]) for number in (1, 2, 3)]
    with pytest.raises(ValueError):
        policy.check_targets(changes)
    policy.observe("list_resources", {"items": [target_resource(2)], "total": 3, "next_offset": 2},
                   {"kind": "feature", "feature": "tailgating", "query": "闸机", "offset": 1})
    policy.check_targets(changes)


@pytest.mark.parametrize("recoverable", [True, False])
def test_only_recoverable_errors_of_the_same_tool_scope_can_be_resolved(recoverable):
    from AiVision.assistant.outcomes import ExecutionOutcome
    from AiVision.assistant.schema import RequestPlan

    outcome = ExecutionOutcome(RequestPlan(mode="change", operations=["update_configurations"], target_context={}))
    arguments = {"kind": "feature", "department": "general_electric"}
    outcome.record("list_resources", {"error": "本次查询未执行", "recoverable": recoverable}, arguments)
    outcome.record("capabilities", {})
    assert outcome.errors
    outcome.record("list_resources", {"items": [], "total": 0}, {"kind": "camera"})
    assert outcome.errors
    outcome.record("list_resources", {"items": [], "total": 0}, {**arguments, "feature": "tailgating"})
    assert bool(outcome.errors) is not recoverable


def test_batch_outcome_requires_a_verified_result_for_every_submitted_target():
    from AiVision.assistant.outcomes import ExecutionOutcome
    from AiVision.assistant.schema import RequestPlan

    outcome = ExecutionOutcome(RequestPlan(mode="change", operations=["update_configurations"], target_context={}))
    arguments = {"changes": [{"resource_key": "camera:1"}, {"resource_key": "camera:2"}]}
    first = {"resource_key": "camera:1", "resource_name": "一号", "status": "unchanged"}
    outcome.record("update_configurations", {"results": [first]}, arguments)
    assert outcome.pending == {"update_configurations"}
    second = {"resource_key": "camera:2", "resource_name": "二号", "status": "unchanged"}
    outcome.record("update_configurations", {"results": [first, second]}, arguments)
    assert not outcome.pending


@pytest.mark.parametrize("tool, arguments", [
    ("list_resources", {"kind": [], "department": {"invalid": True}}),
    ("read_configurations", {"resource_keys": None}),
    ("read_configurations", {"resource_keys": [1, {}, "camera:1"]}),
    ("update_configurations", {"changes": None}),
    ("update_configurations", {"changes": [True, {"resource_key": []}]}),
])
def test_error_bookkeeping_does_not_crash_on_rejected_invalid_tool_arguments(tool, arguments):
    from AiVision.assistant.outcomes import ExecutionOutcome
    from AiVision.assistant.schema import RequestPlan

    outcome = ExecutionOutcome(RequestPlan(mode="change", operations=["update_configurations"], target_context={}))
    outcome.record(tool, {"error": "参数不合法", "recoverable": True}, arguments)
    assert outcome.errors == ["参数不合法"]


def test_success_on_another_resource_does_not_resolve_a_failed_update():
    from AiVision.assistant.outcomes import ExecutionOutcome
    from AiVision.assistant.schema import RequestPlan

    outcome = ExecutionOutcome(RequestPlan(mode="change", operations=["update_configurations"], target_context={}))
    outcome.record("update_configurations", {"error": "尚未保存", "recoverable": True},
                   {"changes": [{"resource_key": "camera:1"}]})
    outcome.record("update_configurations", {"results": [{"resource_key": "camera:2", "resource_name": "二号",
                   "status": "unchanged"}]}, {"changes": [{"resource_key": "camera:2"}]})
    assert outcome.errors == ["尚未保存"]
    outcome.record("update_configurations", {"results": [
        {"resource_key": f"camera:{number}", "resource_name": str(number), "status": "unchanged"}
        for number in (1, 2)]}, {"changes": [{"resource_key": f"camera:{number}"} for number in (1, 2)]})
    assert not outcome.errors and not outcome.pending


@pytest.mark.parametrize("name", ["两台入口", "全部入口"])
def test_words_inside_a_verified_resource_name_are_not_batch_quantifiers(name):
    policy = change_policy(f"把{name}的人体置信度改为0.8", references=[{"kind": "named", "text": name}])
    result = {"items": [target_resource(name=name)], "total": 1, "next_offset": None}
    policy.target_policy.observe("list_resources", result)
    policy.observe("list_resources", result, {"kind": "feature", "feature": "tailgating", "query": name})
    policy.check_targets([SimpleNamespace(resource_key=target_resource()["key"])])


def test_schema_titles_and_array_parameters_are_checked_without_changing_the_business_schema():
    from pydantic import BaseModel, Field
    from AiVision.assistant.resources import ConfigurationResource

    class Parameters(BaseModel):
        duration: float = Field(10, title="驻留时长", gt=0)

    original = change_resource()
    resource = ConfigurationResource(original.reference, Parameters, Parameters().model_dump(), Mock())
    change_policy("驻留时长改为20").check_patch(resource, {"duration": 20})
    change_policy("ROI改为空区域").check_patch(original, {"value": {"roi_pos": []}})
    with pytest.raises(ValueError):
        change_policy("驻留时长改为20").check_patch(resource, {"duration": 20, "extra": 1})
    assert Parameters.model_json_schema()["properties"]["duration"]["exclusiveMinimum"] == 0


@pytest.mark.parametrize("status", ["failed", "unknown", "changed", "executing"])
def test_unverified_batch_item_remains_failed_after_unrelated_queries(status):
    from AiVision.assistant.outcomes import ExecutionOutcome
    from AiVision.assistant.schema import RequestPlan

    outcome = ExecutionOutcome(RequestPlan(mode="change", operations=["update_configurations"], target_context={}))
    outcome.record("list_resources", {"items": [{"key": "camera:2", "name": "二号摄像头"}]})
    outcome.record("update_configurations", {"results": [
        {"resource_key": "camera:1", "resource_name": "一号摄像头", "status": "unchanged"},
        {"resource": {"key": "camera:2"}, "status": status, "detail": "尚未确认保存"},
    ]}, {"changes": [{"resource_key": "camera:1"}, {"resource_key": "camera:2"}]})
    outcome.record("capabilities", {})
    actual_status, answer = outcome.answer([])
    assert actual_status == "failed" and "二号摄像头" in answer and outcome.errors


@pytest.mark.parametrize("prefix", ["示例：", "例如", "假设"])
def test_parameters_in_examples_do_not_authorize_extra_writes(prefix):
    policy = change_policy(f"{prefix}检测间隔改为0.2；实际把人体置信度改为0.8")
    policy.check_patch(change_resource(), {"value": {"threshold": 0.8}})
    with pytest.raises(ValueError):
        policy.check_patch(change_resource(), {"value": {"threshold": 0.8, "cap_interval": 0.2}})


@pytest.mark.parametrize("first, corrected", [
    ("通用电气事业部", "general_electric"), ("general_electric", "通用电气事业部"),
])
def test_corrected_search_uses_canonical_department_identity_for_error_recovery(first, corrected):
    from AiVision.assistant.outcomes import ExecutionOutcome
    from AiVision.assistant.schema import RequestPlan

    outcome = ExecutionOutcome(RequestPlan(mode="query", query_tool="read_configurations", target_context={}))
    outcome.record("list_resources", {"error": "缺少功能", "recoverable": True}, {"kind": "feature", "department": first})
    outcome.record("list_resources", {"items": [], "total": 0},
                   {"kind": "feature", "department": corrected, "feature": "tailgating"})
    assert not outcome.errors
