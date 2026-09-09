# 文件说明：包含运行时的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

from datetime import datetime, time, timezone
from threading import Event, Thread
from types import SimpleNamespace

import numpy as np
import pytest

FEATURE = "detect_logistics_single_person"
OTHER_FEATURE = FEATURE


def test_default_camera_provider_preserves_numeric_primary_key(monkeypatch):
    import AiVision.platform.logistics_channel.runtime as runtime_module

    requested = []
    monkeypatch.setattr(
        runtime_module.camera_config_manager, "get_camera",
        lambda key: requested.append(key) or {"camera_id": key, "shm_name": "warehouse"},
    )
    runtime = runtime_module.LogisticsChannelRuntime(start_background=False)
    assert runtime._camera_provider(12)["camera_id"] == 12
    assert requested == [12]
    assert isinstance(requested[0], int)


# 功能：定义 `FakeChannelService` 类，封装运行时相关的状态、约束与操作
# 参数：
#   - `channels`（未显式标注）：`channels` 对应的业务输入值
# 返回：FakeChannelService；返回新建的 `FakeChannelService` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的 `build_runtime`
#         实例化本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
#         `test_refresh_during_slow_composition_discards_stale_incident_result`
#         实例化本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
#         `test_camera_rename_and_delete_refresh_real_runtime_membership_cache` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeChannelService:
    # 功能：初始化或配置 `__init__` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `channels`（未显式标注）：`channels` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, channels):
        self.channels = {(item["feature_name"], item["id"]): item for item in channels}

    # 功能：读取或查询 `list_channels` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.channels.items`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_channels(self, feature_name):
        return {
            "items": [
                {key: channel[key] for key in ("id", "name", "feature_name", "enabled", "sort_order")}
                for (feature, _channel_id), channel in self.channels.items()
                if feature == feature_name
            ]
        }

    # 功能：读取或查询 `get_channel` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.channels.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_channel(self, feature_name, channel_id):
        return self.channels.get((feature_name, channel_id))

    # 功能：实现 `migrate_existing_feature_cameras` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`SimpleNamespace`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def migrate_existing_feature_cameras(self):
        return SimpleNamespace(created=0, skipped=0, failed=0, errors=())


# 功能：定义 `FakeDispatcher` 类，封装运行时相关的状态、约束与操作
# 参数：无。
# 返回：FakeDispatcher；返回新建的 `FakeDispatcher` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的 `build_runtime` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeDispatcher:
    # 功能：初始化或配置 `__init__` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        self.requests = []
        self.reset_calls = []

    # 功能：发送或分发 `maybe_dispatch` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `request`（未显式标注）：当前 HTTP 请求及上下文
    #   - `alarm_interval`（未显式标注）：`alarm_interval` 对应的时间间隔或时长；默认值为 `5.0`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.requests.append`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    def maybe_dispatch(self, request, alarm_interval=5.0):
        self.requests.append((request, alarm_interval))
        return True

    # 功能：实现 `reset_subject_cooldown` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `subject_type`（未显式标注）：`subject_type` 对应的业务输入值
    #   - `subject_id`（未显式标注）：`subject_id` 对应业务对象的唯一标识
    #   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.reset_calls.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def reset_subject_cooldown(self, subject_type, subject_id, feature_name):
        self.reset_calls.append((subject_type, subject_id, feature_name))


# 功能：实现 `channel` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识；默认值为 `3`
#   - `feature`（未显式标注）：`feature` 对应的业务输入值；默认值为 `FEATURE`
#   - `member_ids`（未显式标注）：`member_ids` 对应的业务输入值；默认值为 `(10, 11)`
#   - `empty_grace`（未显式标注）：`empty_grace` 对应的业务输入值；默认值为 `0.0`
#   - `multi_grace`（未显式标注）：`multi_grace` 对应的业务输入值；默认值为 `0.0`
#   - `enabled`（未显式标注）：是否启用相应能力；默认值为 `True`
#   - `start`（未显式标注）：`start` 对应的业务输入值；默认值为 `time(0, 0)`
#   - `end`（未显式标注）：`end` 对应的业务输入值；默认值为 `time(23, 59, 59)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的 `test_partial_unknown_does_not_trigger_empty_but_known_multiple_wins`
#         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
#         `test_runtime_exposes_channel_person_confidence_threshold_by_camera`
#         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的 `test_channel_root_enabled_is_the_only_runtime_switch`
#         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
#         `test_disabled_members_are_excluded_from_aggregation_status_and_composite` 调用本符号；另有 17 处静态调用
#   - 内部调用：`time`、`enumerate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def channel(
    channel_id=3,
    *,
    feature=FEATURE,
    department="general_electric",
    member_ids=(10, 11),
    empty_grace=0.0,
    multi_grace=0.0,
    enabled=True,
    start=time(0, 0),
    end=time(23, 59, 59),
):
    return {
        "id": channel_id,
        "name": f"物流通道-{channel_id}",
        "feature_name": feature,
        "department": department,
        "enabled": enabled,
        "sort_order": 0,
        "config": {
            "detection_start": start,
            "detection_end": end,
            "confidence_threshold": 0.42,
            "empty_grace_seconds": empty_grace,
            "multi_grace_seconds": multi_grace,
            "alarm_interval": 13.0,
            "alarm": {
                "sql_enable": True,
                "horn": {"enabled": False, "horn_id": None, "horn_event_id": None},
                "wechat": {"enabled": False, "user": ""},
            },
        },
        "members": [
            {"id": index, "channel_id": channel_id, "camera_id": camera_id, "enabled": True, "sort_order": index}
            for index, camera_id in enumerate(member_ids, start=1)
        ],
    }


