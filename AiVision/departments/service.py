"""departments/service.py
部门管理服务。

函数：
    list_departments()：读取固定部门注册表。
    get_features_by_department()：按 FeatureSpec.departments 筛选功能。
    get_departments_by_feature()：返回功能声明的部门列表。
"""
from __future__ import annotations

from AiVision.features.registry import all_specs, get_spec
from .department_registry import DEPARTMENT_SPECS, DepartmentSpec


class DepartmentService:
    def list_departments(self) -> list[DepartmentSpec]:
        """列出所有固定部门，顺序与注册表一致。"""
        return list(DEPARTMENT_SPECS.values())

    def get_features_by_department(self, department: str) -> list[dict[str, str]]:
        """获取部门下的功能列表。给一个部门，查它有哪些Feature"""
        return [
            {"name": spec.name, "display_name": spec.display_name}
            for spec in all_specs().values()
            if department in spec.departments
        ]

    def get_departments_by_feature(self, feature_name: str) -> list[str]:
        """获取功能归属的部门列表。"""
        spec = get_spec(feature_name)
        return list(spec.departments) if spec is not None else []


# 创建一个全局实例
department_service = DepartmentService()
