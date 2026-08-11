"""Migrate legacy Guard Room metadata into the AiVision-owned database.

The standalone Guard Room process loaded ``guard_room/.env`` while the
AiVision-hosted application loads ``AiVision/.env``.  Those files can point at
different databases, so moving the source tree alone is not enough to preserve
guard rooms, cameras, and per-room settings.

This module is intentionally deployment-oriented:

* the legacy database is read only;
* existing target records always win;
* matching records are reused, making repeated runs idempotent;
* when the legacy database has no camera rows, the historical ``config.yaml``
  camera sources are imported as a compatibility fallback.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import URL, MetaData, create_engine, inspect, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

from .config import AppConfig
from .db import Base
from .orm import GuardRoomCamera, GuardRoomSite, GuardRoomSiteConfig
from .service import DEFAULT_DEPARTMENT, MAX_CAMERAS_PER_SITE

_DATABASE_ENV_KEYS = (
    "GUARD_ROOM_DATABASE_URL",
    "MYSQL_DB_URL",
    "MYSQL_DB_USER",
    "MYSQL_DB_PASSWORD",
    "MYSQL_DB_NAME",
    "MYSQL_DB_PORT",
    "MYSQL_DB_CHARSET",
)
_CONFIG_COLUMNS = {
    "video": "video_json",
    "models": "models_json",
    "room": "room_json",
    "rules": "rules_json",
    "classes": "classes_json",
    "runtime": "runtime_json",
    "wechat": "wechat_json",
}


class LegacyMigrationError(RuntimeError):
    """Raised when legacy Guard Room data cannot be migrated safely."""


@dataclass(frozen=True)
class LegacyCameraRecord:
    name: str
    rtsp_url: str
    enabled: bool = True
    sort_order: int = 0


@dataclass(frozen=True)
class LegacySiteRecord:
    name: str
    department: str
    enabled: bool
    sort_order: int
    description: str | None
    cameras: tuple[LegacyCameraRecord, ...] = ()
    config: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


@dataclass
class MigrationReport:
    """Counts from one idempotent migration run."""

    source: str
    sites_created: int = 0
    sites_matched: int = 0
    cameras_created: int = 0
    cameras_matched: int = 0
    camera_conflicts: int = 0
    configs_created: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.sites_created or self.cameras_created or self.configs_created)


def read_env_file(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE entries without mutating ``os.environ``."""
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def database_url_from_values(
    values: Mapping[str, str],
    *,
    base_dir: Path,
    sqlite_fallback: Path | None = None,
) -> URL | None:
    """Resolve the same Guard Room database precedence used at runtime."""
    explicit = str(values.get("GUARD_ROOM_DATABASE_URL") or "").strip()
    if explicit:
        return _resolve_relative_sqlite(make_url(explicit), base_dir)

    host = str(values.get("MYSQL_DB_URL") or "").strip()
    user = str(values.get("MYSQL_DB_USER") or "").strip()
    password = str(values.get("MYSQL_DB_PASSWORD") or "")
    database = str(values.get("MYSQL_DB_NAME") or "").strip()
    if host and user and password and database:
        raw_port = str(values.get("MYSQL_DB_PORT") or "3306").strip()
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise LegacyMigrationError(f"MYSQL_DB_PORT 不是有效端口: {raw_port}") from exc
        charset = str(values.get("MYSQL_DB_CHARSET") or "utf8mb4").strip()
        return URL.create(
            "mysql+pymysql",
            username=user,
            password=password,
            host=host,
            port=port,
            database=database,
            query={"charset": charset},
        )

    if sqlite_fallback is None:
        return None
    return URL.create("sqlite", database=str(sqlite_fallback.resolve()))


def _resolve_relative_sqlite(url: URL, base_dir: Path) -> URL:
    if not url.drivername.startswith("sqlite"):
        return url
    database = url.database
    if not database or database == ":memory:":
        return url
    path = Path(database)
    if path.is_absolute():
        return url
    return url.set(database=str((base_dir / path).resolve()))


def _same_database(first: URL | str, second: URL | str) -> bool:
    return make_url(first) == make_url(second)


