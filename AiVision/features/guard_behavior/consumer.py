"""单摄感知流水线；仅发布局部快照，最终业务判断留给 Site 层。"""
from __future__ import annotations

import math
from collections import deque
from collections.abc import Generator
from dataclasses import dataclass
from time import monotonic, time
from weakref import ReferenceType, ref

import cv2
import numpy as np

from AiVision.core.logger import logger
from AiVision.features._shared.consumer import BaseFunctionConsumer, SubmittedInference
from AiVision.features._shared.roi import annotate_roi, roi_to_pixels
from AiVision.inference.contracts import INFERENCE_ERROR_INVALID_RESULT, build_inference_result
from .behavior import LocalBehaviorState
from .pose_features import bbox_iou, match_pose_features
from .schema import GuardBehaviorRuntimeCameraConfig
from .site_rules import stale_seconds
from .state import (
    CameraPerception, GuardCameraSnapshot, GuardTrackMemory, LocalRuleDecision,
    PhoneDetection, UNIFORM_EXPAND_RATIO, VehicleDetection, VehicleObservation,
)


PERSON_MODEL = "yolo_guard_person_phone"
UNIFORM_MODEL = "guard_uniform"
POSE_MODEL = "yolo_guard_pose"
VEHICLE_MODEL = "yolo_vehicle"
MAX_INFLIGHT_CAMERAS = 2

# 固定裁图与误检过滤参数属于内部算法，不进入 SitePolicy。
PHONE_CROP_HORIZONTAL_RATIO = .35
PHONE_CROP_TOP_RATIO = .20
PHONE_CROP_BOTTOM_RATIO = .15
PHONE_MAX_AREA_RATIO = .12
PHONE_MAX_WIDTH_RATIO = .38
PHONE_MAX_HEIGHT_RATIO = .30
PHONE_TABLET_MIN_AREA_RATIO = .08
PHONE_TABLET_ASPECT_RANGE = (.55, 1.8)
PHONE_DEDUPLICATION_IOU = .5


@dataclass
class _GuardSample:
    """同一摄像头的待处理原图与分阶段感知过程。"""

    frame: np.ndarray
    captured_at: float
    pipeline: Generator[SubmittedInference, dict, CameraPerception]
    request: SubmittedInference | None = None
    perception: CameraPerception | None = None


def _box(detection: dict) -> tuple[float, float, float, float]:
    """验证检测框为有限且具有正面积的原始坐标，拒绝损坏的模型结果。"""
    values = tuple(float(value) for value in detection["bbox"])
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError("检测框必须包含四个有限数值")
    if values[2] <= values[0] or values[3] <= values[1]:
        raise ValueError("检测框必须具有正面积")
    return values


def _confidence(detection: dict) -> float:
    """要求模型概率为零至一的有限数值，防止非法结果进入状态判断。"""
    value = float(detection["confidence"])
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("模型概率必须在 0~1 内")
    return value


def _crop(frame, bbox, *, horizontal, top, bottom):
    """按人体尺寸扩展裁图并裁到帧边界，返回图像及原帧偏移。"""
    x1, y1, x2, y2 = map(int, bbox)
    width, height = max(1, x2 - x1), max(1, y2 - y1)
    x1, y1 = max(0, x1 - int(width * horizontal)), max(0, y1 - int(height * top))
    x2, y2 = min(frame.shape[1], x2 + int(width * horizontal)), min(frame.shape[0], y2 + int(height * bottom))
    if x2 <= x1 or y2 <= y1:
        raise ValueError("人体裁图越界或为空")
    return frame[y1:y2, x1:x2], (x1, y1)


