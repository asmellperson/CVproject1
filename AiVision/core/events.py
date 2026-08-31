# 文件说明：实现`events` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
core/events.py
配置变更事件总线 — pub/sub 模式,系统内部各组件用它传递配置变更通知。

事件流转:
    API/Service 层调用 publish() →
    core.cache.ConfigCache 刷新缓存 →
    Orchestrator 路由到对应 Worker/Consumer →
    Worker/Consumer 热更新内部状态

线程安全:监听器读写在锁内,事件回调在锁外执行(避免回调中再发事件死锁)。
"""
from __future__ import annotations
import threading
from dataclasses import dataclass
from typing import Callable, Optional


# 功能：配置变更事件的数据载体，由 API/Service 层构造后投入事件总线；输入与输出详见下方说明
# 参数：
#   - `change_type`（str）：`change_type` 对应的业务输入值
#   - `camera_id`（int | None）：摄像头唯一标识
#   - `camera_name`（str | None）：`camera_name` 对应的业务输入值
#   - `old_value`（Optional[dict]）：`old_value` 对应的业务输入值
#   - `new_value`（Optional[dict]）：`new_value` 对应的业务输入值
# 返回：ConfigChangeEvent；返回新建的 `ConfigChangeEvent` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/events.py` 的 `ConfigChangeEvent::publish_departments_changed`
#         实例化本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_publish_notifications`
#         实例化本符号；`AiVision/tests/test_orchestrator_camera_update.py` 的 `test_camera_display_update_does_not_restart_runtime`
#         实例化本符号；`AiVision/tests/test_orchestrator_camera_update.py` 的 `test_camera_runtime_update_restarts_runtime` 实例化本符号；另有 9
#         处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class ConfigChangeEvent:
    """
    配置变更事件的数据载体，由 API/Service 层构造后投入事件总线。

    字段说明:
        change_type : 事件类型标识，命名约定为 '<feature>_<action>'，
                      如 'blocks_enabled'、'detect_face_config_updated'。
                      订阅方可按精确匹配、前缀匹配或通配符三种方式过滤。
        camera_id   : 发生变更的摄像头 ID，用于定向刷新缓存与路由 Worker。
        camera_name : 摄像头展示名称，供监听器写日志或告警消息时使用。
        old_value   : 变更前的配置快照，可为 None（新增场景）。
        new_value   : 变更后的配置快照，可为 None（删除场景）。
    """
    change_type: str
    camera_id: int | None = None
    camera_name: str | None = None
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None

    # 功能：发布部门配置变更事件，用于刷新缓存与 UI；输入与输出详见下方说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/department/service.py` 的 `DepartmentService::create_department`
    #         调用本符号；`AiVision/platform/department/service.py` 的 `DepartmentService::update_department`
    #         调用本符号；`AiVision/platform/department/service.py` 的 `DepartmentService::delete_department`
    #         调用本符号；`AiVision/platform/department/service.py` 的 `DepartmentService::set_feature_departments` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`ConfigChangeEvent`、`config_event_bus.publish`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def publish_departments_changed():
        """发布部门配置变更事件，用于刷新缓存与 UI。"""
        event = ConfigChangeEvent(change_type="departments_changed")
        config_event_bus.publish(event)


# 功能：线程安全的同步事件总线，支持三种订阅粒度；输入与输出详见下方说明
# 参数：无。
# 返回：ConfigEventBus；返回新建的 `ConfigEventBus` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ConfigEventBus:
    """
    线程安全的同步事件总线，支持三种订阅粒度。

    订阅方式（优先级由高到低）:
        subscribe()         — 精确匹配 change_type，仅当类型完全相同时触发。
        subscribe_prefix()  — 前缀匹配，如 'blocks_' 可同时捕获该功能的所有事件。
        subscribe_wildcard()— 全量订阅，接收总线上的每一个事件（如审计日志）。

    执行顺序: 精确匹配 → 前缀匹配 → 通配符，同组内按注册顺序调用。

    线程安全策略:
        _lock 仅保护监听器列表的读写；publish() 在锁内做快照后立即释放，
        回调在锁外执行，避免监听器内部再调用 publish() 时产生死锁。
    """

    # 功能：初始化或配置 `__init__` 对应的`events` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`threading.Lock`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(self):
        # 精确匹配表: {change_type → [listener, ...]}
        self._listeners: dict[str, list[Callable]] = {}
        # 前缀匹配表: [(prefix, listener), ...]，按注册顺序线性扫描
        self._prefix_listeners: list[tuple[str, Callable]] = []
        # 通配符监听器列表，接收所有事件
        self._wildcard_listeners: list[Callable] = []
        # 保护上述三个列表的增删操作；回调执行不在锁内
        self._lock = threading.Lock()

    # 功能：注册精确匹配监听器；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `change_type`（str）：`change_type` 对应的业务输入值
    #   - `listener`（Callable）：`listener` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._listeners.setdefault(change_type, []).append`、`self._listeners.setdefault`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def subscribe(self, change_type: str, listener: Callable):
        """
        注册精确匹配监听器。

        Args:
            change_type: 要监听的事件类型，须与 publish() 时的 change_type 完全一致。
            listener   : 接收 ConfigChangeEvent 的可调用对象。
        """
        with self._lock:
            self._listeners.setdefault(change_type, []).append(listener)

    # 功能：注册前缀匹配监听器，适用于需要捕获某一功能所有事件的场景；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `prefix`（str）：`prefix` 对应的业务输入值
    #   - `listener`（Callable）：`listener` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._prefix_listeners.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def subscribe_prefix(self, prefix: str, listener: Callable):
        """
        注册前缀匹配监听器，适用于需要捕获某一功能所有事件的场景。

        示例:
            subscribe_prefix('blocks_', handler)
            → 可匹配 'blocks_enabled'、'blocks_config_updated' 等。

        Args:
            prefix  : 事件类型前缀字符串。
            listener: 接收 ConfigChangeEvent 的可调用对象。
        """
        with self._lock:
            self._prefix_listeners.append((prefix, listener))

    # 功能：注册通配符监听器，接收总线上投递的所有事件；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `listener`（Callable）：`listener` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::__init__` 调用本符号
    #   - 内部调用：`self._wildcard_listeners.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def subscribe_wildcard(self, listener: Callable):
        """
        注册通配符监听器，接收总线上投递的所有事件。

        适用场景: 审计日志、全局监控、调试追踪等需要感知所有变更的组件。

        Args:
            listener: 接收 ConfigChangeEvent 的可调用对象。
        """
        with self._lock:
            self._wildcard_listeners.append(listener)

    # 功能：注销精确匹配监听器；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `change_type`（str）：`change_type` 对应的业务输入值
    #   - `listener`（Callable）：`listener` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._listeners[change_type].remove`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def unsubscribe(self, change_type: str, listener: Callable):
        """
        注销精确匹配监听器。

        listener 不在列表中时静默忽略（不抛异常），便于组件在任意时刻安全注销。
        当前仅支持注销精确匹配监听器；前缀与通配符监听器暂不支持注销。

        Args:
            change_type: 注册时使用的事件类型。
            listener   : 要移除的监听器引用，须与注册时传入的对象相同。
        """
        with self._lock:
            if change_type in self._listeners:
                try:
                    self._listeners[change_type].remove(listener)
                except ValueError:
                    pass  # 未找到，静默忽略

    # 功能：向总线投递事件，同步调用所有匹配的监听器；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `event`（ConfigChangeEvent）：待处理的事件对象
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`list`、`self._listeners.get`、`event.change_type.startswith`、`fn`、`logger.error`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def publish(self, event: ConfigChangeEvent):
        """
        向总线投递事件，同步调用所有匹配的监听器。

        执行流程:
            1. 在锁内对三类监听器列表做浅拷贝快照，立即释放锁。
            2. 锁外依次调用：精确匹配 → 前缀匹配 → 通配符监听器。
            3. 单个监听器异常不影响后续监听器的执行，仅记录 error 日志。

        Note:
            publish() 为同步调用，所有监听器执行完毕后才返回。
            若监听器耗时较长（如 I/O），建议在监听器内部异步处理，
            避免阻塞 API/Service 层的调用线程。
        """
        # 锁内快照：取出当前注册的监听器副本，防止回调执行期间列表被并发修改
        with self._lock:
            exact = list(self._listeners.get(event.change_type, []))
            prefix = [
                fn for pfx, fn in self._prefix_listeners
                if event.change_type.startswith(pfx)
            ]
            wildcard = list(self._wildcard_listeners)

        # 锁外执行：避免监听器内部再调用 publish() 或 subscribe() 时死锁
        for fn in exact + prefix + wildcard:
            try:
                fn(event)
            except Exception as e:
                from core.logger import logger
                logger.error(f"[EventBus] 监听器执行失败 ({event.change_type}): {e}")


# 模块级全局单例
# 各组件通过 `from core.events import config_event_bus` 共享同一总线实例。
config_event_bus = ConfigEventBus()