"""围栏白名单按摄像头独立保存；默认只读检查，停写后显式应用。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text

from .security_fence_authorization_20261022 import _authorization_table, _config_table

STAGING_TABLE = "ai_security_fence_authorization_camera_20261105"
BACKUP_TABLE = "ai_security_fence_authorization_department_20261105"


def _tables():
    """复用正式配置与依赖表，临时表使用相同外键和约束。"""
    from AiVision.features.security_fence.orm import FencePersonAuthorization

    config = _config_table(legacy=False)
    authorization = config.metadata.tables[FencePersonAuthorization.__tablename__]
    staging = authorization.to_metadata(config.metadata, name=STAGING_TABLE)
    return config, authorization, staging


def _camera_rows(connection, config, legacy):
    """把现有事业部权限复制到已配置围栏的摄像头，不给未来加入的摄像头授权。"""
    from AiVision.departments.department_registry import require_department

    cameras = config.metadata.tables["ai_camera_config"]
    persons = config.metadata.tables["ai_face_person"]
    for department in connection.scalars(select(legacy.c.department).distinct()):
        require_department(department)
    missing = connection.execute(select(legacy.c.person_id).select_from(
        legacy.outerjoin(persons, legacy.c.person_id == persons.c.id),
    ).where(persons.c.id.is_(None))).first()
    if missing is not None:
        raise ValueError("围栏白名单引用了不存在的人员，已停止迁移")
    return connection.execute(select(cameras.c.id, legacy.c.person_id, legacy.c.created_at).select_from(
        legacy.join(cameras, legacy.c.department == cameras.c.department)
        .join(config, config.c.camera_id == cameras.c.id),
    )).tuples().all()


def check(engine) -> dict:
    """检查当前结构及待复制数量，不创建表、不修改授权。"""
    from AiVision.core.schema import assert_table_matches

    config, authorization, staging = _tables()
    legacy = _authorization_table()
    with engine.connect() as connection:
        inspector = inspect(connection)
        has_config = inspector.has_table(config.name)
        has_authorization = inspector.has_table(authorization.name)
        has_backup = inspector.has_table(BACKUP_TABLE)
        if has_config:
            assert_table_matches(connection, config)
        source = "missing"
        rows = []
        if has_authorization:
            columns = {column["name"] for column in inspector.get_columns(authorization.name)}
            source = "department" if "department" in columns else "camera"
            assert_table_matches(connection, legacy if source == "department" else authorization)
            if source == "department":
                if not has_config:
                    raise ValueError("围栏配置表不存在，请核查部署数据库")
                if has_backup:
                    raise ValueError("事业部备份表已存在但正式表仍为事业部结构，请保持停写并核查数据库")
                rows = _camera_rows(connection, config, legacy)
            else:
                rows = connection.execute(select(authorization)).tuples().all()
        elif has_backup:
            raise ValueError("围栏授权正式表缺失但备份表存在，请保持停写并核查数据库")
        if inspector.has_table(staging.name):
            if source != "department":
                raise ValueError("存在未完成的围栏临时授权表，请保持停写并核查数据库")
            assert_table_matches(connection, staging)
        counts: dict[str, int] = {}
        for camera_id, _, _ in rows:
            key = str(camera_id)
            counts[key] = counts.get(key, 0) + 1
        return {
            "config_table_present": has_config,
            "authorization_scope": source,
            "needs_migration": source == "department",
            "needs_authorization_table": not has_authorization,
            "camera_authorizations": counts,
            "department_backup_present": has_backup,
        }


def apply(engine) -> dict:
    """完整复制并核验后切换正式表；保留事业部表备份，完成后不再重新继承授权。"""
    from AiVision.core.schema import assert_table_matches

    state = check(engine)
    if state["authorization_scope"] == "camera" or not state["config_table_present"]:
        return {**state, "copied": 0}
    config, authorization, staging = _tables()
    if state["authorization_scope"] == "missing":
        with engine.begin() as connection:
            authorization.create(connection)
            assert_table_matches(connection, authorization)
        return {**check(engine), "copied": 0}
    if engine.dialect.name not in {"mysql", "sqlite"}:
        raise ValueError("围栏白名单迁移仅支持 MySQL 和 SQLite")
    legacy = _authorization_table()
    with engine.begin() as connection:
        original = _camera_rows(connection, config, legacy)
        staging.create(connection, checkfirst=True)
        assert_table_matches(connection, staging)
        # 只重建本版本中间表，正式授权始终保留到完整核验通过。
        connection.execute(staging.delete())
        if original:
            connection.execute(staging.insert(), [
                {"camera_id": camera_id, "person_id": person_id, "created_at": created_at}
                for camera_id, person_id, created_at in original
            ])
        saved = connection.execute(select(staging)).tuples().all()
        if set(saved) != set(original):
            raise ValueError("摄像头授权未完整保存，请保持停写并核查数据库")
    quote = engine.dialect.identifier_preparer.quote
    with engine.begin() as connection:
        if engine.dialect.name == "mysql":
            # MySQL 使用一次原子改名，避免 DDL 隐式提交留下半完成的正式表。
            connection.execute(text(
                f"RENAME TABLE {quote(authorization.name)} TO {quote(BACKUP_TABLE)}, "
                f"{quote(staging.name)} TO {quote(authorization.name)}"
            ))
        else:
            connection.execute(text(f"ALTER TABLE {quote(authorization.name)} RENAME TO {quote(BACKUP_TABLE)}"))
            connection.execute(text(f"ALTER TABLE {quote(staging.name)} RENAME TO {quote(authorization.name)}"))
    result = check(engine)
    if result["needs_migration"] or result["needs_authorization_table"]:
        raise ValueError("围栏摄像头授权结构核验失败，请保持停写并核查数据库")
    return {**result, "copied": len(original)}


def main() -> None:
    """读取部署配置，只有明确声明相关写入已停止时才应用迁移。"""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--apply", action="store_true")
    parser.add_argument("--offline", action="store_true", help="后端及围栏授权写入均已停止")
    args = parser.parse_args()
    if args.apply and not args.offline:
        parser.error("请先停止后端及围栏授权写入，再提供 --apply --offline")
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    from AiVision.core.settings import settings

    engine = create_engine(settings.db.sqlalchemy_url, echo=False)
    action = "迁移" if args.apply else "只读检查"
    try:
        print(json.dumps(apply(engine) if args.apply else check(engine), ensure_ascii=False))
    except ValueError as exc:
        parser.exit(1, f"{action}停止：{exc}\n")
    except Exception as exc:
        hint = "请保持停写并核查数据库。" if args.apply else "请核查脚本依赖和数据库结构。"
        parser.exit(1, f"{action}停止：{type(exc).__name__}；{hint}\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