# 功能：创建或构建 `build_runtime` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `channels`（未显式标注）：`channels` 对应的业务输入值
#   - `active`（未显式标注）：`active` 对应的业务输入值；默认值为 `None`
#   - `wall_time`（未显式标注）：`wall_time` 对应的业务输入值；默认值为 `None`
#   - `cameras`（未显式标注）：`cameras` 对应的业务输入值；默认值为 `None`
#   - `raw_frames`（未显式标注）：`raw_frames` 对应的业务输入值；默认值为 `None`
#   - `compositor`（未显式标注）：`compositor` 对应的业务输入值；默认值为 `None`
#   - `start_background`（未显式标注）：`start_background` 对应的业务输入值；默认值为 `False`
#   - `clock`（未显式标注）：`clock` 对应的业务输入值；默认值为 `None`
#   - `stop_timeout`（未显式标注）：`stop_timeout` 对应的业务输入值；默认值为 `2.0`
#   - `dispatcher`（未显式标注）：`dispatcher` 对应的业务输入值；默认值为 `None`
#   - `channel_service`（未显式标注）：`channel_service` 对应的业务输入值；默认值为 `None`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的 `test_partial_unknown_does_not_trigger_empty_but_known_multiple_wins`
#         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
#         `test_runtime_exposes_channel_person_confidence_threshold_by_camera`
#         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的 `test_channel_root_enabled_is_the_only_runtime_switch`
#         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
#         `test_disabled_members_are_excluded_from_aggregation_status_and_composite` 调用本符号；另有 16 处静态调用
#   - 内部调用：`sys.modules.get`、`hasattr`、`sys.modules.pop`、`FakeDispatcher`、`LogisticsChannelRuntime`、`FakeChannelService`、`cameras.get`、`int`、`(raw_frames
#          or {}).get`、`datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc).astimezone` 等共 12 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def build_runtime(
    channels,
    *,
    active=None,
    wall_time=None,
    cameras=None,
    raw_frames=None,
    compositor=None,
    start_background=False,
    clock=None,
    stop_timeout=2.0,
    dispatcher=None,
    channel_service=None,
):
    from AiVision.platform.logistics_channel.runtime import LogisticsChannelRuntime

    dispatcher = dispatcher or FakeDispatcher()
    cameras = cameras or {
        camera_id: {
            "id": camera_id,
            "name": f"摄像头-{camera_id}",
            "shm_name": f"camera_{camera_id}",
        }
        for item in channels
        for camera_id in [member["camera_id"] for member in item["members"]]
    }
    runtime = LogisticsChannelRuntime(
        channel_service=channel_service or FakeChannelService(channels),
        dispatcher=dispatcher,
        camera_provider=lambda camera_id: cameras.get(int(camera_id)),
        is_camera_active=active or (lambda _shm_name: True),
        frame_provider=lambda shm_name: (raw_frames or {}).get(shm_name),
        stale_seconds=5.0,
        wall_time_provider=wall_time
        or (lambda: datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc).astimezone()),
        violation_type_provider=lambda _feature_name: 6,
        compositor=compositor,
        start_background=start_background,
        clock_provider=clock,
        stop_timeout_seconds=stop_timeout,
    )
    runtime.start()
    return runtime, dispatcher


