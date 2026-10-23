"""有界的专家分工与任务状态；专家只提出工具指令，执行权始终在统一工具层。"""
from copy import deepcopy
from dataclasses import dataclass, field
import json
import re
import time

from .outcomes import ExecutionOutcome, READ_TOOLS
from .responses import PlanFormatError
from .schema import RequestPlan, TargetContext
from .targets import normalized, resource_identity, valid_proposal, verified_bindings


@dataclass(frozen=True)
class QueryAgent:
    name: str = "query"
    instruction: str = ("当前专家：查询专家。只负责本步骤的资源发现和实际数据查询。"
                        "只允许只读工具和 ask_user，不能修改配置，也不能替后续配置步骤执行操作。"
                        "取得本步骤要求的完整结果后结束，由协调器交接。")

    def permits(self, name, plan):
        return name in READ_TOOLS or name == "ask_user"


@dataclass(frozen=True)
class ConfigurationAgent:
    name: str = "configuration"
    instruction: str = ("当前专家：配置专家。只负责本步骤明确授权的配置操作。"
                        "交接的资源身份只用于定位，修改前必须读取当前配置、Schema 和 revision。"
                        "只提交本步骤要求的字段和完整目标集合；不能执行已完成或尚未分派的步骤。"
                        "结果由后台保存记录与回读核验，不能自行声明成功。")

    def permits(self, name, plan):
        return name in READ_TOOLS or name == "ask_user" or name in plan.operations


def validate_task_sources(plan, question):
    """逐段覆盖原话，防止模型在分工时遗漏目标、否定词或批量范围。"""
    if not plan.tasks:
        return
    position = 0
    connector = r"(?:[\s，,。；;：:！!？?、]|然后|接着|再|并且|并|同时|最后|先|请|帮我)*"
    for index, task in enumerate(plan.tasks):
        start = question.find(task.request, position)
        if (not task.request.strip() or start < 0
                or re.fullmatch(connector, question[position:start]) is None):
            raise PlanFormatError("plan_schema", [{"loc": ["tasks", index, "request"], "type": "task_source",
                "message": "子任务必须按顺序逐字引用原文，并完整保留实际要求、否定、条件和范围"}])
        position = start + len(task.request)
    if re.fullmatch(connector, question[position:]) is None:
        raise PlanFormatError("plan_schema", [{"loc": ["tasks"], "type": "task_source",
            "message": "子任务遗漏了用户原文中的实际要求，必须完整覆盖"}])


@dataclass
class AssignedTask:
    request: str
    outcome: ExecutionOutcome
    agent: QueryAgent | ConfigurationAgent | None
    completed: bool = False
    execution_retry: bool = False
    observations: list[dict] = field(default_factory=list)

    def permits(self, name):
        return self.agent is not None and self.agent.permits(name, self.outcome.plan) and self.outcome.permits(name)


