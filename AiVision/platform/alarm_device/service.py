# 文件说明：封装业务服务的业务规则与持久化访问。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
platform/alarm_device/service.py
喇叭设备 CRUD + 启动时加载所有已启用喇叭的运行时实例。
"""
from __future__ import annotations
from typing import Optional

from AiVision.core.db import session_scope, get_session
from AiVision.core.logger import logger
from AiVision.core.alarm.horn import Horn
from .orm import AiHornConfig


# 功能：定义 `HornService` 类，封装业务服务相关的状态、约束与操作
# 参数：无。
# 返回：HornService；返回新建的 `HornService` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class HornService:

    # 功能：读取或查询 `list_horns` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `enabled_only`（bool）：`enabled_only` 对应的业务输入值；默认值为 `False`
    # 返回：list[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/alarm_device/service.py` 的 `HornService::load_runtime_instances` 调用本符号
    #   - 内部调用：`get_session`、`session.query`、`q.filter`、`AiHornConfig.enable.is_`、`self._to_dict`、`q.all`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_horns(self, enabled_only: bool = False) -> list[dict]:
        session = get_session()
        try:
            q = session.query(AiHornConfig)
            if enabled_only:
                q = q.filter(AiHornConfig.enable.is_(True))
            return [self._to_dict(h) for h in q.all()]
        finally:
            session.close()

    # 功能：读取或查询 `get_horn` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `horn_id`（int）：`horn_id` 对应业务对象的唯一标识
    # 返回：Optional[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`get_session`、`session.query(AiHornConfig).get`、`session.query`、`self._to_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_horn(self, horn_id: int) -> Optional[dict]:
        session = get_session()
        try:
            h = session.query(AiHornConfig).get(horn_id)
            return self._to_dict(h) if h else None
        finally:
            session.close()

    # 功能：创建或构建 `create_horn` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `payload`（dict）：接口或事件携带的业务数据
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`AiHornConfig`、`payload.get`、`bool`、`session.add`、`session.flush`、`self._to_dict`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def create_horn(self, payload: dict) -> dict:
        with session_scope() as session:
            h = AiHornConfig(
                name=payload["name"],
                url=payload["url"],
                username=payload.get("username", "admin"),
                password=payload.get("password", "admin"),
                enable=bool(payload.get("enable", True)),
                description=payload.get("description"),
            )
            session.add(h)
            session.flush()
            return self._to_dict(h)

    # 功能：更新或保存 `update_horn` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `horn_id`（int）：`horn_id` 对应业务对象的唯一标识
    #   - `payload`（dict）：接口或事件携带的业务数据
    # 返回：Optional[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`session.query(AiHornConfig).get`、`session.query`、`setattr`、`bool`、`self._to_dict`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_horn(self, horn_id: int, payload: dict) -> Optional[dict]:
        with session_scope() as session:
            h = session.query(AiHornConfig).get(horn_id)
            if h is None:
                return None
            for f in ("name", "url", "username", "password", "description"):
                if f in payload:
                    setattr(h, f, payload[f])
            if "enable" in payload:
                h.enable = bool(payload["enable"])
            return self._to_dict(h)

    # 功能：删除或清理 `delete_horn` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `horn_id`（int）：`horn_id` 对应业务对象的唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`session.query(AiHornConfig).get`、`session.query`、`session.delete`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def delete_horn(self, horn_id: int) -> bool:
        with session_scope() as session:
            h = session.query(AiHornConfig).get(horn_id)
            if h is None:
                return False
            session.delete(h)
            return True

    # ---------- Runtime ----------

    # 功能：启动时调用 — 实例化所有已启用的喇叭并启动心跳；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict[int, Horn]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::start` 调用本符号
    #   - 内部调用：`self.list_horns`、`Horn`、`horn.start_heartbeat`、`logger.info`、`len`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def load_runtime_instances(self) -> dict[int, Horn]:
        """启动时调用 — 实例化所有已启用的喇叭并启动心跳"""
        result: dict[int, Horn] = {}
        for cfg in self.list_horns(enabled_only=True):
            horn = Horn({
                "horn_url": cfg["url"],
                "username": cfg["username"],
                "password": cfg["password"],
            })
            horn.start_heartbeat()
            result[cfg["id"]] = horn
        logger.info(f"[HornService] 已加载 {len(result)} 个喇叭设备")
        return result

    # 功能：转换或规范化 `_to_dict` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `h`（AiHornConfig）：`h` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/alarm_device/service.py` 的 `HornService::list_horns`
    #         调用本符号；`AiVision/platform/alarm_device/service.py` 的 `HornService::get_horn`
    #         调用本符号；`AiVision/platform/alarm_device/service.py` 的 `HornService::create_horn`
    #         调用本符号；`AiVision/platform/alarm_device/service.py` 的 `HornService::update_horn` 调用本符号
    #   - 内部调用：`bool`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _to_dict(h: AiHornConfig) -> dict:
        return {
            "id": h.id,
            "name": h.name,
            "url": h.url,
            "username": h.username,
            "password": h.password,
            "enable": bool(h.enable),
            "description": h.description,
        }


horn_service = HornService()
