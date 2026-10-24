"""聊天正文直接展示；只有完整、符合合同的工具 JSON 才能进入业务执行。"""
import json
import re
from typing import Literal

from pydantic import ValidationError

from AiVision.connectors.qwen.client import QwenError, QwenResponseError, QwenServiceError, QwenTruncatedError
from .intent import deletion_target
from .schema import AgentDecision, RequestPlan


class ToolCallFormatError(QwenError):
    """工具指令格式有误，允许模型纠正一次，未执行任何业务操作。"""


class PlanFormatError(QwenError):
    """可纠正的分类格式错误；仅保留白名单字段和错误类别，不携带模型原文。"""

    def __init__(self, category: Literal["plan_json", "plan_schema"], issues: list[dict]):
        self.category = category
        self.issues = issues
        reason = "JSON 格式不正确" if category == "plan_json" else "字段不符合 Schema"
        detail = "；".join(f"{'.'.join(map(str, issue['loc'])) or '根对象'}：{issue['message']}" for issue in issues)
        super().__init__(f"福达AI任务分类{reason}（{detail}），尚未执行配置操作。")

    def correction_message(self) -> str:
        return ("上次任务分类未通过校验，尚未执行任何操作。校验错误："
                + json.dumps(self.issues, ensure_ascii=False)
                + "。请重新判断原始用户请求，只输出符合系统 Schema 的一个完整 JSON 对象。"
                "必须包含合法 mode；chat/query 的 operations 为空，change 的 operations 必须非空且不重复。"
                "query 必须指定 query_tool，其他 mode 的 query_tool 为 null。"
                "业务任务必须提供 target_context（references 和 bindings）；引用和绑定只能来自用户原文。"
                "单一任务的 tasks 留空；复合任务的每个 request 按顺序逐字引用原文并覆盖全部实际要求，不得丢失否定、条件或范围。"
                "不要输出解释、思考过程、工具指令或额外字段。")


def _plan_issues(exc: ValidationError) -> list[dict]:
    """校验器的 input、ctx、未知字段名和动态错误正文可能含用户数据，不能用于日志或纠正提示。"""
    messages = {
        "missing": "缺少必需字段", "literal_error": "取值不在 Schema 允许范围内",
        "extra_forbidden": "包含 Schema 未允许的字段", "list_type": "字段必须为列表",
        "too_long": "列表超过 Schema 数量上限", "model_type": "分类必须为 JSON 对象",
        "json_invalid": "必须输出语法完整的 JSON", "value_error": "任务类型、目标引用或绑定不符合任务约束",
    }
    issues = []
    for error in exc.errors(include_input=False, include_context=False, include_url=False)[:8]:
        known_fields = set(RequestPlan.model_fields) | {"references", "bindings", "kind", "text", "alias", "target", "evidence", "agent", "request"}
        location = [part if isinstance(part, int) or part in known_fields else "<额外字段>"
                    for part in error["loc"]]
        issues.append({"loc": location, "type": error["type"],
                       "message": messages.get(error["type"], "字段类型或取值不符合 Schema")})
    return issues


def is_simple_greeting(question: str) -> bool:
    """只识别整条独立问候，包含配置请求、引用或其他正文时交给规划器。"""
    return re.fullmatch(
        r"(?:你好|您好|嗨|哈喽|hello|hi)[呀哇啊吖哟哦噢喔哈\s！!。.?？～~，,、；;]*",
        question.strip(), re.IGNORECASE,
    ) is not None


def simple_delete_plan(question: str) -> RequestPlan | None:
    """只识别独立、明确的单目标删除命令，名称位置不影响分类，执行仍由原工具核验。"""
    text = question.strip().rstrip("。！!").strip()
    target = deletion_target(text)
    if target is None:
        return None
    # 讨论、否定、示例、条件和多目标不能通过轻量规则变成删除授权。
    if re.search(r"[？?，,；;、\n]|不要|别删|不删|不能|无需|不需要|怎么|如何|是否|能否|可否|可以|能不能|比如|例如|示例|假设|如果|然后|之后|再|顺便|所有|全部|两台|多台|功能|配置|移除|解除|或者|还是|保留|会怎样|有什么|条件|后果|意味着|(?:吗|么|呢)$", text):
        return None
    # 类别词之后出现说明正文时不能走快捷路径；名称在类别词之后的完整性仍由实际资源核对。
    if not re.match(r"(?:摄像头|摄像机|相机)", target) and not re.search(r"(?:摄像头|摄像机|相机)$", target):
        return None
    if (not 1 <= len(target) <= 200 or re.search(r"和|及|与|这台|那台|它|这些|刚才", target)
            or not re.search(r"摄像头|摄像机|相机", target)
            or len(re.findall(r"摄像头|摄像机|相机", target)) != 1
            or re.fullmatch(r"(?:一台|这个|一个)?(?:摄像头|摄像机|相机)", target)):
        return None
    return RequestPlan(mode="change", operations=["delete_camera"],
                       target_context={"references": [{"kind": "named", "text": target}], "bindings": []})


