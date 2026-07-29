import json
import pickle
import queue
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

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


def test_scanner_rejects_and_cleans_unknown_department_pending(tmp_path):
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
    assert not unknown_task.exists()


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


def _valid_department_payload(**overrides):
    payload = {
        "department": "general_electric",
        "session_id": "camera-a_123_1",
        "camera_id": "camera-a",
        "camera_name": "A",
        "roi_name": "roi-a",
        "roi_box": [0, 0, 10, 10],
        "start_ts": 100.0,
        "end_ts": 101.0,
        "enqueue_ts": 102.0,
        "keyframes": [],
    }
    payload.update(overrides)
    return payload


def _general_processing_task(tmp_path):
    return (
        tmp_path
        / "runtime"
        / "departments"
        / "general_electric"
        / "global"
        / "processing"
        / "camera-a__task.pkl"
    )


def test_pending_parser_rejects_missing_session_id(tmp_path):
    payload = _valid_department_payload()
    payload.pop("session_id")

    with pytest.raises(ValueError, match="session_id"):
        vlm_worker.normalize_pending_payload(
            payload,
            _general_processing_task(tmp_path),
        )


@pytest.mark.parametrize(
    "enqueue_ts",
    ["not-a-number", float("inf"), 10 ** 400],
)
def test_pending_parser_rejects_invalid_enqueue_timestamp(
    tmp_path,
    enqueue_ts,
):
    with pytest.raises(
        (TypeError, ValueError, OverflowError),
        match="enqueue_ts",
    ):
        vlm_worker.normalize_pending_payload(
            _valid_department_payload(enqueue_ts=enqueue_ts),
            _general_processing_task(tmp_path),
        )


def test_invalid_pending_load_cleans_task_and_markers_before_processing(
    tmp_path,
):
    task = _general_processing_task(tmp_path)
    task.parent.mkdir(parents=True, exist_ok=True)
    invalid_payload = _valid_department_payload()
    invalid_payload.pop("session_id")
    task.write_bytes(pickle.dumps(invalid_payload))
    started = task.with_suffix(f"{task.suffix}.started")
    recovered = task.with_suffix(f"{task.suffix}.recovered")
    started.touch()
    recovered.touch()
    results_dir = tmp_path / "results"
    judge_called = False

    payload = vlm_worker.load_validated_pending_task(task)
    if payload is not None:
        judge_called = True
        results_dir.mkdir()

    assert payload is None
    assert judge_called is False
    assert not results_dir.exists()
    assert not task.exists()
    assert not started.exists()
    assert not recovered.exists()


def _write_full_pending(path: Path, *, department: str, camera_id: str, **overrides):
    payload = _valid_department_payload(
        department=department,
        camera_id=camera_id,
        session_id=f"{camera_id}_123_1",
        **overrides,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(payload))
    return path


def test_department_scanner_is_fair_across_departments_and_cameras(tmp_path):
    departments_root = tmp_path / "custom" / "departments"
    for camera_id, task_names in {
        "ge-a": ("1.pkl", "2.pkl"),
        "ge-b": ("1.pkl", "2.pkl"),
    }.items():
        for task_name in task_names:
            _write_full_pending(
                departments_root
                / "general_electric"
                / "cameras"
                / camera_id
                / "pending"
                / task_name,
                department="general_electric",
                camera_id=camera_id,
            )
    _write_full_pending(
        departments_root
        / "electronics_electrician"
        / "cameras"
        / "ee-a"
        / "pending"
        / "1.pkl",
        department="electronics_electrician",
        camera_id="ee-a",
    )
    task_q = queue.Queue()
    scanner = vlm_worker.DepartmentPendingScanner(
        departments_root,
        task_q,
    )

    scanner.scan_once()
    first = task_q.get_nowait()
    second = task_q.get_nowait()
    scanner.scan_once()
    third = task_q.get_nowait()

    assert [first.department, second.department] == [
        "general_electric",
        "electronics_electrician",
    ]
    assert {first.camera_id, third.camera_id} == {"ge-a", "ge-b"}
    assert first.path.parent == (
        departments_root
        / first.department
        / "global"
        / "processing"
        / first.camera_id
    )


