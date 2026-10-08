"""
alarms/devices/horn.py
IP 喇叭设备控制 — 通过 HTTP API 触发语音告警。
AlarmDispatcher 将播放任务交给 HornRuntimeManager，后台调用 horn.play(event_id) 请求设备播放预录语音
包装登录认证、心跳保活、告警触发(带冷却防抖)。
流程:
    Horn(config)->__init__() -> connect() -> POST/login -> 获得access_key/access_id ->status=True
    HornRuntimeManager -> start_heartbeat() -> 创建后台线程 -> _heart_loop -> 每60秒_send_heart() -> POST/online -> 维持登录
    发生告警 -> AlarmDispatcher -> HornRuntimeManager 播放队列 -> horn.play(event_id) - > 检查一秒设备冷却 -> POST/run_task -> IP喇叭播放预录语音
    系统关闭 -> stop_heatbeat() -> _stop_event.set() -> 心跳线程退出
"""
from __future__ import annotations
from functools import wraps
import threading                  # 心跳线程+play()并发锁
import time                       # 告警冷却时间
import requests                   # requests：HTTP访问IP喇叭

from AiVision.core.logger import logger
from AiVision.core.settings import settings


def _serialized(method):
    """同一设备的认证、心跳和播放串行；停止后的排队调用直接退出。"""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        """串行执行设备网络操作，并以在途计数准确呈现停止中的状态。"""
        with self._io_lock:
            if self._stop_event.is_set():
                return False
            with self._state_lock:
                self._inflight += 1
            try:
                return method(self, *args, **kwargs)
            finally:
                with self._state_lock:
                    self._inflight -= 1
    return guarded


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
        网络操作由 _io_lock 串行化；状态与停止门控由 _state_lock 保护。
    """

    def __init__(self, config: dict, *, connect_on_init: bool = True):
        """接受一台喇叭的配置"""
        # ---- 设备连接参数 ----
        raw_url = str(config.get("horn_url") or "").strip()
        self.url: str = f"{raw_url.rstrip('/')}" + "/" if raw_url else ""          # HTTP API 根地址，末尾须带 /
        # 喇叭设备自己的登录账号密码
        self.username: str = config.get("username", "admin")
        self.password: str = config.get("password") or ""

        # ---- 登录态凭证（connect() 成功后填充）----
        # login后返回access_key和access_id
        self.access_key: str | None = None  # 设备颁发的访问密钥，后续请求携带
        self.access_id: str | None = None   # 设备颁发的访问 ID，与 access_key 配对使用
        self.status: bool = False           # 设备当前是否处于可用状态

        # ---- 心跳保活 ----
        self._heart_interval = settings.alarm.horn_heartbeat_interval_seconds           # 心跳发送间隔（秒），与设备端 Session 超时对齐
        self._stop_event = threading.Event()           # 置位时通知心跳线程退出
        self._heart_thread: threading.Thread | None = None   # 真正启动心跳时，这里会保存心跳线程对象

        # ---- 触发冷却防抖 ----
        # dispatcher也有冷却，它是业务防重复报警，这里是设备保护，防止声音重叠
        self._cooldown = settings.alarm.horn_play_cooldown_seconds        # 两次 play() 之间的最小间隔（秒），防止语音重叠
        self._last_trigger = 0.0   # 上次实际触发的 Unix 时间戳
        self._lock = threading.Lock()  # 保护 _last_trigger 的并发写入
        self._connect_lock = threading.Lock()
        self._io_lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._inflight = 0
        self._state = "connecting"
        self._last_error: str | None = None
        self._last_seen_at: float | None = None
        self._request_timeout = settings.alarm.horn_request_timeout_seconds

        # 直接使用时保留自动登录；管理器与连接测试延迟到后台/请求线程执行网络操作。
        if connect_on_init:
            self.connect()

    @_serialized
    def connect(self) -> bool:
        """
        向设备发起登录请求，获取 access_key / access_id 并更新 status。

        Returns:
            True  — 登录成功，凭证已写入实例属性。
            False — 网络异常或设备返回非 200，status 置 False。

        Note:
            登录失败不抛异常，仅记录警告日志，调用方可稍后重试。
        """
        with self._connect_lock:
            self._set_state("connecting")
            self.access_key = None
            self.access_id = None
            if not self.url:
                self._set_state("failed", "未配置 horn_url，无法登录")
                return False
            if self._stop_event.is_set():
                return False
            try:
                resp = requests.post(
                    self.url + "login",
                    json={"user": self.username, "password": self.password},
                    timeout=self._request_timeout,              # 默认最多等5秒
                    allow_redirects=False,
                )
                # 状态码为200说明登录成功
                if resp.status_code != 200:
                    self._set_state("failed", f"登录失败: HTTP {resp.status_code}")
                    return False
                data = resp.json()              # 返回JSON转Python dict
                access_key = data.get("access_key")
                access_id = data.get("access_id")
                if not access_key or not access_id:
                    self._set_state("failed", "登录响应缺少 access_key/access_id")
                    return False
                with self._state_lock:
                    if self._stop_event.is_set():
                        return False
                    self.access_key = access_key
                    self.access_id = access_id
                return self._set_state("online")
            except Exception:
                self._set_state("failed", "登录请求失败")
                return False

    # ------------------------------------------------------------------ #
    #  心跳保活                                                             #
    # ------------------------------------------------------------------ #
    def start_heartbeat(self):
        """
        启动后台心跳守护线程，每隔 _heart_interval=60 秒向设备发送在线心跳。
        外部调用时，Horn(config)本身只是登录，真正启动心跳的是 HornRuntimeManager
        幂等：线程已存活时重复调用无副作用。
        """
        with self._state_lock:
            # 防止重复启动
            if self._stop_event.is_set() or (self._heart_thread and self._heart_thread.is_alive()):
                return  # 已在运行，跳过
            # 停止信号不再清掉；停用后的实例不可复活，重新启用由管理器创建新实例。
            # 创建线程，守护线程，如果主Aivision进程彻底退出了，它不会为了等中国心跳线程而阻止程序退出
            self._heart_thread = threading.Thread(target=self._heart_loop, daemon=True, name="horn-heartbeat")
            self._heart_thread.start()

    def stop_heartbeat(self, timeout: float = 2.0):
        """
        通知心跳线程退出并等待其结束（最多 2 秒）。

        进程退出前调用，确保后台线程优雅终止；超时后守护线程会随进程自动回收。
        """
        # 告诉线程该结束了
        self.request_stop()
        if self._heart_thread:
            # join的意思：当前线程等一下心跳线程，让它有机会正常退出（最多2秒）
            self._heart_thread.join(timeout=timeout)

    def request_stop(self):
        """立即关闭入口，不等待正在执行的 HTTP；返回后不再安排新的请求。"""
        with self._state_lock:
            self._stop_event.set()
            self.status = False
            self.access_key = self.access_id = None
            self._state = "stopping"

    def snapshot(self) -> dict:
        """在状态锁内返回在线、心跳及错误快照，区分停止中与完全停止。"""
        with self._state_lock:
            alive = bool(self._heart_thread and self._heart_thread.is_alive())
            state = self._state
            if self._stop_event.is_set():
                state = "stopping" if alive or self._inflight else "stopped"
            return {"state": state, "online": self.status,
                    "heartbeat_alive": alive, "last_error": self._last_error,
                    "last_seen_at": self._last_seen_at}

    def _set_state(self, state: str, error: str | None = None) -> bool:
        """停止门控生效后拒绝更新状态，在线时刷新最后成功时间。"""
        with self._state_lock:
            if self._stop_event.is_set():
                return False
            self._state = state
            self.status = state == "online"
            self._last_error = error
            if self.status:
                self._last_seen_at = time.time()
        if error:
            logger.warning(f"[Horn] {error}")
        return self.status

    @_serialized
    def check_connection(self) -> dict:
        """只登录/检查在线；不启动心跳，不播放，不持久化配置。"""
        self._send_heart()
        return self.snapshot()

    def _heart_loop(self):
        """
        心跳线程主循环。

        使用 _stop_event.wait() 代替 time.sleep()，使 stop_heartbeat()
        能立即唤醒线程而无需等满整个 _heart_interval。
        """
        while not self._stop_event.is_set():
            try:
                # 真正向喇叭/online接口发送一次HTTP心跳
                self._send_heart()
            except Exception:
                # 心跳异常不向上抛，标记设备不可用后继续循环，等待下次重试
                self._set_state("offline", "心跳执行失败")
            # 只要其他线程调用_stop_event.set()，它就立即醒，并且退出循环
            self._stop_event.wait(self._heart_interval)  # 可被 stop_heartbeat() 提前唤醒

    @_serialized
    def _send_heart(self):
        """
        向设备端 /online 接口发送一次心跳以维持 Session 活跃。

        设备返回失败时将 status 置 False，下次心跳或 play() 自动重新登录。
        """
        if not self.status and not self.connect():
            logger.warning("[Horn] 心跳重连失败")
            return
        if self._stop_event.is_set():
            return False
        try:
            resp = requests.post(
                self.url + "online",
                json={"access_key": self.access_key, "access_id": self.access_id},
                timeout=self._request_timeout,
                allow_redirects=False,
            )
            if not 200 <= resp.status_code < 300:
                # 心跳被拒，Session 可能已过期
                self._set_state("offline", f"心跳失败: HTTP {resp.status_code}")
            else:
                self._set_state("online")
        except Exception:
            self._set_state("offline", "心跳请求失败")

    # ------------------------------------------------------------------ #
    #  告警触发                                                             #
    # ------------------------------------------------------------------ #
    @_serialized
    def play(self, event_id: str | int, *, expires_at: float | None = None):
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
        if expires_at is not None and time.monotonic() >= expires_at:
            return False
        if not self.status and not self.connect():
            logger.warning("[Horn] 设备离线且重连失败，跳过播放")
            return

        now = time.time()
        with self._lock:
            if now - self._last_trigger < self._cooldown:
                return  # 仍在冷却期，静默丢弃
            self._last_trigger = now  # 占位，防止并发重入

        if self._stop_event.is_set() or (expires_at is not None and time.monotonic() >= expires_at):
            return False
        try:
            resp = requests.post(
                self.url + "run_task",             # 播放预录语音
                json={
                    "access_key": self.access_key,
                    "access_id": self.access_id,
                    "id": event_id,
                },
                timeout=self._request_timeout,
                allow_redirects=False,
            )
            if not 200 <= resp.status_code < 300:
                self._set_state("offline", f"触发告警音失败: HTTP {resp.status_code}")
            else:
                self._set_state("online")
        except Exception:
            self._set_state("offline", "触发告警音请求失败")
