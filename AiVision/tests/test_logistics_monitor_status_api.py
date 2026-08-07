import importlib
import sys


sys.modules.pop("platform", None)
compat_module = importlib.import_module("api.compat")
orchestrator_module = importlib.import_module("platform.orchestrator")


class FakeCameraManager:
    def __init__(self, running):
        self._running = running

    def list_running(self):
        return list(self._running)


class FakeConsumer:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def get_monitor_status(self, camera_key):
        return dict(self._snapshot) if self._snapshot else None


def build_orchestrator(*, running=("cam1",), snapshot=None):
    orchestrator = object.__new__(orchestrator_module.Orchestrator)
    orchestrator.camera_manager = FakeCameraManager(running)
    orchestrator.consumers = {
        "detect_logistics_single_person": FakeConsumer(snapshot),
    }
    return orchestrator


def test_orchestrator_returns_fresh_typed_snapshot(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 101.0)
    orchestrator = build_orchestrator(
        snapshot={
            "count": 1,
            "alarm": False,
            "reason": "normal",
            "duration_seconds": 12.5,
            "threshold_seconds": 30.0,
            "updated_at_s": 100.0,
        }
    )

    response = orchestrator.get_feature_monitor_status(
        "cam1",
        "detect_logistics_single_person",
    )

    assert response["camera_key"] == "cam1"
    assert response["online"] is True
    assert response["count"] == 1
    assert response["alarm"] is False
    assert response["reason"] == "normal"
    assert response["duration_seconds"] == 12.5
    assert response["threshold_seconds"] == 30.0
    assert response["updated_at"]


def test_orchestrator_returns_unknown_for_stale_snapshot(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 120.0)
    orchestrator = build_orchestrator(
        running=(),
        snapshot={
            "count": 2,
            "alarm": True,
            "reason": "multiple",
            "duration_seconds": 18.0,
            "threshold_seconds": 10.0,
            "updated_at_s": 100.0,
        },
    )

    response = orchestrator.get_feature_monitor_status(
        "cam1",
        "detect_logistics_single_person",
    )

    assert response["online"] is False
    assert response["count"] is None
    assert response["alarm"] is False
    assert response["reason"] == "unknown"
    assert response["duration_seconds"] is None
    assert response["threshold_seconds"] is None


def test_compat_status_delegates_to_read_only_orchestrator():
    expected = {
        "camera_key": "cam1",
        "feature": "detect_logistics_single_person",
        "online": True,
        "count": 1,
        "alarm": False,
        "reason": "normal",
        "updated_at": "2026-08-06T10:40:46+08:00",
    }

    class StatusOrchestrator:
        def get_feature_monitor_status(self, camera_key, feature):
            assert camera_key == "cam1"
            assert feature == "detect_logistics_single_person"
            return expected

    class CameraService:
        def get_camera(self, key):
            return {"shm_name": key, "department": "general_electric"}

    response = compat_module.compat_get_camera_feature_status(
        key="cam1",
        feature="detect_logistics_single_person",
        user={"role": "viewer", "department": "general_electric"},
        camera_service=CameraService(),
        orchestrator=StatusOrchestrator(),
    )

    assert response == expected
