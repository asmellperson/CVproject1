"""显式离线合并人员逗留配置。默认只读；不被运行代码导入。

要求停止全部写入并先做独立数据库备份。事务只修改行，旧表由独立命令移除。
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from contextlib import closing
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct

from sqlalchemy import Boolean, Integer, JSON, MetaData, String, Table, cast, create_engine, inspect, select, text

from AiVision.core.schema import assert_table_matches
from AiVision.features.detect_human import SPEC


REVISION = "human_20260915"
OLD = "detect_human_haoda"
NEW = "detect_human"
SOURCE = "ai_camera_config_" + OLD
TARGET = "ai_camera_config_" + NEW
CAMERAS = "ai_camera_config"
ALARMS = "ai_violation_image"
LINKS = "ai_feature_department"
FUNCTIONS = "ai_function"
META_FIELDS = {"id", "camera_id", "created_at", "updated_at"}
CAMERA_COLUMNS = ("id", "department", "function_config", "updated_at")
ALARM_COLUMNS = ("id", "violation_type", "feature_name", "department", "event_metadata",
                 "camera_no", "subject_type", "subject_id")


def _json_default(value):
    if isinstance(value, dt.datetime):
        return {"__datetime__": value.isoformat()}
    raise TypeError(f"unsupported backup value: {type(value).__name__}")


def _encode(value):
    return json.dumps(value, default=_json_default, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value):
    return json.loads(value, object_hook=lambda obj: dt.datetime.fromisoformat(obj["__datetime__"])
                      if set(obj) == {"__datetime__"} else obj)


def _contains_old(value):
    return OLD in _encode(value)


def _table(connection, name):
    return Table(name, MetaData(), autoload_with=connection)


def _rows(connection, table, columns=None):
    columns = list(columns or table.columns.keys())
    # 禁止 SQLAlchemy BOOLEAN 把非法 2 静默变为 True。
    selected = [cast(table.c[name], Integer).label(name) if isinstance(table.c[name].type, Boolean)
                else table.c[name] for name in columns]
    return [dict(row) for row in connection.execute(select(*selected).order_by(table.c.id)).mappings()]


def _default_row():
    row = SPEC.orm_class()
    row.apply_config_dict(SPEC.config_schema().model_dump())
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in META_FIELDS}


def _is_default(row, dialect):
    def equal(actual, expected):
        if dialect == "mysql" and isinstance(expected, float) and isinstance(actual, (int, float)):
            return struct.pack("f", actual) == struct.pack("f", expected)
        return actual == expected
    # FeatureConfigBase.to_alarm_dict 已将 NULL 接收人读作空字符串。
    # 仅在微信关闭且接收人确实为空时等价比较，不改写原始 NULL 或其他参数。
    values = dict(row)
    if not values["wechat_enable"] and values["wechat_user"] is None:
        values["wechat_user"] = ""
    return all(equal(values[key], value) for key, value in _default_row().items())


def _validate_config(row, table_name):
    values = dict(row)
    for column in SPEC.orm_class.__table__.columns:
        if isinstance(column.type, Boolean):
            if values[column.name] not in (0, 1) or values[column.name] is None:
                raise ValueError(f"{table_name} id={row['id']}: 非法布尔字段 {column.name}")
            values[column.name] = bool(values[column.name])
    try:
        SPEC.config_schema.model_validate(SPEC.orm_class(**values).to_config_dict())
    except ValueError as exc:
        # 错误仅给行标识，避免在日志输出告警接收人等配置值。
        raise ValueError(f"{table_name} id={row['id']}: 配置不符合 HumanConfigSchema") from exc


def _check_schema(connection, *, source_required=True):
    inspector = inspect(connection)
    names = set(inspector.get_table_names())
    required = {CAMERAS, TARGET, ALARMS} | ({SOURCE} if source_required else set())
    if not required <= names:
        raise ValueError(f"缺少必要表: {sorted(required - names)}")
    assert_table_matches(connection, SPEC.orm_class.__table__)
    if SOURCE in names:
        assert_table_matches(connection, SPEC.orm_class.__table__, actual_name=SOURCE)
    selected = {CAMERAS, TARGET, SOURCE, ALARMS, LINKS, FUNCTIONS} & names
    if connection.dialect.name == "mysql":
        engines = dict(connection.execute(text(
            "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()"
        )).all())
        if any(engines[name] != "InnoDB" for name in selected):
            raise ValueError("迁移涉及的表必须全部使用 InnoDB")
        triggers = connection.execute(text(
            "SELECT EVENT_OBJECT_TABLE FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()"
        )).scalars()
    elif connection.dialect.name == "sqlite":
        triggers = connection.execute(text("SELECT tbl_name FROM sqlite_master WHERE type='trigger'")).scalars()
    else:
        raise ValueError("只支持 MySQL 和 SQLite 隔离测试库")
    if selected.intersection(triggers):
        raise ValueError("涉及表存在触发器，须先人工审查")
    for name in names:
        for fk in inspector.get_foreign_keys(name):
            if fk["referred_table"] in {SOURCE, TARGET}:
                raise ValueError(f"{name}: 外键引用人员配置行 ID，须先制定引用转换方案")
    for name in inspector.get_view_names():
        if OLD in (inspector.get_view_definition(name) or ""):
            raise ValueError(f"视图 {name} 引用旧功能，须先人工处理")
    for name, expected in ((LINKS, {"id", "feature_name", "department"}),
                           (FUNCTIONS, {"id", "name", "description", "required_models", "config_table_name",
                                        "import_path", "enable", "created_at", "updated_at"})):
        if name in names and {c["name"] for c in inspector.get_columns(name)} != expected:
            raise ValueError(f"{name}: 非预期持久化目录结构")
    return names


def _scan_other_references(connection, names):
    """未知表/字段含旧标识时阻断，不猜测语义；历史备份只报告、不改写。"""
    archives = sorted(name for name in names if name.endswith("__cfg_backup") or name.startswith("bak_lg_"))
    allowed = {
        CAMERAS: {"function_config"}, ALARMS: {"feature_name", "event_metadata", "image_path", "video_path"},
        LINKS: {"feature_name"}, FUNCTIONS: {"name", "config_table_name", "import_path"},
    }
    for name in sorted(names - set(archives) - {SOURCE, TARGET}):
        table = _table(connection, name)
        for column in table.columns:
            if column.name in allowed.get(name, set()):
                continue
            if isinstance(column.type, (String, JSON)):
                found = connection.execute(select(column).where(cast(column, String).contains(OLD)).limit(1)).first()
                if found is not None:
                    raise ValueError(f"未处理的持久化引用: {name}.{column.name}")
    return archives


def preflight(connection):
    """只读生成精确前后镜像，所有冲突必须在任何写入之前发现。"""
    names = _check_schema(connection)
    tables = {name: _table(connection, name) for name in {CAMERAS, SOURCE, TARGET, ALARMS, LINKS, FUNCTIONS} & names}
    before = {name: _rows(connection, table, CAMERA_COLUMNS if name == CAMERAS else
                         ALARM_COLUMNS if name == ALARMS else None) for name, table in tables.items()}
    after = deepcopy(before)
    cameras = {row["id"]: row for row in before[CAMERAS]}
    old_by_camera = {}
    new_by_camera = {}
    for table_name, index in ((SOURCE, old_by_camera), (TARGET, new_by_camera)):
        for row in before[table_name]:
            _validate_config(row, table_name)
            camera_id = row["camera_id"]
            if camera_id not in cameras or camera_id in index:
                raise ValueError(f"{table_name} id={row['id']}: 孤立或重复摄像头关联")
            index[camera_id] = row
            if not _is_default(row, connection.dialect.name):
                departments = {"haoda_company"} if table_name == SOURCE else set(SPEC.departments)
                if cameras[camera_id]["department"] not in departments:
                    raise ValueError(
                        f"{table_name} camera_id={camera_id}: 非默认配置与当前事业部归属不一致；"
                        "须人工确认历史用途，不能据此认定配置无效或修改归属绕过检查"
                    )
            if row["horn_id"] is not None:
                horn = _table(connection, "ai_horn_config")
                if connection.execute(select(horn.c.id).where(horn.c.id == row["horn_id"])).first() is None:
                    raise ValueError(f"{table_name} id={row['id']}: 喇叭关联不存在")
    merged = {row["camera_id"]: row for row in after[TARGET]}
    next_id = max((row["id"] for row in after[TARGET]), default=0)
    transferred, placeholders = [], []
    for camera_id, source in old_by_camera.items():
        target = merged.get(camera_id)
        source_default = _is_default(source, connection.dialect.name)
        if source_default:
            placeholders.append(camera_id)
        if target is not None and not source_default and not _is_default(target, connection.dialect.name):
            raise ValueError(f"camera_id={camera_id}: 两表均有非默认配置，禁止覆盖；请显式解决冲突")
        if target is None or not source_default:
            if target is None:
                next_id += 1
            merged[camera_id] = {**source, "id": target["id"] if target else next_id}
            transferred.append(camera_id)
    after[TARGET] = sorted(merged.values(), key=lambda row: row["id"])
    for row in after[CAMERAS]:
        functions = row["function_config"]
        if functions is None:
            continue
        if not isinstance(functions, dict):
            raise ValueError(f"camera_id={row['id']}: function_config 必须是对象")
        if OLD in functions:
            if NEW in functions:
                raise ValueError(f"camera_id={row['id']}: 两个功能启用标识同时存在")
            source = old_by_camera.get(row["id"])
            value = functions[OLD]
            enabled = value.get("enable") if isinstance(value, dict) else value
            if type(enabled) is not bool or source is None or enabled != bool(source["enable"]):
                raise ValueError(f"camera_id={row['id']}: 功能启用字段与旧配置 enable 不一致")
            functions[NEW] = functions.pop(OLD)
        if NEW in functions:
            value = functions[NEW]
            enabled = value.get("enable") if isinstance(value, dict) else value
            target = merged.get(row["id"])
            if type(enabled) is not bool or target is None or enabled != bool(target["enable"]):
                raise ValueError(f"camera_id={row['id']}: 功能启用字段与合并后配置 enable 冲突")
        if _contains_old(functions):
            raise ValueError(f"camera_id={row['id']}: function_config 含未处理的嵌套引用")
    for row in after[ALARMS]:
        metadata = row["event_metadata"]
        old_metadata = isinstance(metadata, dict) and metadata.get("feature_name") == OLD
        if row["feature_name"] == OLD or old_metadata:
            if row["feature_name"] not in {OLD, NEW} or row["violation_type"] != 5 or row["department"] != "haoda_company":
                raise ValueError(f"alarm_id={row['id']}: 旧功能报警正式类型或事业部缺失/冲突")
            if isinstance(metadata, dict) and metadata.get("department", "haoda_company") != "haoda_company":
                raise ValueError(f"alarm_id={row['id']}: metadata 事业部冲突")
            row["feature_name"] = NEW
            if old_metadata:
                metadata["feature_name"] = NEW
        if _contains_old(metadata):
            raise ValueError(f"alarm_id={row['id']}: 含未处理的历史 metadata 引用")
        if _contains_old(row["feature_name"]):
            raise ValueError(f"alarm_id={row['id']}: 含未处理的功能标识")
        if row["feature_name"] == NEW and (row["violation_type"] != 5 or row["department"] not in SPEC.departments):
            raise ValueError(f"alarm_id={row['id']}: 人员逗留报警归属或类型无效")
    for row in after.get(LINKS, []):
        if row["feature_name"] == OLD:
            if row["department"] != "haoda_company":
                raise ValueError(f"{LINKS} id={row['id']}: 旧功能事业部不匹配")
            row["feature_name"] = NEW
        if _contains_old(row["feature_name"]):
            raise ValueError(f"{LINKS} id={row['id']}: 含未处理的功能标识")
    pairs = [(r["feature_name"], r["department"]) for r in after.get(LINKS, [])]
    if len(pairs) != len(set(pairs)):
        raise ValueError("事业部功能关联转换后冲突，禁止静默去重")
    for row in after.get(FUNCTIONS, []):
        if row["name"] == OLD:
            row["name"] = NEW
            for field in ("config_table_name", "import_path"):
                if isinstance(row[field], str):
                    row[field] = row[field].replace(OLD, NEW)
        if _contains_old(row):
            raise ValueError(f"{FUNCTIONS} id={row['id']}: 含未处理的功能目录引用")
    function_names = [r["name"] for r in after.get(FUNCTIONS, [])]
    if len(function_names) != len(set(function_names)):
        raise ValueError("功能目录转换后重名，禁止覆盖或删除目录记录")
    archives = _scan_other_references(connection, names)
    return {"revision": REVISION, "before": before, "after": after, "report": {
        "rows_before": {name: len(rows) for name, rows in before.items()},
        "transferred_camera_ids": transferred, "source_default_camera_ids": placeholders,
        "changed_rows": {name: sum(row not in before[name] for row in rows) for name, rows in after.items()},
        "unchanged_archive_tables": archives,
    }}


def check_auth_database(path: Path | None):
    """现有认证库只读预检；不初始化、不猜测旧权限列、不修改账号。"""
    from AiVision.departments.department_registry import DEPARTMENT_SPECS

    if path is None or not Path(path).is_absolute() or not Path(path).is_file():
        raise ValueError("必须显式提供已确认的现有认证 SQLite 数据库绝对路径")
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        schema = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        names = [name for kind, name, _ in schema if kind == "table"]
        if "auth_users" not in names:
            raise ValueError("认证数据库缺少 auth_users")
        if any(OLD in (definition or "") or OLD in name for _, name, definition in schema):
            raise ValueError("认证库结构包含旧功能引用，须先确认转换规则；禁止任何写入")
        digest.update(_encode(schema).encode())
        references = []
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            cursor = connection.execute(f"SELECT * FROM {quoted}")
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            # 只持久化摘要，不把姓名、口令、令牌等写进迁移报告或备份。
            digest.update(_encode([name, sorted(hashlib.sha256(repr(row).encode()).hexdigest()
                                              for row in rows)]).encode())
            for index, column in enumerate(columns):
                count = sum(isinstance(row[index], str) and OLD in row[index] for row in rows)
                if count:
                    references.append(f"{name}.{column}: {count} 行")
        if references:
            raise ValueError("认证库含旧功能引用，结构/转换语义尚未确认，禁止任何写入: " + "; ".join(references))
        columns = {r[1] for r in connection.execute('PRAGMA table_info(auth_users)')}
        expected = {"employee_id", "name", "role", "department", "departments", "enabled",
                    "password_hash", "auth_version", "created_at", "updated_at"}
        if columns != expected:
            raise ValueError("认证库权限结构不是预期的完整 auth_users；先核实实际部署版本")
        counts = {"admin": 0, "viewer": 0}
        department_counts = {department: 0 for department in SPEC.departments}
        users = connection.execute("SELECT role, department, departments, enabled, auth_version FROM auth_users").fetchall()
        for role, legacy_department, encoded, enabled, version in users:
            try:
                departments = json.loads(encoded)
            except (ValueError, TypeError):
                raise ValueError("认证库 departments 不是合法 JSON 数组") from None
            if (role not in counts or not isinstance(departments, list) or not departments
                    or any(not isinstance(item, str) for item in departments)
                    or len(set(departments)) != len(departments)
                    or legacy_department != departments[0]
                    or enabled not in (0, 1) or type(version) is not int or version < 1):
                raise ValueError("认证库角色、事业部或账号状态存在冲突；禁止自动修复账号")
            if ((role == "admin" and departments != ["all"])
                    or (role == "viewer" and not set(departments) <= set(DEPARTMENT_SPECS))):
                raise ValueError("认证库权限归属不明确；禁止扩大或缩减事业部权限")
            counts[role] += 1
            if enabled and role == "viewer":
                for department in department_counts:
                    department_counts[department] += department in departments
        return {"auth_database": str(path), "auth_sha256": digest.hexdigest(),
                "auth_users": len(users), "auth_roles": counts,
                "auth_enabled_human_viewers": department_counts,
                "auth_old_feature_references": 0, "auth_converted_rows": 0,
                "permission_storage": "role/departments; unchanged"}


def _verify_auth(path, expected):
    if check_auth_database(path) != expected:
        raise ValueError("认证库路径或数据与预检镜像不一致，保持停写并重新核查")


def _identity(engine):
    url = engine.url
    return hashlib.sha256(_encode([url.drivername, url.host, url.port, url.database]).encode()).hexdigest()


def _save_backup(path, plan):
    encoded = _encode(plan).encode("utf-8")
    envelope = _encode({"sha256": hashlib.sha256(encoded).hexdigest(), "payload": encoded.decode("utf-8")})
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(envelope)
        file.flush()
        os.fsync(file.fileno())


def _load_backup(path, engine):
    envelope = json.loads(Path(path).read_text(encoding="utf-8"))
    if hashlib.sha256(envelope["payload"].encode()).hexdigest() != envelope["sha256"]:
        raise ValueError("备份校验和不一致")
    plan = _decode(envelope["payload"])
    if plan["revision"] != REVISION or plan["database"] != _identity(engine):
        raise ValueError("备份版本或目标数据库不匹配")
    return plan


def _verify(connection, snapshot, *, allow_source_absent=False):
    names = set(inspect(connection).get_table_names())
    for name, expected in snapshot.items():
        if name == SOURCE and name not in names and allow_source_absent:
            continue
        table = _table(connection, name)
        columns = CAMERA_COLUMNS if name == CAMERAS else ALARM_COLUMNS if name == ALARMS else None
        if _rows(connection, table, columns) != expected:
            raise ValueError(f"{name}: 数据与迁移镜像不一致，保持停写并人工核查")


def _write_changes(connection, before, after):
    for name, rows in after.items():
        old = {row["id"]: row for row in before[name]}
        new = {row["id"]: row for row in rows}
        table = _table(connection, name)
        for row_id, row in new.items():
            if row_id not in old:
                connection.execute(table.insert().values(**row))
            elif row != old[row_id]:
                # 只更新实际变化的列；摄像头/报警其他字段和媒体路径不动。
                changes = {key: value for key, value in row.items() if value != old[row_id][key]}
                connection.execute(table.update().where(table.c.id == row_id).values(**changes))
        for row_id in old.keys() - new.keys():
            connection.execute(table.delete().where(table.c.id == row_id))


def run(engine, *, action="check", backup=None, auth_db=None):
    auth = check_auth_database(auth_db)
    with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN" if action in {"check", "verify"} else "BEGIN IMMEDIATE")
        elif connection.dialect.name == "mysql":
            connection.exec_driver_sql("START TRANSACTION READ ONLY" if action in {"check", "verify"} else "START TRANSACTION")
        if action in {"check", "apply"}:
            plan = preflight(connection)
            plan["database"] = _identity(engine)
            plan["auth"] = auth
            plan["report"].update({key: value for key, value in auth.items() if key != "auth_sha256"})
            _verify_auth(auth_db, auth)
            if action == "check":
                connection.rollback()
                return plan["report"]
            if backup is None:
                raise ValueError("apply 必须指定不存在的 --backup 文件")
            _save_backup(backup, plan)
            _verify(connection, plan["before"])
            _write_changes(connection, plan["before"], plan["after"])
            _verify(connection, plan["after"])
            _verify_auth(auth_db, auth)
            connection.commit()
            return {**plan["report"], "result": "applied; source table retained"}
        if backup is None:
            raise ValueError("必须提供本次迁移生成的 --backup")
        plan = _load_backup(backup, engine)
        if plan.get("auth") != auth:
            raise ValueError("认证库路径或数据与迁移备份不匹配；禁止切换数据库继续")
        _check_schema(connection, source_required=action == "restore")
        _verify(connection, plan["after"], allow_source_absent=action == "verify")
        _scan_other_references(connection, set(inspect(connection).get_table_names()))
        _verify_auth(auth_db, auth)
        if action == "restore":
            _write_changes(connection, plan["after"], plan["before"])
            _verify(connection, plan["before"])
            _verify_auth(auth_db, auth)
            connection.commit()
            return {"result": "restored; deploy matching previous code before starting"}
        if action == "drop-old":
            # MySQL DROP TABLE 自动提交：数据镜像、外键、触发器、视图先全部核验。
            _table(connection, SOURCE).drop(connection)
            connection.commit()
            return {"result": "source table removed; retain independent database backup"}
        connection.rollback()
        return {"result": "verified", **plan["report"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    for action in ("check", "apply", "verify", "restore", "drop-old"):
        actions.add_argument("--" + action, dest="action", action="store_const", const=action)
    parser.set_defaults(action="check")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--auth-db", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", help="确认服务及所有数据库写入已停止")
    args = parser.parse_args()
    if args.action in {"apply", "restore", "drop-old"} and not args.offline:
        parser.error("写操作必须显式提供 --offline，并由操作员先停止所有写入")
    url = os.environ.get("HUMAN_MIGRATION_DATABASE_URL")
    if not url:
        parser.error("必须显式设置 HUMAN_MIGRATION_DATABASE_URL；不使用应用连接串作为默认值")
    engine = create_engine(url, echo=False)
    try:
        print(json.dumps(run(engine, action=args.action, backup=args.backup, auth_db=args.auth_db), ensure_ascii=False, indent=2))
    except ValueError as exc:
        parser.exit(1, f"迁移停止: {exc}\n")
    except Exception as exc:
        # 不输出驱动异常全文，其中可能包含连接凭据或绑定参数。
        parser.exit(1, f"迁移停止: {type(exc).__name__}；事务未确认，请只读核验备份镜像后处理。\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
