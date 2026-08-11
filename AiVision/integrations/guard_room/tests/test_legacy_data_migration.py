from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import AppConfig
from src.db import Base
from src.legacy_data_migration import migrate_legacy_data
from src.orm import GuardRoomCamera, GuardRoomSite, GuardRoomSiteConfig


def _write_config(path: Path, *, first_source: str = "", second_source: str = "") -> None:
    path.write_text(
        "\n".join(
            (
                "video:",
                "  source: ''",
                f"  source_cam1: '{first_source}'",
                f"  source_cam2: '{second_source}'",
                "models:",
                "  detector_model: models/person_phone.pt",
                "rules:",
                "  absent_seconds: 150",
                "wechat:",
                "  camera_name: 原值班室",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _seed_legacy_database(database_path: Path, config_path: Path) -> None:
    engine = create_engine(_sqlite_url(database_path), future=True)
    Base.metadata.create_all(engine)
    sections = AppConfig.from_yaml(config_path).to_dict()
    sections["video"]["source"] = ""
    sections["video"].pop("source_cam1", None)
    sections["video"].pop("source_cam2", None)
    sections["rules"]["absent_seconds"] = 321

    with engine.begin() as connection:
        site_result = connection.execute(
            GuardRoomSite.__table__.insert().values(
                department="general_electric",
                name="北门保安室",
                enabled=True,
                sort_order=3,
                description="旧库记录",
            )
        )
        site_id = int(site_result.inserted_primary_key[0])
        connection.execute(
            GuardRoomCamera.__table__.insert(),
            (
                {
                    "site_id": site_id,
                    "name": "北门左侧",
                    "rtsp_url": "rtsp://legacy-left",
                    "enabled": True,
                    "sort_order": 1,
                },
                {
                    "site_id": site_id,
                    "name": "北门右侧",
                    "rtsp_url": "rtsp://legacy-right",
                    "enabled": False,
                    "sort_order": 2,
                },
            ),
        )
        connection.execute(
            GuardRoomSiteConfig.__table__.insert().values(
                site_id=site_id,
                video_json=sections["video"],
                models_json=sections["models"],
                room_json=sections["room"],
                rules_json=sections["rules"],
                classes_json=sections["classes"],
                runtime_json=sections["runtime"],
                wechat_json=sections["wechat"],
            )
        )
    engine.dispose()


def test_database_migration_preserves_records_and_is_idempotent(tmp_path):
    config_path = tmp_path / "config.yaml"
    source_path = tmp_path / "legacy.db"
    target_path = tmp_path / "target.db"
    _write_config(config_path)
    _seed_legacy_database(source_path, config_path)

    first = migrate_legacy_data(
        source_url=_sqlite_url(source_path),
        target_url=_sqlite_url(target_path),
        config_path=config_path,
    )

    assert first.sites_created == 1
    assert first.cameras_created == 2
    assert first.configs_created == 1

    engine = create_engine(_sqlite_url(target_path), future=True)
    with engine.connect() as connection:
        sites = connection.execute(select(GuardRoomSite.__table__)).mappings().all()
        cameras = (
            connection.execute(select(GuardRoomCamera.__table__).order_by(GuardRoomCamera.sort_order)).mappings().all()
        )
        configs = connection.execute(select(GuardRoomSiteConfig.__table__)).mappings().all()
    engine.dispose()

    assert [(row["name"], row["description"]) for row in sites] == [("北门保安室", "旧库记录")]
    assert [(row["name"], row["rtsp_url"], row["enabled"]) for row in cameras] == [
        ("北门左侧", "rtsp://legacy-left", True),
        ("北门右侧", "rtsp://legacy-right", False),
    ]
    assert configs[0]["rules_json"]["absent_seconds"] == 321

    second = migrate_legacy_data(
        source_url=_sqlite_url(source_path),
        target_url=_sqlite_url(target_path),
        config_path=config_path,
    )

    assert second.sites_created == 0
    assert second.sites_matched == 1
    assert second.cameras_created == 0
    assert second.cameras_matched == 2
    assert second.configs_created == 0


def test_yaml_camera_sources_seed_empty_target_once(tmp_path):
    config_path = tmp_path / "config.yaml"
    target_path = tmp_path / "target.db"
    _write_config(
        config_path,
        first_source="rtsp://yaml-left",
        second_source="rtsp://yaml-right",
    )

    first = migrate_legacy_data(
        source_url=None,
        target_url=_sqlite_url(target_path),
        config_path=config_path,
    )
    second = migrate_legacy_data(
        source_url=_sqlite_url(target_path),
        target_url=_sqlite_url(target_path),
        config_path=config_path,
    )

    assert first.source == "config.yaml"
    assert first.sites_created == 1
    assert first.cameras_created == 2
    assert second.sites_created == 0
    assert second.cameras_created == 0
    assert second.cameras_matched == 2

    engine = create_engine(_sqlite_url(target_path), future=True)
    with engine.connect() as connection:
        sites = connection.execute(select(GuardRoomSite.__table__)).mappings().all()
        cameras = connection.execute(select(GuardRoomCamera.__table__)).mappings().all()
    engine.dispose()

    assert [row["name"] for row in sites] == ["原值班室"]
    assert {row["rtsp_url"] for row in cameras} == {"rtsp://yaml-left", "rtsp://yaml-right"}


def test_existing_target_camera_wins_on_name_conflict(tmp_path):
    config_path = tmp_path / "config.yaml"
    source_path = tmp_path / "legacy.db"
    target_path = tmp_path / "target.db"
    _write_config(config_path)
    _seed_legacy_database(source_path, config_path)

    target_engine = create_engine(_sqlite_url(target_path), future=True)
    Base.metadata.create_all(target_engine)
    with target_engine.begin() as connection:
        site_result = connection.execute(
            GuardRoomSite.__table__.insert().values(
                department="general_electric",
                name="北门保安室",
                enabled=True,
                sort_order=1,
            )
        )
        site_id = int(site_result.inserted_primary_key[0])
        connection.execute(
            GuardRoomCamera.__table__.insert().values(
                site_id=site_id,
                name="北门左侧",
                rtsp_url="rtsp://new-current-value",
                enabled=True,
                sort_order=1,
            )
        )
    target_engine.dispose()

    report = migrate_legacy_data(
        source_url=_sqlite_url(source_path),
        target_url=_sqlite_url(target_path),
        config_path=config_path,
    )

    assert report.camera_conflicts == 1
    assert report.cameras_created == 1
    engine = create_engine(_sqlite_url(target_path), future=True)
    with engine.connect() as connection:
        cameras = connection.execute(select(GuardRoomCamera.__table__)).mappings().all()
    engine.dispose()
    by_name = {row["name"]: row["rtsp_url"] for row in cameras}
    assert by_name == {
        "北门左侧": "rtsp://new-current-value",
        "北门右侧": "rtsp://legacy-right",
    }
