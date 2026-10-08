"""识别记录写入与查询；冷却状态留在 Consumer 所属进程内。"""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from queue import Empty, Full, Queue
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from sqlalchemy import func, select

from AiVision.core.db import get_session, session_scope
from AiVision.core.logger import logger
from AiVision.core.media_cleanup import CLEANUP_BATCH_SIZE, MediaRecord
from AiVision.core.settings import settings
from .orm import FaceRecognitionRecord
from .schema import RecognitionRecordItem, RecognitionRecordPage

RECORD_RETRY_SECONDS = 5.0


@dataclass(frozen=True)
class _RecognitionTask:
    """固定一帧的记录数据与冷却占位，供后台写入及失败回退使用。"""
    camera_id: int
    values: tuple[dict, ...]
    frame: np.ndarray
    captured_at: datetime
    admitted_at: float
    known_keys: tuple[tuple[int, int], ...]
    has_unknowns: bool


class RecognitionRecorder:
    """Consumer 只筛选、复制和入队；固定 worker 完成一帧的截图与数据库事务。"""

    def __init__(self):
        """建立有界写入队列和摄像头冷却状态，构造时不启动后台线程。"""
        self._recorded_at: dict[tuple[int, int], float] = {}
        self._unknown_recorded_at: dict[int, float] = {}
        self._retry_at = 0.0
        self._queue: Queue[_RecognitionTask] = Queue(maxsize=settings.storage.recognition_record_queue_size)
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._directory = Path(settings.storage.data_path).expanduser().resolve() / "recognize_face"

    def start(self) -> None:
        """在生命周期锁内幂等启动记录线程。"""
        with self._lifecycle_lock:
            if self._thread is not None:
                return
            self._stop_event.clear()
            self._start_worker()

    def _start_worker(self) -> None:
        """创建固定后台写入线程，避免截图与数据库操作阻塞推理。"""
        self._thread = threading.Thread(target=self._run, name="face-recognition-writer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止接收阶段后等待队列排空；必要时启动线程处理已接受任务。"""
        with self._lifecycle_lock:
            with self._lock:
                self._stop_event.set()
            # 即使尚未 start，已接受的任务也交给 worker 排空，绝不在调用线程写盘。
            if self._thread is None and not self._queue.empty():
                self._start_worker()
            if self._thread is not None:
                self._thread.join()
                self._thread = None

    def clear_camera(self, camera_id: int) -> None:
        """清除摄像头对应的已知人员与未知人员冷却记录。"""
        with self._lock:
            self._recorded_at = {key: value for key, value in self._recorded_at.items() if key[0] != camera_id}
            self._unknown_recorded_at.pop(camera_id, None)

    def record(self, camera_id: int, detections: list[dict], cooldown_seconds: float, *, frame: np.ndarray) -> int:
        """返回本次入队记录数；排队失败不占用冷却，也不会阻塞推理。"""
        with self._lock:
            now = time.monotonic()
            if self._stop_event.is_set() or now < self._retry_at:
                return 0
            candidates: dict[tuple[int, int], dict] = {}
            unknowns: list[dict] = []
            unknown_due = now - self._unknown_recorded_at.get(camera_id, float("-inf")) >= cooldown_seconds
            for detection in detections:
                if not detection["matched"]:
                    # 摄像头级限频；同一帧的每个未知人员分别保存。
                    if unknown_due:
                        unknowns.append(detection)
                    continue
                key = (camera_id, detection["person_id"])
                if now - self._recorded_at.get(key, float("-inf")) < cooldown_seconds:
                    continue
                if key not in candidates or detection["similarity"] > candidates[key]["similarity"]:
                    candidates[key] = detection
            values = [*candidates.values(), *unknowns]
            if not values:
                return 0
            try:
                self._queue.put_nowait(_RecognitionTask(
                    camera_id=camera_id,
                    values=tuple({key: value[key] for key in ("person_id", "person_name", "similarity")} for value in values),
                    frame=frame.copy(), captured_at=datetime.now(), admitted_at=now,
                    known_keys=tuple(candidates), has_unknowns=bool(unknowns),
                ))
            except Full:
                logger.warning(f"[FaceRecognition] 记录队列已满，丢弃本帧记录 camera={camera_id}")
                return 0
            self._recorded_at.update(dict.fromkeys(candidates, now))
            if unknowns:
                self._unknown_recorded_at[camera_id] = now
            return len(values)

    def _run(self) -> None:
        """持续消费记录任务，停止信号到达后仍完成已入队任务。"""
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                task = self._queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                self._write(task)
            finally:
                self._queue.task_done()

    def _write(self, task: _RecognitionTask) -> None:
        """为一帧保存截图并在一个事务中写入识别记录。

        失败时清除孤立截图，并仅回退仍属于本任务的冷却占位，避免覆盖较新的
        记录状态；错误日志省略 SQL 参数中的人员信息。
        """
        image_path = None
        try:
            # 复用平台 DATA_PATH、PNG 编码及毫秒时间戳 + UUID 命名规范。
            self._directory.mkdir(parents=True, exist_ok=True)
            filename = task.captured_at.strftime("%Y-%m-%d_%H-%M-%S.%f")[:-3] + f"_{uuid4().hex}.png"
            image_path = self._directory / filename
            if not cv2.imwrite(str(image_path), task.frame):
                raise OSError("识别截图写入失败")
            with session_scope() as session:
                session.add_all([
                    FaceRecognitionRecord(
                        camera_id=task.camera_id, **value,
                        image_path=str(image_path), recognized_at=task.captured_at,
                    ) for value in task.values
                ])
        except Exception as exc:
            # session_scope 在事务失败时 rollback；清除已落盘而未入库的截图。
            if image_path is not None:
                try:
                    image_path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    logger.error(f"[FaceRecognition] 失败截图清理失败：{type(cleanup_error).__name__}")
            with self._lock:
                self._retry_at = time.monotonic() + RECORD_RETRY_SECONDS
                for key in task.known_keys:
                    if self._recorded_at.get(key) == task.admitted_at:
                        self._recorded_at.pop(key)
                if task.has_unknowns and self._unknown_recorded_at.get(task.camera_id) == task.admitted_at:
                    self._unknown_recorded_at.pop(task.camera_id)
            # 不输出 SQL 参数，避免人员信息进入错误日志。
            logger.error(f"[FaceRecognition] 摄像头 {task.camera_id} 识别记录写入失败：{type(exc).__name__}")


class RecognitionMediaReferences:
    """仅处理识别记录的数据库引用；扫描、容量、路径保护和调度由平台共用。"""

    media_directories = ("recognize_face",)

    def __init__(self, session_scope_factory=session_scope):
        """注入事务上下文，供公共媒体清理器查询与删除数据库引用。"""
        self._session_scope = session_scope_factory

    def iter_records(self, before):
        """按截图聚合引用，以最新引用时间决定保留期限并使用游标分批读取。"""
        cursor = None
        latest = func.max(FaceRecognitionRecord.recognized_at)
        last_id = func.max(FaceRecognitionRecord.id)
        while True:
            with self._session_scope() as session:
                # 同一截图的所有引用作为一组，保留时间由最新引用决定。
                query = session.query(last_id, latest, FaceRecognitionRecord.image_path).group_by(
                    FaceRecognitionRecord.image_path,
                ).having(latest < before)
                if cursor is not None:
                    timestamp, record_id = cursor
                    query = query.having((latest > timestamp) | ((latest == timestamp) & (last_id > record_id)))
                rows = query.order_by(latest, last_id).limit(CLEANUP_BATCH_SIZE).all()
            if not rows:
                return
            cursor = (rows[-1][1], rows[-1][0])
            for record_id, timestamp, path in rows:
                yield MediaRecord(record_id, timestamp, (path,) if path is not None else ())

    def delete_record(self, record, remove_file):
        """再次核对引用时间，仅在文件可清理且没有更新引用时删除整组记录。"""
        path = record.paths[0] if record.paths else None
        with self._session_scope() as session:
            query = session.query(FaceRecognitionRecord).filter(FaceRecognitionRecord.image_path == path)
            latest = query.with_entities(func.max(FaceRecognitionRecord.recognized_at)).scalar()
            if latest is None or latest > record.created_at:
                return 0
            if path is not None and not remove_file(path):
                return 0
            count = query.delete(synchronize_session=False)
        return count

    def referenced_paths(self, paths):
        """批量返回仍被识别记录引用的路径，保护共享截图不被误清理。"""
        with self._session_scope() as session:
            return {str(path) for (path,) in session.query(FaceRecognitionRecord.image_path).filter(
                FaceRecognitionRecord.image_path.in_([str(path) for path in paths]),
            ).distinct().all()}


def get_recognition_image(record_id: int, *, departments: list[str] | None = None) -> Path | None:
    """按事业部权限查询记录，并只返回识别存储根目录内实际存在的文件。"""
    from AiVision.cameras.orm import AiCameraConfig

    with get_session() as session:
        statement = select(FaceRecognitionRecord.image_path).join(
            AiCameraConfig, AiCameraConfig.id == FaceRecognitionRecord.camera_id,
        ).where(
            FaceRecognitionRecord.id == record_id,
        )
        if departments is not None:
            statement = statement.where(AiCameraConfig.department.in_(departments))
        image_path = session.scalar(statement)
    if not image_path:
        return None
    path = Path(image_path).resolve()
    root = Path(settings.storage.data_path).expanduser().resolve() / "recognize_face"
    return path if path.is_relative_to(root) and path.is_file() else None


def list_recognition_records(camera_id: int | None, page: int, page_size: int, *, department: str) -> RecognitionRecordPage:
    """按事业部和可选摄像头过滤，按识别时间及 ID 倒序分页返回记录。"""
    from AiVision.cameras.orm import AiCameraConfig

    from AiVision.departments.department_registry import require_department

    filters = [AiCameraConfig.department == require_department(department)]
    if camera_id is not None:
        filters.append(FaceRecognitionRecord.camera_id == camera_id)
    with get_session() as session:
        statement = select(FaceRecognitionRecord).join(
            AiCameraConfig, AiCameraConfig.id == FaceRecognitionRecord.camera_id,
        ).where(*filters)
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
        records = session.scalars(statement.order_by(
            FaceRecognitionRecord.recognized_at.desc(), FaceRecognitionRecord.id.desc(),
        ).offset((page - 1) * page_size).limit(page_size)).all()
        return RecognitionRecordPage(
            total=total, page=page, page_size=page_size,
            items=[RecognitionRecordItem.model_validate(record) for record in records],
        )
