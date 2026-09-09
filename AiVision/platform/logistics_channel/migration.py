"""物流历史兼容迁移；旧物理表保留，运行时仅使用统一 Feature。"""
from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict

from sqlalchemy import Column, Integer, MetaData, String, Table, UniqueConstraint, inspect, or_, select, text
from sqlalchemy.schema import CreateTable

from AiVision.core.db import get_engine, get_session
from AiVision.core.logger import logger
from AiVision.features import all_specs
from AiVision.platform.camera.orm import AiCameraConfig
from .constants import DEFAULT_PERSON_CONFIDENCE_THRESHOLD, LOGISTICS_FEATURES, LOGISTICS_FEATURE_NAME
from .membership_transaction import _MembershipLockSetChanged
from .orm import LogisticsChannel, LogisticsChannelCamera
from .service import LogisticsChannelService, _CameraRef, _PendingNotification


# 仅升级入口认识旧 Feature；业务模块不能再通过 Feature 推导事业部。
LEGACY_FEATURE_DEPARTMENTS = {
    "detect_logistics_single_person": "general_electric",
    "detect_logistics_single_person_electronics_electrician": "electronics_electrician",
    "detect_logistics_single_person_electrical_components": "electrical_components",
    "detect_logistics_single_person_precious_metal_recycling": "precious_metal_recycling",
}
LEGACY_CONFIG_TABLES = {
    "general_electric": "ai_camera_config_detect_logistics_single_person",
    "electronics_electrician": "ai_camera_config_detect_logistics_single_person_ee",
    "electrical_components": "ai_camera_config_detect_logistics_single_person_ec",
    "precious_metal_recycling": "ai_camera_config_detect_logistics_single_person_pmr",
}
_CHANNEL_TABLE = "ai_logistics_channel"
_CHANNEL_UNIQUE_COLUMNS = ("feature_name", "department", "name")
_CHANNEL_UNIQUE_NAME = "uq_logistics_channel_feature_department_name"

# 逐 Camera 的完成标记与配置写入处于同一事务；旧表保留也不会重放旧配置。
_migration_metadata = MetaData()
_camera_migrations = Table(
    "ai_logistics_camera_migration", _migration_metadata,
    Column("camera_id", Integer, primary_key=True),
    Column("source_table", String(128), nullable=False),
)


def _channel_departments(connection) -> list[dict]:
    table = Table(_CHANNEL_TABLE, MetaData(), autoload_with=connection)
    rows = [dict(row) for row in connection.execute(select(table)).mappings()]
    identities = set()
    for row in rows:
        feature = row["feature_name"]
        department = row.get("department")
        if feature not in LEGACY_FEATURE_DEPARTMENTS:
            raise ValueError(f"物流迁移冲突 channel_id={row['id']}: 未知 feature_name={feature}")
        expected = LEGACY_FEATURE_DEPARTMENTS[feature]
        if not department:
            department = expected
        elif department not in LEGACY_CONFIG_TABLES or (
            feature != LOGISTICS_FEATURE_NAME and department != expected
        ):
            raise ValueError(f"物流迁移冲突 channel_id={row['id']}: department={department} 与历史功能不一致")
        row["department"] = department
        identity = (department, row["name"])
        if identity in identities:
            raise ValueError(f"物流迁移冲突: 同一事业部存在同名通道 department={department}, name={row['name']}")
        identities.add(identity)
    return rows


