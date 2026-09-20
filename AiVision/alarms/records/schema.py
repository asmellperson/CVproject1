"""报警查询与处置接口的正式数据契约。"""
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

DispositionStatus = Literal["pending", "acknowledged", "resolved", "false_positive"]
DISPOSITION_HISTORY_LIMIT = 20


def _validate_alarm_id(value: str) -> str:
    if int(value) > 2**64 - 1:
        raise ValueError("报警 ID 超出范围")
    return value


AlarmId = Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,19}$"), AfterValidator(_validate_alarm_id)]


class DispositionActor(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    employee_id: str
    name: str


class DispositionChange(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    status: DispositionStatus
    note: str
    updated_at: str
    updated_by: DispositionActor


class AlarmDisposition(DispositionChange):
    alarm_id: AlarmId
    history: list[DispositionChange]


class DispositionUpdate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    alarm_id: AlarmId
    status: DispositionStatus
    note: str = ""


class DispositionPage(BaseModel):
    items: list[AlarmDisposition]
    next_cursor: AlarmId | None


class AlarmEventResponse(BaseModel):
    """统一告警事件及处置摘要。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    event_type: str
    event_label: str
    violation_type: int | None = None
    feature_name: str | None = None
    department: str | None = None
    camera_no: str | None = None
    camera_name: str | None = None
    subject_type: str
    subject_id: str | None = None
    subject_name: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    reason: str
    status: str | None = None
    confidence: float = 1
    created_at: str | None = None
    image_path: str | None = None
    image_url: str
    video_path: str | None = None
    video_status: str | None = None
    video_url: str | None = None
    disposition_status: DispositionStatus = "pending"
    disposition_note: str = ""
    disposition_updated_at: str | None = None
    disposition_updated_by: DispositionActor | None = None

    camera_ids: list[int] = Field(default_factory=list)
    camera_names: dict[str, str] = Field(default_factory=dict)
    camera_counts: dict[str, int | None] = Field(default_factory=dict)
    camera_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    offending_camera_ids: list[int] = Field(default_factory=list)

    evidence_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class AlarmListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


    items: list[AlarmEventResponse] = Field(default_factory=list)