class TaskCoordinator:
    """串行调度明确的子任务，共享真实工具状态，不创建递归代理或独立写入通道。"""

    def __init__(self, plan, question, memory=None, *, turn_id=None):
        validate_task_sources(plan, question)
        self.plan, self.question = plan, question
        self.turn_id = turn_id
        self.memory = deepcopy(memory) or {}
        self.index = 0
        self.tasks = []
        self.outcome = ExecutionOutcome(plan)
        if not plan.tasks:
            agent = QueryAgent() if plan.mode == "query" else ConfigurationAgent() if plan.mode == "change" else None
            self.tasks.append(AssignedTask(question, self.outcome, agent))
        else:
            for task in plan.tasks:
                context = plan.target_context or TargetContext()
                step_plan = RequestPlan(
                    mode="query" if task.agent == "query" else "change", operations=task.operations,
                    query_tool=task.query_tool,
                    target_context=TargetContext(
                        references=[item for item in context.references if item.text in task.request],
                        bindings=[item for item in context.bindings if item.alias in task.request or item.target in task.request],
                    ),
                )
                agent = QueryAgent() if task.agent == "query" else ConfigurationAgent()
                self.tasks.append(AssignedTask(task.request, ExecutionOutcome(step_plan), agent))

    @property
    def active(self):
        return self.tasks[self.index]

    @property
    def compound(self):
        return len(self.tasks) > 1

    @property
    def conditional(self):
        # 有序任务表不能表达条件分支，条件未核验前必须询问，不能当作普通顺序执行。
        return self.compound and self.plan.mode == "change" and bool(re.search(
            r"如果|假如|假设|若|除非|否则|仅当|只有.+才", self.question))

    def record(self, tool, result, arguments=None):
        self.active.outcome.record(tool, result, arguments)
        if self.active.outcome is not self.outcome:
            self.outcome.record(tool, result, arguments)

    def complete(self):
        outcome = self.active.outcome
        ready = outcome.query_ready if outcome.plan.mode == "query" else not (outcome.pending or outcome.errors)
        if not ready:
            raise ValueError("当前步骤尚未核验完成，不能交接给下一专家")
        self.active.completed = True
        # 交接只保存已读取的资源身份和经过原话、资源共同核验的别名，不转交配置版本。
        resources = [item["resource"] for item in outcome.query_configurations.values()]
        if not resources and outcome.plan.query_tool == "list_resources":
            resources = list(outcome.query_resources.values())
        deleted = ({resource_identity(item) for item in resources}
                   if "delete_camera" in outcome.plan.operations else set())
        structural = bool(set(outcome.plan.operations) & {"add_camera", "delete_camera", "bind_camera"})
        if deleted:
            self.outcome.query_configurations = {key: item for key, item in self.outcome.query_configurations.items()
                                                if resource_identity(item["resource"]) not in deleted}
        if structural:
            # 结构操作的审计标识不是可读取的业务资源，必须重新搜索核验，不能沿用旧目标。
            resources = []
        if resources or outcome.plan.query_tool == "list_resources" or outcome.plan.mode == "change":
            self.memory["last_read_resources"] = deepcopy(resources)
        proposals = self.plan.target_context.bindings if self.plan.target_context else []
        bindings = {normalized(item["alias"]): deepcopy(item) for item in self.memory.get("target_bindings", [])}
        for proposal in proposals:
            if valid_proposal(proposal, self.question):
                bindings.pop(normalized(proposal.alias), None)
        for item in verified_bindings(proposals, self.question,
                                      [item["resource"] for item in self.outcome.query_configurations.values()]):
            bindings[normalized(item["alias"])] = {**item, "turn_id": self.turn_id, "confirmed_at": time.monotonic()}
        self.memory["target_bindings"] = [item for item in bindings.values()
                                          if resource_identity(item["resource"]) not in deleted]
        self.memory.pop("pending_task", None)
        if self.index + 1 >= len(self.tasks):
            return False
        self.index += 1
        return True

    def shared_context(self, *, max_chars=None):
        """只输出后台确认的进度与资源身份，专家的自然语言答复不作为交接依据。"""
        data = {"current_step": self.index + 1, "total_steps": len(self.tasks),
                "completed_steps": [{"step": index + 1, "agent": task.agent.name,
                                     "operations": sorted(task.outcome.completed_operations)}
                                    for index, task in enumerate(self.tasks) if task.completed],
                "last_read_resources": self.memory.get("last_read_resources", []),
                "target_bindings": [{"alias": item["alias"], "resource": item["resource"]}
                                    for item in self.memory.get("target_bindings", [])
                                    if normalized(item["alias"]) in normalized(self.active.request)],
                "history_truncated": False}
        if max_chars is not None and len(json.dumps(data, ensure_ascii=False)) > max_chars:
            # 不把大目标集合的一部分传给下一专家，避免把残余目标误当成全部。
            data.update(last_read_resources=[], target_bindings=[], history_truncated=True)
        return data

    def remaining_tasks(self):
        return [{"request": task.request, "plan": task.outcome.plan.model_dump()}
                for task in self.tasks if not task.completed]

    def answer(self, actions, *, question=None):
        if not self.compound:
            outcome = self.active.outcome
            return outcome.query_answer() if outcome.plan.mode == "query" and question is None else outcome.answer(actions, question=question)
        lines = []
        for index, task in enumerate(self.tasks):
            if task.completed and task.outcome.plan.mode == "query":
                lines.append(f"任务 {index + 1} 查询结果（该步骤执行时）：\n" + task.outcome.query_answer()[1])
        status = "completed" if all(task.completed for task in self.tasks) else "failed"
        if self.plan.mode == "change":
            verified_status, verified_answer = self.outcome.answer(actions, question=question)
            lines.append(verified_answer)
            if verified_status == "failed":
                status = "failed"
        elif question:
            lines.extend(["需要你补充信息：", question])
        elif self.active.outcome.errors:
            lines.append(self.active.outcome.query_answer()[1])
        remaining = [str(index + 1) for index, task in enumerate(self.tasks) if not task.completed]
        if remaining:
            lines.append("尚未完成的任务：" + "、".join(remaining) + "；后续步骤尚未执行。")
        # 澄清是等待用户补充，答复中必须明确复合任务尚未整体完成。
        return ("completed" if question else status), "\n".join(lines)
