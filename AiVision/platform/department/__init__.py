# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""platform/department/
部门管理模块。
"""
from AiVision.platform.department.orm import AiDepartment, AiFeatureDepartment
from AiVision.platform.department.service import department_service

__all__ = [
    "AiDepartment",
    "AiFeatureDepartment",
    "department_service",
]
