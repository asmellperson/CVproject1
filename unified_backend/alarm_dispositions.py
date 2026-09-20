"""JSON 持久化的处置状态：启动建立索引，查询仅复制选中的记录。"""
from __future__ import annotations

from bisect import insort
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import threading
from typing import Any, Iterable, Literal, get_args
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

DispositionStatus = Literal["pending", "acknowledged", "resolved", "false_positive"]
READ_LOCK_TIMEOUT_SECONDS = 0.05


class _Actor(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    employee_id: str
    name: str


class _Change(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    status: DispositionStatus
    note: str
    updated_at: str
    updated_by: _Actor


class _Disposition(_Change):
    alarm_id: str = Field(min_length=1)
    history: list[_Change]


class _DispositionFile(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[_Disposition]


class DispositionStoreBusy(TimeoutError):
    pass


class DispositionSnapshotChanged(ValueError):
    pass


class AlarmDispositionStore:
    """单进程 JSON 存储；alarm_id 字符串升序，修改后使旧分页快照失效。"""

    def __init__(self, data_dir: str | os.PathLike[str]):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "alarm_dispositions.json"
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._items = self._load()
        self._ordered_ids = sorted(self._items)
        self._generation = uuid4().hex
        self._version = 0

    @contextmanager
    def _reading(self):
        if not self._lock.acquire(timeout=READ_LOCK_TIMEOUT_SECONDS):
            raise DispositionStoreBusy("disposition index is busy")
        try:
            yield
        finally:
            self._lock.release()

    def _revision(self) -> str:
        return f"{self._generation}:{self._version}"

    def scan_ids(self, *, offset: int, limit: int, revision: str | None) -> tuple[list[str], bool, str]:
        """有界候选 ID 切片；不读磁盘、不遍历或排序全部处置记录。"""
        with self._reading():
            current = self._revision()
            if revision is not None and revision != current:
                raise DispositionSnapshotChanged("dispositions changed; restart pagination")
            end = min(offset + limit, len(self._ordered_ids))
            return self._ordered_ids[offset:end], end == len(self._ordered_ids), current

    def get_many(self, alarm_ids: Iterable[str], *, revision: str | None = None) -> dict[str, dict[str, Any]]:
        with self._reading():
            if revision is not None and revision != self._revision():
                raise DispositionSnapshotChanged("dispositions changed; restart pagination")
            return {key: deepcopy(self._items[key]) for key in alarm_ids if key in self._items}

    def update(self, *, alarm_id: str, status: str, note: str, user: dict[str, Any]) -> dict[str, Any]:
        alarm_id = str(alarm_id).strip()
        status = str(status).strip()
        if not alarm_id:
            raise ValueError("alarm_id is required")
        if status not in get_args(DispositionStatus):
            raise ValueError("invalid disposition status")
        actor = {"employee_id": str(user.get("employee_id", "")), "name": str(user.get("name", ""))}
        # 串行持久化；构造完整 JSON 和磁盘写入不占查询索引锁。
        with self._write_lock:
            previous = self._items.get(alarm_id)
            history = []
            if previous is not None:
                history = [*previous["history"], {
                    key: previous[key] for key in ("status", "note", "updated_at", "updated_by")
                }]
                history = history[-20:]
            item = {
                "alarm_id": alarm_id, "status": status, "note": str(note or "").strip(),
                "updated_at": datetime.now().isoformat(timespec="seconds"), "updated_by": actor, "history": history,
            }
            updated = dict(self._items)
            updated[alarm_id] = item
            self._flush(updated)
            with self._lock:
                if alarm_id not in self._items:
                    insort(self._ordered_ids, alarm_id)
                self._items = updated
                self._version += 1
            return deepcopy(item)

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            payload = _DispositionFile.model_validate_json(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        items = {}
        for row in payload.items:
            if row.alarm_id in items:
                raise ValueError(f"duplicate disposition alarm_id: {row.alarm_id}")
            items[row.alarm_id] = row.model_dump()
        return items

    def _flush(self, items: dict[str, dict[str, Any]]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"items": list(items.values())}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
