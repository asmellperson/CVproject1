"""platform/department/
部门管理模块。

department_registry.py 定义固定部门的 name、display_name；用户和摄像头
只能选择其中的部门。service.py 提供只读查询，功能归属只读取各功能的
FeatureSpec.departments。此模块不注册 ORM，也不初始化或修改数据库表。

增加部门：在注册表添加 DepartmentSpec，再在对应 FeatureSpec.departments
声明归属。移除部门前，应先处理用户、摄像头及历史业务数据中的引用。
"""
from .department_registry import DEPARTMENT_SPECS, DepartmentSpec, require_department

__all__ = [
    "DEPARTMENT_SPECS",
    "DepartmentSpec",
    "require_department",
]
