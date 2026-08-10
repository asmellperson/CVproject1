"""
platform/violation/service.py
违规图片异步批量写入器 — 替代旧 SQL 类里 run / _commit_batch / insert_alarm 那一坨。

设计原则:
    - Consumer 调 enqueue() 后立即返回(磁盘写入和 SQL 提交都异步)
    - 满 N 条或超 M 秒批量提交
    - 定时清理过期或超过容量上限的报警图片和关联记录
"""
from __future__ import annotations
import datetime
import threading
import time
from pathlib import Path
from queue import Queue, Empty

import cv2
import numpy as np
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

from core.db import session_scope
from core.logger import logger
from core.settings import settings
from .cleanup import GIB, MediaCleanupStats, ViolationMediaCleaner
from .orm import AiViolationImage


class AsyncViolationWriter:
    """违规图片落盘 + 数据库异步写入"""

    def __init__(self):
        self._queue: Queue = Queue(maxsize=1000)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._scheduler: BackgroundScheduler | None = None

        self._batch_size = settings.storage.max_event_count
        self._flush_interval = settings.storage.flush_interval_seconds
        self._data_path = Path(settings.storage.data_path).expanduser().resolve()
        self._retention_days = max(1, int(settings.storage.alarm_media_retention_days))
        self._max_media_bytes = max(
            0,
            int(float(settings.storage.alarm_media_max_gb) * GIB),
        )
        self._cleanup_interval_minutes = max(
            1,
            int(settings.storage.alarm_media_cleanup_interval_minutes),
        )

        self._data_path.mkdir(parents=True, exist_ok=True)
        self._media_cleaner = ViolationMediaCleaner(
            self._data_path,
            retention_days=self._retention_days,
            max_bytes=self._max_media_bytes,
        )

    # ---------- 公开接口 ----------

    def enqueue(
        self,
        frame: np.ndarray,
        violation_type: int,
        camera_no: str,
        *,
        subject_type: str = "camera",
        subject_id: str = "",
        subject_name: str = "",
        reason: str = "",
        event_metadata: dict | None = None,
    ):
        """从 Consumer 调来的入口 — 立即返回,后台线程负责落盘和 DB 写"""
        self._queue.put_nowait({
            "frame": frame,
            "violation_type": violation_type,
            "camera_no": camera_no,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "reason": reason,
            "event_metadata": event_metadata or {},
            "ts": datetime.datetime.now(),
        })

    def save_now(
        self,
        *,
        frame: np.ndarray,
        violation_type: int,
        camera_no: str,
        subject_type: str = "camera",
        subject_id: str = "",
        subject_name: str = "",
        reason: str = "",
        event_metadata: dict | None = None,
    ) -> AiViolationImage | None:
        """同步保存单条违规记录并返回已入库对象。

        微信图文卡片需要立即拿到 alarm_id 和图片地址，因此不能等待后台批量 flush。
        失败时返回 None，由调用方决定是否继续其他告警通道。
        """
        row = self._save_image({
            "frame": frame,
            "violation_type": violation_type,
            "camera_no": camera_no,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "reason": reason,
            "event_metadata": event_metadata or {},
            "ts": datetime.datetime.now(),
        })
        if row is None:
            return None
        try:
            with session_scope() as session:
                item = AiViolationImage(**row)
                session.add(item)
                session.flush()
                return item
        except Exception as e:
            logger.warning(f"[ViolationWriter] 同步提交失败: {e}")
            return None

    # ---------- 生命周期 ----------

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="violation-writer")
        self._thread.start()

        self._scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Shanghai"))
        self._scheduler.add_job(
            self._delete_old,
            "interval",
            minutes=self._cleanup_interval_minutes,
            next_run_time=datetime.datetime.now(pytz.timezone("Asia/Shanghai")),
            id="cleanup_violation_media",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info(
            "[ViolationWriter] 已启动 + 报警图片清理任务已注册 "
            f"retention_days={self._retention_days} "
            f"max_gb={self._max_media_bytes / GIB:.2f} "
            f"interval_minutes={self._cleanup_interval_minutes}"
        )

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass

    # ---------- 内部 ----------

    def _run(self):
        batch: list[dict] = []
        last_flush = time.time()

        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
                # 落盘
                row = self._save_image(item)
                if row is not None:
                    batch.append(row)
            except Empty:
                pass

            now = time.time()
            should_flush = (
                len(batch) >= self._batch_size
                or (batch and now - last_flush > self._flush_interval)
            )
            if should_flush:
                self._flush_batch(batch)
                batch.clear()
                last_flush = now

        # 退出时清空队列
        if batch:
            self._flush_batch(batch)

    def _save_image(self, item: dict) -> dict | None:
        """同步写盘 — 返回供 DB 入库的行字典,失败返回 None"""
        try:
            sub = self._data_path / str(item["violation_type"])
            sub.mkdir(parents=True, exist_ok=True)
            fname = item["ts"].strftime("%Y-%m-%d_%H-%M-%S.%f")[:-3] + ".png"
            full_path = sub / fname
            if not cv2.imwrite(str(full_path), item["frame"]):
                raise OSError(f"OpenCV 写入报警图片失败: {full_path}")
            return {
                "image_path": str(full_path),
                "violation_type": item["violation_type"],
                "camera_no": item["camera_no"],
                "subject_type": item.get("subject_type") or "camera",
                "subject_id": item.get("subject_id") or "",
                "subject_name": item.get("subject_name") or "",
                "reason": item.get("reason") or "",
                "event_metadata": item.get("event_metadata") or {},
                "create_time": item["ts"],
            }
        except Exception as e:
            logger.warning(f"[ViolationWriter] 落盘失败: {e}")
            return None

    def _flush_batch(self, batch: list[dict]):
        try:
            with session_scope() as session:
                for row in batch:
                    session.add(AiViolationImage(**row))
            logger.info(f"[ViolationWriter] 提交 {len(batch)} 条违规记录")
        except Exception as e:
            logger.warning(f"[ViolationWriter] 批量提交失败: {e}")

    def _delete_old(self, now: datetime.datetime | None = None) -> MediaCleanupStats:
        """清理过期图片和超出容量上限的最旧图片，并同步删除数据库记录。"""
        return self._media_cleaner.cleanup(now=now)


violation_writer = AsyncViolationWriter()
