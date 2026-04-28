# wechat_notifier.py
from __future__ import annotations

import base64
import queue
import threading
from typing import Optional,Callable

import cv2
import numpy as np

from .wechat_sender import send_message


from typing import Callable, Optional

class WeChatNotifier:
    def __init__(self, *, corpid, corpsecret, agentid, queue_size=20):
        self.corpid = corpid
        self.corpsecret = corpsecret
        self.agentid = agentid
        # 队列里放:(data, alarm_user, on_result 回调)
        self._queue: queue.Queue[tuple[dict, str, Optional[Callable[[bool], None]]]] = queue.Queue(maxsize=queue_size)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="wechat-notifier")
        self._thread.start()

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                data, alarm_user, on_result = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

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
                success = False
            finally:
                self._queue.task_done()
                if on_result is not None:
                    try:
                        on_result(success)
                    except Exception as e:
                        print(f"[WeChatNotifier] 回调异常: {e}")

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
        if not video_path:
            if on_result:
                on_result(False)
            return

        data = {
            "eventType": event_name,
            "cameraName": camera_name,
            "video_path": video_path,
        }
        self._queue.put((data, alarm_user, on_result))

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=3)