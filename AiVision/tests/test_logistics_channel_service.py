from datetime import time

import pytest
from pydantic import ValidationError

from platform.logistics_channel.constants import require_logistics_feature
from platform.logistics_channel.orm import LogisticsChannel
from platform.logistics_channel.schema import (
    LogisticsChannelConfigUpdate,
    LogisticsChannelMemberCreate,
)


def test_logistics_channel_has_required_python_defaults():
    columns = LogisticsChannel.__table__.c

    assert columns.enabled.default.arg is True
    assert columns.detection_start.default.arg == time(8, 0)
    assert columns.detection_end.default.arg == time(20, 0)
    assert columns.empty_grace_seconds.default.arg == 2.0
    assert columns.multi_grace_seconds.default.arg == 1.0


def test_unknown_logistics_feature_is_rejected():
    with pytest.raises(ValueError, match="不支持的物流检测功能"):
        require_logistics_feature("blocks")


def test_member_accepts_existing_camera_id_mode():
    member = LogisticsChannelMemberCreate(camera_id=12)

    assert member.camera_id == 12
    assert member.name is None
    assert member.url is None


def test_member_accepts_new_camera_name_url_mode():
    member = LogisticsChannelMemberCreate(name="入口摄像头", url="rtsp://example/cam", fps=5)

    assert member.camera_id is None
    assert member.name == "入口摄像头"
    assert member.url == "rtsp://example/cam"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"camera_id": 1, "name": "入口", "url": "rtsp://example/cam", "fps": 5},
        {"name": "入口", "url": "rtsp://example/cam", "fps": 0},
        {"name": "入口"},
    ],
)
def test_member_requires_exactly_one_camera_input_mode(payload):
    with pytest.raises(ValidationError):
        LogisticsChannelMemberCreate(**payload)


def test_channel_config_requires_start_before_end():
    with pytest.raises(ValidationError):
        LogisticsChannelConfigUpdate(detection_start=time(20, 0), detection_end=time(8, 0))
