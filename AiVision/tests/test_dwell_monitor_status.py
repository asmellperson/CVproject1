# 文件说明：包含监控展示的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from AiVision.features._shared.dwell_consumer import build_dwell_monitor_snapshot
from AiVision.features._shared.tracking import Track


# 功能：定义 `FakeTracker` 类，封装监控展示相关的状态、约束与操作
# 参数：
#   - `tracks`（未显式标注）：`tracks` 对应的业务输入值
# 返回：FakeTracker；返回新建的 `FakeTracker` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_dwell_monitor_status.py` 的 `test_dwell_snapshot_counts_visible_tracks_and_longest_duration`
#         实例化本符号；`AiVision/tests/test_dwell_monitor_status.py` 的 `test_dwell_snapshot_is_normal_when_roi_has_no_visible_tracks`
#         实例化本符号；`AiVision/tests/test_dwell_monitor_status.py` 的 `test_dwell_snapshot_ignores_other_cameras` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeTracker:
    # 功能：初始化或配置 `__init__` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `tracks`（未显式标注）：`tracks` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, tracks):
        self.tracks = tracks


# 功能：验证 `test_dwell_snapshot_counts_visible_tracks_and_longest_duration` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`FakeTracker`、`SimpleNamespace`、`build_dwell_monitor_snapshot`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_dwell_snapshot_counts_visible_tracks_and_longest_duration():
    trackers = {
        7: FakeTracker({
            1: Track(bbox=[0, 0, 10, 20], last_seen=110.0, first_seen=100.0, lost=0, alarmed=False),
            2: Track(bbox=[0, 0, 10, 20], last_seen=110.0, first_seen=90.0, lost=0, alarmed=True),
            3: Track(bbox=[0, 0, 10, 20], last_seen=110.0, first_seen=80.0, lost=1, alarmed=True),
        }),
        8: FakeTracker({
            4: Track(bbox=[0, 0, 10, 20], last_seen=110.0, first_seen=70.0, lost=0, alarmed=True),
        }),
    }

    snapshot = build_dwell_monitor_snapshot(
        trackers,
        camera_id=7,
        threshold_seconds=15.0,
        updated_at=109.5,
    )

    assert snapshot == {
        "count": 2,
        "alarm": True,
        "reason": "loitering",
        "duration_seconds": 20.0,
        "threshold_seconds": 15.0,
        "updated_at_s": 109.5,
    }


# 功能：验证 `test_dwell_snapshot_is_normal_when_roi_has_no_visible_tracks` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_dwell_monitor_snapshot`、`FakeTracker`、`SimpleNamespace`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_dwell_snapshot_is_normal_when_roi_has_no_visible_tracks():
    snapshot = build_dwell_monitor_snapshot(
        {7: FakeTracker({1: Track(bbox=[0, 0, 10, 20], last_seen=110.0, first_seen=90.0, lost=2, alarmed=True)})},
        camera_id=7,
        threshold_seconds=30.0,
        updated_at=110.0,
    )

    assert snapshot["count"] == 0
    assert snapshot["duration_seconds"] == 0.0
    assert snapshot["threshold_seconds"] == 30.0
    assert snapshot["alarm"] is False
    assert snapshot["reason"] == "normal"


# 功能：验证 `test_dwell_snapshot_ignores_other_cameras` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`build_dwell_monitor_snapshot`、`FakeTracker`、`SimpleNamespace`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_dwell_snapshot_ignores_other_cameras():
    snapshot = build_dwell_monitor_snapshot(
        {
            7: FakeTracker({1: Track(bbox=[0, 0, 10, 20], last_seen=110.0, first_seen=105.0, lost=0, alarmed=False)}),
            8: FakeTracker({2: Track(bbox=[0, 0, 10, 20], last_seen=110.0, first_seen=80.0, lost=0, alarmed=True)}),
        },
        camera_id=7,
        threshold_seconds=10.0,
        updated_at=110.0,
    )

    assert snapshot["count"] == 1
    assert snapshot["duration_seconds"] == 5.0
    assert snapshot["alarm"] is False
