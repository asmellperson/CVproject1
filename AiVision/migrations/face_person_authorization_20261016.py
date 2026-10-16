"""人脸识别白名单按事业部隔离；默认只读检查，停写后显式应用。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import Boolean, Column, MetaData, create_engine, func, inspect, select, text


def _person_table(*, legacy: bool):
    """按实际版本核对完整人员表，避免在未知结构上执行数据转换。"""
    from AiVision.features.face_recognition.library.orm import FacePerson

    table = FacePerson.__table__.to_metadata(MetaData())
    if legacy:
        table.append_column(Column("is_allowed", Boolean, nullable=False, server_default=text("0")))
    return table


def check(engine) -> dict:
    """只读检查人员表及授权表，不推断原名单属于哪个事业部。"""
    from AiVision.core.schema import assert_table_matches
    from AiVision.features.face_recognition.library.orm import FacePerson, FacePersonAuthorization

    with engine.connect() as connection:
        inspector = inspect(connection)
        legacy = "is_allowed" in {column["name"] for column in inspector.get_columns(FacePerson.__tablename__)}
        persons = _person_table(legacy=legacy)
        assert_table_matches(connection, persons)
        has_authorizations = inspector.has_table(FacePersonAuthorization.__tablename__)
        if has_authorizations:
            assert_table_matches(connection, FacePersonAuthorization.__table__)
        return {
            "needs_migration": legacy,
            "needs_authorization_table": not has_authorizations,
            "legacy_allowed_persons": connection.scalar(select(func.count()).select_from(persons).where(
                persons.c.is_allowed.is_(True),
            )) if legacy else 0,
        }


def apply(engine, *, legacy_department: str) -> dict:
    """将原名单仅归入明确指定的事业部，先提交并核对授权，再移除全局标记。

    MySQL 的 DDL 会隐式提交，因此授权复制必须先完整提交。中途失败时保留
    已复制授权和原标记，重新执行可继续；完成后不会重新恢复已取消的授权。
    """
    from AiVision.core.schema import assert_table_matches
    from AiVision.departments.department_registry import require_department
    from AiVision.features.face_recognition.library.orm import FacePersonAuthorization

    require_department(legacy_department)
    state = check(engine)
    authorizations = FacePersonAuthorization.__table__
    with engine.begin() as connection:
        authorizations.create(connection, checkfirst=True)
        assert_table_matches(connection, authorizations)
    copied = 0
    if state["needs_migration"]:
        persons = _person_table(legacy=True)
        with engine.begin() as connection:
            original = set(connection.scalars(select(persons.c.id).where(persons.c.is_allowed.is_(True))))
            existing = set(connection.scalars(select(authorizations.c.person_id).where(
                authorizations.c.department == legacy_department,
            )))
            missing = original - existing
            if missing:
                connection.execute(authorizations.insert(), [
                    {"department": legacy_department, "person_id": person_id} for person_id in sorted(missing)
                ])
            saved = set(connection.scalars(select(authorizations.c.person_id).where(
                authorizations.c.department == legacy_department,
            )))
            if not original <= saved:
                raise ValueError("原白名单未完整保存，请保持停写并核查数据库")
            copied = len(missing)
        # 仅在授权事务成功提交后执行 DDL；不改人员资料、特征或识别记录。
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE ai_face_person DROP COLUMN is_allowed"))
    result = check(engine)
    if result["needs_migration"] or result["needs_authorization_table"]:
        raise ValueError("白名单结构核验失败，请保持停写并核查数据库")
    return {**result, "legacy_department": legacy_department, "copied": copied}


def main() -> None:
    """读取当前部署配置；写入必须明确名单归属，并声明服务及数据库写入已停止。"""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--apply", action="store_true")
    parser.add_argument("--legacy-department", help="原有白名单唯一归属的事业部编码")
    parser.add_argument("--offline", action="store_true", help="服务及其他数据库写入均已停止")
    args = parser.parse_args()
    if args.apply and (not args.offline or not args.legacy_department):
        parser.error("应用前必须停止服务，并提供 --offline 和 --legacy-department")
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from AiVision.core.settings import settings

    # 迁移检查只连接现有库，不触发应用的自动建库逻辑。
    engine = create_engine(settings.db.sqlalchemy_url, echo=False)
    try:
        result = apply(engine, legacy_department=args.legacy_department) if args.apply else check(engine)
        print(json.dumps(result, ensure_ascii=False))
    except ValueError as exc:
        parser.exit(1, f"迁移停止：{exc}\n")
    except Exception as exc:
        # 数据库异常可能包含连接信息或人员参数，不直接打印异常原文。
        parser.exit(1, f"迁移停止：{type(exc).__name__}；请保持停写并核查数据库。\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
