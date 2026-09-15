# 文件说明：包含运行时的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import os
import threading

import numpy as np


from AiVision.integrations.guard_room.src.runtime import LatestFrameBuffer, RTSPReader, cv2


# 功能：验证 `test_rtsp_reader_opens_stream_with_ffmpeg_tcp_options` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.delenv`、`threading.Event`、`monkeypatch.setattr`、`RTSPReader`、`LatestFrameBuffer`、`reader.run`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_rtsp_reader_opens_stream_with_ffmpeg_tcp_options(monkeypatch):
    monkeypatch.delenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", raising=False)
    monkeypatch.delenv("OPENCV_FFMPEG_READ_ATTEMPTS", raising=False)

    calls = []
    stop_event = threading.Event()

    # 功能：定义 `FakeCapture` 类，封装运行时相关的状态、约束与操作
    # 参数：
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    # 返回：FakeCapture；返回新建的 `FakeCapture` 实例。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeCapture:
        # 功能：初始化或配置 `__init__` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `*args`（未显式标注）：`args` 对应的业务输入值
        # 返回：None；初始化当前实例，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`calls.append`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def __init__(self, *args):
            calls.append(args)

        # 功能：更新或保存 `set` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `*_args`（未显式标注）：`_args` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：`AiVision/integrations/guard_room/tests/test_runtime_rtsp_reader.py` 的
        #         `test_rtsp_reader_opens_stream_with_ffmpeg_tcp_options::FakeCapture::read`
        #         调用本符号；`AiVision/integrations/security_vlm/tests/test_camera_registry.py` 的
        #         `test_two_processes_share_capacity_without_lost_creates`
        #         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
        #         `test_migration_and_other_registry_create_do_not_overwrite_each_other::pause_registry_replace`
        #         调用本符号；`AiVision/integrations/security_vlm/tests/test_department_workspace.py` 的
        #         `test_migration_and_other_registry_create_do_not_overwrite_each_other` 调用本符号；另有 31 处静态调用
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def set(self, *_args):
            return True

        # 功能：检查或判断 `isOpened` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `RTSPReader::run`
        #         调用本符号；`AiVision/alarms/evidence/evidence_recorder.py` 的 `AlarmEvidenceRecorder::_finish_task`
        #         调用本符号；`unified_frontend/scripts/build-overview-mascot.py` 的 `read_video_metadata` 调用本符号
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def isOpened(self):
            return True

        # 功能：读取或查询 `get` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `_prop`（未显式标注）：`_prop` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def get(self, _prop):
            return 0

        # 功能：读取或查询 `read` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`stop_event.set`、`np.zeros`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def read(self):
            stop_event.set()
            return True, np.zeros((8, 8, 3), dtype=np.uint8)

        # 功能：停止并释放 `release` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", FakeCapture)

    reader = RTSPReader(
        camera_name="cam1",
        source="rtsp://camera/stream",
        frame_width=1920,
        frame_height=1080,
        reconnect_seconds=0,
        camera_buffer_size=1,
        buffer=LatestFrameBuffer(),
        stop_event=stop_event,
    )

    reader.run()

    assert calls == [("rtsp://camera/stream", cv2.CAP_FFMPEG)]
    ffmpeg_options = os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]
    assert "rtsp_transport;tcp" in ffmpeg_options
    assert "timeout;5000000" in ffmpeg_options
    assert os.environ["OPENCV_FFMPEG_READ_ATTEMPTS"] == "10000"
