from __future__ import annotations
import torch
if torch.cuda.is_available():
    try:
        torch.cuda.set_per_process_memory_fraction(0.45, device=0)  # 最多用 45% = ~4.6GB
        torch.cuda.empty_cache()
    except RuntimeError as exc:
        print(f"[WARN] CUDA memory limit skipped: {exc}")
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
from ultralytics import YOLO

from .alarm_clip_recorder import AlarmClipRecorder
from .alarms import AlarmManager
from .behavior import BehaviorEngine, RuleDecision
from .config import AppConfig
from .consensus import CameraDecisionBundle, MultiCameraConsensus
from .drawing import draw_alarm_banner, draw_detection
from .pose import PoseEstimator
from .state import AppState
from .types import Detection
from .uniform import UniformClassifier
from .utils import ensure_dir
from .wechat_notifier import WeChatNotifier


class LatestFrameBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_id: int = 0
        self._ts: float = 0.0

    def put(self, frame: np.ndarray) -> None:
        with self._lock:
            self._frame = frame
            self._frame_id += 1
            self._ts = time.time()

    def get(self) -> tuple[int, float, np.ndarray | None]:
        with self._lock:
            if self._frame is None:
                return self._frame_id, self._ts, None
            return self._frame_id, self._ts, self._frame.copy()


class RTSPReader(threading.Thread):
    def __init__(
        self,
        *,
        camera_name: str,
        source: str,
        frame_width: int,
        frame_height: int,
        reconnect_seconds: float,
        camera_buffer_size: int,
        buffer: LatestFrameBuffer,
        stop_event: threading.Event,
    ):
        super().__init__(daemon=True, name=f"guard-room-reader-{camera_name}")
        self.camera_name = camera_name
        self.source = source
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.reconnect_seconds = reconnect_seconds
        self.camera_buffer_size = camera_buffer_size
        self.buffer = buffer
        self.stop_event = stop_event

        self.meta: dict[str, float] = {
            "fps": 12.0,
            "width": frame_width,
            "height": frame_height,
        }
        self.error: str | None = None

    def run(self) -> None:
        source = self._normalize_source(self.source)

        while not self.stop_event.is_set():
            cap = cv2.VideoCapture(source)
            try:
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, self.camera_buffer_size)
                except Exception:
                    pass

                if not cap.isOpened():
                    self.error = f"{self.camera_name} 无法打开视频源: {self.source}"
                    time.sleep(self.reconnect_seconds)
                    continue

                fps = cap.get(cv2.CAP_PROP_FPS)
                width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                self.meta["fps"] = fps if fps and fps > 1 else 12.0
                self.meta["width"] = int(width or self.frame_width)
                self.meta["height"] = int(height or self.frame_height)
                self.error = None

                fail_count = 0
                while not self.stop_event.is_set():
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        fail_count += 1
                        if fail_count >= 20:
                            break
                        time.sleep(0.05)
                        continue

                    fail_count = 0
                    self.buffer.put(frame)
            finally:
                cap.release()

            if not self.stop_event.is_set():
                self.error = f"{self.camera_name} 视频流中断，正在重连"
                time.sleep(self.reconnect_seconds)

    @staticmethod
    def _normalize_source(source: str):
        return int(source) if str(source).isdigit() else source


class ManualRecorder:
    def __init__(self, output_dir: str | Path, fps: int = 10):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.fps = fps
        self._lock = threading.Lock()
        self._want_recording = False
        self.recording = False
        self.writer = None
        self.current_file: str | None = None

    def start(self) -> dict:
        with self._lock:
            self._want_recording = True
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._want_recording = False
            if self.writer is not None:
                self.writer.release()
                self.writer = None
            self.recording = False
            saved_file = self.current_file
            self.current_file = None
            data = self.status()
            data["saved_file"] = saved_file
            return data

    def write(self, frame: np.ndarray) -> None:
        with self._lock:
            if not self._want_recording:
                return

            if self.writer is None:
                h, w = frame.shape[:2]
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = self.output_dir / f"manual_record_{ts}.mp4"
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                self.writer = cv2.VideoWriter(str(path), fourcc, self.fps, (w, h))
                self.current_file = str(path)
                self.recording = True

            if self.writer is not None:
                self.writer.write(frame)

    def status(self) -> dict:
        return {
            "recording": self.recording or self._want_recording,
            "output_dir": str(self.output_dir),
            "current_file": self.current_file,
        }


@dataclass
class SingleCameraResult:
    camera_id: str
    annotated_frame: np.ndarray
    all_persons: List[Detection]
    guard_persons: List[Detection]
    phones: List[Detection]
    pose_features: Dict[int, Dict[str, float]]
    local_decisions: Dict[str, RuleDecision]
    guard_present: bool
    guard_confidence: float
    camera_online: bool

