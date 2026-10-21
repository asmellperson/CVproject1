"""
alarms/devices/horn.py
IP 喇叭控制器，按设备配置播放服务器 AAC 或设备内置音频。
AlarmDispatcher 经 HornRuntimeManager 调用 play(event_id)，SIP 模式读取服务器素材并发送 RTP，
设备音频模式使用 ISAPI 素材 ID。连接测试只读；后台运行和试播负责同步 SIP 参数。
"""
from __future__ import annotations
from functools import wraps
import threading                  # 心跳线程+play()并发锁
import time                       # 告警冷却时间

from AiVision.alarms.devices.hikvision import HikvisionSpeakerClient, HikvisionSpeakerError
from AiVision.alarms.devices.audio import horn_audio_service, HornAudioError
from AiVision.alarms.devices.schema import DEFAULT_VOLUME_PERCENT
from AiVision.alarms.devices.sip_protocol import SipAudioError
from AiVision.alarms.devices.sip_service import horn_sip_service
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
        1. __init__ 时自动调用 connect()，通过 ISAPI 摘要认证读取设备信息。
        2. 调用 start_heartbeat() 启动周期在线检查线程。
        3. 业务层通过 play(event_id) 播放所选素材；SIP 串行发送，设备素材保留保护冷却。
        4. 进程退出前可调用 stop_heartbeat() 优雅终止保活线程。

    线程安全:
        play() 使用 _lock 保护冷却时间戳，可被多线程并发调用。
        网络操作由 _io_lock 串行化；状态与停止门控由 _state_lock 保护。
    """

    def __init__(self, config: dict, *, connect_on_init: bool = True):
        """接受一台喇叭的配置"""
        # ---- 设备连接参数 ----
        raw_url = str(config.get("horn_url") or "").strip()
        self.url: str = f"{raw_url.rstrip('/')}" + "/" if raw_url else ""
        # 喇叭设备自己的登录账号密码
        self.username: str = config.get("username", "admin")
        self.password: str = config.get("password") or ""
        self._id = config.get("id")
        self._sip = config.get("sip")
        self._sip_generation = -1
        self._sip_ready = False
        self._playing = False

        self.status: bool = False           # 设备当前是否处于可用状态

        # ---- 心跳保活 ----
        self._heart_interval = settings.alarm.horn_heartbeat_interval_seconds
        self._stop_event = threading.Event()           # 置位时通知心跳线程退出
        self._heart_thread: threading.Thread | None = None   # 真正启动心跳时，这里会保存心跳线程对象

        # ---- 触发冷却防抖 ----
        # SIP 发送完成才返回；只有无法取得播放完成回执的设备素材模式使用保护间隔。
        self._cooldown = settings.alarm.horn_play_cooldown_seconds
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
        self._client = HikvisionSpeakerClient(self.url, self.username, self.password, self._request_timeout)

        # 直接使用时保留自动登录；管理器与连接测试延迟到后台/请求线程执行网络操作。
        if connect_on_init:
            self.connect()

    @_serialized
    def connect(self) -> bool:
        """
        使用海康 ISAPI 摘要认证读取设备信息并更新 status。

        Returns:
            True  — 认证通过，设备信息有效，在线状态已更新。
            False — 网络、认证或设备信息响应无效，status 置 False。

        Note:
            登录失败不抛异常，仅记录警告日志，调用方可稍后重试。
        """
        with self._connect_lock:
            self._set_state("connecting")
            if not self.url:
                self._set_state("failed", "未配置 horn_url，无法登录")
                return False
            if self._stop_event.is_set():
                return False
            try:
                self._client.check_connection()
                return self._set_state("online")
            except HikvisionSpeakerError as exc:
                self._set_state("failed", str(exc))
                return False
            except Exception as exc:
                self._set_state("failed", f"设备认证执行失败（{type(exc).__name__}）")
                return False

    # ------------------------------------------------------------------ #
    #  心跳保活                                                             #
    # ------------------------------------------------------------------ #
    def start_heartbeat(self):
        """
        启动后台线程，检查设备在线状态并同步平台保存的 SIP 参数。
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
            self._state = "stopping"
            self._sip_ready = False

    def snapshot(self) -> dict:
        """在状态锁内返回在线、心跳及错误快照，区分停止中与完全停止。"""
        with self._state_lock:
            alive = bool(self._heart_thread and self._heart_thread.is_alive())
            state = self._state
            if self._stop_event.is_set():
                state = "stopping" if alive or self._inflight else "stopped"
            return {"state": state, "online": self.status,
                    "heartbeat_alive": alive, "last_error": self._last_error,
                    "last_seen_at": self._last_seen_at,
                    "sip_ready": self._sip_ready, "playing": self._playing}

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
                self._send_heart()
                if self.status and self._sip:
                    self.prepare_sip()
            except (SipAudioError, HikvisionSpeakerError) as exc:
                self._sip_ready = False
                self._set_state("offline", str(exc))
            except Exception as exc:
                self._set_state("offline", f"在线检查执行失败（{type(exc).__name__}）")
            # 只要其他线程调用_stop_event.set()，它就立即醒，并且退出循环
            self._stop_event.wait(self._heart_interval)  # 可被 stop_heartbeat() 提前唤醒

    @_serialized
    def _send_heart(self):
        """
        读取设备信息检查在线状态，失败后由后续检查或播放尝试恢复连接。
        """
        if not self.status:
            return self.connect()
        if self._stop_event.is_set():
            return False
        try:
            self._client.check_connection()
            return self._set_state("online")
        except HikvisionSpeakerError as exc:
            self._set_state("offline", str(exc))
        except Exception as exc:
            self._set_state("offline", f"在线检查执行失败（{type(exc).__name__}）")
        return False

    @_serialized
    def prepare_sip(self):
        """仅后台启用或明确试播时同步设备；无声连接测试仍只读取设备信息。"""
        if not self._sip:
            return True
        self._sip_ready = False
        server = horn_sip_service.ensure_started()
        if not server["running"]:
            raise SipAudioError("请先在喇叭配置中设置并启用 SIP 服务")
        horn_sip_service.server.set_device({"id": self._id, "url": self.url, "enable": True, "sip": self._sip})
        generation = horn_sip_service.server.generation
        registered = horn_sip_service.server.registered(self._id)
        if generation != self._sip_generation or not registered:
            self._client.configure_sip(server, self._sip, restart_registration=not registered)
        # 设备应用 SIP 配置需要时间，注册完成前发 INVITE 会被设备拒绝。
        deadline = time.monotonic() + settings.alarm.horn_sip_call_timeout
        while not horn_sip_service.server.registered(self._id):
            if self._stop_event.wait(0.1):
                return False
            if time.monotonic() >= deadline:
                raise SipAudioError(horn_sip_service.server.registration_error(self._id))
        # 完成注册才记住同步代次，失败后的心跳和试播仍会主动恢复注册。
        self._sip_generation = generation
        with self._state_lock:
            self._sip_ready = not self._stop_event.is_set()
        return self._sip_ready

    # ------------------------------------------------------------------ #
    #  告警触发                                                             #
    # ------------------------------------------------------------------ #
    @_serialized
    def play(self, event_id: str | int, *, expires_at: float | None = None, preview: bool = False):
        """
        按设备的播放模式执行服务器素材或设备内置语音。

        SIP 音频发送完成才返回，由运行队列保证串行；设备内置音频的播放时长
        无法从触发接口取得，保留该模式的设备保护间隔。

        Args:
            event_id: SIP 模式为服务器音频 ID，设备模式为 ISAPI 素材 ID。

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
            if not preview and not self._sip and now - self._last_trigger < self._cooldown:
                return  # 仍在冷却期，静默丢弃
            self._last_trigger = now  # 占位，防止并发重入

        if self._stop_event.is_set() or (expires_at is not None and time.monotonic() >= expires_at):
            return False
        try:
            with self._state_lock:
                self._playing = True
            if self._sip:
                audio = horn_audio_service.read_encoded(
                    int(event_id), volume_percent=self._sip.get("volume_percent", DEFAULT_VOLUME_PERCENT),
                )
                self.prepare_sip()
                if self._stop_event.is_set():
                    return False
                horn_sip_service.server.play(self._id, audio, self._stop_event, expires_at=expires_at)
            else:
                self._client.play(event_id)
            return self._set_state("online")
        except (HikvisionSpeakerError, SipAudioError, HornAudioError) as exc:
            self._set_state("offline", str(exc))
        except Exception as exc:
            self._set_state("offline", f"语音播放执行失败（{type(exc).__name__}）")
        finally:
            with self._state_lock:
                self._playing = False
        return False
