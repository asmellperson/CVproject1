"""
platform/camera/runtime_manager.py
多台摄像头怎么统一管理

职责:
    - 启动/停止单路或所有摄像头采集进程
    - 维护跨进程共享配置(Manager.dict + Manager.Value)
    - 启动后通知 FrameReaderRegistry 注册共享内存
函数：
    _shared_confogs:应该有哪些摄像头
    _runtimes: 当前已经运行哪些camera
    start_camera()
    _start_one()
    CameraRuntime
    FrameReader注册
    stop_camera(): 注销FrameReader、停止CameraRuntime
    remove_camera_config():Camera彻底移除
    watchdog（每五秒）:
        收camera子进程异常事件
        检查采集进程是否死亡
        检查画面是否停更
        故障——》重建CameraRuntime
        应运行但没运行 -> 每30秒重置
Camera有两级修复：
    第一级：
        CameraRuntime
            ffmpeg坏了-> 重启ffmpeg
    第二级：
        CameraRuntimeManager：
            整个采集进程坏了/画面停更 -> 重建CameraRuntime
camera的跨进程共享对象：
    有双帧索引，active_index、frame_seq(当前是第几帧)、Manager.dict(cfg):Camera期望配置（Runtime使用启动时快照）
共享内存SharedMemory：
    只有当前图片的像素信息。其他都没有
"""
from __future__ import annotations
import threading
import time
from typing import Callable

from AiVision.core.logger import logger
from .runtime import CameraRuntime
from .frame_reader import frame_reader_registry

