"""诊断程序自身的隔离性、统计口径及受控业务链路验证，不连接真实模型。"""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from AiVision.tests.assistant_diagnostics.cases import PROBES, SCENARIOS
from AiVision.tests.assistant_diagnostics.conversations import conversation_cases, run_conversation
from AiVision.tests.assistant_diagnostics.runner import aggregate, diagnostic_environment, model_cases, run_model_case, run_tool_probe
from AiVision.tests.assistant_diagnostics.sandbox import completion, isolated_platform, json_validity, run_dialogue


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
    client.complete.return_value = completion({"mode": "unknown"}), 0.0
    row = run_model_case(case, client, {"base_url": "http://model.invalid/v1", "model": "fixture",
                                     "max_tokens": 2048, "temperature": 0.0, "timeout": 10.0}, 1)
    assert row["json_ok"] == [True] and row["classification_ok"] is False
    assert row["failure_layers"] == ["model_output"] and row["errors"] == ["PlanFormatError"]


def test_correct_mode_with_wrong_operation_is_not_counted_as_correct_planning():
    case = next(case for case in model_cases() if case["name"] == "classification_single")
    client = Mock()
    client.complete.return_value = completion({"mode": "change", "operations": ["delete_camera"]}), 0.0
    row = run_model_case(case, client, {"base_url": "http://model.invalid/v1", "model": "fixture",
                                     "max_tokens": 2048, "temperature": 0.0, "timeout": 10.0}, 1)
    assert row["classification_ok"] is True and row["planning_operations_ok"] is False
    assert row["behavior_ok"] is False and row["failure_layers"] == ["model_output"]


def test_all_model_cases_use_the_same_fixed_settings_and_never_log_raw_content():
    cases = model_cases()
    assert {case["kind"] for case in cases} == {"chat", "classification", "resource", "parameter", "tool"}
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
    assert all(call.kwargs["temperature"] == 0.0 and call.kwargs["max_tokens"] == 256
               for call in client.complete.call_args_list)
    assert secret not in json.dumps(rows)


def test_offline_cli_report_marks_real_model_layers_as_blocked(tmp_path):
    from AiVision.tests.assistant_diagnostics.runner import main

    assert main(["--layers", "model,e2e-live", "--output", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert all(layer["status"] == "blocked" and layer["rows"] == [] for layer in report["layers"].values())
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
        assert "context_transfer" in rows[7]["failure_layers"]
        assert rows[9]["anchor_in_history"] is True


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