def _prepare_channel_schema(connection) -> None:
    inspector = inspect(connection)
    if not inspector.has_table(_CHANNEL_TABLE):
        return
    # 在 DDL 前先确认每条历史记录都能明确归属。
    rows = _channel_departments(connection)
    columns = {column["name"]: column for column in inspector.get_columns(_CHANNEL_TABLE)}
    unique = inspector.get_unique_constraints(_CHANNEL_TABLE)
    old_unique = [item for item in unique if tuple(item["column_names"]) == ("feature_name", "name")]
    has_unique = any(tuple(item["column_names"]) == _CHANNEL_UNIQUE_COLUMNS for item in unique)
    dialect = connection.dialect.name
    quote = connection.dialect.identifier_preparer.quote
    if "department" not in columns:
        connection.execute(text(f"ALTER TABLE {quote(_CHANNEL_TABLE)} ADD COLUMN department VARCHAR(100)"))
    table = Table(_CHANNEL_TABLE, MetaData(), autoload_with=connection)
    for row in rows:
        # 显式保留 updated_at，避免 MySQL ON UPDATE 时间被迁移刷新。
        values = {"department": row["department"]}
        if "updated_at" in row:
            values["updated_at"] = row["updated_at"]
        connection.execute(table.update().where(table.c.id == row["id"]).values(**values))

    if dialect == "sqlite" and (old_unique or columns.get("department", {}).get("nullable", True)):
        # SQLite 不能 ALTER 内联 UNIQUE。保留原表作为备份，再创建同名业务表；绝不 DROP 表。
        backup = "ai_logistics_channel_before_department"
        if inspect(connection).has_table(backup):
            raise ValueError(f"物流 schema 迁移需要人工检查：备份表 {backup} 已存在")
        for constraint in list(table.constraints):
            if isinstance(constraint, UniqueConstraint) and tuple(column.name for column in constraint.columns) == ("feature_name", "name"):
                table.constraints.remove(constraint)
        if not has_unique:
            table.append_constraint(UniqueConstraint(*_CHANNEL_UNIQUE_COLUMNS, name=_CHANNEL_UNIQUE_NAME))
        table.c.department.nullable = False
        indexes = list(table.indexes)
        connection.execute(text(f"ALTER TABLE {quote(_CHANNEL_TABLE)} RENAME TO {quote(backup)}"))
        connection.execute(CreateTable(table))
        if rows:
            connection.execute(table.insert(), rows)
        for index in indexes:
            connection.execute(text(f"DROP INDEX IF EXISTS {quote(index.name)}"))
            index.create(connection)
    elif dialect in {"mysql", "mariadb"}:
        clauses = [f"DROP INDEX {quote(item['name'])}" for item in old_unique]
        if not has_unique:
            clauses.append(f"ADD CONSTRAINT {quote(_CHANNEL_UNIQUE_NAME)} UNIQUE (feature_name, department, name)")
        if columns.get("department", {}).get("nullable", True):
            clauses.append("MODIFY COLUMN department VARCHAR(100) NOT NULL COMMENT '物流通道所属事业部'")
        if clauses:
            connection.execute(text(f"ALTER TABLE {quote(_CHANNEL_TABLE)} " + ", ".join(clauses)))
    elif old_unique or not has_unique:
        raise ValueError(f"物流 schema 迁移尚不支持数据库方言: {dialect}")

    indexes = inspect(connection).get_indexes(_CHANNEL_TABLE)
    if not any(item["column_names"] == ["department"] for item in indexes):
        connection.execute(text(f"CREATE INDEX ix_ai_logistics_channel_department ON {quote(_CHANNEL_TABLE)} (department)"))
    for row in rows:
        values = {"feature_name": LOGISTICS_FEATURE_NAME}
        if "updated_at" in row:
            values["updated_at"] = row["updated_at"]
        connection.execute(table.update().where(table.c.id == row["id"]).values(**values))


def prepare_logistics_schema(engine=None) -> None:
    """先修补物流专用 schema，避免通用补列逻辑直接向旧表添加必填列。"""
    engine = engine if engine is not None else get_engine()
    with engine.connect() as connection:
        if engine.dialect.name != "sqlite":
            with connection.begin():
                _prepare_channel_schema(connection)
            return
        # legacy_alter_table 防止改名备份表时重写成员表的外键目标。
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
        legacy_alter = connection.exec_driver_sql("PRAGMA legacy_alter_table").scalar()
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.exec_driver_sql("PRAGMA legacy_alter_table=ON")
        connection.commit()
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            _prepare_channel_schema(connection)
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check(ai_logistics_channel_camera)").all() if inspect(connection).has_table("ai_logistics_channel_camera") else []
            if violations:
                raise ValueError("物流 schema 迁移后成员外键校验失败")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.exec_driver_sql(f"PRAGMA legacy_alter_table={int(legacy_alter)}")
            connection.exec_driver_sql(f"PRAGMA foreign_keys={int(foreign_keys)}")
            connection.commit()

@dataclass(frozen=True)
class MigrationSummary:
    """旧数据迁移的结果统计"""
    created: int
    skipped: int
    failed: int
    errors: tuple[str, ...] = ()


