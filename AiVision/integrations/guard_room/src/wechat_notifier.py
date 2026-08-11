# wechat_notifier.py
"""
企业微信报警推送模块。

采用异步队列模式：notify_alarm() 将推送任务入队后立即返回，
不阻塞主循环；后台 _worker 线程依次消费队列并调用 send_message()。

设计决策：
    - 有界队列（maxsize=20）：队列满时 put() 会阻塞，防止网络慢时任务无限积压；
    - on_result 回调：推送结果异步通知调用方，调用方可据此更新报警状态或记录日志；
    - video_path 为空时提前返回：无视频不推送，on_result(False) 通知调用方。
"""
from __future__ import annotations

import queue
import threading
from typing import Callable, Optional

import cv2
import numpy as np

from .wechat_sender import send_message


class WeChatNotifier:
    """企业微信报警推送器（异步队列模式）。

    线程安全：notify_alarm() 可从任意线程调用，推送由专属 _worker 线程串行执行。
    """

    def __init__(self, *, corpid: str, corpsecret: str, agentid: int, queue_size: int = 20):
        """
        Args:
            corpid:     企业微信企业 ID。
            corpsecret: 自建应用 Secret。
            agentid:    自建应用 AgentID。
            queue_size: 推送任务队列上限；队列满时 notify_alarm() 阻塞，防止任务无限积压。
        """
        self.corpid = corpid
        self.corpsecret = corpsecret
        self.agentid = agentid

        # 队列元素：(消息数据, 接收人账号, 结果回调)
        self._queue: queue.Queue[tuple[dict, str, Optional[Callable[[bool], None]]]] = (
            queue.Queue(maxsize=queue_size)
        )
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="wechat-notifier"
        )
        self._thread.start()

    def _worker(self) -> None:
        """推送工作线程：从队列取任务，调用 send_message()，结果通过回调通知调用方。

        send_message() 异常时 success=False，确保 on_result 始终被调用，
        调用方无需处理"回调未触发"的情况。
        """
        while not self._stop_event.is_set():
            try:
                data, alarm_user, on_result = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue    # 超时后检查 stop_event，支持优雅退出

            success = False
            try:
                success = send_message(
                    data,
                    alarm_user,
                    corpid=self.corpid,
                    corpsecret=self.corpsecret,
                    agentid=self.agentid,
                )
            except Exception as e:
                print(f"[WeChatNotifier] 发送异常: {e}")
            finally:
                self._queue.task_done()
                if on_result is not None:
                    try:
                        on_result(success)
                    except Exception as e:
                        print(f"[WeChatNotifier] 回调异常: {e}")  # 回调本身报错不影响主流程

    def notify_alarm(
        self,
        *,
        frame: np.ndarray,
        camera_name: str,
        event_name: str,
        alarm_user: str,
        video_path: Optional[str] = None,
        on_result: Optional[Callable[[bool], None]] = None,
    ) -> None:
        """将报警推送任务加入队列（非阻塞，立即返回）。

        video_path 为空时视为推送条件不满足，直接调用 on_result(False) 后返回，
        不占用队列槽位。

        Args:
            frame:       报警触发时的视频帧（当前仅备用，推送内容以 video_path 为主）。
            camera_name: 消息中显示的摄像头名称。
            event_name:  报警类型字符串，如 "absent"、"phone_use"。
            alarm_user:  接收人账号，多人用 '|' 分隔，"@all" 表示全体。
            video_path:  报警视频片段路径；为空时跳过推送。
            on_result:   推送完成后的回调，参数为 True（成功）/ False（失败）。
        """
        if not video_path:
            if on_result:
                on_result(False)    # 无视频，通知调用方推送未执行
            return

        data = {
            "eventType": event_name,
            "cameraName": camera_name,
            "video_path": video_path,
        }
        self._queue.put((data, alarm_user, on_result))  # 队列满时阻塞，背压保护

    def stop(self) -> None:
        """通知工作线程退出，等待最多 3 秒后返回。

        建议在程序退出前调用，确保队列中剩余任务有机会完成。
        """
        self._stop_event.set()
        self._thread.join(timeout=3)