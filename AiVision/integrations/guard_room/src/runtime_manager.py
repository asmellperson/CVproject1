# 文件说明：实现运行时相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""Runtime manager for multiple Guard Room sites."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Type

from .config import AppConfig, resolve_runtime_paths
from .runtime import GuardRoomRuntime
from .service import GuardRoomService
from .state import AppState
from .types import AlarmEvent
from .wechat_notifier import WeChatNotifier


# 功能：AppState that annotates status and alarms with site metadata；输入与输出详见下方说明
# 参数：
#   - `cfg`（AppConfig）：运行配置对象
#   - `config_path`（str | Path）：`config_path` 对应的业务输入值
#   - `site_id`（int）：保安室站点唯一标识
#   - `site_name`（str）：`site_name` 对应的业务输入值
# 返回：SiteAppState；返回新建的 `SiteAppState` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::_get_or_create_context` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class SiteAppState(AppState):
    """AppState that annotates status and alarms with site metadata."""

    # 功能：初始化或配置 `__init__` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `cfg`（AppConfig）：运行配置对象
    #   - `config_path`（str | Path）：`config_path` 对应的业务输入值
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `site_name`（str）：`site_name` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().__init__`、`super`、`int`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, cfg: AppConfig, config_path: str | Path, *, site_id: int, site_name: str):
        super().__init__(cfg, config_path=config_path)
        self.site_id = int(site_id)
        self.site_name = site_name

    # 功能：更新或保存 `set_site` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `site_name`（str）：`site_name` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`int`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def set_site(self, site_id: int, site_name: str) -> None:
        with self._lock:
            self.site_id = int(site_id)
            self.site_name = site_name

    # 功能：读取或查询 `get_status` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().get_status`、`super`、`payload.get`、`self._with_site`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_status(self) -> dict[str, Any]:
        payload = super().get_status()
        payload["site_id"] = self.site_id
        payload["site_name"] = self.site_name
        if payload.get("last_alarm"):
            payload["last_alarm"] = self._with_site(payload["last_alarm"])
        return payload

    # 功能：创建或构建 `add_alarm` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `alarm`（AlarmEvent）：`alarm` 对应的业务输入值
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().add_alarm`、`super`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def add_alarm(self, alarm: AlarmEvent) -> dict[str, Any]:
        payload = super().add_alarm(alarm)
        with self._lock:
            payload["site_id"] = self.site_id
            payload["site_name"] = self.site_name
            if self.last_alarm is not None:
                self.last_alarm["site_id"] = self.site_id
                self.last_alarm["site_name"] = self.site_name
        return payload

    # 功能：读取或查询 `get_alarms` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `limit`（int）：返回或处理的最大记录数；默认值为 `50`
    # 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._with_site`、`super().get_alarms`、`super`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_alarms(self, limit: int = 50) -> list[dict[str, Any]]:
        return [self._with_site(item) for item in super().get_alarms(limit=limit)]

    # 功能：读取或查询 `get_alarm` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `alarm_id`（str）：`alarm_id` 对应业务对象的唯一标识
    # 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().get_alarm`、`super`、`self._with_site`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_alarm(self, alarm_id: str) -> dict[str, Any] | None:
        alarm = super().get_alarm(alarm_id)
        return self._with_site(alarm) if alarm else None

    # 功能：读取或查询 `get_statistics` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().get_statistics`、`super`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_statistics(self) -> dict[str, Any]:
        payload = super().get_statistics()
        payload["site_id"] = self.site_id
        payload["site_name"] = self.site_name
        return payload

    # 功能：实现 `_with_site` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `item`（dict[str, Any]）：`item` 对应的业务输入值
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `SiteAppState::get_status`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `SiteAppState::get_alarms`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `SiteAppState::get_alarm` 调用本符号
    #   - 内部调用：`item.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _with_site(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            **item,
            "site_id": item.get("site_id", self.site_id),
            "site_name": item.get("site_name", self.site_name),
        }


# 功能：定义 `RuntimeContext` 类，封装运行时相关的状态、约束与操作
# 参数：
#   - `site_id`（int）：保安室站点唯一标识
#   - `site_name`（str）：`site_name` 对应的业务输入值
#   - `cfg`（AppConfig）：运行配置对象
#   - `state`（SiteAppState）：`state` 对应的业务输入值
#   - `runtime`（GuardRoomRuntime）：`runtime` 对应的业务输入值
#   - `wechat_notifier`（WeChatNotifier | None）：`wechat_notifier` 对应的业务输入值
# 返回：RuntimeContext；返回新建的 `RuntimeContext` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::_get_or_create_context` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class RuntimeContext:
    site_id: int
    site_name: str
    cfg: AppConfig
    state: SiteAppState
    runtime: GuardRoomRuntime
    wechat_notifier: WeChatNotifier | None = None


