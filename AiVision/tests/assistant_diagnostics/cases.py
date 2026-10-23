"""固定的虚构业务样例；期望值独立于模型输出及 Agent 自报状态。"""
from dataclasses import dataclass, field


DEPARTMENT = "general_electric"
FEATURE = "tailgating"
CAMERA_NAME = "诊断闸机一号"
SECOND_CAMERA_NAME = "诊断闸机二号"
RESOURCE = "feature:tailgating:101"
SECOND_RESOURCE = "feature:tailgating:102"


@dataclass(frozen=True)
class Scenario:
    name: str
    label: str
    question: str
    mode: str = "change"
    patch: dict = field(default_factory=lambda: {"value": {"threshold": 0.8}})
    expected: str = "saved"
    prelude: str | None = None
    continuation: str | None = None
    fault: str | None = None
    eligible: bool = True


SCENARIOS = (
    Scenario("greeting", "简单问候", "你好哇", mode="chat", expected="chat"),
    Scenario("capabilities", "查询可用检测功能", "查询当前可用检测功能", mode="query", expected="capabilities"),
    Scenario("camera", "查询指定摄像头", f"查询通用电气事业部的{CAMERA_NAME}摄像头", mode="query", expected="camera"),
    Scenario("single", "修改单个合法参数", f"通用电气事业部，非法闯闸功能，{CAMERA_NAME}的人体置信度改为0.8"),
    Scenario("double", "同时修改两个参数", f"将通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为0.8，检测间隔改为0.2秒",
             patch={"value": {"threshold": 0.8, "cap_interval": 0.2}}),
    Scenario("reference", "依赖上下文的指代", "把这个阈值调低一点", expected="clarify_value", eligible=False,
             prelude=f"查询通用电气事业部{CAMERA_NAME}非法闯闸的人体置信度"),
    Scenario("ambiguous", "目标名称存在歧义", "通用电气事业部诊断闸机的非法闯闸人体置信度改为0.8",
             expected="clarify_target", eligible=False),
    Scenario("bounds", "参数超出合法范围", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为1.5",
             patch={"value": {"threshold": 1.5}}, expected="rejected", eligible=False),
    Scenario("permission", "用户没有修改权限", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为0.8",
             expected="rejected", eligible=False),
    Scenario("tool_error", "工具返回错误", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为0.8",
             fault="tool_error", expected="rejected", eligible=False),
    Scenario("conflict", "配置版本发生冲突", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为0.8",
             fault="conflict", expected="rejected", eligible=False),
    Scenario("unchanged", "配置已是目标值", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度保持0.5",
             patch={"value": {"threshold": 0.5}}, expected="unchanged"),
    Scenario("invalid_json", "非法 JSON 后纠正", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为0.8", fault="invalid_json"),
    Scenario("truncated", "模型输出截断", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为0.8",
             fault="truncated", expected="rejected", eligible=False),
    Scenario("wrong_answer", "保存成功但模型最终答复错误", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为0.8", fault="wrong_answer"),
    Scenario("continuation", "多轮任务延续", "通用电气事业部、非法闯闸功能，人体置信度配置值，改为0.8",
             continuation=CAMERA_NAME),
    Scenario("duplicate", "同一请求重复提交", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为0.8"),
    Scenario("cancel", "执行过程中取消任务", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为0.8",
             fault="cancel", expected="cancelled", eligible=False),
)

PROBES = (
    Scenario("extra_field", "拦截模型额外修改未请求字段", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为0.8",
             expected="scope_rejected", eligible=False),
    Scenario("partial_batch", "拦截批量任务漏目标", "把通用电气事业部两台诊断闸机的非法闯闸人体置信度都改为0.8",
             expected="scope_rejected", eligible=False),
    Scenario("recovered_tool_error", "工具纠正成功后的最终状态", f"通用电气事业部{CAMERA_NAME}非法闯闸人体置信度改为0.8"),
)

METRICS = {
    "first_plan_valid": "首次规划 Schema 通过率", "query_goal_ok": "查询目标规划准确率",
    "classification_ok": "任务分类准确率", "resource_ok": "资源识别准确率",
    "planning_operations_ok": "操作类别规划准确率",
    "orchestration_ok": "专家任务编排通过率",
    "tool_selection_ok": "工具选择准确率", "parameter_ok": "参数提取准确率",
    "json_ok": "JSON 格式有效率", "schema_output_ok": "输出合同通过率", "tool_execution_ok": "工具执行成功率",
    "configuration_ok": "最终配置核验通过率", "task_ok": "端到端任务成功率",
    "behavior_ok": "预期处理行为通过率", "report_ok": "结果报告正确率",
}
