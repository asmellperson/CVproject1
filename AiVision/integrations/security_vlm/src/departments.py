# 文件说明：实现`departments` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""安检事业部白名单及统一校验。"""

from __future__ import annotations


SECURITY_DEPARTMENTS = (
    "general_electric",
    "electronics_electrician",
    "electrical_components",
    "precious_metal_recycling",
)


# 功能：返回合法事业部标识；空值或未知标识会被拒绝；输入与输出详见下方说明
# 参数：
#   - `value`（str）：待转换、校验或写入的值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::__init__`
#         调用本符号；`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `DepartmentWorkspaceManager::get`
#         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTask::__post_init__`
#         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentFairTaskQueue::has_queued` 调用本符号；另有 24 处静态调用
#   - 内部调用：`str(value or '').strip`、`str`、`ValueError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def require_department(value: str) -> str:
    """返回合法事业部标识；空值或未知标识会被拒绝。"""
    department = str(value or "").strip()
    if department not in SECURITY_DEPARTMENTS:
        raise ValueError(f"未知安检事业部: {department or '<empty>'}")
    return department
