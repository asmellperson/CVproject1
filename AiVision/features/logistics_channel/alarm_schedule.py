"""独立于检测时段的报警日历；禁报期间仍保留画面和检测状态。"""
from datetime import datetime, time
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LogisticsAlarmSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, from_attributes=True)
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(
        default_factory=lambda: list(range(7)), description="周一为0，周日为6；空列表表示不报警",
    )
    start: time = Field(default=time(0, 0), description="每天开始报警的时间，包含端点")
    end: time = Field(default=time(23, 59, 59), description="每天结束报警的时间，包含端点；须晚于开始时间")
    timezone: str = "Asia/Shanghai"

    @field_validator("weekdays")
    @classmethod
    def unique_days(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("报警星期不能重复")
        return sorted(value)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("报警计划时区无效") from exc
        return value

    @model_validator(mode="after")
    def ordered_times(self):
        if self.start.tzinfo or self.end.tzinfo or self.start.microsecond or self.end.microsecond or self.start >= self.end:
            raise ValueError("报警起止时间必须是同一天内不带时区的时刻，且开始早于结束")
        return self


def is_alarm_time(schedule: LogisticsAlarmSchedule, now: datetime) -> bool:
    local = now.astimezone(ZoneInfo(schedule.timezone))
    return local.weekday() in schedule.weekdays and schedule.start <= local.time().replace(microsecond=0) <= schedule.end
