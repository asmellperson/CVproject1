# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""platform/department/orm.py
部门主表 & 功能-部门映射表 ORM。
"""
from __future__ import annotations

from sqlalchemy import Column, Integer, String, UniqueConstraint

from core.db import Base


# 功能：定义 `AiDepartment` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：AiDepartment；返回新建的 `AiDepartment` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/department/service.py` 的 `DepartmentService::create_department` 实例化本符号
#   - 内部调用：`Column`、`String`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AiDepartment(Base):
    __tablename__ = "ai_department"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, comment="部门标识，如 general_electric/research_institute")
    display_name = Column(String(100), nullable=False, comment="部门显示名称，如 通用电气/福达新材院")

    # 功能：实现 `__repr__` 对应的数据库模型逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def __repr__(self):
        return f"<AiDepartment name={self.name!r} display={self.display_name!r}>"


# 功能：定义 `AiFeatureDepartment` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：AiFeatureDepartment；返回新建的 `AiFeatureDepartment` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/department/service.py` 的 `DepartmentService::set_feature_departments`
#         实例化本符号；`AiVision/api/departments.py` 的 `set_department_features` 实例化本符号
#   - 内部调用：`Column`、`String`、`UniqueConstraint`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AiFeatureDepartment(Base):
    __tablename__ = "ai_feature_department"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feature_name = Column(
        String(100), nullable=False, unique=False,
        comment="功能名如 blocks/detect_face/detect_door/detect_human/detect_phone"
    )
    department = Column(
        String(100), nullable=False, unique=False,
        comment="部门如 general_electric/research_institute"
    )

    __table_args__ = (
        UniqueConstraint("feature_name", "department", name="uq_feature_department"),
    )

    # 功能：实现 `__repr__` 对应的数据库模型逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def __repr__(self):
        return f"<AiFeatureDepartment feature={self.feature_name!r} dept={self.department!r}>"
