"""同一会话持续 10～13 轮，观察第 4～6 轮及六轮历史窗口之后的行为。"""
from copy import deepcopy
from dataclasses import dataclass, field
import json
import re
import time

from .cases import CAMERA_NAME, DEPARTMENT, FEATURE, RESOURCE, SECOND_CAMERA_NAME, SECOND_RESOURCE, Scenario
from .sandbox import MeasuredClient, ScriptedClient, completion, execute_turn, isolated_platform, observed_arguments


@dataclass(frozen=True)
class Step:
    label: str
    question: str
    mode: str
    kind: str
    targets: tuple[str, ...] = (RESOURCE,)
    delta: dict = field(default_factory=dict)
    anchor_expected: bool | None = None


def conversation_cases(history_turns=6):
    mixed = [
        Step("问候", "你好哇", "chat", "chat"),
        Step("功能查询", "查询当前可以使用的检测功能", "query", "capabilities"),
        Step("定位一号", f"查询通用电气事业部{CAMERA_NAME}非法闯闸的人体置信度", "query", "read"),
        Step("第4轮修改", "把刚才那台摄像头的非法闯闸人体置信度改为0.8", "change", "write", delta={"value": {"threshold": 0.8}}),
        Step("第5轮回查", "再查一下刚才那台摄像头的非法闯闸人体置信度", "query", "read"),
        Step("第6轮另一参数", "它的非法闯闸检测间隔也改为0.2秒", "change", "write", delta={"value": {"cap_interval": 0.2}}),
        Step("切换二号", f"换成通用电气事业部{SECOND_CAMERA_NAME}，查询非法闯闸人体置信度", "query", "read", targets=(SECOND_RESOURCE,)),
        Step("二号指代修改", "把它的非法闯闸人体置信度改为0.7", "change", "write", targets=(SECOND_RESOURCE,), delta={"value": {"threshold": 0.7}}),
        Step("明确批量", "把通用电气事业部两台诊断闸机的非法闯闸人体置信度都改为0.6", "change", "write",
             targets=(RESOURCE, SECOND_RESOURCE), delta={"value": {"threshold": 0.6}}),
        Step("任务后问候", "你好哇", "chat", "chat"),
        Step("明确回到一号", f"查询通用电气事业部{CAMERA_NAME}非法闯闸的人体置信度和检测间隔", "query", "read"),
        Step("模糊数值", "把这台摄像头的非法闯闸人体置信度调低一点", "change", "clarify_value"),
        Step("补充数值续办", "就改为0.55", "change", "write", delta={"value": {"threshold": 0.55}}),
    ]
    window = [Step("建立会话指代", "请记住：记忆代号甲对应诊断闸机一号。先查询通用电气事业部这台摄像头的非法闯闸人体置信度。", "query", "read")]
    fillers = ("你好哇", "谢谢你", "今天先聊一句", "明白了", "你能简单介绍一下自己吗", "嗯，收到")
    window.extend(Step(f"间隔闲聊{number + 1}", fillers[number % len(fillers)], "chat", "chat")
                  for number in range(max(6, history_turns)))
    window.extend([
        Step("历史窗口外指代", "查询记忆代号甲的非法闯闸人体置信度", "query", "clarify_target", anchor_expected=False),
        Step("重述目标后修改", "记忆代号甲对应诊断闸机一号。把通用电气事业部这台摄像头的非法闯闸人体置信度改为0.75。",
             "change", "write", delta={"value": {"threshold": 0.75}}),
        Step("重述后的指代回查", "再查一下这台摄像头的非法闯闸人体置信度", "query", "read", anchor_expected=True),
    ])
    pressure = [Step(f"完整配置查询{number}", "查询通用电气事业部两台诊断闸机的完整非法闯闸配置，不要修改。",
                     "query", "read", targets=(RESOURCE, SECOND_RESOURCE)) for number in range(1, 11)]
    return {"mixed": mixed, "window": window, "pressure": pressure}