def migrate_camera_feature_configs(engine=None) -> MigrationSummary:
    """按 Camera.department 选择唯一旧配置来源，每台 Camera 独立提交。"""
    engine = engine if engine is not None else get_engine()
    _migration_metadata.create_all(engine)
    metadata = MetaData()
    inspector = inspect(engine)
    tables = {
        department: Table(name, metadata, autoload_with=engine)
        for department, name in LEGACY_CONFIG_TABLES.items()
        if inspector.has_table(name)
    }
    canonical = tables.get("general_electric")
    if canonical is None:
        raise ValueError("物流 canonical 配置表尚未创建")
    cameras = Table("ai_camera_config", metadata, autoload_with=engine)
    channels = Table(_CHANNEL_TABLE, metadata, autoload_with=engine)
    members = Table("ai_logistics_channel_camera", metadata, autoload_with=engine)
    candidates = set()
    with engine.connect() as connection:
        for table in tables.values():
            candidates.update(connection.execute(select(table.c.camera_id)).scalars())
    created = skipped = failed = 0
    errors = []
    for camera_id in sorted(candidates):
        try:
            with engine.begin() as connection:
                camera = connection.execute(select(cameras).where(cameras.c.id == camera_id).with_for_update()).mappings().first()
                if camera is None:
                    raise ValueError("Camera 不存在，无法确定配置来源")
                completed = connection.execute(select(_camera_migrations.c.camera_id).where(_camera_migrations.c.camera_id == camera_id)).first()
                if completed:
                    skipped += 1
                    continue
                sources = defaultdict(list)
                for department, table in tables.items():
                    sources[department].extend(connection.execute(
                        select(table).where(table.c.camera_id == camera_id).with_for_update()
                    ).mappings())
                department = camera["department"]
                memberships = connection.execute(
                    select(channels.c.id, channels.c.department)
                    .join(members, members.c.channel_id == channels.c.id)
                    .where(members.c.camera_id == camera_id)
                ).all()
                active = any(row.get("enable") for rows in sources.values() for row in rows)
                if department not in LEGACY_CONFIG_TABLES:
                    ambiguous_department = not department and sum(len(rows) for rows in sources.values()) > 1
                    if active or memberships or ambiguous_department:
                        available = [tables[key].name for key, rows in sources.items() if rows]
                        raise ValueError(f"Camera.department={department!r} 无法确定物流配置来源，候选表={available}")
                    skipped += 1
                    continue
                if len(memberships) > 1 or any(row.department != department for row in memberships):
                    raise ValueError(f"Channel 成员关系冲突，Camera.department={department}, channel_ids={[row.id for row in memberships]}")
                matching = sources[department]
                source_table = tables.get(department, canonical)
                if len(matching) != 1:
                    # 迁移完成标记缺失时，不能把另一个事业部的配置当作正确来源。
                    # 没有旧表的全新数据库只存在 canonical，且不需要合并。
                    fresh_canonical = department != "general_electric" and not any(rows for source_department, rows in sources.items() if source_department != "general_electric") and len(sources["general_electric"]) == 1
                    if not fresh_canonical:
                        raise ValueError(f"department={department} 对应配置来源数量={len(matching)}，停止该 Camera 迁移")
                    matching = sources["general_electric"]
                    source_table = canonical
                source = dict(matching[0])
                extra = set(source) - set(canonical.c.keys())
                if extra:
                    raise ValueError(f"旧配置存在 canonical 未声明字段: {sorted(extra)}，请人工确认")
                existing = sources["general_electric"]
                if len(existing) > 1:
                    raise ValueError("canonical 中存在重复 Camera 配置")
                if source_table.name != canonical.name:
                    values = {name: value for name, value in source.items() if name != "id"}
                    if existing:
                        connection.execute(canonical.update().where(canonical.c.camera_id == camera_id).values(**values))
                    else:
                        connection.execute(canonical.insert().values(**values))
                connection.execute(_camera_migrations.insert().values(camera_id=camera_id, source_table=source_table.name))
                created += 1
        except Exception as exc:
            failed += 1
            message = f"camera_id={camera_id}: {exc}"
            errors.append(message)
            logger.error(f"[LogisticsMigration] Camera 配置迁移失败 {message}")
    return MigrationSummary(created, skipped, failed, tuple(errors))


