"""录像结束通过真实写入器回写对应告警；SQLite、帧和视频均在临时目录。"""
from pathlib import Path
import threading

import numpy as np
import pytest

from AiVision.alarms.evidence import evidence_recorder
from AiVision.alarms.records.orm import AiAlarmEvent
from AiVision.core.video_encoding import VideoEncodingError
from test_violation_writer import writer_db  # noqa: F401


@pytest.mark.parametrize("encode_failure,expected_status", [(False, "ready"), (True, "failed")])
def test_recorder_updates_only_its_record_and_releases_workers(writer_db, monkeypatch, encode_failure, expected_status):  # noqa: F811 - pytest 注入复用夹具
    writer, factory, _ = writer_db
    frame = np.full((24, 32, 3), 100, dtype=np.uint8)
    encoder_entered = threading.Event()
    release_encoder = threading.Event()
    released = []

    class FakeVideoWriter:
        def __init__(self, path, *_args):
            self.path = path
            self.frames = []
            encoder_entered.set()
            assert release_encoder.wait(5), "test did not release encoder"

        def isOpened(self):
            return True

        def write(self, value):
            self.frames.append(value.copy())

        def release(self):
            Path(self.path).write_bytes(b"simulated-video")
            released.append(self)

    def convert(path):
        if encode_failure:
            raise VideoEncodingError("simulated encoding failure")
        return path

    monkeypatch.setattr(evidence_recorder.cv2, "VideoWriter", FakeVideoWriter)
    monkeypatch.setattr(evidence_recorder, "ensure_browser_compatible_mp4", convert)
    recorder = evidence_recorder.AlarmEvidenceRecorder(writer._data_path, enabled=True, post_seconds=0)
    recorder.set_status_callback(writer.update_video_status)
    common = dict(frame=frame, violation_type=5, camera_no="test-camera", feature_name="detect_human",
                  department="haoda_company", video_status="pending")
    unrelated = writer.save_now(video_path=str(writer._data_path / "unrelated.mp4"), **common)
    assert unrelated is not None
    try:
        video_path = recorder.start_alarm("test-camera", frame, timestamp=1000.)
        assert video_path is not None and encoder_entered.wait(5)
        record = writer.save_now(video_path=video_path, **common)
        assert record is not None
    finally:
        release_encoder.set()
        recorder.stop()
    with factory() as session:
        assert session.get(AiAlarmEvent, record.id).video_status == expected_status
        assert session.get(AiAlarmEvent, unrelated.id).video_status == "pending"
        assert session.query(AiAlarmEvent).count() == 2
    assert len(released) == 1 and released[0].frames
    assert recorder._writer_threads == [] and recorder._sampler_thread is None
    assert recorder._tasks == [] and recorder._write_queue.unfinished_tasks == 0
    assert recorder.start_alarm("test-camera", frame) is None
