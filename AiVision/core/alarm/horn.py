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
    """
    单个 IP 喇叭设备的控制器。

    生命周期:
        1. __init__ 时自动调用 connect() 完成登录认证，获取 access_key / access_id。
        2. 调用 start_heartbeat() 启动后台保活线程，防止设备端 Session 超时。
        3. 业务层通过 play(event_id) 触发预录制语音；内置冷却防抖避免短时重复播放。
        4. 进程退出前可调用 stop_heartbeat() 优雅终止保活线程。

    线程安全:
        play() 使用 _lock 保护冷却时间戳，可被多线程并发调用。
        心跳线程与业务线程共享 status 标志，status 仅做可见性用途，无需额外同步。
    """

    def __init__(self, config: dict):
        # ---- 设备连接参数 ----
        self.url: str = config.get("horn_url", "")          # HTTP API 根地址，末尾须带 /
        self.username: str = config.get("username", "admin")
        self.password: str = config.get("password", "admin")

        # ---- 登录态凭证（connect() 成功后填充）----
        self.access_key: str | None = None  # 设备颁发的访问密钥，后续请求携带
        self.access_id: str | None = None   # 设备颁发的访问 ID，与 access_key 配对使用
        self.status: bool = False           # 设备当前是否处于可用状态

        # ---- 心跳保活 ----
        self._heart_interval = 60           # 心跳发送间隔（秒），与设备端 Session 超时对齐
        self._stop_event = threading.Event()           # 置位时通知心跳线程退出
        self._heart_thread: threading.Thread | None = None

        # ---- 触发冷却防抖 ----
        self._cooldown = 1.0        # 两次 play() 之间的最小间隔（秒），防止语音重叠
        self._last_trigger = 0.0   # 上次实际触发的 Unix 时间戳
        self._lock = threading.Lock()  # 保护 _last_trigger 的并发写入

        # 构造时立即尝试登录；失败时 status=False，后续 play() 仍可安全调用
        self.connect()

    def connect(self) -> bool:
        """
        向设备发起登录请求，获取 access_key / access_id 并更新 status。

        Returns:
            True  — 登录成功，凭证已写入实例属性。
            False — 网络异常或设备返回非 200，status 置 False。

        Note:
            登录失败不抛异常，仅记录警告日志，调用方可稍后重试。
        """
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

    # ------------------------------------------------------------------ #
    #  心跳保活                                                             #
    # ------------------------------------------------------------------ #

    def start_heartbeat(self):
        """
        启动后台心跳守护线程，每隔 _heart_interval 秒向设备发送在线心跳。

        幂等：线程已存活时重复调用无副作用。
        """
        if self._heart_thread and self._heart_thread.is_alive():
            return  # 已在运行，跳过
        self._stop_event.clear()
        self._heart_thread = threading.Thread(target=self._heart_loop, daemon=True)
        self._heart_thread.start()

    def stop_heartbeat(self):
        """
        通知心跳线程退出并等待其结束（最多 2 秒）。

        进程退出前调用，确保后台线程优雅终止；超时后守护线程会随进程自动回收。
        """
        self._stop_event.set()
        if self._heart_thread:
            self._heart_thread.join(timeout=2)

    def _heart_loop(self):
        """
        心跳线程主循环。

        使用 _stop_event.wait() 代替 time.sleep()，使 stop_heartbeat()
        能立即唤醒线程而无需等满整个 _heart_interval。
        """
        while not self._stop_event.is_set():
            try:
                self._send_heart()
            except Exception:
                # 心跳异常不向上抛，标记设备不可用后继续循环，等待下次重试
                self.status = False
            self._stop_event.wait(self._heart_interval)  # 可被 stop_heartbeat() 提前唤醒

    def _send_heart(self):
        """
        向设备端 /online 接口发送一次心跳以维持 Session 活跃。

        设备返回非 200 时将 status 置 False，下次 play() 调用将因
        access_key 失效而请求报错，需外部重新调用 connect()。
        """
        if not self.status:
            return  # 设备已离线，无需发送（避免用失效凭证刷接口）
        resp = requests.post(
            self.url + "online",
            json={"access_key": self.access_key, "access_id": self.access_id},
            timeout=5,
        )
        if resp.status_code != 200:
            self.status = False  # 心跳被拒，Session 可能已过期

    # ------------------------------------------------------------------ #
    #  告警触发                                                             #
    # ------------------------------------------------------------------ #

    def play(self, event_id: str | int):
        """
        触发设备上预录制的语音任务。

        冷却防抖:
            同一实例在 _cooldown 秒内的重复调用会被静默丢弃，
            防止连续告警事件导致语音叠放或设备过载。

        Args:
            event_id: 设备上预录制的语音任务 ID（由设备管理后台配置）。

        Note:
            HTTP 请求失败时仅记录警告日志，不向调用方抛出异常，
            保证告警链路中单个设备故障不影响其他通道。
        """
        now = time.time()
        with self._lock:
            if now - self._last_trigger < self._cooldown:
                return  # 仍在冷却期，静默丢弃
            self._last_trigger = now  # 占位，防止并发重入

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