def _phone_detections(detections, person, offset) -> list[PhoneDetection]:
    """过滤非手机及相对人体过大的检测框，再还原为原帧坐标。"""
    width = max(1., person.bbox[2] - person.bbox[0])
    height = max(1., person.bbox[3] - person.bbox[1])
    phones = []
    for detection in detections:
        if detection["type"] != "phone":
            continue
        x1, y1, x2, y2 = _box(detection)
        bw, bh = x2 - x1, y2 - y1
        area_ratio, aspect = bw * bh / (width * height), bw / bh
        # 固定几何过滤，剔除相对人体过大的平板、书本类误检。
        if (area_ratio > PHONE_MAX_AREA_RATIO or bw / width > PHONE_MAX_WIDTH_RATIO
                or bh / height > PHONE_MAX_HEIGHT_RATIO
                or (area_ratio > PHONE_TABLET_MIN_AREA_RATIO
                    and PHONE_TABLET_ASPECT_RANGE[0] <= aspect <= PHONE_TABLET_ASPECT_RANGE[1])):
            continue
        ox, oy = offset
        phones.append(PhoneDetection((x1 + ox, y1 + oy, x2 + ox, y2 + oy), _confidence(detection)))
    return phones


def _deduplicate_phones(phones: list[PhoneDetection]) -> list[PhoneDetection]:
    """多个保安裁图可能覆盖同一手机，保留 IoU 不超过 0.5 的高分框。"""
    kept = []
    for phone in sorted(phones, key=lambda item: item.confidence, reverse=True):
        if all(bbox_iou(phone.bbox, previous.bbox) <= PHONE_DEDUPLICATION_IOU for previous in kept):
            kept.append(phone)
    return kept