class ConversationScriptedClient:
    """只验证程序在长期会话中能否正确传递历史，真实理解能力由 live 层测量。"""

    def __init__(self, sandbox):
        self.sandbox = sandbox

    def complete(self, **kwargs):
        step = self.sandbox.step
        if "只判断当前用户请求" in kwargs["messages"][0]["content"]:
            goal = ("capabilities" if step.kind == "capabilities" else "read_configurations") if step.mode == "query" else None
            return completion({"mode": step.mode, "operations": ["update_configurations"] if step.mode == "change" else [],
                               "query_tool": goal}), 0.0
        if not kwargs["json_mode"]:
            return completion("你好呀，我是福达AI助手，收到你的消息。"), 0.0
        last = kwargs["messages"][-1]["content"]
        if last.startswith("后台已查询"):
            if step.kind == "capabilities":
                return ScriptedClient.tool("capabilities", {})
            query = "诊断闸机" if len(step.targets) > 1 or step.kind == "clarify_target" else (
                SECOND_CAMERA_NAME if step.targets[0] == SECOND_RESOURCE else CAMERA_NAME)
            return ScriptedClient.tool("list_resources", {"kind": "feature", "department": DEPARTMENT, "feature": FEATURE, "query": query})
        if not last.startswith("工具执行结果"):
            return ScriptedClient.answer()
        data = json.loads(last.split("：", 1)[1])
        if "error" in data:
            return ScriptedClient.answer()
        if "items" in data and data["items"] and "key" in data["items"][0]:
            if step.kind == "clarify_target":
                return ScriptedClient.tool("ask_user", {"question": f"请确认是哪台摄像头：{CAMERA_NAME}还是{SECOND_CAMERA_NAME}？"})
            return ScriptedClient.tool("read_configurations", {"resource_keys": [item["key"] for item in data["items"] if item["key"] in step.targets]})
        if "items" in data and data["items"] and "resource" in data["items"][0]:
            if step.kind == "clarify_value":
                return ScriptedClient.tool("ask_user", {"question": "要把这台摄像头的人体置信度调低到哪个具体数值？"})
            if step.kind == "write":
                return ScriptedClient.tool("update_configurations", {"changes": [{"resource_key": item["resource"]["key"],
                    "expected_revision": item["revision"], "patch": step.delta} for item in data["items"]]})
        return ScriptedClient.answer()


