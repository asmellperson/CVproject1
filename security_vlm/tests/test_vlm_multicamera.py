import pickle
import queue
from pathlib import Path

import numpy as np
import pytest

import session_worker
import vlm_worker


def test_session_framehub_wait_timeout_covers_slow_rtsp_startup():
    assert session_worker.framehub_wait_timeout({}) == 30.0
    assert session_worker.framehub_wait_timeout({
        "runtime": {"framehub_wait_timeout_sec": 45},
    }) == 45.0


def test_finalized_session_contains_camera_identity(tmp_path):
    cfg = {
        "data": {
            "department": "electronics_electrician",
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
    assert payload["department"] == "electronics_electrician"
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


def test_pending_payload_without_department_defaults_to_general_electric():
    assert vlm_worker.payload_department({}) == "general_electric"
    assert (
        vlm_worker.payload_department({"department": "electrical_components"})
        == "electrical_components"
    )


def test_scanner_discovers_new_department_and_legacy_pending_paths(tmp_path):
    runtime_root = tmp_path / "runtime"
    legacy_task = runtime_root / "cameras" / "legacy-camera" / "pending" / "old.pkl"
    general_task = (
        runtime_root
        / "departments"
        / "general_electric"
        / "cameras"
        / "shared-camera"
        / "pending"
        / "general.pkl"
    )
    electronics_task = (
        runtime_root
        / "departments"
        / "electronics_electrician"
        / "cameras"
        / "shared-camera"
        / "pending"
        / "electronics.pkl"
    )
    for task in (legacy_task, general_task, electronics_task):
        _write_pending(task)
    task_q = queue.Queue()
    scanner = vlm_worker.MultiCameraPendingScanner(runtime_root, task_q)

    scanner.scan_once()

    queued = [task_q.get_nowait() for _ in range(3)]
    assert {path.name.rsplit("__", 1)[-1] for path in queued} == {
        "old.pkl",
        "general.pkl",
        "electronics.pkl",
    }
    general_claim = next(path for path in queued if path.name.endswith("general.pkl"))
    electronics_claim = next(
        path for path in queued if path.name.endswith("electronics.pkl")
    )
    legacy_claim = next(path for path in queued if path.name.endswith("old.pkl"))
    assert general_claim.parent == (
        runtime_root / "departments" / "general_electric" / "global" / "processing"
    )
    assert electronics_claim.parent == (
        runtime_root
        / "departments"
        / "electronics_electrician"
        / "global"
        / "processing"
    )
    assert legacy_claim.parent == runtime_root / "global" / "processing"


def test_department_processing_collision_stays_in_department(tmp_path):
    runtime_root = tmp_path / "runtime"
    pending_task = (
        runtime_root
        / "departments"
        / "general_electric"
        / "cameras"
        / "shared-camera"
        / "pending"
        / "same.pkl"
    )
    processing_dir = (
        runtime_root
        / "departments"
        / "general_electric"
        / "global"
        / "processing"
    )
    existing_task = processing_dir / "shared-camera__same.pkl"
    _write_pending(pending_task)
    _write_pending(existing_task)
    task_q = queue.Queue()
    scanner = vlm_worker.MultiCameraPendingScanner(runtime_root, task_q)

    scanner.scan_once()

    queued = [task_q.get_nowait() for _ in range(2)]
    assert all(path.parent == processing_dir for path in queued)
    assert list((runtime_root / "global" / "processing").glob("*.pkl")) == []


def test_scanner_does_not_claim_unknown_department_pending(tmp_path):
    runtime_root = tmp_path / "runtime"
    unknown_task = (
        runtime_root
        / "departments"
        / "unknown_department"
        / "cameras"
        / "camera-a"
        / "pending"
        / "task.pkl"
    )
    _write_pending(unknown_task)
    task_q = queue.Queue()
    scanner = vlm_worker.MultiCameraPendingScanner(runtime_root, task_q)

    scanner.scan_once()

    assert task_q.empty()
    assert unknown_task.exists()


def test_department_pending_requires_explicit_matching_payload_department(tmp_path):
    processing_dir = (
        tmp_path
        / "runtime"
        / "departments"
        / "general_electric"
        / "global"
        / "processing"
    )
    task = processing_dir / "camera-a__task.pkl"

    with pytest.raises(ValueError, match="缺少 department"):
        vlm_worker.validate_pending_payload_department({}, task)
    with pytest.raises(ValueError, match="不一致"):
        vlm_worker.validate_pending_payload_department(
            {"department": "electronics_electrician"},
            task,
        )
    assert (
        vlm_worker.validate_pending_payload_department(
            {"department": "general_electric"},
            task,
        )
        == "general_electric"
    )


def test_legacy_processing_without_department_defaults_to_general_electric(tmp_path):
    task = (
        tmp_path
        / "runtime"
        / "global"
        / "processing"
        / "legacy-camera__task.pkl"
    )

    assert vlm_worker.validate_pending_payload_department({}, task) == (
        "general_electric"
    )
    single_queue_task = tmp_path / "runtime" / "session_pending" / "task.pkl"
    assert vlm_worker.validate_pending_payload_department(
        {},
        single_queue_task,
    ) == "general_electric"


def test_same_named_tasks_in_two_departments_do_not_collide(tmp_path):
    runtime_root = tmp_path / "runtime"
    departments = ("general_electric", "electronics_electrician")
    for department in departments:
        task = (
            runtime_root
            / "departments"
            / department
            / "cameras"
            / "shared-camera"
            / "pending"
            / "same.pkl"
        )
        task.parent.mkdir(parents=True, exist_ok=True)
        task.write_bytes(
            pickle.dumps({
                "department": department,
                "enqueue_ts": 100.0,
            })
        )
    task_q = queue.Queue()
    scanner = vlm_worker.MultiCameraPendingScanner(runtime_root, task_q)

    scanner.scan_once()

    queued = [task_q.get_nowait() for _ in range(2)]
    assert {path.parents[2].name for path in queued} == set(departments)
    assert {
        vlm_worker.validate_pending_payload_department(
            pickle.loads(path.read_bytes()),
            path,
        )
        for path in queued
    } == set(departments)
