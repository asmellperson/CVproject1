"""departments/
事业部定义、只读查询及相关业务约束。

department_registry.py 定义固定部门的 name、display_name；用户和摄像头
只能选择其中的部门。service.py 提供只读查询，所有正式部门共享平台功能全集。此模块不注册 ORM，也不初始化或修改数据库表。

包入口仅保留注册表对象的既有公开导出，不导入查询服务或 Feature 注册表，
不连接数据库、请求外部服务或启动后台任务。调用方共享同一份不可变定义。

增加部门：在注册表添加 DepartmentSpec，即可使用平台全部检测能力。移除部门前，应先处理用户、摄像头及历史业务数据中的引用。
"""
from .department_registry import DEPARTMENT_SPECS, DepartmentSpec, require_department

__all__ = [
    "DEPARTMENT_SPECS",
    "DepartmentSpec",
    "require_department",
]
