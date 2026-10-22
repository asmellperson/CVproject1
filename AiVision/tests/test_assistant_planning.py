"""严格任务分类、单次格式纠正与执行边界的回归验证，不连接模型或业务数据库。"""

import json
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
    ("你好，帮我修改摄像头 FPS", False), ("你好\n删除一号摄像头", False),
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
            check_cancel=lambda: None, turn_id=1, allow_greeting=False, **kwargs,
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


def test_greeting_with_existing_context_still_uses_the_planner(runtime_case):
    case = runtime_case
    case.current.question = "你好"
    previous = SimpleNamespace(id=0, question="请修改摄像头名称", status="completed", answer="请提供名称", actions=[])
    case.service.conversation.return_value.turns.insert(0, previous)
    case.client.complete.side_effect = [(completion({"mode": "chat"}), 0.1), (completion("你好"), 0.1)]
    case.execute()
    assert case.client.complete.call_count == 2
    assert case.client.complete.call_args_list[0].kwargs["json_mode"] is True


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
