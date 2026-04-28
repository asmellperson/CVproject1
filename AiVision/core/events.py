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


@dataclass
class ConfigChangeEvent:
    """配置变更事件 — change_type 命名约定: '<feature>_<action>',如 'blocks_enabled'"""
    change_type: str
    camera_id: int
    camera_name: str
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None


class ConfigEventBus:
    """线程安全的事件总线"""

    _PREFIX_KEY = "__prefix__"

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}
        self._prefix_listeners: list[tuple[str, Callable]] = []
        self._wildcard_listeners: list[Callable] = []
        self._lock = threading.Lock()

    def subscribe(self, change_type: str, listener: Callable):
        with self._lock:
            self._listeners.setdefault(change_type, []).append(listener)

    def subscribe_prefix(self, prefix: str, listener: Callable):
        """订阅前缀匹配的事件,如 prefix='blocks_' 会匹配 blocks_enabled / blocks_config_updated"""
        with self._lock:
            self._prefix_listeners.append((prefix, listener))

    def subscribe_wildcard(self, listener: Callable):
        with self._lock:
            self._wildcard_listeners.append(listener)

    def unsubscribe(self, change_type: str, listener: Callable):
        with self._lock:
            if change_type in self._listeners:
                try:
                    self._listeners[change_type].remove(listener)
                except ValueError:
                    pass

    def publish(self, event: ConfigChangeEvent):
        """发布事件 — 锁内快照监听器,锁外执行回调"""
        with self._lock:
            exact = list(self._listeners.get(event.change_type, []))
            prefix = [
                fn for prefix, fn in self._prefix_listeners
                if event.change_type.startswith(prefix)
            ]
            wildcard = list(self._wildcard_listeners)

        for fn in exact + prefix + wildcard:
            try:
                fn(event)
            except Exception as e:
                from core.logger import logger
                logger.error(f"[EventBus] 监听器执行失败 ({event.change_type}): {e}")


# 全局单例
config_event_bus = ConfigEventBus()
