"""使用现有本地千问服务，严格判定监控指令与当前事件是否匹配。"""

import json

from pydantic import ValidationError

from AiVision.connectors.qwen.client import ChatCompletion, QwenClient, QwenError
from AiVision.features.security_inspection.service import InspectionService
from .prompts import JUDGMENT_SYSTEM_PROMPT
from .schema import MonitoringVerdict


class EventJudgmentError(RuntimeError):
    """判定不可用时只记录错误，不产生报警候选。"""


def _unique_fields(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise EventJudgmentError("千问事件判定 JSON 含重复字段")
        result[key] = value
    return result


def parse_verdict(body: str) -> MonitoringVerdict:
    """完整结束的响应与严格 JSON 均通过校验后才接受命中值。"""
    try:
        choice = ChatCompletion.model_validate_json(body, strict=True).choices[0]
        if choice.finish_reason != "stop" or choice.message.refusal or choice.message.content is None:
            raise EventJudgmentError("千问事件判定未正常完成或被拒绝")
        # 拒绝重复 hit 字段，不能让后出现的值覆盖前面的否定结论。
        payload = json.loads(choice.message.content, object_pairs_hook=_unique_fields)
        return MonitoringVerdict.model_validate(payload)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise EventJudgmentError("千问事件判定返回非法 JSON 或不符合 hit/reason 契约") from exc


class EventJudge:
    def __init__(self):
        self.client = QwenClient()
        self.settings_service = InspectionService()

    def judge(self, instruction: str, event_description: str) -> MonitoringVerdict:
        # 使用项目现有千问配置；不另建模型地址、认证或模型管理入口。
        config = self.settings_service.get_settings()
        try:
            body = self.client.complete(
                base_url=config.base_url, model=config.model,
                messages=[
                    {"role": "system", "content": JUDGMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps({
                        "monitoring_instruction": instruction,
                        "event_description": event_description,
                    }, ensure_ascii=False)},
                ],
                max_tokens=config.max_tokens, temperature=config.temperature,
                timeout_seconds=config.api_timeout_sec,
            )
        except QwenError as exc:
            raise EventJudgmentError(f"千问事件判定失败：{exc}") from exc
        return parse_verdict(body)
