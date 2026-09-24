"""事业部功能分配接口的数据契约。"""

from pydantic import BaseModel, ConfigDict, Field


class FeatureAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department: str
    features: list[str]
    revision: int = Field(..., ge=1, strict=True)


class FeatureAssignmentsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignments: list[FeatureAssignment]


class FeatureChoice(BaseModel):
    name: str
    display_name: str


class FeatureAssignmentsResponse(BaseModel):
    assignments: list[FeatureAssignment]
    features: list[FeatureChoice]
