"""platform/department/orm.py
部门主表 & 功能-部门映射表 ORM。
"""
from __future__ import annotations

from sqlalchemy import Column, Integer, String, UniqueConstraint

from core.db import Base


class AiDepartment(Base):
    __tablename__ = "ai_department"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, comment="部门标识，如 general_electric/research_institute")
    display_name = Column(String(100), nullable=False, comment="部门显示名称，如 通用电气/福达新材院")

    def __repr__(self):
        return f"<AiDepartment name={self.name!r} display={self.display_name!r}>"


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

    def __repr__(self):
        return f"<AiFeatureDepartment feature={self.feature_name!r} dept={self.department!r}>"
