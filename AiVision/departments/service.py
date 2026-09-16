"""departments/service.py
部门管理服务。

函数：
    list_departments()：读取固定部门注册表。
    get_features_by_department()：为任意正式部门返回平台全部功能。
"""
from __future__ import annotations

from AiVision.features.registry import all_specs
from .department_registry import DEPARTMENT_SPECS, DepartmentSpec, require_department


class DepartmentService:
    def list_departments(self) -> list[DepartmentSpec]:
        """列出所有固定部门，顺序与注册表一致。"""
        return list(DEPARTMENT_SPECS.values())

    def get_features_by_department(self, department: str) -> list[dict[str, str]]:
        """合法事业部统一拥有平台全部功能。"""
        require_department(department)
        return [
            {"name": spec.name, "display_name": spec.display_name}
            for spec in all_specs().values()
        ]



# 创建一个全局实例
department_service = DepartmentService()