# 功能：实现 `snapshot` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `camera_id`（未显式标注）：摄像头唯一标识
#   - `count`（未显式标注）：`count` 对应的数量或大小
#   - `now`（未显式标注）：`now` 对应的业务输入值；默认值为 `100.0`
#   - `online`（未显式标注）：`online` 对应的业务输入值；默认值为 `True`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`CameraSnapshot`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def snapshot(camera_id, count, *, now=100.0, online=True):
    from AiVision.platform.logistics_channel.state import CameraSnapshot

    return CameraSnapshot(
        camera_id=camera_id,
        camera_name=f"摄像头-{camera_id}",
        count=count,
        updated_at=now,
        online=online,
    )


# 功能：验证 `test_partial_unknown_does_not_trigger_empty_but_known_multiple_wins` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_runtime`、`channel`、`runtime.update_camera_snapshot`、`snapshot`、`np.zeros`、`runtime.evaluate`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_partial_unknown_does_not_trigger_empty_but_known_multiple_wins():
    runtime, dispatcher = build_runtime([channel()])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 0), np.zeros((8, 8, 3), np.uint8))

    unknown = runtime.evaluate(FEATURE, 3, now=100.0)

    assert unknown.reason == "unknown"
    assert dispatcher.requests == []

    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), np.zeros((8, 8, 3), np.uint8))
    multiple = runtime.evaluate(FEATURE, 3, now=100.1)

    assert multiple.reason == "multiple"
    assert multiple.alarm is True
    assert len(dispatcher.requests) == 1


# 功能：验证 `test_runtime_exposes_channel_person_confidence_threshold_by_camera` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_runtime`、`channel`、`runtime.person_confidence_threshold`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_runtime_exposes_channel_person_confidence_threshold_by_camera():
    runtime, _dispatcher = build_runtime([channel(member_ids=(10,))])

    assert runtime.person_confidence_threshold(FEATURE, 10) == 0.42
    assert runtime.person_confidence_threshold(FEATURE, 999) is None


# 功能：验证 `test_channel_root_enabled_is_the_only_runtime_switch` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`channel`、`build_runtime`、`runtime.evaluate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_channel_root_enabled_is_the_only_runtime_switch():
    item = channel(enabled=True, member_ids=(10,))
    item["config"]["enabled"] = False
    runtime, _dispatcher = build_runtime([item])

    runtime.evaluate(FEATURE, 3, now=100.0)

    assert runtime._channels[(FEATURE, 3)].enabled is True


# 功能：验证 `test_disabled_members_are_excluded_from_aggregation_status_and_composite` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`channel`、`build_runtime`、`runtime.update_camera_snapshot`、`snapshot`、`runtime.evaluate`、`runtime.get_channel_status`、`runtime.get_composite_frame`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_disabled_members_are_excluded_from_aggregation_status_and_composite():
    item = channel(member_ids=(10, 11))
    item["members"][1]["enabled"] = False
    composed = []

    # 功能：实现 `compositor` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `tiles`（未显式标注）：`tiles` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`composed.append`、`tuple`、`np.zeros`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def compositor(tiles):
        composed.append(tuple(tile.camera_id for tile in tiles))
        return np.zeros((20, 30, 3), np.uint8)

    runtime, dispatcher = build_runtime([item], compositor=compositor)
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 1), None)
    runtime.update_camera_snapshot(FEATURE, snapshot(11, 2), None)

    assert runtime.evaluate(FEATURE, 3, now=100.0).reason == "normal"
    status = runtime.get_channel_status(FEATURE, 3)
    assert status["camera_ids"] == [10]
    assert "11" not in status["camera_states"]
    assert runtime.get_composite_frame(FEATURE, 3).shape == (20, 30, 3)
    assert composed == [(10,)]
    assert dispatcher.requests == []


# 功能：验证 `test_inactive_detection_window_still_composes_live_preview_frames` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`channel`、`time`、`np.full`、`build_runtime`、`datetime`、`runtime.update_camera_snapshot`、`snapshot`、`runtime.evaluate`、`runtime.get_composite_frame`、`len`
#          等共 13 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_inactive_detection_window_still_composes_live_preview_frames():
    item = channel(
        member_ids=(10, 11),
        start=time(8, 0),
        end=time(20, 0),
    )
    raw_frames = {
        "camera_10": np.full((8, 12, 3), 10, np.uint8),
        "camera_11": np.full((8, 12, 3), 20, np.uint8),
    }
    captured = []

    # 功能：实现 `compositor` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `tiles`（未显式标注）：`tiles` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`captured.append`、`tuple`、`np.concatenate`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def compositor(tiles):
        captured.append(tuple(tile.frame for tile in tiles))
        return np.concatenate([tile.frame for tile in tiles], axis=1)

    runtime, _dispatcher = build_runtime(
        [item],
        raw_frames=raw_frames,
        wall_time=lambda: datetime(2026, 8, 7, 22, 55),
        compositor=compositor,
    )
    runtime.update_camera_snapshot(
        FEATURE,
        snapshot(10, 1),
        np.full((8, 12, 3), 99, np.uint8),
    )

    assert runtime.evaluate(FEATURE, 3, now=100.0).reason == "inactive"
    frame = runtime.get_composite_frame(FEATURE, 3)

    assert frame.shape == (8, 24, 3)
    assert len(captured) == 1
    assert all(tile_frame is not None for tile_frame in captured[0])
    assert np.all(frame[:, :12] == 10)
    assert np.all(frame[:, 12:] == 20)
    status = runtime.get_channel_status(FEATURE, 3)
    assert status["camera_states"]["10"]["stale_reason"] == "detection_inactive"


