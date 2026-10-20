"""聊天正文直接展示；只有完整、符合合同的工具 JSON 才能进入业务执行。"""
import json
import re

from pydantic import ValidationError

from AiVision.connectors.qwen.client import QwenError
from .schema import AgentDecision


class ToolCallFormatError(QwenError):
    """工具指令格式有误，允许模型纠正一次，未执行任何业务操作。"""


def parse_decision(raw: str) -> AgentDecision:
    try:
        response = json.loads(raw)
        if not isinstance(response, dict) or len(response["choices"]) != 1:
            raise ValueError("响应候选数量无效")
        choice = response["choices"][0]
        message = choice["message"]
        if not isinstance(message, dict):
            raise ValueError("响应消息无效")
        reason = choice["finish_reason"]
        content = message.get("content")
        refusal = message.get("refusal")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise QwenError("福达AI返回的聊天响应格式不正确，请检查模型接口。") from exc
    if refusal or reason == "content_filter":
        raise QwenError("福达AI未能回答这个问题，可以换个说法再试试。")
    if reason == "length":
        raise QwenError("这条回复被输出长度限制截断了，可以增加模型设置中的输出长度，或让我分段回答。")
    if reason != "stop":
        raise QwenError("福达AI没有正常结束回复，请稍后重试并检查模型服务状态。")
    if not isinstance(content, str) or not content.strip():
        raise QwenError("福达AI没有返回回复正文，请检查模型的非思考模式设置。")
    content = content.strip()
    if content.startswith("<think>"):
        _, separator, content = content.partition("</think>")
        if not separator:
            raise QwenError("福达AI的思考输出没有结束，请检查模型的非思考模式设置。")
        content = content.strip()
    if not content:
        raise QwenError("福达AI只返回了思考内容，没有回复正文，请重试。")
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", content, flags=re.DOTALL | re.IGNORECASE)
    candidate = fenced[1].strip() if fenced else content
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
