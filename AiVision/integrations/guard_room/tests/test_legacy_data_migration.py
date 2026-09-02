# 文件说明：包含数据迁移的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select


from AiVision.integrations.guard_room.src.config import AppConfig
from AiVision.integrations.guard_room.src.db import Base
from AiVision.integrations.guard_room.src.legacy_data_migration import migrate_legacy_data
from AiVision.integrations.guard_room.src.orm import GuardRoomCamera, GuardRoomSite, GuardRoomSiteConfig


# 功能：更新或保存 `_write_config` 对应的数据迁移逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
#   - `first_source`（str）：`first_source` 对应的业务输入值；默认值为 `''`
#   - `second_source`（str）：`second_source` 对应的业务输入值；默认值为 `''`
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的
#         `test_database_migration_preserves_records_and_is_idempotent`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的
#         `test_yaml_camera_sources_seed_empty_target_once`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的
#         `test_existing_target_camera_wins_on_name_conflict` 调用本符号
#   - 内部调用：`path.write_text`、`'\n'.join`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
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


# 功能：实现 `_sqlite_url` 对应的数据迁移逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的 `_seed_legacy_database`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的
#         `test_database_migration_preserves_records_and_is_idempotent`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的
#         `test_yaml_camera_sources_seed_empty_target_once`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的
#         `test_existing_target_camera_wins_on_name_conflict` 调用本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


# 功能：实现 `_seed_legacy_database` 对应的数据迁移逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `database_path`（Path）：`database_path` 对应的业务输入值
#   - `config_path`（Path）：`config_path` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的
#         `test_database_migration_preserves_records_and_is_idempotent`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的
#         `test_existing_target_camera_wins_on_name_conflict` 调用本符号
#   - 内部调用：`create_engine`、`_sqlite_url`、`Base.metadata.create_all`、`AppConfig.from_yaml(config_path).to_dict`、`AppConfig.from_yaml`、`sections['video'].pop`、`engine.begin`、`connection.execute`、`GuardRoomSite.__table__.insert().values`、`GuardRoomSite.__table__.insert`
#          等共 15 个调用。
# 副作用/注意事项：可能读取或修改数据库事务。
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


# 功能：验证 `test_database_migration_preserves_records_and_is_idempotent` 对应的数据迁移逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_write_config`、`_seed_legacy_database`、`migrate_legacy_data`、`_sqlite_url`、`create_engine`、`engine.connect`、`connection.execute(select(GuardRoomSite.__table__)).mappings().all`、`connection.execute(select(GuardRoomSite.__table__)).mappings`、`connection.execute`、`select`
#          等共 16 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能读取或修改数据库事务。
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


# 功能：验证 `test_yaml_camera_sources_seed_empty_target_once` 对应的数据迁移逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_write_config`、`migrate_legacy_data`、`_sqlite_url`、`create_engine`、`engine.connect`、`connection.execute(select(GuardRoomSite.__table__)).mappings().all`、`connection.execute(select(GuardRoomSite.__table__)).mappings`、`connection.execute`、`select`、`connection.execute(select(GuardRoomCamera.__table__)).mappings().all`
#          等共 12 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能读取或修改数据库事务。
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


# 功能：验证 `test_existing_target_camera_wins_on_name_conflict` 对应的数据迁移逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_write_config`、`_seed_legacy_database`、`create_engine`、`_sqlite_url`、`Base.metadata.create_all`、`target_engine.begin`、`connection.execute`、`GuardRoomSite.__table__.insert().values`、`GuardRoomSite.__table__.insert`、`int`
#          等共 19 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能读取或修改数据库事务。
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