def _create_engine(url: URL | str, *, source: bool = False) -> Engine:
    parsed = make_url(url)
    if source and parsed.drivername.startswith("sqlite"):
        database = parsed.database
        if database and database != ":memory:" and not Path(database).is_file():
            raise LegacyMigrationError(f"旧 Guard Room SQLite 数据库不存在: {database}")
    return create_engine(parsed, pool_pre_ping=not parsed.drivername.startswith("sqlite"), future=True)


def _ensure_target_schema(engine: Engine) -> None:
    """Create current tables and add the one column absent from early schemas."""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "guard_room_site" not in inspector.get_table_names():
        raise LegacyMigrationError("目标数据库无法创建 guard_room_site 表")
    columns = {column["name"] for column in inspector.get_columns("guard_room_site")}
    if "department" in columns:
        return

    if engine.dialect.name == "mysql":
        ddl = (
            "ALTER TABLE guard_room_site ADD COLUMN department VARCHAR(100) "
            f"NOT NULL DEFAULT '{DEFAULT_DEPARTMENT}' COMMENT '所属部门'"
        )
    else:
        ddl = f"ALTER TABLE guard_room_site ADD COLUMN department VARCHAR(100) NOT NULL DEFAULT '{DEFAULT_DEPARTMENT}'"
    with engine.begin() as connection:
        connection.execute(text(ddl))


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise LegacyMigrationError("旧 Guard Room 配置包含无效 JSON") from exc
        if isinstance(decoded, Mapping):
            return deepcopy(dict(decoded))
    return {}


