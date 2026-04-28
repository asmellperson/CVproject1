"""
core/alarm/horn.py
IP 喇叭设备控制 — 通过 HTTP API 触发语音告警。

包装登录认证、心跳保活、告警触发(带冷却防抖)。
"""
from __future__ import annotations
import threading
import time
import requests

from core.logger import logger


class Horn:
    """单个 IP 喇叭设备的控制器"""

    def __init__(self, config: dict):
        self.url: str = config.get("horn_url", "")
        self.username: str = config.get("username", "admin")
        self.password: str = config.get("password", "admin")
        self.access_key: str | None = None
        self.access_id: str | None = None
        self.status: bool = False

        self._heart_interval = 60
        self._stop_event = threading.Event()
        self._heart_thread: threading.Thread | None = None

        self._cooldown = 1.0
        self._last_trigger = 0.0
        self._lock = threading.Lock()

        self.connect()

    def connect(self) -> bool:
        try:
            resp = requests.post(
                self.url + "login",
                json={"user": self.username, "password": self.password},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                self.access_key = data.get("access_key")
                self.access_id = data.get("access_id")
                self.status = True
                return True
        except Exception as e:
            logger.warning(f"[Horn] 登录失败 {self.url}: {e}")
        self.status = False
        return False

    # ---------- Heartbeat ----------

    def start_heartbeat(self):
        if self._heart_thread and self._heart_thread.is_alive():
            return
        self._stop_event.clear()
        self._heart_thread = threading.Thread(target=self._heart_loop, daemon=True)
        self._heart_thread.start()

    def stop_heartbeat(self):
        self._stop_event.set()
        if self._heart_thread:
            self._heart_thread.join(timeout=2)

    def _heart_loop(self):
        while not self._stop_event.is_set():
            try:
                self._send_heart()
            except Exception:
                self.status = False
            self._stop_event.wait(self._heart_interval)

    def _send_heart(self):
        if not self.status:
            return
        resp = requests.post(
            self.url + "online",
            json={"access_key": self.access_key, "access_id": self.access_id},
            timeout=5,
        )
        if resp.status_code != 200:
            self.status = False

    # ---------- Trigger ----------

    def play(self, event_id: str | int):
        """触发指定告警音 — 带冷却防抖,event_id 是设备上预录制的语音任务 ID"""
        now = time.time()
        with self._lock:
            if now - self._last_trigger < self._cooldown:
                return
            self._last_trigger = now
        try:
            requests.post(
                self.url + "run_task",
                json={
                    "access_key": self.access_key,
                    "access_id": self.access_id,
                    "id": event_id,
                },
                timeout=5,
            )
        except Exception as e:
            logger.warning(f"[Horn] 触发告警音失败: {e}")