class TrackGuardGate:
    def __init__(self, hold_seconds: float = 1.0):
        self.hold_seconds = hold_seconds
        self.last_positive_ts: Dict[int, float] = {}

    def keep(self, track_id: int | None, timestamp_s: float, is_guard_now: bool) -> bool:
        if track_id is None:
            return is_guard_now

        if is_guard_now:
            self.last_positive_ts[track_id] = timestamp_s
            return True

        last_ts = self.last_positive_ts.get(track_id, -1e9)
        return (timestamp_s - last_ts) <= self.hold_seconds


class UniformCache:
    def __init__(self, ttl_seconds: float = 1):
        self.ttl = ttl_seconds
        self._cache: dict[tuple[str, int], tuple[float, bool, float]] = {}
        self._lock = threading.Lock()

    def get_or_infer(
        self,
        camera_id: str,
        track_id: int | None,
        timestamp_s: float,
        classifier: UniformClassifier,
        frame: np.ndarray,
        bbox: tuple[int, int, int, int],
    ) -> tuple[bool, float]:
        if track_id is not None:
            key = (camera_id, track_id)
            with self._lock:
                cached = self._cache.get(key)
                if cached and (timestamp_s - cached[0]) < self.ttl:
                    return cached[1], cached[2]

        is_guard, conf = classifier.predict_person(frame, bbox)

        if track_id is not None:
            with self._lock:
                self._cache[(camera_id, track_id)] = (timestamp_s, is_guard, conf)
                if len(self._cache) > 200:
                    expired = [
                        k for k, v in self._cache.items()
                        if (timestamp_s - v[0]) > self.ttl * 3
                    ]
                    for k in expired:
                        self._cache.pop(k, None)

        return is_guard, conf


