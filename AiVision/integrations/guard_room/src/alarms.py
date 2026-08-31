# 文件说明：实现告警相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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
from typing import List, Optional

import cv2
import json
import numpy as np
import threading

from .media_cleanup import (
    AlarmMediaCleanupStats,
    cleanup_alarm_media,
    event_media_available,
)
from .types import AlarmEvent
from .utils import ensure_dir, now_str


# 功能：报警事件的生命周期管理器；输入与输出详见下方说明
# 参数：
#   - `output_dir`（str）：`output_dir` 对应的业务输入值
# 返回：AlarmManager；返回新建的 `AlarmManager` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_media_cleanup.py` 的
#         `test_cleanup_rejects_symlinks_and_alarm_manager_prunes_memory` 实例化本符号；`AiVision/integrations/guard_room/src/runtime.py` 的
#         `GuardRoomRuntime::_run_loop` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AlarmManager:
    """报警事件的生命周期管理器。

    职责边界：
        - 只负责事件的"产生 → 持久化 → 状态更新"，不负责视频录制本身。
        - 视频录制完成后由外部（AlarmClipRecorder）调用 attach_video() 回填路径。

    持久化结构（output_dir/）：
        alarm_events.json   —— 全量事件列表，每次变更后全量覆写。
        alarms/             —— 报警触发瞬间的 JPEG 快照。
    """

    # 功能：output_dir: 根输出目录；快照子目录 alarms/ 会自动创建；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `output_dir`（str）：`output_dir` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`ensure_dir`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, output_dir: str):
        """
        Args:
            output_dir: 根输出目录；快照子目录 alarms/ 会自动创建。
        """
        self.output_dir = ensure_dir(output_dir)
        self.snapshots_dir = ensure_dir(self.output_dir / "alarms")  # 快照存放目录
        self.events: List[AlarmEvent] = []          # 运行期全量事件列表（内存）
        self._last_emit_ts: dict[str, float] = {}   # 各冷却键上次触发的流时间戳

    # 功能：尝试触发一条报警事件；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `event_type`（str）：事件类型标识
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    #   - `timestamp_s`（float）：以秒表示的流时间戳
    #   - `frame_index`（int）：视频流中的帧序号
    #   - `track_id`（Optional[int]）：目标跟踪标识
    #   - `confidence`（float）：模型预测或规则判断的置信度
    #   - `reason`（str）：`reason` 对应的业务输入值
    #   - `camera_name`（str）：`camera_name` 对应的业务输入值；默认值为 `''`
    #   - `cooldown_seconds`（float）：`cooldown_seconds` 对应的时间间隔或时长；默认值为 `60.0`
    # 返回：Optional[AlarmEvent]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_emit_alarm_once` 调用本符号
    #   - 内部调用：`self._last_emit_ts.get`、`now_str`、`cv2.imwrite`、`str`、`AlarmEvent`、`self.events.append`、`self._flush`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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

    # 功能：将录制完成的视频路径回写到已有事件，并更新状态为 "ready"；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `event`（AlarmEvent）：待处理的事件对象
    #   - `video_path`（str）：`video_path` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 调用本符号
    #   - 内部调用：`str`、`self._flush`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：将事件的视频状态标记为 "failed"；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `event`（AlarmEvent）：待处理的事件对象
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._flush`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def mark_video_failed(self, event: AlarmEvent) -> None:
        """将事件的视频状态标记为 "failed"。

        当视频录制或上传出现不可恢复错误时调用，
        便于监控系统区分"未完成"与"已失败"两种状态。

        Args:
            event: 需要标记的报警事件对象。
        """
        event.video_status = "failed"
        self._flush()

    # 功能：清理过期/超限的报警图片和视频，并同步裁剪内存事件；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `retention_days`（int）：`retention_days` 对应的业务输入值
    #   - `max_bytes`（int）：`max_bytes` 对应的业务输入值
    #   - `now`（float | None）：`now` 对应的业务输入值；默认值为 `None`
    # 返回：AlarmMediaCleanupStats；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/tests/test_media_cleanup.py` 的
    #         `test_cleanup_rejects_symlinks_and_alarm_manager_prunes_memory`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_cleanup_alarm_media` 调用本符号
    #   - 内部调用：`cleanup_alarm_media`、`event_media_available`、`len`、`self._flush`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def cleanup_media(
        self,
        *,
        retention_days: int,
        max_bytes: int,
        now: float | None = None,
    ) -> AlarmMediaCleanupStats:
        """清理过期/超限的报警图片和视频，并同步裁剪内存事件。"""
        stats = cleanup_alarm_media(
            self.output_dir,
            retention_days=retention_days,
            max_bytes=max_bytes,
            now=now,
        )
        if stats.skipped_busy:
            return stats
        retained = [event for event in self.events if event_media_available(event)]
        if len(retained) != len(self.events):
            self.events = retained
            self._flush()
        return stats

    # 功能：将内存中的全量事件列表序列化并覆写到 alarm_events.json；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/alarms.py` 的 `AlarmManager::emit`
    #         调用本符号；`AiVision/integrations/guard_room/src/alarms.py` 的 `AlarmManager::attach_video`
    #         调用本符号；`AiVision/integrations/guard_room/src/alarms.py` 的 `AlarmManager::mark_video_failed`
    #         调用本符号；`AiVision/integrations/guard_room/src/alarms.py` 的 `AlarmManager::cleanup_media` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`out_file.with_name`、`threading.get_ident`、`open`、`json.dump`、`asdict`、`temporary_file.replace`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
    def _flush(self) -> None:
        """将内存中的全量事件列表序列化并覆写到 alarm_events.json。

        采用全量覆写而非追加，以保证文件始终是合法的 JSON 数组，
        即使进程在写入中途崩溃，旧文件仍完好（依赖 OS 的原子写语义）。
        """
        out_file = self.output_dir / "alarm_events.json"
        temporary_file = out_file.with_name(
            f".{out_file.name}.{threading.get_ident()}.tmp"
        )
        with open(temporary_file, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self.events], f, ensure_ascii=False, indent=2)
        temporary_file.replace(out_file)