class CameraRuntimeManager:
    """所有摄像头采集进程的生命周期管理"""

    def __init__(self, manager):
        """manager 是 multiprocessing.Manager() 实例,用来创建跨进程共享对象"""
        self._mp_manager = manager
        # shm_name → (Manager.dict, active_index, frame_seq) — 跨进程配置 + 双缓冲索引 + 帧序号（启动应该运行哪些Camera，配置是什么）
        self._shared_configs: dict[str, tuple] = {}
        # shm_name → 当前已经启动了的CameraRuntime
        self._runtimes: dict[str, CameraRuntime] = {}
        self._watchdog_running = False
        self._stopping = False
        self._watchdog_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._camera_locks: dict[str, threading.RLock] = {}
        self._stale_seconds = 15.0
        self._restart_retry_interval = 30.0
        self._last_start_attempts: dict[str, float] = {}
        self._runtime_started_at: dict[str, float] = {}
        self._runtime_alert_handler: Callable[[str, str, str, str], None] | None = None
        self._runtime_alert_cooldown = 300.0
        self._last_runtime_alerts: dict[tuple[str, str], float] = {}
        self._runtime_event_queue = manager.Queue(maxsize=200)

    def initialize_configs(self, camera_configs: list[dict]):
        """把Orchestrator给过来的摄像头配置列表转成跨进程共享 Manager.dict"""
        for cfg in camera_configs:
            shm_name = cfg["shm_name"]
            self._shared_configs[shm_name] = (
                self._mp_manager.dict(cfg),
                self._mp_manager.Value("i", 0),
                self._mp_manager.Value("i", 0),
            )
        logger.info(f"[CameraRuntimeManager] 初始化了 {len(self._shared_configs)} 个摄像头共享配置")

    def start_all(self):
        """启动所有已配置且 enable=True 的摄像头
        逻辑：
            遍历所有_shared_configs -》 _start_one() -》 每台间隔0.3秒 -》 全部处理完 -》 启动watchdog
        """
        self._stopping = False
        for shm_name, (cfg, active_index, frame_seq) in list(self._shared_configs.items()):
            self._start_one(shm_name, cfg, active_index, frame_seq)
            time.sleep(0.3)  # 错开启动峰值
        self._start_watchdog()
        logger.info(f"[CameraRuntimeManager] 启动了 {len(self._runtimes)} 个采集进程")

    def stop_all(self):
        """
        逻辑：
            先禁止新启动并停止watchdog -》 遍历所有已配置/运行中的Camera -》 stop_camera
        """
        self._stopping = True
        self._stop_watchdog()
        for shm_name in set(self._shared_configs) | set(self._runtimes):
            self.stop_camera(shm_name)
        logger.info("[CameraRuntimeManager] 所有采集进程已停止")

    def start_camera(self, shm_name: str) -> bool:
        """单独启动一个摄像头(配置必须已在 _shared_configs 中)"""
        if shm_name in self._runtimes:
            return True
        item = self._shared_configs.get(shm_name)
        if item is None:
            logger.warning(f"[CameraRuntimeManager] 未知摄像头 shm_name={shm_name}")
            return False
        cfg, active_index, frame_seq = item
        # 单独启动一台摄像头的逻辑在_start_one函数里
        return self._start_one(shm_name, cfg, active_index, frame_seq)

    def stop_camera(self, shm_name: str):
        ""
        with self._camera_lock(shm_name):
            with self._lock:
                # 先从运行列表中移除
                runtime = self._runtimes.pop(shm_name, None)
                self._runtime_started_at.pop(shm_name, None)
            try:
                # 通知不要再从它的共享内存中读帧
                frame_reader_registry.unregister(shm_name)
            finally:
                if runtime is not None:
                    try:
                        # 真正的采集进程退出
                        runtime.stop()
                    except Exception:
                        with self._lock:
                            self._runtimes[shm_name] = runtime
                        raise
            if runtime is not None:
                logger.info(f"[CameraRuntimeManager] 摄像头已停止: {shm_name}")
                time.sleep(0.3)

    def remove_camera_config(self, shm_name: str):
        """彻底移除摄像头运行配置,用于删除摄像头后避免 watchdog 再次拉起。"""
        with self._camera_lock(shm_name):
            with self._lock:
                # 删除运行配置
                self._shared_configs.pop(shm_name, None)
                self._last_start_attempts.pop(shm_name, None)
                for key in list(self._last_runtime_alerts):
                    if key[0] == shm_name:
                        self._last_runtime_alerts.pop(key, None)
            self.stop_camera(shm_name)

    def update_camera_config(self, shm_name: str, new_cfg: dict):
        """更新期望配置；CameraRuntime 持有 dict 快照，新值在下次启动或重启时生效。"""
        with self._camera_lock(shm_name):
            with self._lock:
                item = self._shared_configs.get(shm_name)
                if item is None:
                    self._shared_configs[shm_name] = (
                        self._mp_manager.dict(new_cfg),
                        self._mp_manager.Value("i", 0),
                        self._mp_manager.Value("i", 0),
                    )
                else:
                    shared_dict, _, _ = item
                    # 更新Manager.dict
                    shared_dict.update(new_cfg)

    # ---------- 状态查询(供 Orchestrator/API 用) ----------
    def is_running(self, shm_name: str) -> bool:
        return shm_name in self._runtimes

    def list_running(self) -> list[str]:
        return list(self._runtimes.keys())

    def configure_runtime_alerts(
        self,
        handler: Callable[[str, str, str, str], None] | None,
        cooldown_seconds: float = 300.0,
    ):
        """Camera出问题以后，谁负责把异常通知发出来"""
        """配置摄像头运行异常通知回调。"""
        self._runtime_alert_handler = handler
        self._runtime_alert_cooldown = max(1.0, float(cooldown_seconds))

    # ---------- 内部 ----------
    def _camera_lock(self, shm_name: str):
        with self._lock:
            return self._camera_locks.setdefault(shm_name, threading.RLock())

    def _start_one(self, shm_name: str, cfg, active_index, frame_seq) -> bool:
        """真正把一台Camera从"配置"变成正在工作的CameraRuntime"""
        with self._camera_lock(shm_name):
            item = self._shared_configs.get(shm_name)
            if self._stopping or item is None or item[0] is not cfg:
                return False
            return self._start_one_locked(shm_name, cfg, active_index, frame_seq)

    def _start_one_locked(self, shm_name: str, cfg, active_index, frame_seq) -> bool:
        # camera总开关关闭就不启动
        if not cfg.get("enable", True):
            logger.info(f"[CameraRuntimeManager] 跳过禁用的摄像头: {shm_name}")
            return False

        with self._lock:
            if shm_name in self._runtimes:
                return True
            self._last_start_attempts[shm_name] = time.time()

        frame_seq.value = 0
        # 创建CameraRuntime
        try:
            runtime = CameraRuntime(dict(cfg), active_index, frame_seq, event_queue=self._runtime_event_queue)
        except Exception as exc:
            logger.exception(f"[CameraRuntimeManager] 摄像头配置或初始化异常 {shm_name}")
            self._notify_runtime_alert(
                shm_name=shm_name,
                camera_name=cfg.get("name", shm_name),
                event_type="启动失败",
                detail=f"{type(exc).__name__}: {exc}",
            )
            return False
        if not runtime.status:
            logger.warning(f"[CameraRuntimeManager] 摄像头初始化失败 {shm_name}: {runtime.msg}")
            self._notify_runtime_alert(
                shm_name=shm_name,
                camera_name=cfg.get("name", shm_name),
                event_type="启动失败",
                detail=str(runtime.msg),
            )
            return False

        try:
            # 初始化期间最长等待第一帧约40秒
            runtime.start(active_index)
        # 发启动超时异常
        except TimeoutError as e:
            runtime.stop()
            logger.warning(f"[CameraRuntimeManager] {e}")
            self._notify_runtime_alert(
                shm_name=shm_name,
                camera_name=cfg.get("name", shm_name),
                event_type="启动超时",
                detail=str(e),
            )
            return False
        except Exception as exc:
            runtime.stop()
            logger.exception(f"[CameraRuntimeManager] 摄像头启动异常 {shm_name}")
            self._notify_runtime_alert(
                shm_name=shm_name,
                camera_name=cfg.get("name", shm_name),
                event_type="启动失败",
                detail=f"{type(exc).__name__}: {exc}",
            )
            return False

        # 写回实际分辨率(CameraRuntime初始化时通过ffprobe探测的真实尺寸)
        cfg["shape"] = runtime.shape

        # 注册到统一帧读取器（通知系统这台摄像头的共享内存可以读了）
        # CameraRuntime负责写，FrameReader负责读
        try:
            registered = frame_reader_registry.register(shm_name, runtime.shape, active_index, frame_seq)
        except Exception:
            logger.exception(f"[CameraRuntimeManager] 帧读取器注册异常 {shm_name}")
            registered = False
        if not registered:
            try:
                frame_reader_registry.unregister(shm_name)
            finally:
                runtime.stop()
            self._notify_runtime_alert(
                shm_name=shm_name,
                camera_name=cfg.get("name", shm_name),
                event_type="启动失败",
                detail="帧读取器注册失败，已停止采集进程",
            )
            return False

        with self._lock:
            # 正式登记为运行中
            self._runtimes[shm_name] = runtime
            self._runtime_started_at[shm_name] = time.time()
        return True
    
    def _start_watchdog(self):
        """创建一个watchdog线程，每五秒巡检所有camera,函数是_watchdog_loop"""
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
        """
        和runtime.py形成两层自动恢复
        第一层：CameraRuntime内部：
            ffmpeg读流失败：只重启ffmpeg
        第二层：CameraRuntimeManager
            如果camera采集子进程死了，或者画面长期停更，那么重建整个CameraRuntime
        """
        while self._watchdog_running:
            # 每五秒执行一次
            time.sleep(5.0)
            if not self._watchdog_running:
                break
            now = time.time()
            # 把Camera子进程通过Queue报上来的异常全部取出来
            self._drain_runtime_events()
            with self._lock:
                items = list(self._runtimes.items())
            for shm_name, runtime in items:
                if runtime is None:
                    continue
                # 检查Camera子进程死没死
                proc_dead = runtime.proc is None or not runtime.proc.is_alive()
                # 检查画面有没有停更
                updated_at = frame_reader_registry.latest_frame_times.get(shm_name)
                if updated_at is None:
                    updated_at = self._runtime_started_at.get(shm_name, now)
                # 如果camera进程还活着，但是15秒没有新画面也认为异常
                stale = now - updated_at > self._stale_seconds
                if not proc_dead and not stale:
                    continue
                reason = "采集进程退出" if proc_dead else f"画面停更 {now - updated_at:.1f}s"
                logger.warning(f"[CameraRuntimeManager] 摄像头异常,准备重启 {shm_name}: {reason}")
                self._notify_runtime_alert(
                    shm_name=shm_name,
                    camera_name=runtime.name,
                    event_type=reason,
                    detail="准备自动重启采集进程",
                )
                # 无论proc_dead还是stale，都会重新建立CameraRuntime、Camera采集子进程、ffmpeg、FeameReader注册
                self._restart_one(shm_name)
            # 找那些实际应该运行但是没有运行的摄像头将它运行起来
            self._retry_missing_enabled(now)

    def _restart_one(self, shm_name: str):
        """重启一次震整个cameraruntime"""
        with self._camera_lock(shm_name):
            item = self._shared_configs.get(shm_name)
            if item is None:
                return
            cfg, active_index, frame_seq = item
            self.stop_camera(shm_name)
            self._start_one(shm_name, cfg, active_index, frame_seq)

    def _retry_missing_enabled(self, now: float):
        """找理论上应该运行，但是实际上没有运行的摄像头，并且对该摄像头进行_start_one
        逻辑：
            共享配置_shared_configs里面有
            并且enable为True
            但是_runtime里面没有的摄像头
        """
        with self._lock:
            missing = [
                (shm_name, item)
                for shm_name, item in self._shared_configs.items()
                if shm_name not in self._runtimes
            ]
        for shm_name, (cfg, active_index, frame_seq) in missing:
            if not cfg.get("enable", True):
                continue
            last_attempt = self._last_start_attempts.get(shm_name, 0.0)
            if now - last_attempt < self._restart_retry_interval:
                continue
            logger.warning(f"[CameraRuntimeManager] 摄像头未运行,自动重试启动 {shm_name}")
            self._start_one(shm_name, cfg, active_index, frame_seq)

    def _drain_runtime_events(self):
        """接收端 """
        while True:
            try:
                event = self._runtime_event_queue.get_nowait()
            except Exception:
                break

            shm_name = str(event.get("shm_name") or "")
            if not shm_name:
                continue
            # 异常通知
            self._notify_runtime_alert(
                shm_name=shm_name,
                camera_name=str(event.get("camera_name") or shm_name),
                event_type=str(event.get("event_type") or "摄像头运行异常"),
                detail=str(event.get("detail") or ""),
            )

    def _notify_runtime_alert(self, shm_name: str, camera_name: str, event_type: str, detail: str):
        """"""
        # 没有上层注入handler，不发通知
        handler = self._runtime_alert_handler
        if handler is None:
            return

        now = time.time()
        # 五分钟内同一种异常不重复发送
        key = (shm_name, event_type)
        last = self._last_runtime_alerts.get(key, 0.0)
        if now - last < self._runtime_alert_cooldown:
            return
        self._last_runtime_alerts[key] = now

        def _send():
            try:
                handler(camera_name, shm_name, event_type, detail)
            except Exception as e:
                logger.warning(f"[CameraRuntimeManager] 摄像头异常企微推送失败 {shm_name}: {e}")
        # 丢给一个小线程发送企业微信通知
        threading.Thread(
            target=_send,
            daemon=True,
            name=f"camera-runtime-alert-{shm_name}",
        ).start()
