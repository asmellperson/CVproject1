# 文件说明：包含后台任务的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import inspect
import io
import json
import subprocess
import unittest

import numpy as np

from AiVision.integrations.security_vlm.src import capture_worker


# 功能：定义 `FragmentedStream` 类，封装后台任务相关的状态、约束与操作
# 参数：
#   - `chunks`（未显式标注）：`chunks` 对应的业务输入值
# 返回：FragmentedStream；返回新建的 `FragmentedStream` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_capture_worker_ffmpeg.py` 的
#         `ExactReadTests::test_read_exact_joins_fragmented_pipe_reads`
#         实例化本符号；`AiVision/integrations/security_vlm/tests/test_capture_worker_ffmpeg.py` 的
#         `ExactReadTests::test_read_exact_returns_none_for_incomplete_frame`
#         实例化本符号；`AiVision/integrations/security_vlm/tests/test_capture_worker_ffmpeg.py` 的
#         `RtspCaptureLifecycleTests::test_capture_uses_ffmpeg_and_reads_a_complete_bgr_frame`
#         实例化本符号；`AiVision/integrations/security_vlm/tests/test_capture_worker_ffmpeg.py` 的
#         `RtspCaptureLifecycleTests::test_incomplete_frame_restarts_ffmpeg_before_publishing` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FragmentedStream:
    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `chunks`（未显式标注）：`chunks` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`list`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, chunks):
        self.chunks = list(chunks)

    # 功能：读取或查询 `read` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `size`（未显式标注）：`size` 对应的数量或大小
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.chunks.pop`、`len`、`self.chunks.insert`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def read(self, size):
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if len(chunk) <= size:
            return chunk
        self.chunks.insert(0, chunk[size:])
        return chunk[:size]


# 功能：定义 `StopAfterReadStream` 类，封装后台任务相关的状态、约束与操作
# 参数：
#   - `chunks`（未显式标注）：`chunks` 对应的业务输入值
#   - `on_complete`（未显式标注）：`on_complete` 对应的业务输入值
# 返回：StopAfterReadStream；返回新建的 `StopAfterReadStream` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_capture_worker_ffmpeg.py` 的
#         `RtspCaptureLifecycleTests::test_incomplete_frame_restarts_ffmpeg_before_publishing` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class StopAfterReadStream(FragmentedStream):
    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `chunks`（未显式标注）：`chunks` 对应的业务输入值
    #   - `on_complete`（未显式标注）：`on_complete` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().__init__`、`super`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, chunks, on_complete):
        super().__init__(chunks)
        self.on_complete = on_complete

    # 功能：读取或查询 `read` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `size`（未显式标注）：`size` 对应的数量或大小
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().read`、`super`、`self.on_complete`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def read(self, size):
        chunk = super().read(size)
        if chunk and not self.chunks:
            self.on_complete()
        return chunk


# 功能：定义 `FfmpegCommandTests` 类，封装后台任务相关的状态、约束与操作
# 参数：无。
# 返回：FfmpegCommandTests；返回新建的 `FfmpegCommandTests` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FfmpegCommandTests(unittest.TestCase):
    # 功能：验证 `test_build_ffmpeg_command_uses_tcp_rawvideo_and_target_fps` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.assertTrue`、`hasattr`、`capture_worker.build_ffmpeg_command`、`self.assertIn`、`self.assertNotIn`、`self.assertEqual`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def test_build_ffmpeg_command_uses_tcp_rawvideo_and_target_fps(self):
        self.assertTrue(
            hasattr(capture_worker, "build_ffmpeg_command"),
            "capture_worker.build_ffmpeg_command is required",
        )

        command = capture_worker.build_ffmpeg_command("rtsp://camera/stream", 10)

        self.assertIn("-rtsp_transport", command)
        self.assertIn("tcp", command)
        self.assertNotIn("-rw_timeout", command)
        self.assertIn("fps=10", command)
        self.assertIn("bgr24", command)
        self.assertEqual(command[-2:], ["rawvideo", "pipe:1"])

    # 功能：验证 `test_build_ffmpeg_command_keeps_local_file_support` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`capture_worker.build_ffmpeg_command`、`self.assertNotIn`、`self.assertIn`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def test_build_ffmpeg_command_keeps_local_file_support(self):
        command = capture_worker.build_ffmpeg_command("video.mp4", 8)

        self.assertNotIn("-rtsp_transport", command)
        self.assertNotIn("-rw_timeout", command)
        self.assertIn("video.mp4", command)
        self.assertIn("fps=8", command)