def completion_metadata(raw: str) -> dict:
    """只记录有界类别、计数和标记；异常输出和思考正文均不能进入日志。"""
    try:
        response = json.loads(raw)
        choice = response["choices"][0]
        message = choice["message"]
        content = message.get("content")
        reason = choice.get("finish_reason")
        usage = response.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        result = {"finish_reason": reason if reason in {"stop", "length", "content_filter", "error", "tool_calls"} else "other",
                  "content_characters": len(content) if isinstance(content, str) else 0,
                  "has_thinking": bool(message.get("reasoning") or message.get("reasoning_content")
                                       or isinstance(content, str) and "<think>" in content)}
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if type(usage.get(name)) is int and usage[name] >= 0:
                result[name] = usage[name]
        if type(details.get("reasoning_tokens")) is int and details["reasoning_tokens"] >= 0:
            result["reasoning_tokens"] = details["reasoning_tokens"]
        return result
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return {"envelope_valid": False}


def completion_content(raw: str) -> str:
    try:
        response = json.loads(raw)
        if isinstance(response, dict) and "error" in response:
            raise QwenServiceError("福达AI服务返回错误，请检查模型服务状态。")
        if not isinstance(response, dict) or not isinstance(response["choices"], list) or len(response["choices"]) != 1:
            raise ValueError("响应候选数量无效")
        choice = response["choices"][0]
        message = choice["message"]
        if not isinstance(message, dict):
            raise ValueError("响应消息无效")
        reason = choice["finish_reason"]
        content = message.get("content")
        refusal = message.get("refusal")
    except (KeyError, IndexError, TypeError, ValueError):
        raise QwenResponseError("福达AI返回的聊天响应格式不正确，请检查模型接口。") from None
    if refusal or reason == "content_filter":
        raise QwenServiceError("福达AI未能回答这个问题，可以换个说法再试试。")
    if reason == "length":
        raise QwenTruncatedError("这条回复被输出长度限制截断了，可以增加模型设置中的输出长度，或让我分段回答。")
    if reason != "stop":
        raise QwenServiceError("福达AI没有正常结束回复，请稍后重试并检查模型服务状态。")
    if not isinstance(content, str) or not content.strip():
        raise QwenResponseError("福达AI没有返回回复正文，请检查模型的非思考模式设置。")
    content = content.strip()
    if content.startswith("<think>"):
        _, separator, content = content.partition("</think>")
        if not separator:
            raise QwenResponseError("福达AI的思考输出没有结束，请检查模型的非思考模式设置。")
        content = content.strip()
    if not content:
        raise QwenResponseError("福达AI只返回了思考内容，没有回复正文，请重试。")
    return content


def json_content(content: str) -> str:
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", content, flags=re.DOTALL | re.IGNORECASE)
    return fenced[1].strip() if fenced else content


def parse_plan(raw: str) -> RequestPlan:
    try:
        return RequestPlan.model_validate_json(json_content(completion_content(raw)))
    except ValidationError as exc:
        issues = _plan_issues(exc)
        category = "plan_json" if any(issue["type"] == "json_invalid" for issue in issues) else "plan_schema"
        raise PlanFormatError(category, issues) from None


def parse_decision(raw: str) -> AgentDecision:
    content = completion_content(raw)
    candidate = json_content(content)
    try:
        decision = json.loads(candidate)
    except ValueError as exc:
        if candidate.startswith("{") and re.search(r'"(?:action|arguments)"\s*:', candidate):
            raise ToolCallFormatError("工具指令 JSON 不完整，本次未执行操作。") from exc
        return AgentDecision(action="answer", answer=content)
    if not isinstance(decision, dict) or "action" not in decision:
        return AgentDecision(action="answer", answer=content)
    try:
        return AgentDecision.model_validate(decision)
    except ValidationError as exc:
        raise ToolCallFormatError("工具指令字段不符合合同，本次未执行操作。") from exc