def test_department_scanner_uses_exact_root_and_does_not_scan_nested_decoy(tmp_path):
    departments_root = tmp_path / "custom" / "departments"
    valid = _write_full_pending(
        departments_root
        / "general_electric"
        / "cameras"
        / "camera-a"
        / "pending"
        / "valid.pkl",
        department="general_electric",
        camera_id="camera-a",
    )
    decoy = _write_full_pending(
        departments_root
        / "nested"
        / "departments"
        / "general_electric"
        / "cameras"
        / "camera-b"
        / "pending"
        / "decoy.pkl",
        department="general_electric",
        camera_id="camera-b",
    )
    task_q = queue.Queue()
    scanner = vlm_worker.DepartmentPendingScanner(departments_root, task_q)

    scanner.scan_once()

    claimed = task_q.get_nowait()
    assert claimed.camera_id == "camera-a"
    assert not valid.exists()
    assert decoy.exists()
    assert task_q.empty()


def test_recovered_processing_round_robins_cameras_within_department(tmp_path):
    departments_root = tmp_path / "departments"
    processing_root = (
        departments_root
        / "general_electric"
        / "global"
        / "processing"
    )
    for camera_id in ("camera-a", "camera-b"):
        for task_name in ("1.pkl", "2.pkl"):
            _write_full_pending(
                processing_root / camera_id / task_name,
                department="general_electric",
                camera_id=camera_id,
            )
    task_q = queue.Queue()
    scanner = vlm_worker.DepartmentPendingScanner(departments_root, task_q)

    scanner.scan_once()
    scanner.scan_once()

    assert [
        task_q.get_nowait().camera_id,
        task_q.get_nowait().camera_id,
    ] == ["camera-a", "camera-b"]


def test_worker_get_fairly_selects_late_department_after_general_backlog(
    tmp_path,
):
    departments_root = tmp_path / "departments"
    task_q = vlm_worker.DepartmentFairTaskQueue()
    scanner = vlm_worker.DepartmentPendingScanner(departments_root, task_q)
    for camera_id in ("camera-a", "camera-b", "camera-c"):
        _write_full_pending(
            departments_root
            / "general_electric"
            / "cameras"
            / camera_id
            / "pending"
            / "task.pkl",
            department="general_electric",
            camera_id=camera_id,
        )
    scanner.scan_once()
    scanner.scan_once()
    scanner.scan_once()
    assert vlm_worker.queued_department_counts(task_q)[
        "general_electric"
    ] == 3

    assert task_q.get().department == "general_electric"
    task_q.task_done()
    _write_full_pending(
        departments_root
        / "electronics_electrician"
        / "cameras"
        / "camera-ee"
        / "pending"
        / "task.pkl",
        department="electronics_electrician",
        camera_id="camera-ee",
    )
    scanner.scan_once()
    counts = vlm_worker.queued_department_counts(task_q)
    assert counts["general_electric"] == 2
    assert counts["electronics_electrician"] == 1

    selected = task_q.get()

    assert selected.department == "electronics_electrician"
    task_q.task_done()


def test_worker_get_fairly_selects_late_camera_after_camera_backlog(tmp_path):
    task_q = vlm_worker.DepartmentFairTaskQueue()
    for index in range(4):
        task_q.put(vlm_worker.PendingTask(
            "general_electric",
            "camera-a",
            tmp_path / f"camera-a-{index}.pkl",
        ))

    assert task_q.get().camera_id == "camera-a"
    task_q.task_done()
    task_q.put(vlm_worker.PendingTask(
        "general_electric",
        "camera-b",
        tmp_path / "camera-b.pkl",
    ))

    selected = task_q.get()

    assert selected.camera_id == "camera-b"
    task_q.task_done()


