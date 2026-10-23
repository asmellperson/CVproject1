"""配置完成提示只由业务工具结果及数据库审计生成，不采用模型自述。"""
from dataclasses import dataclass, field
import json

from .schema import ActionResponse, MutationTool, RequestPlan
from .targets import normalized
from AiVision.departments.department_registry import DEPARTMENT_SPECS


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
    unresolved_errors: list[str] = field(default_factory=list)
    recoverable_errors: dict[tuple, str] = field(default_factory=dict)
    required_targets: dict[str, set[str]] = field(default_factory=dict)
    completed_targets: dict[str, set[str]] = field(default_factory=dict)
    query_tool: str | None = None
    query_result: dict | None = None
    query_resources: dict[str, dict] = field(default_factory=dict)
    query_configurations: dict[str, dict] = field(default_factory=dict)
    query_next_offset: int | None = None
    query_total: int | None = None
    query_pages: dict[int, int] = field(default_factory=dict)
    query_scope: str | None = None
    query_pages_invalid: bool = False

    def permits(self, tool: str) -> bool:
        return tool == "ask_user" or (self.plan.mode != "chat" and tool in READ_TOOLS) or tool in self.plan.operations

    @property
    def errors(self) -> list[str]:
        return [*self.unresolved_errors, *self.recoverable_errors.values()]

    @staticmethod
    def error_scope(tool, arguments):
        def identifiers(value):
            return tuple(sorted({item for item in value if isinstance(item, str)})) if isinstance(value, list) else ()

        if tool == "list_resources":
            department = arguments.get("department")
            if isinstance(department, str):
                department = next((spec.name for spec in DEPARTMENT_SPECS.values()
                                   if normalized(department) in {normalized(spec.name), normalized(spec.display_name)}), department)
            return tool, tuple(value if isinstance(value, str) else None
                               for value in (arguments.get("kind"), department, arguments.get("parent_key")))
        if tool == "read_configurations":
            return tool, identifiers(arguments.get("resource_keys"))
        if tool == "update_configurations":
            changes = arguments.get("changes")
            return tool, identifiers([change.get("resource_key") for change in changes if isinstance(change, dict)]
                                      if isinstance(changes, list) else [])
        return tool, ()

    def record(self, tool: str, result: dict, arguments: dict | None = None) -> None:
        arguments = arguments or {}
        scope = self.error_scope(tool, arguments)
        if "error" in result:
            if result.get("recoverable") is True:
                self.recoverable_errors[scope] = str(result["error"])
            else:
                self.unresolved_errors.append(str(result["error"]))
            return
        if tool in READ_TOOLS:
            self.recoverable_errors.pop(scope, None)
            self.query_tool, self.query_result = tool, result
            if tool == "list_resources":
                if self.plan.mode == "query" and self.plan.query_tool == "list_resources":
                    filters = result.get("applied_filters") or {key: arguments.get(key) for key in
                        ("kind", "department", "feature", "query", "parent_key", "feature_enabled")}
                    query_scope = json.dumps(filters, sort_keys=True, ensure_ascii=False)
                    offset = arguments.get("offset", 0)
                    if query_scope != self.query_scope or offset == 0:
                        self.query_resources.clear()
                        self.query_pages.clear()
                        self.query_total = None
                        self.query_pages_invalid = False
                    self.query_scope = query_scope
                    total = result.get("total")
                    if type(total) is int and total >= 0:
                        if self.query_total is not None and total != self.query_total:
                            self.query_pages_invalid = True
                        self.query_total = total
                        self.query_pages[offset] = len(result["items"])
                self.query_resources.update((item["key"], item) for item in result["items"])
                self.query_next_offset = result.get("next_offset")
            elif tool == "read_configurations":
                self.query_configurations.update((item["resource"]["key"], item) for item in result["items"])
        if tool not in self.plan.operations:
            return
        expected = {change["resource_key"] for change in arguments.get("changes", [])}
        self.required_targets.setdefault(tool, set()).update(expected)
        verified = self.completed_targets.setdefault(tool, set())
        current_verified = set()
        items = result.get("results", [result])
        complete = bool(items)
        for item in items:
            key = item.get("resource_key") or item.get("resource", {}).get("key")
            succeeded = ((item.get("status") == "saved" and item.get("after") is not None)
                         or item.get("status") == "unchanged")
            if succeeded and key:
                verified.add(key)
                current_verified.add(key)
            if item.get("status") == "unchanged":
                self.unchanged[item["resource_key"]] = item["resource_name"]
            if "error" in item:
                self.unresolved_errors.append(str(item["error"]))
            elif not succeeded:
                self.unresolved_errors.append(item.get("detail") or "操作结果未核实，请查看操作记录")
            complete &= succeeded
        if complete and self.required_targets[tool] <= verified:
            self.completed_operations.add(tool)
            # 批量纠正可以覆盖原失败子集；另一资源的成功不能解除本目标的错误。
            for previous in list(self.recoverable_errors):
                if previous == scope or (previous[0] == tool and set(previous[1]) <= current_verified):
                    del self.recoverable_errors[previous]
        else:
            self.completed_operations.discard(tool)

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
            if self.query_total is not None and (self.query_pages_invalid or self.missing_query_offset is not None
                                                  or len(self.query_resources) != self.query_total):
                return False
            return self.query_tool == "list_resources" or self.query_tool == "read_configurations" and bool(self.query_resources)
        return bool(self.query_configurations) and self.query_resources.keys() <= self.query_configurations.keys()

    def query_requirement(self) -> str:
        if self.plan.query_tool == "list_resources" and self.query_total is not None:
            offset = self.missing_query_offset
            if self.query_pages_invalid or offset is None and len(self.query_resources) != self.query_total:
                return "分页总数或去重目标不一致，请保留原筛选条件从 offset=0 重新查询，不能报告完整数量。"
            if offset is not None:
                return f"分页尚未完整，请保留原筛选条件从 offset={offset} 继续查询，不能跳页或只列出当前页。"
        if self.query_next_offset is not None:
            return "资源列表还有下一页，请按 next_offset 继续查询，不能把当前页当成全部目标。"
        if self.plan.query_tool == "read_configurations":
            missing = sorted(self.query_resources.keys() - self.query_configurations.keys())
            return ("本轮要求实际配置，资源名称或搜索 Schema 不能替代读取结果。请调用 read_configurations"
                    "；目标有歧义时调用 ask_user。尚未读取的候选：" + json.dumps(missing, ensure_ascii=False))
        return "本轮尚未取得要求的查询结果，请调用 " + str(self.plan.query_tool) + "；缺少信息时使用 ask_user。"

    @property
    def missing_query_offset(self):
        offset = 0
        while self.query_total is not None and offset < self.query_total:
            count = self.query_pages.get(offset, 0)
            if count <= 0:
                return offset
            offset += count
        return None

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
        show_configurations = self.plan.query_tool == "read_configurations"
        items = list(self.query_configurations.values()) if show_configurations else list(self.query_resources.values())
        if not items:
            return "completed", "当前部门和查询条件下匹配的摄像头为 0 台。本轮没有修改配置。" if (
                self.query_result.get("applied_filters", {}).get("kind") in {"camera", "feature"}) else (
                "当前部门和查询条件下没有找到匹配资源。本轮没有修改配置。")
        lines = []
        for item in items:
            reference = item["resource"] if show_configurations else item
            label = reference["name"]
            if reference.get("identifier"):
                label += "（" + reference["identifier"] + "）"
            if show_configurations:
                label += "当前配置：\n" + json.dumps(item["config"], ensure_ascii=False, indent=2)
            lines.append(label)
        if not show_configurations:
            filters = self.query_result.get("applied_filters", {})
            if filters.get("kind") in {"camera", "feature"}:
                departments = "、".join(DEPARTMENT_SPECS[key].display_name for key in filters.get("departments", []) if key in DEPARTMENT_SPECS)
                scope = " / ".join(value for value in (departments, filters.get("feature_label")) if value)
                state = {True: "（该功能已启用）", False: "（该功能未启用）"}.get(filters.get("feature_enabled"), "") if filters.get("feature") else ""
                lines.insert(0, f"{scope or '当前查询范围'}：共 {len(items)} 台摄像头{state}：")
            else:
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
            missing = set().union(*(self.required_targets.get(tool, set()) - self.completed_targets.get(tool, set())
                                    for tool in self.pending))
            if missing:
                names = [self.query_resources.get(key, self.query_configurations.get(key, {}).get("resource", {})).get("name", key)
                         for key in sorted(missing)]
                lines.append("尚未完成的目标：" + "、".join(names) + "。")
        if self.errors:
            lines.append("未完成原因：" + self.errors[-1])
        return ("failed" if failed else "completed"), "\n".join(lines)
