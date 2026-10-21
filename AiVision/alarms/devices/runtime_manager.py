"""进程内喇叭生命周期、提交后热同步和非阻塞播放队列。"""
from __future__ import annotations

import queue
import threading
import time

from AiVision.alarms.devices.horn import Horn
from AiVision.alarms.devices.sip_service import horn_sip_service
from AiVision.core.logger import logger
from AiVision.core.settings import settings


def _load_configs(horn_id=None):
    """延迟导入服务并读取内部运行配置，避免模块初始化的循环依赖。"""
    from .service import horn_service
    return horn_service.runtime_configs(horn_id)


class HornRuntimeManager:
    """管理设备认证和心跳生命周期，以有界队列异步播放语音。"""
    def __init__(self, config_loader=None, horn_factory=Horn):
        """注入配置读取和设备工厂，构造时不启动网络操作或线程。"""
        self._load = config_loader or _load_configs
        self._factory = horn_factory
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._entries: dict[int, tuple[dict, Horn]] = {}
        self._retired: list[tuple[int, Horn]] = []
        self._failures: set[int] = set()
        self._sync_failed = False
        self._active = False
        self._stop = threading.Event()
        self._queue = queue.Queue(maxsize=settings.alarm.horn_queue_size)
        self._pending: dict[int, Horn] = {}
        self._threads: list[threading.Thread] = []

    @staticmethod
    def _credentials(config):
        """提取设备认证所需字段，仅供内部实例比较和连接。"""
        return {"id": config.get("id"), "horn_url": config["url"], "username": config["username"],
                "password": config["password"], "sip": config.get("sip")}

    def start(self):
        """创建本轮播放和同步线程，再读取已提交设备配置。"""
        horn_sip_service.start()
        with self._sync_lock:
            with self._lock:
                if self._active:
                    return
                self._active = True
                self._stop = threading.Event()
                self._queue = queue.Queue(maxsize=settings.alarm.horn_queue_size)
                self._pending.clear()
                stop, jobs = self._stop, self._queue
                self._threads = [
                    threading.Thread(target=self._reconcile_loop, args=(stop,), daemon=True, name="horn-reconcile"),
                    *(threading.Thread(target=self._play_loop, args=(stop, jobs), daemon=True, name=f"horn-playback-{index}")
                      for index in range(settings.alarm.horn_playback_workers)),
                ]
                for thread in self._threads:
                    thread.start()
        self.sync()

    def _retire(self, horn_id):
        """立即关闭旧设备入口并保留引用，供停止状态查询和资源回收。"""
        entry = self._entries.pop(horn_id, None)
        self._pending.pop(horn_id, None)
        horn_sip_service.server.remove_device(horn_id)
        if entry:
            entry[1].request_stop()
            self._retired.append((horn_id, entry[1]))

    def sync(self, horn_id: int | None = None):
        """仅在事务提交后调用；读取最新提交值，串行处理乱序的更新通知。"""
        with self._sync_lock:
            with self._lock:
                if not self._active:
                    return
            try:
                configs = {cfg["id"]: cfg for cfg in self._load(horn_id)}
                with self._lock:
                    ids = {horn_id} if horn_id is not None else set(self._entries) | set(configs) | self._failures
                    for device_id in ids:
                        cfg = configs.get(device_id)
                        old = self._entries.get(device_id)
                        try:
                            if cfg is None or not cfg["enable"]:
                                self._retire(device_id)
                            elif old is None or self._credentials(old[0]) != self._credentials(cfg):
                                self._retire(device_id)
                                horn_sip_service.server.set_device(cfg)
                                horn = self._factory(self._credentials(cfg), connect_on_init=False)
                                self._entries[device_id] = (cfg, horn)
                                horn.start_heartbeat()
                            else:
                                horn_sip_service.server.set_device(cfg)
                                self._entries[device_id] = (cfg, old[1])
                            self._failures.discard(device_id)
                        except Exception:
                            # 一台喇叭的地址或身份错误不能中断其他设备的报警。
                            self._retire(device_id)
                            self._failures.add(device_id)
                            logger.warning(f"[HornRuntime] 喇叭 {device_id} 配置同步失败，等待重试")
                    if horn_id is None:
                        self._sync_failed = False
                    self._retired = [(key, horn) for key, horn in self._retired
                                     if horn.snapshot()["state"] == "stopping"]
            except Exception:
                # 配置已提交但同步失败时先关闭旧实例，避免停用设备继续播放；后台定期重试。
                with self._lock:
                    if horn_id is None:
                        self._sync_failed = True
                    ids = {horn_id} if horn_id is not None else set(self._entries)
                    for device_id in ids:
                        self._retire(device_id)
                        self._failures.add(device_id)
                logger.warning("[HornRuntime] 配置同步失败，已关闭旧实例，等待重试")

    def _reconcile_loop(self, stop):
        """周期重新核对数据库配置，使失败同步能够自动重试。"""
        while not stop.wait(settings.alarm.horn_reconcile_interval_seconds):
            if stop.is_set():
                return
            self.sync()

    def enqueue_play(self, horn_id: int, event_id: str | int) -> bool:
        """非阻塞接收播放；同台在播任务合并，队列已满或设备不可用返回 False。"""
        with self._lock:
            entry = self._entries.get(horn_id)
            if not self._active or entry is None:
                return False
            if self._pending.get(horn_id) is entry[1]:
                # 同台喇叭只保留一项待播或在播任务，避免长音频占满所有工作线程。
                return True
            try:
                self._queue.put_nowait((horn_id, entry[1], event_id, time.monotonic()))
                self._pending[horn_id] = entry[1]
                return True
            except queue.Full:
                logger.warning("[HornRuntime] 播放队列已满，本次喇叭告警跳过")
                return False

    def _play_loop(self, stop, jobs):
        """只执行未过期且仍对应当前设备实例的任务，防止配置更换后播放旧任务。"""
        while not stop.is_set():
            try:
                horn_id, horn, event_id, queued_at = jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                with self._lock:
                    entry = self._entries.get(horn_id)
                    valid = (not stop.is_set() and self._active and entry is not None
                             and entry[1] is horn)
                if valid and time.monotonic() - queued_at <= settings.alarm.horn_queue_ttl_seconds:
                    horn.play(event_id, expires_at=queued_at + settings.alarm.horn_queue_ttl_seconds)
            except Exception:
                logger.warning("[HornRuntime] 播放任务失败")
            finally:
                with self._lock:
                    if self._pending.get(horn_id) is horn:
                        self._pending.pop(horn_id, None)
                jobs.task_done()

    def status(self, config: dict) -> dict:
        """综合当前实例、同步错误和退役实例，生成设备的准确生命周期状态。"""
        with self._lock:
            device_id = config["id"]
            entry = self._entries.get(device_id)
            if entry is not None:
                return entry[1].snapshot()
            if (device_id in self._failures or self._sync_failed) and self._active:
                return {"state": "failed", "last_error": "运行配置同步失败，等待重试"}
            if any(key == device_id and horn.snapshot()["state"] == "stopping"
                   for key, horn in self._retired):
                return {"state": "stopping"}
            return {"state": "disabled" if not config["enable"] else
                    ("pending" if self._active else "not_started")}

    def test_connection(self, config: dict) -> dict:
        """优先复用同凭据运行实例，否则创建不启动心跳的临时连接探测。"""
        credentials = self._credentials(config)
        with self._lock:
            entry = self._entries.get(config.get("id"))
            horn = entry[1] if entry and self._credentials(entry[0]) == credentials else None
        if horn is not None:
            # 已运行设备复用认证会话，避免测试登录挤掉现场心跳的会话。
            result = horn.check_connection()
            if result:
                return result
            return horn.snapshot()
        probe = self._factory(credentials, connect_on_init=False)
        try:
            return probe.check_connection()
        finally:
            # 独立测试实例从未启动心跳，不加入运行列表，不写配置。
            probe.request_stop()

    def stop(self):
        """关闭设备入口、丢弃待播任务，并在共享期限内等待后台与在途请求结束。"""
        with self._sync_lock:
            with self._lock:
                self._active = False
                self._stop.set()
                self._pending.clear()
                for horn_id in list(self._entries):
                    self._retire(horn_id)
                retired, threads = list(self._retired), list(self._threads)
                while True:
                    try:
                        self._queue.get_nowait()
                        self._queue.task_done()
                    except queue.Empty:
                        break
        deadline = time.monotonic() + 2.0
        for _, horn in retired:
            horn.stop_heartbeat(timeout=max(0.0, deadline - time.monotonic()))
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads) or any(
            horn.snapshot()["state"] == "stopping" for _, horn in retired
        ):
            logger.warning("[HornRuntime] 停止门控已关闭，等待在途 HTTP 请求结束")
        horn_sip_service.server.stop()

    def test_play(self, config: dict, audio_id: int) -> dict:
        """试播复用正式播放路径，不写检测绑定、不绕过设备停用和停止门控。"""
        credentials = self._credentials(config)
        with self._lock:
            entry = self._entries.get(config["id"])
            horn = entry[1] if entry and self._credentials(entry[0]) == credentials else None
        probe = horn is None
        if probe:
            horn = self._factory(credentials, connect_on_init=False)
        try:
            success = bool(horn.play(audio_id, preview=True))
            return {"success": success, "runtime": horn.snapshot()}
        finally:
            if probe:
                horn.request_stop()


horn_runtime_manager = HornRuntimeManager()
