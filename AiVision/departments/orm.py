"""事业部功能分配；仅控制访问权限，不控制检测任务启停。"""

from sqlalchemy import CheckConstraint, Column, Integer, JSON, String

from AiVision.core.db import Base


class DepartmentFeatureAccess(Base):
    __tablename__ = "department_feature_access"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_department_feature_revision"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin"},
    )

    department = Column(String(64), primary_key=True)
    features = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
