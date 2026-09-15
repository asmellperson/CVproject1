# 文件说明：包含摄像头、视频帧的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import importlib
from types import SimpleNamespace


orchestrator_module = importlib.import_module("AiVision.runtime.orchestrator")
Orchestrator = orchestrator_module.Orchestrator


# 功能：实现 `_orchestrator` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `raw`（未显式标注）：`raw` 对应的业务输入值
#   - `raw_updated_at`（未显式标注）：`raw_updated_at` 对应的业务输入值
#   - `annotated`（未显式标注）：`annotated` 对应的业务输入值
#   - `annotated_updated_at`（未显式标注）：`annotated_updated_at` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_orchestrator_camera_frame.py` 的 `test_missing_raw_frame_does_not_return_expired_annotated_frame`
#         调用本符号；`AiVision/tests/test_orchestrator_camera_frame.py` 的 `test_fresh_annotated_frame_is_preferred`
#         调用本符号；`AiVision/tests/test_orchestrator_camera_frame.py` 的 `test_expired_annotated_frame_does_not_expose_raw_in_monitor`
#         调用本符号；`AiVision/tests/test_orchestrator_camera_frame.py` 的 `test_all_expired_frames_return_latest_known_timestamp` 调用本符号
#   - 内部调用：`object.__new__`、`SimpleNamespace`、`monkeypatch.setattr`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _orchestrator(
    monkeypatch,
    *,
    raw,
    raw_updated_at,
    annotated,
    annotated_updated_at,
):
    instance = object.__new__(Orchestrator)
    instance.consumers = {
        "detect_logistics_single_person": SimpleNamespace(
            result_dict={"logistics": annotated} if annotated is not None else {},
            result_updated_at={"logistics": annotated_updated_at} if annotated is not None else {},
        )
    }
    monkeypatch.setattr(
        orchestrator_module.frame_reader_registry,
        "latest_frames",
        {"logistics": raw} if raw is not None else {},
    )
    monkeypatch.setattr(
        orchestrator_module.frame_reader_registry,
        "latest_frame_times",
        {"logistics": raw_updated_at} if raw_updated_at else {},
    )
    return instance


# 功能：验证 `test_missing_raw_frame_does_not_return_expired_annotated_frame` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`object`、`_orchestrator`、`instance.get_camera_frame_info`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_missing_raw_frame_does_not_return_expired_annotated_frame(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    annotated = object()
    instance = _orchestrator(
        monkeypatch,
        raw=None,
        raw_updated_at=0.0,
        annotated=annotated,
        annotated_updated_at=90.0,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (None, 90.0)


# 功能：验证 `test_fresh_annotated_frame_is_preferred` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`object`、`_orchestrator`、`instance.get_camera_frame_info`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_fresh_annotated_frame_is_preferred(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    raw, annotated = object(), object()
    instance = _orchestrator(
        monkeypatch,
        raw=raw,
        raw_updated_at=99.0,
        annotated=annotated,
        annotated_updated_at=99.5,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (annotated, 99.5)


# 功能：验证 `test_expired_annotated_frame_does_not_expose_raw_in_monitor` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`object`、`_orchestrator`、`instance.get_camera_frame_info`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_expired_annotated_frame_does_not_expose_raw_in_monitor(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    raw, annotated = object(), object()
    instance = _orchestrator(
        monkeypatch,
        raw=raw,
        raw_updated_at=99.0,
        annotated=annotated,
        annotated_updated_at=90.0,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (None, 99.0)
    assert instance.get_camera_frame_info("logistics") == (raw, 99.0)


# 功能：验证 `test_all_expired_frames_return_latest_known_timestamp` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`_orchestrator`、`object`、`instance.get_camera_frame_info`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_all_expired_frames_return_latest_known_timestamp(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    instance = _orchestrator(
        monkeypatch,
        raw=object(),
        raw_updated_at=80.0,
        annotated=object(),
        annotated_updated_at=90.0,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (None, 90.0)
