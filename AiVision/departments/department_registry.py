"""固定事业部目录；增删或改名只在开发阶段修改此注册表。

功能属于平台；此目录只定义数据归属和访问范围。
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class DepartmentSpec:
    """不可变事业部定义；name 用于持久化与权限，display_name 用于展示。"""
    name: str
    display_name: str


DEPARTMENT_SPECS = MappingProxyType({
    spec.name: spec
    for spec in (
        DepartmentSpec("general_electric", "通用电气事业部"),
        DepartmentSpec("electronics_electrician", "电子电工事业部"),
        DepartmentSpec("electrical_components", "电气部件事业部"),
        DepartmentSpec("research_institute", "福达新材院"),
        DepartmentSpec("precious_metal_recycling", "伟达子公司"),
        DepartmentSpec("haoda_company", "皓达子公司"),
        DepartmentSpec("fulida_company", "福力达子公司"),
    )
})


def require_department(name: str) -> str:
    """只接受注册表中的部门编码，不创建部门或转换历史别名。"""
    if not isinstance(name, str) or name not in DEPARTMENT_SPECS:
        raise ValueError(f"unknown department: {name!r}")
    return name
