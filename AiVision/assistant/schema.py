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
    target_name: str | None = Field(default=None, description="实际主体名称，用于目标核验；name 可含功能展示后缀")


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


MutationTool = Literal["update_configurations", "undo_configuration", "add_camera", "bind_camera", "delete_camera"]


class TargetReference(StrictModel):
    """规划器提议的引用，text 必须来自本轮用户原文，不能充当资源身份证明。"""
    kind: Literal["named", "alias", "context", "pending"]
    text: str = Field(min_length=1, max_length=200)


class TargetBindingProposal(StrictModel):
    """用户声明的别名关系，仍须由后台核对原话和真实资源。"""
    alias: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=400)


class TargetContext(StrictModel):
    references: list[TargetReference] = Field(default_factory=list, max_length=10)
    bindings: list[TargetBindingProposal] = Field(default_factory=list, max_length=10)


class RequestPlan(StrictModel):
    """先区分聊天与业务任务，业务任务不能凭模型正文结束为成功。"""
    mode: Literal["chat", "query", "change"]
    operations: list[MutationTool] = Field(default_factory=list, max_length=5)
    query_tool: Literal["capabilities", "list_resources", "read_configurations"] | None = None
    target_context: TargetContext | None = None

    @model_validator(mode="after")
    def check_operations(self):
        if (self.mode == "change") != bool(self.operations):
            raise ValueError("配置任务必须列出操作，聊天和查询不能携带配置操作")
        if len(self.operations) != len(set(self.operations)):
            raise ValueError("操作类别不能重复")
        if (self.mode == "query") != (self.query_tool is not None):
            raise ValueError("查询任务必须指定结果工具，聊天和配置任务不能携带查询目标")
        if self.mode != "chat" and self.target_context is None:
            raise ValueError("业务任务必须声明目标引用与绑定提议，无相关信息时使用空列表")
        if self.mode == "chat" and self.target_context and (self.target_context.references or self.target_context.bindings):
            raise ValueError("聊天任务不能携带资源绑定或执行目标")
        return self


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
