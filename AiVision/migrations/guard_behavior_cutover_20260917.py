"""Guard 一次性正式迁移；默认只读，写入前必须停机并完成备份。"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values
from sqlalchemy import MetaData, Table, URL, create_engine, inspect, select
from sqlalchemy.engine import make_url
import yaml

from AiVision.features.guard_behavior.constants import (
    ALARM_INTERVAL_DEFAULTS, ALARM_POLICY_DEFAULTS, MAX_CAMERAS_PER_SITE, SITE_POLICY_DEFAULTS,
)

REVISION = "guard_behavior_cutover_20260917"
ROOT = Path(__file__).resolve().parents[2]
OLD_ROOT = ROOT / "AiVision/integrations/guard_room"
OLD_TABLES = ("guard_room_site", "guard_room_camera", "guard_room_site_config")
NEW_TABLES = (
    "ai_guard_behavior_site", "ai_guard_behavior_site_camera", "ai_camera_config_guard_behavior",
    "ai_guard_behavior_site_policy", "ai_guard_behavior_alarm_policy",
)
SECTIONS = dict(zip(
    ("video", "models", "room", "rules", "classes", "runtime", "wechat"),
    ("VideoConfig", "ModelConfig", "RoomConfig", "RuleConfig", "ClassConfig", "RuntimeConfig", "WeChatConfig"),
))
MODEL_FIELDS = {
    "detector_model": ("yolo_guard_person_phone", "yolo"),
    "uniform_cls_model": ("guard_uniform", "timm_classifier"),
    "pose_model_task": ("yolo_guard_pose", "yolo_pose"),
    "vehicle_detector_model": ("yolo_vehicle", "yolo"),
}
POLICY_FIELDS = {
    "models.detector_conf": "person_confidence_threshold",
    "models.phone_conf": "phone_confidence_threshold",
    "models.uniform_cls_conf": "uniform_confidence_threshold",
    "models.vehicle_conf": "vehicle_confidence_threshold",
    "models.detector_iou": "model_iou_threshold",
    "models.detector_imgsz": "person_phone_imgsz",
    **{f"models.{name}": name for name in ("phone_crop_imgsz", "pose_imgsz", "vehicle_imgsz")},
    **{f"rules.{name}": name for name in (
        "guard_hold_seconds", "absent_alarm_seconds", "phone_seconds", "phone_window_seconds",
        "phone_min_hits_in_window", "phone_grace_seconds", "phone_near_person_px", "phone_near_head_px",
        "prone_sleep_seconds", "static_motion_threshold", "prone_head_down_ratio_threshold",
        "prone_bbox_height_ratio_threshold", "prone_consecutive_frames", "state_ttl_seconds",
        "vehicle_occlusion_seconds", "vehicle_near_px", "vehicle_exit_direction",
        "vehicle_direction_min_delta_ratio", "vehicle_reassociate_seconds",
    )},
    "runtime.enable_vehicle_unattended": "vehicle_inspection_enabled",
    "runtime.vehicle_camera_id": "vehicle_camera_id",
}
ALARM_FIELDS = {
    8: ("alarm_cooldown_absent", "enable_absent", "guard_absent"),
    9: ("alarm_cooldown_phone", "enable_phone", "guard_phone_use"),
    10: ("alarm_cooldown_prone_sleep", "enable_prone_sleep", "guard_prone_sleep"),
    11: ("alarm_cooldown_vehicle_unattended", None, "guard_vehicle_inspection_missing"),
}
DELETED_FIELDS = {
    "video": "save_annotated_video annotated_video_fps reconnect_seconds jpeg_quality camera_buffer_size",
    "models": "phone_full_frame_imgsz uniform_cls_imgsz use_half device tracker",
    "room": "frame_width frame_height",
    "rules": "absent_seconds dual_sync_seconds",
    "classes": "person play_phone vehicle_bicycle vehicle_car vehicle_motorcycle",
    "runtime": "show_window debug draw_debug max_alarm_history infer_max_workers share_phone_detector share_pose_estimator phone_detect_mode",
    "wechat": "camera_name",
}
PUBLIC_FIELDS = {
    "video.output_dir": "公共 Evidence 存储；旧文件保留待归档",
    "video.alarm_media_retention_days": "公共 Evidence 保留天数",
    "video.alarm_media_max_gb": "公共 Evidence 容量限制",
    "video.alarm_media_cleanup_interval_minutes": "公共 Evidence 清理间隔",
    "wechat.clip_seconds": "公共 Evidence pre/post 配置，不直接换算",
    "wechat.corpid": "全局 WECHAT_CORP_ID",
    "wechat.corpsecret": "全局 WECHAT_CORP_SECRET",
    "wechat.agentid": "全局 WECHAT_AGENT_ID",
}


@dataclass
class PrecheckReport:
    blockers: list[dict] = field(default_factory=list)
    planned_actions: list[dict] = field(default_factory=list)
    sites: list[dict] = field(default_factory=list)
    models: list[dict] = field(default_factory=list)
    history: dict = field(default_factory=dict)
    storage: dict = field(default_factory=dict)
    field_dispositions: list[dict] = field(default_factory=list)

    def block(self, code: str, detail: str, **identity) -> None:
        self.blockers.append({"code": code, "detail": detail, **identity})

    def payload(self) -> dict:
        return {
            "revision": REVISION, "mode": "preflight", "read_only": True,
            "result": "PRECHECK BLOCKED" if self.blockers else "PRECHECK PASS",
            "site_count": len(self.sites),
            "departments": dict(Counter(site["department"] for site in self.sites)),
            "sites": self.sites, "models": self.models, "history": self.history,
            "storage": self.storage, "field_dispositions": self.field_dispositions,
            "blockers_total": len(self.blockers), "blockers": self.blockers,
            "planned_actions": self.planned_actions,
        }


def redact_url(value: str) -> str:
    """报告不输出 URL 中的账号、密码或查询参数；精确匹配在脱敏前完成。"""
    parts = urlsplit(value)
    authority = parts.netloc.rsplit("@", 1)[-1]
    if "@" in parts.netloc:
        authority = "***@" + authority
    return urlunsplit((parts.scheme, authority, parts.path, "", ""))


def database_location(url) -> str:
    value = make_url(url)
    return str(value.set(username=None, password=None, query={})) if value.get_backend_name() == "sqlite" else (
        f"{value.get_backend_name()}://{value.host}:{value.port or 3306}/{value.database}"
    )


@contextmanager
def read_only_connection(url):
    """数据库自身拒绝写入；不调用可能 create_all 的业务初始化入口。"""
    url = make_url(url)
    if url.get_backend_name() == "sqlite":
        path = Path(url.database or "").resolve(strict=True)
        url = URL.create("sqlite", database=f"file:{path.as_posix()}", query={"mode": "ro", "uri": "true"})
        connect_args = {}
    elif url.get_backend_name() == "mysql":
        connect_args = {"connect_timeout": 5, "read_timeout": 15}
    else:
        raise ValueError("预检仅支持 MySQL 和本地 SQLite 文件")
    engine = create_engine(url, echo=False, connect_args=connect_args)
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("PRAGMA query_only=ON")
                connection.exec_driver_sql("BEGIN")
            else:
                connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            try:
                yield connection
            finally:
                connection.rollback()
    finally:
        engine.dispose()


def read_tables(connection, names: tuple[str, ...], report: PrecheckReport, label: str) -> dict:
    existing = set(inspect(connection).get_table_names())
    missing = sorted(set(names) - existing)
    required_missing = sorted(set(missing) - set(NEW_TABLES))
    if required_missing:
        report.block("missing_tables", f"{label}缺少源表或物理 Camera 表", tables=required_missing)
    if set(missing) & set(NEW_TABLES):
        report.planned_actions.append({"action": "planned_schema_creation", "tables": sorted(set(missing) & set(NEW_TABLES))})
    rows = {}
    for name in names:
        rows[name] = []
        if name in existing:
            table = Table(name, MetaData(), autoload_with=connection)
            rows[name] = [dict(row) for row in connection.execute(select(table)).mappings()]
    report.storage[label] = {"tables": sorted(existing & set(names)), "missing_tables": missing}
    return rows


# 固定迁移源版本的字段清单；旧目录删除后仍能独立核验备份。
FIELD_CATALOG = {'video': ['source',
           'source_cam1',
           'source_cam2',
           'source_cam3',
           'process_every_n_frames',
           'output_dir',
           'save_annotated_video',
           'annotated_video_fps',
           'reconnect_seconds',
           'jpeg_quality',
           'camera_buffer_size',
           'alarm_media_retention_days',
           'alarm_media_max_gb',
           'alarm_media_cleanup_interval_minutes',
           'source_cam4',
           'source_cam5',
           'source_cam6',
           'source_cam7',
           'source_cam8',
           'source_cam9'],
 'models': ['detector_model',
            'vehicle_detector_model',
            'uniform_cls_model',
            'pose_model_task',
            'detector_conf',
            'phone_conf',
            'vehicle_conf',
            'detector_iou',
            'detector_imgsz',
            'vehicle_imgsz',
            'phone_crop_imgsz',
            'phone_full_frame_imgsz',
            'pose_imgsz',
            'use_half',
            'tracker',
            'device',
            'uniform_cls_imgsz',
            'uniform_cls_conf'],
 'room': ['frame_width', 'frame_height'],
 'rules': ['absent_seconds',
           'phone_seconds',
           'prone_sleep_seconds',
           'vehicle_occlusion_seconds',
           'phone_near_person_px',
           'phone_near_head_px',
           'vehicle_near_px',
           'vehicle_roi',
           'vehicle_exit_direction',
           'vehicle_direction_min_delta_ratio',
           'vehicle_reassociate_seconds',
           'static_motion_threshold',
           'prone_head_down_ratio_threshold',
           'prone_bbox_height_ratio_threshold',
           'prone_consecutive_frames',
           'state_ttl_seconds',
           'phone_window_seconds',
           'phone_min_hits_in_window',
           'phone_grace_seconds',
           'guard_hold_seconds',
           'dual_sync_seconds',
           'absent_alarm_seconds',
           'alarm_cooldown_absent',
           'alarm_cooldown_phone',
           'alarm_cooldown_prone_sleep',
           'alarm_cooldown_vehicle_unattended'],
 'classes': ['person', 'play_phone', 'vehicle_bicycle', 'vehicle_car', 'vehicle_motorcycle'],
 'runtime': ['show_window',
             'debug',
             'draw_debug',
             'max_alarm_history',
             'infer_max_workers',
             'share_phone_detector',
             'share_pose_estimator',
             'phone_detect_mode',
             'enable_vehicle_unattended',
             'vehicle_camera_id'],
 'wechat': ['enable',
            'corpid',
            'corpsecret',
            'agentid',
            'alarm_user',
            'camera_name',
            'clip_seconds',
            'enable_phone',
            'enable_absent',
            'enable_prone_sleep']}


def field_catalog() -> dict[str, list[str]]:
    return {key: list(values) for key, values in FIELD_CATALOG.items()}


def dispositions(catalog: dict[str, list[str]], report: PrecheckReport) -> None:
    known = {key: ("迁移", f"SitePolicy.{target}") for key, target in POLICY_FIELDS.items()}
    known.update({f"models.{key}": ("迁移", f"公共 model_paths.yaml: {name}，仅列计划，须确认本机路径")
                  for key, (name, _) in MODEL_FIELDS.items()})
    known.update({key: ("使用新默认值", target) for key, target in PUBLIC_FIELDS.items()})
    known.update({f"{section}.{key}": ("删除", "不进入新配置合同")
                  for section, keys in DELETED_FIELDS.items() for key in keys.split()})
    known.update({f"video.{key}": ("迁移", "AiCameraConfig；以旧 Camera 表为准，不使用 YAML 覆盖")
                  for key in ("source", *(f"source_cam{i}" for i in range(1, 10)))})
    known["video.process_every_n_frames"] = ("使用新默认值", f"cap_interval={SITE_POLICY_DEFAULTS['cap_interval']} 秒；帧数不是秒")
    known["rules.vehicle_roi"] = ("迁移", "指定 Camera.vehicle_roi_pos，必要时仅在迁移中归一化")
    for alarm_id, (cooldown, switch, _) in ALARM_FIELDS.items():
        known[f"rules.{cooldown}"] = ("迁移", f"AlarmPolicy[{alarm_id}].alarm_interval")
        if switch:
            known[f"wechat.{switch}"] = ("迁移", f"AlarmPolicy[{alarm_id}].wechat_enable 与总开关相与")
    known["wechat.enable"] = ("迁移", "四类 AlarmPolicy.wechat_enable 总开关；车辆没有旧独立开关")
    known["wechat.alarm_user"] = ("迁移", "四类 AlarmPolicy.wechat_user")
    for key in ("frame_width", "frame_height"):
        known[f"room.{key}"] = ("删除", "仅供一次性像素 ROI 转换，转换后不进入新配置")
    for section, keys in catalog.items():
        for key in keys:
            full = f"{section}.{key}"
            action, target = known.get(full, ("未分类", "需人工确认"))
            report.field_dispositions.append({"field": full, "action": action, "target": target})
            if action == "未分类":
                report.block("unclassified_field", "旧字段尚无处置方案", field=full)


def audit_extra_tables(connection, report: PrecheckReport) -> None:
    """不将未知旧表默认为可删除对象，尤其不能遗漏数据库中的历史记录。"""
    names = sorted(name for name in inspect(connection).get_table_names()
                   if name.startswith("guard_room") and name not in OLD_TABLES)
    for name in names:
        report.block("unclassified_old_table", "发现未分类旧表，禁止删除；需核对是否保存历史", table=name)


def convert_roi(value, room: dict) -> tuple[list, str]:
    from AiVision.features._shared.roi import ROI_ADAPTER
    if not isinstance(value, list):
        raise ValueError("ROI 必须为点列表")
    for point in value:
        if not isinstance(point, list) or len(point) != 2 or any(
            type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in point
        ):
            raise ValueError("ROI 含非数值、负值或错误点结构")
    if all(v <= 1 for point in value for v in point):
        return ROI_ADAPTER.validate_python(value), "normalized"
    width, height = room.get("frame_width"), room.get("frame_height")
    if any(type(v) is not int or v <= 0 for v in (width, height)):
        raise ValueError("像素 ROI 缺少明确、有效的旧画面宽高")
    normalized = [[x / width, y / height] for x, y in value]
    return ROI_ADAPTER.validate_python(normalized), "pixel_converted_with_explicit_room_dimensions"


def plan_cameras(site: dict, cameras: list[dict], target: dict, report: PrecheckReport, claimed: dict) -> list[dict]:
    result = []
    if len(cameras) > MAX_CAMERAS_PER_SITE:
        report.block("camera_limit", "Site Camera 超过 9 路", site_id=site["id"])
    for camera in cameras:
        raw_url = camera["rtsp_url"]
        source_key = (site["department"], raw_url)
        if source_key in claimed:
            report.block("camera_source_duplicated", "旧成员重复引用同一事业部 RTSP", old_camera_id=camera["id"])
        claimed[source_key] = camera["id"]
        candidates = [row for row in target["ai_camera_config"]
                      if row["department"] == site["department"] and row["url"] == raw_url]
        item = {"old_camera_id": camera["id"], "name": camera["name"], "enabled": bool(camera["enabled"]),
                "sort_order": camera["sort_order"], "rtsp": redact_url(raw_url),
                "rtsp_sha256": hashlib.sha256(raw_url.encode()).hexdigest(),
                "candidate_ids": [row["id"] for row in candidates], "camera_id": None}
        if not raw_url or not raw_url.startswith("rtsp://"):
            report.block("invalid_camera_source", "Camera 不是明确 RTSP 源", camera_id=camera["id"])
        if not candidates:
            item["action"] = "planned_camera_creation"
            report.planned_actions.append({"action": item["action"], "old_camera_id": camera["id"]})
        elif len(candidates) > 1:
            item["action"] = "多重匹配，禁止猜测"
            report.block("camera_ambiguous", item["action"], site_id=site["id"],
                         old_camera_id=camera["id"], candidates=item["candidate_ids"])
        else:
            found = candidates[0]
            item.update(action="复用", camera_id=found["id"], platform_name=found["name"],
                        physical_enabled=bool(found["enable"]), fps=found["fps"])
            if found["id"] in claimed:
                report.block("camera_claimed_twice", "同一物理 Camera 被多个旧成员引用", camera_id=found["id"])
            claimed[found["id"]] = site["id"]
            if any(row["camera_id"] == found["id"] for row in target["ai_guard_behavior_site_camera"]):
                report.block("existing_membership", "目标 Camera 已有 Guard 绑定，禁止覆盖或隐式移动", camera_id=found["id"])
        item["name_conflicts"] = [row["id"] for row in target["ai_camera_config"]
                                  if row["name"] == camera["name"] and row not in candidates]
        item["other_department_same_rtsp"] = [row["id"] for row in target["ai_camera_config"]
                                              if row["url"] == raw_url and row["department"] != site["department"]]
        if item["other_department_same_rtsp"]:
            report.block("camera_department_conflict", "同一完整 RTSP 出现在其他事业部，须人工核对归属", old_camera_id=camera["id"],
                         candidates=item["other_department_same_rtsp"])
        if item["name_conflicts"] and not candidates:
            report.block("camera_name_conflict", "需要创建的 Camera 名称已被平台占用", old_camera_id=camera["id"],
                         candidates=item["name_conflicts"])
        result.append(item)
    return result


def plan_config(site: dict, config: dict, members: list[dict], catalog: dict, report: PrecheckReport, env: dict) -> dict:
    from pydantic import ValidationError
    from AiVision.features.guard_behavior.schema import GuardBehaviorSitePolicySchema, GuardBehaviorSitePolicyUpdate, GuardBehaviorRuntimeAlarmPolicy
    sections = {}
    for section in SECTIONS:
        raw = config.get(f"{section}_json")
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            report.block("invalid_section", "配置 JSON 缺失或不是对象", site_id=site["id"], section=section)
            raw = {}
        sections[section] = raw
        for key in raw:
            if key not in catalog[section] and not (section == "video" and key in {f"source_cam{i}" for i in range(1, 10)}):
                report.block("unknown_config_key", "实际配置含未分类字段", site_id=site["id"], field=f"{section}.{key}")
    policy = dict(SITE_POLICY_DEFAULTS)
    defaults = set(policy)
    for old, new in POLICY_FIELDS.items():
        section, key = old.split(".")
        if key in sections[section] and new != "vehicle_camera_id":
            policy[new] = sections[section][key]
            defaults.discard(new)
    # camN 在旧服务中是“已启用成员按 sort_order/id 排序”的位置，不是旧数据库主键。
    selected = sections["runtime"].get("vehicle_camera_id")
    active_members = [member for member in members if member["enabled"]]
    slot_map = {f"cam{i}": member for i, member in enumerate(active_members, 1)}
    vehicle_member = slot_map.get(selected) if isinstance(selected, str) else None
    if policy["vehicle_inspection_enabled"]:
        if not sections["models"].get("vehicle_detector_model"):
            report.planned_actions.append({"action": "use_global_vehicle_model", "site_id": site["id"]})
        if vehicle_member is None or (vehicle_member["camera_id"] is None and vehicle_member.get("action") != "planned_camera_creation"):
            report.block("vehicle_camera_unresolved", "车辆 Camera 槽位无法映射至平台 ID", site_id=site["id"], old_slot=selected)
        else:
            policy["vehicle_camera_id"] = vehicle_member["camera_id"]
            defaults.discard("vehicle_camera_id")
    roi = {"original": sections["rules"].get("vehicle_roi", []), "normalized": None,
           "old_vehicle_slot": selected, "camera_id": vehicle_member["camera_id"] if vehicle_member else None,
           "old_vehicle_camera_id": vehicle_member["old_camera_id"] if vehicle_member else None,
           "dimensions": {key: sections["room"].get(key) for key in ("frame_width", "frame_height")}}
    try:
        roi["normalized"], roi["conversion"] = convert_roi(roi["original"], sections["room"])
        if roi["original"] and (vehicle_member is None or (vehicle_member["camera_id"] is None and vehicle_member.get("action") != "planned_camera_creation")):
            report.block("roi_camera_unresolved", "非空 ROI 无法归属至明确平台 Camera", site_id=site["id"])
    except ValueError:
        report.block("invalid_roi", "ROI 格式、面积、范围或像素宽高无效，禁止猜测转换", site_id=site["id"])
    try:
        schema = GuardBehaviorSitePolicyUpdate if vehicle_member and vehicle_member.get("action") == "planned_camera_creation" else GuardBehaviorSitePolicySchema
        schema.model_validate(policy)
    except ValidationError as exc:
        report.block("invalid_policy", "迁移策略不满足新 Schema", site_id=site["id"],
                     fields=[".".join(map(str, error["loc"])) or "vehicle_camera_id/vehicle_inspection_enabled" for error in exc.errors()])
    alarms = []
    wechat = sections["wechat"]
    for alarm_id, (interval, switch, event) in ALARM_FIELDS.items():
        value = {**ALARM_POLICY_DEFAULTS, "violation_type": alarm_id,
                 "alarm_interval": sections["rules"].get(interval, ALARM_INTERVAL_DEFAULTS[alarm_id]),
                 "wechat_enable": wechat.get("enable", False) and (wechat.get(switch, True) if switch else True),
                 "wechat_user": wechat.get("alarm_user", "")}
        try:
            GuardBehaviorRuntimeAlarmPolicy.model_validate(value)
        except ValidationError:
            report.block("invalid_alarm_policy", "报警策略不满足新 Schema", site_id=site["id"], violation_type=alarm_id)
        alarms.append({**value, "event_type": event, "interval_source": "迁移" if interval in sections["rules"] else "使用新默认值",
                       "sql_horn_source": "使用新默认值；旧文件历史不等于 SQL 开关"})
    credential_checks = {}
    for key, env_key in (("corpid", "WECHAT_CORP_ID"), ("corpsecret", "WECHAT_CORP_SECRET"), ("agentid", "WECHAT_AGENT_ID")):
        credential_checks[key] = bool(env.get(env_key)) and str(wechat.get(key, "")) == str(env.get(env_key))
    if any(value["wechat_enable"] for value in alarms) and (
        not all(credential_checks.values()) or str(env.get("WECHAT_ENABLE", "true")).lower() not in ("1", "true", "yes")
    ):
        report.block("wechat_global_mismatch", "旧推送已启用，但公共凭据或总开关不一致，需明确确认", site_id=site["id"])
    expected_classes = {"person": 0, "play_phone": 1, "vehicle_bicycle": 1, "vehicle_car": 2, "vehicle_motorcycle": 3}
    if any(sections["classes"].get(key, value) != value for key, value in expected_classes.items()):
        report.block("class_mapping_changed", "旧类别编号与公共 ModelSpec 不一致", site_id=site["id"])
    field_values = []
    for section, keys in catalog.items():
        for key in keys:
            raw = sections[section].get(key)
            if section == "wechat" and key in {"corpid", "corpsecret", "agentid"}:
                raw = "[已配置]" if raw else "[未配置]"
            if section == "video" and key.startswith("source") and isinstance(raw, str):
                raw = redact_url(raw)
            field_values.append({"field": f"{section}.{key}", "present": key in sections[section], "old_value": raw})
    return {"policy": policy, "new_default_fields": sorted(defaults), "roi": roi, "alarms": alarms,
            "field_values": field_values,
            "wechat_credentials_match_global": credential_checks, "sections": sections}


def inspect_models(plans: list[dict], model_config: Path, old_root: Path, report: PrecheckReport, model_paths: dict | None = None) -> None:
    from AiVision.inference.model_paths import _read_document, validate_model_path
    try:
        source, _ = _read_document(model_config)
        models = (yaml.safe_load(source) or {}).get("models", {})
    except (OSError, ValueError, yaml.YAMLError):
        report.block("model_config_invalid", "公共模型路径配置不可读或格式错误")
        models = {}
    for old, (name, model_type) in MODEL_FIELDS.items():
        value = (model_paths or {}).get(name, models.get(name, {}).get("path", ""))
        if model_paths and name in model_paths:
            report.planned_actions.append({"action": "configure_global_model", "name": name, "path": value})
        item = {"name": name, "new_path": value, "valid": False, "old_paths": []}
        for plan in plans:
            raw = plan["sections"]["models"].get(old, "")
            path = (old_root / raw).resolve() if raw else None
            item["old_paths"].append({"site_id": plan["site_id"], "raw": raw,
                                      "resolved": str(path) if path else None,
                                      "exists": bool(path and path.is_file())})
        try:
            validated = Path(validate_model_path(value, model_type=model_type))
            item["valid"] = True
            if validated.is_relative_to(old_root.resolve()):
                report.block("model_inside_deleted_tree", "正式模型路径仍位于待删除目录内", model=name)
            different = [entry["site_id"] for entry in item["old_paths"] if entry["exists"] and not validated.samefile(entry["resolved"])]
            item["different_physical_file_sites"] = different
            if different:
                report.block("model_file_changed", "新旧权重不是同一物理文件，需确认权重一致性", model=name, sites=different)
        except (ValueError, OSError):
            report.block("model_path_missing_or_invalid", "公共模型路径未配置或本机文件无效", model=name)
        report.models.append(item)


def inspect_history(plans: list[dict], old_root: Path, yaml_config: dict, report: PrecheckReport) -> None:
    roots = {old_root.resolve()}
    for sections in [yaml_config, *(plan["sections"] for plan in plans)]:
        raw = sections.get("video", {}).get("output_dir")
        if isinstance(raw, str) and raw:
            roots.add((old_root / raw).resolve())
    files = set()
    for root in roots:
        if root.exists():
            files.update(path.resolve() for path in root.rglob("alarm_events.json"))
    entries = []
    for path in sorted(files):
        try:
            before = path.stat()
            raw = path.read_bytes()
            data = json.loads(raw)
            after = path.stat()
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise ValueError("统计期间历史发生变化")
            if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
                raise ValueError("历史不是事件列表")
            entries.append({"path": str(path), "count": len(data), "bytes": len(raw),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "event_types": dict(Counter(str(row.get("event_type")) for row in data))})
        except (OSError, ValueError):
            report.block("history_unreadable", "历史不可读、格式无效或统计时发生变化", path=str(path))
    report.history = {"files": entries, "count": sum(entry["count"] for entry in entries),
                      "searched_roots": sorted(map(str, roots)),
                      "complete": len(entries) == len(files), "action": "仅统计，不写入 AiAlarmEvent，不删除",
                      "note": "计数是磁盘快照；未运行旧 Runtime API，不声称覆盖尚未落盘的内存事件"}
    protected = [str(path) for path in sorted(old_root.rglob("*")) if path.is_file()
                 and (path.suffix.lower() in {".pt", ".onnx", ".engine", ".task", ".db", ".sqlite", ".sqlite3", ".jpg", ".jpeg", ".png", ".mp4", ".avi"}
                      or path.name == "alarm_events.json")]
    report.storage["deletion_plan"] = {"after_verify_tables": list(OLD_TABLES), "after_verify_directory": str(old_root),
                                        "protected_files": protected,
                                        "condition": "先确认备份及历史/权重归档，verify 成功后才可删除；本次不执行"}
    if protected:
        report.planned_actions.append({"action": "archive_runtime_assets", "count": len(protected)})


def preflight(source, target_connection, *, old_root: Path, model_config: Path, guard_config: Path, env: dict, model_paths: dict | None = None) -> dict:
    from pydantic import ValidationError
    from AiVision.features.guard_behavior.schema import GuardBehaviorSiteCreate
    report = PrecheckReport()
    old = read_tables(source, OLD_TABLES, report, "old_database")
    audit_extra_tables(source, report)
    target = read_tables(target_connection, ("ai_camera_config", *NEW_TABLES), report, "target_database")
    report.storage.update(old_database_location=database_location(source.engine.url),
                          target_database_location=database_location(target_connection.engine.url),
                          guard_yaml=str(guard_config), model_paths_yaml=str(model_config))
    catalog = field_catalog()
    # source_cam4..9 是旧 Service 动态写入的扩展槽位，也纳入逐字段处置。
    for index in range(1, 10):
        key = f"source_cam{index}"
        if key not in catalog["video"]:
            catalog["video"].append(key)
    dispositions(catalog, report)
    yaml_config = yaml.safe_load(guard_config.read_text()) or {}
    if not isinstance(yaml_config, dict):
        raise ValueError("旧 YAML 顶层必须是对象")
    report.storage["guard_yaml_role"] = "仅新建旧 Site 的默认值及历史目录线索；已有 Site 以数据库 JSON 为准"
    claimed, plans, site_keys = {}, [], set()
    for site in sorted(old["guard_room_site"], key=lambda row: (row["sort_order"], row["id"])):
        entry = {key: site[key] for key in ("id", "department", "name", "enabled", "sort_order")}
        entry["enabled"] = bool(entry["enabled"])
        try:
            GuardBehaviorSiteCreate.model_validate({key: value for key, value in entry.items() if key != "id"})
        except ValidationError:
            report.block("invalid_site", "Site 名称、事业部或排序不满足新合同", site_id=site["id"])
        key = (site["department"], site["name"].strip())
        if key in site_keys or any((row["department"], row["name"]) == key for row in target["ai_guard_behavior_site"]):
            report.block("site_name_conflict", "同事业部同名 Site 已存在，不能猜测覆盖关系", site_id=site["id"])
        site_keys.add(key)
        cameras = sorted([row for row in old["guard_room_camera"] if row["site_id"] == site["id"]],
                         key=lambda row: (row["sort_order"], row["id"]))
        entry["cameras"] = plan_cameras(site, cameras, target, report, claimed)
        configs = [row for row in old["guard_room_site_config"] if row["site_id"] == site["id"]]
        if len(configs) != 1:
            report.block("site_config_count", "Site 必须有且仅有一份旧配置", site_id=site["id"], count=len(configs))
        else:
            plan = plan_config(site, configs[0], entry["cameras"], catalog, report, env)
            plans.append({**plan, "site_id": site["id"]})
            entry.update({key: value for key, value in plan.items() if key != "sections"})
        report.sites.append(entry)
    site_ids = {site["id"] for site in old["guard_room_site"]}
    for name in OLD_TABLES[1:]:
        for row in old[name]:
            if row["site_id"] not in site_ids:
                report.block("orphan_row", "旧表含无所属 Site 的记录", table=name, id=row["id"])
    inspect_models(plans, model_config, old_root, report, model_paths)
    inspect_history(plans, old_root, yaml_config, report)
    return report.payload()


def execute_cutover(args, values, source_url, target_url, model_config, guard_config):
    from sqlalchemy.orm import Session
    from .guard_behavior_cutover_storage import (
        archive_assets, asset_inventory, create_backup, require_stopped, write_json,
    )
    from .guard_behavior_cutover_data import (
        assert_source, create_schema, migrate_data, table_rows, verify_archive, verify_data,
    )
    from AiVision.inference.model_paths import save_model_path, validate_model_path

    model_paths = dict(args.model_path or [])
    allowed_models = {name: kind for name, kind in MODEL_FIELDS.values()}
    for name, path in model_paths.items():
        if name not in allowed_models:
            raise ValueError("只允许设置本次切换的四个逻辑模型")
        validate_model_path(path, model_type=allowed_models[name])
    data_root = Path(values["DATA_PATH"])
    directory = data_root / "migration_backups" / REVISION
    archive = data_root / "legacy_guard_room_archive" / "20260917"
    snapshot = None
    if args.apply or args.verify:
        require_stopped()
        if (directory / "backup.json").exists():
            snapshot = create_backup(directory, source_url=source_url, target_url=target_url,
                                     model_config=model_config, old_root=OLD_ROOT, snapshot={})
    if snapshot is None:
        with read_only_connection(source_url) as source, read_only_connection(target_url) as target:
            plan = preflight(source, target, old_root=OLD_ROOT, model_config=model_config,
                             guard_config=guard_config, env=values, model_paths=model_paths)
            if not args.apply and not args.verify:
                return plan
            if plan["blockers_total"]:
                return plan
            snapshot = {"source": table_rows(source, OLD_TABLES), "plan": plan,
                        "physical_camera_count": len(table_rows(target, ("ai_camera_config",))["ai_camera_config"]),
                        "old_root": str(OLD_ROOT), "assets": asset_inventory(OLD_ROOT),
                        "models": {row["name"]: row["new_path"] for row in plan["models"]}}
        if args.verify:
            raise ValueError("尚无完整迁移备份，不能 verify")
        snapshot = create_backup(directory, source_url=source_url, target_url=target_url,
                                 model_config=model_config, old_root=OLD_ROOT, snapshot=snapshot)
    engine = create_engine(target_url, echo=False)
    try:
        with read_only_connection(source_url) as source:
            assert_source(source, snapshot, allow_retired=args.verify or (directory / "retired.json").exists())
        if args.apply:
            require_stopped()
            for name, path in snapshot["models"].items():
                save_model_path(name, path)
            create_schema(engine)
            result = migrate_data(engine, snapshot)
            archive_assets(OLD_ROOT, archive, snapshot["assets"])
        else:
            with Session(engine) as session:
                result = verify_data(session, snapshot)
        history_count = verify_archive(snapshot, archive)
        report = PrecheckReport()
        inspect_models([], model_config, OLD_ROOT, report)
        if report.blockers or {row["name"]: row["new_path"] for row in report.models} != snapshot["models"]:
            raise ValueError("正式模型配置与迁移快照不一致")
        result.update(result="APPLY PASS" if args.apply else "VERIFY PASS", history_count=history_count,
                      backup=str(directory), archive=str(archive), blockers_total=0)
        if args.retire:
            # 清理必须再次完成全部核验；DDL 顺序与数据迁移事务明确分离。
            require_stopped()
            source_engine = create_engine(source_url, echo=False)
            try:
                with source_engine.connect() as connection:
                    assert_source(connection, snapshot, allow_retired=True)
                for name in reversed(OLD_TABLES):
                    with source_engine.begin() as connection:
                        if inspect(connection).has_table(name):
                            Table(name, MetaData(), autoload_with=connection).drop(connection)
            finally:
                source_engine.dispose()
            result["retired_tables"] = list(OLD_TABLES)
        record = directory / ("retired.json" if args.retire else "applied.json" if args.apply else "verified.json")
        if not record.exists():
            write_json(record, result)
        return result
    finally:
        engine.dispose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true", help="默认只读计划")
    mode.add_argument("--apply", action="store_true", help="停机备份后执行数据迁移和资产归档")
    mode.add_argument("--verify", action="store_true", help="逐字段核验迁移及归档")
    parser.add_argument("--retire", action="store_true", help="仅与 --verify 合用，核验成功后删除三张旧表")
    parser.add_argument("--model-path", action="append", nargs=2, metavar=("NAME", "PATH"))
    parser.add_argument("--env-file", type=Path, default=ROOT / "AiVision/.env")
    args = parser.parse_args(argv)
    if args.retire and not args.verify:
        parser.error("--retire 必须与 --verify 一起使用")
    values = {**dotenv_values(args.env_file), **os.environ}
    for key, value in values.items():
        if value is not None:
            os.environ.setdefault(key, value)
    try:
        target_url = values.get("GUARD_CUTOVER_TARGET_DATABASE_URL") or URL.create(
            "mysql+pymysql", username=values["MYSQL_DB_USER"], password=values["MYSQL_DB_PASSWORD"],
            host=values["MYSQL_DB_URL"], port=int(values.get("MYSQL_DB_PORT", 3306)), database=values["MYSQL_DB_NAME"],
            query={"charset": values.get("MYSQL_DB_CHARSET", "utf8mb4")},
        )
        source_url = values.get("GUARD_ROOM_DATABASE_URL") or target_url
        model_config = Path(values.get("MODEL_PATHS_CONFIG", "config/model_paths.yaml"))
        if not model_config.is_absolute():
            model_config = ROOT / "AiVision" / model_config
        guard_config = Path(values.get("GUARD_ROOM_CONFIG_PATH", OLD_ROOT / "config/config.yaml"))
        result = execute_cutover(args, values, source_url, target_url, model_config, guard_config)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return int(bool(result["blockers_total"]))
    except Exception as exc:
        # 数据库异常可能含 RTSP 或凭据；只输出类型。主动校验错误只含固定业务说明。
        print(json.dumps({"result": "BLOCKED", "blockers_total": 1,
                          "error_type": type(exc).__name__,
                          "detail": str(exc) if type(exc) is ValueError else "执行失败，未继续切换"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
