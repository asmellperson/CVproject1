import json
import multiprocessing
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

try:
    import camera_registry
except ModuleNotFoundError:
    camera_registry = None


def _process_create_cameras(registry_path, start_event, results, prefix):
    registry = camera_registry.CameraRegistry(registry_path)
    original_read = registry._read_unlocked

    def slow_read():
        payload = original_read()
        time.sleep(0.1)
        return payload

    registry._read_unlocked = slow_read
    start_event.wait()
    for index in range(3):
        try:
            registry.create(
                f"{prefix} {index}",
                f"rtsp://{prefix.lower()}-{index}/stream",
            )
        except ValueError:
            results.put("full")
        else:
            results.put("created")


def test_camera_registry_module_exists():
    assert camera_registry is not None, "camera_registry module is required"


@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_create_read_and_redact_camera(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "config" / "cameras.json")

    created = registry.create(
        "安检工位一号",
        "rtsp://admin:secret@172.16.0.10:554/streaming/channels/101",
    )

    assert created["camera_id"]
    assert registry.get(created["camera_id"])["name"] == "安检工位一号"
    public = registry.public(created)
    assert public["rtsp_url"] == "rtsp://***:***@172.16.0.10:554/streaming/channels/101"
    assert public["has_rtsp_url"] is True
    assert "secret" not in json.dumps(public, ensure_ascii=False)


@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_rejects_empty_duplicate_names_and_non_rtsp_urls(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "cameras.json")
    registry.create("Camera A", "rtsp://camera-a/stream")

    with pytest.raises(ValueError, match="名称"):
        registry.create("  ", "rtsp://camera-b/stream")
    with pytest.raises(ValueError, match="已存在"):
        registry.create("camera a", "rtsp://camera-b/stream")
    with pytest.raises(ValueError, match="RTSP"):
        registry.create("Camera B", "http://camera-b/stream")


@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_update_blank_url_preserves_secret_and_delete_returns_record(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "cameras.json")
    created = registry.create("Camera A", "rtsps://user:pass@camera-a/stream")

    updated = registry.update(
        created["camera_id"],
        name="Camera A East",
        rtsp_url="",
    )

    assert updated["name"] == "Camera A East"
    assert updated["rtsp_url"] == "rtsps://user:pass@camera-a/stream"
    assert registry.delete(created["camera_id"])["camera_id"] == created["camera_id"]
    assert registry.get(created["camera_id"]) is None


@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_concurrent_creates_keep_registry_json_valid(tmp_path):
    registry_path = tmp_path / "cameras.json"
    registry = camera_registry.CameraRegistry(registry_path)

    def create(index):
        return registry.create(f"Camera {index}", f"rtsp://camera-{index}/stream")

    with ThreadPoolExecutor(max_workers=8) as executor:
        created = list(executor.map(create, range(4)))

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["department"] == "general_electric"
    assert len(payload["cameras"]) == 4
    assert len({item["camera_id"] for item in created}) == 4
    assert registry_path.stat().st_mode & 0o777 == 0o600


def test_two_registry_instances_do_not_lose_concurrent_creates(tmp_path):
    registry_path = tmp_path / "cameras.json"
    registries = [
        camera_registry.CameraRegistry(registry_path),
        camera_registry.CameraRegistry(registry_path),
    ]
    for registry in registries:
        original_read = registry._read_unlocked

        def slow_read(original_read=original_read):
            payload = original_read()
            time.sleep(0.05)
            return payload

        registry._read_unlocked = slow_read

    def create_pair(item):
        registry, prefix = item
        return [
            registry.create(
                f"{prefix} {index}",
                f"rtsp://{prefix.lower()}-{index}/stream",
            )
            for index in range(2)
        ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                create_pair,
                zip(registries, ("InstanceA", "InstanceB")),
            )
        )

    assert sum(len(items) for items in results) == 4
    assert len(camera_registry.CameraRegistry(registry_path).list()) == 4


