# 文件说明：实现`horn` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：单个 IP 喇叭设备的控制器；输入与输出详见下方说明
# 参数：
#   - `config`（dict）：运行配置对象
# 返回：Horn；返回新建的 `Horn` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/alarm_device/service.py` 的 `HornService::load_runtime_instances` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：初始化或配置 `__init__` 对应的`horn` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `config`（dict）：运行配置对象
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`config.get`、`threading.Event`、`threading.Lock`、`self.connect`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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

    # 功能：向设备发起登录请求，获取 access_key / access_id 并更新 status；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/core/alarm/horn.py` 的 `Horn::__init__` 调用本符号；`AiVision/core/db.py` 的 `_ensure_database_exists`
    #         调用本符号；`AiVision/integrations/guard_room/src/db.py` 的 `ping`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的
    #         `test_database_migration_preserves_records_and_is_idempotent` 调用本符号；另有 7 处静态调用
    #   - 内部调用：`requests.post`、`resp.json`、`data.get`、`logger.warning`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能发起网络请求或发送外部消息；会向日志系统输出运行或异常信息。
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

    # 功能：启动后台心跳守护线程，每隔 _heart_interval 秒向设备发送在线心跳；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/alarm_device/service.py` 的 `HornService::load_runtime_instances` 调用本符号
    #   - 内部调用：`self._heart_thread.is_alive`、`self._stop_event.clear`、`threading.Thread`、`self._heart_thread.start`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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

    # 功能：通知心跳线程退出并等待其结束（最多 2 秒）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::stop` 调用本符号
    #   - 内部调用：`self._stop_event.set`、`self._heart_thread.join`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def stop_heartbeat(self):
        """
        通知心跳线程退出并等待其结束（最多 2 秒）。

        进程退出前调用，确保后台线程优雅终止；超时后守护线程会随进程自动回收。
        """
        self._stop_event.set()
        if self._heart_thread:
            self._heart_thread.join(timeout=2)

    # 功能：心跳线程主循环；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.is_set`、`self._send_heart`、`self._stop_event.wait`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能发起网络请求或发送外部消息。
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

    # 功能：向设备端 /online 接口发送一次心跳以维持 Session 活跃；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/core/alarm/horn.py` 的 `Horn::_heart_loop` 调用本符号
    #   - 内部调用：`requests.post`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能发起网络请求或发送外部消息。
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

    # 功能：触发设备上预录制的语音任务；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `event_id`（str | int）：`event_id` 对应业务对象的唯一标识
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/core/alarm/dispatcher.py` 的 `AlarmDispatcher::_execute` 调用本符号
    #   - 内部调用：`time.time`、`requests.post`、`logger.warning`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能发起网络请求或发送外部消息；会向日志系统输出运行或异常信息。
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
