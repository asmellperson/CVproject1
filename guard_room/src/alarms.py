# alarms.py
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

import cv2
import json
import numpy as np

from .types import AlarmEvent
from .utils import ensure_dir, now_str


class AlarmManager:
    def __init__(self, output_dir: str):
        self.output_dir = ensure_dir(output_dir)
        self.snapshots_dir = ensure_dir(self.output_dir / "alarms")
        self.events: List[AlarmEvent] = []
        # 改成记录上次报警时间，替代原来的 _seen_keys
        self._last_emit_ts: dict[str, float] = {}

    def emit(
        self,
        event_type: str,
        frame: np.ndarray,
        timestamp_s: float,
        frame_index: int,
        track_id: Optional[int],
        confidence: float,
        reason: str,
        camera_name: str = "",
        cooldown_seconds: float = 60.0,       # 新增参数
    ) -> Optional[AlarmEvent]:
        cooldown_key = f"{event_type}:{track_id}"
        last_ts = self._last_emit_ts.get(cooldown_key, -1e9)
        if (timestamp_s - last_ts) < cooldown_seconds:
            return None
        self._last_emit_ts[cooldown_key] = timestamp_s

        filename = f"{event_type}_{track_id}_{frame_index}_{now_str()}.jpg"
        image_path = self.snapshots_dir / filename
        cv2.imwrite(str(image_path), frame)

        event = AlarmEvent(
            event_type=event_type,
            timestamp_s=timestamp_s,
            frame_index=frame_index,
            track_id=track_id,
            confidence=confidence,
            reason=reason,
            image_path=str(image_path),
            camera_name=camera_name,
            video_path=None,
            video_status="pending",
        )
        self.events.append(event)
        self._flush()
        return event

    def attach_video(self, event: AlarmEvent, video_path: str) -> None:
        event.video_path = str(video_path)
        event.video_status = "ready"
        self._flush()

    def mark_video_failed(self, event: AlarmEvent) -> None:
        event.video_status = "failed"
        self._flush()

    def _flush(self) -> None:
        out_file = self.output_dir / "alarm_events.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self.events], f, ensure_ascii=False, indent=2)