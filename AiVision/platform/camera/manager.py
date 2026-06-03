"""
platform/camera/manager.py
摄像头进程生命周期管理 — 替代旧 CapManager.start_product / stop_product。

职责:
    - 启动/停止单路或所有摄像头采集进程
    - 维护跨进程共享配置(Manager.dict + Manager.Value)
    - 启动后通知 FrameReaderRegistry 注册共享内存
"""
from __future__ import annotations
import threading
import time

from core.logger import logger
from .runtime import CameraRuntime
from .frame_reader import frame_reader_registry


class CameraManager:
    """所有摄像头采集进程的生命周期管理"""

    def __init__(self, manager):
        """manager 是 multiprocessing.Manager() 实例,用来创建跨进程共享对象"""
        self._mp_manager = manager
        # shm_name → (Manager.dict, active_index, frame_seq) — 跨进程配置 + 双缓冲索引 + 帧序号
        self._shared_configs: dict[str, tuple] = {}
        # shm_name → CameraRuntime
        self._runtimes: dict[str, CameraRuntime] = {}
        self._watchdog_running = False
        self._watchdog_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stale_seconds = 15.0

    def initialize_configs(self, camera_configs: list[dict]):
        """把摄像头配置列表转成跨进程共享 Manager.dict"""
        for cfg in camera_configs:
            shm_name = cfg["shm_name"]
            self._shared_configs[shm_name] = (
                self._mp_manager.dict(cfg),
                self._mp_manager.Value("i", 0),
                self._mp_manager.Value("i", 0),
            )
        logger.info(f"[CameraManager] 初始化了 {len(self._shared_configs)} 个摄像头共享配置")

    def start_all(self):
        """启动所有已配置且 enable=True 的摄像头"""
        for shm_name, (cfg, active_index, frame_seq) in self._shared_configs.items():
            self._start_one(shm_name, cfg, active_index, frame_seq)
            time.sleep(0.3)  # 错开启动峰值
        self._start_watchdog()
        logger.info(f"[CameraManager] 启动了 {len(self._runtimes)} 个采集进程")

    def stop_all(self):
        self._stop_watchdog()
        for shm_name in list(self._runtimes.keys()):
            self.stop_camera(shm_name)
        logger.info("[CameraManager] 所有采集进程已停止")

    def start_camera(self, shm_name: str) -> bool:
        """单独启动一个摄像头(配置必须已在 _shared_configs 中)"""
        if shm_name in self._runtimes:
            return True
        item = self._shared_configs.get(shm_name)
        if item is None:
            logger.warning(f"[CameraManager] 未知摄像头 shm_name={shm_name}")
            return False
        cfg, active_index, frame_seq = item
        return self._start_one(shm_name, cfg, active_index, frame_seq)

    def stop_camera(self, shm_name: str):
        with self._lock:
            runtime = self._runtimes.pop(shm_name, None)
        if runtime is None:
            return
        frame_reader_registry.unregister(shm_name)
        runtime.stop()
        logger.info(f"[CameraManager] 摄像头已停止: {shm_name}")
        time.sleep(0.3)

    def update_camera_config(self, shm_name: str, new_cfg: dict):
        """运行时更新摄像头共享配置 — 子进程会看到最新值"""
        item = self._shared_configs.get(shm_name)
        if item is None:
            self._shared_configs[shm_name] = (
                self._mp_manager.dict(new_cfg),
                self._mp_manager.Value("i", 0),
                self._mp_manager.Value("i", 0),
            )
        else:
            shared_dict, _, _ = item
            shared_dict.update(new_cfg)

    # ---------- 状态查询(供 Orchestrator/API 用) ----------

    def is_running(self, shm_name: str) -> bool:
        return shm_name in self._runtimes

    def list_running(self) -> list[str]:
        return list(self._runtimes.keys())

    # ---------- 内部 ----------

    def _start_one(self, shm_name: str, cfg, active_index, frame_seq) -> bool:
        if not cfg.get("enable", True):
            logger.info(f"[CameraManager] 跳过禁用的摄像头: {shm_name}")
            return False

        with self._lock:
            if shm_name in self._runtimes:
                return True

        frame_seq.value = 0
        runtime = CameraRuntime(dict(cfg), active_index, frame_seq)
        if not runtime.status:
            logger.warning(f"[CameraManager] 摄像头初始化失败 {shm_name}: {runtime.msg}")
            return False

        try:
            runtime.start(active_index)
        except TimeoutError as e:
            logger.warning(f"[CameraManager] {e}")
            return False

        # 写回实际分辨率(子进程探测到的真实尺寸)
        cfg["shape"] = runtime.shape

        # 注册到统一帧读取器
        frame_reader_registry.register(shm_name, runtime.shape, active_index, frame_seq)

        with self._lock:
            self._runtimes[shm_name] = runtime
        return True

    def _start_watchdog(self):
        if self._watchdog_running:
            return
        self._watchdog_running = True
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="camera-manager-watchdog",
        )
        self._watchdog_thread.start()

    def _stop_watchdog(self):
        self._watchdog_running = False
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=2)
            self._watchdog_thread = None

    def _watchdog_loop(self):
        while self._watchdog_running:
            time.sleep(5.0)
            now = time.time()
            with self._lock:
                items = list(self._runtimes.items())
            for shm_name, runtime in items:
                if runtime is None:
                    continue
                proc_dead = runtime.proc is None or not runtime.proc.is_alive()
                updated_at = frame_reader_registry.latest_frame_times.get(shm_name, 0.0)
                stale = updated_at > 0 and now - updated_at > self._stale_seconds
                if not proc_dead and not stale:
                    continue
                reason = "采集进程退出" if proc_dead else f"画面停更 {now - updated_at:.1f}s"
                logger.warning(f"[CameraManager] 摄像头异常,准备重启 {shm_name}: {reason}")
                self._restart_one(shm_name)

    def _restart_one(self, shm_name: str):
        item = self._shared_configs.get(shm_name)
        if item is None:
            return
        cfg, active_index, frame_seq = item
        self.stop_camera(shm_name)
        self._start_one(shm_name, cfg, active_index, frame_seq)