# 功能：定义 `ExactReadTests` 类，封装后台任务相关的状态、约束与操作
# 参数：无。
# 返回：ExactReadTests；返回新建的 `ExactReadTests` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ExactReadTests(unittest.TestCase):
    # 功能：验证 `test_read_exact_joins_fragmented_pipe_reads` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.assertTrue`、`hasattr`、`FragmentedStream`、`self.assertEqual`、`capture_worker.read_exact`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def test_read_exact_joins_fragmented_pipe_reads(self):
        self.assertTrue(
            hasattr(capture_worker, "read_exact"),
            "capture_worker.read_exact is required",
        )
        stream = FragmentedStream([b"ab", b"c", b"def"])

        self.assertEqual(capture_worker.read_exact(stream, 6), b"abcdef")

    # 功能：验证 `test_read_exact_returns_none_for_incomplete_frame` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.assertTrue`、`hasattr`、`FragmentedStream`、`self.assertIsNone`、`capture_worker.read_exact`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def test_read_exact_returns_none_for_incomplete_frame(self):
        self.assertTrue(
            hasattr(capture_worker, "read_exact"),
            "capture_worker.read_exact is required",
        )
        stream = FragmentedStream([b"ab", b""])

        self.assertIsNone(capture_worker.read_exact(stream, 4))

    # 功能：验证 `test_read_exact_returns_none_when_pipe_closes_during_shutdown` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.assertIsNone`、`capture_worker.read_exact`、`ClosedPipe`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def test_read_exact_returns_none_when_pipe_closes_during_shutdown(self):
        # 功能：定义 `ClosedPipe` 类，封装后台任务相关的状态、约束与操作
        # 参数：无。
        # 返回：ClosedPipe；返回新建的 `ClosedPipe` 实例。
        # 调用关系：
        #   - 调用方：`AiVision/integrations/security_vlm/tests/test_capture_worker_ffmpeg.py` 的
        #         `ExactReadTests::test_read_exact_returns_none_when_pipe_closes_during_shutdown` 实例化本符号
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        class ClosedPipe:
            # 功能：读取或查询 `read` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
            # 参数：
            #   - `self`（未显式标注）：当前类实例
            #   - `_size`（未显式标注）：`_size` 对应的数量或大小
            # 返回：None；仅执行处理流程，不返回业务数据。
            # 调用关系：
            #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
            #   - 内部调用：`ValueError`。
            # 副作用/注意事项：校验或执行失败时会主动抛出异常。
            def read(self, _size):
                raise ValueError("read of closed file")

        self.assertIsNone(capture_worker.read_exact(ClosedPipe(), 4))


