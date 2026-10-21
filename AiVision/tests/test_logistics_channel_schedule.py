"""统一时段的日期边界、时区和已有配置合并回归验证。"""
from datetime import datetime, time, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from AiVision.features.logistics_channel.schedule import (
    LogisticsSchedule,
    is_scheduled_time,
    schedule_from_storage,
)


@pytest.mark.parametrize(
    ("day", "clock", "expected"),
    [
        (19, time(8, 59, 59), False),
        (19, time(9), True),
        (19, time(12), True),
        (19, time(18), True),
        (19, time(18, 0, 0, 1), False),
        (25, time(12), False),
    ],
)
def test_detection_and_alarm_share_weekday_and_time_boundaries(day, clock, expected):
    schedule = LogisticsSchedule(weekdays=list(range(5)), start=time(9), end=time(18))
    now = datetime.combine(datetime(2026, 10, day), clock, ZoneInfo("Asia/Shanghai"))
    assert is_scheduled_time(schedule, now) is expected


def test_schedule_uses_its_own_timezone():
    schedule = LogisticsSchedule(start=time(9), end=time(18))
    assert is_scheduled_time(schedule, datetime(2026, 10, 19, 2, tzinfo=timezone.utc))
    assert not is_scheduled_time(schedule, datetime(2026, 10, 19, 0, 59, tzinfo=timezone.utc))


def test_empty_weekdays_disable_detection_and_alarm():
    schedule = LogisticsSchedule(weekdays=[])
    assert not is_scheduled_time(schedule, datetime(2026, 10, 19, 12, tzinfo=timezone.utc))


def test_api_time_strings_are_valid_and_weekdays_are_sorted():
    schedule = LogisticsSchedule.model_validate({"start": "09:15:00", "end": "18:30:00", "weekdays": [4, 0]})
    assert (schedule.start, schedule.end, schedule.weekdays) == (time(9, 15), time(18, 30), [0, 4])


@pytest.mark.parametrize(
    "values",
    [
        {"start": "18:00", "end": "09:00"},
        {"start": "09:00", "end": "09:00"},
        {"start": "09:00+08:00"},
        {"weekdays": [0, 0]},
        {"weekdays": [7]},
        {"weekdays": ["0"]},
        {"timezone": "invalid/timezone"},
    ],
)
def test_invalid_schedule_is_rejected(values):
    with pytest.raises(ValidationError):
        LogisticsSchedule.model_validate(values)


def test_existing_channel_without_calendar_uses_saved_detection_window():
    schedule = schedule_from_storage(time(7), time(19), None)
    assert (schedule.start, schedule.end, schedule.weekdays) == (time(7), time(19), list(range(7)))


def test_existing_windows_use_their_effective_overlap():
    stored = SimpleNamespace(weekdays=[0, 2, 4], start=time(9), end=time(22), timezone="Asia/Shanghai")
    schedule = schedule_from_storage(time(8), time(20), stored)
    assert (schedule.start, schedule.end, schedule.weekdays) == (time(9), time(20), [0, 2, 4])
    assert (stored.start, stored.end) == (time(9), time(22))


@pytest.mark.parametrize(("start", "end"), [(time(21), time(22)), (time(20), time(22))])
def test_non_overlapping_windows_remain_inactive(start, end):
    stored = SimpleNamespace(weekdays=[0], start=start, end=end, timezone="Asia/Shanghai")
    schedule = schedule_from_storage(time(8), time(20), stored)
    assert schedule.weekdays == []
    assert (schedule.start, schedule.end) == (time(8), time(20))


def test_saved_unified_window_is_stable_when_read_again():
    stored = SimpleNamespace(weekdays=[0, 1], start=time(6), end=time(23), timezone="Asia/Shanghai")
    schedule = schedule_from_storage(time(6), time(23), stored)
    assert schedule == LogisticsSchedule.model_validate(stored)