def test_two_processes_share_capacity_without_lost_creates(tmp_path):
    registry_path = tmp_path / "cameras.json"
    context = multiprocessing.get_context("fork")
    start_event = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_process_create_cameras,
            args=(registry_path, start_event, results, prefix),
        )
        for prefix in ("ProcessA", "ProcessB")
    ]
    for process in processes:
        process.start()
    start_event.set()
    outcomes = [results.get(timeout=5) for _index in range(6)]
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0

    assert outcomes.count("created") == 4
    assert outcomes.count("full") == 2
    assert len(camera_registry.CameraRegistry(registry_path).list()) == 4


def test_registry_rejects_more_than_four_cameras(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "cameras.json")
    for index in range(4):
        registry.create(f"Camera {index}", f"rtsp://camera-{index}/stream")

    with pytest.raises(ValueError, match="4"):
        registry.create("Camera 5", "rtsp://camera-5/stream")


def test_registry_persists_department_and_rejects_mismatch(tmp_path):
    registry_path = tmp_path / "cameras.json"
    registry = camera_registry.CameraRegistry(
        registry_path,
        department="electrical_components",
    )
    registry.create("Camera A", "rtsp://camera-a/stream")

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["department"] == "electrical_components"

    mismatched = camera_registry.CameraRegistry(
        registry_path,
        department="precious_metal_recycling",
    )
    with pytest.raises(RuntimeError, match="事业部"):
        mismatched.list()


def test_registry_rejects_v1_file_even_for_default_department(tmp_path):
    registry_path = tmp_path / "cameras.json"
    registry_path.write_text(
        json.dumps({"version": 1, "cameras": []}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="格式"):
        camera_registry.CameraRegistry(registry_path).list()


def test_registry_rejects_malformed_camera_records(tmp_path):
    registry_path = tmp_path / "cameras.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": 2,
                "department": "general_electric",
                "cameras": [{"broken": True}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="格式"):
        camera_registry.CameraRegistry(registry_path).list()


@pytest.mark.parametrize("camera_id", [123, "../escape", "camera/id", "camera id"])
def test_registry_rejects_unsafe_persisted_camera_ids(tmp_path, camera_id):
    registry_path = tmp_path / "cameras.json"
    camera = {
        "camera_id": camera_id,
        "name": "Camera A",
        "rtsp_url": "rtsp://camera-a/stream",
        "created_at": 1.0,
        "updated_at": 1.0,
    }
    registry_path.write_text(
        json.dumps(
            {
                "version": 2,
                "department": "general_electric",
                "cameras": [camera],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="camera_id"):
        camera_registry.CameraRegistry(registry_path).list()


@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_legacy_migration_is_idempotent_and_copies_roi(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "config" / "cameras.json")
    staff_dir = tmp_path / "staff_rois"
    staff_dir.mkdir()
    legacy_roi = staff_dir / "stream_staff_rois.json"
    legacy_roi.write_text(
        json.dumps({"staff_rois": {"security_staff_1": [1, 2, 3, 4]}}),
        encoding="utf-8",
    )
    cfg = {
        "data": {
            "input_video": "rtsp://legacy-camera/stream",
            "video_id": "stream",
        },
    }

    first = registry.migrate_legacy(cfg, staff_dir)
    second = registry.migrate_legacy(cfg, staff_dir)

    assert first["camera_id"] == "legacy-default"
    assert second is None
    assert len(registry.list()) == 1
    payload = json.loads(registry.path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["department"] == "general_electric"
    migrated_roi = staff_dir / "legacy-default_staff_rois.json"
    assert migrated_roi.read_text(encoding="utf-8") == legacy_roi.read_text(encoding="utf-8")
    assert legacy_roi.exists()


@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_migration_does_nothing_without_legacy_source(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "cameras.json")

    assert registry.migrate_legacy({"data": {"input_video": ""}}, tmp_path) is None
    assert registry.list() == []
