"""单摄感知流水线；仅发布局部快照，最终业务判断留给 Site 层。"""
from __future__ import annotations

import math
from time import monotonic, time

import cv2
import numpy as np

from AiVision.core.logger import logger
from AiVision.features._shared.consumer import BaseFunctionConsumer
from AiVision.features._shared.roi import roi_to_pixels
from AiVision.inference.contracts import INFERENCE_ERROR_INVALID_RESULT, build_inference_result
from .behavior import LocalBehaviorState
from .pose_features import bbox_iou, match_pose_features
from .schema import GuardBehaviorRuntimeCameraConfig
from .state import (
    CameraPerception, GuardCameraSnapshot, GuardTrackMemory, LocalRuleDecision,
    PhoneDetection, UNIFORM_EXPAND_RATIO, VehicleDetection, VehicleObservation,
)


PERSON_MODEL = "yolo_guard_person_phone"
UNIFORM_MODEL = "guard_uniform"
POSE_MODEL = "yolo_guard_pose"
VEHICLE_MODEL = "yolo_vehicle"

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


def _box(detection: dict) -> tuple[float, float, float, float]:
    values = tuple(float(value) for value in detection["bbox"])
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError("检测框必须包含四个有限数值")
    if values[2] <= values[0] or values[3] <= values[1]:
        raise ValueError("检测框必须具有正面积")
    return values


def _confidence(detection: dict) -> float:
    value = float(detection["confidence"])
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("模型概率必须在 0~1 内")
    return value


def _crop(frame, bbox, *, horizontal, top, bottom):
    x1, y1, x2, y2 = map(int, bbox)
    width, height = max(1, x2 - x1), max(1, y2 - y1)
    x1, y1 = max(0, x1 - int(width * horizontal)), max(0, y1 - int(height * top))
    x2, y2 = min(frame.shape[1], x2 + int(width * horizontal)), min(frame.shape[0], y2 + int(height * bottom))
    if x2 <= x1 or y2 <= y1:
        raise ValueError("人体裁图越界或为空")
    return frame[y1:y2, x1:x2], (x1, y1)


