"""事业部功能分配接口的数据契约。"""

from pydantic import BaseModel, ConfigDict, Field


class FeatureAssignment(BaseModel):
    """事业部、功能名列表与严格正整数版本号；拒绝输入未声明字段。"""
    model_config = ConfigDict(extra="forbid")

    department: str
    features: list[str]
    revision: int = Field(..., ge=1, strict=True)


class FeatureAssignmentsUpdate(BaseModel):
    """管理员提交的完整事业部分配集合，是否齐全与功能合法性由 Service 继续核验。"""
    model_config = ConfigDict(extra="forbid")

    assignments: list[FeatureAssignment]


class FeatureChoice(BaseModel):
    """功能分配页面可选项，使用持久化功能名及对应展示名称。"""
    name: str
    display_name: str


class FeatureAssignmentsResponse(BaseModel):
    """返回当前分配和平台完整功能目录，供页面编辑与版本冲突后刷新。"""
    assignments: list[FeatureAssignment]
    features: list[FeatureChoice]
