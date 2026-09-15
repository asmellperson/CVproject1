"""进程内喇叭生命周期、提交后热同步和非阻塞播放队列。"""
from __future__ import annotations

import queue
import threading
import time

from AiVision.alarms.devices.horn import Horn
from AiVision.core.logger import logger
from AiVision.core.settings import settings


def _load_configs(horn_id=None):
    from .service import horn_service
    return horn_service.runtime_configs(horn_id)


class HornRuntimeManager:
    def __init__(self, config_loader=None, horn_factory=Horn):
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
        self._threads: list[threading.Thread] = []

    @staticmethod
    def _credentials(config):
        return {"horn_url": config["url"], "username": config["username"],
                "password": config["password"]}

    def start(self):
        with self._sync_lock:
            with self._lock:
                if self._active:
                    return
                self._active = True
                self._stop = threading.Event()
                self._queue = queue.Queue(maxsize=settings.alarm.horn_queue_size)
                stop, jobs = self._stop, self._queue
                self._threads = [
                    threading.Thread(target=self._play_loop, args=(stop, jobs), daemon=True, name="horn-playback"),
                    threading.Thread(target=self._reconcile_loop, args=(stop,), daemon=True, name="horn-reconcile"),
                ]
                for thread in self._threads:
                    thread.start()
        self.sync()

    def _retire(self, horn_id):
        entry = self._entries.pop(horn_id, None)
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
                        if cfg is None or not cfg["enable"]:
                            self._retire(device_id)
                        elif old is None or self._credentials(old[0]) != self._credentials(cfg):
                            self._retire(device_id)
                            horn = self._factory(self._credentials(cfg), connect_on_init=False)
                            self._entries[device_id] = (cfg, horn)
                            horn.start_heartbeat()
                        else:
                            self._entries[device_id] = (cfg, old[1])
                        self._failures.discard(device_id)
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
        while not stop.wait(settings.alarm.horn_reconcile_interval_seconds):
            if stop.is_set():
                return
            self.sync()

    def enqueue_play(self, horn_id: int, event_id: str | int) -> bool:
        with self._lock:
            entry = self._entries.get(horn_id)
            if not self._active or entry is None:
                return False
            try:
                self._queue.put_nowait((horn_id, entry[1], event_id, time.monotonic()))
                return True
            except queue.Full:
                logger.warning("[HornRuntime] 播放队列已满，本次喇叭告警跳过")
                return False

    def _play_loop(self, stop, jobs):
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
                jobs.task_done()

    def status(self, config: dict) -> dict:
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
        with self._sync_lock:
            with self._lock:
                self._active = False
                self._stop.set()
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


horn_runtime_manager = HornRuntimeManager()
