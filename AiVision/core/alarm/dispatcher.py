"""
core/alarm/dispatcher.py
统一告警分发器 — 把"判断该不该告警 + 触发哪些通道"从 Consumer 里抽出来。

旧代码: 每个 Consumer 都把 _should_alarm / _execute_alarm / _send_wechat_alert /
        _save_to_sql / wechat 后台线程 缠在一起,~150 行重复散落在 5 个子类。
新代码: Consumer 只管业务判断,告警分发交给 AlarmDispatcher。
"""
from __future__ import annotations
import base64
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from core.logger import logger
from core.alarm.horn import Horn
from core.alarm.wechat import WeChatNotifier


@dataclass
class AlarmRequest:
    """单次告警请求 — 由 Consumer 提交给 dispatcher"""
    feature_name: str
    camera_id: int
    camera_name: str    # 展示名称
    frame: np.ndarray
    violation_type: int
    alarm_config: dict  # {sql, horn, wechat} 三个通道的开关和参数
    camera_key: str = ""  # 内部摄像头标识(shm_name)


class AlarmDispatcher:
    """全局告警分发器 — 单例,在系统启动时由 Orchestrator 注入依赖"""

    def __init__(self):
        # 由 Orchestrator 注入
        self.horn_dict: dict[int, Horn] = {}
        self.wechat: Optional[WeChatNotifier] = None
        self.violation_writer = None  # platform.violation.service.ViolationWriter

        # 异步微信发送队列(微信 API 网络延迟可能较高)
        self._wechat_queue: queue.Queue = queue.Queue(maxsize=100)
        self._wechat_thread = threading.Thread(target=self._wechat_loop, daemon=True)
        self._wechat_started = False

        # 每摄像头-功能维度的告警冷却时间戳
        self._last_alarm: dict[tuple[int, str], float] = {}
        self._lock = threading.Lock()

    def configure(
        self,
        horn_dict: dict[int, Horn],
        wechat: Optional[WeChatNotifier],
        violation_writer,
    ):
        """启动时由 Orchestrator 调用注入依赖"""
        self.horn_dict = horn_dict
        self.wechat = wechat
        self.violation_writer = violation_writer
        if not self._wechat_started:
            self._wechat_thread.start()
            self._wechat_started = True

    # ---------- 核心入口 ----------

    def maybe_dispatch(
        self,
        request: AlarmRequest,
        alarm_interval: float = 5.0,
    ) -> bool:
        """触发告警(若冷却已过) — Consumer 在判定违规时调用此方法。
        
        返回 True 表示真的发了告警,False 表示在冷却期内被吞掉。
        """
        key = (request.camera_id, request.feature_name)
        now = time.time()
        with self._lock:
            last = self._last_alarm.get(key, 0.0)
            if now - last < alarm_interval:
                return False
            self._last_alarm[key] = now

        self._execute(request)
        return True

    # ---------- 私有 ----------

    def _execute(self, req: AlarmRequest):
        alarm = req.alarm_config or {}

        # 喇叭
        horn_cfg = alarm.get("horn") or {}
        if horn_cfg.get("enable"):
            horn_id = (horn_cfg.get("parm") or {}).get("horn_id")
            event_id = (horn_cfg.get("parm") or {}).get("horn_event_id")
            horn = self.horn_dict.get(horn_id) if horn_id is not None else None
            if horn is not None and event_id is not None:
                try:
                    horn.play(event_id)
                except Exception as e:
                    logger.warning(f"[Alarm] 喇叭触发失败: {e}")

        # 微信(异步)
        wechat_cfg = alarm.get("wechat") or {}
        if wechat_cfg.get("enable") and self.wechat is not None:
            user = (wechat_cfg.get("parm") or {}).get("user", "")
            if user:
                try:
                    self._wechat_queue.put_nowait((req, user))
                except queue.Full:
                    logger.warning(f"[Alarm] 微信告警队列满,丢弃 {req.feature_name}")

        # 报警记录持久化: 所有已触发报警都保存截图,各推送通道仍按自身开关控制。
        if self.violation_writer is not None:
            try:
                self.violation_writer.enqueue(
                    frame=req.frame,
                    violation_type=req.violation_type,
                    camera_no=req.camera_key or req.camera_name,
                )
            except Exception as e:
                logger.warning(f"[Alarm] SQL 入队失败: {e}")

    def _wechat_loop(self):
        while True:
            req, user = self._wechat_queue.get()
            if self.wechat is None:
                continue
            try:
                ok, buffer = cv2.imencode(".jpg", req.frame)
                if not ok:
                    continue
                self.wechat.send(
                    feature_name=req.feature_name,
                    camera_name=req.camera_name,
                    image_jpeg_bytes=buffer.tobytes(),
                    recipients=user,
                )
            except Exception as e:
                logger.warning(f"[Alarm] 微信发送失败: {e}")


# 全局单例
alarm_dispatcher = AlarmDispatcher()
