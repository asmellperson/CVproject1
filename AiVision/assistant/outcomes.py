"""配置完成提示只由业务工具结果及数据库审计生成，不采用模型自述。"""
from dataclasses import dataclass, field
import json

from .schema import ActionResponse, MutationTool, RequestPlan


OPERATION_LABELS: dict[MutationTool, str] = {
    "update_configurations": "修改配置", "undo_configuration": "撤销参数修改",
    "add_camera": "添加摄像头", "bind_camera": "绑定摄像头", "delete_camera": "删除摄像头",
}
READ_TOOLS = frozenset({"capabilities", "list_resources", "read_configurations"})


@dataclass
class ExecutionOutcome:
    plan: RequestPlan
    completed_operations: set[str] = field(default_factory=set)
    unchanged: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    query_tool: str | None = None
    query_result: dict | None = None
    query_resources: dict[str, dict] = field(default_factory=dict)
    query_configurations: dict[str, dict] = field(default_factory=dict)
    query_next_offset: int | None = None

    def permits(self, tool: str) -> bool:
        return tool == "ask_user" or (self.plan.mode != "chat" and tool in READ_TOOLS) or tool in self.plan.operations

    def record(self, tool: str, result: dict) -> None:
        if "error" in result:
            self.errors.append(str(result["error"]))
            return
        if tool in READ_TOOLS:
            self.query_tool, self.query_result = tool, result
            if tool == "list_resources":
                self.query_resources.update((item["key"], item) for item in result["items"])
                self.query_next_offset = result.get("next_offset")
            elif tool == "read_configurations":
                self.query_configurations.update((item["resource"]["key"], item) for item in result["items"])
        if tool not in self.plan.operations:
            return
        for item in result.get("results", [result]):
            if item.get("status") == "saved" and item.get("after") is not None:
                self.completed_operations.add(tool)
            elif item.get("status") == "unchanged":
                self.completed_operations.add(tool)
                self.unchanged[item["resource_key"]] = item["resource_name"]
            elif "error" in item:
                self.errors.append(str(item["error"]))
            elif item.get("status") in {"failed", "unknown", "changed", "executing"}:
                self.errors.append(item.get("detail") or "操作结果未核实，请查看操作记录")

    @property
    def pending(self) -> set[str]:
        return set(self.plan.operations) - self.completed_operations

    @property
    def query_ready(self) -> bool:
        if self.plan.mode != "query" or self.query_result is None or self.errors:
            return False
        if self.plan.query_tool == "capabilities":
            return self.query_tool == "capabilities"
        if self.query_next_offset is not None:
            return False
        if self.plan.query_tool == "list_resources":
            return self.query_tool in {"list_resources", "read_configurations"}
        return bool(self.query_configurations) and self.query_resources.keys() <= self.query_configurations.keys()

    def query_requirement(self) -> str:
        if self.query_next_offset is not None:
            return "资源列表还有下一页，请按 next_offset 继续查询，不能把当前页当成全部目标。"
        if self.plan.query_tool == "read_configurations":
            missing = sorted(self.query_resources.keys() - self.query_configurations.keys())
            return ("本轮要求实际配置，资源名称或搜索 Schema 不能替代读取结果。请调用 read_configurations"
                    "；目标有歧义时调用 ask_user。尚未读取的候选：" + json.dumps(missing, ensure_ascii=False))
        return "本轮尚未取得要求的查询结果，请调用 " + str(self.plan.query_tool) + "；缺少信息时使用 ask_user。"

    def query_answer(self) -> tuple[str, str]:
        if self.errors:
            return "failed", "查询尚未完成：" + self.errors[-1]
        if not self.query_ready:
            detail = "尚未读取全部目标的实际配置。" if self.plan.query_tool == "read_configurations" else "尚未取得完整查询结果。"
            return "failed", "本轮查询尚未完成，不能确认实际状态。" + detail
        if self.query_tool == "capabilities" and not (self.query_configurations or self.query_resources):
            departments = "、".join(item["name"] for item in self.query_result["departments"])
            features = "、".join(item["label"] for item in self.query_result["features"])
            return "completed", f"当前可访问部门：{departments}。\n可访问检测功能：{features}。"
        items = list(self.query_configurations.values()) or list(self.query_resources.values())
        if not items:
            return "completed", "当前部门和查询条件下没有找到匹配资源。本轮没有修改配置。"
        lines = []
        for item in items:
            reference = item["resource"] if self.query_configurations else item
            label = reference["name"]
            if reference.get("identifier"):
                label += "（" + reference["identifier"] + "）"
            if self.query_configurations:
                label += "当前配置：\n" + json.dumps(item["config"], ensure_ascii=False, indent=2)
            lines.append(label)
        if not self.query_configurations:
            lines.insert(0, f"本轮查询实际取得 {len(items)} 个资源：")
        return "completed", "\n".join(lines)

    def answer(self, actions: list[ActionResponse], *, question: str | None = None) -> tuple[str, str]:
        lines = []
        failed = bool(self.pending or self.errors)
        for action in actions:
            target = f"“{action.resource.name}”"
            if action.resource.identifier:
                target += f"（{action.resource.identifier}）"
            if action.status == "saved" and action.after is not None:
                verb = {"camera_deletion": "已删除摄像头", "camera_creation": "已添加摄像头",
                        "camera_binding": "已完成摄像头绑定："}.get(action.resource.kind, "已保存配置：")
                lines.append(verb + target + "。" + action.detail)
            else:
                failed = True
                label = "执行失败" if action.status == "failed" else "结果待核对"
                lines.append(f"{target}{label}：{action.detail}")
        lines.extend(f"“{name}”已是目标值，无需修改。" for name in self.unchanged.values())
        if question is not None:
            prefix = "还需要你补充信息，尚未执行配置操作。" if not lines and self.plan.mode == "change" else "需要你补充信息："
            lines.extend([prefix, question])
            return "completed", "\n".join(lines)
        if not lines:
            lines.append("本轮没有执行配置变更，不能确认操作完成。")
            failed = True
        if self.pending:
            labels = [OPERATION_LABELS[name] for name in self.plan.operations if name in self.pending]
            lines.append("尚未完成：" + "、".join(labels) + "。")
        if self.errors:
            lines.append("未完成原因：" + self.errors[-1])
        return ("failed" if failed else "completed"), "\n".join(lines)
