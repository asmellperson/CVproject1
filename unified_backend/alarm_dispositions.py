# 文件说明：实现告警相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""统一报警处置状态存储。"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


ALARM_DISPOSITION_STATUSES = {
    "pending",
    "acknowledged",
    "resolved",
    "false_positive",
}


# 功能：基于 JSON 文件的报警处置状态存储；输入与输出详见下方说明
# 参数：
#   - `data_dir`（str | os.PathLike[str]）：`data_dir` 对应的业务输入值
# 返回：AlarmDispositionStore；返回新建的 `AlarmDispositionStore` 实例。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AlarmDispositionStore:
    """基于 JSON 文件的报警处置状态存储。"""

    # 功能：初始化或配置 `__init__` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `data_dir`（str | os.PathLike[str]）：`data_dir` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path`、`self.data_dir.mkdir`、`threading.Lock`、`self._load`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
    def __init__(self, data_dir: str | os.PathLike[str]):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "alarm_dispositions.json"
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, Any]] = self._load()

    # 功能：读取或查询 `list_items` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`unified_backend/app.py` 的 `_collect_alarms` 调用本符号；`unified_backend/app.py` 的 `create_app::get_alarm_dispositions`
    #         调用本符号
    #   - 内部调用：`list`、`self._items.values`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_items(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items.values())

    # 功能：更新或保存 `update` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `alarm_id`（str）：`alarm_id` 对应业务对象的唯一标识
    #   - `status`（str）：当前或目标状态值
    #   - `note`（str）：`note` 对应的业务输入值
    #   - `user`（dict[str, Any]）：当前用户或待处理用户对象
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`str(alarm_id).strip`、`str`、`str(status).strip`、`ValueError`、`datetime.now().isoformat`、`datetime.now`、`user.get`、`self._items.get`、`list`、`previous.get`
    #          等共 14 个调用。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def update(self, *, alarm_id: str, status: str, note: str, user: dict[str, Any]) -> dict[str, Any]:
        alarm_id = str(alarm_id).strip()
        status = str(status).strip()
        if not alarm_id:
            raise ValueError("alarm_id is required")
        if status not in ALARM_DISPOSITION_STATUSES:
            raise ValueError("invalid disposition status")

        now = datetime.now().isoformat(timespec="seconds")
        actor = {
            "employee_id": str(user.get("employee_id", "")),
            "name": str(user.get("name", "")),
        }

        with self._lock:
            previous = self._items.get(alarm_id) or {}
            history = list(previous.get("history") or [])
            if previous:
                history.append({
                    "status": previous.get("status", "pending"),
                    "note": previous.get("note", ""),
                    "updated_at": previous.get("updated_at"),
                    "updated_by": previous.get("updated_by"),
                })
                history = history[-20:]

            item = {
                "alarm_id": alarm_id,
                "status": status,
                "note": str(note or "").strip(),
                "updated_at": now,
                "updated_by": actor,
                "history": history,
            }
            self._items[alarm_id] = item
            self._flush_locked()
            return dict(item)

    # 功能：读取或查询 `_load` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict[str, dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`unified_backend/alarm_dispositions.py` 的 `AlarmDispositionStore::__init__` 调用本符号
    #   - 内部调用：`json.loads`、`self.path.read_text`、`isinstance`、`payload.get`、`str(row.get('alarm_id', '')).strip`、`str`、`row.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            return {}

        rows = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return {}

        items: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            alarm_id = str(row.get("alarm_id", "")).strip()
            status = str(row.get("status", "pending"))
            if alarm_id and status in ALARM_DISPOSITION_STATUSES:
                items[alarm_id] = row
        return items

    # 功能：实现 `_flush_locked` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`unified_backend/alarm_dispositions.py` 的 `AlarmDispositionStore::update` 调用本符号
    #   - 内部调用：`list`、`self._items.values`、`self.path.with_suffix`、`tmp.write_text`、`json.dumps`、`os.replace`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def _flush_locked(self) -> None:
        payload = {"items": list(self._items.values())}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