class LogisticsChannelMigration(LogisticsChannelService):
    def migrate_existing_feature_cameras(self) -> MigrationSummary:
        """历史迁移代码"""
        candidates: list[tuple[str, int]] = []
        read_session = get_session()
        try:
            for feature_name in sorted(LOGISTICS_FEATURES):
                spec = all_specs()[feature_name]
                camera_ids = (
                    read_session.query(spec.orm_class.camera_id)
                    .filter(spec.orm_class.enable.is_(True))
                    .order_by(spec.orm_class.camera_id)
                    .all()
                )
                candidates.extend((feature_name, row[0]) for row in camera_ids)
        finally:
            read_session.close()

        created = skipped = failed = 0
        errors: list[str] = []
        pending_notifications: list[_PendingNotification] = []
        for feature_name, camera_id in candidates:
            try:
                def discover():
                    return self._discover_memberships(camera_ids=(camera_id,))

                def migrate_one(session, discovery):
                    # 迁移只锁 camera/config，之后只插入新 channel；不再获取任何
                    # 已存在 channel 行锁，避免与 channels→cameras 层级形成环。
                    camera = self._lock_migration_camera(session, camera_id)
                    if camera is None:
                        raise ValueError(f"摄像头不存在: {camera_id}")
                    spec = all_specs()[feature_name]
                    cfg = (
                        session.query(spec.orm_class)
                        .filter_by(camera_id=camera_id)
                        .with_for_update()
                        .first()
                    )
                    if cfg is None or not cfg.enable:
                        return None
                    current_members = self._build_membership_lock_query(
                        session,
                        member_ids=discovery.member_ids,
                        camera_ids=discovery.camera_scope,
                    ).all()
                    current_pairs = {
                        (member.id, member.channel_id) for member in current_members
                    }
                    if current_pairs != discovery.expected_pairs:
                        raise _MembershipLockSetChanged()
                    if any(
                        member.feature_name == feature_name
                        for member in discovery.members
                    ):
                        return None
                    department = self._require_department(feature_name, camera.department)
                    name = camera.name
                    collision = (
                        session.query(LogisticsChannel.id)
                        .filter_by(feature_name=feature_name, department=department, name=name)
                        .first()
                    )
                    if collision is not None:
                        name = f"{camera.name}-{camera.id}"
                    channel = LogisticsChannel(
                        name=name,
                        feature_name=feature_name,
                        department=department,
                        confidence_threshold=(
                            cfg.CONF_THRESHOLD
                            if cfg.CONF_THRESHOLD is not None
                            else DEFAULT_PERSON_CONFIDENCE_THRESHOLD
                        ),
                        empty_grace_seconds=cfg.empty_grace_seconds,
                        multi_grace_seconds=cfg.multi_grace_seconds,
                        alarm_interval=cfg.alarm_interval,
                        sql_enable=bool(cfg.sql_enable),
                        horn_enable=bool(cfg.horn_enable),
                        horn_id=cfg.horn_id,
                        horn_event_id=cfg.horn_event_id,
                        wechat_enable=bool(cfg.wechat_enable),
                        wechat_user=cfg.wechat_user,
                    )
                    session.add(channel)
                    session.flush()
                    session.add(LogisticsChannelCamera(
                        channel_id=channel.id,
                        camera_id=camera_id,
                        enabled=True,
                        sort_order=0,
                    ))
                    session.flush()
                    camera_ref = _CameraRef(camera.id, camera.shm_name)
                    return _PendingNotification(
                        channel_id=channel.id,
                        feature_name=feature_name,
                        camera_refs=(camera_ref,),
                        feature_action="enabled",
                    )

                notification = self._run_membership_transaction(discover, migrate_one)
                if notification is None:
                    skipped += 1
                    continue
                created += 1
                pending_notifications.append(notification)
            except Exception as exc:
                failed += 1
                message = f"{feature_name}/camera_id={camera_id}: {exc}"
                errors.append(message)
                logger.warning(f"[LogisticsChannelService] 迁移失败 {message}")
        if pending_notifications:
            self._publish_notifications(pending_notifications)
        return MigrationSummary(created, skipped, failed, tuple(errors))

    @staticmethod
    def _lock_migration_camera(session, camera_id: int):
        """迁移专用例外：锁 camera 后只写新 channel，不获取既有 channel 锁。"""
        return (
            session.query(AiCameraConfig)
            .filter_by(id=camera_id)
            .with_for_update()
            .first()
        )


def migrate_legacy_logistics() -> MigrationSummary:
    """在默认 Feature 配置补齐、缓存初始化和 Runtime 启动之前执行。"""
    result = migrate_camera_feature_configs()
    if result.failed:
        return result
    migrate_channel_alarm_features()
    channels = LogisticsChannelMigration().migrate_existing_feature_cameras()
    return MigrationSummary(
        result.created + channels.created,
        result.skipped + channels.skipped,
        channels.failed,
        channels.errors,
    )


def migrate_channel_alarm_features(engine=None) -> None:
    """保持旧通道告警在统一 Feature 的历史列表和统计中可见。"""
    engine = engine if engine is not None else get_engine()
    from AiVision.platform.violation.orm import AiAlarmEvent

    name = AiAlarmEvent.__tablename__
    if not inspect(engine).has_table(name):
        return
    table = Table(name, MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        channels = Table(_CHANNEL_TABLE, MetaData(), autoload_with=connection)
        channel_departments = {
            str(row.id): row.department
            for row in connection.execute(select(channels.c.id, channels.c.department))
        }
        for feature, department in LEGACY_FEATURE_DEPARTMENTS.items():
            query = select(table).where(
                table.c.subject_type == "logistics_channel", table.c.feature_name == feature,
            )
            if feature == LOGISTICS_FEATURE_NAME:
                query = query.where(or_(table.c.department.is_(None), table.c.department == ""))
            rows = connection.execute(query).mappings().all()
            for row in rows:
                values = {"feature_name": LOGISTICS_FEATURE_NAME}
                if not row["department"]:
                    values["department"] = channel_departments.get(row["subject_id"], department)
                connection.execute(table.update().where(table.c.id == row["id"]).values(**values))
