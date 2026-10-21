"""安检在低帧率、检测顺序变化和轨迹过期时的会话回归验证。"""

import numpy as np
import pytest

from AiVision.features.security_inspection.schema import InspectionValue
from AiVision.features.security_inspection.sessions import PairSessionManager


def person_pair(offset, reverse=False):
    tracks = [
        {"track_id": 1, "x1": 60.0 + offset, "y1": 40.0, "x2": 100.0 + offset, "y2": 160.0},
        {"track_id": 2, "x1": 160.0 + offset, "y1": 40.0, "x2": 200.0 + offset, "y2": 160.0},
    ]
    return tracks[::-1] if reverse else tracks


def draw_people(frame, tracks):
    frame.fill(0)
    for track in tracks:
        color = (20, 40, 200) if track["track_id"] == 1 else (200, 80, 20)
        frame[int(track["y1"]):int(track["y2"]), int(track["x1"]):int(track["x2"])] = color


@pytest.mark.parametrize("interval", [0.1, 0.5, 1.1, 5.0])
@pytest.mark.parametrize("alternate_order", [False, True])
def test_moving_pair_completes_session_at_different_processing_rates(interval, alternate_order):
    config = InspectionValue()
    manager = PairSessionManager(config)
    frame = np.zeros((240, 4096, 3), dtype=np.uint8)
    rois = {"station": [[0.0, 0.0], [4096.0, 0.0], [4096.0, 240.0], [0.0, 240.0]]}

    # 相同的真实运动速度分别按正常和拥堵轮询采样，保持默认配对及采样门槛。
    for index in range(40):
        now = 1000.0 + index * interval
        tracks = person_pair(index * interval * 16.0, reverse=alternate_order and index % 2 == 1)
        draw_people(frame, tracks)
        manager.step(frame, tracks, rois, now)
        session = manager.roi_states["station"].active
        if session is not None and len(session.keyframes) >= 2:
            break

    assert session is not None, "持续交互不能因轮询变慢或检测排序变化而始终无法启动"
    assert len(session.keyframes) >= 2
    completed = manager.step(frame, [], rois, now + config.fingerprint_lost_seconds + 0.1)
    assert len(completed) == 1
    assert completed[0] is session
    assert completed[0].end_ts > completed[0].start_ts


@pytest.mark.parametrize("speed", [0.0, 2.0])
def test_sparse_samples_do_not_turn_stationary_or_slow_people_into_interaction(speed):
    manager = PairSessionManager(InspectionValue(pair_start_hold_frames=1))
    frame = np.zeros((240, 2048, 3), dtype=np.uint8)
    rois = {"station": [[0.0, 0.0], [2048.0, 0.0], [2048.0, 240.0], [0.0, 240.0]]}
    for index in range(12):
        tracks = person_pair(index * 5.0 * speed)
        draw_people(frame, tracks)
        assert manager.step(frame, tracks, rois, 1000.0 + index * 5.0) == []
        assert manager.roi_states["station"].active is None


@pytest.mark.parametrize("interval", [5.1, 10.0])
def test_expired_track_history_cannot_start_a_pair(interval):
    manager = PairSessionManager(InspectionValue(pair_start_hold_frames=1))
    frame = np.zeros((240, 1024, 3), dtype=np.uint8)
    rois = {"station": [[0.0, 0.0], [1024.0, 0.0], [1024.0, 240.0], [0.0, 240.0]]}
    for now, offset in [(1000.0, 0.0), (1000.0 + interval, interval * 16.0)]:
        tracks = person_pair(offset)
        draw_people(frame, tracks)
        assert manager.step(frame, tracks, rois, now) == []
        assert manager.roi_states["station"].active is None
