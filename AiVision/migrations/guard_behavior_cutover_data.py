"""切换数据事务与逐字段核验；不依赖待删除的旧 Guard 代码。"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.orm import Session

from AiVision.cameras.orm import AiCameraConfig
from AiVision.features.guard_behavior.orm import (
    GuardBehaviorAlarmPolicy, GuardBehaviorCameraConfig, GuardBehaviorSite,
    GuardBehaviorSiteCamera, GuardBehaviorSitePolicy,
)
from AiVision.features.guard_behavior.schema import GuardBehaviorSitePolicySchema
from .guard_behavior_cutover_storage import digest

TABLE_CLASSES = (GuardBehaviorSite, GuardBehaviorSiteCamera, GuardBehaviorCameraConfig,
                 GuardBehaviorSitePolicy, GuardBehaviorAlarmPolicy)


def table_rows(connection, names) -> dict:
    """反射并读取明确列出的旧表，生成与旧代码无关的数据快照。"""
    return {name: [dict(row) for row in connection.execute(select(
        Table(name, MetaData(), autoload_with=connection))).mappings()] for name in names}


def comparable(rows: dict) -> str:
    """按表内 ID 和对象键稳定排序，生成快照比较文本。"""
    return json.dumps({key: sorted(value, key=lambda row: row["id"]) for key, value in rows.items()},
                      sort_keys=True, default=str, ensure_ascii=False)


def assert_source(connection, snapshot: dict, *, allow_retired=False) -> None:
    """要求旧表集合及内容仍匹配停机快照，仅显式允许时接受全部旧表已退役。"""
    names = set(snapshot["source"])
    existing = set(inspect(connection).get_table_names()) & names
    if not existing and allow_retired:
        return
    if existing != names or comparable(table_rows(connection, names)) != comparable(snapshot["source"]):
        raise ValueError("旧表与停机迁移快照不一致")


def create_schema(engine) -> None:
    """仅创建明确列出的目标表并校验结构，MySQL 建表不受后续数据回滚保护。"""
    from AiVision.core.schema import assert_table_matches
    # MySQL DDL 不可随数据回滚；只创建明确列出的五张表，空表可安全重跑。
    for model in TABLE_CLASSES:
        model.__table__.create(engine, checkfirst=True)
    with engine.connect() as connection:
        for model in TABLE_CLASSES:
            assert_table_matches(connection, model.__table__)


def _expect(row, values: dict, label: str) -> None:
    """核对目标 ORM 对象的指定字段，不存在或不一致时立即停止。"""
    if row is None or any(getattr(row, key) != value for key, value in values.items()):
        raise ValueError(f"{label} 与迁移快照不一致")


def _site_values(plan):
    """提取迁移计划中站点基础属性，避免无关计划字段进入 ORM。"""
    return {key: plan[key] for key in ("name", "department", "enabled", "sort_order")}


def _alarm_values(alarm):
    """提取已确认的告警类型、冷却及通道绑定字段。"""
    return {key: alarm[key] for key in ("violation_type", "alarm_interval", "sql_enable", "horn_enable",
                                       "horn_id", "horn_event_id", "wechat_enable", "wechat_user")}


def migrate_data(engine, snapshot: dict) -> dict:
    """在一个事务内迁移站点、摄像头关联与策略，并在提交前完整核验。

    已存在目标站点时通过镜像验证识别已完成状态；不覆盖部分迁移数据。
    """
    with Session(engine) as session, session.begin():
        # 已提交但进程未写入结果文件时，依靠快照及完整核验识别完成状态，不重复创建。
        if session.query(GuardBehaviorSite).count():
            return verify_data(session, snapshot)
        if any(session.query(model).count() for model in TABLE_CLASSES[1:]):
            raise ValueError("新表存在不完整数据，拒绝覆盖")
        old_cameras = {row["id"]: row for row in snapshot["source"]["guard_room_camera"]}
        for plan in snapshot["plan"]["sites"]:
            site = GuardBehaviorSite(**_site_values(plan))
            session.add(site)
            session.flush()
            mapping = {}
            for member in plan["cameras"]:
                old = old_cameras[member["old_camera_id"]]
                camera = session.get(AiCameraConfig, member["camera_id"]) if member["camera_id"] else None
                if camera is None:
                    camera = AiCameraConfig(name=old["name"], url=old["rtsp_url"], department=plan["department"],
                                            enable=bool(old["enabled"]), sort_order=old["sort_order"],
                                            shm_name=f"__pending_camera_{uuid4().hex}")
                    session.add(camera)
                    session.flush()
                    camera.shm_name = f"camera_{camera.id}"
                mapping[old["id"]] = camera.id
                session.add(GuardBehaviorSiteCamera(site_id=site.id, camera_id=camera.id,
                                                   enabled=member["enabled"], sort_order=member["sort_order"]))
                config = session.query(GuardBehaviorCameraConfig).filter_by(camera_id=camera.id).one_or_none()
                if config is None:
                    config = GuardBehaviorCameraConfig(camera_id=camera.id)
                    session.add(config)
                config.enable = True
                config.vehicle_roi_pos = (plan["roi"]["normalized"] if old["id"] == plan["roi"]["old_vehicle_camera_id"] else [])
            policy = dict(plan["policy"])
            if policy["vehicle_inspection_enabled"]:
                policy["vehicle_camera_id"] = mapping[plan["roi"]["old_vehicle_camera_id"]]
            policy = GuardBehaviorSitePolicySchema.model_validate(policy).model_dump()
            session.add(GuardBehaviorSitePolicy(site_id=site.id, **policy))
            for alarm in plan["alarms"]:
                session.add(GuardBehaviorAlarmPolicy(site_id=site.id, **_alarm_values(alarm)))
        session.flush()
        return verify_data(session, snapshot)


def verify_data(session: Session, snapshot: dict) -> dict:
    """逐字段核对摄像头复用、成员、ROI 和策略，并验证目标及物理摄像头总数。"""
    old_cameras = {row["id"]: row for row in snapshot["source"]["guard_room_camera"]}
    mappings = []
    for plan in snapshot["plan"]["sites"]:
        site = session.query(GuardBehaviorSite).filter_by(name=plan["name"], department=plan["department"]).one_or_none()
        _expect(site, _site_values(plan), "Site")
        mapping = {}
        for member in plan["cameras"]:
            old = old_cameras[member["old_camera_id"]]
            camera = session.query(AiCameraConfig).filter_by(department=plan["department"], url=old["rtsp_url"]).one_or_none()
            if camera is None:
                raise ValueError("物理 Camera 映射丢失")
            if member["camera_id"] is not None and camera.id != member["camera_id"]:
                raise ValueError("复用 Camera 主键发生变化")
            if member["camera_id"] is None:
                _expect(camera, {"name": old["name"], "enable": bool(old["enabled"]), "sort_order": old["sort_order"],
                                 "shm_name": f"camera_{camera.id}"}, "新增物理 Camera")
                for key in ("fps", "max_restart", "shape"):
                    _expect(camera, {key: AiCameraConfig.__table__.c[key].default.arg}, "Camera 正式默认值")
            binding = session.query(GuardBehaviorSiteCamera).filter_by(camera_id=camera.id).one_or_none()
            _expect(binding, {"site_id": site.id, "enabled": member["enabled"], "sort_order": member["sort_order"]}, "成员")
            config = session.query(GuardBehaviorCameraConfig).filter_by(camera_id=camera.id).one_or_none()
            _expect(config, {"enable": True, "vehicle_roi_pos": plan["roi"]["normalized"]
                            if old["id"] == plan["roi"]["old_vehicle_camera_id"] else []}, "Camera 配置/ROI")
            mapping[old["id"]] = camera.id
        values = dict(plan["policy"])
        if values["vehicle_inspection_enabled"]:
            values["vehicle_camera_id"] = mapping[plan["roi"]["old_vehicle_camera_id"]]
        GuardBehaviorSitePolicySchema.model_validate(values)
        _expect(session.query(GuardBehaviorSitePolicy).filter_by(site_id=site.id).one_or_none(), values, "SitePolicy")
        for alarm in plan["alarms"]:
            _expect(session.query(GuardBehaviorAlarmPolicy).filter_by(site_id=site.id, violation_type=alarm["violation_type"]).one_or_none(),
                    _alarm_values(alarm), "AlarmPolicy")
        mappings.append({"old_site_id": plan["id"], "site_id": site.id, "camera_ids": mapping})
    sites, cameras = len(mappings), len(old_cameras)
    migrated_camera_ids = {camera_id for mapping in mappings for camera_id in mapping["camera_ids"].values()}
    counts = {}
    for model in TABLE_CLASSES:
        query = session.query(model)
        if model is GuardBehaviorCameraConfig:
            # 启动会为其他物理 Camera 补默认配置，迁移核验只统计本次涉及的 Camera。
            query = query.filter(model.camera_id.in_(migrated_camera_ids))
        counts[model.__tablename__] = query.count()
    if list(counts.values()) != [sites, cameras, cameras, sites, sites * 4]:
        raise ValueError("迁移目标数量不一致")
    expected_cameras = snapshot["physical_camera_count"] + sum(
        member["camera_id"] is None for plan in snapshot["plan"]["sites"] for member in plan["cameras"])
    if session.query(AiCameraConfig).count() != expected_cameras:
        raise ValueError("物理 Camera 总数与迁移计划不一致")
    return {"counts": counts, "mappings": mappings, "cameras": cameras}


def verify_archive(snapshot: dict, archive: Path) -> int:
    """核对全部资产摘要以及历史文件条数，返回完整归档的历史记录总数。"""
    for asset in snapshot["assets"]:
        if digest(archive / asset["path"]) != asset["sha256"]:
            raise ValueError("归档资产校验失败")
    count = 0
    for entry in snapshot["plan"]["history"]["files"]:
        relative = Path(entry["path"]).relative_to(snapshot["old_root"])
        path = archive / relative
        if digest(path) != entry["sha256"] or len(json.loads(path.read_text())) != entry["count"]:
            raise ValueError("归档历史数量或内容不一致")
        count += entry["count"]
    return count
