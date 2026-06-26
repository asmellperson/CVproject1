import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import AppConfig
from src.db import configure_for_tests, session_scope
from src.orm import GuardRoomSiteConfig
from src.service import GuardRoomService


def test_site_service_creates_site_cameras_and_app_config(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room.db'}")
    service = GuardRoomService()
    service.ensure_schema()

    site = service.create_site("一厂区南门保安室")
    assert site["name"] == "一厂区南门保安室"

    first = service.create_camera(site["id"], name="门口左侧", rtsp_url="rtsp://camera-1")
    second = service.create_camera(site["id"], name="门口右侧", rtsp_url="rtsp://camera-2")

    assert first["sort_order"] == 1
    assert second["sort_order"] == 2

    detail = service.get_site(site["id"])
    assert detail is not None
    assert [camera["name"] for camera in detail["cameras"]] == ["门口左侧", "门口右侧"]

    cfg = service.build_app_config(site["id"])
    assert isinstance(cfg, AppConfig)
    assert cfg.camera_sources() == [("cam1", "rtsp://camera-1"), ("cam2", "rtsp://camera-2")]
    assert cfg.wechat.camera_name == "一厂区南门保安室"


def test_site_service_limits_site_to_nine_cameras(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room.db'}")
    service = GuardRoomService()
    service.ensure_schema()
    site = service.create_site("二厂区值班室")

    for idx in range(1, 10):
        service.create_camera(site["id"], name=f"摄像头{idx}", rtsp_url=f"rtsp://camera-{idx}")

    with pytest.raises(ValueError, match="最多只能添加 9 路摄像头"):
        service.create_camera(site["id"], name="摄像头10", rtsp_url="rtsp://camera-10")


def test_site_service_scopes_sites_by_department(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_department.db'}")
    service = GuardRoomService()
    service.ensure_schema()

    ge_site = service.create_site("南门保安室", department="general_electric")
    electronics_site = service.create_site("南门保安室", department="electronics_electrician")

    assert ge_site["department"] == "general_electric"
    assert electronics_site["department"] == "electronics_electrician"
    assert [site["id"] for site in service.list_sites(department="general_electric")] == [ge_site["id"]]
    assert [site["id"] for site in service.list_sites(department="electronics_electrician")] == [electronics_site["id"]]


def test_site_service_replaces_orphan_config_when_sqlite_reuses_site_id(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_orphan_config.db'}")
    service = GuardRoomService()
    service.ensure_schema()

    first_site = service.create_site("临时保安室")
    first_config = service.get_site_config(first_site["id"])
    assert first_config is not None
    service.delete_site(first_site["id"])

    with session_scope() as session:
        session.add(
            GuardRoomSiteConfig(
                site_id=2,
                **GuardRoomService._sections_to_orm_kwargs(service._config_sections(first_config)),
            )
        )

    second_site = service.create_site("电子电工保安室", department="electronics_electrician")

    assert second_site["department"] == "electronics_electrician"
    assert service.get_site_config(second_site["id"]) is not None