def test_scanner_unifies_recovered_and_pending_with_one_prefetch_per_camera(
    tmp_path,
):
    departments_root = tmp_path / "departments"
    processing_root = (
        departments_root
        / "general_electric"
        / "global"
        / "processing"
    )
    for task_name in ("1.pkl", "2.pkl", "3.pkl"):
        _write_full_pending(
            processing_root / "camera-a" / task_name,
            department="general_electric",
            camera_id="camera-a",
        )
    pending_b = _write_full_pending(
        departments_root
        / "general_electric"
        / "cameras"
        / "camera-b"
        / "pending"
        / "pending.pkl",
        department="general_electric",
        camera_id="camera-b",
    )
    task_q = vlm_worker.DepartmentFairTaskQueue()
    scanner = vlm_worker.DepartmentPendingScanner(departments_root, task_q)

    scanner.scan_once()
    scanner.scan_once()
    scanner.scan_once()

    assert task_q.qsize() == 2
    first = task_q.get()
    second = task_q.get()
    assert [first.camera_id, second.camera_id] == ["camera-a", "camera-b"]
    assert not pending_b.exists()
    task_q.task_done()
    task_q.task_done()


def test_new_processing_identity_requires_matching_department_and_camera(tmp_path):
    task = vlm_worker.PendingTask(
        "general_electric",
        "camera-a",
        tmp_path
        / "departments"
        / "general_electric"
        / "global"
        / "processing"
        / "camera-a"
        / "task.pkl",
    )

    with pytest.raises(ValueError, match="camera_id"):
        vlm_worker.normalize_pending_payload(
            _valid_department_payload(camera_id="camera-b"),
            task,
        )
    with pytest.raises(ValueError, match="department"):
        vlm_worker.normalize_pending_payload(
            _valid_department_payload(department="electronics_electrician"),
            task,
        )


def test_legacy_task_rejects_explicit_non_general_department(tmp_path):
    task = vlm_worker.PendingTask(
        "general_electric",
        "legacy-camera",
        tmp_path / "runtime" / "global" / "processing" / "legacy.pkl",
        legacy=True,
    )

    with pytest.raises(ValueError, match="旧版"):
        vlm_worker.normalize_pending_payload(
            _valid_department_payload(
                department="electronics_electrician",
                camera_id="legacy-camera",
            ),
            task,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("camera_id", "../camera"),
        ("session_id", "bad\x00session"),
        ("session_id", "s" * 193),
    ],
)
def test_invalid_task_identifiers_are_rejected_and_cleaned(
    tmp_path,
    field,
    value,
):
    task_path = (
        tmp_path
        / "departments"
        / "general_electric"
        / "global"
        / "processing"
        / "camera-a"
        / "task.pkl"
    )
    task = vlm_worker.PendingTask("general_electric", "camera-a", task_path)
    payload = _valid_department_payload(**{field: value})
    task_path.parent.mkdir(parents=True)
    task_path.write_bytes(pickle.dumps(payload))

    assert vlm_worker.load_validated_pending_task(task) is None
    assert not task_path.exists()


def test_department_results_accumulators_are_fully_isolated(tmp_path):
    stores = vlm_worker.DepartmentResultStores(tmp_path)
    accumulators = vlm_worker.DepartmentAccumulators(stores, max_history=10)
    today = datetime.now().strftime("%Y-%m-%d")

    accumulators.get("general_electric").record({
        "department": "general_electric",
        "camera_id": "shared-camera",
        "session_id": "shared-session",
        "time": today,
        "duration_sec": 1.0,
        "result": {"compliant": True},
    })
    accumulators.get("electronics_electrician").record({
        "department": "electronics_electrician",
        "camera_id": "shared-camera",
        "session_id": "shared-session",
        "time": today,
        "duration_sec": 1.0,
        "result": {"compliant": False, "reason": "x"},
    })

    general_history = stores.get("general_electric").read("vlm_history")["items"]
    electronics_history = stores.get(
        "electronics_electrician"
    ).read("vlm_history")["items"]
    assert {item["department"] for item in general_history} == {
        "general_electric"
    }
    assert {item["department"] for item in electronics_history} == {
        "electronics_electrician"
    }
    assert stores.get("general_electric").read("vlm_latest_stats")[
        "compliant"
    ] == 1
    assert stores.get("electronics_electrician").read("vlm_latest_stats")[
        "non_compliant"
    ] == 1
    assert stores.results_dir("general_electric") != stores.results_dir(
        "electronics_electrician"
    )
    assert stores.budget_store.runtime_dir == tmp_path / "_shared"