def _phone_detections(detections, person, offset) -> list[PhoneDetection]:
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
    def __init__(self, *args, guard_config_provider, model_running_provider, snapshot_sink=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.guard_config_provider = guard_config_provider
        self.model_running_provider = model_running_provider
        self.snapshot_sink = snapshot_sink
        self._runtime_configs: dict[int, GuardBehaviorRuntimeCameraConfig] = {}
        self._trackers = {}
        self._guard_memories: dict[int, GuardTrackMemory] = {}
        self._behaviors: dict[int, LocalBehaviorState] = {}
        self.latest_snapshots: dict[int, GuardCameraSnapshot] = {}

    def _install_config(self, camera_id: int, config) -> None:
        old = self.config_cache.pop(camera_id, {})
        self._clear_camera_state(camera_id, old.get("shm_name"))
        self._runtime_configs.pop(camera_id, None)
        if config is None:
            return
        config = GuardBehaviorRuntimeCameraConfig.model_validate(config)
        if config.camera_id != camera_id:
            raise ValueError("运行配置的 Camera 身份不一致")
        if config.site_enabled and config.member_enabled and config.feature_enabled:
            self._runtime_configs[camera_id] = config
            # 主循环只需要帧身份；SitePolicy 不进入公共配置缓存结构。
            self.config_cache[camera_id] = {"shm_name": config.shm_name}

    def _load_initial_configs(self):
        configs = self.guard_config_provider.list_runtime_camera_configs()
        with self._camera_state_lock:
            for camera_id in list(self.config_cache):
                self._install_config(camera_id, None)
            for config in configs:
                self._install_config(config.camera_id, config)

    def reload_camera_config(self, camera_id: int) -> None:
        with self._camera_state_lock:
            self._install_config(camera_id, self.guard_config_provider.get_runtime_camera_config(camera_id))

    def update_config(self, camera_id: int):
        self.reload_camera_config(camera_id)

    def update_status(self, camera_id: int, enabled: bool):
        if enabled:
            self.reload_camera_config(camera_id)
        else:
            self.remove_camera(camera_id)

    def remove_camera(self, camera_id: int, shm_name: str | None = None):
        with self._camera_state_lock:
            self._install_config(camera_id, None)
            if shm_name:
                self.result_dict.pop(shm_name, None)
                self.result_updated_at.pop(shm_name, None)

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        super()._clear_camera_state(camera_id, shm_name)
        # 所有跨帧状态都随 Camera 解绑或禁用销毁，重新加入不能继承旧判断。
        self._trackers.pop(camera_id, None)
        self._guard_memories.pop(camera_id, None)
        self._behaviors.pop(camera_id, None)
        self.latest_snapshots.pop(camera_id, None)

    def stop(self):
        super().stop()
        with self._camera_state_lock:
            for camera_id in list(self.config_cache):
                self._install_config(camera_id, None)

    def _get_roi(self, camera_id, frame):
        return frame

    def _process_static_frames(self, camera_id, cfg):
        return True

    def _processing_interval_seconds(self, camera_id, cfg):
        return self._runtime_configs[camera_id].policy.cap_interval

    def _should_process_now(self, camera_id, cfg):
        return time() - self._last_process_at.get(camera_id, 0.) >= self._processing_interval_seconds(camera_id, cfg)

    def _handle_alarm(self, camera_id, result, frame):
        """单摄只发布 Snapshot，由 SiteRuntime 统一决定业务告警。"""
        return None

    def _infer(self, camera_id, model, frame, meta, states, parse):
        if not self.model_running_provider(model):
            states[model] = "unavailable"
            return None
        result = self.dispatch_inference_sync(camera_id, model, frame, task_meta=meta)
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
        if len(detections) != 1 or detections[0]["type"] != "uniform":
            raise ValueError("制服模型必须返回唯一正类概率")
        return _confidence(detections[0])

    def _persons(self, detections, camera_id, frame, config):
        from .tracking import CameraByteTracker

        persons = [{"bbox": _box(item), "confidence": _confidence(item)}
                   for item in detections if item["type"] == "person"]
        if camera_id not in self._trackers:
            self._trackers[camera_id] = CameraByteTracker(config.fps)
        return self._trackers[camera_id].update(persons, frame.shape)

    def _vehicles(self, camera_id, frame, config, states):
        policy = config.policy
        if not policy.vehicle_inspection_enabled or policy.vehicle_camera_id != camera_id:
            return VehicleObservation(False)

        def parse(detections):
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

        vehicles = self._infer(camera_id, VEHICLE_MODEL, frame, {
            "conf": policy.vehicle_confidence_threshold, "iou": policy.model_iou_threshold,
            "imgsz": policy.vehicle_imgsz,
        }, states, parse)
        return VehicleObservation(vehicles is not None, vehicles or (),
                                  None if vehicles is not None else "车辆模型不可用或推理失败")

    def _process(self, roi, camera_id):
        config = self._runtime_configs[camera_id]
        policy, now = config.policy, monotonic()
        self.frame_cache[camera_id] = roi
        states = {model: "not_applicable" for model in self.spec.model_names}
        memory = self._guard_memories.setdefault(camera_id, GuardTrackMemory())
        behavior = self._behaviors.setdefault(camera_id, LocalBehaviorState())
        persons = self._infer(camera_id, PERSON_MODEL, roi, {
            "conf": policy.person_confidence_threshold, "iou": policy.model_iou_threshold,
            "imgsz": policy.person_phone_imgsz,
        }, states, lambda items: self._persons(items, camera_id, roi, config))
        vehicle = self._vehicles(camera_id, roi, config, states)
        if persons is None:
            # 失败结果不是空场景；清除时序证据，避免恢复后跨越未知时段累计。
            memory.observe([], now, policy.state_ttl_seconds)
            behavior.mark_unknown(now, policy.state_ttl_seconds)
            unknown = LocalRuleDecision("unknown", "核心人体推理不可用")
            return False, CameraPerception((), (), (), None, None, None, unknown, unknown, vehicle, states)
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
                probability = self._infer(camera_id, UNIFORM_MODEL, crop, {}, states, self._uniform_probability)
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
            found = self._infer(camera_id, PERSON_MODEL, crop, {
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
            features = self._infer(camera_id, POSE_MODEL, roi, {
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
        return False, CameraPerception(tuple(persons), tuple(guards), tuple(phones), present, count, confidence,
                                       phone, prone, vehicle, states)

    def post_process(self, camera_id, result):
        detail = result[1]
        config = self._runtime_configs[camera_id]
        annotated = self.frame_cache[camera_id].copy()
        for person in detail.persons:
            guard = person in detail.guards
            self._draw_box(annotated, person.bbox, (0, 220, 0) if guard else (200, 160, 80),
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
        updated_at = time()
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
        x1, y1, x2, y2 = map(int, bbox)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, .45, color, 1)