def _clean_video_sources(video: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(dict(video))
    cleaned["source"] = ""
    for index in range(1, MAX_CAMERAS_PER_SITE + 1):
        cleaned.pop(f"source_cam{index}", None)
    return cleaned


def _load_default_sections(config_path: Path) -> dict[str, dict[str, Any]]:
    if not config_path.is_file():
        raise LegacyMigrationError(f"Guard Room 配置文件不存在: {config_path}")
    data = AppConfig.from_yaml(config_path).to_dict()
    sections = {section: deepcopy(dict(data.get(section) or {})) for section in _CONFIG_COLUMNS}
    sections["video"] = _clean_video_sources(sections["video"])
    return sections


def _merge_sections(
    defaults: Mapping[str, Mapping[str, Any]],
    legacy: Mapping[str, Mapping[str, Any]],
    *,
    site_name: str,
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for section in _CONFIG_COLUMNS:
        values = deepcopy(dict(defaults.get(section) or {}))
        values.update(deepcopy(dict(legacy.get(section) or {})))
        merged[section] = values
    merged["video"] = _clean_video_sources(merged["video"])
    if not str(merged["wechat"].get("camera_name") or "").strip():
        merged["wechat"]["camera_name"] = site_name
    return merged


def _load_database_records(engine: Engine) -> list[LegacySiteRecord]:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "guard_room_site" not in table_names:
        return []

    selected = ["guard_room_site"]
    if "guard_room_camera" in table_names:
        selected.append("guard_room_camera")
    if "guard_room_site_config" in table_names:
        selected.append("guard_room_site_config")
    metadata = MetaData()
    metadata.reflect(bind=engine, only=selected)
    site_table = metadata.tables["guard_room_site"]
    camera_table = metadata.tables.get("guard_room_camera")
    config_table = metadata.tables.get("guard_room_site_config")

    with engine.connect() as connection:
        site_rows = [dict(row._mapping) for row in connection.execute(select(site_table))]
        camera_rows = (
            [dict(row._mapping) for row in connection.execute(select(camera_table))] if camera_table is not None else []
        )
        config_rows = (
            [dict(row._mapping) for row in connection.execute(select(config_table))] if config_table is not None else []
        )

    cameras_by_site: dict[int, list[LegacyCameraRecord]] = {}
    for row in camera_rows:
        site_id = int(row["site_id"])
        name = str(row.get("name") or "").strip()
        rtsp_url = str(row.get("rtsp_url") or "").strip()
        if not name or not rtsp_url:
            raise LegacyMigrationError(f"旧数据库的摄像头记录不完整，site_id={site_id}")
        cameras_by_site.setdefault(site_id, []).append(
            LegacyCameraRecord(
                name=name,
                rtsp_url=rtsp_url,
                enabled=bool(row.get("enabled", True)),
                sort_order=int(row.get("sort_order") or 0),
            )
        )

    configs_by_site: dict[int, dict[str, dict[str, Any]]] = {}
    for row in config_rows:
        site_id = int(row["site_id"])
        configs_by_site[site_id] = {section: _json_dict(row.get(column)) for section, column in _CONFIG_COLUMNS.items()}

    records: list[LegacySiteRecord] = []
    for row in site_rows:
        site_id = int(row["id"])
        name = str(row.get("name") or "").strip()
        if not name:
            raise LegacyMigrationError(f"旧数据库存在空保安室名称，site_id={site_id}")
        cameras = sorted(
            cameras_by_site.get(site_id, []),
            key=lambda camera: (camera.sort_order, camera.name),
        )
        if len(cameras) > MAX_CAMERAS_PER_SITE:
            raise LegacyMigrationError(
                f"旧保安室“{name}”有 {len(cameras)} 路摄像头，超过平台上限 {MAX_CAMERAS_PER_SITE}"
            )
        records.append(
            LegacySiteRecord(
                name=name,
                department=str(row.get("department") or DEFAULT_DEPARTMENT).strip() or DEFAULT_DEPARTMENT,
                enabled=bool(row.get("enabled", True)),
                sort_order=int(row.get("sort_order") or 0),
                description=(str(row["description"]).strip() if row.get("description") else None),
                cameras=tuple(cameras),
                config=configs_by_site.get(site_id, {}),
            )
        )
    return sorted(records, key=lambda site: (site.sort_order, site.name))


def _yaml_camera_records(config_path: Path) -> tuple[LegacyCameraRecord, ...]:
    cfg = AppConfig.from_yaml(config_path)
    video = cfg.video
    sources: list[tuple[str, str]] = []
    for index in range(1, MAX_CAMERAS_PER_SITE + 1):
        value = getattr(video, f"source_cam{index}", "")
        normalized = str(value).strip() if value is not None else ""
        if normalized:
            sources.append((f"cam{index}", normalized))
    if not sources:
        fallback = str(video.source).strip() if video.source is not None else ""
        if fallback:
            sources.append(("cam1", fallback))
    return tuple(
        LegacyCameraRecord(name=name, rtsp_url=url, enabled=True, sort_order=index)
        for index, (name, url) in enumerate(sources, start=1)
    )


def _merge_yaml_camera_fallback(
    records: Sequence[LegacySiteRecord],
    *,
    config_path: Path,
    default_sections: Mapping[str, Mapping[str, Any]],
    legacy_site_name: str | None,
) -> tuple[list[LegacySiteRecord], bool]:
    if any(site.cameras for site in records):
        return list(records), False

    cameras = _yaml_camera_records(config_path)
    if not cameras:
        return list(records), False

    if len(records) > 1:
        raise LegacyMigrationError("旧数据库存在多个保安室但没有摄像头，无法判断 config.yaml 摄像头应归属哪个保安室")

    if records:
        existing = records[0]
        return [
            LegacySiteRecord(
                name=existing.name,
                department=existing.department,
                enabled=existing.enabled,
                sort_order=existing.sort_order,
                description=existing.description,
                cameras=cameras,
                config=existing.config or default_sections,
            )
        ], True

    configured_name = str(default_sections.get("wechat", {}).get("camera_name") or "").strip()
    site_name = str(legacy_site_name or configured_name or "默认保安室").strip()
    return [
        LegacySiteRecord(
            name=site_name,
            department=DEFAULT_DEPARTMENT,
            enabled=True,
            sort_order=1,
            description="由旧版 Guard Room 配置自动迁移",
            cameras=cameras,
            config=default_sections,
        )
    ], True


def _target_config_values(
    sections: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {column: deepcopy(dict(sections.get(section) or {})) for section, column in _CONFIG_COLUMNS.items()}


def _apply_records(
    engine: Engine,
    records: Sequence[LegacySiteRecord],
    *,
    defaults: Mapping[str, Mapping[str, Any]],
    source: str,
) -> MigrationReport:
    report = MigrationReport(source=source)
    site_table = GuardRoomSite.__table__
    camera_table = GuardRoomCamera.__table__
    config_table = GuardRoomSiteConfig.__table__

    with engine.begin() as connection:
        target_sites = [dict(row._mapping) for row in connection.execute(select(site_table))]
        target_cameras = [dict(row._mapping) for row in connection.execute(select(camera_table))]
        target_configs = [dict(row._mapping) for row in connection.execute(select(config_table))]

        sites_by_key = {
            (str(row.get("department") or DEFAULT_DEPARTMENT), str(row["name"])): row for row in target_sites
        }
        cameras_by_site: dict[int, list[dict[str, Any]]] = {}
        for row in target_cameras:
            cameras_by_site.setdefault(int(row["site_id"]), []).append(row)
        configured_site_ids = {int(row["site_id"]) for row in target_configs}

        for legacy_site in records:
            key = (legacy_site.department, legacy_site.name)
            target_site = sites_by_key.get(key)
            if target_site is None:
                result = connection.execute(
                    site_table.insert().values(
                        department=legacy_site.department,
                        name=legacy_site.name,
                        enabled=legacy_site.enabled,
                        sort_order=legacy_site.sort_order,
                        description=legacy_site.description,
                    )
                )
                target_site_id = int(result.inserted_primary_key[0])
                target_site = {
                    "id": target_site_id,
                    "department": legacy_site.department,
                    "name": legacy_site.name,
                }
                sites_by_key[key] = target_site
                cameras_by_site[target_site_id] = []
                report.sites_created += 1
            else:
                target_site_id = int(target_site["id"])
                report.sites_matched += 1

            sections = _merge_sections(defaults, legacy_site.config, site_name=legacy_site.name)
            if target_site_id not in configured_site_ids:
                connection.execute(
                    config_table.insert().values(
                        site_id=target_site_id,
                        **_target_config_values(sections),
                    )
                )
                configured_site_ids.add(target_site_id)
                report.configs_created += 1

            existing_cameras = cameras_by_site.setdefault(target_site_id, [])
            existing_by_name = {str(row["name"]): row for row in existing_cameras}
            existing_by_url = {str(row["rtsp_url"]): row for row in existing_cameras}
            pending: list[LegacyCameraRecord] = []
            seen_names: dict[str, str] = {}
            seen_urls: set[str] = set()
            for camera in legacy_site.cameras:
                duplicate_url = seen_names.get(camera.name)
                if duplicate_url is not None and duplicate_url != camera.rtsp_url:
                    raise LegacyMigrationError(f"旧保安室“{legacy_site.name}”存在同名但地址不同的摄像头: {camera.name}")
                if camera.rtsp_url in seen_urls or duplicate_url == camera.rtsp_url:
                    continue
                seen_names[camera.name] = camera.rtsp_url
                seen_urls.add(camera.rtsp_url)

                same_name = existing_by_name.get(camera.name)
                if same_name is not None:
                    if str(same_name["rtsp_url"]) == camera.rtsp_url:
                        report.cameras_matched += 1
                    else:
                        report.camera_conflicts += 1
                    continue
                if camera.rtsp_url in existing_by_url:
                    report.cameras_matched += 1
                    continue
                pending.append(camera)

            if len(existing_cameras) + len(pending) > MAX_CAMERAS_PER_SITE:
                raise LegacyMigrationError(
                    f"迁移后保安室“{legacy_site.name}”将超过 {MAX_CAMERAS_PER_SITE} 路摄像头上限"
                )

            for camera in pending:
                result = connection.execute(
                    camera_table.insert().values(
                        site_id=target_site_id,
                        name=camera.name,
                        rtsp_url=camera.rtsp_url,
                        enabled=camera.enabled,
                        sort_order=camera.sort_order,
                    )
                )
                created = {
                    "id": int(result.inserted_primary_key[0]),
                    "site_id": target_site_id,
                    "name": camera.name,
                    "rtsp_url": camera.rtsp_url,
                }
                existing_cameras.append(created)
                existing_by_name[camera.name] = created
                existing_by_url[camera.rtsp_url] = created
                report.cameras_created += 1

    return report


def migrate_legacy_data(
    *,
    target_url: URL | str,
    source_url: URL | str | None,
    config_path: Path,
    legacy_site_name: str | None = None,
) -> MigrationReport:
    """Merge legacy database/YAML records into the target database."""
    config_path = Path(config_path).resolve()
    defaults = _load_default_sections(config_path)
    target_engine = _create_engine(target_url)
    source_engine: Engine | None = None
    try:
        _ensure_target_schema(target_engine)
        records: list[LegacySiteRecord] = []
        source_name = "config.yaml"
        if source_url is not None:
            if _same_database(source_url, target_url):
                records = _load_database_records(target_engine)
                source_name = "目标库中的既有 Guard Room 数据"
            else:
                source_engine = _create_engine(source_url, source=True)
                records = _load_database_records(source_engine)
                source_name = "旧 Guard Room 数据库"

        records, used_yaml = _merge_yaml_camera_fallback(
            records,
            config_path=config_path,
            default_sections=defaults,
            legacy_site_name=legacy_site_name,
        )
        if used_yaml:
            source_name = f"{source_name} + config.yaml" if source_url is not None else "config.yaml"
        return _apply_records(target_engine, records, defaults=defaults, source=source_name)
    finally:
        if source_engine is not None:
            source_engine.dispose()
        target_engine.dispose()


def _overlay_runtime_database_values(file_values: Mapping[str, str]) -> dict[str, str]:
    values = dict(file_values)
    for key in _DATABASE_ENV_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def resolve_project_urls(project_root: Path) -> tuple[URL | None, URL, Path]:
    """Resolve legacy source, AiVision target, and real Guard config paths."""
    project_root = Path(project_root).resolve()
    aivision_root = project_root / "AiVision"
    module_root = aivision_root / "integrations" / "guard_room"
    target_env = aivision_root / ".env"
    target_values = _overlay_runtime_database_values(read_env_file(target_env))
    target_url = database_url_from_values(
        target_values,
        base_dir=aivision_root,
        sqlite_fallback=module_root / "guard_room.db",
    )
    if target_url is None:
        raise LegacyMigrationError("无法确定 AiVision 的 Guard Room 目标数据库")

    legacy_env_candidates = (module_root / ".env", project_root / "guard_room" / ".env")
    legacy_env = next((path for path in legacy_env_candidates if path.is_file()), None)
    legacy_values = read_env_file(legacy_env) if legacy_env is not None else {}
    legacy_sqlite_candidates = (
        module_root / "guard_room.db",
        project_root / "guard_room" / "guard_room.db",
    )
    legacy_sqlite = next((path for path in legacy_sqlite_candidates if path.is_file()), None)
    source_url = database_url_from_values(
        legacy_values,
        base_dir=legacy_env.parent if legacy_env is not None else module_root,
        sqlite_fallback=legacy_sqlite,
    )
    return source_url, target_url, module_root / "config" / "config.yaml"


def _build_parser() -> argparse.ArgumentParser:
    module_path = Path(__file__).resolve()
    parser = argparse.ArgumentParser(description="迁移旧版保安行为规范检测的保安室与摄像头数据")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=module_path.parents[4],
        help="项目根目录；默认根据当前模块位置推导",
    )
    parser.add_argument("--source-url", help="显式指定旧数据库 URL（通常不需要）")
    parser.add_argument("--target-url", help="显式指定目标数据库 URL（通常不需要）")
    parser.add_argument("--config", type=Path, help="显式指定旧 Guard Room config.yaml")
    parser.add_argument("--legacy-site-name", help="YAML 回退导入时使用的保安室名称")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        resolved_source, resolved_target, resolved_config = resolve_project_urls(args.project_root)
        source_url = make_url(args.source_url) if args.source_url else resolved_source
        target_url = make_url(args.target_url) if args.target_url else resolved_target
        config_path = args.config.resolve() if args.config else resolved_config
        report = migrate_legacy_data(
            target_url=target_url,
            source_url=source_url,
            config_path=config_path,
            legacy_site_name=args.legacy_site_name,
        )
    except (LegacyMigrationError, OSError, SQLAlchemyError, ValueError) as exc:
        print(f"ERROR: Guard Room 历史数据迁移失败: {exc}", file=os.sys.stderr)
        return 2

    action = "已写入目标库" if report.changed else "目标库已包含全部数据"
    print(f"Guard Room 历史数据迁移完成：{action}（来源：{report.source}）")
    print(
        "  保安室 新建/已存在: "
        f"{report.sites_created}/{report.sites_matched}，"
        "摄像头 新建/已存在/冲突保留现值: "
        f"{report.cameras_created}/{report.cameras_matched}/{report.camera_conflicts}，"
        f"配置 新建: {report.configs_created}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
