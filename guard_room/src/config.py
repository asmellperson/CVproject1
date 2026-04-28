# config.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class VideoConfig:
    # 兼容旧字段
    source: str = ""

    # 多路摄像头（兼容现有双摄配置）
    source_cam1: str = ""
    source_cam2: str = ""
    source_cam3: str = ""

    process_every_n_frames: int = 3
    output_dir: str = "outputs"
    save_annotated_video: bool = False
    annotated_video_fps: int = 10
    reconnect_seconds: float = 1.0
    jpeg_quality: int = 80
    camera_buffer_size: int = 1


@dataclass
class ModelConfig:
    detector_model: str
    uniform_cls_model: str = ""
    pose_model_task: str = ""
    detector_conf: float = 0.35
    detector_iou: float = 0.45
    tracker: str = "bytetrack.yaml"
    device: str = ""
    uniform_cls_imgsz: int = 224
    uniform_cls_conf: float = 0.75


@dataclass
class RoomConfig:
    frame_width: int = 1920
    frame_height: int = 1080


@dataclass
class RuleConfig:
    absent_seconds: int = 900
    phone_seconds: int = 300
    prone_sleep_seconds: int = 300
    phone_near_person_px: int = 220
    phone_near_head_px: int = 160
    static_motion_threshold: float = 8.0
    prone_head_down_ratio_threshold: float = 0.22
    prone_bbox_height_ratio_threshold: float = 0.18
    prone_consecutive_frames: int = 8
    state_ttl_seconds: int = 20
    phone_window_seconds: int = 3
    phone_min_hits_in_window: int = 5
    phone_grace_seconds: int = 2

    # ===== 新增：保安识别与双摄共识 =====
    guard_hold_seconds: float = 1.3
    dual_sync_seconds: float = 1.5
    absent_alarm_seconds: float = 60.0

    alarm_cooldown_absent: int=120     # 离岗 冷却 2 分钟
    alarm_cooldown_phone: int=60       # 手机冷却 1 分钟 
    alarm_cooldown_prone_sleep: int=300 


@dataclass
class ClassConfig:
    person: int = 0
    play_phone: int = 1


@dataclass
class RuntimeConfig:
    show_window: bool = False
    debug: bool = True
    draw_debug: bool = False
    max_alarm_history: int = 1000
    phone_detect_mode: str = "guard_crop"  # guard_crop（只对保安） / full_frame_test（全图）


@dataclass
class AppConfig:
    video: VideoConfig
    models: ModelConfig
    room: RoomConfig
    rules: RuleConfig
    classes: ClassConfig
    runtime: RuntimeConfig
    wechat: WeChatConfig

    def camera_sources(self) -> list[tuple[str, str]]:
        video = self.video
        sources: list[tuple[str, str]] = []

        for idx in range(1, 10):
            value = (getattr(video, f"source_cam{idx}", "") or "").strip()
            if value:
                sources.append((f"cam{idx}", value))

        if sources:
            return sources

        fallback = (video.source or "").strip()
        return [("cam1", fallback)] if fallback else []

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AppConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        video_data = dict(data.get("video") or {})
        if not video_data.get("source") and video_data.get("source_cam1"):
            video_data["source"] = video_data["source_cam1"]

        return cls(
            video=VideoConfig(**video_data),
            models=ModelConfig(**(data.get("models") or {})),
            room=RoomConfig(**(data.get("room") or {})),
            rules=RuleConfig(**(data.get("rules") or {})),
            classes=ClassConfig(**(data.get("classes") or {})),
            runtime=RuntimeConfig(**(data.get("runtime") or {})),
            wechat=WeChatConfig(**(data.get("wechat") or {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "video": asdict(self.video),
            "models": asdict(self.models),
            "room": asdict(self.room),
            "rules": asdict(self.rules),
            "classes": asdict(self.classes),
            "runtime": asdict(self.runtime),
            "wechat": asdict(self.wechat),
        }
@dataclass
class WeChatConfig:
    enable: bool = False
    corpid: str = ""
    corpsecret: str = ""
    agentid: int = 1000050
    alarm_user: str = ""
    camera_name: str = "值班室双摄像头"
    clip_seconds: float = 5.0
    enable_phone: bool = True
    enable_absent: bool = True
    enable_prone_sleep: bool = True
