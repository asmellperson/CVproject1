"""
platform/violation/service.py
违规图片异步批量写入器 — 替代旧 SQL 类里 run / _commit_batch / insert_alarm 那一坨。

设计原则:
    - Consumer 调 enqueue() 后立即返回(磁盘写入和 SQL 提交都异步)
    - 满 N 条或超 M 秒批量提交
    - 定时清理超过 90 天的旧记录
"""
from __future__ import annotations
import datetime
import os
import threading
import time
from queue import Queue, Empty

import cv2
import numpy as np
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

from core.db import session_scope
from core.logger import logger
from core.settings import settings
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
        self._data_path = settings.storage.data_path

        os.makedirs(self._data_path, exist_ok=True)

    # ---------- 公开接口 ----------

    def enqueue(self, frame: np.ndarray, violation_type: int, camera_no: str):
        """从 Consumer 调来的入口 — 立即返回,后台线程负责落盘和 DB 写"""
        self._queue.put_nowait({
            "frame": frame,
            "violation_type": violation_type,
            "camera_no": camera_no,
            "ts": datetime.datetime.now(),
        })

    def save_now(self, *, frame: np.ndarray, violation_type: int, camera_no: str) -> AiViolationImage | None:
        """同步保存单条违规记录并返回已入库对象。

        微信图文卡片需要立即拿到 alarm_id 和图片地址，因此不能等待后台批量 flush。
        失败时返回 None，由调用方决定是否继续其他告警通道。
        """
        row = self._save_image({
            "frame": frame,
            "violation_type": violation_type,
            "camera_no": camera_no,
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
        self._scheduler.add_job(self._delete_old, "cron", hour=2, minute=0, id="delete_old_violations")
        self._scheduler.start()
        logger.info("[ViolationWriter] 已启动 + 定时清理任务已注册")

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
            sub = os.path.join(self._data_path, str(item["violation_type"]))
            os.makedirs(sub, exist_ok=True)
            fname = item["ts"].strftime("%Y-%m-%d_%H-%M-%S.%f")[:-3] + ".png"
            full_path = os.path.join(sub, fname)
            cv2.imwrite(full_path, item["frame"])
            return {
                "image_path": full_path,
                "violation_type": item["violation_type"],
                "camera_no": item["camera_no"],
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

    def _delete_old(self):
        cutoff = datetime.datetime.now() - datetime.timedelta(days=90)
        try:
            with session_scope() as session:
                deleted = (
                    session.query(AiViolationImage)
                    .filter(AiViolationImage.create_time < cutoff)
                    .delete()
                )
            logger.info(f"[ViolationWriter] 清理了 {deleted} 条过期记录(早于 {cutoff})")
        except Exception as e:
            logger.warning(f"[ViolationWriter] 清理失败: {e}")


violation_writer = AsyncViolationWriter()
