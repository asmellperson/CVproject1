"""可携带到模型服务器运行的诊断入口，报告不包含模型原文、对话或认证信息。"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform as system_platform
import statistics
import subprocess
import time
from unittest.mock import patch

from .cases import CAMERA_NAME, DEPARTMENT, FEATURE, METRICS, PROBES, RESOURCE, SCENARIOS
from .conversations import conversation_cases, run_conversation
from .sandbox import ObservedTools, isolated_platform, json_validity, response_statistics, run_dialogue


@contextmanager
def diagnostic_environment():
    # 必须先隔离环境再导入生产模块，不能因缺少数据库变量而加载生产 .env。
    with patch.dict(os.environ, {"MYSQL_DB_URL": "diagnostic.invalid", "MYSQL_DB_USER": "diagnostic",
                               "MYSQL_DB_PASSWORD": "unused", "MYSQL_DB_NAME": "diagnostic",
                               "AUTO_CREATE_DB": "false", "DATA_PATH": "/tmp"}):
        yield


def aggregate(rows):
    metrics = {}
    for key, label in METRICS.items():
        samples = []
        for row in rows:
            value = row.get(key)
            if isinstance(value, list):
                samples.extend(item for item in value if isinstance(item, bool))
            elif isinstance(value, bool):
                samples.append(value)
        metrics[key] = {"label": label, "passed": sum(samples), "total": len(samples),
                        "rate": round(sum(samples) / len(samples), 6) if samples else None}
    return {"samples": len(rows), "metrics": metrics,
            "average_model_calls": round(statistics.mean(row.get("model_calls", 0) for row in rows), 4) if rows else None,
            "average_seconds": round(statistics.mean(row.get("duration_seconds", 0) for row in rows), 6) if rows else None}


def model_cases():
    from typing import Literal
    from pydantic import BaseModel, ConfigDict
    from AiVision.assistant.responses import parse_plan
    from AiVision.assistant.runtime import CHAT_SYSTEM_PROMPT, PLANNING_PROMPT
    from AiVision.assistant.schema import AgentDecision, RequestPlan
    from AiVision.assistant.tools import UpdateArguments
    from AiVision.features.tailgating.schema import TailgatingConfig

    class Target(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        department: str | None
        feature: str | None
        camera_names: list[str]

    class Assignment(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
        path: Literal["value.threshold", "value.cap_interval"]
        operation: Literal["set", "decrease"]
        value: float | None

    class Parameters(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        assignments: list[Assignment]

    class FormatProbe(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        probe: Literal["schema_ok"]

    catalog = {"departments": [{"id": DEPARTMENT, "name": "通用电气事业部"}],
               "features": [{"name": FEATURE, "label": "非法闯闸"}], "camera_names": [CAMERA_NAME, "诊断闸机二号"]}
    schema_text = json.dumps(TailgatingConfig.model_json_schema(), ensure_ascii=False)
    cases = [{"name": "chat", "kind": "chat", "messages": [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT}, {"role": "user", "content": "你好哇"}], "json_mode": False}]
    # 同一输出合同分别配合一致及冲突的提示，区分服务接受参数与实际约束输出。
    # 冲突只涉及固定的格式文本，不包含业务数据，也不涉及任何工具执行。
    for name, question in (
        ("schema_aligned", '只输出 {"probe":"schema_ok"}，不要其他文字。'),
        ("schema_conflicting", "只输出一句普通文本：格式探针完成。不要输出 JSON 或代码块。"),
    ):
        cases.append({"name": name, "kind": "format", "json_mode": True, "schema": FormatProbe,
                      "expected": {"probe": "schema_ok"}, "messages": [
                          {"role": "system", "content": "这是固定虚构的输出格式测试，请按用户指定的形式作答。"},
                          {"role": "user", "content": question}]})
    for name in ("greeting", "capabilities", "camera", "single", "double", "continuation"):
        case = next(item for item in SCENARIOS if item.name == name)
        messages = [{"role": "system", "content": PLANNING_PROMPT + json.dumps(RequestPlan.model_json_schema(), ensure_ascii=False)},
                    {"role": "user", "content": case.question}]
        cases.append({"name": "classification_" + name, "kind": "classification", "messages": messages,
                      "json_mode": True, "expected": case.mode, "validate": parse_plan,
                      "response_schema": RequestPlan.model_json_schema(),
                      "query_tool": ("capabilities" if name == "capabilities" else "list_resources") if case.mode == "query" else None})
    cases.append({"name": "classification_continuation_reply", "kind": "classification", "json_mode": True,
                  "expected": "change", "validate": parse_plan, "response_schema": RequestPlan.model_json_schema(), "query_tool": None, "messages": [
                      {"role": "system", "content": PLANNING_PROMPT + json.dumps(RequestPlan.model_json_schema(), ensure_ascii=False)},
                      {"role": "user", "content": SCENARIOS[15].question},
                      {"role": "assistant", "content": "请选择诊断闸机一号或诊断闸机二号，本轮没有执行配置操作。"},
                      {"role": "user", "content": CAMERA_NAME}]})
    for name, question, cameras in [
        ("named_camera", SCENARIOS[3].question, [CAMERA_NAME]),
        ("parameter_is_not_camera", SCENARIOS[15].question, []),
    ]:
        instruction = ("从用户请求提取部门编码、功能标识和明确提到的摄像头名称。参数名不是摄像头名称。"
                       "未提摄像头时 camera_names=[]；只输出严格 JSON。目录：" + json.dumps(catalog, ensure_ascii=False)
                       + "\n输出 Schema：" + json.dumps(Target.model_json_schema(), ensure_ascii=False))
        cases.append({"name": "resource_" + name, "kind": "resource", "json_mode": True, "schema": Target,
                      "expected": {"department": DEPARTMENT, "feature": FEATURE, "camera_names": cameras},
                      "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": question}]})
    for name, question, assignments in [
        ("single", SCENARIOS[3].question, [{"path": "value.threshold", "operation": "set", "value": 0.8}]),
        ("double", SCENARIOS[4].question, [{"path": "value.threshold", "operation": "set", "value": 0.8},
                                           {"path": "value.cap_interval", "operation": "set", "value": 0.2}]),
        ("relative", "当前讨论的是非法闯闸人体置信度0.5。把这个阈值调低一点。",
         [{"path": "value.threshold", "operation": "decrease", "value": None}]),
    ]:
        instruction = ("提取用户明确要求修改的参数；不补充其他参数。相对调整未给出数值时 value=null，不猜测。"
                       "检测间隔对应 value.cap_interval。只输出严格 JSON。业务 Schema：" + schema_text
                       + "\n输出 Schema：" + json.dumps(Parameters.model_json_schema(), ensure_ascii=False))
        cases.append({"name": "parameter_" + name, "kind": "parameter", "json_mode": True, "schema": Parameters,
                      "expected": {"assignments": assignments},
                      "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": question}]})
    cases.append({"name": "structured_tool", "kind": "tool", "json_mode": True,
                  "response_schema": AgentDecision.model_json_schema(),
                  "messages": [{"role": "system", "content": "只输出一个修改配置工具 JSON，不要其他文字。工具参数 Schema："
                                + json.dumps(UpdateArguments.model_json_schema(), ensure_ascii=False)
                                + "\n外层 Schema：" + json.dumps(AgentDecision.model_json_schema(), ensure_ascii=False)},
                               {"role": "user", "content": f"已读取资源 {RESOURCE}，revision={'a' * 64}。"
                                "仅将 value.threshold 改为0.8。action 必须为 update_configurations。"}],
                  "expected": {"changes": [{"resource_key": RESOURCE, "expected_revision": "a" * 64,
                                             "patch": {"value": {"threshold": 0.8}}}]}})
    return cases


def run_model_case(case, client, settings, repeat):
    from AiVision.assistant.responses import completion_content, json_content
    from AiVision.assistant.schema import AgentDecision
    from AiVision.assistant.tools import UpdateArguments
    from AiVision.core.settings import settings as application_settings

    started = time.perf_counter()
    row = {"scenario": case["name"], "label": case["name"], "repeat": repeat, "model_calls": 1,
           "real_model_calls": 1, "json_ok": [], "failure_layers": [], "errors": []}
    try:
        schema = case.get("response_schema") or (case["schema"].model_json_schema() if "schema" in case else None)
        row["requested_response_format"] = "json_schema" if schema is not None else "json_object" if case["json_mode"] else "text"
        raw, _ = client.complete(base_url=settings["base_url"], model=settings["model"], messages=case["messages"],
                                 max_tokens=min(application_settings.runtime.assistant_plan_max_tokens, settings["max_tokens"]) if case["kind"] == "classification" else settings["max_tokens"],
                                 temperature=settings["temperature"], timeout=settings["timeout"], json_mode=case["json_mode"],
                                 response_schema=schema)
        row["response_metadata"] = response_statistics(raw)
        if case["json_mode"]:
            syntax_ok = json_validity(raw)
            if syntax_ok is not None:
                row["json_ok"] = [syntax_ok]
        content = completion_content(raw)
        if case["kind"] == "chat":
            row["behavior_ok"] = any(token in content for token in ("你好", "您好", "嗨", "哈喽")) and not any(
                token in content for token in ('"action"', "尚未完成", "已删除摄像头", "已保存配置"))
        elif case["kind"] == "classification":
            plan = case["validate"](raw)
            row["schema_output_ok"] = True
            row["first_plan_valid"] = True
            row["classification_ok"] = plan.mode == case["expected"]
            row["planning_operations_ok"] = set(plan.operations) == ({"update_configurations"} if case["expected"] == "change" else set())
            row["query_goal_ok"] = plan.query_tool == case["query_tool"]
            row["behavior_ok"] = row["classification_ok"] and row["planning_operations_ok"] and row["query_goal_ok"]
        elif case["kind"] in {"resource", "parameter", "format"}:
            value = case["schema"].model_validate_json(json_content(content)).model_dump()
            row["schema_output_ok"] = True
            if case["kind"] == "parameter":
                value["assignments"].sort(key=lambda item: item["path"])
                expected = deepcopy(case["expected"])
                expected["assignments"].sort(key=lambda item: item["path"])
            else:
                expected = case["expected"]
            if case["kind"] != "format":
                row["resource_ok" if case["kind"] == "resource" else "parameter_ok"] = value == expected
            row["behavior_ok"] = value == expected
        else:
            # 诊断不能将生产解析器允许的普通答复当成符合工具输出合同。
            decision = AgentDecision.model_validate_json(json_content(content))
            row["schema_output_ok"] = True
            row["tool_selection_ok"] = decision.action == "update_configurations"
            arguments = UpdateArguments.model_validate(decision.arguments).model_dump()
            row["parameter_ok"] = arguments == case["expected"]
            row["behavior_ok"] = row["tool_selection_ok"] and row["parameter_ok"]
    except Exception as exc:
        row["errors"] = [type(exc).__name__]
        categories = {"ValidationError": "schema_validation", "ValueError": "json_syntax",
                      "QwenResponseError": "response_envelope", "QwenTruncatedError": "output_truncated"}
        row["error_category"] = getattr(exc, "category", categories.get(type(exc).__name__, "service_or_transport"))
        if type(exc).__name__ == "ValidationError" and row["json_ok"] == [False]:
            row["error_category"] = "json_syntax"
        if hasattr(exc, "issues"):
            row["validation_issues"] = exc.issues
        row["behavior_ok"] = False
        metric = {"classification": "classification_ok", "resource": "resource_ok", "parameter": "parameter_ok",
                  "tool": "tool_selection_ok"}.get(case["kind"])
        service_failed = type(exc).__name__ in {"QwenNetworkError", "QwenTimeoutError", "QwenServiceError"}
        if case["json_mode"] and "schema_output_ok" not in row:
            row["schema_output_ok"] = None if service_failed else False
        if metric:
            row[metric] = None if service_failed else False
        if case["kind"] == "classification":
            row["planning_operations_ok"] = None if service_failed else False
            row["first_plan_valid"] = None if service_failed else False
        row["failure_layers"] = ["model_service" if service_failed else "model_output"]
    if not row["behavior_ok"] and not row["failure_layers"]:
        row["failure_layers"] = ["model_output"]
    row["duration_seconds"] = round(time.perf_counter() - started, 6)
    return row


TOOL_PROBES = ("resource_matching", "partial_update", "schema_range", "schema_type", "schema_unknown",
               "missing_read", "stale_version", "permission_denied", "readback_changed", "postcommit_error")


def run_tool_probe(name, settings):
    from AiVision.assistant.schema import ConfigurationChange
    from AiVision.core.config_revision import configuration_revision

    started = time.perf_counter()
    scenario = next(case for case in SCENARIOS if case.name == ("permission" if name == "permission_denied" else "single"))
    with isolated_platform(scenario, **settings) as sandbox:
        turn = sandbox.service.enqueue(sandbox.session_id, str(__import__("uuid").uuid4()), scenario.question, sandbox.user)
        tool = ObservedTools(sandbox, turn_id=turn.id, session_id=sandbox.session_id, department=DEPARTMENT,
                             load_user=lambda: sandbox.user, sources=sandbox.runtime.sources, orchestrator=None,
                             check_cancel=lambda: None)
        expected = deepcopy(sandbox.before)
        observed_error = None
        result = None
        if name == "resource_matching":
            result = tool.run("list_resources", {"kind": "feature", "department": "通用电气事业部", "feature": FEATURE, "query": "诊断闸机"})
            behavior_ok = result["total"] == 2 and all(item["department"] == DEPARTMENT for item in result["items"])
        else:
            revision = configuration_revision(sandbox.before[RESOURCE])
            if name != "missing_read":
                read = tool.run("read_configurations", {"resource_keys": [RESOURCE]})
                revision = read["items"][0]["revision"]
            delta = {"value": {"threshold": 0.8}}
            if name == "schema_range":
                delta["value"]["threshold"] = 1.5
            elif name == "schema_type":
                delta["value"]["threshold"] = "0.8"
            elif name == "schema_unknown":
                delta = {"value": {"人体置信度": 0.8}}
            elif name == "stale_version":
                sandbox.set_threshold(101, 0.6)
                expected[RESOURCE]["value"]["threshold"] = 0.6
            original_save = sandbox.feature_manager.save_config

            def save_with_fault(*args, **kwargs):
                value = original_save(*args, **kwargs)
                if name == "readback_changed":
                    sandbox.set_threshold(101, 0.65)
                if name == "postcommit_error":
                    raise RuntimeError("诊断注入提交后刷新异常")
                return value

            with patch.object(sandbox.feature_manager, "save_config", save_with_fault):
                try:
                    result = tool.run("update_configurations", {"changes": [ConfigurationChange(
                        resource_key=RESOURCE, expected_revision=revision, patch=delta).model_dump()]})
                except Exception as exc:
                    observed_error = type(exc).__name__
            if name in {"partial_update", "postcommit_error", "readback_changed"}:
                expected[RESOURCE]["value"]["threshold"] = 0.65 if name == "readback_changed" else 0.8
                status = result["results"][0]["status"] if result else None
                behavior_ok = observed_error is None and status == ("changed" if name == "readback_changed" else "saved")
            else:
                expected_error = "ValidationError" if name.startswith("schema_") else (
                    "HTTPException" if name == "permission_denied" else "ConfigurationConflict")
                behavior_ok = observed_error == expected_error and not sandbox.service.actions(turn.id)
        configuration_ok = sandbox.snapshot() == expected
        return {"scenario": name, "label": name, "behavior_ok": bool(behavior_ok and configuration_ok),
                "configuration_ok": configuration_ok, "resource_ok": bool(behavior_ok) if name == "resource_matching" else None,
                "tool_execution_ok": [entry["ok"] for entry in sandbox.trace], "errors": [observed_error] if observed_error else [],
                "injected_faults": [name] if name in {"stale_version", "readback_changed", "postcommit_error"} else [],
                "model_calls": 0, "real_model_calls": 0, "duration_seconds": round(time.perf_counter() - started, 6),
                "failure_layers": [] if behavior_ok and configuration_ok else ["business_execution"],
                "business_storage": "temporary_sqlite", "status": "passed" if behavior_ok and configuration_ok else "failed"}


CHAIN = (
    ("消息接收", "MessageCreate、账号、会话、request_id", "脱敏正文、排队任务", "submit/duplicate/enqueue", "422、403、409、429；重复请求返回原轮次", "已有输入、权限保护；诊断补幂等及隔离持久化"),
    ("任务分类", "当前消息、有界上下文、RequestPlan Schema", "chat/query/change、操作类别、查询结果工具", "_plan_request/parse_plan", "Schema 约束；仅格式及字段错误纠正一次，共用分类超时预算", "严格 Schema、格式纠正、取消和超时；真实模型准确率需 A 层"),
    ("模型传输", "messages、模型名、生成参数、JSON 模式", "Chat Completions 响应和耗时", "QwenClient.complete", "共享并发名额；区分网络、超时、服务错误；不自动重试", "已有请求体、并发、名额回收及错误脱敏"),
    ("工具选择", "工具目录、历史、累计工具结果", "AgentDecision", "_execute/parse_decision", "工具格式错误纠正一次；未执行就结束会提醒一次；工具类别受计划约束", "已有模拟调度；B/D 检查连续调用和结果传递"),
    ("工具执行", "工具参数、当前权限、资源目录", "资源、Schema、revision 或错误", "AssistantTools.run/catalog", "严格工具参数；每次校验权限；异常转安全错误进入模型", "已有部分匹配和版本检查；C 补真实事务和回读"),
    ("配置保存", "resource_key、读取版本、局部 patch", "业务事务及审计记录", "update/ConfigurationResource.prepare/save_config", "读版本、当前版本、事务内期望值三层核对；逐资源事务；保留其他字段", "C/D 使用真实 Schema、ORM、事务，缓存及事件为替身"),
    ("结果核验", "保存后的数据库配置、期望配置", "saved/changed/failed/unknown/unchanged", "AssistantTools.update/finish_action", "提交后报错仍回读；结果不明确不盲重放", "C 检查回读变化及提交后异常；SQLite 不证明 MySQL 行锁"),
    ("用户答复", "分类、真实工具结果、审计", "最终状态和正文", "ExecutionOutcome.answer/query_answer", "查询须满足计划目标及分页；配置结果依据审计，变更类别仍不代表完整目标清单", "D 验证错误最终正文；额外探针验证部分完成与恢复状态"),
    ("多轮与取消", "最近完成轮次、操作记录、取消标志", "新的上下文或停止状态", "conversation/_execute/cancel/cancelled", "独立问候隔离历史；澄清结束当前轮次；取消在调用前后及工具边界检查", "已有问候隔离；D 验证指代、续办和取消；不验证中断在途 HTTP"),
)


def markdown_report(report):
    lines = ["# 福达 AI 助手分层诊断报告", "", f"生成时间：{report['generated_at']}；源码提交：`{report['revision']}`。",
             f"实际源码指纹：`{report.get('source_fingerprint', '未记录')}`；压缩包覆盖部署时以实际源码指纹核对版本。", "",
             "生产业务数据库未接入诊断。业务数据为临时 SQLite 中的三台虚构摄像头；缓存刷新和运行事件使用替身。真实模型只接收固定虚构输入。",
             "", "## 当前调用链", "", "| 阶段 | 输入 | 输出 | 代码入口 | 异常处理 | 覆盖情况 |", "|---|---|---|---|---|---|"]
    lines.extend("| " + " | ".join(stage) + " |" for stage in CHAIN)
    inspection = report.get("service_inspection")
    if inspection is not None:
        lines.extend(["", "## 模型服务身份与合同证据", "",
                      "监听进程与安装包版本只在目标为本机时采集；代理进程、候选环境安装包和 HTTP Server 头均不能单独证明实际推理引擎。",
                      "application_version 为 OpenAPI 应用版本，不等同于推理运行库版本。请求字段声明和入口源码关键词不证明真实透传，需结合固定探针及服务实现确认。",
                      "无显式解码启动标志不等于禁用解码；输出长度缺少 usage 或对照不足时标记 inconclusive，不假称通过。",
                      "以下元数据仅包含脱敏标记、固定字段、版本和代码摘要：", "", "```json",
                      json.dumps(inspection, ensure_ascii=False, indent=2), "```", ""])
    lines.extend(["", "## 方法与统计口径", "",
                  f"每例重复 {report['settings']['repeats']} 次；temperature={report['settings']['temperature']}，业务生成上限 {report['settings']['max_tokens']}，分类上限 {report.get('runtime_limits', {}).get('assistant_plan_max_tokens', '未记录')} tokens，单次超时 {report['settings']['timeout']} 秒。",
                  "模型层直接调用 Qwen，不经过 Agent；Agent 模拟层使用固定模型输出和模拟业务工具；业务层直接调用真实保存服务；端到端层运行真实 submit、runtime、工具、保存及审计。",
                  "脚本端到端用于判断程序行为，真实模型端到端用于判断自然语言实际成功率，两者分开统计。故障注入单独标记，不能归因为模型自然故障。",
                  "端到端任务成功率统计预期可完成的聊天、查询及明确合法的配置请求，不等于配置写入成功次数；越界、无权限、故障、歧义、取消另计预期处理行为通过率。",
                  "JSON 有效率按结构化响应尝试计数；聊天正文不计入分母。工具执行成功率按实际调用计数，预期拒绝和故障注入也会降低该值，不能单独据此判断业务服务质量。",
                  "输出合同通过率独立于业务语义正确率：合法 JSON 仍须通过对应 Pydantic Schema。已有可见目标引用可以直接读取，工具选择不强制重复搜索；本轮仍须读取全部预期目标及新版本，猜测标识或漏读目标不能通过。",
                  "平均模型调用次数包括分类、纠正和业务请求；模型替身及故障注入不等于实际网络调用，结果中另有 real_model_calls。耗时为本次环境实测，不代表生产吞吐。",
                  "本工具同步投递任务，保留 submit、幂等和取消流程；不验证线程池压力、MySQL 行锁、GPU、摄像头连通或运行层热更新效果。",
                  "", "## 分层结果", ""])
    for name, layer in report["layers"].items():
        lines.extend([f"### {name}", "", f"状态：{layer['status']}。{layer.get('reason', '')}", ""])
        if not layer.get("rows"):
            lines.append("未执行，不提供准确率或成功率。")
            lines.append("")
            continue
        summary = layer["summary"]
        lines.extend([f"样本数 {summary['samples']}；平均模型调用 {summary['average_model_calls']} 次；平均耗时 {summary['average_seconds']} 秒。",
                      "", "| 指标 | 通过/适用样本 | 比例 |", "|---|---|---|"])
        for value in summary["metrics"].values():
            rate = f"{value['rate'] * 100:.2f}%" if value["rate"] is not None else "不适用"
            lines.append(f"| {value['label']} | {value['passed']}/{value['total']} | {rate} |")
        lines.extend(["", "| 场景 | 预期行为通过/运行次数 | 故障归属 | 错误类别 | 人工注入 |", "|---|---|---|---|---|"])
        for scenario in dict.fromkeys(row["scenario"] for row in layer["rows"]):
            rows = [row for row in layer["rows"] if row["scenario"] == scenario]
            faults = sorted({item for row in rows for item in row.get("failure_layers", [])})
            errors = sorted({item for row in rows for item in row.get("errors", [])})
            injected = sorted({item for row in rows for item in row.get("injected_faults", [])})
            lines.append(f"| {rows[0]['label']} | {sum(row.get('behavior_ok', False) for row in rows)}/{len(rows)} | {', '.join(faults) or '无'} | {', '.join(errors) or '无'} | {', '.join(injected) or '无'} |")
        lines.append("")
        if name == "service":
            lines.extend(["服务探针每项重复三次以上，串行复用 QwenClient 的超时与并发名额。非法 Schema 探针预期 HTTP 400/422，符合预期的拒绝不是服务故障。",
                          "格式探针分别检查 JSON 对象及固定 Schema；长度探针对照相同输入的 128 与 1 token 请求。结果只能核对客户端可见行为，不能仅据此确定转发层还是解码层丢失了参数。", "",
                          "| 探针 | 重复 | 状态 | HTTP | 请求 Token 上限 | 实际输出 Tokens |",
                          "|---|---|---|---|---|---|"])
            for row in layer["rows"]:
                tokens = row.get("response_metadata", {}).get("completion_tokens", "未提供")
                lines.append(f"| {row['scenario']} | {row['repeat']} | {row.get('probe_status', '未知')} | {row.get('http_status')} | {row.get('requested_max_tokens')} | {tokens} |")
            lines.append("")
        if name == "model":
            lines.extend(["格式探针分别使用与 Schema 一致、与 Schema 冲突的固定提示，检查 HTTP 接受请求后实际返回的格式；不调用任何业务工具。",
                          "探针通过只证明这些样例符合约束，不证明服务支持所有 Schema。失败需结合服务实现、模板和模型输出排查，不能单独归因为模型理解能力。",
                          "has_thinking 包括空的 <think> 标签；thinking_characters 和 reasoning_characters 只统计字符数，不保存正文，也不能据此确认服务启动设置。", "",
                          "| 场景 | 输出合同通过/适用次数 | 回复格式 | 对象结构 | 非空思考内容次数 |",
                          "|---|---|---|---|---|"])
            for scenario in dict.fromkeys(row["scenario"] for row in layer["rows"]):
                samples = [row for row in layer["rows"] if row["scenario"] == scenario]
                contracts = [row["schema_output_ok"] for row in samples if isinstance(row.get("schema_output_ok"), bool)]
                metadata = [row.get("response_metadata", {}) for row in samples]
                formats = sorted({item.get("answer_format", "未记录") for item in metadata})
                shapes = sorted({item["object_shape"] for item in metadata if "object_shape" in item})
                thinking = sum(bool(item.get("thinking_characters", 0) or item.get("reasoning_characters", 0)) for item in metadata)
                lines.append(f"| {samples[0]['label']} | {sum(contracts)}/{len(contracts)} | {', '.join(formats)} | {', '.join(shapes) or '不适用'} | {thinking} |")
            lines.append("")
        if name.startswith("conversation-"):
            groups = {(row["conversation"], row["repeat"]) for row in layer["rows"] if "conversation" in row}
            successful = 0
            for group in groups:
                completed = [row for row in layer["rows"] if (row.get("conversation"), row.get("repeat")) == group]
                successful += len(completed) == completed[0]["conversation_total_turns"] and all(row["behavior_ok"] for row in completed)
            lines.extend([f"完整连续对话通过：{successful}/{len(groups)} 组。", "",
                          "| 对话及轮次 | 最大请求字符数 | 服务返回的最大输入 Tokens | 历史对数 | 原始目标绑定片段可见 |",
                          "|---|---|---|---|---|"])
            for scenario in dict.fromkeys(row["scenario"] for row in layer["rows"]):
                samples = [row for row in layer["rows"] if row["scenario"] == scenario]
                tokens = [row["max_prompt_tokens"] for row in samples if row.get("max_prompt_tokens") is not None]
                lines.append(f"| {samples[0]['label']} | {max(row.get('max_request_characters', 0) for row in samples)} | "
                             f"{max(tokens) if tokens else '服务未提供/未调用真实模型'} | "
                             f"{max(row.get('history_pairs', 0) for row in samples)} | "
                             f"{samples[0].get('anchor_in_history')} |")
            lines.append("")
            failed = [row for row in layer["rows"] if not row.get("behavior_ok")]
            if failed:
                lines.extend(["目标核验失败证据（每个场景取首个失败样本）：", "",
                              "只记录引用类别、固定虚构词类别、匹配数量及资源是否来自真实搜索；不记录名称、资源 key、原文或配置。",
                              "已声明代号的查询必须实际读取，首次绑定未建立后的澄清不能计为跨窗口成功。", ""])
                for scenario in dict.fromkeys(row["scenario"] for row in failed):
                    row = next(item for item in failed if item["scenario"] == scenario)
                    planning = next((item for item in row.get("request_statistics", []) if item["kind"] == "planning"), {})
                    evidence = {"scenario": scenario, "binding_prerequisite_ok": row.get("binding_prerequisite_ok"),
                                "planning": planning.get("target_context_evidence"), "tools": row.get("target_evidence")}
                    lines.extend(["```json", json.dumps(evidence, ensure_ascii=False, indent=2), "```", ""])
    lines.extend(["## 失败证据与归属", "",
                  "JSON 及严格分类 Schema 失败归入 model_output；网络/超时/模型服务错误归入 model_service，不计为模型理解错误。",
                  "固定模型已给出可解析指令，但额外字段或未完成目标未被约束，归入 agent_scheduling；真实保存、校验或回读不符归入 business_execution；最终状态与实际配置不符归入 result_reporting。",
                  "真实模型触发 TargetClarification 时标记 target_resolution；须结合选择器匹配数量与资源来源区分模型标识错误和后台误拦，不能仅凭异常类型归责模型。如实澄清不等于任务完成，尚未发出修改指令时不评价参数提取。",
                  "额外探针主动提交合法但偏离用户意图的指令，检验后端约束能力；探针失败不代表真实模型必然产生同类指令。探针仍通过才说明相应约束有效。",
                  "失败记录只保留场景编号、错误类型、固定类别、数量、布尔指标及工具名称。完整请求、响应和认证头均不写入报告。",
                  ""])
    probe_explanations = {
        "extra_field": "请求仅包含人体置信度，但实际保存包含其他字段；当前工具校验合法字段及版本，未将 patch 限制在用户请求字段内。",
        "partial_batch": "请求覆盖两个目标，实际仅完成其中一个；完成集合按工具类别记账，没有核对完整目标清单。",
        "recovered_tool_error": "检索错误已纠正，配置和审计已保存，但本轮仍报失败；工具错误一直保留在 outcome.errors 中。",
    }
    for layer in report["layers"].values():
        for row in layer.get("rows", []):
            if row.get("repeat", 1) != 1 or row.get("behavior_ok", False):
                continue
            explanation = probe_explanations.get(row["scenario"])
            if explanation:
                lines.extend([f"- {row['label']}：{explanation} 证据：`{json.dumps(row.get('evidence', {}), ensure_ascii=False)}`", ""])
    recommendations = [
        "核验实际模型服务的 JSON Schema 与非思考模式，分别分析首次规划、纠正成功、截断和服务超时，不能只比较最终成功率。",
        "将配置意图约束到具体资源、字段和目标值，在写入前校验 patch 与完整目标集合，保留现有权限、版本及审计。",
        "按目标逐项核对配置任务完成情况，区分已恢复与未恢复的工具错误，并以实际 Qwen 多轮结果验证上下文及异常恢复。",
    ]
    if any("TargetClarification" in row.get("errors", []) for layer in report["layers"].values() for row in layer.get("rows", [])):
        recommendations[:2] = [
            "优先核对目标拦截证据：引用类别、选择器匹配数量、真实搜索结果与请求资源来源。证据不足时不能把后台误拦和模型选错标识混为一谈。",
            "先验收首次绑定建立，再验证跨窗口读取和重述恢复；前置绑定失败后的澄清不能计为已声明代号查询成功。",
        ]
    lines.extend(["## 证据不足", "",
                  "缺少或不可达的模型层会标记 blocked，不以脚本模型结果代替。即使全部虚构样例通过，也不能证明所有自然语言表达和生产部署均可靠。",
                  "Qwen 的 API model 标识不能证明实际权重、量化、chat template 或启动参数；本诊断不修改或验证模型权重。",
                  "SQLite 用于验证事务结果、字段校验和版本逻辑，不覆盖 MySQL 的锁竞争、死锁重试及生产数据规模。",
                  "多轮测试在同一 session 内持续 10～13 轮，分别覆盖混合任务、历史窗口和重复完整配置查询。逐轮记录模型请求字符数；Token 数只采用服务 usage，不进行估算。",
                  "历史同时受轮数和字符预算限制，规划历史不含助手答复正文，短期目标引用和待澄清任务按权限可见性隔离。工具观察单独按 60000 字符裁剪。片段可见性不证明完整语义记忆。",
                  "前端 sendAssistantMessage 只提交 request_id/text，由 useAssistant 复用 sessionId；源码未发现第 4 或第 5 轮的固定上限。本工具不运行浏览器，不能排除轮询、页面挂载或会话切换故障。",
                  "", "## 优先级最高的三项建议", "",
                  *[f"{number}. {item}" for number, item in enumerate(recommendations, 1)],
                  "", "建议应结合各层实测结果排序；未运行的层不支持对模型优劣作结论。", ""])
    return "\n".join(lines)


def run(args, progress=print, checkpoint=None):
    settings = {"base_url": args.base_url or "http://127.0.0.1:18100/v1", "model": args.model,
                "max_tokens": args.max_tokens, "timeout": args.timeout, "temperature": args.temperature}
    revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[3], check=False).stdout.strip() or "unknown"
    root = Path(__file__).resolve().parents[3]
    sources = [*root.joinpath("AiVision/assistant").glob("*.py"), *Path(__file__).parent.glob("*.py"),
               root / "AiVision/connectors/qwen/client.py", root / "AiVision/core/settings.py"]
    fingerprint = hashlib.sha256()
    # 覆盖压缩包不会更新 Git HEAD，需用实际源码指纹区分服务器执行的版本。
    for source in sorted(sources):
        fingerprint.update(str(source.relative_to(root)).encode("utf-8") + b"\0" + source.read_bytes() + b"\0")
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "revision": revision,
              "source_fingerprint": fingerprint.hexdigest(),
              "environment": {"python": system_platform.python_version(), **{name: importlib.metadata.version(name)
                              for name in ("pydantic", "sqlalchemy", "requests")}},
              "settings": {"model": args.model, "repeats": args.repeats, "temperature": args.temperature,
                           "max_tokens": args.max_tokens, "timeout": args.timeout}, "layers": {}}
    with diagnostic_environment():
        from AiVision.assistant.schema import AssistantSettings, RequestPlan
        from AiVision.assistant.runtime import PLANNING_PROMPT
        from AiVision.connectors.qwen.client import QwenClient
        from AiVision.core.settings import settings as application_settings

        report["runtime_limits"] = {key: getattr(application_settings.runtime, key) for key in (
            "assistant_max_rounds", "assistant_max_changes", "assistant_history_turns", "assistant_workers",
            "assistant_queue_capacity", "qwen_max_concurrent_requests", "assistant_plan_max_tokens", "assistant_history_max_chars")}
        AssistantSettings(base_url=settings["base_url"], model=args.model, max_tokens=args.max_tokens,
                          api_timeout_sec=args.timeout, temperature=args.temperature)
        live_unavailable = None
        if args.base_url and set(args.layers.split(",")) & {"model", "e2e-live", "conversation-live"}:
            progress("[连接检查] 使用固定虚构问候验证模型服务，不读取生产业务数据。")
            preflight_stage = "连接"
            try:
                QwenClient().complete(base_url=settings["base_url"], model=args.model,
                    messages=[{"role": "user", "content": "你好，请简短回复。"}], max_tokens=128,
                    temperature=args.temperature, timeout=args.timeout, json_mode=False)
                preflight_stage = "JSON Schema 请求"
                progress("[连接检查] 检查服务是否接受 JSON Schema 请求，格式正确率仍按实际场景统计。")
                QwenClient().complete(base_url=settings["base_url"], model=args.model,
                    messages=[{"role": "system", "content": PLANNING_PROMPT + json.dumps(RequestPlan.model_json_schema(), ensure_ascii=False)},
                              {"role": "user", "content": "查询可用检测功能"}],
                    max_tokens=min(args.max_tokens, application_settings.runtime.assistant_plan_max_tokens),
                    temperature=0.0, timeout=args.timeout, json_mode=True,
                    response_schema=RequestPlan.model_json_schema())
            except Exception as exc:
                live_unavailable = preflight_stage + "未完成：" + type(exc).__name__
        for layer in args.layers.split(","):
            rows = []
            descriptions = {
                "service": "只读服务身份与接口合同检查；固定格式和输出长度探针，不访问业务数据库。",
                "agent": "固定模型与模拟业务工具；配置核验只对应虚构字典，不代表数据库保存能力。",
                "tools": "真实业务工具、Schema、ORM、事务和回读；存储为临时 SQLite。",
                "e2e-scripted": "固定模型与真实业务工具；只证明程序流程，不证明模型理解能力。",
                "e2e-live": "真实 Qwen 与真实业务工具；业务写入仍只在临时 SQLite。",
                "model": "直接调用真实 Qwen，不经过 Agent 分类或工具循环。",
                "probes": "主动模拟偏离意图或恢复异常的输出，检查 Agent 约束。",
                "conversation-scripted": "固定模型，在同一会话持续 10～13 轮；验证历史传递和连续保存。",
                "conversation-live": "真实模型，在同一会话持续 10～13 轮；重点观察第 4～6 轮及历史窗口边界。",
            }
            report["layers"][layer] = {"status": "running", "reason": descriptions[layer], "rows": rows, "summary": aggregate(rows)}

            def record(row):
                rows.append(row)
                report["layers"][layer]["summary"] = aggregate(rows)
                if checkpoint:
                    checkpoint(report)

            if layer in {"model", "e2e-live", "conversation-live"} and not args.base_url:
                report["layers"][layer] = {"status": "blocked", "reason": "未显式提供 --base-url，未连接任何模型服务。", "rows": []}
                continue
            if layer in {"model", "e2e-live", "conversation-live"} and live_unavailable:
                report["layers"][layer] = {"status": "blocked", "reason": "模型" + live_unavailable,
                                           "rows": []}
                continue
            if layer == "service":
                if not args.base_url:
                    report["layers"][layer] = {"status": "blocked", "reason": "未显式提供 --base-url，未检查任何模型服务。", "rows": []}
                    continue
                from .service import run_service_probes, service_metadata
                progress("[service] 只读采集监听进程、版本接口及 OpenAPI；不保存原始命令行或响应正文。")
                report["service_inspection"] = service_metadata(settings)
                if checkpoint:
                    checkpoint(report)
                run_service_probes(settings, args.repeats, record, progress)
            elif layer == "model":
                for case in model_cases():
                    for repeat in range(1, args.repeats + 1):
                        record(run_model_case(case, QwenClient(), settings, repeat))
                        progress(f"[{layer}] {case['name']} {repeat}/{args.repeats}: {'通过' if rows[-1]['behavior_ok'] else '失败'}")
            elif layer == "tools":
                for probe in TOOL_PROBES:
                    record(run_tool_probe(probe, settings))
                    progress(f"[{layer}] {probe}: {'通过' if rows[-1]['behavior_ok'] else '失败'}")
            elif layer.startswith("conversation-"):
                for name in args.conversations.split(","):
                    for repeat in range(1, args.repeats + 1):
                        run_conversation(name, repeat=repeat, live=layer == "conversation-live", on_row=record,
                                         progress=progress, **settings)
            else:
                if layer == "agent":
                    scenarios = [case for case in SCENARIOS if case.name in {"single", "double", "tool_error", "reference", "continuation"}]
                elif layer == "probes":
                    scenarios = PROBES
                else:
                    scenarios = SCENARIOS
                for case in scenarios:
                    for repeat in range(1, args.repeats + 1):
                        try:
                            result = run_dialogue(case, **settings, fake_tools=layer == "agent", live=layer == "e2e-live")
                        except Exception as exc:
                            result = {"scenario": case.name, "label": case.label, "behavior_ok": False,
                                      "errors": [type(exc).__name__], "failure_layers": ["diagnostic_harness"], "model_calls": 0}
                        result["repeat"] = repeat
                        record(result)
                        progress(f"[{layer}] {case.name} {repeat}/{args.repeats}: {'通过' if result['behavior_ok'] else '失败'}")
            report["layers"][layer] = {"status": "completed", "reason": descriptions[layer],
                                       "rows": rows, "summary": aggregate(rows)}
            if checkpoint:
                checkpoint(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="福达 AI 分层诊断；业务写入只使用临时 SQLite，不加载生产 .env")
    parser.add_argument("--base-url", default=os.environ.get("ASSISTANT_DIAGNOSTIC_BASE_URL"))
    parser.add_argument("--model", default=os.environ.get("ASSISTANT_DIAGNOSTIC_MODEL", "fuda-qwen38-27b"))
    parser.add_argument("--layers", default="service,model,agent,tools,e2e-scripted,e2e-live,probes,conversation-scripted,conversation-live")
    parser.add_argument("--conversations", default="mixed,window,pressure")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    allowed = {"service", "model", "agent", "tools", "e2e-scripted", "e2e-live", "probes", "conversation-scripted", "conversation-live"}
    if args.repeats < 3:
        parser.error("--repeats 至少为 3")
    if not set(args.layers.split(",")) <= allowed:
        parser.error("--layers 只能包含 " + ",".join(sorted(allowed)))
    if not set(args.conversations.split(",")) <= set(conversation_cases()):
        parser.error("--conversations 只能包含 mixed,window,pressure")
    args.output.mkdir(parents=True, exist_ok=True)

    def write_outputs(report):
        for name, content in {"results.json": json.dumps(report, ensure_ascii=False, indent=2),
                              "report.md": markdown_report(report)}.items():
            temporary = args.output / (name + ".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(args.output / name)

    try:
        report = run(args, progress=lambda message: print(message, flush=True), checkpoint=write_outputs)
    except KeyboardInterrupt:
        print("诊断已中断，已完成样本保存在输出目录，未完成层保留 running 状态。", flush=True)
        return 130
    except Exception as exc:
        print("诊断初始化失败，错误类别：" + type(exc).__name__, flush=True)
        if isinstance(exc, ModuleNotFoundError):
            print("缺少 Python 模块：" + str(exc.name), flush=True)
        return 2
    write_outputs(report)
    print("已生成脱敏 results.json 和 report.md", flush=True)
    harness_failed = any("diagnostic_harness" in row.get("failure_layers", [])
                         for layer in report["layers"].values() for row in layer.get("rows", []))
    return 2 if harness_failed else 0