def run_conversation(name, *, repeat=1, live=False, on_row=None, progress=None, **settings):
    from AiVision.assistant.responses import is_simple_greeting
    from AiVision.connectors.qwen.client import QwenClient
    from AiVision.core.settings import settings as application_settings

    steps = conversation_cases(application_settings.runtime.assistant_history_turns)[name]
    initial = Scenario("conversation", "持续多轮对话", steps[0].question, mode=steps[0].mode)
    rows = []
    with isolated_platform(initial, live=False, **settings) as sandbox:
        sandbox.phase = "conversation"
        sandbox.history_anchor = "记忆代号甲对应诊断闸机一号" if name == "window" else CAMERA_NAME
        if name == "window":
            sandbox.history_binding = ("记忆代号甲", CAMERA_NAME)
        delegate = QwenClient() if live else ConversationScriptedClient(sandbox)
        sandbox.client = MeasuredClient(sandbox, delegate, live=live)
        sandbox.runtime.client = sandbox.client
        for number, step in enumerate(steps, 1):
            sandbox.step = step
            sandbox.scenario = Scenario("conversation", step.label, step.question, mode=step.mode, patch=step.delta)
            if progress:
                progress(f"[conversation] {name} 第{repeat}组 第{number}/{len(steps)}轮开始")
                if live:
                    sandbox.model_progress = lambda kind, count: progress(f"[conversation] {name} 第{repeat}组 第{number}轮 {kind} 请求{count}")
            before = sandbox.snapshot()
            visible = sandbox.service.conversation(sandbox.session_id, sandbox.user)
            previous_context = sandbox.runtime.memory.get(sandbox.session_id, {turn.id for turn in visible.turns}) or {}
            expected = deepcopy(before)
            for key in step.targets if step.kind == "write" else ():
                expected[key]["value"].update(step.delta["value"])
            client = sandbox.client
            starts = (client.calls, client.real_calls, len(client.plans), len(client.json_results), len(client.requests),
                      len(sandbox.trace), len(client.errors))
            started = time.perf_counter()
            turn, _payload = execute_turn(sandbox, step.question)
            duration = time.perf_counter() - started
            actual = sandbox.snapshot()
            traces, requests = sandbox.trace[starts[5]:], client.requests[starts[4]:]
            planning_requests = [request for request in requests if request["kind"] == "planning"]
            binding_visible = planning_requests[0].get("binding_in_history") if planning_requests else None
            # 模型若在后续闲聊中明确复述过目标绑定，仍允许依据该可见片段完成查询。
            kind = "read" if step.kind == "clarify_target" and binding_visible else step.kind
            tools = [entry["tool"] for entry in traces]
            reads = [item for entry in traces if entry["tool"] == "read_configurations" and entry["ok"]
                     for item in entry["result"].get("items", [])]
            changes = observed_arguments(traces, "update_configurations", "changes", dict)
            plans = client.plans[starts[2]:]
            classification_ok = plans[-1] == step.mode if plans else step.mode == "chat" and is_simple_greeting(step.question)
            operations = client.plan_operations[starts[2]:]
            operations_ok = (set(operations[-1]) == ({"update_configurations"} if step.mode == "change" else set())
                             if operations else step.mode == "chat" and is_simple_greeting(step.question))
            configuration_ok = actual == expected
            resource_ok = None
            parameter_ok = None
            resolution_ok = None
            required = set()
            if kind in {"read", "write", "clarify_value"}:
                required = {"read_configurations"}
                known = {item["key"] for item in previous_context.get("last_read_resources", [])}
                searched = {item["key"] for entry in traces if entry["tool"] == "list_resources" and entry["ok"]
                            for item in entry["result"].get("items", [])}
                read_keys = {item["resource"]["key"] for item in reads}
                resolved = known | searched
                # 允许复用权限可见的目标引用，但配置与版本必须在本轮重新读取。
                # 固定用例没有直接给出资源 key，不能把猜中标识当作完成目标定位。
                resolution_ok = bool(read_keys) and read_keys <= resolved
                resource_ok = read_keys == set(step.targets) and resolution_ok
                resource_ok &= all(item["config"] == before.get(item["resource"]["key"]) for item in reads)
            if kind == "clarify_value":
                # 已定位目标后询问具体值无需再次读配置；真正写入仍必须重新读取版本。
                known = {item["key"] for item in previous_context.get("last_read_resources", [])}
                known.update(item["resource"]["key"] for item in reads)
                questions = [entry["arguments"].get("question", "") for entry in traces
                             if entry["tool"] == "ask_user" and entry["ok"]]
                asks_value = any(re.search(r"数值|多少|具体值|调低到", text) and not re.search(
                    r"哪台|哪个摄像头|选择.*摄像头|完整名称|所属部门|资源.?ID", text, re.IGNORECASE,
                ) for text in questions if isinstance(text, str))
                resource_ok = known == set(step.targets) and asks_value
                resource_ok &= all(item["resource"]["key"] in step.targets for item in reads)
                resolution_ok = set(step.targets) <= resolved
                resource_ok &= resolution_ok
                required = {"ask_user"}
            if step.kind == "write":
                required.add("update_configurations")
                resource_ok &= all(isinstance(item.get("resource_key"), str) for item in changes)
                resource_ok &= {item.get("resource_key") for item in changes if isinstance(item.get("resource_key"), str)} == set(step.targets)
                parameter_ok = bool(changes) and all(item["patch"] == step.delta for item in changes)
            if kind.startswith("clarify"):
                required.add("ask_user")
            if step.kind == "capabilities":
                required.add("capabilities")
            tool_ok = required <= set(tools)
            if step.kind == "write":
                success = "已保存配置" in turn.answer or "已是目标值" in turn.answer
                report_ok = (turn.status == "completed" and success) if configuration_ok else (turn.status == "failed" and not success)
            elif step.kind == "chat":
                report_ok = turn.status == "completed" and bool(turn.answer) and not tools and not any(
                    word in turn.answer for word in ("尚未完成", "已保存配置", "已删除摄像头", '"action"'))
            else:
                report_ok = turn.status == "completed" and not sandbox.service.actions(turn.id) and tool_ok
            behavior_ok = classification_ok and operations_ok and configuration_ok and tool_ok and report_ok and resource_ok is not False and parameter_ok is not False
            anchor_visible = planning_requests[0].get("anchor_in_history") if planning_requests else None
            failure_layers = []
            if not classification_ok or not operations_ok or resource_ok is False or parameter_ok is False or not tool_ok:
                failure_layers.append("model_output" if live else "agent_scheduling")
            if not configuration_ok:
                failure_layers.append("agent_scheduling" if changes else "model_output" if live else "agent_scheduling")
            if not report_ok:
                failure_layers.append("result_reporting")
            if step.anchor_expected is False and anchor_visible is False and not binding_visible:
                failure_layers.append("context_transfer")
            errors = sorted(set(client.errors[starts[6]:] + [entry["error_type"] for entry in traces if "error_type" in entry]))
            service_failed = any(error in {"QwenNetworkError", "QwenTimeoutError", "QwenServiceError"} for error in errors)
            if service_failed:
                failure_layers = ["model_service"] + (["result_reporting"] if not report_ok else [])
                if not plans:
                    classification_ok = None
                    operations_ok = None
                if not reads:
                    resource_ok = None
                if not traces or tools == ["capabilities"]:
                    tool_ok = None
            row = {"scenario": f"{name}_{number:02d}", "label": f"{name} 第{number}轮：{step.label}", "conversation": name,
                   "repeat": repeat, "turn_index": number, "conversation_total_turns": len(steps),
                   "status": turn.status, "classification_ok": classification_ok,
                   "planning_operations_ok": operations_ok,
                   "resource_ok": resource_ok, "parameter_ok": parameter_ok, "tool_selection_ok": tool_ok,
                   "resource_resolution_ok": resolution_ok,
                   "configuration_ok": configuration_ok, "report_ok": bool(report_ok), "behavior_ok": bool(behavior_ok),
                   "task_ok": bool(behavior_ok) if not kind.startswith("clarify") else None,
                   "json_ok": client.json_results[starts[3]:], "tool_execution_ok": [entry["ok"] for entry in traces],
                   "first_plan_valid": planning_requests[0].get("plan_valid") if planning_requests else None,
                   "model_calls": client.calls - starts[0], "real_model_calls": client.real_calls - starts[1],
                   "duration_seconds": round(duration, 6), "tools": tools, "failure_layers": sorted(set(failure_layers)),
                   "errors": errors, "prior_failed_turns": sum(not row["behavior_ok"] for row in rows),
                   "history_pairs": planning_requests[0]["history_pairs"] if planning_requests else 0,
                   "anchor_in_history": anchor_visible, "anchor_expected": step.anchor_expected,
                   "binding_in_history": binding_visible,
                   "max_request_characters": max((request["characters"] for request in requests), default=0),
                   "max_prompt_tokens": max((request["prompt_tokens"] for request in requests if "prompt_tokens" in request), default=None),
                   "request_statistics": requests, "business_storage": "temporary_sqlite"}
            rows.append(row)
            if on_row:
                on_row(row)
    return rows
