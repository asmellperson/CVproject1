from pathlib import Path
import inspect
import io
import json
import subprocess
import sys
import unittest

import numpy as np

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

import capture_worker


class FragmentedStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read(self, size):
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if len(chunk) <= size:
            return chunk
        self.chunks.insert(0, chunk[size:])
        return chunk[:size]


class StopAfterReadStream(FragmentedStream):
    def __init__(self, chunks, on_complete):
        super().__init__(chunks)
        self.on_complete = on_complete

    def read(self, size):
        chunk = super().read(size)
        if chunk and not self.chunks:
            self.on_complete()
        return chunk


class FfmpegCommandTests(unittest.TestCase):
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

    def test_build_ffmpeg_command_keeps_local_file_support(self):
        command = capture_worker.build_ffmpeg_command("video.mp4", 8)

        self.assertNotIn("-rtsp_transport", command)
        self.assertNotIn("-rw_timeout", command)
        self.assertIn("video.mp4", command)
        self.assertIn("fps=8", command)


class ExactReadTests(unittest.TestCase):
    def test_read_exact_joins_fragmented_pipe_reads(self):
        self.assertTrue(
            hasattr(capture_worker, "read_exact"),
            "capture_worker.read_exact is required",
        )
        stream = FragmentedStream([b"ab", b"c", b"def"])

        self.assertEqual(capture_worker.read_exact(stream, 6), b"abcdef")

    def test_read_exact_returns_none_for_incomplete_frame(self):
        self.assertTrue(
            hasattr(capture_worker, "read_exact"),
            "capture_worker.read_exact is required",
        )
        stream = FragmentedStream([b"ab", b""])

        self.assertIsNone(capture_worker.read_exact(stream, 4))

    def test_read_exact_returns_none_when_pipe_closes_during_shutdown(self):
        class ClosedPipe:
            def read(self, _size):
                raise ValueError("read of closed file")

        self.assertIsNone(capture_worker.read_exact(ClosedPipe(), 4))


class ProbeTests(unittest.TestCase):
    def test_probe_video_shape_parses_dimensions_and_uses_rtsp_tcp(self):
        self.assertTrue(
            hasattr(capture_worker, "probe_video_shape"),
            "capture_worker.probe_video_shape is required",
        )
        calls = []

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

    def test_probe_video_shape_rejects_invalid_dimensions(self):
        self.assertTrue(
            hasattr(capture_worker, "probe_video_shape"),
            "capture_worker.probe_video_shape is required",
        )

        def runner(_command, **_kwargs):
            return type("Result", (), {
                "stdout": json.dumps({"streams": [{"width": 0, "height": 1440}]}),
            })()

        with self.assertRaisesRegex(RuntimeError, "有效分辨率"):
            capture_worker.probe_video_shape("video.mp4", runner=runner)

    def test_probe_failure_does_not_expose_rtsp_credentials(self):
        secret_url = "rtsp://admin:super-secret@camera/stream"

        def runner(command, **_kwargs):
            raise subprocess.CalledProcessError(1, command)

        with self.assertRaises(RuntimeError) as raised:
            capture_worker.probe_video_shape(secret_url, runner=runner)

        self.assertNotIn("super-secret", str(raised.exception))


class FakeProcess:
    def __init__(self, stdout):
        self.stdout = stdout
        self.stderr = io.BytesIO()
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        del timeout
        return self.returncode


class RtspCaptureLifecycleTests(unittest.TestCase):
    def test_capture_uses_ffmpeg_and_reads_a_complete_bgr_frame(self):
        parameters = inspect.signature(capture_worker.RtspCapture).parameters
        self.assertIn("target_fps", parameters)
        self.assertIn("process_factory", parameters)
        self.assertIn("probe_runner", parameters)

        expected = bytes(range(18))
        process = FakeProcess(FragmentedStream([expected[:5], expected[5:11], expected[11:]]))
        popen_calls = []

        def process_factory(command, **kwargs):
            popen_calls.append((command, kwargs))
            return process

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

    def test_incomplete_frame_restarts_ffmpeg_before_publishing(self):
        processes = []
        sleep_calls = []
        capture = None

        first_process = FakeProcess(FragmentedStream([b"incomplete", b""]))

        def stop_capture():
            capture.stop_flag = True

        second_process = FakeProcess(
            StopAfterReadStream([bytes(range(18))], stop_capture),
        )
        available_processes = [first_process, second_process]

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
