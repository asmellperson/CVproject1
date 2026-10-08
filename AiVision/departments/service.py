"""departments/service.py
部门管理服务。

函数：
    list_departments()：读取固定部门注册表。
    get_features_by_department()：读取数据库中分配给事业部的功能。
"""
from __future__ import annotations

from sqlalchemy import select

from AiVision.core.db import get_session
from AiVision.features.registry import all_specs
from .department_registry import DEPARTMENT_SPECS, DepartmentSpec, require_department
from .orm import DepartmentFeatureAccess
from .schema import FeatureAssignment, FeatureAssignmentsResponse, FeatureChoice


class FeatureAssignmentConflict(ValueError):
    """配置已被其他管理员修改，拒绝覆盖。"""


class DepartmentService:
    """连接固定事业部目录与数据库功能分配，按版本号原子保存全量配置。"""
    def __init__(self, session_factory=get_session):
        """注入 Session 工厂便于隔离事务与测试，构造时不读取数据库。"""
        self._session_factory = session_factory

    def list_departments(self) -> list[DepartmentSpec]:
        """列出所有固定部门，顺序与注册表一致。"""
        return list(DEPARTMENT_SPECS.values())

    def get_features_by_department(self, department: str) -> list[dict[str, str]]:
        """仅返回该事业部已分配的功能。"""
        require_department(department)
        features = self.feature_access()[department]
        return [
            {"name": spec.name, "display_name": spec.display_name}
            for spec in all_specs().values()
            if spec.name in features
        ]

    def assignments(self) -> list[FeatureAssignment]:
        """读取完整配置；缺少正式事业部时直接报错，不回退为全部开放。"""
        with self._session_factory() as session:
            rows = {row.department: row for row in session.scalars(select(DepartmentFeatureAccess))}
            if set(rows) != set(DEPARTMENT_SPECS):
                raise RuntimeError("事业部功能分配数据不完整，请检查数据库")
            return [FeatureAssignment(department=name, features=rows[name].features, revision=rows[name].revision)
                    for name in DEPARTMENT_SPECS]

    def feature_access(self) -> dict[str, list[str]]:
        """供认证、菜单与总览共用同一份数据库分配。"""
        return {item.department: item.features for item in self.assignments()}

    def feature_settings(self) -> FeatureAssignmentsResponse:
        """提供管理员编辑所需的分配与正式功能目录。"""
        return FeatureAssignmentsResponse(
            assignments=self.assignments(),
            features=[FeatureChoice(name=spec.name, display_name=spec.display_name)
                      for spec in all_specs().values()],
        )

    def save_feature_settings(self, assignments: list[FeatureAssignment]) -> FeatureAssignmentsResponse:
        """整表原子保存；先校验全部版本，避免并发覆盖及部分保存。"""
        names = [item.department for item in assignments]
        if len(names) != len(set(names)) or set(names) != set(DEPARTMENT_SPECS):
            raise ValueError("必须完整提交全部事业部，且不能重复")
        specs = all_specs()
        for item in assignments:
            if len(item.features) != len(set(item.features)) or set(item.features) - specs.keys():
                raise ValueError("功能列表包含重复或未注册的功能")
        with self._session_factory() as session, session.begin():
            rows = {row.department: row for row in session.scalars(
                select(DepartmentFeatureAccess).order_by(DepartmentFeatureAccess.department).with_for_update()
            )}
            if set(rows) != set(DEPARTMENT_SPECS):
                raise RuntimeError("事业部功能分配数据不完整，请检查数据库")
            if any(rows[item.department].revision != item.revision for item in assignments):
                raise FeatureAssignmentConflict("配置已被其他管理员修改，请重新加载后保存")
            for item in assignments:
                row = rows[item.department]
                features = [name for name in specs if name in item.features]
                if set(row.features) != set(features):
                    row.features = features
                    row.revision += 1
        return self.feature_settings()


# 创建一个全局实例
department_service = DepartmentService()
