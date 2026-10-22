"""诊断程序自身的隔离性、统计口径及受控业务链路验证，不连接真实模型。"""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from AiVision.tests.assistant_diagnostics.cases import PROBES, SCENARIOS
from AiVision.tests.assistant_diagnostics.conversations import conversation_cases, run_conversation
from AiVision.tests.assistant_diagnostics.runner import aggregate, diagnostic_environment, model_cases, run_model_case, run_tool_probe
from AiVision.tests.assistant_diagnostics.sandbox import completion, execute_turn, isolated_platform, json_validity, response_statistics, run_dialogue


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("诊断程序的本地回归测试禁止网络连接")

    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    with diagnostic_environment():
        yield


def test_scenario_set_contains_all_eighteen_required_cases():
    assert len(SCENARIOS) == 18
    assert len({case.name for case in SCENARIOS}) == 18
    assert {case.fault for case in SCENARIOS if case.fault} == {
        "tool_error", "conflict", "invalid_json", "truncated", "wrong_answer", "cancel",
    }


def test_sandbox_blocks_every_other_database_engine():
    from sqlalchemy import create_engine

    other = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with isolated_platform(SCENARIOS[3]) as sandbox:
            assert sandbox.db.get_engine().dialect.name == "sqlite"
            with pytest.raises(RuntimeError, match="诊断隔离禁止连接其他业务数据库"):
                other.connect()
    finally:
        other.dispose()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda case: case.name)
def test_scripted_dialogues_use_real_isolated_business_services(scenario):
    row = run_dialogue(scenario)
    assert row["business_storage"] == "temporary_sqlite"
    assert row["real_model_calls"] == 0
    assert row["behavior_ok"] and row["configuration_ok"] and row["report_ok"]
    if scenario.fault:
        assert scenario.fault in row["injected_faults"]
    if scenario.name == "duplicate":
        assert row["duplicate_ok"]
    if scenario.prelude or scenario.continuation:
        assert row["history_received"]


@pytest.mark.parametrize("name", ["partial_update", "schema_range", "schema_type", "schema_unknown", "missing_read",
                                  "stale_version", "permission_denied", "readback_changed", "postcommit_error"])
def test_tools_reject_invalid_changes_and_verify_real_database_results(name):
    row = run_tool_probe(name, {})
    assert row["behavior_ok"] and row["configuration_ok"]


@pytest.mark.parametrize("probe", PROBES, ids=lambda case: case.name)
@pytest.mark.xfail(reason="诊断探针揭示现有 Agent 的任务约束与结果状态缺口；未修改生产执行逻辑", strict=False)
def test_current_agent_enforces_the_requested_scope_and_reports_recovery(probe):
    # 保留真实失败结果，不能以放宽预期或伪造业务返回让该保护性探针通过。
    row = run_dialogue(probe)
    assert row["behavior_ok"]


def test_aggregate_keeps_not_applicable_values_out_of_the_denominator():
    result = aggregate([
        {"classification_ok": True, "json_ok": [True, False], "model_calls": 2, "duration_seconds": 1.0},
        {"classification_ok": None, "json_ok": [], "model_calls": 1, "duration_seconds": 3.0},
    ])
    assert result["metrics"]["classification_ok"] == {
        "label": "任务分类准确率", "passed": 1, "total": 1, "rate": 1.0,
    }
    assert result["metrics"]["json_ok"]["rate"] == 0.5
    assert result["metrics"]["parameter_ok"]["rate"] is None
    assert result["average_model_calls"] == 1.5 and result["average_seconds"] == 2.0


def test_greeting_metric_does_not_accept_a_false_operation_claim(monkeypatch):
    client = Mock()
    client.complete.return_value = completion("你好，已删除摄像头。"), 0.0
    monkeypatch.setattr("AiVision.assistant.runtime.QwenClient", lambda: client)
    row = run_dialogue(SCENARIOS[0], live=True)
    assert row["report_ok"] is False and row["behavior_ok"] is False


@pytest.mark.parametrize("content, expected", [('{}', True), ('{"mode":', False), ('{"value":NaN}', False)])
def test_json_syntax_is_separate_from_finish_reason_and_schema(content, expected):
    assert json_validity(completion(content, "length")) is expected
    assert json_validity('{"error": {}}') is None


def test_service_failure_is_not_misreported_as_invalid_json_or_bad_classification():
    from AiVision.connectors.qwen.client import QwenNetworkError

    case = next(case for case in model_cases() if case["kind"] == "classification")
    client = Mock()
    client.complete.side_effect = QwenNetworkError("测试连接失败")
    row = run_model_case(case, client, {"base_url": "http://model.invalid/v1", "model": "fixture",
                                     "max_tokens": 2048, "temperature": 0.0, "timeout": 10.0}, 1)
    assert row["json_ok"] == [] and row["classification_ok"] is None
    assert row["failure_layers"] == ["model_service"]


def test_valid_json_with_wrong_schema_is_a_model_output_error():
    case = next(case for case in model_cases() if case["kind"] == "classification")
    client = Mock()
    client.complete.return_value = completion({"target_context": {}, "mode": "unknown"}), 0.0
    row = run_model_case(case, client, {"base_url": "http://model.invalid/v1", "model": "fixture",
                                     "max_tokens": 2048, "temperature": 0.0, "timeout": 10.0}, 1)
    assert row["json_ok"] == [True] and row["classification_ok"] is False
    assert row["failure_layers"] == ["model_output"] and row["errors"] == ["PlanFormatError"]


def test_correct_mode_with_wrong_operation_is_not_counted_as_correct_planning():
    case = next(case for case in model_cases() if case["name"] == "classification_single")
    client = Mock()
    client.complete.return_value = completion({"target_context": {}, "mode": "change", "operations": ["delete_camera"]}), 0.0
    row = run_model_case(case, client, {"base_url": "http://model.invalid/v1", "model": "fixture",
                                     "max_tokens": 2048, "temperature": 0.0, "timeout": 10.0}, 1)
    assert row["classification_ok"] is True and row["planning_operations_ok"] is False
    assert row["behavior_ok"] is False and row["failure_layers"] == ["model_output"]


def test_all_model_cases_use_the_same_fixed_settings_and_never_log_raw_content():
    cases = model_cases()
    assert {case["kind"] for case in cases} == {"chat", "classification", "resource", "parameter", "tool", "format"}
    client = Mock()
    secret = "fixture-private-response-sentinel"
    client.complete.return_value = completion(secret), 0.0
    settings = {"base_url": "http://model.invalid/v1", "model": "fixture", "max_tokens": 2048,
                "temperature": 0.0, "timeout": 10.0}
    case = next(item for item in cases if item["kind"] == "classification")
    original = deepcopy(case["messages"])
    rows = [run_model_case(case, client, settings, repeat) for repeat in range(1, 4)]
    assert case["messages"] == original
    assert len(client.complete.call_args_list) == 3
    from AiVision.core.settings import settings as application_settings
    assert all(call.kwargs["temperature"] == 0.0 and call.kwargs["max_tokens"] == application_settings.runtime.assistant_plan_max_tokens
               for call in client.complete.call_args_list)
    assert secret not in json.dumps(rows)