class GuardRoomRuntime:
    def __init__(
        self,
        config: AppConfig,
        state: AppState,
        *,
        wechat_notifier: WeChatNotifier | None = None,
        alarm_user: str = "",
        alarm_camera_name: str = "值班室双摄像头",
    ):
        self.cfg = config
        self.state = state
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self._alarm_latches: dict[str, bool] = {}
        self._banner_alarm = None
        self._banner_expire_ts: float = 0.0
        self._banner_show_seconds: float = 1.0

        self.recorder = ManualRecorder(
            output_dir=Path(self.cfg.video.output_dir) / "records",
            fps=self.cfg.video.annotated_video_fps,
        )
        self.wechat_notifier = wechat_notifier
        self.alarm_user = alarm_user
        self.alarm_camera_name = alarm_camera_name

        self.alarm_clip_recorder = AlarmClipRecorder(
            output_dir=Path(self.cfg.video.output_dir) / "alarm_clips",
            fps=self.cfg.video.annotated_video_fps,
            clip_seconds=self.cfg.wechat.clip_seconds,
        )

        self.uniform_cache = UniformCache(ttl_seconds=0.1)
        self._camera_pool: ThreadPoolExecutor | None = None


    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self.is_running:
                return
            self._stop_event.clear()
            max_workers = max(1, len(self.cfg.camera_sources()))
            if self._camera_pool is None:
                self._camera_pool = ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix="cam-infer",
                )
            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="guard-room-runtime",
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._stop_event.set()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

        with self._lock:
            self._thread = None
            pool = self._camera_pool
            self._camera_pool = None

        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)

        self.state.mark_running(False)

    def _active_alarm_key(self, event_type: str, track_id: int | None) -> str:
        return f"{event_type}:{track_id if track_id is not None else 'global'}"

    def _refresh_alarm_latches(self, decisions: dict[str, object]) -> None:
        active_keys = set()

        if getattr(decisions["absent"], "active", False):
            active_keys.add(self._active_alarm_key("absent", None))
        if getattr(decisions["phone"], "active", False):
            active_keys.add(self._active_alarm_key(
                "phone_use",
                getattr(decisions["phone"], "track_id", None),
            ))
        if getattr(decisions["prone_sleep"], "active", False):
            active_keys.add(self._active_alarm_key(
                "prone_sleep",
                getattr(decisions["prone_sleep"], "track_id", None),
            ))

        # 只在行为真正结束(不再 active)时才清 latch
        # 这样同一轮行为期间,latch 一直锁着,不会重复打扰 alarm_manager
        for key in list(self._alarm_latches.keys()):
            if key not in active_keys:
                self._alarm_latches.pop(key, None)

    def _emit_alarm_once(
        self,
        alarm_manager: AlarmManager,
        event_type: str,
        frame,
        timestamp_s: float,
        frame_id: int,
        track_id: int | None,
        confidence: float,
        reason: str,
        cooldown_seconds: float = 60.0,
    ):
        key = self._active_alarm_key(event_type, track_id)
        if self._alarm_latches.get(key, False):
            return None

        event = alarm_manager.emit(
            event_type,
            frame,
            timestamp_s,
            frame_id,
            track_id,
            confidence,
            reason,
            camera_name=self.alarm_camera_name,
            cooldown_seconds=cooldown_seconds,
        )
        if event is not None:
            # 真实触发:更新 state、latch、banner
            self.state.add_alarm(event)
            self._alarm_latches[key] = True
            self._banner_alarm = event
            self._banner_expire_ts = timestamp_s + self._banner_show_seconds
        else:
            # 冷却期拦住:也要锁 latch,防止每帧都打扰 alarm_manager
            # 但不刷新 banner
            self._alarm_latches[key] = True
        return event

    def _run_loop(self) -> None:
        detector_by_camera: Dict[str, YOLO] = {}
        detector_phone = None
        pose_estimator_by_camera: Dict[str, PoseEstimator] = {}
        uniform_classifier = None
        out_writer = None
        readers: Dict[str, RTSPReader] = {}

        try:
            self.state.clear_error()
            self.state.set_config(self.cfg)
            self.state.mark_running(True)

            camera_sources = self.cfg.camera_sources()
            if len(camera_sources) < 2:
                raise RuntimeError("请至少配置两路摄像头，当前需要设置 video.source_cam1 和 video.source_cam2")

            detector_by_camera = {
                camera_id: YOLO(self.cfg.models.detector_model)
                for camera_id, _ in camera_sources
            }
            detector_phone = YOLO(self.cfg.models.detector_model)

            uniform_classifier = UniformClassifier(
                model_path=self.cfg.models.uniform_cls_model,
                device=self.cfg.models.device,
                imgsz=self.cfg.models.uniform_cls_imgsz,
                conf_thres=self.cfg.models.uniform_cls_conf,
            )

            pose_estimator_by_camera = {
                camera_id: PoseEstimator(self.cfg.models.pose_model_task)
                for camera_id, _ in camera_sources
            }

            behavior_by_camera = {
                camera_id: BehaviorEngine(self.cfg)
                for camera_id, _ in camera_sources
            }

            guard_gate_by_camera = {
                camera_id: TrackGuardGate(hold_seconds=self.cfg.rules.guard_hold_seconds)
                for camera_id, _ in camera_sources
            }

            consensus = MultiCameraConsensus(
                guard_hold_seconds=self.cfg.rules.guard_hold_seconds,
                absent_alarm_seconds=self.cfg.rules.absent_alarm_seconds,
                behavior_sync_seconds=self.cfg.rules.dual_sync_seconds,
            )

            alarm_manager = AlarmManager(self.cfg.video.output_dir)

            latest_buffers = {
                camera_id: LatestFrameBuffer()
                for camera_id, _ in camera_sources
            }

            for camera_id, source in camera_sources:
                reader = RTSPReader(
                    camera_name=camera_id,
                    source=source,
                    frame_width=self.cfg.room.frame_width,
                    frame_height=self.cfg.room.frame_height,
                    reconnect_seconds=self.cfg.video.reconnect_seconds,
                    camera_buffer_size=self.cfg.video.camera_buffer_size,
                    buffer=latest_buffers[camera_id],
                    stop_event=self._stop_event,
                )
                readers[camera_id] = reader
                reader.start()

            first_frames = {
                camera_id: self._wait_first_frame(latest_buffers[camera_id], readers[camera_id], timeout_s=12.0)
                for camera_id, _ in camera_sources
            }

            combined_first = self._stack_frames([first_frames[camera_id] for camera_id, _ in camera_sources])
            out_writer = self._build_writer(combined_first.shape[1], combined_first.shape[0])

            frame_id = 0
            infer_fps_ema = 0.0
            last_infer_ts = time.time()
            started_wall_ts = time.time()

            processed_ids = {camera_id: -1 for camera_id, _ in camera_sources}

            false_decisions = {
                "absent": RuleDecision(),
                "phone": RuleDecision(),
                "prone_sleep": RuleDecision(),
            }

            last_results = {
                camera_id: SingleCameraResult(
                    camera_id=camera_id,
                    annotated_frame=first_frames[camera_id].copy(),
                    all_persons=[],
                    guard_persons=[],
                    phones=[],
                    pose_features={},
                    local_decisions=false_decisions,
                    guard_present=False,
                    guard_confidence=0.0,
                    camera_online=True,
                )
                for camera_id, _ in camera_sources
            }
            last_global_decisions = false_decisions

            while not self._stop_event.is_set():
                buffer_items = {
                    camera_id: latest_buffers[camera_id].get()
                    for camera_id, _ in camera_sources
                }
                current_frames = {
                    camera_id: item[2]
                    for camera_id, item in buffer_items.items()
                }

                if any(frame is None for frame in current_frames.values()):
                    time.sleep(0.02)
                    continue

                if all(buffer_items[camera_id][0] == processed_ids[camera_id] for camera_id, _ in camera_sources):
                    time.sleep(0.01)
                    continue

                for camera_id, _ in camera_sources:
                    processed_ids[camera_id] = buffer_items[camera_id][0]
                frame_id += 1

                timestamp_s = time.time() - started_wall_ts

                need_infer = (
                    self.cfg.video.process_every_n_frames <= 1
                    or frame_id % self.cfg.video.process_every_n_frames == 0
                )

                if need_infer:
                    fps_by_camera = {
                        camera_id: max(1.0, float(readers[camera_id].meta.get("fps", 12.0)))
                        for camera_id, _ in camera_sources
                    }

                    phone_mode = str(
                        getattr(self.cfg.runtime, "phone_detect_mode", "guard_crop") or "guard_crop"
                    ).strip().lower()
                    precomputed_phone_map: dict[str, List[Detection]] | None = None

                    if phone_mode == "full_frame_test":
                        precomputed_phone_map = self._detect_phones_full_frames_batch(
                            detector=detector_phone,
                            frames_by_camera={camera_id: current_frames[camera_id] for camera_id, _ in camera_sources},
                        )

                    if self._camera_pool is None:
                        raise RuntimeError("camera pool 未初始化")

                    futures = {
                        camera_id: self._camera_pool.submit(
                            self._process_one_camera,
                            camera_id=camera_id,
                            frame=current_frames[camera_id],
                            timestamp_s=timestamp_s,
                            fps=max(
                                fps_by_camera[camera_id] / max(1, self.cfg.video.process_every_n_frames),
                                1.0,
                            ),
                            main_detector=detector_by_camera[camera_id],
                            phone_detector=detector_phone,
                            pose_estimator=pose_estimator_by_camera[camera_id],
                            behavior_engine=behavior_by_camera[camera_id],
                            guard_gate=guard_gate_by_camera[camera_id],
                            uniform_classifier=uniform_classifier,
                            camera_online=(readers[camera_id].error is None),
                            precomputed_phones=None if precomputed_phone_map is None else precomputed_phone_map.get(camera_id),
                        )
                        for camera_id, _ in camera_sources
                    }

                    last_results = {
                        camera_id: future.result()
                        for camera_id, future in futures.items()
                    }

                    last_global_decisions = consensus.update(
                        timestamp_s=timestamp_s,
                        cameras={
                            camera_id: CameraDecisionBundle(
                                camera_id=camera_id,
                                camera_online=result.camera_online,
                                guard_present=result.guard_present,
                                phone=result.local_decisions["phone"],
                                prone_sleep=result.local_decisions["prone_sleep"],
                            )
                            for camera_id, result in last_results.items()
                        },
                    )
                    self._refresh_alarm_latches(last_global_decisions)

                ordered_frames = [last_results[camera_id].annotated_frame for camera_id, _ in camera_sources]
                combined = self._stack_frames(ordered_frames)

                self._draw_global_panel(
                    combined,
                    last_global_decisions,
                    timestamp_s,
                )

                new_alarm_events = []

                # 离岗
                if last_global_decisions["absent"].active:
                    event = self._emit_alarm_once(
                        alarm_manager=alarm_manager,
                        event_type="absent",
                        frame=combined,
                        timestamp_s=timestamp_s,
                        frame_id=frame_id,
                        track_id=None,
                        confidence=last_global_decisions["absent"].confidence,
                        reason=last_global_decisions["absent"].reason,
                        cooldown_seconds=self.cfg.rules.alarm_cooldown_absent,
                    )
                    if event is not None:
                        new_alarm_events.append(event)

                # 手机
                if last_global_decisions["phone"].active:
                    event = self._emit_alarm_once(
                        alarm_manager=alarm_manager,
                        event_type="phone_use",
                        frame=combined,
                        timestamp_s=timestamp_s,
                        frame_id=frame_id,
                        track_id=None,
                        confidence=last_global_decisions["phone"].confidence,
                        reason=last_global_decisions["phone"].reason,
                        cooldown_seconds=self.cfg.rules.alarm_cooldown_phone,
                    )
                    if event is not None:
                        new_alarm_events.append(event)

                # 趴睡
                if last_global_decisions["prone_sleep"].active:
                    event = self._emit_alarm_once(
                        alarm_manager=alarm_manager,
                        event_type="prone_sleep",
                        frame=combined,
                        timestamp_s=timestamp_s,
                        frame_id=frame_id,
                        track_id=None,
                        confidence=last_global_decisions["prone_sleep"].confidence,
                        reason=last_global_decisions["prone_sleep"].reason,
                        cooldown_seconds=self.cfg.rules.alarm_cooldown_prone_sleep,
                    )
                    if event is not None:
                        new_alarm_events.append(event)

                visible_alarm = self._banner_alarm if timestamp_s <= self._banner_expire_ts else None
                draw_alarm_banner(combined, visible_alarm)

                for event in new_alarm_events:
                    self.alarm_clip_recorder.start_clip(
                        event=event,
                        frame=combined.copy(),
                        timestamp_s=timestamp_s,
                        camera_name=self.alarm_camera_name,
                        alarm_user=self.alarm_user,
                    )

                self.recorder.write(combined)
                if out_writer is not None:
                    out_writer.write(combined)

                finished_tasks = self.alarm_clip_recorder.update(combined, timestamp_s)
                for task in finished_tasks:
                    if hasattr(alarm_manager, "attach_video"):
                        alarm_manager.attach_video(task.event, task.video_path)

                    if hasattr(self.state, "attach_alarm_video"):
                        self.state.attach_alarm_video(
                            task.event.event_type,
                            task.event.frame_index,
                            task.video_path,
                        )

                    if self.wechat_notifier is not None:
                        event_type = task.event.event_type
                        wechat_cfg = self.cfg.wechat
                        
                        # 子开关检查
                        enabled = True
                        if event_type == "phone_use" and not wechat_cfg.enable_phone:
                            enabled = False
                        elif event_type == "absent" and not wechat_cfg.enable_absent:
                            enabled = False
                        elif event_type == "prone_sleep" and not wechat_cfg.enable_prone_sleep:
                            enabled = False
                        
                        if enabled:
                            # 抓一下当前 task 引用,闭包要用
                            _event_ref = task.event
                            
                            def _on_wechat_result(success: bool, _event=_event_ref):
                                if not success:
                                    print(f"[ALARM] {_event.event_type} 微信视频推送失败,本地报警视频已保留")
                                else:
                                    print(f"[ALARM] {_event.event_type} 视频推送成功")
                            
                            self.wechat_notifier.notify_alarm(
                                frame=task.snapshot_frame,
                                camera_name=task.camera_name,
                                event_name=task.event.event_type,
                                alarm_user=task.alarm_user,
                                video_path=task.video_path,
                                on_result=_on_wechat_result,
                            )

                now = time.time()
                instant_fps = 1.0 / max(1e-6, now - last_infer_ts)
                last_infer_ts = now
                infer_fps_ema = instant_fps if infer_fps_ema == 0 else (infer_fps_ema * 0.85 + instant_fps * 0.15)

                stacked_frames, y_offsets = self._stack_frames_with_offsets(
                    [last_results[camera_id].annotated_frame for camera_id, _ in camera_sources]
                )
                combined = stacked_frames
                merged_persons: List[Detection] = []
                merged_phones: List[Detection] = []
                merged_pose_features: Dict[int, Dict[str, float]] = {}

                for idx, (camera_id, _) in enumerate(camera_sources):
                    result = last_results[camera_id]
                    merged_persons.extend(self._offset_detections(result.all_persons, y_offset=y_offsets[idx]))
                    merged_phones.extend(self._offset_detections(result.phones, y_offset=y_offsets[idx]))
                    merged_pose_features.update(
                        self._merge_pose_features(result.pose_features, camera_index=idx)
                    )

                self.state.update_frame(
                    combined,
                    frame_count=frame_id,
                    fps=infer_fps_ema,
                    timestamp_s=timestamp_s,
                    persons=merged_persons,
                    phones=merged_phones,
                    pose_features=merged_pose_features,
                    decisions=last_global_decisions,
                    pose_enabled=any(estimator.enabled for estimator in pose_estimator_by_camera.values()),
                    jpeg_quality=self.cfg.video.jpeg_quality,
                )

                warn_msgs = [reader.error for reader in readers.values() if reader.error]
                if warn_msgs:
                    self.state.set_reader_warning(" | ".join(warn_msgs))
                else:
                    self.state.clear_reader_warning()

        except Exception as exc:
            self.state.set_error(str(exc))
        finally:
            self.state.mark_running(False)
            self._stop_event.set()
            self.recorder.stop()
            self.alarm_clip_recorder.close()

            if out_writer is not None:
                out_writer.release()

            for pose_estimator in pose_estimator_by_camera.values():
                pose_estimator.close()

            with self._lock:
                pool = self._camera_pool
                self._camera_pool = None
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)

    def _process_one_camera(
    self,
    *,
    camera_id: str,
    frame: np.ndarray,
    timestamp_s: float,
    fps: float,
    main_detector: YOLO,
    phone_detector: YOLO,
    pose_estimator: PoseEstimator,
    behavior_engine: BehaviorEngine,
    guard_gate: TrackGuardGate,
    uniform_classifier: UniformClassifier,
    camera_online: bool,
    precomputed_phones: Optional[List[Detection]] = None,
) -> SingleCameraResult:
        main_detections = self._detect_main(main_detector, frame)
        all_persons = [d for d in main_detections if d.cls_id == self.cfg.classes.person]
        
        guard_persons: List[Detection] = []
        guard_confidence = 0.0

        for person in all_persons:
            is_guard_now, uniform_conf = self.uniform_cache.get_or_infer(
                camera_id=camera_id,
                track_id=person.track_id,
                timestamp_s=timestamp_s,
                classifier=uniform_classifier,
                frame=frame,
                bbox=person.bbox,
            )

            if person.track_id is None:
                if is_guard_now:
                    guard_persons.append(person)
                    guard_confidence = max(guard_confidence, uniform_conf)
                continue

            keep_guard = guard_gate.keep(person.track_id, timestamp_s, is_guard_now)
            if keep_guard:
                guard_persons.append(person)
                guard_confidence = max(guard_confidence, uniform_conf)

        phone_mode = str(
            getattr(self.cfg.runtime, "phone_detect_mode", "guard_crop") or "guard_crop"
        ).strip().lower()

        if phone_mode == "full_frame_test":
            if precomputed_phones is not None:
                phones = precomputed_phones
            else:
                phones = self._detect_phones_full_frame(phone_detector, frame)
            persons_for_phone_rule = all_persons
        else:
            phones = self._detect_phones_in_person_regions(phone_detector, frame, guard_persons)
            persons_for_phone_rule = guard_persons

        pose_features = self._estimate_pose(pose_estimator, frame, guard_persons, timestamp_s)

        local_decisions = behavior_engine.update(
            timestamp_s=timestamp_s,
            fps=fps,
            frame_shape=frame.shape,
            persons=persons_for_phone_rule,
            phones=phones,
            pose_features=pose_features,
        )

        annotated = frame.copy()
        self._draw_camera(
            annotated,
            camera_id=camera_id,
            all_persons=all_persons,
            guard_persons=guard_persons,
            phones=phones,
            pose_features=pose_features,
            guard_confidence=guard_confidence,
            local_decisions=local_decisions,
            camera_online=camera_online,
        )

        return SingleCameraResult(
            camera_id=camera_id,
            annotated_frame=annotated,
            all_persons=all_persons,
            guard_persons=guard_persons,
            phones=phones,
            pose_features=pose_features,
            local_decisions=local_decisions,
            guard_present=len(guard_persons) > 0,
            guard_confidence=guard_confidence,
            camera_online=camera_online,
        )

    def _detect_main(self, detector: YOLO, frame: np.ndarray) -> List[Detection]:
        results = detector.track(
            source=frame,
            persist=True,
            tracker=self.cfg.models.tracker,
            classes=[self.cfg.classes.person],
            conf=max(0.20, self.cfg.models.detector_conf),
            iou=self.cfg.models.detector_iou,
            device=(self.cfg.models.device or None),
            verbose=False,
        )

        boxes = results[0].boxes
        detections: List[Detection] = []
        if boxes is None:
            return detections

        xyxy = boxes.xyxy.cpu().numpy() if boxes.xyxy is not None else []
        confs = boxes.conf.cpu().numpy() if boxes.conf is not None else []
        clss = boxes.cls.cpu().numpy().astype(int) if boxes.cls is not None else []
        ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else None

        for idx, bbox in enumerate(xyxy):
            track_id = int(ids[idx]) if ids is not None else None
            detections.append(
                Detection(
                    cls_id=int(clss[idx]),
                    conf=float(confs[idx]),
                    bbox=tuple(map(int, bbox.tolist())),
                    track_id=track_id,
                )
            )
        return detections

    def _detect_phones_in_person_regions(
        self,
        detector: YOLO,
        frame: np.ndarray,
        persons: List[Detection],
    ) -> List[Detection]:
        if not persons:
            return []

        h, w = frame.shape[:2]
        crops: List[np.ndarray] = []
        crop_meta: List[dict] = []

        for person in persons:
            px1, py1, px2, py2 = person.bbox
            person_w = max(1, px2 - px1)
            person_h = max(1, py2 - py1)

            pad_x = int(person_w * 0.35)
            pad_top = int(person_h * 0.20)
            pad_bottom = int(person_h * 0.15)

            x1 = max(0, px1 - pad_x)
            y1 = max(0, py1 - pad_top)
            x2 = min(w, px2 + pad_x)
            y2 = min(h, py2 + pad_bottom)

            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            crops.append(crop)
            crop_meta.append(
                {
                    "offset": (x1, y1),
                    "person_w": person_w,
                    "person_h": person_h,
                    "person_area": person_w * person_h,
                }
            )

        if not crops:
            return []

        results = detector.predict(
            source=crops,
            classes=[self.cfg.classes.play_phone],
            conf=min(0.9,max(0.10, self.cfg.models.detector_conf * 3.0)),
            iou=self.cfg.models.detector_iou,
            imgsz=640,
            device=(self.cfg.models.device or None),
            verbose=False,
        )

        detections: List[Detection] = []

        for result, meta in zip(results, crop_meta):
            boxes = result.boxes
            if boxes is None:
                continue

            xyxy = boxes.xyxy.cpu().numpy() if boxes.xyxy is not None else []
            confs = boxes.conf.cpu().numpy() if boxes.conf is not None else []

            ox, oy = meta["offset"]
            person_w = meta["person_w"]
            person_h = meta["person_h"]
            person_area = meta["person_area"]

            for idx, bbox in enumerate(xyxy):
                cx1, cy1, cx2, cy2 = map(int, bbox.tolist())
                bw = max(1, cx2 - cx1)
                bh = max(1, cy2 - cy1)
                area = bw * bh
                aspect = bw / max(1, bh)

                gx1, gy1, gx2, gy2 = cx1 + ox, cy1 + oy, cx2 + ox, cy2 + oy

                area_ratio = area / max(1, person_area)
                width_ratio = bw / max(1, person_w)
                height_ratio = bh / max(1, person_h)

                suspected_tablet = (
                    area_ratio > 0.12
                    or width_ratio > 0.38
                    or height_ratio > 0.30
                    or (area_ratio > 0.08 and 0.55 <= aspect <= 1.8)
                )
                if suspected_tablet:
                    continue

                detections.append(
                    Detection(
                        cls_id=self.cfg.classes.play_phone,
                        conf=float(confs[idx]),
                        bbox=(gx1, gy1, gx2, gy2),
                        track_id=None,
                    )
                )

        return self._dedup_overlaps(detections)

    def _detect_phones_full_frames_batch(
        self,
        detector: YOLO,
        frames_by_camera: Dict[str, np.ndarray],
    ) -> Dict[str, List[Detection]]:
        if not frames_by_camera:
            return {}

        camera_ids = list(frames_by_camera.keys())
        frames = [frames_by_camera[cid] for cid in camera_ids]

        results = detector.predict(
            source=frames,
            classes=[self.cfg.classes.play_phone],
            conf=max(0.05, self.cfg.models.detector_conf*1.8),
            iou=self.cfg.models.detector_iou,
            imgsz=1280,
            device=(self.cfg.models.device or None),
            verbose=False,
        )

        out: Dict[str, List[Detection]] = {}
        for cid, frame, result in zip(camera_ids, frames, results):
            detections: List[Detection] = []
            boxes = result.boxes
            if boxes is not None:
                xyxy = boxes.xyxy.cpu().numpy() if boxes.xyxy is not None else []
                confs = boxes.conf.cpu().numpy() if boxes.conf is not None else []

                h, w = frame.shape[:2]
                for idx, bbox in enumerate(xyxy):
                    x1, y1, x2, y2 = map(int, bbox.tolist())

                    x1 = max(0, min(x1, w - 1))
                    y1 = max(0, min(y1, h - 1))
                    x2 = max(0, min(x2, w - 1))
                    y2 = max(0, min(y2, h - 1))

                    if x2 <= x1 or y2 <= y1:
                        continue

                    detections.append(
                        Detection(
                            cls_id=self.cfg.classes.play_phone,
                            conf=float(confs[idx]),
                            bbox=(x1, y1, x2, y2),
                            track_id=None,
                        )
                    )

            out[cid] = self._dedup_overlaps(detections)

        return out

    def _detect_phones_full_frame(
        self,
        detector: YOLO,
        frame: np.ndarray,
    ) -> List[Detection]:
        result = self._detect_phones_full_frames_batch(
            detector=detector,
            frames_by_camera={"single": frame},
        )
        return result.get("single", [])

    def _estimate_pose(
        self,
        pose_estimator: PoseEstimator,
        frame: np.ndarray,
        persons: List[Detection],
        timestamp_s: float,
    ) -> Dict[int, Dict[str, float]]:
        if not pose_estimator.enabled:
            return {}
        
        # YOLO-Pose 对整帧做一次推理,内部匹配每个 person
        return pose_estimator.infer_frame(frame, persons)

    def _draw_camera(
        self,
        frame: np.ndarray,
        *,
        camera_id: str,
        all_persons: List[Detection],
        guard_persons: List[Detection],
        phones: List[Detection],
        pose_features: Dict[int, Dict[str, float]],
        guard_confidence: float,
        local_decisions: Dict[str, RuleDecision],
        camera_online: bool,
    ) -> None:
        for det in all_persons:
            draw_detection(frame, det, f"person id={det.track_id}", color=(128, 128, 128))

        for det in guard_persons:
            label = f"guard id={det.track_id}"
            if (
                det.track_id is not None
                and det.track_id in pose_features
                and "head_down_ratio" in pose_features[det.track_id]
            ):
                label += f" hd={pose_features[det.track_id]['head_down_ratio']:.2f}"
            draw_detection(frame, det, label, color=(0, 255, 0))

        for det in phones:
            draw_detection(frame, det, f"phone {det.conf:.2f}", color=(255, 0, 255))


        header_bg = (0, 120, 0) if camera_online else (0, 0, 180)
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 34), header_bg, -1)
        header = (
            f"{camera_id} | online={camera_online} | "
            f"guards={len(guard_persons)} | guard_conf={guard_confidence:.2f} | "
            f"phone={local_decisions['phone'].active} | prone={local_decisions['prone_sleep'].active}"
        )
        cv2.putText(frame, header, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)

    def _draw_global_panel(
        self,
        frame: np.ndarray,
        decisions: Dict[str, RuleDecision],
        timestamp_s: float,
    ) -> None:
        text = (
            f"GLOBAL | t={timestamp_s:.1f}s | "
            f"absent={decisions['absent'].active} | "
            f"phone={decisions['phone'].active} | "
            f"prone={decisions['prone_sleep'].active}"
        )
        y = frame.shape[0] - 14
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (0, 180, 255), 2)

    @staticmethod
    def _dedup_overlaps(dets: List[Detection], iou_threshold: float = 0.5) -> List[Detection]:
        if not dets:
            return []

        dets = sorted(dets, key=lambda d: d.conf, reverse=True)
        kept: List[Detection] = []

        for det in dets:
            keep = True
            for old in kept:
                if GuardRoomRuntime._iou(det.bbox, old.bbox) >= iou_threshold:
                    keep = False
                    break
            if keep:
                kept.append(det)
        return kept

    @staticmethod
    def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b

        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)

        if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
            return 0.0

        inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
        area_a = max(1, ax2 - ax1) * max(1, ay2 - ay1)
        area_b = max(1, bx2 - bx1) * max(1, by2 - by1)
        return inter / float(area_a + area_b - inter)

    @staticmethod
    def _resize_to_width(frame: np.ndarray, target_w: int) -> np.ndarray:
        h, w = frame.shape[:2]
        if w == target_w:
            return frame
        scale = target_w / max(1, w)
        new_h = max(1, int(round(h * scale)))
        return cv2.resize(frame, (target_w, new_h))

    def _stack_frames(self, frames: List[np.ndarray]) -> np.ndarray:
        combined, _ = self._stack_frames_with_offsets(frames)
        return combined

    @staticmethod
    def _offset_detections(dets: List[Detection], y_offset: int = 0) -> List[Detection]:
        out: List[Detection] = []
        for d in dets:
            x1, y1, x2, y2 = d.bbox
            out.append(
                Detection(
                    cls_id=d.cls_id,
                    conf=d.conf,
                    bbox=(x1, y1 + y_offset, x2, y2 + y_offset),
                    track_id=d.track_id,
                )
            )
        return out

    @staticmethod
    def _merge_pose_features(
        pose_features: Dict[int, Dict[str, float]],
        camera_index: int,
    ) -> Dict[int, Dict[str, float]]:
        base = camera_index * 100000
        return {
            int(track_id) + base: value
            for track_id, value in pose_features.items()
        }

    def _stack_frames_with_offsets(self, frames: List[np.ndarray]) -> tuple[np.ndarray, List[int]]:
        if not frames:
            raise RuntimeError("没有可拼接的画面")

        target_w = min(frame.shape[1] for frame in frames)
        resized_frames = [self._resize_to_width(frame, target_w) for frame in frames]

        y_offsets: List[int] = []
        current_y = 0
        for frame in resized_frames:
            y_offsets.append(current_y)
            current_y += frame.shape[0]

        return np.vstack(resized_frames), y_offsets

    def _wait_first_frame(self, buffer: LatestFrameBuffer, reader: RTSPReader, timeout_s: float = 12.0) -> np.ndarray:
        deadline = time.time() + timeout_s
        frame = None
        while not self._stop_event.is_set() and time.time() < deadline:
            _, _, frame = buffer.get()
            if frame is not None:
                return frame
            time.sleep(0.1)
        raise RuntimeError(reader.error or f"{reader.camera_name} 首帧超时: {reader.source}")

    def _build_writer(self, width: int, height: int):
        if not self.cfg.video.save_annotated_video:
            return None
        output_dir = ensure_dir(self.cfg.video.output_dir)
        out_path = output_dir / "annotated.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        return cv2.VideoWriter(
            str(out_path),
            fourcc,
            self.cfg.video.annotated_video_fps,
            (width, height),
        )