# 功能：验证 `test_alarm_incident_reopens_after_recovery_without_resetting_cooldown` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_runtime`、`channel`、`np.full`、`runtime.update_camera_snapshot`、`snapshot`、`runtime.evaluate`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_alarm_incident_reopens_after_recovery_without_resetting_cooldown():
    runtime, dispatcher = build_runtime([channel(member_ids=(10,))])
    frame = np.full((12, 16, 3), 20, np.uint8)

    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), frame)
    runtime.evaluate(FEATURE, 3, now=100.0)
    runtime.evaluate(FEATURE, 3, now=110.0)
    assert len(dispatcher.requests) == 1

    runtime.update_camera_snapshot(FEATURE, snapshot(10, 1, now=111.0), frame)
    assert runtime.evaluate(FEATURE, 3, now=111.0).reason == "normal"
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=112.0), frame)
    runtime.evaluate(FEATURE, 3, now=112.0)

    assert len(dispatcher.requests) == 2
    assert dispatcher.reset_calls == []


# 功能：验证 `test_alarm_interval_remains_effective_after_recovery` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`sys.modules.get`、`hasattr`、`sys.modules.pop`、`AlarmDispatcher`、`monkeypatch.setattr`、`dispatched.append`、`build_runtime`、`channel`、`np.full`、`runtime.update_camera_snapshot`
#          等共 13 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_alarm_interval_remains_effective_after_recovery(monkeypatch):
    from AiVision.core.alarm.dispatcher import AlarmDispatcher

    dispatcher = AlarmDispatcher()
    dispatched = []
    dispatcher_time = {"now": 100.0}
    monkeypatch.setattr("AiVision.core.alarm.dispatcher.time.time", lambda: dispatcher_time["now"])
    monkeypatch.setattr(dispatcher, "_execute", lambda request: dispatched.append(request))
    runtime, _ = build_runtime(
        [channel(member_ids=(10,))],
        dispatcher=dispatcher,
    )
    frame = np.full((12, 16, 3), 20, np.uint8)

    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=100.0), frame)
    runtime.evaluate(FEATURE, 3, now=100.0)
    assert len(dispatched) == 1

    runtime.update_camera_snapshot(FEATURE, snapshot(10, 1, now=111.0), frame)
    assert runtime.evaluate(FEATURE, 3, now=111.0).reason == "normal"

    dispatcher_time["now"] = 112.0
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=112.0), frame)
    runtime.evaluate(FEATURE, 3, now=112.0)
    assert len(dispatched) == 1

    dispatcher_time["now"] = 113.0
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=113.0), frame)
    runtime.evaluate(FEATURE, 3, now=113.0)
    assert len(dispatched) == 2


# 功能：验证 `test_cooldown_rejection_does_not_permanently_latch_new_incident` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_runtime`、`channel`、`iter`、`runtime.update_camera_snapshot`、`snapshot`、`runtime.evaluate`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_cooldown_rejection_does_not_permanently_latch_new_incident():
    runtime, dispatcher = build_runtime([channel(member_ids=(10,))])
    accepted = iter((False, True))

    # 功能：发送或分发 `maybe_dispatch` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `request`（未显式标注）：当前 HTTP 请求及上下文
    #   - `alarm_interval`（未显式标注）：`alarm_interval` 对应的时间间隔或时长；默认值为 `5.0`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`dispatcher.requests.append`、`next`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    def maybe_dispatch(request, alarm_interval=5.0):
        dispatcher.requests.append((request, alarm_interval))
        return next(accepted)

    dispatcher.maybe_dispatch = maybe_dispatch
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)

    runtime.evaluate(FEATURE, 3, now=100.0)
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=101.0), None)
    runtime.evaluate(FEATURE, 3, now=101.0)
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=102.0), None)
    runtime.evaluate(FEATURE, 3, now=102.0)

    assert len(dispatcher.requests) == 2


