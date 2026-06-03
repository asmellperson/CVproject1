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


class AlarmDispositionStore:
    """基于 JSON 文件的报警处置状态存储。"""

    def __init__(self, data_dir: str | os.PathLike[str]):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "alarm_dispositions.json"
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, Any]] = self._load()

    def list_items(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items.values())

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

    def _flush_locked(self) -> None:
        payload = {"items": list(self._items.values())}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
