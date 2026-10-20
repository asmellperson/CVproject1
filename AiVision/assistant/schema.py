"""聊天、资源能力和配置执行结果的稳定数据合同。"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from AiVision.connectors.qwen.schema import QwenConnectionSettings


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AssistantSettings(QwenConnectionSettings):
    """默认共用安检的福达AI连接；独立保存的连接设置对后续对话生效。"""


class SessionCreate(StrictModel):
    department: str | None = None


class MessageCreate(StrictModel):
    request_id: UUID
    text: str = Field(min_length=1, max_length=4000)


class SessionResponse(StrictModel):
    id: str
    title: str
    department: str | None
    created_at: datetime
    updated_at: datetime


class ResourceReference(StrictModel):
    key: str
    kind: str
    name: str
    department: str | None
    feature: str | None = None
    identifier: str | None = None


class ConfigurationResponse(StrictModel):
    resource: ResourceReference
    config: dict
    revision: str
    schema_definition: dict


class ConfigurationChange(StrictModel):
    resource_key: str = Field(min_length=1, max_length=200)
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    patch: dict


class ActionResponse(StrictModel):
    id: str
    resource: ResourceReference
    status: str
    before: dict
    after: dict | None
    changes: dict
    detail: str
    created_at: datetime


class TurnResponse(StrictModel):
    id: int
    request_id: str
    question: str
    answer: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
    progress: str
    actions: list[ActionResponse] = Field(default_factory=list)
    created_at: datetime


class ConversationResponse(StrictModel):
    session: SessionResponse
    turns: list[TurnResponse]
    hidden_turns: int = 0


class AgentDecision(StrictModel):
    """模型只能选择登记工具或回答；参数还须通过工具自己的严格合同。"""
    action: str
    arguments: dict = Field(default_factory=dict)
    answer: str = ""

    @model_validator(mode="after")
    def check_answer(self):
        if self.action == "answer" and (not self.answer.strip() or self.arguments):
            raise ValueError("回答必须包含正文且不携带工具参数")
        if self.action != "answer" and self.answer:
            raise ValueError("工具调用不能同时声明执行结果")
        return self
