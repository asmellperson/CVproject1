from datetime import time, timezone

import pytest
from pydantic import ValidationError

from platform.logistics_channel.constants import (
    DEFAULT_STATUS_STALE_SECONDS,
    LOGISTICS_FEATURES,
    MAX_CAMERAS_PER_CHANNEL,
    require_logistics_feature,
)
from platform.logistics_channel.orm import LogisticsChannel, LogisticsChannelCamera
from platform.logistics_channel.schema import (
    LogisticsChannelAlarm,
    LogisticsChannelConfigUpdate,
    LogisticsChannelDetailResponse,
    LogisticsChannelMemberCreate,
    LogisticsChannelMemberOrder,
    LogisticsChannelStatusResponse,
    LogisticsFeatureName,
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


def test_logistics_feature_literal_matches_feature_whitelist():
    assert set(LogisticsFeatureName.__args__) == LOGISTICS_FEATURES


def test_status_constants_and_reasons_are_stable():
    assert DEFAULT_STATUS_STALE_SECONDS == 5.0
    assert set(LogisticsChannelStatusResponse.model_fields["reason"].annotation.__args__) == {
        "normal", "empty", "multiple", "unknown", "unconfigured", "inactive",
    }


def test_member_accepts_existing_camera_id_mode():
    member = LogisticsChannelMemberCreate(camera_id=12)

    assert member.camera_id == 12
    assert member.name is None
    assert member.url is None


def test_member_existing_camera_mode_rejects_explicit_new_camera_fields():
    with pytest.raises(ValidationError):
        LogisticsChannelMemberCreate(camera_id=12, shm_name="cam-12")
    with pytest.raises(ValidationError):
        LogisticsChannelMemberCreate(camera_id=12, fps=5)


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


def test_member_rejects_unknown_fields_and_non_positive_camera_id():
    with pytest.raises(ValidationError):
        LogisticsChannelMemberCreate(camera_id=0)
    with pytest.raises(ValidationError):
        LogisticsChannelMemberCreate(camera_id=1, unknown=True)


def test_member_order_limits_routes_to_nine_positive_unique_ids():
    assert LogisticsChannelMemberOrder(camera_ids=list(range(1, MAX_CAMERAS_PER_CHANNEL + 1))).camera_ids
    with pytest.raises(ValidationError):
        LogisticsChannelMemberOrder(camera_ids=list(range(1, MAX_CAMERAS_PER_CHANNEL + 2)))
    with pytest.raises(ValidationError):
        LogisticsChannelMemberOrder(camera_ids=[0])
    with pytest.raises(ValidationError):
        LogisticsChannelMemberOrder(camera_ids=[1, 1])


def test_channel_config_requires_start_before_end():
    with pytest.raises(ValidationError):
        LogisticsChannelConfigUpdate(detection_start=time(20, 0), detection_end=time(8, 0))


def test_channel_config_rejects_aware_times_without_type_error():
    with pytest.raises(ValidationError):
        LogisticsChannelConfigUpdate(
            detection_start=time(8, 0, tzinfo=timezone.utc),
            detection_end=time(20, 0),
        )


def test_enabled_horn_requires_positive_device_and_event_ids():
    with pytest.raises(ValidationError):
        LogisticsChannelAlarm(horn={"enabled": True})
    with pytest.raises(ValidationError):
        LogisticsChannelAlarm(horn={"enabled": False, "horn_id": 0})


def test_channel_orm_constraints_foreign_keys_and_relationships():
    channel_constraints = {constraint.name for constraint in LogisticsChannel.__table__.constraints}
    member_constraints = {constraint.name for constraint in LogisticsChannelCamera.__table__.constraints}
    camera_fk = next(fk for fk in LogisticsChannelCamera.__table__.foreign_keys if fk.column.table.name == "ai_camera_config")
    channel_fk = next(fk for fk in LogisticsChannelCamera.__table__.foreign_keys if fk.column.table.name == "ai_logistics_channel")

    assert "uq_logistics_channel_feature_name" in channel_constraints
    assert "uq_logistics_channel_camera" in member_constraints
    assert camera_fk.ondelete == "CASCADE"
    assert channel_fk.ondelete == "CASCADE"
    assert LogisticsChannel.cameras.property.cascade.delete_orphan
    assert LogisticsChannel.cameras.property.passive_deletes is True


def test_detail_response_adapts_orm_flat_fields_and_camera_relationship():
    channel = LogisticsChannel(
        id=1,
        name="收货通道",
        feature_name="detect_logistics_single_person",
        enabled=True,
        sort_order=2,
        detection_start=time(8, 0),
        detection_end=time(20, 0),
        empty_grace_seconds=2.0,
        multi_grace_seconds=1.0,
        alarm_interval=5.0,
        sql_enable=True,
        horn_enable=True,
        horn_id=3,
        horn_event_id=4,
        wechat_enable=True,
        wechat_user="operator",
    )
    channel.cameras = [LogisticsChannelCamera(id=7, channel_id=1, camera_id=9, enabled=True, sort_order=0)]

    response = LogisticsChannelDetailResponse.model_validate(channel)

    assert response.config.alarm.horn.horn_id == 3
    assert response.config.alarm.wechat.user == "operator"
    assert response.members[0].camera_id == 9
