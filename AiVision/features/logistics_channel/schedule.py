"""物流通道检测和报警共用的星期、每日时段与时区。"""
from datetime import datetime, time
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .constants import DEFAULT_DETECTION_START, DEFAULT_DETECTION_END


class LogisticsSchedule(BaseModel):
    """只有处于统一时段内，通道才进行检测并允许异常报警。"""
    model_config = ConfigDict(extra="forbid", strict=True, from_attributes=True)
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(
        default_factory=lambda: list(range(7)), description="周一为0，周日为6；空列表表示不检测、不报警",
    )
    start: time = Field(default=DEFAULT_DETECTION_START, strict=False, description="每日检测与报警开始时间，包含端点")
    end: time = Field(default=DEFAULT_DETECTION_END, strict=False, description="每日检测与报警结束时间，包含端点；须晚于开始时间")
    timezone: str = "Asia/Shanghai"

    @field_validator("weekdays")
    @classmethod
    def unique_days(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("检测与报警星期不能重复")
        return sorted(value)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("检测与报警时区无效") from exc
        return value

    @model_validator(mode="after")
    def ordered_times(self):
        """单端更新先核对格式，起止顺序由服务合并已保存配置后校验。"""
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError("检测与报警起止时间不能带时区")
        if {"start", "end"} <= self.model_fields_set and self.start >= self.end:
            raise ValueError("检测与报警时段必须在同一天内，且开始早于结束")
        return self


def is_scheduled_time(schedule: LogisticsSchedule, now: datetime) -> bool:
    """检测调度和报警分发使用相同的本地星期与含端点时段。"""
    local = now.astimezone(ZoneInfo(schedule.timezone))
    return local.weekday() in schedule.weekdays and schedule.start <= local.time() <= schedule.end


def schedule_from_storage(start: time, end: time, stored: object | None) -> LogisticsSchedule:
    """读取已有通道的有效交集，合并时不扩大原先允许报警的范围。"""
    detection = LogisticsSchedule(start=start, end=end)
    if stored is None:
        return detection
    schedule = LogisticsSchedule.model_validate(stored)
    overlap_start = max(detection.start, schedule.start)
    overlap_end = min(detection.end, schedule.end)
    if overlap_start >= overlap_end:
        # 没有有效交集时明确停用时段，保留可编辑的起止值。
        return LogisticsSchedule(**{**schedule.model_dump(), "weekdays": [], "start": start, "end": end})
    return LogisticsSchedule(**{**schedule.model_dump(), "start": overlap_start, "end": overlap_end})