def test_offline_cli_report_marks_real_model_layers_as_blocked(tmp_path):
    from AiVision.tests.assistant_diagnostics.runner import main

    assert main(["--layers", "model,e2e-live", "--output", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert all(layer["status"] == "blocked" and layer["rows"] == [] for layer in report["layers"].values())
    assert len(report["source_fingerprint"]) == 64 and int(report["source_fingerprint"], 16) >= 0
    assert "未执行" in (tmp_path / "report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["mixed", "window", "pressure"])
def test_long_dialogues_share_one_session_and_preserve_per_turn_metrics(name):
    from AiVision.core.settings import settings

    rows = run_conversation(name)
    assert len(rows) == len(conversation_cases(settings.runtime.assistant_history_turns)[name]) >= 10
    assert all(row["behavior_ok"] and row["configuration_ok"] for row in rows)
    assert all(row["real_model_calls"] == 0 for row in rows)
    assert all(row["history_pairs"] <= settings.runtime.assistant_history_turns for row in rows)
    assert all(row["max_request_characters"] > 0 and row["max_prompt_tokens"] is None for row in rows)
    if name == "window" and settings.runtime.assistant_history_turns == 6:
        assert rows[7]["history_pairs"] == 6 and rows[7]["anchor_in_history"] is False
        assert rows[7]["binding_in_history"] is True and rows[7]["resource_ok"] is True
        assert rows[7]["verified_binding_in_context"] is True
        assert rows[7]["failure_layers"] == []
        assert rows[8]["binding_in_history"] is False and rows[8]["tools"] == ["capabilities", "ask_user"]
        assert rows[8]["verified_binding_in_context"] is False
        assert rows[10]["anchor_in_history"] is True


@pytest.mark.parametrize("text", ["这台摄像头", "通用电气事业部这台摄像头", "通用电气事业部", "记忆代号甲"])
def test_named_scope_or_context_does_not_block_a_verified_binding_and_its_later_use(monkeypatch, text):
    from AiVision.tests.assistant_diagnostics.conversations import ConversationScriptedClient

    original = ConversationScriptedClient.complete

    def literal_reference(self, **kwargs):
        raw, latency = original(self, **kwargs)
        if "只判断当前用户请求" in kwargs["messages"][0]["content"] and "对应" in self.sandbox.step.question:
            body = json.loads(json.loads(raw)["choices"][0]["message"]["content"])
            body["target_context"]["references"] = [{"kind": "named", "text": text}]
            return completion(body), latency
        return raw, latency

    monkeypatch.setattr(ConversationScriptedClient, "complete", literal_reference)
    rows = run_conversation("window")
    assert all(row["behavior_ok"] and row["configuration_ok"] for row in rows)
    assert rows[7]["binding_prerequisite_ok"] is True and rows[7]["verified_binding_in_context"] is True
    assert rows[8]["tools"] == ["capabilities", "ask_user"]
    assert "update_configurations" in rows[9]["tools"]
    assert all("ask_user" not in rows[index]["tools"] for index in (0, 7, 9, 10))


@pytest.mark.parametrize("fault", ["unknown_key", "different_target", "unbound_named_alias", "ambiguous_name"])
def test_target_block_evidence_distinguishes_lookup_selector_and_identity_failures(fault):
    from AiVision.assistant.schema import RequestPlan
    from AiVision.assistant.targets import TargetClarification, TargetPolicy
    from AiVision.assistant.tools import ReadArguments
    from AiVision.tests.assistant_diagnostics.cases import CAMERA_NAME, DEPARTMENT, RESOURCE, SECOND_CAMERA_NAME, SECOND_RESOURCE
    from AiVision.tests.assistant_diagnostics.sandbox import tool_target_evidence

    question = f"记忆代号甲对应{CAMERA_NAME}。查询配置"
    reference = "记忆代号乙" if fault == "unbound_named_alias" else CAMERA_NAME
    question += reference
    plan = RequestPlan(mode="query", query_tool="read_configurations", target_context={
        "references": [{"kind": "named", "text": reference}],
        "bindings": [{"alias": "记忆代号甲", "target": CAMERA_NAME, "evidence": f"记忆代号甲对应{CAMERA_NAME}"}]})
    policy = TargetPolicy(question, plan)
    candidates = [{"key": RESOURCE, "kind": "feature", "name": CAMERA_NAME, "department": DEPARTMENT}]
    if fault in {"different_target", "ambiguous_name"}:
        candidates.append({"key": SECOND_RESOURCE, "kind": "feature", "department": DEPARTMENT,
                           "name": CAMERA_NAME if fault == "ambiguous_name" else SECOND_CAMERA_NAME})
    policy.observe("list_resources", {"items": candidates})
    key = "feature:tailgating:9999" if fault == "unknown_key" else SECOND_RESOURCE if fault == "different_target" else RESOURCE
    arguments = {"resource_keys": [key]}
    with pytest.raises(TargetClarification):
        policy.check("read_configurations", ReadArguments(**arguments))
    evidence = tool_target_evidence(policy, "read_configurations", arguments)
    requested = evidence["requested_resources"][0]
    if fault == "unknown_key":
        assert not requested["discovered"] and all(item["matched_identities"] == 1 for item in evidence["selectors"])
    elif fault == "different_target":
        assert requested["discovered"] and not requested["matches_selector"]
    elif fault == "unbound_named_alias":
        assert requested["discovered"] and evidence["selectors"][-1] == {
            "kind": "name", "role": "fixture_alias", "matched_identities": 0}
    else:
        assert evidence["selectors"][0]["matched_identities"] == 2
    assert key not in json.dumps(evidence) and CAMERA_NAME not in json.dumps(evidence, ensure_ascii=False)


def test_target_evidence_never_exports_unknown_literals_evidence_keys_or_configuration():
    from AiVision.assistant.schema import RequestPlan
    from AiVision.assistant.targets import TargetPolicy
    from AiVision.tests.assistant_diagnostics.sandbox import planning_target_evidence, tool_target_evidence

    alias, target, key = "private-alias-sentinel", "private-target-sentinel", "private-key-sentinel"
    question = f"{alias}对应{target}。private-conversation-sentinel"
    plan = RequestPlan(mode="query", query_tool="read_configurations", target_context={
        "references": [{"kind": "named", "text": target}],
        "bindings": [{"alias": alias, "target": target, "evidence": question.split("。", 1)[0]}]})
    policy = TargetPolicy(question, plan)
    policy.observe("list_resources", {"items": [{"key": key, "kind": "other", "name": target, "department": None,
                                                "config": {"password": "private-password-sentinel"}}]})
    evidence = {"planning": planning_target_evidence(plan, question),
                "tools": tool_target_evidence(policy, "read_configurations", {"resource_keys": [key]})}
    assert "private-" not in json.dumps(evidence)
    assert evidence["planning"]["references"] == [{"kind": "named", "role": "other", "literal_in_message": True}]
    assert evidence["planning"]["bindings"][0]["positive_relation"] is True
    assert evidence["tools"]["requested_resources"][0]["discovered"] is True


@pytest.mark.parametrize("live", [False, True])
def test_failed_binding_cannot_make_subsequent_alias_clarification_pass(monkeypatch, live):
    from AiVision.tests.assistant_diagnostics import conversations as module
    from AiVision.tests.assistant_diagnostics.runner import markdown_report

    original = module.ConversationScriptedClient.complete

    def fail_setup(self, **kwargs):
        raw, latency = original(self, **kwargs)
        if self.sandbox.step.label in {"建立会话指代", "重述目标后修改"} and kwargs["json_mode"]:
            body = json.loads(json.loads(raw)["choices"][0]["message"]["content"])
            if body.get("action") == "read_configurations":
                body["arguments"]["resource_keys"] = ["feature:tailgating:9999"]
                return completion(body), latency
        return raw, latency

    monkeypatch.setattr(module.ConversationScriptedClient, "complete", fail_setup)
    if live:
        # 此处替代真实网络，只验证真实模型分支的故障归属规则。
        measured = module.MeasuredClient
        monkeypatch.setattr(module, "MeasuredClient", lambda sandbox, _delegate, **options:
                            measured(sandbox, module.ConversationScriptedClient(sandbox), **options))
    rows = run_conversation("window", live=live)
    first, later = rows[0], rows[7]
    assert not first["behavior_ok"] and first["errors"] == ["TargetClarification"]
    assert first["report_ok"] is True
    assert later["tools"] == ["capabilities", "ask_user"] and later["report_ok"] is True
    assert later["binding_prerequisite_ok"] is False
    assert later["behavior_ok"] is False and later["task_ok"] is False and later["resource_ok"] is False
    assert rows[8]["behavior_ok"] is True
    read = next(item for item in first["target_evidence"] if item["tool"] == "read_configurations")
    assert read["requested_resources"][0]["discovered"] is False
    planning = first["request_statistics"][0]["target_context_evidence"]
    assert planning["bindings"][0]["positive_relation"] is True
    if live:
        assert "target_resolution" in first["failure_layers"] and "model_output" not in first["failure_layers"]
        assert "target_resolution" in later["failure_layers"] and "model_output" not in later["failure_layers"]
        assert "target_resolution" in rows[9]["failure_layers"] and "model_output" not in rows[9]["failure_layers"]
        assert rows[8]["failure_layers"] == []
    report = markdown_report({"generated_at": "fixture", "revision": "fixture", "settings": {
        "repeats": 3, "temperature": 0, "max_tokens": 2048, "timeout": 45}, "layers": {
            "conversation-live" if live else "conversation-scripted": {
                "status": "completed", "rows": rows, "summary": aggregate(rows)}}})
    assert "目标核验失败证据" in report and '"discovered": false' in report
    assert "1. 优先核对目标拦截证据" in report
    assert "feature:tailgating:9999" not in report


def test_token_usage_is_recorded_without_request_or_response_text(monkeypatch):
    client = Mock()
    response = json.loads(completion("你好呀"))
    response["usage"] = {"prompt_tokens": 123, "completion_tokens": 5, "total_tokens": 128}
    client.complete.return_value = json.dumps(response), 0.0
    monkeypatch.setattr("AiVision.assistant.runtime.QwenClient", lambda: client)
    with isolated_platform(SCENARIOS[0], live=True) as sandbox:
        from AiVision.tests.assistant_diagnostics.sandbox import execute_turn
        execute_turn(sandbox, "你好哇")
        statistics = sandbox.client.requests[0]
        assert statistics["prompt_tokens"] == 123 and statistics["total_tokens"] == 128
        assert "messages" in statistics and isinstance(statistics["messages"], int)
        assert "你好" not in json.dumps(statistics, ensure_ascii=False)


def test_malformed_tool_arguments_are_scored_instead_of_crashing_the_diagnostic(monkeypatch):
    from AiVision.tests.assistant_diagnostics.sandbox import ScriptedClient

    original = ScriptedClient.complete

    def malformed(self, **kwargs):
        raw, latency = original(self, **kwargs)
        body = json.loads(json.loads(raw)["choices"][0]["message"]["content"])
        if body.get("action") == "update_configurations":
            body["arguments"]["changes"] = None
            raw = completion(body)
        return raw, latency

    monkeypatch.setattr(ScriptedClient, "complete", malformed)
    row = run_dialogue(SCENARIOS[3])
    assert row["behavior_ok"] is False and row["parameter_ok"] is False
    assert "ValidationError" in row["errors"]


def test_reading_the_wrong_configuration_kind_is_a_resource_error(monkeypatch):
    from AiVision.tests.assistant_diagnostics.conversations import ConversationScriptedClient

    original = ConversationScriptedClient.complete

    def wrong_kind(self, **kwargs):
        raw, latency = original(self, **kwargs)
        body = json.loads(json.loads(raw)["choices"][0]["message"]["content"])
        if body.get("action") == "read_configurations":
            body["arguments"]["resource_keys"] = ["camera:101"]
            raw = completion(body)
        return raw, latency

    monkeypatch.setattr(ConversationScriptedClient, "complete", wrong_kind)
    rows = run_conversation("pressure")
    assert all(row["resource_ok"] is False and row["behavior_ok"] is False for row in rows)


def test_target_and_pending_parameter_survive_eight_greetings_and_save_with_a_fresh_read():
    from AiVision.assistant.context import CONTEXT_PREFIX
    from AiVision.core.config_revision import configuration_revision
    from AiVision.tests.assistant_diagnostics.cases import CAMERA_NAME, DEPARTMENT, FEATURE, RESOURCE
    from AiVision.tests.assistant_diagnostics.sandbox import execute_turn

    with isolated_platform(SCENARIOS[3]) as sandbox:
        reference = {"key": RESOURCE}
        revision = configuration_revision(sandbox.before[RESOURCE])
        lowering = "把这台摄像头的非法闯闸人体置信度调低一点"
        replies = [
            {"target_context": {}, "mode": "query", "query_tool": "read_configurations"},
            {"action": "list_resources", "arguments": {"kind": "feature", "department": DEPARTMENT,
                "feature": FEATURE, "query": CAMERA_NAME}},
            {"action": "read_configurations", "arguments": {"resource_keys": [RESOURCE]}},
            *["你好呀" for _ in range(8)],
            {"target_context": {"references": [{"kind": "context", "text": "这台摄像头"}]}, "mode": "change", "operations": ["update_configurations"]},
            {"action": "ask_user", "arguments": {"question": "人体置信度想调低到哪个具体数值？"}},
            {"target_context": {"references": [{"kind": "pending", "text": "就改为0.55"}]}, "mode": "change", "operations": ["update_configurations"]},
            {"action": "read_configurations", "arguments": {"resource_keys": [RESOURCE]}},
            {"action": "update_configurations", "arguments": {"changes": [{"resource_key": RESOURCE,
                "expected_revision": revision, "patch": {"value": {"threshold": 0.55}}}]}},
            {"action": "answer", "answer": "结束本轮"},
        ]
        client = Mock()
        client.complete.side_effect = [(completion(reply), 0.0) for reply in replies]
        sandbox.runtime.client = client
        first, _ = execute_turn(sandbox, f"读取通用电气事业部{CAMERA_NAME}的非法闯闸人体置信度")
        assert first.status == "completed"
        for _ in range(8):
            greeting, _ = execute_turn(sandbox, "你好哇")
            assert greeting.status == "completed"
        before_clarification = client.complete.call_count
        clarification, _ = execute_turn(sandbox, lowering)
        assert clarification.status == "completed" and not sandbox.service.actions(clarification.id)
        planning = client.complete.call_args_list[before_clarification].kwargs
        context = next(message["content"] for message in planning["messages"] if message["content"].startswith(CONTEXT_PREFIX))
        data = json.loads(context[len(CONTEXT_PREFIX):])
        assert len(data["recent_turns"]) == 6
        assert all(item["request"] == "你好哇" for item in data["recent_turns"])
        assert data["task_context"]["last_read_resources"][0]["key"] == reference["key"]
        before_continuation = client.complete.call_count
        saved, _ = execute_turn(sandbox, "就改为0.55")
        assert saved.status == "completed" and "已保存配置" in saved.answer
        planning = client.complete.call_args_list[before_continuation].kwargs
        context = next(message["content"] for message in planning["messages"] if message["content"].startswith(CONTEXT_PREFIX))
        data = json.loads(context[len(CONTEXT_PREFIX):])
        assert data["task_context"]["pending_task"]["request"] == lowering
        assert data["task_context"]["last_read_resources"][0]["key"] == RESOURCE
        assert "revision" not in data["task_context"]["last_read_resources"][0]
        actual = sandbox.snapshot()
        expected = deepcopy(sandbox.before)
        expected[RESOURCE]["value"]["threshold"] = 0.55
        assert actual == expected
        assert len(sandbox.service.actions(saved.id)) == 1
        recent_tools = [entry["tool"] for entry in sandbox.trace if entry.get("tool") != "capabilities"]
        assert recent_tools == ["list_resources", "read_configurations", "ask_user", "read_configurations", "update_configurations"]


def test_permission_change_hides_in_memory_targets_along_with_database_history():
    from AiVision.tests.assistant_diagnostics.cases import CAMERA_NAME, DEPARTMENT, FEATURE, RESOURCE
    from AiVision.tests.assistant_diagnostics.sandbox import execute_turn

    with isolated_platform(SCENARIOS[3]) as sandbox:
        client = Mock()
        client.complete.side_effect = [(completion(reply), 0.0) for reply in [
            {"target_context": {}, "mode": "query", "query_tool": "read_configurations"},
            {"action": "list_resources", "arguments": {"kind": "feature", "department": DEPARTMENT,
                "feature": FEATURE, "query": CAMERA_NAME}},
            {"action": "read_configurations", "arguments": {"resource_keys": [RESOURCE]}},
            {"target_context": {}, "mode": "query", "query_tool": "read_configurations"},
            {"action": "ask_user", "arguments": {"question": "请明确摄像头名称"}},
        ]]
        sandbox.runtime.client = client
        first, _ = execute_turn(sandbox, f"读取{CAMERA_NAME}的非法闯闸配置")
        assert sandbox.runtime.memory.get(sandbox.session_id, {first.id}) is not None
        sandbox.user["role"] = "viewer"
        next_turn, _ = execute_turn(sandbox, "再查一下这台摄像头的配置")
        assert next_turn.status == "completed" and not sandbox.service.actions(next_turn.id)
        planning = client.complete.call_args_list[3].kwargs
        assert CAMERA_NAME not in json.dumps(planning["messages"], ensure_ascii=False)
        assert RESOURCE not in json.dumps(planning["messages"], ensure_ascii=False)
        assert sandbox.snapshot() == sandbox.before


def bind_diagnostic_alias(sandbox):
    from AiVision.tests.assistant_diagnostics.cases import CAMERA_NAME, DEPARTMENT, FEATURE, RESOURCE

    declaration = f"记忆代号甲对应{CAMERA_NAME}"
    client = Mock()
    client.complete.side_effect = [(completion(reply), 0.0) for reply in [
        {"mode": "query", "query_tool": "read_configurations", "target_context": {
            "references": [{"kind": "context", "text": "这台摄像头"}],
            "bindings": [{"alias": "记忆代号甲", "target": CAMERA_NAME, "evidence": declaration}]}},
        {"action": "list_resources", "arguments": {"kind": "feature", "department": DEPARTMENT,
            "feature": FEATURE, "query": CAMERA_NAME}},
        {"action": "read_configurations", "arguments": {"resource_keys": [RESOURCE]}},
    ]]
    sandbox.runtime.client = client
    turn, _ = execute_turn(sandbox, declaration + "。查询通用电气事业部这台摄像头的非法闯闸配置")
    assert turn.status == "completed"
    state = sandbox.runtime.memory.get(sandbox.session_id, {turn.id})
    assert state["target_bindings"][0]["resource"]["key"] == RESOURCE
    return client, turn


@pytest.mark.parametrize("wrong_target", [False, True])
def test_verified_alias_survives_target_switch_and_blocks_the_models_wrong_resource(wrong_target):
    from AiVision.tests.assistant_diagnostics.cases import DEPARTMENT, FEATURE, RESOURCE, SECOND_CAMERA_NAME, SECOND_RESOURCE

    with isolated_platform(SCENARIOS[3]) as sandbox:
        client, _ = bind_diagnostic_alias(sandbox)
        client.complete.side_effect = [(completion(reply), 0.0) for reply in [
            {"mode": "query", "query_tool": "read_configurations", "target_context": {
                "references": [{"kind": "named", "text": SECOND_CAMERA_NAME}]}},
            {"action": "list_resources", "arguments": {"kind": "feature", "department": DEPARTMENT,
                "feature": FEATURE, "query": SECOND_CAMERA_NAME}},
            {"action": "read_configurations", "arguments": {"resource_keys": [SECOND_RESOURCE]}},
            *["你好呀" for _ in range(8)],
            {"mode": "query", "query_tool": "read_configurations", "target_context": {
                "references": [{"kind": "alias", "text": "记忆代号甲"}]}},
            {"action": "read_configurations", "arguments": {"resource_keys": [SECOND_RESOURCE if wrong_target else RESOURCE]}},
        ]]
        switched, _ = execute_turn(sandbox, f"查询{SECOND_CAMERA_NAME}的非法闯闸配置")
        assert switched.status == "completed"
        for _ in range(8):
            greeting, _ = execute_turn(sandbox, "你好哇")
            assert greeting.status == "completed"
        start = len(sandbox.trace)
        turn, _ = execute_turn(sandbox, "查询记忆代号甲的非法闯闸配置")
        recent = sandbox.trace[start:]
        assert turn.status == "completed" and sandbox.snapshot() == sandbox.before
        assert not sandbox.service.actions(turn.id)
        if wrong_target:
            assert recent[-2]["error_type"] == "TargetClarification"
            assert recent[-1]["tool"] == "ask_user" and "对应关系" in turn.answer
            state = sandbox.runtime.memory.get(sandbox.session_id, {item.id for item in sandbox.service.conversation(sandbox.session_id, sandbox.user).turns})
            assert state["last_read_resources"] == []
        else:
            assert [item["tool"] for item in recent] == ["capabilities", "read_configurations"]
            assert recent[-1]["result"]["items"][0]["resource"]["key"] == RESOURCE


@pytest.mark.parametrize("loss", ["never_bound", "restart", "expired", "permission"])
def test_missing_or_invisible_binding_asks_before_the_business_model_can_guess(monkeypatch, loss):
    from AiVision.assistant import context as module

    with isolated_platform(SCENARIOS[3]) as sandbox:
        client, _ = bind_diagnostic_alias(sandbox)
        alias = "记忆代号甲"
        if loss == "never_bound":
            alias = "记忆代号乙"
        elif loss == "restart":
            sandbox.runtime.memory.clear()
        elif loss == "expired":
            expired = module.time.monotonic() + module.CONTEXT_TTL_SECONDS
            monkeypatch.setattr(module.time, "monotonic", lambda: expired)
        else:
            sandbox.user["role"] = "viewer"
        client.complete.side_effect = [(completion({"mode": "query", "query_tool": "read_configurations",
            "target_context": {"references": [{"kind": "alias", "text": alias}]}}), 0.0)]
        calls, start = client.complete.call_count, len(sandbox.trace)
        turn, _ = execute_turn(sandbox, f"查询{alias}的非法闯闸配置")
        assert turn.status == "completed" and "对应关系" in turn.answer
        assert client.complete.call_count == calls + 1
        assert [item["tool"] for item in sandbox.trace[start:]] == ["capabilities", "ask_user"]
        assert not sandbox.service.actions(turn.id) and sandbox.snapshot() == sandbox.before


def test_a_number_cannot_resume_an_unknown_alias_against_the_previous_camera():
    with isolated_platform(SCENARIOS[3]) as sandbox:
        client, _ = bind_diagnostic_alias(sandbox)
        client.complete.side_effect = [(completion(reply), 0.0) for reply in [
            {"mode": "change", "operations": ["update_configurations"], "target_context": {
                "references": [{"kind": "alias", "text": "记忆代号乙"}]}},
            {"mode": "change", "operations": ["update_configurations"], "target_context": {
                "references": [{"kind": "pending", "text": "就改为0.8"}]}},
        ]]
        start = len(sandbox.trace)
        unknown, _ = execute_turn(sandbox, "把记忆代号乙的非法闯闸人体置信度调低一点")
        number, _ = execute_turn(sandbox, "就改为0.8")
        assert all(turn.status == "completed" and "对应关系" in turn.answer for turn in (unknown, number))
        assert [item["tool"] for item in sandbox.trace[start:]] == ["capabilities", "ask_user"] * 2
        assert not sandbox.service.actions(number.id) and sandbox.snapshot() == sandbox.before


def test_resource_listing_cannot_report_a_different_camera_for_a_verified_alias():
    from AiVision.tests.assistant_diagnostics.cases import DEPARTMENT, SECOND_CAMERA_NAME

    with isolated_platform(SCENARIOS[3]) as sandbox:
        client, _ = bind_diagnostic_alias(sandbox)
        client.complete.side_effect = [(completion(reply), 0.0) for reply in [
            {"mode": "query", "query_tool": "list_resources", "target_context": {
                "references": [{"kind": "alias", "text": "记忆代号甲"}]}},
            {"action": "list_resources", "arguments": {"kind": "camera", "department": DEPARTMENT,
                "query": SECOND_CAMERA_NAME}},
        ]]
        turn, _ = execute_turn(sandbox, "查询记忆代号甲这台摄像头")
        assert turn.status == "completed" and "对应关系" in turn.answer
        assert sandbox.trace[-2]["error_type"] == "TargetClarification"
        assert sandbox.trace[-1]["tool"] == "ask_user"
        assert not sandbox.service.actions(turn.id) and sandbox.snapshot() == sandbox.before


@pytest.mark.parametrize("read_verified_target", [True, False])
def test_alias_redeclaration_replaces_or_invalidates_the_old_target(read_verified_target):
    from AiVision.tests.assistant_diagnostics.cases import DEPARTMENT, FEATURE, RESOURCE, SECOND_CAMERA_NAME, SECOND_RESOURCE

    with isolated_platform(SCENARIOS[3]) as sandbox:
        client, _ = bind_diagnostic_alias(sandbox)
        declaration = f"记忆代号甲对应{SECOND_CAMERA_NAME}"
        client.complete.side_effect = [(completion(reply), 0.0) for reply in [
            {"mode": "query", "query_tool": "read_configurations", "target_context": {
                "references": [{"kind": "alias", "text": "记忆代号甲"}],
                "bindings": [{"alias": "记忆代号甲", "target": SECOND_CAMERA_NAME, "evidence": declaration}]}},
            {"action": "list_resources", "arguments": {"kind": "feature", "department": DEPARTMENT,
                "feature": FEATURE, "query": SECOND_CAMERA_NAME}},
            {"action": "read_configurations", "arguments": {"resource_keys": [SECOND_RESOURCE if read_verified_target else RESOURCE]}},
            {"mode": "query", "query_tool": "read_configurations", "target_context": {
                "references": [{"kind": "alias", "text": "记忆代号甲"}]}},
            {"action": "read_configurations", "arguments": {"resource_keys": [SECOND_RESOURCE]}},
        ]]
        rebound, _ = execute_turn(sandbox, declaration + "。读取非法闯闸配置")
        start = len(sandbox.trace)
        turn, _ = execute_turn(sandbox, "查询记忆代号甲的非法闯闸配置")
        assert rebound.status == turn.status == "completed" and sandbox.snapshot() == sandbox.before
        if read_verified_target:
            assert sandbox.trace[-1]["result"]["items"][0]["resource"]["key"] == SECOND_RESOURCE
        else:
            assert [item["tool"] for item in sandbox.trace[start:]] == ["capabilities", "ask_user"]
            assert "对应关系" in turn.answer


@pytest.mark.parametrize("guard", ["saved", "missing_read", "conflict", "permission"])
def test_alias_writes_keep_fresh_read_revision_permission_and_audit_guards(guard):
    from dataclasses import replace
    from AiVision.core.config_revision import configuration_revision
    from AiVision.tests.assistant_diagnostics.cases import RESOURCE

    with isolated_platform(SCENARIOS[3]) as sandbox:
        client, _ = bind_diagnostic_alias(sandbox)
        revision = configuration_revision(sandbox.snapshot()[RESOURCE])
        if guard == "conflict":
            sandbox.scenario = replace(SCENARIOS[3], fault="conflict")
        if guard == "permission":
            sandbox.user["role"] = "viewer"
        replies = [{"mode": "change", "operations": ["update_configurations"], "target_context": {
            "references": [{"kind": "alias", "text": "记忆代号甲"}]}}]
        if guard != "missing_read":
            replies.append({"action": "read_configurations", "arguments": {"resource_keys": [RESOURCE]}})
        replies.extend([
            {"action": "update_configurations", "arguments": {"changes": [{"resource_key": RESOURCE,
                "expected_revision": revision, "patch": {"value": {"threshold": 0.8}}}]}},
            {"action": "answer", "answer": "配置操作已经完成"},
        ])
        client.complete.side_effect = [(completion(reply), 0.0) for reply in replies]
        turn, _ = execute_turn(sandbox, "把记忆代号甲的非法闯闸人体置信度改为0.8")
        actions = sandbox.service.actions(turn.id)
        if guard == "saved":
            assert turn.status == "completed" and "已保存配置" in turn.answer
            assert len(actions) == 1 and actions[0].status == "saved"
        else:
            assert turn.status == "failed" and "已保存配置" not in turn.answer
            assert not any(action.status == "saved" for action in actions)
        expected = deepcopy(sandbox.before)
        expected[RESOURCE]["value"]["threshold"] = 0.8 if guard == "saved" else 0.6 if guard == "conflict" else 0.5
        assert sandbox.snapshot() == expected


def test_alias_cannot_undo_another_cameras_successful_audited_change():
    from AiVision.core.config_revision import configuration_revision
    from AiVision.tests.assistant_diagnostics.cases import DEPARTMENT, FEATURE, SECOND_CAMERA_NAME, SECOND_RESOURCE

    with isolated_platform(SCENARIOS[3]) as sandbox:
        client, _ = bind_diagnostic_alias(sandbox)
        revision = configuration_revision(sandbox.snapshot()[SECOND_RESOURCE])
        client.complete.side_effect = [(completion(reply), 0.0) for reply in [
            {"mode": "change", "operations": ["update_configurations"], "target_context": {
                "references": [{"kind": "named", "text": SECOND_CAMERA_NAME}]}},
            {"action": "list_resources", "arguments": {"kind": "feature", "department": DEPARTMENT,
                "feature": FEATURE, "query": SECOND_CAMERA_NAME}},
            {"action": "read_configurations", "arguments": {"resource_keys": [SECOND_RESOURCE]}},
            {"action": "update_configurations", "arguments": {"changes": [{"resource_key": SECOND_RESOURCE,
                "expected_revision": revision, "patch": {"value": {"threshold": 0.8}}}]}},
            {"action": "answer", "answer": "完成"},
        ]]
        changed, _ = execute_turn(sandbox, f"把{SECOND_CAMERA_NAME}非法闯闸人体置信度改为0.8")
        action = sandbox.service.actions(changed.id)[0]
        assert action.status == "saved"
        before_undo = sandbox.snapshot()
        client.complete.side_effect = [(completion(reply), 0.0) for reply in [
            {"mode": "change", "operations": ["undo_configuration"], "target_context": {
                "references": [{"kind": "alias", "text": "记忆代号甲"}]}},
            {"action": "undo_configuration", "arguments": {"action_id": action.id}},
        ]]
        turn, _ = execute_turn(sandbox, "撤销记忆代号甲的参数修改")
        assert turn.status == "completed" and "对应关系" in turn.answer
        assert sandbox.trace[-2]["error_type"] == "TargetClarification"
        assert not sandbox.service.actions(turn.id) and sandbox.snapshot() == before_undo


def test_cancellation_during_forced_target_clarification_does_not_finish_or_save_memory(monkeypatch):
    from AiVision.tests.assistant_diagnostics.sandbox import ObservedTools

    with isolated_platform(SCENARIOS[3]) as sandbox:
        original = ObservedTools.run

        def cancel_on_question(self, name, arguments):
            result = original(self, name, arguments)
            if name == "ask_user":
                sandbox.service.cancel(sandbox.session_id, sandbox.turn_id, sandbox.user)
            return result

        monkeypatch.setattr(ObservedTools, "run", cancel_on_question)
        sandbox.runtime.client = Mock()
        sandbox.runtime.client.complete.return_value = completion({"mode": "query", "query_tool": "read_configurations",
            "target_context": {"references": [{"kind": "alias", "text": "记忆代号乙"}]}}), 0.0
        turn, _ = execute_turn(sandbox, "查询记忆代号乙的非法闯闸配置")
        assert turn.status == "cancelled" and sandbox.snapshot() == sandbox.before
        assert sandbox.runtime.memory.get(sandbox.session_id, {turn.id}) is None
        assert not sandbox.service.actions(turn.id)


def test_schema_service_incompatibility_is_reported_before_running_ninety_nine_turns(monkeypatch, tmp_path):
    from AiVision.connectors.qwen.client import QwenServiceError
    from AiVision.tests.assistant_diagnostics.runner import main

    client = Mock()
    client.complete.side_effect = [(completion("你好"), 0.0), QwenServiceError("HTTP 400")]
    monkeypatch.setattr("AiVision.connectors.qwen.client.QwenClient", lambda: client)
    assert main(["--base-url", "http://model.invalid/v1", "--layers", "conversation-live",
                 "--output", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    layer = report["layers"]["conversation-live"]
    assert layer["status"] == "blocked" and layer["rows"] == []
    assert "JSON Schema 请求" in layer["reason"]
    assert client.complete.call_count == 2
    assert client.complete.call_args.kwargs["response_schema"]["additionalProperties"] is False


@pytest.mark.parametrize("question, expected", [("人体置信度要调低到哪个具体数值？", True),
                                                ("请确认哪台摄像头或所属部门？", False)])
def test_numeric_clarification_uses_verified_target_without_requiring_an_unnecessary_read(monkeypatch, question, expected):
    from AiVision.tests.assistant_diagnostics.conversations import ConversationScriptedClient

    original = ConversationScriptedClient.complete

    def ask_without_read(self, **kwargs):
        raw, latency = original(self, **kwargs)
        body = json.loads(json.loads(raw)["choices"][0]["message"]["content"])
        if self.sandbox.step.kind == "clarify_value" and body.get("action") == "read_configurations":
            return completion({"action": "ask_user", "arguments": {"question": question}}), latency
        return raw, latency

    monkeypatch.setattr(ConversationScriptedClient, "complete", ask_without_read)
    row = run_conversation("mixed")[11]
    assert "read_configurations" not in row["tools"] and row["configuration_ok"]
    assert row["behavior_ok"] is expected


@pytest.mark.parametrize("name", ["mixed", "pressure"])
def test_reusing_a_verified_target_still_requires_a_fresh_read_but_not_another_search(monkeypatch, name):
    from AiVision.assistant.context import CONTEXT_PREFIX
    from AiVision.tests.assistant_diagnostics.conversations import ConversationScriptedClient
    from AiVision.tests.assistant_diagnostics.sandbox import ScriptedClient

    original = ConversationScriptedClient.complete

    def reuse_target(self, **kwargs):
        step = self.sandbox.step
        if kwargs["messages"][-1]["content"].startswith("后台已查询"):
            for message in kwargs["messages"]:
                content = message["content"]
                if not content.startswith(CONTEXT_PREFIX):
                    continue
                context = json.loads(content[len(CONTEXT_PREFIX):])
                known = {item["key"] for item in (context.get("task_context") or {}).get("last_read_resources", [])}
                if set(step.targets) <= known and step.kind in {"read", "write", "clarify_value"}:
                    return ScriptedClient.tool("read_configurations", {"resource_keys": list(step.targets)})
        return original(self, **kwargs)

    monkeypatch.setattr(ConversationScriptedClient, "complete", reuse_target)
    rows = run_conversation(name)
    direct = [row for row in rows if "read_configurations" in row["tools"] and "list_resources" not in row["tools"]]
    assert direct and all(row["resource_resolution_ok"] for row in direct)
    assert all(row["tool_selection_ok"] and row["behavior_ok"] for row in rows)
    if name == "mixed":
        assert all("list_resources" not in rows[index]["tools"] for index in (3, 5, 7, 12))


@pytest.mark.parametrize("fault", ["unresolved_key", "wrong_target", "partial_targets", "no_read"])
def test_revised_scoring_rejects_unresolved_wrong_or_unread_targets(monkeypatch, fault):
    from AiVision.tests.assistant_diagnostics.cases import RESOURCE, SECOND_RESOURCE
    from AiVision.tests.assistant_diagnostics.conversations import ConversationScriptedClient
    from AiVision.tests.assistant_diagnostics.sandbox import ScriptedClient

    original = ConversationScriptedClient.complete

    def faulty_read(self, **kwargs):
        last = kwargs["messages"][-1]["content"]
        if fault == "unresolved_key" and last.startswith("后台已查询"):
            return ScriptedClient.tool("read_configurations", {"resource_keys": [RESOURCE, SECOND_RESOURCE]})
        raw, latency = original(self, **kwargs)
        body = json.loads(json.loads(raw)["choices"][0]["message"]["content"])
        if body.get("action") == "read_configurations":
            if fault == "no_read":
                return ScriptedClient.answer()
            body["arguments"]["resource_keys"] = ["camera:101"] if fault == "wrong_target" else [RESOURCE]
            return completion(body), latency
        return raw, latency

    monkeypatch.setattr(ConversationScriptedClient, "complete", faulty_read)
    row = run_conversation("pressure")[0]
    assert row["behavior_ok"] is False and row["configuration_ok"] is True
    assert row["resource_ok"] is False or row["tool_selection_ok"] is False
    if fault == "unresolved_key":
        assert row["status"] == "completed" and row["resource_resolution_ok"] is False


def test_cached_target_cannot_supply_a_read_version_for_a_later_write(monkeypatch):
    from AiVision.core.config_revision import configuration_revision
    from AiVision.tests.assistant_diagnostics.conversations import ConversationScriptedClient
    from AiVision.tests.assistant_diagnostics.sandbox import ScriptedClient

    original = ConversationScriptedClient.complete

    def skip_read(self, **kwargs):
        step = self.sandbox.step
        if step.kind == "write" and kwargs["messages"][-1]["content"].startswith("后台已查询"):
            configs = self.sandbox.snapshot()
            return ScriptedClient.tool("update_configurations", {"changes": [
                {"resource_key": key, "expected_revision": configuration_revision(configs[key]), "patch": step.delta}
                for key in step.targets]})
        return original(self, **kwargs)

    monkeypatch.setattr(ConversationScriptedClient, "complete", skip_read)
    row = run_conversation("mixed")[3]
    assert row["status"] == "failed" and row["configuration_ok"] is False and row["behavior_ok"] is False
    assert "read_configurations" not in row["tools"] and "ConfigurationConflict" in row["errors"]


@pytest.mark.parametrize("content, wrapper, thinking, format_, shape", [
    ('<think>\n</think>\n{"mode":"chat"}', "closed", 0, "object", "request_plan"),
    ('<think>private-thinking-sentinel</think>\n```json\n{"action":"answer"}\n```', "closed", 25, "object", "agent_decision"),
    ("<think>private-thinking-sentinel", "unclosed", 25, "unclosed_thinking", None),
    ("private-answer-sentinel", "absent", 0, "text", None),
    ('{"private-field-sentinel":', "absent", 0, "invalid_json", None),
    ('{"private-field-sentinel":"private-answer-sentinel"}', "absent", 0, "object", "other"),
    ("[1,2]", "absent", 0, "array", None),
    ("null", "absent", 0, "scalar", None),
])
def test_response_statistics_reveal_shape_without_logging_private_content(content, wrapper, thinking, format_, shape):
    raw = json.loads(completion(content))
    raw["choices"][0]["message"]["reasoning_content"] = "private-reasoning-sentinel"
    statistics = response_statistics(json.dumps(raw))
    assert statistics["thinking_wrapper"] == wrapper and statistics["thinking_characters"] == thinking
    assert statistics["answer_format"] == format_ and statistics.get("object_shape") == shape
    assert statistics["reasoning_characters"] == len("private-reasoning-sentinel")
    assert "private-" not in json.dumps(statistics)


@pytest.mark.parametrize("raw", ['{"error":{}}', "not-json", '{"choices":null}', '{"choices":[{"message":null}]}'])
def test_response_statistics_handle_invalid_envelopes(raw):
    assert response_statistics(raw) == {"envelope_valid": False}


@pytest.mark.parametrize("content, category", [('not json', "plan_json"), ('{}', "plan_schema")])
def test_independent_classification_uses_the_same_strict_parser_as_runtime(content, category):
    case = next(case for case in model_cases() if case["kind"] == "classification")
    client = Mock()
    client.complete.return_value = completion(content), 0.0
    row = run_model_case(case, client, {"base_url": "http://model.invalid/v1", "model": "fixture",
                                     "max_tokens": 2048, "temperature": 0.0, "timeout": 10.0}, 1)
    assert row["errors"] == ["PlanFormatError"] and row["error_category"] == category
    assert row["schema_output_ok"] is False and row["validation_issues"]


@pytest.mark.parametrize("name", ["schema_aligned", "schema_conflicting"])
@pytest.mark.parametrize("content, expected", [({"probe": "schema_ok"}, True), ("格式探针完成", False),
                                             ({"probe": "wrong"}, False), ({"probe": "schema_ok", "extra": 1}, False)])
def test_format_probes_check_actual_output_instead_of_http_acceptance(name, content, expected):
    case = next(case for case in model_cases() if case["name"] == name)
    client = Mock()
    client.complete.return_value = completion(content), 0.0
    row = run_model_case(case, client, {"base_url": "http://model.invalid/v1", "model": "fixture",
                                     "max_tokens": 2048, "temperature": 0.0, "timeout": 10.0}, 1)
    assert row["schema_output_ok"] is expected and row["behavior_ok"] is expected
    assert client.complete.call_args.kwargs["response_schema"]["additionalProperties"] is False
    assert row["requested_response_format"] == "json_schema"


def test_model_cli_renders_format_evidence_without_raw_content(monkeypatch, tmp_path):
    from AiVision.tests.assistant_diagnostics.runner import main

    client = Mock()
    client.complete.return_value = completion('<think>private-thinking-sentinel</think>\n{"probe":"schema_ok"}'), 0.0
    monkeypatch.setattr("AiVision.connectors.qwen.client.QwenClient", lambda: client)
    assert main(["--base-url", "http://model.invalid/v1", "--layers", "model", "--repeats", "3",
                 "--output", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    rows = report["layers"]["model"]["rows"]
    assert len(rows) == len(model_cases()) * 3
    assert sum(row["behavior_ok"] for row in rows if row["scenario"].startswith("schema_")) == 6
    assert all(row["response_metadata"]["thinking_characters"] == 25 for row in rows)
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "schema_conflicting" in markdown and "输出合同通过/适用次数" in markdown
    assert "private-" not in markdown and "private-" not in json.dumps(report)


def test_service_openapi_contract_follows_references_without_logging_defaults():
    from AiVision.tests.assistant_diagnostics.service import openapi_contract

    schema = {"paths": {"/v1/chat/completions": {"post": {"requestBody": {"$ref": "#/components/requestBodies/Input"}}}},
              "components": {"requestBodies": {"Input": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Input"}}}}},
                             "schemas": {"Input": {"allOf": [{"properties": {"messages": {}, "response_format": {},
                                 "private-field-sentinel": {"default": "private-value-sentinel"}}, "additionalProperties": False},
                                 {"$ref": "#/components/schemas/Input"}]}}}}
    result = openapi_contract(schema)
    assert result == {"chat_completions_found": True, "declared_fields": ["messages", "response_format"], "extra_fields_policy": "forbid"}
    assert "private-" not in json.dumps(result)


def test_service_process_inspection_redacts_arguments_and_reads_listener_environment(tmp_path):
    from AiVision.tests.assistant_diagnostics.service import process_details

    process = tmp_path / "123"
    process.mkdir()
    (process / "exe").symlink_to("/env/bin/python3.11")
    (process / "cmdline").write_bytes(b"/env/bin/python\0/srv/serve_model.py\0--api-key\0private-key-sentinel\0--structured-outputs-config.backend\0xgrammar\0--infer_backend\0vllm\0")
    source = process / "root/srv/serve_model.py"
    source.parent.mkdir(parents=True)
    source.write_text("import transformers\nresponse_format = 'private-source-sentinel'\n", encoding="utf-8")
    metadata = process / "root/env/lib/python3.11/site-packages/transformers-5.1.0.dist-info/METADATA"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("Name: transformers\nVersion: 5.1.0\nPrivate: private-metadata-sentinel\n", encoding="utf-8")
    swift_metadata = metadata.parent.parent / "ms_swift-4.4.2.dist-info/METADATA"
    swift_metadata.parent.mkdir()
    swift_metadata.write_text("Name: ms-swift\nVersion: 4.4.2\n", encoding="utf-8")
    result = process_details(123, proc_root=tmp_path)
    assert result["entrypoint_name"] == "serve_model.py" and len(result["entrypoint_sha256"]) == 64
    assert result["source_signals"]["response_format"] and result["source_signals"]["transformers"]
    assert result["installed_package_versions"] == {"transformers": ["5.1.0"], "ms_swift": ["4.4.2"]}
    assert result["decoding_backend_hints"] == ["xgrammar"]
    assert result["inference_backend_hints"] == ["vllm"]
    assert "private-" not in json.dumps(result) and "--api-key" not in json.dumps(result)


@pytest.mark.parametrize("entry,expected", [
    (["-u", "-m", "vllm.entrypoints.openai.api_server"], "vllm.entrypoints.openai.api_server"),
    (["serve_model.py", "-m", "private_module_sentinel"], None),
])
def test_service_process_module_detection_does_not_expose_application_arguments(tmp_path, entry, expected):
    from AiVision.tests.assistant_diagnostics.service import process_details

    process = tmp_path / "123"
    process.mkdir()
    (process / "exe").symlink_to("/env/bin/python3.11")
    (process / "cmdline").write_bytes("\0".join(["/env/bin/python", *entry]).encode())
    result = process_details(123, proc_root=tmp_path)
    assert result.get("python_module") == expected and "private_module_sentinel" not in json.dumps(result)


def test_service_metadata_retains_only_version_and_contract_evidence(monkeypatch):
    from AiVision.tests.assistant_diagnostics import service

    monkeypatch.setattr(service, "local_listener", lambda _url: {"status": "not_found", "processes": []})
    monkeypatch.setenv("SECURITY_VLM_API_KEY", "private-header-sentinel")
    document = {"version": "0.8.2", "build_info": "private-version-sentinel", "password": "private-password-sentinel",
                "info": {"title": "vLLM private-title-sentinel", "version": "0.1.0"},
                "data": [{"id": "fixture", "owned_by": "vllm", "root": "private-path-sentinel"}]}
    calls = []

    def get(_self, url, **kwargs):
        assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
        assert kwargs["headers"]["Authorization"] == "Bearer private-header-sentinel"
        calls.append(url)
        response = Mock(status_code=200, headers={"Server": "uvicorn private-server-sentinel"})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [json.dumps(document).encode()]
        return response

    monkeypatch.setattr("requests.Session.get", get)
    result = service.service_metadata({"base_url": "http://model.invalid/proxy/v1", "model": "fixture", "timeout": 10.0})
    assert len(calls) == 6 and "http://model.invalid/proxy/version" in calls
    assert result["endpoints"]["version"]["versions"] == {"version": "0.8.2"}
    assert result["endpoints"]["openapi"]["application_version"] == "0.1.0"
    assert result["endpoints"]["models"]["owner_hints"] == ["vllm"]
    assert "private-" not in json.dumps(result)


@pytest.mark.parametrize("payload,status,error", [(b'{"version":"1.2.3"}', 302, None), (b'not-json', 200, "JSONDecodeError"),
                                                (b'x' * (2 * 1024 * 1024 + 1), 200, "ValueError")])
def test_service_metadata_handles_redirects_invalid_json_and_size_limits(monkeypatch, payload, status, error):
    from AiVision.tests.assistant_diagnostics import service

    monkeypatch.setattr(service, "local_listener", lambda _url: {})
    response = Mock(status_code=status, headers={"Location": "private-redirect-sentinel"})
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.side_effect = lambda **_kwargs: iter([payload])
    monkeypatch.setattr("requests.Session.get", lambda *_args, **_kwargs: response)
    result = service.service_metadata({"base_url": "http://model.invalid/v1", "model": "fixture", "timeout": 10.0})
    assert all(entry["http_status"] == status for entry in result["endpoints"].values())
    if status == 200:
        assert all(entry["error_type"] == error for entry in result["endpoints"].values())
    assert "private-" not in json.dumps(result)


@pytest.mark.parametrize("network_error", [False, True])
def test_service_contract_probes_preserve_rejections_limits_and_inconclusive_results(monkeypatch, network_error):
    from AiVision.connectors.qwen.client import QwenNetworkError, QwenServiceError
    from AiVision.tests.assistant_diagnostics.service import run_service_probes

    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        if network_error:
            raise QwenNetworkError("private-network-sentinel")
        schema = kwargs.get("response_schema") or {}
        if schema.get("type") == "assistant_diagnostic_invalid_type":
            raise QwenServiceError("HTTP 422 private-error-sentinel")
        body = json.loads(completion({"probe": "schema_ok"} if kwargs["json_mode"] else "private-response-sentinel"))
        body["usage"] = {"completion_tokens": 1 if kwargs["max_tokens"] == 1 else 12}
        return json.dumps(body), 0.0

    client = Mock()
    client.complete.side_effect = complete
    monkeypatch.setattr("AiVision.connectors.qwen.client.QwenClient", lambda: client)
    rows = []
    run_service_probes({"base_url": "http://model.invalid/v1", "model": "fixture", "timeout": 10.0}, 3, rows.append, lambda _message: None)
    assert len(rows) == 15 and len(calls) == 15
    assert all(call["temperature"] == 0.0 and call["timeout"] == 10.0 for call in calls)
    if network_error:
        assert all(row["probe_status"] == "inconclusive" and row["failure_layers"] == ["model_service"] for row in rows)
    else:
        assert all(row["behavior_ok"] and row["probe_status"] == "passed" for row in rows)
        assert all(row["http_status"] == 422 for row in rows if row["scenario"] == "invalid_schema_rejection")
        assert all(row["max_tokens_ok"] for row in rows if row["scenario"] == "max_tokens_one")
    assert "private-" not in json.dumps(rows)


def test_service_layer_is_blocked_without_an_explicit_target(tmp_path):
    from AiVision.tests.assistant_diagnostics.runner import main

    assert main(["--layers", "service", "--output", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert report["layers"]["service"]["status"] == "blocked" and "service_inspection" not in report


@pytest.mark.parametrize("fault", ["ignored_schema", "ignored_length", "missing_usage", "short_control"])
def test_service_probes_do_not_confuse_ignored_parameters_with_success(monkeypatch, fault):
    from AiVision.tests.assistant_diagnostics.service import run_service_probes

    def complete(**kwargs):
        body = json.loads(completion("fixed text" if fault == "ignored_schema" else {"probe": "schema_ok"}))
        if fault != "missing_usage":
            body["usage"] = {"completion_tokens": 10 if fault == "ignored_length" else 1 if kwargs["max_tokens"] == 1 or fault == "short_control" else 12}
        return json.dumps(body), 0.0

    client = Mock()
    client.complete.side_effect = complete
    monkeypatch.setattr("AiVision.connectors.qwen.client.QwenClient", lambda: client)
    rows = []
    run_service_probes({"base_url": "http://model.invalid/v1", "model": "fixture", "timeout": 10.0}, 3, rows.append, lambda _message: None)
    rejection = [row for row in rows if row["scenario"] == "invalid_schema_rejection"]
    assert all(row["schema_rejection_ok"] is False for row in rejection)
    if fault == "ignored_schema":
        assert all(row["behavior_ok"] is False for row in rows if row["scenario"] in {"json_object_conflict", "json_schema_conflict"})
    length = [row for row in rows if row["scenario"] == "max_tokens_one"]
    if fault != "ignored_schema":
        assert all(row["probe_status"] == ("failed" if fault == "ignored_length" else "inconclusive") for row in length)


def test_service_cli_writes_identity_and_probe_results_without_database_access(monkeypatch, tmp_path):
    from AiVision.connectors.qwen.client import QwenServiceError
    from AiVision.tests.assistant_diagnostics import service
    from AiVision.tests.assistant_diagnostics.runner import main

    monkeypatch.setattr(service, "service_metadata", lambda _settings: {"listener": {"status": "not_found"}, "endpoints": {}})

    def no_database(*_args, **_kwargs):
        raise AssertionError("服务检查不得连接业务数据库")

    monkeypatch.setattr("sqlalchemy.engine.Engine.connect", no_database)

    def complete(**kwargs):
        schema = kwargs.get("response_schema") or {}
        if schema.get("type") == "assistant_diagnostic_invalid_type":
            raise QwenServiceError("HTTP 400")
        body = json.loads(completion({"probe": "schema_ok"} if kwargs["json_mode"] else "fixed text"))
        body["usage"] = {"completion_tokens": 1 if kwargs["max_tokens"] == 1 else 12}
        return json.dumps(body), 0.0

    client = Mock()
    client.complete.side_effect = complete
    monkeypatch.setattr("AiVision.connectors.qwen.client.QwenClient", lambda: client)
    assert main(["--base-url", "http://model.invalid/v1", "--layers", "service", "--output", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert len(report["layers"]["service"]["rows"]) == 15 and client.complete.call_count == 15
    assert report["service_inspection"]["listener"]["status"] == "not_found"
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "模型服务身份与合同证据" in markdown and "invalid_schema_rejection" in markdown
