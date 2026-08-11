import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import configure_for_tests
from src.runtime_manager import GuardRoomRuntimeManager
from src.service import GuardRoomService
from src.types import AlarmEvent


class FakeRuntime:
    def __init__(self, config, state, **kwargs):
        self.config = config
        self.state = state
        self.kwargs = kwargs
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1
        self.state.mark_running(True)

    def stop(self):
        self.stop_calls += 1
        self.state.mark_running(False)


def _service(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_runtime.db'}")
    service = GuardRoomService()
    service.ensure_schema()
    return service


def test_runtime_manager_starts_and_stops_one_site_without_affecting_another(tmp_path):
    service = _service(tmp_path)
    site_a = service.create_site("一厂区南门保安室")
    site_b = service.create_site("二厂区值班室")
    for site in (site_a, site_b):
        service.update_site_config(site["id"], {"wechat": {"enable": False}})
        service.create_camera(site["id"], name="左侧", rtsp_url=f"rtsp://{site['id']}-1")
        service.create_camera(site["id"], name="右侧", rtsp_url=f"rtsp://{site['id']}-2")

    manager = GuardRoomRuntimeManager(service, runtime_cls=FakeRuntime)

    started = manager.start(site_a["id"])
    assert started["running"] is True
    assert started["site_id"] == site_a["id"]
    assert manager.get_status(site_a["id"])["running"] is True
    assert manager.get_status(site_b["id"])["running"] is False

    stopped = manager.stop(site_a["id"])
    assert stopped["running"] is False
    assert manager.get_status(site_a["id"])["running"] is False
    assert service.get_site(site_a["id"])["enabled"] is False
    assert service.get_site(site_b["id"])["enabled"] is True


def test_runtime_manager_shutdown_preserves_desired_enabled_state(tmp_path):
    service = _service(tmp_path)
    site = service.create_site("默认开启保安室")
    service.update_site_config(site["id"], {"wechat": {"enable": False}})
    service.create_camera(site["id"], name="入口", rtsp_url="rtsp://camera-1")
    manager = GuardRoomRuntimeManager(service, runtime_cls=FakeRuntime)

    manager.start(site["id"])
    manager.stop_all()

    assert service.get_site(site["id"])["enabled"] is True


def test_runtime_manager_enriches_status_frame_and_alarms_with_site_metadata(tmp_path):
    service = _service(tmp_path)
    site = service.create_site("仓库岗亭")
    service.update_site_config(site["id"], {"wechat": {"enable": False}})
    service.create_camera(site["id"], name="左侧", rtsp_url="rtsp://camera-1")
    service.create_camera(site["id"], name="右侧", rtsp_url="rtsp://camera-2")
    manager = GuardRoomRuntimeManager(service, runtime_cls=FakeRuntime)

    manager.start(site["id"])
    state = manager.get_state(site["id"])
    state.add_alarm(
        AlarmEvent(
            event_type="absent",
            timestamp_s=1.0,
            frame_index=3,
            track_id=None,
            confidence=0.9,
            reason="测试报警",
            camera_name="仓库岗亭",
        )
    )

    status = manager.get_status(site["id"])
    assert status["site_id"] == site["id"]
    assert status["site_name"] == "仓库岗亭"
    assert status["last_alarm"]["site_id"] == site["id"]
    assert manager.get_latest_frame(site["id"]).startswith(b"\xff\xd8")
    assert manager.get_alarms(site["id"], limit=10)[0]["site_name"] == "仓库岗亭"