# 功能：定义 `ProbeTests` 类，封装后台任务相关的状态、约束与操作
# 参数：无。
# 返回：ProbeTests；返回新建的 `ProbeTests` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ProbeTests(unittest.TestCase):
    # 功能：验证 `test_probe_video_shape_parses_dimensions_and_uses_rtsp_tcp` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.assertTrue`、`hasattr`、`capture_worker.probe_video_shape`、`self.assertEqual`、`self.assertIn`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def test_probe_video_shape_parses_dimensions_and_uses_rtsp_tcp(self):
        self.assertTrue(
            hasattr(capture_worker, "probe_video_shape"),
            "capture_worker.probe_video_shape is required",
        )
        calls = []

        # 功能：实现 `runner` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `command`（未显式标注）：`command` 对应的业务输入值
        #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`calls.append`、`type('Result', (), {'stdout': json.dumps({'streams': [{'width': 2560, 'height':
        #          1440}]})})`、`type`、`json.dumps`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return type("Result", (), {
                "stdout": json.dumps({"streams": [{"width": 2560, "height": 1440}]}),
            })()

        shape = capture_worker.probe_video_shape(
            "rtsp://camera/stream",
            runner=runner,
        )

        self.assertEqual(shape, (1440, 2560, 3))
        self.assertIn("-rtsp_transport", calls[0][0])
        self.assertIn("tcp", calls[0][0])
        self.assertEqual(calls[0][1]["timeout"], 10)
        self.assertTrue(calls[0][1]["check"])

    # 功能：验证 `test_probe_video_shape_rejects_invalid_dimensions` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.assertTrue`、`hasattr`、`self.assertRaisesRegex`、`capture_worker.probe_video_shape`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def test_probe_video_shape_rejects_invalid_dimensions(self):
        self.assertTrue(
            hasattr(capture_worker, "probe_video_shape"),
            "capture_worker.probe_video_shape is required",
        )

        # 功能：实现 `runner` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `_command`（未显式标注）：`_command` 对应的业务输入值
        #   - `**_kwargs`（未显式标注）：`_kwargs` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`type('Result', (), {'stdout': json.dumps({'streams': [{'width': 0, 'height': 1440}]})})`、`type`、`json.dumps`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def runner(_command, **_kwargs):
            return type("Result", (), {
                "stdout": json.dumps({"streams": [{"width": 0, "height": 1440}]}),
            })()

        with self.assertRaisesRegex(RuntimeError, "有效分辨率"):
            capture_worker.probe_video_shape("video.mp4", runner=runner)

    # 功能：验证 `test_probe_failure_does_not_expose_rtsp_credentials` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.assertRaises`、`capture_worker.probe_video_shape`、`self.assertNotIn`、`str`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def test_probe_failure_does_not_expose_rtsp_credentials(self):
        secret_url = "rtsp://admin:super-secret@camera/stream"

        # 功能：实现 `runner` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `command`（未显式标注）：`command` 对应的业务输入值
        #   - `**_kwargs`（未显式标注）：`_kwargs` 对应的业务输入值
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`subprocess.CalledProcessError`。
        # 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
        def runner(command, **_kwargs):
            raise subprocess.CalledProcessError(1, command)

        with self.assertRaises(RuntimeError) as raised:
            capture_worker.probe_video_shape(secret_url, runner=runner)

        self.assertNotIn("super-secret", str(raised.exception))


# 功能：定义 `FakeProcess` 类，封装后台任务相关的状态、约束与操作
# 参数：
#   - `stdout`（未显式标注）：`stdout` 对应的业务输入值
# 返回：FakeProcess；返回新建的 `FakeProcess` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeProcess:
    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `stdout`（未显式标注）：`stdout` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`io.BytesIO`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, stdout):
        self.stdout = stdout
        self.stderr = io.BytesIO()
        self.returncode = None
        self.terminated = False
        self.killed = False

    # 功能：实现 `poll` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def poll(self):
        return self.returncode

    # 功能：实现 `terminate` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def terminate(self):
        self.terminated = True
        self.returncode = 0

    # 功能：实现 `kill` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def kill(self):
        self.killed = True
        self.returncode = -9

    # 功能：实现 `wait` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `timeout`（未显式标注）：允许操作等待的最长秒数；默认值为 `None`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def wait(self, timeout=None):
        del timeout
        return self.returncode


