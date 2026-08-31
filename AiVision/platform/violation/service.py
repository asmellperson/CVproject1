# 文件说明：封装业务服务的业务规则与持久化访问。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：违规图片落盘 + 数据库异步写入；输入与输出详见下方说明
# 参数：无。
# 返回：AsyncViolationWriter；返回新建的 `AsyncViolationWriter` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AsyncViolationWriter:
    """违规图片落盘 + 数据库异步写入"""

    # 功能：初始化或配置 `__init__` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Queue`、`threading.Event`、`Path(settings.storage.data_path).expanduser().resolve`、`Path(settings.storage.data_path).expanduser`、`Path`、`max`、`int`、`float`、`self._data_path.mkdir`、`ViolationMediaCleaner`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
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

    # 功能：从 Consumer 调来的入口 — 立即返回,后台线程负责落盘和 DB 写；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    #   - `violation_type`（int）：`violation_type` 对应的业务输入值
    #   - `camera_no`（str）：`camera_no` 对应的业务输入值
    #   - `subject_type`（str）：`subject_type` 对应的业务输入值；默认值为 `'camera'`
    #   - `subject_id`（str）：`subject_id` 对应业务对象的唯一标识；默认值为 `''`
    #   - `subject_name`（str）：`subject_name` 对应的业务输入值；默认值为 `''`
    #   - `reason`（str）：`reason` 对应的业务输入值；默认值为 `''`
    #   - `event_metadata`（dict | None）：`event_metadata` 对应的业务输入值；默认值为 `None`
    #   - `video_path`（str | None）：`video_path` 对应的业务输入值；默认值为 `None`
    #   - `video_status`（str | None）：`video_status` 对应的业务输入值；默认值为 `None`
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._queue.put_nowait`、`datetime.datetime.now`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
        video_path: str | None = None,
        video_status: str | None = None,
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
            "video_path": video_path,
            "video_status": video_status,
            "ts": datetime.datetime.now(),
        })

    # 功能：同步保存单条违规记录并返回已入库对象；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    #   - `violation_type`（int）：`violation_type` 对应的业务输入值
    #   - `camera_no`（str）：`camera_no` 对应的业务输入值
    #   - `subject_type`（str）：`subject_type` 对应的业务输入值；默认值为 `'camera'`
    #   - `subject_id`（str）：`subject_id` 对应业务对象的唯一标识；默认值为 `''`
    #   - `subject_name`（str）：`subject_name` 对应的业务输入值；默认值为 `''`
    #   - `reason`（str）：`reason` 对应的业务输入值；默认值为 `''`
    #   - `event_metadata`（dict | None）：`event_metadata` 对应的业务输入值；默认值为 `None`
    #   - `video_path`（str | None）：`video_path` 对应的业务输入值；默认值为 `None`
    #   - `video_status`（str | None）：`video_status` 对应的业务输入值；默认值为 `None`
    # 返回：AiViolationImage | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._save_image`、`datetime.datetime.now`、`session_scope`、`AiViolationImage`、`session.add`、`session.flush`、`logger.warning`。
    # 副作用/注意事项：可能读取或修改数据库事务；会向日志系统输出运行或异常信息。
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
        video_path: str | None = None,
        video_status: str | None = None,
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
            "video_path": video_path,
            "video_status": video_status,
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

    # 功能：Update the alarm row after its asynchronous evidence clip finishes；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `video_path`（str）：`video_path` 对应的业务输入值
    #   - `status`（str）：当前或目标状态值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`range`、`session_scope`、`session.query(AiViolationImage).filter(AiViolationImage.video_path ==
    #          str(video_path)).first`、`session.query(AiViolationImage).filter`、`session.query`、`str`、`logger.warning`、`time.sleep`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def update_video_status(self, video_path: str, status: str) -> None:
        """Update the alarm row after its asynchronous evidence clip finishes."""
        normalized_status = status if status in {"ready", "failed"} else "failed"
        # 非企微告警使用批量入库，录像可能先于数据库 flush 完成；短暂重试
        # 能避免记录永久停留在 pending，同时不阻塞检测和录像线程。
        for attempt in range(12):
            try:
                with session_scope() as session:
                    row = (
                        session.query(AiViolationImage)
                        .filter(AiViolationImage.video_path == str(video_path))
                        .first()
                    )
                    if row is not None:
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

    # 功能：启动或执行 `start` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._thread.is_alive`、`self._stop_event.clear`、`threading.Thread`、`self._thread.start`、`BackgroundScheduler`、`pytz.timezone`、`self._scheduler.add_job`、`datetime.datetime.now`、`self._scheduler.start`、`logger.info`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
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

    # 功能：停止并释放 `stop` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.set`、`self._thread.join`、`self._scheduler.shutdown`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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

    # 功能：启动或执行 `_run` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`time.time`、`self._stop_event.is_set`、`self._queue.get`、`self._save_image`、`batch.append`、`len`、`self._flush_batch`、`batch.clear`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：同步写盘 — 返回供 DB 入库的行字典,失败返回 None；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `item`（dict）：`item` 对应的业务输入值
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/service.py` 的 `AsyncViolationWriter::save_now`
    #         调用本符号；`AiVision/platform/violation/service.py` 的 `AsyncViolationWriter::_run` 调用本符号
    #   - 内部调用：`str`、`sub.mkdir`、`item['ts'].strftime`、`cv2.imwrite`、`OSError`、`item.get`、`logger.warning`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
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
                "video_path": item.get("video_path"),
                "video_status": item.get("video_status"),
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

    # 功能：实现 `_flush_batch` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `batch`（list[dict]）：`batch` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/service.py` 的 `AsyncViolationWriter::_run` 调用本符号
    #   - 内部调用：`session_scope`、`session.add`、`AiViolationImage`、`logger.info`、`len`、`logger.warning`。
    # 副作用/注意事项：可能读取或修改数据库事务；会向日志系统输出运行或异常信息。
    def _flush_batch(self, batch: list[dict]):
        try:
            with session_scope() as session:
                for row in batch:
                    session.add(AiViolationImage(**row))
            logger.info(f"[ViolationWriter] 提交 {len(batch)} 条违规记录")
        except Exception as e:
            logger.warning(f"[ViolationWriter] 批量提交失败: {e}")

    # 功能：清理过期图片和超出容量上限的最旧图片，并同步删除数据库记录；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `now`（datetime.datetime | None）：`now` 对应的业务输入值；默认值为 `None`
    # 返回：MediaCleanupStats；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._media_cleaner.cleanup`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _delete_old(self, now: datetime.datetime | None = None) -> MediaCleanupStats:
        """清理过期图片和超出容量上限的最旧图片，并同步删除数据库记录。"""
        return self._media_cleaner.cleanup(now=now)


violation_writer = AsyncViolationWriter()