class GuardBehaviorConsumer(BaseFunctionConsumer):
    """执行人体、制服、手机、姿态和车辆感知，向保安室层发布单摄证据。"""
    def __init__(self, *args, guard_config_provider, model_running_provider, snapshot_sink=None, **kwargs):
        """注入配置、模型状态与快照接收器，隔离各摄像头跨帧状态。"""
        super().__init__(*args, **kwargs)
        self.guard_config_provider = guard_config_provider
        self.model_running_provider = model_running_provider
        self.snapshot_sink = snapshot_sink
        self._runtime_configs: dict[int, GuardBehaviorRuntimeCameraConfig] = {}
        self._trackers = {}
        self._guard_memories: dict[int, GuardTrackMemory] = {}
        self._behaviors: dict[int, LocalBehaviorState] = {}
        self.latest_snapshots: dict[int, GuardCameraSnapshot] = {}
        self._sample_order: deque[int] = deque()
        self._pending_samples: dict[int, _GuardSample] = {}
        self._last_samples: dict[int, tuple[float, ReferenceType[np.ndarray]]] = {}

    def _install_config(self, camera_id: int, config) -> None:
        """先清除旧状态，再校验并安装启用的运行配置，避免配置变更继承旧证据。"""
        old = self.config_cache.pop(camera_id, {})
        if old:
            self._sample_order.remove(camera_id)
        self._clear_camera_state(camera_id, old.get("shm_name"))
        self._runtime_configs.pop(camera_id, None)
        if config is None:
            return
        config = GuardBehaviorRuntimeCameraConfig.model_validate(config)
        if config.camera_id != camera_id:
            raise ValueError("运行配置的 Camera 身份不一致")
        if config.site_enabled and config.member_enabled and config.feature_enabled:
            self._runtime_configs[camera_id] = config
            # 公共预览只读取启用标记与车辆区域，SitePolicy 仍由专用配置管理。
            self.config_cache[camera_id] = {
                "shm_name": config.shm_name, "enable": True,
                "roi_pos": [list(point) for point in config.vehicle_roi_pos],
            }
            self._sample_order.append(camera_id)

    def _load_initial_configs(self):
        """从专用配置服务取得快照，在摄像头锁内整体替换本地配置。"""
        configs = self.guard_config_provider.list_runtime_camera_configs()
        with self._camera_state_lock:
            for camera_id in list(self.config_cache):
                self._install_config(camera_id, None)
            for config in configs:
                self._install_config(config.camera_id, config)

    def reload_camera_config(self, camera_id: int) -> None:
        """重新读取指定摄像头的保安室配置并重建其状态。"""
        with self._camera_state_lock:
            self._install_config(camera_id, self.guard_config_provider.get_runtime_camera_config(camera_id))

    def update_config(self, camera_id: int):
        """将公共配置更新入口转交保安室专用加载流程。"""
        self.reload_camera_config(camera_id)

    def update_status(self, camera_id: int, enabled: bool):
        """启用时加载专用配置，禁用时移除摄像头状态。"""
        if enabled:
            self.reload_camera_config(camera_id)
        else:
            self.remove_camera(camera_id)

    def remove_camera(self, camera_id: int, shm_name: str | None = None):
        """移除配置、感知记忆及共享标识下的预览结果。"""
        with self._camera_state_lock:
            self._install_config(camera_id, None)
            if shm_name:
                self.result_dict.pop(shm_name, None)
                self.result_updated_at.pop(shm_name, None)

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        """清除跟踪、制服、行为与快照缓存，使重新加入的摄像头从零开始。"""
        super()._clear_camera_state(camera_id, shm_name)
        self._discard_sample(camera_id)
        self._last_samples.pop(camera_id, None)
        self.latest_snapshots.pop(camera_id, None)

    def _discard_sample(self, camera_id: int) -> None:
        sample = self._pending_samples.pop(camera_id, None)
        if sample is not None:
            if sample.request is not None:
                self.cancel_inference(sample.request)
            sample.pipeline.close()
        # 中止时感知可能已经推进一部分，清除这些状态以免和下一帧拼成连续证据。
        self._trackers.pop(camera_id, None)
        self._guard_memories.pop(camera_id, None)
        self._behaviors.pop(camera_id, None)

    def stop(self):
        """先停止消费，再在状态锁内清空全部运行配置与时序证据。"""
        super().stop()
        with self._camera_state_lock:
            for camera_id in list(self.config_cache):
                self._install_config(camera_id, None)

    def _processing_frame(self, camera_id, camera_key):
        """预览和取证使用当前结果对应的原图，即使采集线程已写入新帧。"""
        sample = self._pending_samples.get(camera_id)
        return (sample.frame, sample.captured_at) if sample is not None else (None, 0.0)

    def _get_roi(self, camera_id, frame):
        """保留原帧，车辆区域由车辆解析阶段单独应用。"""
        return frame

    @staticmethod
    def _is_fresh(config: GuardBehaviorRuntimeCameraConfig, captured_at: float) -> bool:
        return 0 <= time() - captured_at <= stale_seconds(config)

    def _before_camera_round(self):
        """轮转摄像头，每路等待一项推理时可继续推进其他摄像头。"""
        with self._camera_state_lock:
            for camera_id, sample in list(self._pending_samples.items()):
                config = self._runtime_configs[camera_id]
                current_frame = self.latest_frames.get(config.shm_name)
                if (not self.is_camera_active(config.shm_name) or current_frame is None
                        or current_frame.shape != sample.frame.shape or not self._is_fresh(config, sample.captured_at)):
                    self._discard_sample(camera_id)
                elif sample.request is not None and sample.request.ready(monotonic()):
                    self._advance_sample(camera_id, sample)

            for _ in range(len(self._sample_order)):
                if not self.running or len(self._pending_samples) >= MAX_INFLIGHT_CAMERAS:
                    break
                camera_id = self._sample_order[0]
                self._sample_order.rotate(-1)
                if camera_id in self._pending_samples:
                    continue
                config = self._runtime_configs[camera_id]
                key = config.shm_name
                frame, captured_at = super()._processing_frame(camera_id, key)
                observed_at = monotonic()
                if frame is None or not self.is_camera_active(key) or not self._is_fresh(config, captured_at):
                    continue
                previous = self._last_samples.get(camera_id)
                if previous is not None:
                    previous_at, previous_frame = previous
                    if frame is previous_frame() or observed_at - previous_at < config.policy.cap_interval:
                        continue
                sample = _GuardSample(frame, captured_at, self._perceive(frame, camera_id, observed_at))
                self._pending_samples[camera_id] = sample
                self._last_samples[camera_id] = observed_at, ref(frame)
                self._advance_sample(camera_id, sample)

    def _advance_sample(self, camera_id: int, sample: _GuardSample) -> None:
        try:
            if sample.request is None:
                sample.request = next(sample.pipeline)
            else:
                response = self.resolve_inference(sample.request)
                sample.request = None
                sample.request = sample.pipeline.send(response)
        except StopIteration as finished:
            sample.request = None
            sample.perception = finished.value
        except Exception:
            self._discard_sample(camera_id)
            raise

    def _processing_interval_seconds(self, camera_id, cfg):
        """采样时已限频，已完成的结果直接发布。"""
        return 0.0

    def _frame_changed(self, camera_id, roi, threshold=0.005):
        """静止画面也用于检测在岗，已就绪的采样无需再计算帧差。"""
        return True

    def _should_process_now(self, camera_id, cfg):
        sample = self._pending_samples.get(camera_id)
        if sample is None or sample.perception is None:
            return False
        config = self._runtime_configs[camera_id]
        current_frame = self.latest_frames.get(config.shm_name)
        if (current_frame is None or current_frame.shape != sample.frame.shape
                or not self._is_fresh(config, sample.captured_at)):
            self._discard_sample(camera_id)
            return False
        return True

    def _handle_alarm(self, camera_id, result, frame):
        """单摄只发布 Snapshot，由 SiteRuntime 统一决定业务告警。"""
        return None

    def _infer(self, camera_id, model, frame, meta, states, parse):
        """检查模型运行状态、执行推理并校验结果，按模型记录不可用或错误状态。"""
        if not self.model_running_provider(model):
            states[model] = "unavailable"
            return None
        result = yield self.submit_inference(camera_id, model, frame, task_meta=meta)
        if result["status"] != "ok":
            states[model] = "unavailable" if result["status"] == "unavailable" else "error"
            return None
        try:
            parsed = parse(result["detections"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            states[model] = "error"
            logger.warning(f"[guard_behavior] 模型结果无效 camera_id={camera_id} model={model}: {exc}")
            failure = build_inference_result(result, status="error", error_code=INFERENCE_ERROR_INVALID_RESULT,
                                             error_message=str(exc))
            self._record_inference_outcomes(camera_id=camera_id, model_name=model, outcomes=[failure])
            return None
        if states[model] not in ("error", "unavailable"):
            states[model] = "ready"
        return parsed

    @staticmethod
    def _uniform_probability(detections):
        """要求制服模型返回唯一制服正类概率，拒绝格式含糊的分类结果。"""
        if len(detections) != 1 or detections[0]["type"] != "uniform":
            raise ValueError("制服模型必须返回唯一正类概率")
        return _confidence(detections[0])

    def _persons(self, detections, camera_id, frame, config):
        """筛选并校验人体框，交由摄像头独立的 ByteTrack 分配轨迹。"""
        from .tracking import CameraByteTracker

        persons = [{"bbox": _box(item), "confidence": _confidence(item)}
                   for item in detections if item["type"] == "person"]
        if camera_id not in self._trackers:
            self._trackers[camera_id] = CameraByteTracker(config.fps)
        return self._trackers[camera_id].update(persons, frame.shape)

    def _vehicles(self, camera_id, frame, config, states):
        """仅在指定的车辆检查摄像头执行车辆模型，保留不可用与无人车的区别。"""
        policy = config.policy
        if not policy.vehicle_inspection_enabled or policy.vehicle_camera_id != camera_id:
            return VehicleObservation(False)

        def parse(detections):
            """以车辆框底边中心是否位于 ROI 内筛选车辆，保留原始类别。"""
            polygon = roi_to_pixels([list(point) for point in config.vehicle_roi_pos], frame.shape)
            vehicles = []
            for item in detections:
                if item["type"] != "vehicle":
                    continue
                bbox = _box(item)
                # 车辆触地点按框底边中心判定，不能用框中心替代。
                point = ((bbox[0] + bbox[2]) / 2, bbox[3])
                if not config.vehicle_roi_pos or cv2.pointPolygonTest(polygon, point, False) >= 0:
                    vehicles.append(VehicleDetection(bbox, _confidence(item), int(item["class_id"])))
            return tuple(vehicles)

        vehicles = yield from self._infer(camera_id, VEHICLE_MODEL, frame, {
            "conf": policy.vehicle_confidence_threshold, "iou": policy.model_iou_threshold,
            "imgsz": policy.vehicle_imgsz,
        }, states, parse)
        return VehicleObservation(vehicles is not None, vehicles or (),
                                  None if vehicles is not None else "车辆模型不可用或推理失败")

    def _process(self, roi, camera_id):
        return False, self._pending_samples.pop(camera_id).perception

    def _perceive(self, roi, camera_id, now):
        """生成单帧人体身份与局部行为事实，失败环节显式保留未知状态。

        先检测人体并跟踪，再用制服概率确认保安；手机仅采信保安裁图结果，
        姿态用于局部行为规则。存在保安与人数完全已知分别判断，避免未知身份
        被当作不存在。最终告警由保安室运行层统一决定。
        """
        config = self._runtime_configs[camera_id]
        policy = config.policy
        states = {model: "not_applicable" for model in self.spec.model_names}
        memory = self._guard_memories.setdefault(camera_id, GuardTrackMemory())
        behavior = self._behaviors.setdefault(camera_id, LocalBehaviorState())
        persons = yield from self._infer(camera_id, PERSON_MODEL, roi, {
            "conf": policy.person_confidence_threshold, "iou": policy.model_iou_threshold,
            "imgsz": policy.person_phone_imgsz,
        }, states, lambda items: self._persons(items, camera_id, roi, config))
        vehicle = yield from self._vehicles(camera_id, roi, config, states)
        if persons is None:
            # 失败结果不是空场景；清除时序证据，避免恢复后跨越未知时段累计。
            memory.observe([], now, policy.state_ttl_seconds)
            behavior.mark_unknown(now, policy.state_ttl_seconds)
            unknown = LocalRuleDecision("unknown", "核心人体推理不可用")
            return CameraPerception((), (), (), None, None, None, unknown, unknown, vehicle, states)
        memory.observe(persons, now, policy.state_ttl_seconds)
        guards, probabilities, identity_unknown = [], [], False
        for person in persons:
            # 只复用短期制服概率，阈值和保持窗口始终在当前策略下重新判断。
            probability = memory.cached_probability(person.track_id, now)
            if probability is None:
                try:
                    crop, _ = _crop(roi, person.bbox, horizontal=UNIFORM_EXPAND_RATIO,
                                    top=UNIFORM_EXPAND_RATIO, bottom=UNIFORM_EXPAND_RATIO)
                except ValueError:
                    identity_unknown = True
                    states[UNIFORM_MODEL] = "error"
                    continue
                probability = yield from self._infer(camera_id, UNIFORM_MODEL, crop, {}, states, self._uniform_probability)
                if probability is None:
                    identity_unknown = True
                    continue
                memory.remember(person.track_id, probability, now)
            elif states[UNIFORM_MODEL] == "not_applicable":
                states[UNIFORM_MODEL] = "ready"
            if memory.keep(person.track_id, probability >= policy.uniform_confidence_threshold, now, policy.guard_hold_seconds):
                guards.append(person)
                probabilities.append(probability)
        phones, failed_phone_tracks = [], set()
        for person in guards:
            # 手机只采信保安裁图中的结果；主检测输出的全图手机不会进入规则。
            try:
                crop, offset = _crop(roi, person.bbox, horizontal=PHONE_CROP_HORIZONTAL_RATIO,
                                     top=PHONE_CROP_TOP_RATIO, bottom=PHONE_CROP_BOTTOM_RATIO)
            except ValueError:
                failed_phone_tracks.add(person.track_id)
                states[PERSON_MODEL] = "error"
                continue
            found = yield from self._infer(camera_id, PERSON_MODEL, crop, {
                "conf": policy.phone_confidence_threshold, "iou": policy.model_iou_threshold,
                "imgsz": policy.phone_crop_imgsz,
            }, states, lambda items: _phone_detections(items, person, offset))
            if found is None:
                failed_phone_tracks.add(person.track_id)
            else:
                phones.extend(found)
        phones = _deduplicate_phones(phones)
        pose_available = self.model_running_provider(POSE_MODEL)
        features = {}
        if not pose_available:
            states[POSE_MODEL] = "unavailable"
        elif guards:
            # 不传 conf，使用 Pose ModelSpec 的正式默认值。
            features = yield from self._infer(camera_id, POSE_MODEL, roi, {
                "iou": policy.model_iou_threshold, "imgsz": policy.pose_imgsz,
            }, states, lambda items: match_pose_features(guards, items))
            pose_available = features is not None
        phone, prone = behavior.update(
            now=now, fps=min(config.fps, 1. / policy.cap_interval), frame_height=roi.shape[0], guards=guards,
            phones=phones, phone_failed_tracks=failed_phone_tracks, pose_features=features or {},
            pose_available=pose_available, identity_unknown=identity_unknown, policy=policy,
        )
        present = True if guards else (None if identity_unknown else False)
        # 部分未知时可以确认存在保安，但不能声称已知精确人数。
        count = None if identity_unknown else len(guards)
        confidence = max(probabilities) if probabilities else (None if identity_unknown else 0.)
        return CameraPerception(tuple(persons), tuple(guards), tuple(phones), present, count, confidence,
                                phone, prone, vehicle, states)

    def _preview_background(self, frame, cfg):
        """车辆 ROI 沿用保安室配置，检测较慢时不保留上一张人物画面。"""
        return annotate_roi(frame, cfg["roi_pos"], self.ROI_COLOR) if cfg["roi_pos"] else frame

    def post_process(self, camera_id, result):
        """绘制局部结果，分别缓存图像与纯数据快照，再将两者交给保安室运行层。"""
        detail = result[1]
        config = self._runtime_configs[camera_id]
        annotated = self.frame_cache[camera_id].copy()
        for person in detail.persons:
            guard = person in detail.guards
            self._draw_box(annotated, person.bbox, (0, 220, 0) if guard else (160, 160, 160),
                           f'{"guard" if guard else "person"} #{person.track_id} {person.confidence:.2f}')
        for phone in detail.phones:
            self._draw_box(annotated, phone.bbox, (0, 120, 255), f"phone {phone.confidence:.2f}")
        for vehicle in detail.vehicle.detections:
            self._draw_box(annotated, vehicle.bbox, (220, 150, 0), f"vehicle:{vehicle.class_id} {vehicle.confidence:.2f}")
        if config.vehicle_roi_pos:
            polygon = roi_to_pixels([list(point) for point in config.vehicle_roi_pos], annotated.shape)
            polygon = np.clip(polygon, [0, 0], [annotated.shape[1] - 1, annotated.shape[0] - 1])
            cv2.polylines(annotated, [polygon], True, self.ROI_COLOR, 2)
        cv2.putText(annotated, f"guard={detail.guard_present} phone={detail.phone.state} prone={detail.prone.state}",
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
        updated_at = self._frame_sampled_at[camera_id]
        # 快照只有模型事实与局部状态；图像保存在预览字典并单独交给 sink。
        snapshot = GuardCameraSnapshot(
            camera_id, config.camera_name, config.site_id, config.site_name, updated_at,
            bool(self.is_camera_active(config.shm_name)), detail.guard_present, detail.guard_count,
            detail.guard_confidence, detail.phone, detail.prone, detail.vehicle, dict(detail.model_states),
            detail.guards, (annotated.shape[1], annotated.shape[0]),
        )
        self.latest_snapshots[camera_id] = snapshot
        self.result_dict[config.shm_name] = annotated
        self.result_updated_at[config.shm_name] = updated_at
        if self.snapshot_sink is not None:
            self.snapshot_sink(snapshot, annotated)
        return annotated

    @staticmethod
    def _draw_box(frame, bbox, color, label):
        """将检测框与简短标签绘制到传入的标注帧上。"""
        x1, y1, x2, y2 = map(int, bbox)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, .45, color, 1)