# 功能：验证 `test_dispatch_request_uses_channel_subject_mosaic_and_complete_metadata` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_runtime`、`channel`、`runtime.update_camera_snapshot`、`snapshot`、`np.full`、`runtime.evaluate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_dispatch_request_uses_channel_subject_mosaic_and_complete_metadata():
    runtime, dispatcher = build_runtime([channel()])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), np.full((10, 20, 3), 10, np.uint8))
    runtime.update_camera_snapshot(FEATURE, snapshot(11, 1), np.full((10, 20, 3), 30, np.uint8))

    runtime.evaluate(FEATURE, 3, now=101.0)

    request, interval = dispatcher.requests[0]
    assert request.subject_type == "logistics_channel"
    assert request.subject_id == "3"
    assert request.subject_name == "物流通道-3"
    assert request.department == "general_electric"
    assert request.camera_name == "物流通道-3"
    assert request.reason == "multiple"
    assert request.frame.shape == (360, 1280, 3)
    assert interval == 13.0
    assert request.metadata["channel_id"] == 3
    assert request.metadata["channel_name"] == "物流通道-3"
    assert request.metadata["camera_ids"] == [10, 11]
    assert request.metadata["camera_counts"] == {"10": 2, "11": 1}
    assert request.metadata["camera_states"]["10"]["status"] == "multiple"
    assert request.metadata["offending_camera_ids"] == [10]
    assert request.metadata["alarm_started_at"] == 101.0
    assert request.metadata["triggered_at"] == 101.0
    assert request.alarm_config["sql"] == {"enable": True, "parm": {}}


# 功能：验证 `test_runtime_forwards_disabled_sql_channel_to_dispatcher` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`channel`、`build_runtime`、`runtime.update_camera_snapshot`、`snapshot`、`runtime.evaluate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_runtime_forwards_disabled_sql_channel_to_dispatcher():
    item = channel(member_ids=(10,))
    item["config"]["alarm"]["sql_enable"] = False
    runtime, dispatcher = build_runtime([item])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)

    runtime.evaluate(FEATURE, 3, now=100.0)

    assert dispatcher.requests[0][0].alarm_config["sql"] == {
        "enable": False,
        "parm": {},
    }


# 功能：验证 `test_all_members_must_be_fresh_online_and_zero_for_empty_alarm` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_runtime`、`channel`、`runtime.update_camera_snapshot`、`snapshot`、`runtime.evaluate`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_all_members_must_be_fresh_online_and_zero_for_empty_alarm():
    active = {"camera_10": True, "camera_11": False}
    runtime, dispatcher = build_runtime([channel()], active=lambda key: active[key])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 0), None)
    runtime.update_camera_snapshot(FEATURE, snapshot(11, 0), None)

    assert runtime.evaluate(FEATURE, 3, now=100.0).reason == "unknown"
    assert dispatcher.requests == []

    active["camera_11"] = True
    decision = runtime.evaluate(FEATURE, 3, now=100.1)
    assert decision.reason == "empty"
    assert len(dispatcher.requests) == 1


# 功能：验证 `test_schedule_and_feature_namespaces_are_isolated` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`channel`、`time`、`build_runtime`、`datetime(2026, 8, 7, 10, 0,
#          tzinfo=timezone.utc).astimezone`、`datetime`、`runtime.camera_should_run`、`runtime.evaluate`、`runtime.update_camera_snapshot`、`snapshot`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_schedule_and_department_channels_are_isolated():
    outside = channel(channel_id=3, start=time(11, 0), end=time(12, 0))
    other = channel(channel_id=4, department="electronics_electrician", member_ids=(12,))
    runtime, dispatcher = build_runtime(
        [outside, other],
        wall_time=lambda: datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc).astimezone(),
    )

    assert runtime.camera_should_run(FEATURE, 10) is False
    assert runtime.evaluate(FEATURE, 3, now=100.0).reason == "inactive"

    runtime.update_camera_snapshot(FEATURE, snapshot(12, 2), None)
    assert runtime.evaluate(FEATURE, 4, now=100.0).reason == "multiple"
    assert len(dispatcher.requests) == 1
    assert dispatcher.requests[0][0].feature_name == FEATURE
    assert dispatcher.requests[0][0].department == "electronics_electrician"
    assert runtime.get_channel_status(FEATURE, 4)["department"] == "electronics_electrician"