# 功能：定义 `RtspCaptureLifecycleTests` 类，封装后台任务相关的状态、约束与操作
# 参数：无。
# 返回：RtspCaptureLifecycleTests；返回新建的 `RtspCaptureLifecycleTests` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class RtspCaptureLifecycleTests(unittest.TestCase):
    # 功能：验证 `test_capture_uses_ffmpeg_and_reads_a_complete_bgr_frame` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`inspect.signature`、`self.assertIn`、`bytes`、`range`、`FakeProcess`、`FragmentedStream`、`capture_worker.RtspCapture`、`self.assertTrue`、`capture._open`、`capture._read_one_frame`
    #          等共 15 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
    def test_capture_uses_ffmpeg_and_reads_a_complete_bgr_frame(self):
        parameters = inspect.signature(capture_worker.RtspCapture).parameters
        self.assertIn("target_fps", parameters)
        self.assertIn("process_factory", parameters)
        self.assertIn("probe_runner", parameters)

        expected = bytes(range(18))
        process = FakeProcess(FragmentedStream([expected[:5], expected[5:11], expected[11:]]))
        popen_calls = []

        # 功能：处理 `process_factory` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `command`（未显式标注）：`command` 对应的业务输入值
        #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`popen_calls.append`。
        # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
        def process_factory(command, **kwargs):
            popen_calls.append((command, kwargs))
            return process

        # 功能：实现 `probe_runner` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `_command`（未显式标注）：`_command` 对应的业务输入值
        #   - `**_kwargs`（未显式标注）：`_kwargs` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`type('Result', (), {'stdout': json.dumps({'streams': [{'width': 3, 'height': 2}]})})`、`type`、`json.dumps`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def probe_runner(_command, **_kwargs):
            return type("Result", (), {
                "stdout": json.dumps({"streams": [{"width": 3, "height": 2}]}),
            })()

        capture = capture_worker.RtspCapture(
            "rtsp://camera/stream",
            target_fps=10,
            process_factory=process_factory,
            probe_runner=probe_runner,
        )

        self.assertTrue(capture._open())
        frame = capture._read_one_frame()

        self.assertEqual(frame.shape, (2, 3, 3))
        self.assertEqual(frame.dtype, np.uint8)
        np.testing.assert_array_equal(frame.reshape(-1), np.arange(18, dtype=np.uint8))
        self.assertIn("ffmpeg", popen_calls[0][0][0])
        self.assertIs(popen_calls[0][1]["stdout"], capture_worker.subprocess.PIPE)
        self.assertIs(popen_calls[0][1]["stderr"], capture_worker.subprocess.PIPE)

    # 功能：验证 `test_close_process_terminates_running_ffmpeg` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`inspect.signature`、`self.assertIn`、`FakeProcess`、`io.BytesIO`、`capture_worker.RtspCapture`、`type('Result', (),
    #          {'stdout': json.dumps({'streams': [{'width': 3, 'height':
    #          2}]})})`、`type`、`json.dumps`、`capture._close_process`、`self.assertTrue` 等共 11 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def test_close_process_terminates_running_ffmpeg(self):
        parameters = inspect.signature(capture_worker.RtspCapture).parameters
        self.assertIn("process_factory", parameters)
        process = FakeProcess(io.BytesIO())

        capture = capture_worker.RtspCapture(
            "video.mp4",
            process_factory=lambda *_args, **_kwargs: process,
            probe_runner=lambda *_args, **_kwargs: type("Result", (), {
                "stdout": json.dumps({"streams": [{"width": 3, "height": 2}]}),
            })(),
        )
        capture.process = process

        capture._close_process()

        self.assertTrue(process.terminated)
        self.assertIsNone(capture.process)

    # 功能：验证 `test_incomplete_frame_restarts_ffmpeg_before_publishing` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`FakeProcess`、`FragmentedStream`、`StopAfterReadStream`、`bytes`、`range`、`capture_worker.RtspCapture`、`type('Result',
    #          (), {'stdout': json.dumps({'streams': [{'width': 3, 'height': 2}]})})`、`type`、`json.dumps`、`capture._loop` 等共 16 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def test_incomplete_frame_restarts_ffmpeg_before_publishing(self):
        processes = []
        sleep_calls = []
        capture = None

        first_process = FakeProcess(FragmentedStream([b"incomplete", b""]))

        # 功能：停止并释放 `stop_capture` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def stop_capture():
            capture.stop_flag = True

        second_process = FakeProcess(
            StopAfterReadStream([bytes(range(18))], stop_capture),
        )
        available_processes = [first_process, second_process]

        # 功能：处理 `process_factory` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `_command`（未显式标注）：`_command` 对应的业务输入值
        #   - `**_kwargs`（未显式标注）：`_kwargs` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`available_processes.pop`、`processes.append`。
        # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
        def process_factory(_command, **_kwargs):
            process = available_processes.pop(0)
            processes.append(process)
            return process

        capture = capture_worker.RtspCapture(
            "rtsp://camera/stream",
            target_fps=10,
            process_factory=process_factory,
            probe_runner=lambda *_args, **_kwargs: type("Result", (), {
                "stdout": json.dumps({"streams": [{"width": 3, "height": 2}]}),
            })(),
            sleep_fn=sleep_calls.append,
        )

        capture._loop()

        self.assertEqual(len(processes), 2)
        self.assertTrue(first_process.terminated)
        self.assertEqual(sleep_calls, [1.0])
        self.assertEqual(capture.frame_id, 1)
        np.testing.assert_array_equal(
            capture.frame.reshape(-1),
            np.arange(18, dtype=np.uint8),
        )


if __name__ == "__main__":
    unittest.main()
