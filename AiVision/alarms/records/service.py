"""
alarms/records/service.py
违规图片异步批量写入器 
设计原则:
    - Consumer 调 enqueue() 后立即返回(磁盘写入和 SQL 提交都异步)
    - 满 N 条或超 M 秒批量提交
    - 定时清理过期或超过容量上限的报警图片和关联记录
"""
from __future__ import annotations
import datetime
import json
import os
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from queue import Queue, Empty, Full      # 线程之间使用的队列

import cv2
import numpy as np
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

from AiVision.core.db import session_scope
from AiVision.core.logger import logger
from AiVision.core.media_cleanup import GIB, MediaCleanupStats, MediaReferences
from AiVision.core.settings import settings
from .cleanup import ViolationMediaCleaner
from .orm import AiAlarmEvent
from ..validation import validate_alarm_identity

class AsyncViolationWriter:
    """
    把告警图片保存到磁盘，并把告警信息写入数据库
    设计：
        Consumer发现告警 -> 写入队列 -> Consumer继续工作 -> 后台线程慢慢保存数据 -> 批量写数据库
    """
    def __init__(self):
        """读取写入与保留策略，建立有界队列、存储目录和媒体清理器。"""
        self._queue: Queue = Queue(maxsize=1000)       # 最多暂存1000个待处理告警
        self._stop_event = threading.Event()           # 线程控制工具，告诉后台线程该停了
        self._enqueue_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None   # 真正负责处理告警Queue的后台线程
        self._scheduler: BackgroundScheduler | None = None # 定时任务调度器（定期清理旧告警图片和视频）

        # 从settings读配置
        self._batch_size = settings.storage.max_event_count       # 攒多少条以后一次性写数据库
        self._flush_interval = settings.storage.flush_interval_seconds    # 过多久时间必须写入数据库（不管也没有攒够）
        self._write_attempts = settings.storage.alarm_db_write_attempts
        self._retry_backoff = settings.storage.alarm_db_retry_backoff_seconds
        self._data_path = Path(settings.storage.data_path).expanduser().resolve()   # 数据存的地址
        self._retention_days = max(1, int(settings.storage.alarm_media_retention_days))    # 告警媒体至少保留一天
        self._max_media_bytes = max(
            0,
            int(float(settings.storage.alarm_media_max_gb) * GIB),
        )
        self._cleanup_interval_minutes = max(
            1,
            int(settings.storage.alarm_media_cleanup_interval_minutes),
        )
        # 创建目录
        self._data_path.mkdir(parents=True, exist_ok=True)
        # 创建Cleaner，它负责检查旧图片和视频，超过保存天数或者总容量超过上限，旧删除旧媒体，并且同步处理数据库记录
        self._media_cleaner = ViolationMediaCleaner(
            self._data_path,
            retention_days=self._retention_days,
            max_bytes=self._max_media_bytes,
        )

    # ---------- 公开接口 ----------
    def configure_media_cleanup(self, *references: MediaReferences) -> None:
        """在平台启动时接入业务引用，共用现有 scheduler、保留策略和总容量。"""
        self._media_cleaner.set_additional_references(references)

    def enqueue(
        self,
        frame: np.ndarray,
        violation_type: int,
        camera_no: str | None,
        *,
        feature_name: str,
        department: str,
        subject_type: str = "camera",
        subject_id: str = "",
        subject_name: str = "",
        reason: str = "",
        event_metadata: dict | None = None,
        video_path: str | None = None,
        video_status: str | None = None,
    ):
        """从 Consumer 调来的入口 — 立即返回,后台线程负责落盘和 DB 写，属于普通异步告警写入入口"""
        # 告警类型
        validate_alarm_identity(violation_type, feature_name, department)
        # 构造一个字典然后放入队列
        item = {
            "frame": frame.copy(),
            "violation_type": violation_type,
            "feature_name": feature_name,
            "department": department,
            "camera_no": camera_no,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "reason": reason,
            "event_metadata": deepcopy(event_metadata or {}),
            "video_path": video_path,
            "video_status": video_status,
            "ts": datetime.datetime.now(),
        }
        # 帧和嵌套元数据在入队前冻结；停止门控与入队使用同一把锁。
        with self._enqueue_lock:
            if self._stop_event.is_set():
                logger.warning(f"[ViolationWriter] 已停止接收告警 feature={feature_name} camera={camera_no}")
                return
            try:
                self._queue.put_nowait(item)
            except Full:
                logger.warning(f"[ViolationWriter] 告警队列已满，丢弃本条入库请求 feature={feature_name} camera={camera_no}")
    def save_now(
        self,
        *,
        frame: np.ndarray,
        violation_type: int,
        camera_no: str | None,
        feature_name: str,
        department: str,
        subject_type: str = "camera",
        subject_id: str = "",
        subject_name: str = "",
        reason: str = "",
        event_metadata: dict | None = None,
        video_path: str | None = None,
        video_status: str | None = None,
    ) -> AiAlarmEvent | None:
        """同步保存单条违规记录并返回已入库对象。
        
        与上一个函数很像，但是它是异步，这个函数是同步（因为微信图文卡片需要马上拿到 ）

        微信图文卡片需要立即拿到 alarm_id 和图片地址，因此不能等待后台批量 flush。
        失败时返回 None，由调用方决定是否继续其他告警通道。

        流程：
            微信需要立即发报警
            ↓
            save_now()
            ↓
            校验正式字段
            ↓
            _save_alarm_snapshot()
            ↓
            PNG马上落盘
            ↓
            AiAlarmEvent(**row)
            ↓
            session.add()
            ↓
            flush拿alarm_id
            ↓
            commit
            ↓
            返回AiAlarmEvent
            ↓
            微信卡片拿id和图片
        """
        validate_alarm_identity(violation_type, feature_name, department)
        # _save_alarm_snapshot:1、把frame真正写成PNG文件，2、构造可以直接给AiAlarmEvent入库的字典
        row = self._save_alarm_snapshot({
            "frame": frame,
            "violation_type": violation_type,
            "feature_name": feature_name,
            "department": department,
            "camera_no": camera_no,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "reason": reason,
            "event_metadata": event_metadata or {},
            "video_path": video_path,
            "video_status": video_status,
            "ts": datetime.datetime.now(),
        })
        # 如果图片保存失败，这条告警不入数据库
        if row is None:
            return None
        try:
            # 正式写数据库，成功commit，异常rollback，最后close（真正的提交是session_scope退出的时候）
            with session_scope() as session:
                item = AiAlarmEvent(**row)
                session.add(item)        # 我要 INSERT 一条新的告警记录。
                session.flush()          # flush后数据库生成id
                return item
        except Exception as e:
            logger.warning(f"[ViolationWriter] 同步提交失败: {e}")
            return None

    def update_video_status(self, video_path: str, status: str) -> None:
        """告警视频生成完成后，更新数据库里的video_status"""
        # 只允许ready和faild两个状态
        normalized_status = status if status in {"ready", "failed"} else "failed"
        # 非企微告警使用批量入库，录像可能先于数据库 flush 完成；短暂重试
        # 能避免记录永久停留在 pending，同时不阻塞检测和录像线程。
        for attempt in range(12):
            try:
                with session_scope() as session:
                    # 查询数据库
                    row = (
                        session.query(AiAlarmEvent)
                        .filter(AiAlarmEvent.video_path == str(video_path))
                        .first()
                    )
                    if row is not None:
                        # SQLAlchemy追踪变化
                        row.video_status = normalized_status
                        return
            except Exception as exc:
                logger.warning(
                    f"[ViolationWriter] 报警视频状态更新失败 "
                    f"path={video_path} attempt={attempt + 1}: {exc}"
                )
            if attempt < 11:
                time.sleep(0.5)
        logger.warning(f"[ViolationWriter] 未找到报警视频对应记录 path={video_path}")

    # ---------- 生命周期 ----------
    def start(self):
        """启动后台写入系统"""
        with self._lifecycle_lock:
            self._start()

    def _start(self):
        """启动异步记录线程及单实例定期清理任务，启动后立即安排一次清理。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        # 创建线程，新线程执行_run():负责保存新告警
        self._thread = threading.Thread(target=self._run, daemon=True, name="violation-writer")
        self._thread.start()
        # 负责定时清理老告警
        self._scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Shanghai"))
        # 每隔cleanup_interval执行一次_delete_old
        self._scheduler.add_job(
            self._delete_old,
            "interval",
            minutes=self._cleanup_interval_minutes,
            next_run_time=datetime.datetime.now(pytz.timezone("Asia/Shanghai")),    # Scheduler 一启动，就先执行一次
            id="cleanup_violation_media",
            max_instances=1,                # 最多同时有一个清理任务
            coalesce=True,                  # 程序阻塞错过好几次执行时间，会合并成一次执行
        )
        # scheduler开始工作
        self._scheduler.start()
        logger.info(
            "[ViolationWriter] 已启动 + 平台媒体清理任务已注册 "
            f"retention_days={self._retention_days} "
            f"max_gb={self._max_media_bytes / GIB:.2f} "
            f"interval_minutes={self._cleanup_interval_minutes}"
        )

    def stop(self):
        """系统关闭"""
        with self._lifecycle_lock:
            with self._enqueue_lock:
                self._stop_event.set()
            if self._thread:
                # 当前线程等待后台Writer线程退出
                self._thread.join()
                self._thread = None
            elif not self._queue.empty():
                # 支持 start 前已入队的请求；停止返回时不遗留队列数据。
                self._run()
            if self._scheduler:
                try:
                    # 发停止指令
                    self._scheduler.shutdown(wait=True)
                except Exception as exc:
                    logger.warning(f"[ViolationWriter] 停止清理调度器失败: {exc}")
                self._scheduler = None

    # ---------- 内部 ----------
    def _run(self):
        """真正的后台循环"""
        batch: list[dict] = []
        # 上一次批量提交数据库是什么时候
        last_flush = time.monotonic()
        # 只要数据库还没停止一直循环
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                # 从enqueue塞进去的Queue里拿一条告警
                item = self._queue.get(timeout=0.5)
                # 写入磁盘（先写磁盘再考虑数据库）
                row = self._save_alarm_snapshot(item)
                if row is not None:
                    batch.append(row)
                else:
                    self._queue.task_done()
            except Empty:
                pass

            now = time.monotonic()
            # 数量够了或者时间到了
            should_flush = (
                len(batch) >= self._batch_size
                or (batch and now - last_flush > self._flush_interval)
            )
            # 真正提交批量写数据库
            if should_flush:
                self._complete_batch(batch)
                batch.clear()
                last_flush = now

        # 退出时提交当前batch
        if batch:
            self._complete_batch(batch)

    def _save_alarm_snapshot(self, item: dict) -> dict | None:
        """同步写盘 — 返回供 DB 入库的行字典,失败返回 None"""
        try:
            # 图片目录按告警类型编号
            sub = self._data_path / str(item["violation_type"])
            sub.mkdir(parents=True, exist_ok=True)
            # 文件名去掉最后三位微秒，所以图片精确到毫秒
            fname = item["ts"].strftime("%Y-%m-%d_%H-%M-%S.%f")[:-3] + f"_{uuid.uuid4().hex}.png"
            # 真正保存图片，把 NumPy 数组真正编码成 PNG 并写到磁盘。
            full_path = sub / fname
            if not cv2.imwrite(str(full_path), item["frame"]):
                raise OSError(f"OpenCV 写入报警图片失败: {full_path}")
            return {
                "image_path": str(full_path),
                "video_path": item.get("video_path"),
                "video_status": item.get("video_status"),
                "violation_type": item["violation_type"],
                "feature_name": item["feature_name"],
                "department": item["department"],
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

    def _flush_batch(self, batch: list[dict]) -> bool:
        """批量写MySQL"""
        for attempt in range(self._write_attempts):
            try:
                # row1 → AiAlarmEvent对象1 → session.add
                with session_scope() as session:
                    # 重试时以本次快照的唯一文件名识别已提交记录，处理 commit 回执丢失。
                    existing = set()
                    if attempt:
                        existing = {path for (path,) in session.query(AiAlarmEvent.image_path).filter(
                            AiAlarmEvent.image_path.in_([row["image_path"] for row in batch])
                        ).all()}
                    for row in batch:
                        if row["image_path"] not in existing:
                            session.add(AiAlarmEvent(**row))
                logger.info(f"[ViolationWriter] 提交 {len(batch)} 条违规记录")
                return True
            except Exception as exc:
                logger.warning(
                    f"[ViolationWriter] 批量提交失败 attempt={attempt + 1}/{self._write_attempts}: {exc}"
                )
                if attempt + 1 < self._write_attempts:
                    time.sleep(self._retry_backoff * (2 ** attempt))
        return False

    def _complete_batch(self, batch: list[dict]) -> None:
        """提交成功或保存失败批次后，才将队列中的请求标记为处理完成。"""
        try:
            if not self._flush_batch(batch):
                self._preserve_failed_batch(batch)
        finally:
            for _ in batch:
                self._queue.task_done()

    def _preserve_failed_batch(self, batch: list[dict]) -> None:
        """有限重试耗尽后留存恢复资料；不自动重放，以免不明确的提交结果造成重复告警。"""
        try:
            directory = self._data_path / "alarm_failed_batches"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{uuid.uuid4().hex}.json"
            payload = [dict(row, create_time=row["create_time"].isoformat()) for row in batch]
            with path.open("x", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            logger.error(f"[ViolationWriter] 入库重试耗尽，{len(batch)} 条告警待人工恢复: {path}")
        except Exception as exc:
            logger.error(
                f"[ViolationWriter] 入库及失败批次留存均失败，records={len(batch)} "
                f"images={[row['image_path'] for row in batch]}: {exc}"
            )

    def _delete_old(self, now: datetime.datetime | None = None) -> MediaCleanupStats:
        """统一清理报警媒体与已接入的业务媒体，数据库引用仍由各业务处理。"""
        return self._media_cleaner.cleanup(now=now)


violation_writer = AsyncViolationWriter()