# 功能：Owns one ``GuardRoomRuntime`` per guard-room site；输入与输出详见下方说明
# 参数：
#   - `service`（GuardRoomService）：`service` 对应的业务输入值
#   - `runtime_cls`（Type[GuardRoomRuntime]）：`runtime_cls` 对应的业务输入值；默认值为 `GuardRoomRuntime`
#   - `notifier_cls`（Type[WeChatNotifier]）：`notifier_cls` 对应的业务输入值；默认值为 `WeChatNotifier`
# 返回：GuardRoomRuntimeManager；返回新建的 `GuardRoomRuntimeManager` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_runtime_manager.py` 的
#         `test_runtime_manager_starts_and_stops_one_site_without_affecting_another`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_manager.py` 的
#         `test_runtime_manager_shutdown_preserves_desired_enabled_state`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_manager.py` 的
#         `test_runtime_manager_enriches_status_frame_and_alarms_with_site_metadata`
#         实例化本符号；`AiVision/integrations/guard_room/src/server.py` 的 `create_app` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class GuardRoomRuntimeManager:
    """Owns one ``GuardRoomRuntime`` per guard-room site."""

    # 功能：初始化或配置 `__init__` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `service`（GuardRoomService）：`service` 对应的业务输入值
    #   - `runtime_cls`（Type[GuardRoomRuntime]）：`runtime_cls` 对应的业务输入值；默认值为 `GuardRoomRuntime`
    #   - `notifier_cls`（Type[WeChatNotifier]）：`notifier_cls` 对应的业务输入值；默认值为 `WeChatNotifier`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`threading.RLock`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(
        self,
        service: GuardRoomService,
        *,
        runtime_cls: Type[GuardRoomRuntime] = GuardRoomRuntime,
        notifier_cls: Type[WeChatNotifier] = WeChatNotifier,
    ):
        self.service = service
        self.runtime_cls = runtime_cls
        self.notifier_cls = notifier_cls
        self._contexts: dict[int, RuntimeContext] = {}
        self._lock = threading.RLock()

    # 功能：Start one site's runtime and return its status；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.service.update_site`、`ValueError`、`self._get_or_create_context`、`self._is_running`、`context.runtime.start`、`context.state.get_status`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
    def start(self, site_id: int) -> dict[str, Any]:
        """Start one site's runtime and return its status."""
        with self._lock:
            site = self.service.update_site(site_id, {"enabled": True})
            if site is None:
                raise ValueError(f"保安室不存在: {site_id}")
            context = self._get_or_create_context(site_id, rebuild=not self._is_running(site_id))
            context.runtime.start()
            return context.state.get_status()

    # 功能：Stop one site's runtime and return its status；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.service.update_site`、`ValueError`、`self._contexts.get`、`self._get_or_create_context`、`context.runtime.stop`、`self._stop_notifier`、`context.state.get_status`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def stop(self, site_id: int) -> dict[str, Any]:
        """Stop one site's runtime and return its status."""
        with self._lock:
            site = self.service.update_site(site_id, {"enabled": False})
            if site is None:
                raise ValueError(f"保安室不存在: {site_id}")
            context = self._contexts.get(site_id)
            if context is None:
                context = self._get_or_create_context(site_id, rebuild=True)
            context.runtime.stop()
            self._stop_notifier(context)
            return context.state.get_status()

    # 功能：Rebuild config from DB, restart one site, and return status；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.service.update_site`、`ValueError`、`self._contexts.get`、`old_context.runtime.stop`、`self._stop_notifier`、`self._contexts.pop`、`self._get_or_create_context`、`context.runtime.start`、`context.state.get_status`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
    def restart(self, site_id: int) -> dict[str, Any]:
        """Rebuild config from DB, restart one site, and return status."""
        with self._lock:
            site = self.service.update_site(site_id, {"enabled": True})
            if site is None:
                raise ValueError(f"保安室不存在: {site_id}")
            old_context = self._contexts.get(site_id)
            if old_context is not None:
                old_context.runtime.stop()
                self._stop_notifier(old_context)
                self._contexts.pop(site_id, None)
            context = self._get_or_create_context(site_id, rebuild=True)
            context.runtime.start()
            return context.state.get_status()

    # 功能：读取或查询 `get_status` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._get_or_create_context(site_id).state.get_status`、`self._get_or_create_context`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_status(self, site_id: int) -> dict[str, Any]:
        with self._lock:
            return self._get_or_create_context(site_id).state.get_status()

    # 功能：读取或查询 `get_state` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：SiteAppState；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::get_latest_frame`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::get_camera_frame`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::get_alarms`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::get_alarm` 调用本符号；另有 1
    #         处静态调用
    #   - 内部调用：`self._get_or_create_context`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_state(self, site_id: int) -> SiteAppState:
        with self._lock:
            return self._get_or_create_context(site_id).state

    # 功能：读取或查询 `get_latest_frame` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：bytes；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.get_state(site_id).get_latest_frame`、`self.get_state`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_latest_frame(self, site_id: int) -> bytes:
        return self.get_state(site_id).get_latest_frame()

    # 功能：读取或查询 `get_camera_frame` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：bytes；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.get_state(site_id).get_camera_frame`、`self.get_state`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_camera_frame(self, site_id: int, camera_id: str) -> bytes:
        return self.get_state(site_id).get_camera_frame(camera_id)

    # 功能：读取或查询 `get_alarms` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `limit`（int）：返回或处理的最大记录数；默认值为 `50`
    # 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.get_state(site_id).get_alarms`、`self.get_state`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_alarms(self, site_id: int, limit: int = 50) -> list[dict[str, Any]]:
        return self.get_state(site_id).get_alarms(limit=limit)

    # 功能：读取或查询 `get_alarm` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `alarm_id`（str）：`alarm_id` 对应业务对象的唯一标识
    # 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.get_state(site_id).get_alarm`、`self.get_state`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_alarm(self, site_id: int, alarm_id: str) -> dict[str, Any] | None:
        return self.get_state(site_id).get_alarm(alarm_id)

    # 功能：读取或查询 `get_statistics` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.get_state(site_id).get_statistics`、`self.get_state`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_statistics(self, site_id: int) -> dict[str, Any]:
        return self.get_state(site_id).get_statistics()

    # 功能：Stop all processes without changing their persisted desired state；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`list`、`self._contexts.values`、`context.runtime.stop`、`self._stop_notifier`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def stop_all(self) -> None:
        """Stop all processes without changing their persisted desired state."""
        with self._lock:
            for context in list(self._contexts.values()):
                context.runtime.stop()
                self._stop_notifier(context)

    # 功能：Stop and forget one site without recreating a missing context；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._contexts.pop`、`int`、`context.runtime.stop`、`self._stop_notifier`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def remove(self, site_id: int) -> None:
        """Stop and forget one site without recreating a missing context."""
        with self._lock:
            context = self._contexts.pop(int(site_id), None)
            if context is None:
                return
            context.runtime.stop()
            self._stop_notifier(context)

    # 功能：读取或查询 `_get_or_create_context` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `rebuild`（bool）：`rebuild` 对应的业务输入值；默认值为 `False`
    # 返回：RuntimeContext；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::start`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::stop`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::restart`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::get_status` 调用本符号；另有 1
    #         处静态调用
    #   - 内部调用：`int`、`self.service.get_site`、`ValueError`、`resolve_runtime_paths`、`self.service.build_app_config`、`SiteAppState`、`self.notifier_cls`、`self.runtime_cls`、`RuntimeContext`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def _get_or_create_context(self, site_id: int, *, rebuild: bool = False) -> RuntimeContext:
        site_id = int(site_id)
        if not rebuild and site_id in self._contexts:
            return self._contexts[site_id]

        site = self.service.get_site(site_id, include_config=False)
        if site is None:
            raise ValueError(f"保安室不存在: {site_id}")

        cfg = resolve_runtime_paths(
            self.service.build_app_config(site_id),
            self.service.project_root,
        )
        config_path = f"db://guard_room_site/{site_id}"
        state = SiteAppState(cfg, config_path=config_path, site_id=site_id, site_name=site["name"])

        wechat_notifier = None
        if cfg.wechat.enable:
            wechat_notifier = self.notifier_cls(
                corpid=cfg.wechat.corpid,
                corpsecret=cfg.wechat.corpsecret,
                agentid=cfg.wechat.agentid,
            )

        runtime = self.runtime_cls(
            config=cfg,
            state=state,
            wechat_notifier=wechat_notifier,
            alarm_user=cfg.wechat.alarm_user,
            alarm_camera_name=cfg.wechat.camera_name or site["name"],
        )
        context = RuntimeContext(
            site_id=site_id,
            site_name=site["name"],
            cfg=cfg,
            state=state,
            runtime=runtime,
            wechat_notifier=wechat_notifier,
        )
        self._contexts[site_id] = context
        return context

    # 功能：检查或判断 `_is_running` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::start` 调用本符号
    #   - 内部调用：`self._contexts.get`、`bool`、`getattr`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _is_running(self, site_id: int) -> bool:
        context = self._contexts.get(site_id)
        return bool(context and getattr(context.runtime, "is_running", False))

    # 功能：停止并释放 `_stop_notifier` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `context`（RuntimeContext）：`context` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::stop`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::restart`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::stop_all`
    #         调用本符号；`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::remove` 调用本符号
    #   - 内部调用：`hasattr`、`notifier.stop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _stop_notifier(context: RuntimeContext) -> None:
        notifier = context.wechat_notifier
        if notifier is not None and hasattr(notifier, "stop"):
            notifier.stop()
        context.wechat_notifier = None
