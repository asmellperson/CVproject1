# 文件说明：封装业务服务的业务规则与持久化访问。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""platform/department/service.py
部门管理服务。
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from sqlalchemy import delete

from core.cache import config_cache
from core.events import ConfigChangeEvent
from features import all_specs
from platform.department.orm import AiDepartment, AiFeatureDepartment

logger = logging.getLogger("aivision.department.service")


# 功能：定义 `DepartmentService` 类，封装业务服务相关的状态、约束与操作
# 参数：无。
# 返回：DepartmentService；返回新建的 `DepartmentService` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DepartmentService:
    # 功能：列出所有部门；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    # 返回：list[AiDepartment]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`select(AiDepartment).order_by`、`select`、`list`、`session.scalars(stmt).all`、`session.scalars`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_departments(self, session) -> list[AiDepartment]:
        """列出所有部门。"""
        from sqlalchemy import select
        stmt = select(AiDepartment).order_by(AiDepartment.id)
        return list(session.scalars(stmt).all())

    # 功能：根据名称获取单个部门；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `name`（str）：业务对象名称
    # 返回：Optional[AiDepartment]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/department/service.py` 的 `DepartmentService::update_department`
    #         调用本符号；`AiVision/platform/department/service.py` 的 `DepartmentService::delete_department`
    #         调用本符号；`AiVision/platform/department/service.py` 的 `DepartmentService::ensure_seed_data` 调用本符号
    #   - 内部调用：`select(AiDepartment).where`、`select`、`session.scalar`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_department(self, session, name: str) -> Optional[AiDepartment]:
        """根据名称获取单个部门。"""
        from sqlalchemy import select
        stmt = select(AiDepartment).where(AiDepartment.name == name)
        return session.scalar(stmt)

    # 功能：创建部门 (admin only)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
    # 返回：AiDepartment；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/department/service.py` 的 `DepartmentService::ensure_seed_data` 调用本符号
    #   - 内部调用：`AiDepartment`、`session.add`、`session.flush`、`logger.info`、`config_cache.reload`、`ConfigChangeEvent.publish_departments_changed`。
    # 副作用/注意事项：可能读取或修改数据库事务；会向日志系统输出运行或异常信息。
    def create_department(self, session, payload: dict[str, Any]) -> AiDepartment:
        """创建部门 (admin only)。"""
        dept = AiDepartment(name=payload["name"], display_name=payload["display_name"])
        session.add(dept)
        session.flush()
        logger.info("[dept] created department: %s", payload)
        config_cache.reload()
        ConfigChangeEvent.publish_departments_changed()
        return dept

    # 功能：更新部门 (admin only)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `name`（str）：业务对象名称
    #   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
    # 返回：Optional[AiDepartment]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.get_department`、`session.flush`、`logger.info`、`config_cache.reload`、`ConfigChangeEvent.publish_departments_changed`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def update_department(self, session, name: str, payload: dict[str, Any]) -> Optional[AiDepartment]:
        """更新部门 (admin only)。"""
        dept = self.get_department(session, name)
        if not dept:
            return None
        if "display_name" in payload:
            dept.display_name = payload["display_name"]
        session.flush()
        logger.info("[dept] updated department %s: %s", name, payload)
        config_cache.reload()
        ConfigChangeEvent.publish_departments_changed()
        return dept

    # 功能：删除部门 (admin only)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `name`（str）：业务对象名称
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.get_department`、`session.execute`、`delete(AiFeatureDepartment).where`、`delete`、`session.delete`、`session.flush`、`logger.info`、`config_cache.reload`、`ConfigChangeEvent.publish_departments_changed`。
    # 副作用/注意事项：可能读取或修改数据库事务；会向日志系统输出运行或异常信息。
    def delete_department(self, session, name: str) -> bool:
        """删除部门 (admin only)。"""
        dept = self.get_department(session, name)
        if not dept:
            return False
        session.execute(delete(AiFeatureDepartment).where(AiFeatureDepartment.department == name))
        session.delete(dept)
        session.flush()
        logger.info("[dept] deleted department: %s", name)
        config_cache.reload()
        ConfigChangeEvent.publish_departments_changed()
        return True

    # 功能：获取部门下的功能列表；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `department`（str）：业务部门名称或标识
    # 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/api/compat.py` 的 `compat_get_department_features` 调用本符号；`AiVision/api/departments.py` 的
    #         `get_department_features` 调用本符号
    #   - 内部调用：`select(AiFeatureDepartment).where`、`select`、`session.scalars(stmt).all`、`session.scalars`、`all_specs`、`specs.get`、`features.append`、`specs.items`、`hasattr`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_features_by_department(self, session, department: str) -> list[dict[str, Any]]:
        """获取部门下的功能列表。"""
        # First, try to get from DB
        from sqlalchemy import select
        stmt = select(AiFeatureDepartment).where(AiFeatureDepartment.department == department)
        db_feature_names = [row.feature_name for row in session.scalars(stmt).all()]
        specs = all_specs()

        if db_feature_names:
            # If DB has data, return those
            features = []
            for name in db_feature_names:
                if spec := specs.get(name):
                    features.append({"name": spec.name, "display_name": spec.display_name})
            return features

        # Else, fallback to FeatureSpec.departments
        features = []
        for name, spec in specs.items():
            if hasattr(spec, "departments") and department in spec.departments:
                features.append({"name": spec.name, "display_name": spec.display_name})
        return features

    # 功能：获取功能归属的部门列表；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：list[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/department/service.py` 的 `DepartmentService::ensure_seed_data`
    #         调用本符号；`AiVision/api/features.py` 的 `create_features_router::_spec_to_meta` 调用本符号
    #   - 内部调用：`select(AiFeatureDepartment).where`、`select`、`session.scalars(stmt).all`、`session.scalars`、`all_specs`、`specs.get`、`hasattr`、`list`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_departments_by_feature(self, session, feature_name: str) -> list[str]:
        """获取功能归属的部门列表。"""
        from sqlalchemy import select
        stmt = select(AiFeatureDepartment).where(AiFeatureDepartment.feature_name == feature_name)
        db_depts = [row.department for row in session.scalars(stmt).all()]
        if db_depts:
            return db_depts
        # Fallback to FeatureSpec.departments
        specs = all_specs()
        if spec := specs.get(feature_name):
            if hasattr(spec, "departments"):
                return list(spec.departments)
        return []

    # 功能：设置功能的部门列表 (admin only)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `dept_names`（Sequence[str]）：`dept_names` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/department/service.py` 的 `DepartmentService::ensure_seed_data` 调用本符号
    #   - 内部调用：`session.execute`、`delete(AiFeatureDepartment).where`、`delete`、`session.add`、`AiFeatureDepartment`、`session.flush`、`logger.info`、`config_cache.reload`、`ConfigChangeEvent.publish_departments_changed`。
    # 副作用/注意事项：可能读取或修改数据库事务；会向日志系统输出运行或异常信息。
    def set_feature_departments(self, session, feature_name: str, dept_names: Sequence[str]) -> None:
        """设置功能的部门列表 (admin only)。"""
        # Delete old mappings
        session.execute(delete(AiFeatureDepartment).where(AiFeatureDepartment.feature_name == feature_name))
        # Add new mappings
        for dept in dept_names:
            session.add(AiFeatureDepartment(feature_name=feature_name, department=dept))
        session.flush()
        logger.info("[dept] set feature %s departments: %s", feature_name, dept_names)
        config_cache.reload()
        ConfigChangeEvent.publish_departments_changed()

    # 功能：移除功能的单个部门映射 (admin only)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `dept_name`（str）：`dept_name` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session.execute`、`delete(AiFeatureDepartment).where`、`delete`、`session.flush`、`logger.info`、`config_cache.reload`、`ConfigChangeEvent.publish_departments_changed`。
    # 副作用/注意事项：可能读取或修改数据库事务；会向日志系统输出运行或异常信息。
    def remove_feature_department(self, session, feature_name: str, dept_name: str) -> None:
        """移除功能的单个部门映射 (admin only)。"""
        session.execute(
            delete(AiFeatureDepartment).where(
                AiFeatureDepartment.feature_name == feature_name,
                AiFeatureDepartment.department == dept_name
            )
        )
        session.flush()
        logger.info("[dept] removed feature %s from dept %s", feature_name, dept_name)
        config_cache.reload()
        ConfigChangeEvent.publish_departments_changed()

    # 功能：确保种子数据存在（部门 + feature-department 映射）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session`（未显式标注）：数据库会话或运行会话
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.get_department`、`self.create_department`、`session.flush`、`all_specs`、`specs.items`、`self.get_departments_by_feature`、`hasattr`、`self.set_feature_departments`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def ensure_seed_data(self, session) -> None:
        """确保种子数据存在（部门 + feature-department 映射）。"""
        # Seed departments
        seed_departments = [
            {"name": "general_electric", "display_name": "通用电气"},
            {"name": "research_institute", "display_name": "福达新材院"},
            {"name": "electronics_electrician", "display_name": "电子电工"},
            {"name": "electrical_components", "display_name": "电气部件事业部"},
            {"name": "precious_metal_recycling", "display_name": "伟达公司"},
            {"name": "haoda_company", "display_name": "皓达公司"},
        ]
        for seed in seed_departments:
            department = self.get_department(session, seed["name"])
            if department is None:
                self.create_department(session, seed)
            elif department.display_name != seed["display_name"]:
                department.display_name = seed["display_name"]
                session.flush()
        # Seed feature-department mappings only if DB is empty
        specs = all_specs()
        for name, spec in specs.items():
            current = self.get_departments_by_feature(session, name)
            if not current:
                if hasattr(spec, "departments") and spec.departments:
                    self.set_feature_departments(session, name, spec.departments)


department_service = DepartmentService()