# 功能：验证 `test_refresh_clears_timing_snapshot_and_incident_state` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`channel`、`build_runtime`、`runtime.update_camera_snapshot`、`snapshot`、`runtime.evaluate`、`runtime.refresh_channel`、`runtime.get_channel_status`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_refresh_clears_timing_snapshot_and_incident_state():
    item = channel(member_ids=(10,), multi_grace=5.0)
    runtime, dispatcher = build_runtime([item])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)
    assert runtime.evaluate(FEATURE, 3, now=100.0).alarm is False
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=106.0), None)
    assert runtime.evaluate(FEATURE, 3, now=106.0).alarm is True

    runtime.refresh_channel(FEATURE, 3)

    assert runtime.get_channel_status(FEATURE, 3) is None
    assert runtime.evaluate(FEATURE, 3, now=107.0).reason == "unknown"
    assert len(dispatcher.requests) == 1


# 功能：验证 `test_concurrent_camera_updates_produce_consistent_channel_snapshot` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_runtime`、`channel`、`Thread`、`snapshot`、`thread.start`、`thread.join`、`runtime.evaluate`、`runtime.get_channel_status`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_concurrent_camera_updates_produce_consistent_channel_snapshot():
    runtime, _dispatcher = build_runtime([channel()])

    threads = [
        Thread(target=runtime.update_camera_snapshot, args=(FEATURE, snapshot(camera_id, count), None))
        for camera_id, count in ((10, 1), (11, 1))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    decision = runtime.evaluate(FEATURE, 3, now=100.0)
    status = runtime.get_channel_status(FEATURE, 3)
    assert decision.reason == "normal"
    assert status["camera_counts"] == {"10": 1, "11": 1}


# 功能：验证 `test_channel_status_returns_defensive_copies_of_nested_collections` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_runtime`、`channel`、`runtime.update_camera_snapshot`、`snapshot`、`runtime.evaluate`、`runtime.get_channel_status`、`external['camera_ids'].append`、`external['offending_camera_ids'].clear`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_channel_status_returns_defensive_copies_of_nested_collections():
    runtime, _dispatcher = build_runtime([channel()])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)
    runtime.update_camera_snapshot(FEATURE, snapshot(11, 0), None)
    runtime.evaluate(FEATURE, 3, now=100.0)

    external = runtime.get_channel_status(FEATURE, 3)
    external["camera_ids"].append(99)
    external["offending_camera_ids"].clear()
    external["camera_counts"]["10"] = 0
    external["camera_states"]["10"]["camera_name"] = "外部篡改"

    internal = runtime.get_channel_status(FEATURE, 3)
    assert internal["camera_ids"] == [10, 11]
    assert internal["offending_camera_ids"] == [10]
    assert internal["camera_counts"]["10"] == 2
    assert internal["camera_states"]["10"]["camera_name"] == "摄像头-10"


# 功能：验证 `test_invalid_count_is_unknown_in_decision_and_display` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `invalid_count`（未显式标注）：`invalid_count` 对应的数量或大小
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_runtime`、`channel`、`runtime.update_camera_snapshot`、`snapshot`、`runtime.evaluate`、`runtime.get_channel_status`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("invalid_count", [True, -1, 1.5])
def test_invalid_count_is_unknown_in_decision_and_display(invalid_count):
    runtime, dispatcher = build_runtime([channel(member_ids=(10,))])
    runtime.update_camera_snapshot(FEATURE, snapshot(10, invalid_count), None)

    decision = runtime.evaluate(FEATURE, 3, now=100.0)
    status = runtime.get_channel_status(FEATURE, 3)

    assert decision.reason == "unknown"
    assert status["camera_counts"] == {"10": None}
    assert status["camera_states"]["10"]["status"] == "unknown"
    assert status["camera_states"]["10"]["stale_reason"] == "invalid_count"
    assert dispatcher.requests == []


# 功能：验证 `test_compositor_runs_only_for_alarm_or_explicit_frame_request` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_runtime`、`channel`、`runtime.update_camera_snapshot`、`snapshot`、`runtime.evaluate`、`runtime.get_composite_frame`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_compositor_runs_only_for_alarm_or_explicit_frame_request():
    calls = []

    # 功能：实现 `compositor` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `tiles`（未显式标注）：`tiles` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`calls.append`、`tuple`、`np.zeros`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def compositor(tiles):
        calls.append(tuple(tile.camera_id for tile in tiles))
        return np.zeros((20, 30, 3), np.uint8)

    runtime, dispatcher = build_runtime(
        [channel(member_ids=(10,))],
        compositor=compositor,
    )
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 1), None)

    assert runtime.evaluate(FEATURE, 3, now=100.0).reason == "normal"
    assert calls == []
    assert runtime.get_composite_frame(FEATURE, 3).shape == (20, 30, 3)
    assert calls == [(10,)]

    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=101.0), None)
    assert runtime.evaluate(FEATURE, 3, now=101.0).reason == "multiple"
    assert calls == [(10,), (10,)]
    assert len(dispatcher.requests) == 1