def test_worker_paths_resolve_relative_roots_from_project_and_keep_exact_root(
    tmp_path,
):
    project_root = tmp_path / "security_vlm"
    cfg = {
        "runtime": {
            "dir": "runtime",
            "camera_root": "runtime/legacy-cameras",
        },
        "departments": {
            "runtime_root": "runtime/custom/departments",
            "data_root": "data/custom/departments",
        },
    }

    paths = vlm_worker.VLMWorkerPaths.from_config(cfg, project_root)

    assert paths.runtime_dir == (project_root / "runtime").resolve()
    assert paths.departments_root == (
        project_root / "runtime" / "custom" / "departments"
    ).resolve()
    assert paths.legacy_camera_root == (
        project_root / "runtime" / "legacy-cameras"
    ).resolve()
    assert paths.data_root == (
        project_root / "data" / "custom" / "departments"
    ).resolve()


def test_real_claim_process_partition_clip_history_stats_and_cleanup(
    tmp_path,
    monkeypatch,
):
    departments_root = tmp_path / "runtime" / "departments"
    pending = _write_full_pending(
        departments_root
        / "electrical_components"
        / "cameras"
        / "camera-a"
        / "pending"
        / "task.pkl",
        department="electrical_components",
        camera_id="camera-a",
        keyframes=[np.zeros((4, 4, 3), dtype=np.uint8)] * 2,
    )
    task_q = queue.Queue()
    scanner = vlm_worker.DepartmentPendingScanner(departments_root, task_q)
    scanner.scan_once()
    task = task_q.get_nowait()
    stores = vlm_worker.DepartmentResultStores(tmp_path / "data")
    accumulators = vlm_worker.DepartmentAccumulators(stores, max_history=10)
    judge = SimpleNamespace(
        judge=lambda *_args, **_kwargs: {
            "compliant": False,
            "reason": "未执行安检",
        }
    )
    saved_clips = []
    monkeypatch.setattr(
        vlm_worker,
        "save_clip",
        lambda _frames, _result, session_id, out_dir: saved_clips.append(
            out_dir / f"{session_id}.jpg"
        ),
    )
    processor = vlm_worker.PendingTaskProcessor(
        stores=stores,
        accumulators=accumulators,
        judge=judge,
        queue_timeout=60,
        save_clip_only_non_compliant=True,
    )

    assert processor.process(task, now_ts=103.0) is True

    result_path = (
        stores.results_dir("electrical_components")
        / "camera-a"
        / "camera-a_123_1.json"
    )
    assert json.loads(result_path.read_text())["department"] == (
        "electrical_components"
    )
    assert saved_clips == [
        stores.results_dir("electrical_components")
        / "clips"
        / "camera-a"
        / "camera-a_123_1.jpg"
    ]
    assert stores.get("electrical_components").read("vlm_history")["items"]
    assert stores.get("electrical_components").read("vlm_latest_stats")[
        "non_compliant"
    ] == 1
    assert not pending.exists()
    assert not task.path.exists()


def test_completion_record_identity_mismatch_is_rejected_without_vlm_call(tmp_path):
    stores = vlm_worker.DepartmentResultStores(tmp_path / "data")
    accumulators = vlm_worker.DepartmentAccumulators(stores, max_history=10)
    task_path = (
        tmp_path
        / "runtime"
        / "departments"
        / "general_electric"
        / "global"
        / "processing"
        / "camera-a"
        / "task.pkl"
    )
    _write_full_pending(
        task_path,
        department="general_electric",
        camera_id="camera-a",
    )
    result_path = (
        stores.results_dir("general_electric")
        / "camera-a"
        / "camera-a_123_1.json"
    )
    result_path.parent.mkdir(parents=True)
    result_path.write_text(json.dumps({
        "department": "electronics_electrician",
        "camera_id": "camera-a",
        "session_id": "camera-a_123_1",
        "result": {"compliant": True},
    }))
    calls = []
    processor = vlm_worker.PendingTaskProcessor(
        stores=stores,
        accumulators=accumulators,
        judge=SimpleNamespace(judge=lambda *_a, **_k: calls.append(True)),
        queue_timeout=60,
    )

    assert processor.process(
        vlm_worker.PendingTask(
            "general_electric",
            "camera-a",
            task_path,
        ),
        now_ts=103.0,
    ) is False
    assert calls == []
    assert task_path.exists()
    assert result_path.exists()


