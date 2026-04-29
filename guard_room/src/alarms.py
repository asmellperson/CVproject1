# alarms.py
"""
报警事件管理模块。

负责：
  1. 对检测结果去抖（冷却期内同一目标的同类报警只触发一次）；
  2. 保存报警快照（JPEG）；
  3. 维护报警事件列表，并将其持久化到 alarm_events.json；
  4. 在视频片段就绪后回写视频路径与状态。
"""
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
    """报警事件的生命周期管理器。

    职责边界：
        - 只负责事件的"产生 → 持久化 → 状态更新"，不负责视频录制本身。
        - 视频录制完成后由外部（AlarmClipRecorder）调用 attach_video() 回填路径。

    持久化结构（output_dir/）：
        alarm_events.json   —— 全量事件列表，每次变更后全量覆写。
        alarms/             —— 报警触发瞬间的 JPEG 快照。
    """

    def __init__(self, output_dir: str):
        """
        Args:
            output_dir: 根输出目录；快照子目录 alarms/ 会自动创建。
        """
        self.output_dir = ensure_dir(output_dir)
        self.snapshots_dir = ensure_dir(self.output_dir / "alarms")  # 快照存放目录
        self.events: List[AlarmEvent] = []          # 运行期全量事件列表（内存）
        self._last_emit_ts: dict[str, float] = {}   # 各冷却键上次触发的流时间戳

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
        cooldown_seconds: float = 60.0,
    ) -> Optional[AlarmEvent]:
        """尝试触发一条报警事件。

        冷却机制：同一 (event_type, track_id) 组合在 cooldown_seconds 内
        只允许触发一次，重复调用返回 None，不产生任何副作用。

        触发成功时会：
          1. 将当前帧写为 JPEG 快照；
          2. 构造 AlarmEvent（video_path=None，video_status="pending"）；
          3. 追加到内存列表并刷新 alarm_events.json。

        Args:
            event_type:        报警类型字符串，如 "fall"、"intrusion"。
            frame:             触发报警时的原始视频帧（BGR）。
            timestamp_s:       当前流时间戳（秒），用于冷却判断。
            frame_index:       当前帧序号，写入文件名与事件元数据。
            track_id:          目标跟踪 ID；无跟踪时传 None。
            confidence:        检测置信度（0~1）。
            reason:            人类可读的触发原因描述，便于后续审计。
            camera_name:       摄像头标识，默认为空字符串。
            cooldown_seconds:  同一目标同类事件的最小触发间隔（秒），默认 60。

        Returns:
            成功触发时返回新建的 AlarmEvent；冷却期内返回 None。
        """
        # 冷却键：同一事件类型 + 同一跟踪目标 视为同一报警源
        cooldown_key = f"{event_type}:{track_id}"
        last_ts = self._last_emit_ts.get(cooldown_key, -1e9)   # 未记录时视为无穷久前
        if (timestamp_s - last_ts) < cooldown_seconds:
            return None                     # 仍在冷却期，静默丢弃
        self._last_emit_ts[cooldown_key] = timestamp_s          # 更新上次触发时间

        # 保存快照：文件名含事件类型、跟踪 ID、帧序号和时间戳，便于溯源
        filename = f"{event_type}_{track_id}_{frame_index}_{now_str()}.jpg"
        image_path = self.snapshots_dir / filename
        cv2.imwrite(str(image_path), frame)

        # 构造事件对象；视频路径留空，待录制完成后由 attach_video() 回填
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
            video_status="pending",         # 初始状态：等待视频录制完成
        )
        self.events.append(event)
        self._flush()                       # 每次变更后立即持久化，防止进程崩溃丢失数据
        return event

    def attach_video(self, event: AlarmEvent, video_path: str) -> None:
        """将录制完成的视频路径回写到已有事件，并更新状态为 "ready"。

        由 AlarmClipRecorder 在片段录制完成后调用。

        Args:
            event:      需要更新的报警事件对象（直接修改其字段）。
            video_path: 录制完成的 MP4 文件路径。
        """
        event.video_path = str(video_path)
        event.video_status = "ready"
        self._flush()

    def mark_video_failed(self, event: AlarmEvent) -> None:
        """将事件的视频状态标记为 "failed"。

        当视频录制或上传出现不可恢复错误时调用，
        便于监控系统区分"未完成"与"已失败"两种状态。

        Args:
            event: 需要标记的报警事件对象。
        """
        event.video_status = "failed"
        self._flush()

    def _flush(self) -> None:
        """将内存中的全量事件列表序列化并覆写到 alarm_events.json。

        采用全量覆写而非追加，以保证文件始终是合法的 JSON 数组，
        即使进程在写入中途崩溃，旧文件仍完好（依赖 OS 的原子写语义）。
        """
        out_file = self.output_dir / "alarm_events.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self.events], f, ensure_ascii=False, indent=2)