# 功能：验证 `test_service_camera_online_compositor_and_dispatcher_run_outside_global_lock` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`channel`、`GuardedDispatcher`、`LogisticsChannelRuntime`、`GuardedService`、`assert_unlocked`、`np.zeros`、`datetime`、`runtime.start`、`runtime.update_camera_snapshot`、`snapshot`
#          等共 12 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_service_camera_online_compositor_and_dispatcher_run_outside_global_lock():
    from AiVision.platform.logistics_channel.runtime import LogisticsChannelRuntime

    holder = {}
    item = channel(member_ids=(10,))

    # 功能：实现 `assert_unlocked` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_service_camera_online_compositor_and_dispatcher_run_outside_global_lock::GuardedService::list_channels`
    #         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_service_camera_online_compositor_and_dispatcher_run_outside_global_lock::GuardedService::get_channel`
    #         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_service_camera_online_compositor_and_dispatcher_run_outside_global_lock::GuardedDispatcher::maybe_dispatch`
    #         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_service_camera_online_compositor_and_dispatcher_run_outside_global_lock` 调用本符号
    #   - 内部调用：`holder.get`、`runtime._lock._is_owned`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def assert_unlocked():
        runtime = holder.get("runtime")
        if runtime is not None:
            assert runtime._lock._is_owned() is False

    # 功能：定义 `GuardedService` 类，封装运行时相关的状态、约束与操作
    # 参数：无。
    # 返回：GuardedService；返回新建的 `GuardedService` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_service_camera_online_compositor_and_dispatcher_run_outside_global_lock` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class GuardedService(FakeChannelService):
        # 功能：读取或查询 `list_channels` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`assert_unlocked`、`super().list_channels`、`super`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def list_channels(self, feature_name):
            assert_unlocked()
            return super().list_channels(feature_name)

        # 功能：读取或查询 `get_channel` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
        #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`assert_unlocked`、`super().get_channel`、`super`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def get_channel(self, feature_name, channel_id):
            assert_unlocked()
            return super().get_channel(feature_name, channel_id)

    # 功能：定义 `GuardedDispatcher` 类，封装运行时相关的状态、约束与操作
    # 参数：无。
    # 返回：GuardedDispatcher；返回新建的 `GuardedDispatcher` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_service_camera_online_compositor_and_dispatcher_run_outside_global_lock` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class GuardedDispatcher(FakeDispatcher):
        # 功能：发送或分发 `maybe_dispatch` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `request`（未显式标注）：当前 HTTP 请求及上下文
        #   - `alarm_interval`（未显式标注）：`alarm_interval` 对应的时间间隔或时长；默认值为 `5.0`
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`assert_unlocked`、`super().maybe_dispatch`、`super`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def maybe_dispatch(self, request, alarm_interval=5.0):
            assert_unlocked()
            return super().maybe_dispatch(request, alarm_interval)

    dispatcher = GuardedDispatcher()
    runtime = LogisticsChannelRuntime(
        channel_service=GuardedService([item]),
        dispatcher=dispatcher,
        camera_provider=lambda camera_id: (
            assert_unlocked()
            or {"id": camera_id, "name": "摄像头-10", "shm_name": "camera_10"}
        ),
        is_camera_active=lambda _key: assert_unlocked() or True,
        compositor=lambda _tiles: assert_unlocked() or np.zeros((10, 10, 3), np.uint8),
        stale_seconds=5.0,
        wall_time_provider=lambda: datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc),
        violation_type_provider=lambda _feature: assert_unlocked() or 6,
        start_background=False,
    )
    holder["runtime"] = runtime
    runtime.start()
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)

    assert runtime.evaluate(FEATURE, 3, now=100.0).alarm is True
    assert len(dispatcher.requests) == 1


# 功能：验证 `test_refresh_during_slow_composition_discards_stale_incident_result` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Event`、`channel`、`FakeChannelService`、`build_runtime`、`runtime.update_camera_snapshot`、`snapshot`、`Thread`、`worker.start`、`entered.wait`、`runtime.refresh_channel`
#          等共 14 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_refresh_during_slow_composition_discards_stale_incident_result():
    entered = Event()
    release = Event()

    # 功能：实现 `slow_compositor` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `_tiles`（未显式标注）：`_tiles` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`entered.set`、`release.wait`、`np.zeros`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def slow_compositor(_tiles):
        entered.set()
        assert release.wait(1.0)
        return np.zeros((10, 10, 3), np.uint8)

    item = channel(member_ids=(10,))
    service = FakeChannelService([item])
    runtime, dispatcher = build_runtime(
        [item],
        channel_service=service,
        compositor=slow_compositor,
    )
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)
    worker = Thread(target=runtime.evaluate, args=(FEATURE, 3), kwargs={"now": 100.0})
    worker.start()
    assert entered.wait(1.0)

    item["name"] = "重命名后的通道"
    runtime.refresh_channel(FEATURE, 3)
    release.set()
    worker.join(1.0)

    assert worker.is_alive() is False
    assert dispatcher.requests == []
    assert runtime.get_channel_status(FEATURE, 3) is None


