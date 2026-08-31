# 文件说明：实现`manager` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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
from typing import Callable

from core.logger import logger
from .runtime import CameraRuntime
from .frame_reader import frame_reader_registry


# 功能：所有摄像头采集进程的生命周期管理；输入与输出详见下方说明
# 参数：
#   - `manager`（未显式标注）：`manager` 对应的业务输入值
# 返回：CameraManager；返回新建的 `CameraManager` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class CameraManager:
    """所有摄像头采集进程的生命周期管理"""

    # 功能：manager 是 multiprocessing.Manager() 实例,用来创建跨进程共享对象；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `manager`（未显式标注）：`manager` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`threading.Lock`、`manager.Queue`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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
        self._restart_retry_interval = 30.0
        self._last_start_attempts: dict[str, float] = {}
        self._runtime_alert_handler: Callable[[str, str, str, str], None] | None = None
        self._runtime_alert_cooldown = 300.0
        self._last_runtime_alerts: dict[tuple[str, str], float] = {}
        self._runtime_event_queue = manager.Queue(maxsize=200)

    # 功能：把摄像头配置列表转成跨进程共享 Manager.dict；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_configs`（list[dict]）：`camera_configs` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._mp_manager.dict`、`self._mp_manager.Value`、`logger.info`、`len`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
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

    # 功能：启动所有已配置且 enable=True 的摄像头；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._shared_configs.items`、`self._start_one`、`time.sleep`、`self._start_watchdog`、`logger.info`、`len`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def start_all(self):
        """启动所有已配置且 enable=True 的摄像头"""
        for shm_name, (cfg, active_index, frame_seq) in self._shared_configs.items():
            self._start_one(shm_name, cfg, active_index, frame_seq)
            time.sleep(0.3)  # 错开启动峰值
        self._start_watchdog()
        logger.info(f"[CameraManager] 启动了 {len(self._runtimes)} 个采集进程")

    # 功能：停止并释放 `stop_all` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_watchdog`、`list`、`self._runtimes.keys`、`self.stop_camera`、`logger.info`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def stop_all(self):
        self._stop_watchdog()
        for shm_name in list(self._runtimes.keys()):
            self.stop_camera(shm_name)
        logger.info("[CameraManager] 所有采集进程已停止")

    # 功能：单独启动一个摄像头(配置必须已在 _shared_configs 中)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._shared_configs.get`、`logger.warning`、`self._start_one`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
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

    # 功能：停止并释放 `stop_camera` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/manager.py` 的 `CameraManager::stop_all` 调用本符号；`AiVision/platform/camera/manager.py` 的
    #         `CameraManager::remove_camera_config` 调用本符号；`AiVision/platform/camera/manager.py` 的 `CameraManager::_restart_one`
    #         调用本符号
    #   - 内部调用：`self._runtimes.pop`、`frame_reader_registry.unregister`、`runtime.stop`、`logger.info`、`time.sleep`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def stop_camera(self, shm_name: str):
        with self._lock:
            runtime = self._runtimes.pop(shm_name, None)
        if runtime is None:
            return
        frame_reader_registry.unregister(shm_name)
        runtime.stop()
        logger.info(f"[CameraManager] 摄像头已停止: {shm_name}")
        time.sleep(0.3)

    # 功能：彻底移除摄像头运行配置,用于删除摄像头后避免 watchdog 再次拉起；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.stop_camera`、`self._shared_configs.pop`、`self._last_start_attempts.pop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def remove_camera_config(self, shm_name: str):
        """彻底移除摄像头运行配置,用于删除摄像头后避免 watchdog 再次拉起。"""
        self.stop_camera(shm_name)
        with self._lock:
            self._shared_configs.pop(shm_name, None)
            self._last_start_attempts.pop(shm_name, None)

    # 功能：运行时更新摄像头共享配置 — 子进程会看到最新值；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    #   - `new_cfg`（dict）：`new_cfg` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._shared_configs.get`、`self._mp_manager.dict`、`self._mp_manager.Value`、`shared_dict.update`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：检查或判断 `is_running` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def is_running(self, shm_name: str) -> bool:
        return shm_name in self._runtimes

    # 功能：读取或查询 `list_running` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：list[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`list`、`self._runtimes.keys`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_running(self) -> list[str]:
        return list(self._runtimes.keys())

    # 功能：配置摄像头运行异常通知回调；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `handler`（Callable[[str, str, str, str], None] | None）：负责处理事件或结果的回调函数
    #   - `cooldown_seconds`（float）：`cooldown_seconds` 对应的时间间隔或时长；默认值为 `300.0`
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`max`、`float`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def configure_runtime_alerts(
        self,
        handler: Callable[[str, str, str, str], None] | None,
        cooldown_seconds: float = 300.0,
    ):
        """配置摄像头运行异常通知回调。"""
        self._runtime_alert_handler = handler
        self._runtime_alert_cooldown = max(1.0, float(cooldown_seconds))

    # ---------- 内部 ----------

    # 功能：启动或执行 `_start_one` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    #   - `cfg`（未显式标注）：运行配置对象
    #   - `active_index`（未显式标注）：`active_index` 对应的业务输入值
    #   - `frame_seq`（未显式标注）：`frame_seq` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/manager.py` 的 `CameraManager::start_all` 调用本符号；`AiVision/platform/camera/manager.py` 的
    #         `CameraManager::start_camera` 调用本符号；`AiVision/platform/camera/manager.py` 的 `CameraManager::_restart_one`
    #         调用本符号；`AiVision/platform/camera/manager.py` 的 `CameraManager::_retry_missing_enabled` 调用本符号
    #   - 内部调用：`cfg.get`、`logger.info`、`time.time`、`CameraRuntime`、`dict`、`logger.warning`、`self._notify_runtime_alert`、`str`、`runtime.start`、`frame_reader_registry.register`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def _start_one(self, shm_name: str, cfg, active_index, frame_seq) -> bool:
        if not cfg.get("enable", True):
            logger.info(f"[CameraManager] 跳过禁用的摄像头: {shm_name}")
            return False

        with self._lock:
            if shm_name in self._runtimes:
                return True
            self._last_start_attempts[shm_name] = time.time()

        frame_seq.value = 0
        runtime = CameraRuntime(dict(cfg), active_index, frame_seq, event_queue=self._runtime_event_queue)
        if not runtime.status:
            logger.warning(f"[CameraManager] 摄像头初始化失败 {shm_name}: {runtime.msg}")
            self._notify_runtime_alert(
                shm_name=shm_name,
                camera_name=cfg.get("name", shm_name),
                event_type="启动失败",
                detail=str(runtime.msg),
            )
            return False

        try:
            runtime.start(active_index)
        except TimeoutError as e:
            logger.warning(f"[CameraManager] {e}")
            self._notify_runtime_alert(
                shm_name=shm_name,
                camera_name=cfg.get("name", shm_name),
                event_type="启动超时",
                detail=str(e),
            )
            return False

        # 写回实际分辨率(子进程探测到的真实尺寸)
        cfg["shape"] = runtime.shape

        # 注册到统一帧读取器
        frame_reader_registry.register(shm_name, runtime.shape, active_index, frame_seq)

        with self._lock:
            self._runtimes[shm_name] = runtime
        return True

    # 功能：启动或执行 `_start_watchdog` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/manager.py` 的 `CameraManager::start_all` 调用本符号
    #   - 内部调用：`threading.Thread`、`self._watchdog_thread.start`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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

    # 功能：停止并释放 `_stop_watchdog` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/manager.py` 的 `CameraManager::stop_all` 调用本符号
    #   - 内部调用：`self._watchdog_thread.join`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def _stop_watchdog(self):
        self._watchdog_running = False
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=2)
            self._watchdog_thread = None

    # 功能：实现 `_watchdog_loop` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`time.sleep`、`time.time`、`self._drain_runtime_events`、`list`、`self._runtimes.items`、`runtime.proc.is_alive`、`frame_reader_registry.latest_frame_times.get`、`logger.warning`、`self._notify_runtime_alert`、`self._restart_one`
    #          等共 11 个调用。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _watchdog_loop(self):
        while self._watchdog_running:
            time.sleep(5.0)
            now = time.time()
            self._drain_runtime_events()
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
                self._notify_runtime_alert(
                    shm_name=shm_name,
                    camera_name=runtime.name,
                    event_type=reason,
                    detail="准备自动重启采集进程",
                )
                self._restart_one(shm_name)
            self._retry_missing_enabled(now)

    # 功能：实现 `_restart_one` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/manager.py` 的 `CameraManager::_watchdog_loop` 调用本符号
    #   - 内部调用：`self._shared_configs.get`、`self.stop_camera`、`self._start_one`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _restart_one(self, shm_name: str):
        item = self._shared_configs.get(shm_name)
        if item is None:
            return
        cfg, active_index, frame_seq = item
        self.stop_camera(shm_name)
        self._start_one(shm_name, cfg, active_index, frame_seq)

    # 功能：实现 `_retry_missing_enabled` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `now`（float）：`now` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/manager.py` 的 `CameraManager::_watchdog_loop` 调用本符号
    #   - 内部调用：`self._shared_configs.items`、`cfg.get`、`self._last_start_attempts.get`、`logger.warning`、`self._start_one`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _retry_missing_enabled(self, now: float):
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
            logger.warning(f"[CameraManager] 摄像头未运行,自动重试启动 {shm_name}")
            self._start_one(shm_name, cfg, active_index, frame_seq)

    # 功能：实现 `_drain_runtime_events` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/manager.py` 的 `CameraManager::_watchdog_loop` 调用本符号
    #   - 内部调用：`self._runtime_event_queue.get_nowait`、`str`、`event.get`、`self._notify_runtime_alert`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _drain_runtime_events(self):
        while True:
            try:
                event = self._runtime_event_queue.get_nowait()
            except Exception:
                break

            shm_name = str(event.get("shm_name") or "")
            if not shm_name:
                continue
            self._notify_runtime_alert(
                shm_name=shm_name,
                camera_name=str(event.get("camera_name") or shm_name),
                event_type=str(event.get("event_type") or "摄像头运行异常"),
                detail=str(event.get("detail") or ""),
            )

    # 功能：发送或分发 `_notify_runtime_alert` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    #   - `camera_name`（str）：`camera_name` 对应的业务输入值
    #   - `event_type`（str）：事件类型标识
    #   - `detail`（str）：`detail` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/camera/manager.py` 的 `CameraManager::_start_one` 调用本符号；`AiVision/platform/camera/manager.py` 的
    #         `CameraManager::_watchdog_loop` 调用本符号；`AiVision/platform/camera/manager.py` 的 `CameraManager::_drain_runtime_events`
    #         调用本符号
    #   - 内部调用：`time.time`、`self._last_runtime_alerts.get`、`threading.Thread(target=_send, daemon=True,
    #          name=f'camera-runtime-alert-{shm_name}').start`、`threading.Thread`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；可能启动、等待或停止线程/进程资源。
    def _notify_runtime_alert(self, shm_name: str, camera_name: str, event_type: str, detail: str):
        handler = self._runtime_alert_handler
        if handler is None:
            return

        now = time.time()
        key = (shm_name, event_type)
        last = self._last_runtime_alerts.get(key, 0.0)
        if now - last < self._runtime_alert_cooldown:
            return
        self._last_runtime_alerts[key] = now

        # 功能：发送或分发 `_send` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`handler`、`logger.warning`。
        # 副作用/注意事项：会向日志系统输出运行或异常信息。
        def _send():
            try:
                handler(camera_name, shm_name, event_type, detail)
            except Exception as e:
                logger.warning(f"[CameraManager] 摄像头异常企微推送失败 {shm_name}: {e}")

        threading.Thread(
            target=_send,
            daemon=True,
            name=f"camera-runtime-alert-{shm_name}",
        ).start()
