# state.py
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from .config import AppConfig
from .types import AlarmEvent, Detection


class AppState:
    def __init__(self, cfg: AppConfig, config_path: str | Path):
        self._lock = threading.RLock()
        self.config = cfg
        self.config_path = str(config_path)
        self.latest_jpeg: bytes = self._build_placeholder("Waiting for stream")
        self.error: Optional[str] = None
        self.reader_warning: Optional[str] = None
        self.running = False
        self.started_at: Optional[float] = None
        self.frame_count = 0
        self.fps = 0.0
        self.pose_enabled = False
        self.source = ", ".join(source for _, source in cfg.camera_sources())
        self.last_update_ts: Optional[float] = None
        self.last_alarm: Optional[dict[str, Any]] = None
        self.alarms: deque[dict[str, Any]] = deque(maxlen=cfg.runtime.max_alarm_history)
        self.latest_detections: dict[str, Any] = {"persons": [], "phones": [], "pose_features": {}, "decisions": {"absent": False, "phone_use": False, "prone_sleep": False}, "metrics": {"person_confidence": 0.0, "phone_confidence": 0.0, "head_down_ratio": 0.0}, "counts": {"persons": 0, "phones": 0}}
        self._stats_cache: Optional[dict] = None
        self._stats_cache_ts: float = 0.0

    def set_config(self, cfg: AppConfig, config_path: str | Path | None = None) -> None:
        with self._lock:
            self.config = cfg
            self.source = ", ".join(source for _, source in cfg.camera_sources())
            if config_path is not None:
                self.config_path = str(config_path)

    def mark_running(self, running: bool) -> None:
        with self._lock:
            self.running = running
            if running:
                self.started_at = time.time()
                self.error = None
            else:
                self.started_at = None

    def set_error(self, message: str) -> None:
        with self._lock:
            self.error = message
            self.running = False

    def clear_error(self) -> None:
        with self._lock:
            self.error = None

    def set_reader_warning(self, message: str) -> None:
        with self._lock:
            self.reader_warning = message

    def clear_reader_warning(self) -> None:
        with self._lock:
            self.reader_warning = None

    def update_frame(self, frame_bgr: np.ndarray, *, frame_count: int, fps: float, timestamp_s: float, persons: list[Detection], phones: list[Detection], pose_features: dict[int, dict[str, float]], decisions: dict[str, Any], pose_enabled: bool, jpeg_quality: int = 80) -> None:
        ok, encoded = cv2.imencode('.jpg', frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
        if not ok:
            return
        metrics = {"person_confidence": max((float(d.conf) for d in persons), default=0.0), "phone_confidence": max((float(d.conf) for d in phones), default=0.0), "head_down_ratio": max((float(v.get("head_down_ratio", 0.0)) for v in pose_features.values()), default=0.0)}
        with self._lock:
            self.latest_jpeg = encoded.tobytes()
            self.frame_count = frame_count
            self.fps = float(fps)
            self.pose_enabled = bool(pose_enabled)
            self.last_update_ts = time.time()
            self.latest_detections = {
                "persons": [self._det_to_dict(d) for d in persons],
                "phones": [self._det_to_dict(d) for d in phones],
                "pose_features": {str(k): v for k, v in pose_features.items()},
                "decisions": {"absent": bool(getattr(decisions.get("absent"), "active", False)), "phone_use": bool(getattr(decisions.get("phone"), "active", False)), "prone_sleep": bool(getattr(decisions.get("prone_sleep"), "active", False))},
                "metrics": metrics,
                "counts": {"persons": len(persons), "phones": len(phones)},
                "stream_time_s": round(timestamp_s, 2),
            }

    def add_alarm(self, alarm: AlarmEvent) -> dict[str, Any]:
        payload = asdict(alarm)
        payload["id"] = uuid.uuid4().hex[:12]
        payload["created_at"] = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self.last_alarm = payload
            self.alarms.appendleft(payload)
        return payload
    
    def attach_alarm_video(self, event_type: str, frame_index: int, video_path: str) -> None:
        with self._lock:
            if self.last_alarm and self.last_alarm.get("event_type") == event_type and self.last_alarm.get("frame_index") == frame_index:
                self.last_alarm["video_path"] = video_path
                self.last_alarm["video_status"] = "ready"

            for item in self.alarms:
                if item.get("event_type") == event_type and item.get("frame_index") == frame_index:
                    item["video_path"] = video_path
                    item["video_status"] = "ready"
                    break
    def mark_alarm_video_failed(self, event_type: str, frame_index: int) -> None:
        with self._lock:
            if (self.last_alarm 
                and self.last_alarm.get("event_type") == event_type 
                and self.last_alarm.get("frame_index") == frame_index):
                self.last_alarm["video_status"] = "failed"
            
            for item in self.alarms:
                if (item.get("event_type") == event_type 
                    and item.get("frame_index") == frame_index):
                    item["video_status"] = "failed"
                    break

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            uptime = 0.0 if not self.running or self.started_at is None else max(0.0, time.time() - self.started_at)
            return {"running": self.running, "fps": round(self.fps, 2), "frame_count": self.frame_count, "pose_enabled": self.pose_enabled, "source": self.source, "error": self.error, "reader_warning": self.reader_warning, "updated_at": datetime.now().isoformat(timespec="seconds"), "uptime_sec": round(uptime, 1), "last_alarm": self.last_alarm, "stream_url": "/api/stream.mjpg", "frame_url": "/api/frame.jpg", **self.latest_detections}

    def get_config_dict(self) -> dict[str, Any]:
        with self._lock:
            return self.config.to_dict()

    def get_latest_frame(self) -> bytes:
        with self._lock:
            return self.latest_jpeg

    def get_alarms(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(list(self.alarms)[:limit])

    def get_alarm(self, alarm_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            for item in self.alarms:
                if item["id"] == alarm_id:
                    return item
        return None

    def get_statistics(self) -> dict[str, Any]:
        alarms = self.get_alarms(limit=1000)
        now = datetime.now()
        summary = {"total": len(alarms), "absent": sum(1 for a in alarms if a["event_type"] == "absent"), "phone_use": sum(1 for a in alarms if a["event_type"] == "phone_use"), "prone_sleep": sum(1 for a in alarms if a["event_type"] == "prone_sleep"), "today": 0, "week": 0}
        hourly_map = {h: {"absent": 0, "phone": 0, "prone_sleep": 0} for h in range(24)}
        weekly_keys = [(now - timedelta(days=i)).date() for i in range(6, -1, -1)]
        weekly_map = {d: {"absent": 0, "phone": 0, "prone_sleep": 0} for d in weekly_keys}
        weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        for alarm in alarms:
            created_at = datetime.fromisoformat(alarm["created_at"])
            if created_at.date() == now.date():
                summary["today"] += 1
            if created_at >= now - timedelta(days=7):
                summary["week"] += 1
            bucket = alarm["event_type"]
            bucket_key = "phone" if bucket == "phone_use" else bucket
            hourly_map[created_at.hour][bucket_key] += 1
            if created_at.date() in weekly_map:
                weekly_map[created_at.date()][bucket_key] += 1
        hourly = [{"time": f"{hour:02d}:00", **vals} for hour, vals in hourly_map.items()]
        weekly = [{"day": weekday_cn[d.weekday()], **weekly_map[d]} for d in weekly_keys]
        pie = [{"name": "离岗", "value": summary["absent"], "color": "#ef4444"}, {"name": "玩手机", "value": summary["phone_use"], "color": "#f97316"}, {"name": "趴睡", "value": summary["prone_sleep"], "color": "#eab308"}]
        return {"summary": summary, "hourly": hourly, "weekly": weekly, "pie": pie}
    @staticmethod
    def _det_to_dict(det: Detection) -> dict[str, Any]:
        return {"cls_id": det.cls_id, "conf": float(det.conf), "bbox": list(det.bbox), "track_id": det.track_id}

    @staticmethod
    def _build_placeholder(text: str) -> bytes:
        canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
        canvas[:] = (17, 24, 39)
        cv2.putText(canvas, text, (90, 360), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 4)
        ok, encoded = cv2.imencode('.jpg', canvas)
        return encoded.tobytes() if ok else b''
