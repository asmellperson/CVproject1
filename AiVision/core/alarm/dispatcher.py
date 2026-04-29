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
    """
    单次告警请求的数据载体，由 Consumer 构造后提交给 AlarmDispatcher。

    字段说明:
        feature_name   : 触发告警的功能名称。
        camera_id      : 摄像头数字 ID，作为冷却表的 key 之一。
        camera_name    : 摄像头展示名称，写入告警消息与数据库。
        frame          : 违规帧的 BGR 图像（np.ndarray），用于截图保存与微信推图。
        violation_type : 违规类型编号，对应数据库中的枚举值。
        alarm_config   : 告警通道配置字典，结构为
                         {"horn": {...}, "wechat": {...}, "sql": {...}}，
                         每个通道包含 enable 开关与 parm 参数子字典。
        camera_key     : 共享内存标识（shm_name），优先用于数据库写入；
                         为空时回退到 camera_name。
    """
    feature_name: str
    camera_id: int
    camera_name: str
    frame: np.ndarray
    violation_type: int
    alarm_config: dict
    camera_key: str = ""


class AlarmDispatcher:
    """
    全局告警分发器（单例）。

    职责:
        1. 冷却控制  — 同一摄像头 × 功能维度，在 alarm_interval 秒内只触发一次。
        2. 通道分发  — 按 alarm_config 中各通道的 enable 开关，分别调用
                       喇叭 / 微信 / SQL 三条告警链路。
        3. 异步解耦  — 微信发送通过内部队列 + 守护线程异步执行，
                       避免网络延迟阻塞主检测流程。

    生命周期:
        系统启动时由 Orchestrator 调用 configure() 注入依赖，之后各 Consumer
        通过全局单例 alarm_dispatcher.maybe_dispatch() 提交告警请求。
    """

    def __init__(self):
        # ---- 外部依赖（由 Orchestrator 通过 configure() 注入）----
        self.horn_dict: dict[int, Horn] = {}          # horn_id → Horn 实例映射
        self.wechat: Optional[WeChatNotifier] = None  # 微信推送客户端
        self.violation_writer = None                  # ViolationWriter，负责 SQL 持久化

        # ---- 微信异步发送队列 ----
        # 微信 API 存在网络延迟，使用独立队列 + 守护线程，防止阻塞检测主循环。
        # maxsize=100：队列满时丢弃新请求（见 _execute 中的 put_nowait 处理）。
        self._wechat_queue: queue.Queue = queue.Queue(maxsize=100)
        self._wechat_thread = threading.Thread(target=self._wechat_loop, daemon=True)
        self._wechat_started = False  # 防止 configure() 被重复调用时二次启动线程

        # ---- 冷却状态 ----
        # key: (camera_id, feature_name)，value: 上次实际触发告警的 Unix 时间戳。
        # 使用 _lock 保护，避免多 Consumer 线程并发写入时的竞态条件。
        self._last_alarm: dict[tuple[int, str], float] = {}
        self._lock = threading.Lock()

    def configure(
        self,
        horn_dict: dict[int, Horn],
        wechat: Optional[WeChatNotifier],
        violation_writer,
    ):
        """
        注入运行时依赖，并启动微信后台发送线程。

        应在系统启动阶段由 Orchestrator 调用且只调用一次。
        重复调用时依赖会被覆盖，但后台线程不会重复创建（_wechat_started 守护）。
        """
        self.horn_dict = horn_dict
        self.wechat = wechat
        self.violation_writer = violation_writer
        if not self._wechat_started:
            self._wechat_thread.start()
            self._wechat_started = True

    # ------------------------------------------------------------------ #
    #  核心入口                                                             #
    # ------------------------------------------------------------------ #

    def maybe_dispatch(
        self,
        request: AlarmRequest,
        alarm_interval: float = 5.0,
    ) -> bool:
        """
        冷却检查 + 告警分发的统一入口，Consumer 检测到违规时调用此方法。

        冷却逻辑:
            以 (camera_id, feature_name) 为粒度记录上次触发时间；
            若距上次触发不足 alarm_interval 秒，静默丢弃并返回 False。

        Args:
            request        : 封装本次违规信息的 AlarmRequest 对象。
            alarm_interval : 同一摄像头×功能的告警冷却秒数，默认 5 秒。

        Returns:
            True  — 冷却已过，告警已提交各通道执行。
            False — 仍在冷却期，本次告警被静默丢弃。
        """
        key = (request.camera_id, request.feature_name)
        now = time.time()

        with self._lock:
            last = self._last_alarm.get(key, 0.0)
            if now - last < alarm_interval:
                return False          # 冷却期内，跳过
            self._last_alarm[key] = now  # 更新时间戳，占位防并发重入

        self._execute(request)
        return True

    # ------------------------------------------------------------------ #
    #  私有方法                                                             #
    # ------------------------------------------------------------------ #

    def _execute(self, req: AlarmRequest):
        """
        按 alarm_config 中各通道的 enable 开关，依次触发喇叭、微信、SQL 三条链路。

        设计原则:
            - 各通道相互独立，单个通道异常不影响其他通道执行。
            - 微信通过队列异步发送；喇叭同步调用；SQL 通过 ViolationWriter 异步入队。
            - SQL（violation_writer）对所有已触发告警无条件写入，不受微信/喇叭开关影响。
        """
        alarm = req.alarm_config or {}

        # ---- 通道 1: 喇叭（同步）----
        horn_cfg = alarm.get("horn") or {}
        if horn_cfg.get("enable"):
            # 从配置中解析喇叭 ID 与事件 ID
            horn_id  = (horn_cfg.get("parm") or {}).get("horn_id")
            event_id = (horn_cfg.get("parm") or {}).get("horn_event_id")
            horn = self.horn_dict.get(horn_id) if horn_id is not None else None
            if horn is not None and event_id is not None:
                try:
                    horn.play(event_id)
                except Exception as e:
                    logger.warning(f"[Alarm] 喇叭触发失败: {e}")

        # ---- 通道 2: 微信（异步入队）----
        wechat_cfg = alarm.get("wechat") or {}
        if wechat_cfg.get("enable") and self.wechat is not None:
            user = (wechat_cfg.get("parm") or {}).get("user", "")
            if user:
                try:
                    # put_nowait: 队列满时抛 queue.Full，记录日志后丢弃，不阻塞主流程
                    self._wechat_queue.put_nowait((req, user))
                except queue.Full:
                    logger.warning(f"[Alarm] 微信告警队列满，丢弃 {req.feature_name}")

        # ---- 通道 3: SQL 持久化（无条件写入）----
        # 只要告警通过冷却检查就落库，与微信/喇叭的 enable 开关无关，
        # 确保系统有完整的违规记录可供事后审计。
        if self.violation_writer is not None:
            try:
                self.violation_writer.enqueue(
                    frame=req.frame,
                    violation_type=req.violation_type,
                    # camera_key（shm_name）优先；为空时回退到 camera_name
                    camera_no=req.camera_key or req.camera_name,
                )
            except Exception as e:
                logger.warning(f"[Alarm] SQL 入队失败: {e}")

    def _wechat_loop(self):
        """
        微信后台发送线程的主循环（守护线程，随主进程退出自动结束）。

        处理流程:
            1. 阻塞等待 _wechat_queue 中的 (AlarmRequest, user) 元组。
            2. 将 frame（BGR ndarray）编码为 JPEG 字节流。
            3. 调用 WeChatNotifier.send() 推送消息与图片。

        异常处理:
            编码失败或网络异常仅记录警告日志，不中断循环，保证线程持续运行。
        """
        while True:
            req, user = self._wechat_queue.get()  # 阻塞直到有新任务

            if self.wechat is None:
                continue  # wechat 客户端未注入，跳过（理论上不应发生）

            try:
                # 将 BGR 帧编码为 JPEG，传输体积远小于原始 ndarray
                ok, buffer = cv2.imencode(".jpg", req.frame)
                if not ok:
                    logger.warning(f"[Alarm] 帧编码失败，跳过微信推送: {req.feature_name}")
                    continue

                self.wechat.send(
                    feature_name=req.feature_name,
                    camera_name=req.camera_name,
                    image_jpeg_bytes=buffer.tobytes(),
                    recipients=user,
                )
            except Exception as e:
                logger.warning(f"[Alarm] 微信发送失败: {e}")


# 模块级全局单例
# 大多数场景直接 `from core.alarm import alarm_dispatcher` 使用；
# 需要独立实例时才直接实例化 AlarmDispatcher。
alarm_dispatcher = AlarmDispatcher()