"""围栏白名单按事业部共享；默认只读检查，停止相关写入后显式应用。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import Column, JSON, MetaData, create_engine, inspect, select, text


def _config_table(*, legacy: bool):
    """复制正式结构并保留依赖表，使完整外键核验也能覆盖历史配置。"""
    from AiVision.alarms.devices.orm import AiHornConfig  # noqa: F401
    from AiVision.cameras.orm import AiCameraConfig  # noqa: F401
    from AiVision.features.face_recognition.library.orm import FacePerson  # noqa: F401
    from AiVision.features.security_fence.orm import FenceConfigORM

    metadata = MetaData()
    for table in FenceConfigORM.metadata.tables.values():
        table.to_metadata(metadata)
    config = metadata.tables[FenceConfigORM.__tablename__]
    if legacy:
        config.append_column(Column("allowed_person_ids", JSON, nullable=False))
    return config


def _legacy_authorizations(connection, config) -> tuple[set[tuple[str, int]], int]:
    """按摄像头归属合并已明确添加的人员，拒绝无法确定归属或不存在的人员。"""
    from AiVision.cameras.orm import AiCameraConfig
    from AiVision.departments.department_registry import require_department
    from AiVision.features.face_recognition.library.orm import FacePerson

    cameras = AiCameraConfig.__table__
    rows = connection.execute(select(
        config.c.allowed_person_ids, cameras.c.department,
    ).select_from(config.outerjoin(cameras, config.c.camera_id == cameras.c.id)))
    pairs: set[tuple[str, int]] = set()
    populated = 0
    for ids, department in rows:
        if not isinstance(ids, list) or any(type(person_id) is not int or person_id < 1 for person_id in ids):
            raise ValueError("摄像头白名单必须是有效的正整数人员 ID 列表")
        if not ids:
            continue
        require_department(department)
        populated += 1
        pairs.update((department, person_id) for person_id in ids)
    requested = {person_id for _, person_id in pairs}
    if requested:
        found = set(connection.scalars(select(FacePerson.id).where(FacePerson.id.in_(requested))))
        if requested != found:
            raise ValueError(f"摄像头白名单引用了 {len(requested - found)} 个不存在的人员，已停止迁移")
    return pairs, populated


def check(engine) -> dict:
    """检查历史结构和按事业部合并的授权数量，不改变数据库。"""
    from AiVision.core.schema import assert_table_matches
    from AiVision.features.security_fence.orm import FenceConfigORM, FencePersonAuthorization

    with engine.connect() as connection:
        inspector = inspect(connection)
        has_config = inspector.has_table(FenceConfigORM.__tablename__)
        has_authorizations = inspector.has_table(FencePersonAuthorization.__tablename__)
        if has_authorizations:
            assert_table_matches(connection, FencePersonAuthorization.__table__)
        legacy = False
        pairs, populated = set(), 0
        if has_config:
            legacy = "allowed_person_ids" in {column["name"] for column in inspector.get_columns(FenceConfigORM.__tablename__)}
            config = _config_table(legacy=legacy)
            assert_table_matches(connection, config)
            if legacy:
                pairs, populated = _legacy_authorizations(connection, config)
        return {
            "config_table_present": has_config,
            "needs_migration": legacy,
            "needs_authorization_table": not has_authorizations,
            "camera_whitelists": populated,
            "department_authorizations": {
                department: sum(scope == department for scope, _ in pairs)
                for department in sorted({scope for scope, _ in pairs})
            },
        }


def apply(engine) -> dict:
    """先提交并核对事业部授权，再移除摄像头名单；可在中断后重新执行。

    MySQL DDL 会隐式提交。删除旧列前必须确认全部人员已保存；迁移完成后
    再次执行不会恢复已被管理员取消的授权。空库由应用启动创建正式结构。
    """
    from AiVision.core.schema import assert_table_matches
    from AiVision.features.security_fence.orm import FenceConfigORM, FencePersonAuthorization

    state = check(engine)
    if not state["config_table_present"]:
        return {**state, "copied": 0}
    authorizations = FencePersonAuthorization.__table__
    with engine.begin() as connection:
        authorizations.create(connection, checkfirst=True)
        assert_table_matches(connection, authorizations)
    copied = 0
    if state["needs_migration"]:
        config = _config_table(legacy=True)
        with engine.begin() as connection:
            original, _ = _legacy_authorizations(connection, config)
            existing = set(connection.execute(select(authorizations.c.department, authorizations.c.person_id)).tuples())
            missing = original - existing
            if missing:
                connection.execute(authorizations.insert(), [
                    {"department": department, "person_id": person_id}
                    for department, person_id in sorted(missing)
                ])
            saved = set(connection.execute(select(authorizations.c.department, authorizations.c.person_id)).tuples())
            if not original <= saved:
                raise ValueError("摄像头名单未完整保存为事业部授权，请保持停写并核查数据库")
            copied = len(missing)
        quote = engine.dialect.identifier_preparer.quote
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {quote(FenceConfigORM.__tablename__)} DROP COLUMN allowed_person_ids"))
    result = check(engine)
    if result["needs_migration"] or result["needs_authorization_table"]:
        raise ValueError("围栏白名单结构核验失败，请保持停写并核查数据库")
    return {**result, "copied": copied}


def main() -> None:
    """读取部署配置，只有明确声明停止相关写入时才应用迁移。"""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--apply", action="store_true")
    parser.add_argument("--offline", action="store_true", help="后端及围栏配置、授权写入均已停止")
    args = parser.parse_args()
    if args.apply and not args.offline:
        parser.error("请先停止后端及围栏相关写入，再提供 --apply --offline")
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    from AiVision.core.settings import settings

    engine = create_engine(settings.db.sqlalchemy_url, echo=False)
    try:
        print(json.dumps(apply(engine) if args.apply else check(engine), ensure_ascii=False))
    except ValueError as exc:
        parser.exit(1, f"迁移停止：{exc}\n")
    except Exception as exc:
        parser.exit(1, f"迁移停止：{type(exc).__name__}；请保持停写并核查数据库。\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
