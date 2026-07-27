import pickle
import queue
from pathlib import Path

import numpy as np

import session_worker
import vlm_worker


def test_finalized_session_contains_camera_identity(tmp_path):
    cfg = {
        "data": {
            "video_id": "camera-a",
            "camera_name": "安检工位一号",
        },
        "session": {},
    }
    manager = session_worker.PairSessionManager(cfg, tmp_path)
    session = session_worker.PairSession(
        session_id="session-1",
        roi_name="security_staff_1",
        roi_box=[0, 0, 100, 100],
        init_track_a=1,
        init_track_b=2,
        fp_a={},
        fp_b={},
        last_box_a=[0, 0, 10, 10],
        last_box_b=[10, 10, 20, 20],
        start_ts=10.0,
        end_ts=20.0,
        keyframes=[
            np.zeros((4, 4, 3), dtype=np.uint8),
            np.zeros((4, 4, 3), dtype=np.uint8),
        ],
    )

    manager._finalize(session)

    payload = pickle.loads((tmp_path / "session-1.pkl").read_bytes())
    assert payload["camera_id"] == "camera-a"
    assert payload["camera_name"] == "安检工位一号"
    assert list(tmp_path.glob("*.tmp")) == []


def _write_pending(path: Path, enqueue_ts: float = 100.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps({"enqueue_ts": enqueue_ts}))


def test_multicamera_scanner_round_robins_and_deduplicates_full_paths(tmp_path):
    camera_root = tmp_path / "cameras"
    _write_pending(camera_root / "camera-a" / "pending" / "same.pkl")
    _write_pending(camera_root / "camera-a" / "pending" / "second.pkl")
    _write_pending(camera_root / "camera-b" / "pending" / "same.pkl")
    _write_pending(camera_root / "camera-b" / "pending" / "second.pkl")
    task_q = queue.Queue()
    processing_dir = tmp_path / "global" / "processing"
    scanner = vlm_worker.MultiCameraPendingScanner(
        camera_root,
        task_q,
        processing_dir=processing_dir,
    )

    scanner.scan_once()
    scanner.scan_once()

    queued = [task_q.get_nowait() for _ in range(4)]
    assert [path.name.split("__", 1)[0] for path in queued] == [
        "camera-a",
        "camera-b",
        "camera-b",
        "camera-a",
    ]
    assert len({str(path) for path in queued}) == 4
    assert all(path.parent == processing_dir for path in queued)
    assert list(camera_root.glob("*/pending/*.pkl")) == []


def test_cleanup_keeps_valid_preexisting_tasks_and_removes_only_expired(tmp_path):
    pending = tmp_path / "pending"
    valid = pending / "valid.pkl"
    expired = pending / "expired.pkl"
    _write_pending(valid, enqueue_ts=95.0)
    _write_pending(expired, enqueue_ts=10.0)

    removed = vlm_worker.cleanup_stale_pending(
        pending,
        now_ts=100.0,
        queue_timeout=60.0,
    )

    assert removed == 1
    assert valid.exists()
    assert not expired.exists()


def test_legacy_pending_tasks_are_moved_into_global_processing(tmp_path):
    legacy_pending = tmp_path / "session_pending"
    processing = tmp_path / "global" / "processing"
    task = legacy_pending / "legacy-session.pkl"
    _write_pending(task)

    moved = vlm_worker.migrate_legacy_pending(legacy_pending, processing)

    assert moved == 1
    assert not task.exists()
    assert (processing / "legacy-default__legacy-session.pkl").exists()


def test_preexisting_processing_tasks_are_marked_for_crash_recovery(tmp_path):
    processing = tmp_path / "global" / "processing"
    task = processing / "camera-a__session.pkl"
    _write_pending(task, enqueue_ts=1.0)

    marked = vlm_worker.mark_recovered_processing(processing)

    assert marked == 1
    assert (processing / "camera-a__session.pkl.recovered").exists()