# 功能：验证 `test_camera_rename_and_delete_refresh_real_runtime_membership_cache` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`channel`、`FakeChannelService`、`build_runtime`、`runtime.update_camera_snapshot`、`snapshot`、`runtime.evaluate`、`runtime.refresh_camera_all`、`cameras.pop`、`runtime.get_channel_status`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_rename_and_delete_refresh_real_runtime_membership_cache():
    item = channel(member_ids=(10, 11))
    service = FakeChannelService([item])
    cameras = {
        10: {"id": 10, "name": "旧名称", "shm_name": "camera_10"},
        11: {"id": 11, "name": "待删除", "shm_name": "camera_11"},
    }
    runtime, dispatcher = build_runtime(
        [item],
        channel_service=service,
        cameras=cameras,
    )
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)
    runtime.update_camera_snapshot(FEATURE, snapshot(11, 0), None)
    runtime.evaluate(FEATURE, 3, now=100.0)
    assert dispatcher.requests[0][0].metadata["camera_states"]["10"]["camera_name"] == "旧名称"

    cameras[10]["name"] = "新名称"
    runtime.refresh_camera_all(10)
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2, now=101.0), None)
    runtime.update_camera_snapshot(FEATURE, snapshot(11, 0, now=101.0), None)
    runtime.evaluate(FEATURE, 3, now=101.0)
    assert dispatcher.requests[-1][0].metadata["camera_states"]["10"]["camera_name"] == "新名称"

    item["members"] = [member for member in item["members"] if member["camera_id"] != 11]
    cameras.pop(11)
    runtime.refresh_camera_all(11)
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 0, now=102.0), None)
    decision = runtime.evaluate(FEATURE, 3, now=102.0)
    status = runtime.get_channel_status(FEATURE, 3)

    assert decision.reason == "empty"
    assert status["camera_ids"] == [10]
    assert status["camera_counts"] == {"10": 0}


# 功能：验证 `test_stop_timeout_keeps_thread_reference_and_prevents_double_start` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Event`、`BlockingDispatcher`、`channel`、`build_runtime`、`runtime.update_camera_snapshot`、`snapshot`、`entered.wait`、`pytest.raises`、`runtime.stop`、`original_thread.is_alive`
#          等共 13 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_stop_timeout_keeps_thread_reference_and_prevents_double_start():
    entered = Event()
    release = Event()

    # 功能：定义 `BlockingDispatcher` 类，封装运行时相关的状态、约束与操作
    # 参数：无。
    # 返回：BlockingDispatcher；返回新建的 `BlockingDispatcher` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_stop_timeout_keeps_thread_reference_and_prevents_double_start` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class BlockingDispatcher(FakeDispatcher):
        # 功能：发送或分发 `maybe_dispatch` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `request`（未显式标注）：当前 HTTP 请求及上下文
        #   - `alarm_interval`（未显式标注）：`alarm_interval` 对应的时间间隔或时长；默认值为 `5.0`
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`entered.set`、`release.wait`、`super().maybe_dispatch`、`super`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def maybe_dispatch(self, request, alarm_interval=5.0):
            entered.set()
            assert release.wait(2.0)
            return super().maybe_dispatch(request, alarm_interval)

    dispatcher = BlockingDispatcher()
    item = channel(member_ids=(10,))
    runtime, _ = build_runtime(
        [item],
        dispatcher=dispatcher,
        start_background=True,
        clock=lambda: 100.0,
        stop_timeout=0.01,
    )
    runtime.update_camera_snapshot(FEATURE, snapshot(10, 2), None)
    assert entered.wait(1.5)
    original_thread = runtime._thread

    with pytest.raises(RuntimeError, match="停止超时"):
        runtime.stop()
    assert runtime._thread is original_thread
    assert original_thread.is_alive()
    with pytest.raises(RuntimeError, match="禁止重复启动"):
        runtime.start()

    release.set()
    original_thread.join(1.0)
    assert original_thread.is_alive() is False
    runtime.stop()
    runtime.start()
    assert runtime._thread is not original_thread
    runtime.stop()