def test_corrupt_completion_preserves_task_markers_and_result(tmp_path):
    stores = vlm_worker.DepartmentResultStores(tmp_path / "data")
    accumulators = vlm_worker.DepartmentAccumulators(stores, max_history=10)
    task_path = (
        tmp_path
        / "runtime"
        / "departments"
        / "general_electric"
        / "global"
        / "processing"
        / "camera-a"
        / "task.pkl"
    )
    _write_full_pending(
        task_path,
        department="general_electric",
        camera_id="camera-a",
    )
    started = task_path.with_suffix(".pkl.started")
    recovered = task_path.with_suffix(".pkl.recovered")
    started.touch()
    recovered.touch()
    result_path = (
        stores.results_dir("general_electric")
        / "camera-a"
        / "camera-a_123_1.json"
    )
    result_path.parent.mkdir(parents=True)
    result_path.write_text("{broken", encoding="utf-8")
    calls = []
    processor = vlm_worker.PendingTaskProcessor(
        stores=stores,
        accumulators=accumulators,
        judge=SimpleNamespace(judge=lambda *_a, **_k: calls.append(True)),
        queue_timeout=60,
    )

    assert processor.process(
        vlm_worker.PendingTask(
            "general_electric",
            "camera-a",
            task_path,
        ),
        now_ts=103.0,
    ) is False
    assert calls == []
    assert task_path.exists()
    assert started.exists()
    assert recovered.exists()
    assert result_path.read_text(encoding="utf-8") == "{broken"


@pytest.mark.parametrize("corrupt_payload", ["{broken", "[]"])
def test_corrupt_department_state_is_isolated_and_preserved(
    tmp_path,
    corrupt_payload,
):
    stores = vlm_worker.DepartmentResultStores(tmp_path / "data")
    corrupt_store = stores.get("general_electric")
    state_path = corrupt_store._path("vlm_state")
    state_path.write_text(corrupt_payload, encoding="utf-8")
    budget = {
        "date": "2026-07-29",
        "call_count": 3,
        "spent_yuan": 0.15,
    }

    accumulators = vlm_worker.DepartmentAccumulators(
        stores,
        max_history=10,
        budget_snapshot=lambda: dict(budget),
    )
    accumulators.write_all()

    assert state_path.read_text(encoding="utf-8") == corrupt_payload
    assert accumulators.get("general_electric").disabled is True
    assert corrupt_store.read("workspace_error")["department"] == (
        "general_electric"
    )

    good = accumulators.get("electronics_electrician")
    assert good.record({
        "department": "electronics_electrician",
        "camera_id": "camera-a",
        "session_id": "session-a",
        "result": {"compliant": True},
    })
    good_stats = stores.get("electronics_electrician").read(
        "vlm_latest_stats"
    )
    assert good_stats["compliant"] == 1
    assert good_stats["budget"] == budget

    task_path = (
        tmp_path
        / "runtime"
        / "departments"
        / "general_electric"
        / "global"
        / "processing"
        / "camera-a"
        / "task.pkl"
    )
    _write_full_pending(
        task_path,
        department="general_electric",
        camera_id="camera-a",
    )
    processor = vlm_worker.PendingTaskProcessor(
        stores=stores,
        accumulators=accumulators,
        judge=SimpleNamespace(
            judge=lambda *_a, **_k: {"compliant": True}
        ),
        queue_timeout=60,
    )
    with pytest.raises(vlm_worker.DepartmentWorkspaceStateError):
        processor.process(
            vlm_worker.PendingTask(
                "general_electric",
                "camera-a",
                task_path,
            ),
            now_ts=103.0,
        )
    assert task_path.exists()
