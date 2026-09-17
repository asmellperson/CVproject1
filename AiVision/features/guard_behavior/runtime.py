"""Site 级聚合与调度；输入只有配置快照、单摄事实和标注帧。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from math import ceil, isfinite, sqrt
import threading
import time
from typing import Literal

import cv2
import numpy as np

from AiVision.alarms.dispatcher import AlarmEvidenceRequest, AlarmRequest
from AiVision.core.logger import logger
from .constants import (
    GUARD_ABSENT_VIOLATION_TYPE, GUARD_PHONE_USE_VIOLATION_TYPE,
    GUARD_PRONE_SLEEP_VIOLATION_TYPE, GUARD_VEHICLE_INSPECTION_MISSING_VIOLATION_TYPE,
)
from .schema import GuardBehaviorRuntimeSiteConfig
from .site_rules import AbsenceState, aggregate_positive, camera_availability, expected_members, stale_seconds
from .state import CameraAvailability, GuardCameraSnapshot, SiteEvaluation, SiteRuleDecision
from .vehicle_episode import VehicleEpisodeOutcome, VehicleEpisodeTracker


EVALUATION_INTERVAL_SECONDS = .1
STOP_TIMEOUT_SECONDS = 5.
TILE_WIDTH, TILE_HEIGHT = 640, 360
SiteRuleName = Literal["absence", "phone", "prone", "vehicle"]


@dataclass
class SiteRuntimeState:
    config: GuardBehaviorRuntimeSiteConfig
    absence: AbsenceState = field(default_factory=AbsenceState)
    vehicle: VehicleEpisodeTracker = field(default_factory=VehicleEpisodeTracker)
    episode_tokens: dict[str, str] = field(default_factory=dict)
    evaluation: SiteEvaluation | None = None
    last_error: str | None = None


class GuardBehaviorSiteRuntime:
    def __init__(self, *, service, dispatcher, evidence_recorder, clock=time.time, start_background=True):
        if dispatcher.evidence_recorder is not None and dispatcher.evidence_recorder is not evidence_recorder:
            raise ValueError("SiteRuntime 与 Dispatcher 必须使用同一个公共 Evidence 实例")
        self.service, self.dispatcher, self.evidence = service, dispatcher, evidence_recorder
        self._clock, self._start_background = clock, start_background
        self.sites: dict[int, SiteRuntimeState] = {}
        self.latest_snapshots: dict[int, GuardCameraSnapshot] = {}
        self._frames: dict[int, np.ndarray] = {}
        self._lock, self._lifecycle_lock = threading.RLock(), threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.running = False

    def start(self) -> None:
        with self._lifecycle_lock:
            # Orchestrator 先构造 Runtime，再配置 Dispatcher；启动前才要求依赖完整且一致。
            if self.evidence is None or self.dispatcher.evidence_recorder is not self.evidence:
                raise ValueError("SiteRuntime 启动前必须为 Dispatcher 配置同一个公共 Evidence 实例")
            if self.running:
                return
            configs = self.service.list_runtime_site_configs()
            camera_ids = [member.camera_id for config in configs for member in config.members]
            if len(camera_ids) != len(set(camera_ids)):
                raise ValueError("同一 Camera 不能属于多个 Guard Site")
            with self._lock:
                self.sites = {config.site_id: SiteRuntimeState(config) for config in configs}
                self._stop_event.clear()
                self.running = True
            if self._start_background:
                self._thread = threading.Thread(target=self._run, name="guard-site-runtime", daemon=True)
                try:
                    self._thread.start()
                except RuntimeError:
                    self.running = False
                    self._thread = None
                    raise

    def stop(self) -> None:
        with self._lifecycle_lock:
            self.running = False
            self._stop_event.set()
            if self._thread is not None:
                self._thread.join(STOP_TIMEOUT_SECONDS)
                if self._thread.is_alive():
                    raise RuntimeError("Guard SiteRuntime 停止超时")
                self._thread = None
            with self._lock:
                for site_id in tuple(self.sites):
                    self.remove_site(site_id)

    def reload_site(self, site_id: int) -> None:
        config = self.service.get_runtime_site_config(site_id)
        with self._lock:
            if config is not None:
                config = GuardBehaviorRuntimeSiteConfig.model_validate(config)
                if config.site_id != site_id:
                    raise ValueError("Site 运行配置身份不一致")
                occupied = {member.camera_id for key, state in self.sites.items() if key != site_id
                            for member in state.config.members}
                if occupied.intersection(member.camera_id for member in config.members):
                    raise ValueError("Camera 已属于其他 Guard Site")
            self.remove_site(site_id)
            if config is not None:
                self.sites[site_id] = SiteRuntimeState(config)

    def remove_site(self, site_id: int) -> None:
        with self._lock:
            state = self.sites.pop(site_id, None)
            if state is None:
                return
            self._cancel_episodes(state)
            for member in state.config.members:
                self.latest_snapshots.pop(member.camera_id, None)
                self._frames.pop(member.camera_id, None)
                self.evidence.clear_source(self._camera_source(member.camera_id))
            self.evidence.clear_source(self._site_source(site_id))

    def update_camera_snapshot(self, snapshot: GuardCameraSnapshot, annotated_frame: np.ndarray) -> bool:
        with self._lock:
            state = self.sites.get(snapshot.site_id)
            if not self.running or state is None:
                return False
            member = next((member for member in expected_members(state.config)
                           if member.camera_id == snapshot.camera_id), None)
            if member is None:
                return False
            if (not isinstance(annotated_frame, np.ndarray) or annotated_frame.ndim != 3
                    or annotated_frame.shape[2] != 3 or not annotated_frame.size
                    or snapshot.frame_size != (annotated_frame.shape[1], annotated_frame.shape[0])
                    or not isfinite(snapshot.updated_at)):
                raise ValueError("Snapshot 必须携带一致的原始尺寸和有效标注帧")
            previous = self.latest_snapshots.get(snapshot.camera_id)
            if previous is not None and snapshot.updated_at <= previous.updated_at:
                return False
            status = camera_availability(member, snapshot, self._clock(), stale_seconds(state.config))
            if status != CameraAvailability.READY:
                # 快照可能在下一次聚合前被覆盖，未知区间必须立即切断连续负证据。
                state.absence.clear()
            if snapshot.camera_id == state.config.policy.vehicle_camera_id:
                gap = previous is not None and snapshot.updated_at - previous.updated_at > stale_seconds(state.config)
                if (gap or status != CameraAvailability.READY or not snapshot.vehicle.available
                        or snapshot.guard_count is None):
                    state.vehicle.mark_unknown()
                    self._cancel_episodes(state)
            self.latest_snapshots[snapshot.camera_id] = replace(snapshot, model_states=dict(snapshot.model_states))
            self._frames[snapshot.camera_id] = annotated_frame.copy()
            self.evidence.record_frame(self._camera_source(snapshot.camera_id), annotated_frame, snapshot.updated_at)
            # 巡检线程统一评估同一时刻已收到的多摄快照；显式评估入口也供确定性调度使用。
            return True

    def evaluate_after_camera_update(self, site_id: int) -> SiteEvaluation | None:
        with self._lock:
            state = self.sites.get(site_id)
            if not self.running or state is None:
                return None
            now, config = self._clock(), state.config
            members = expected_members(config)
            if not config.enabled or not members:
                state.absence.clear()
                inactive = SiteRuleDecision("unavailable", "unknown", "Site 未启用或没有参与检测的 Camera")
                state.evaluation = SiteEvaluation(
                    "disabled" if not config.enabled else "unconfigured", {}, inactive, inactive, inactive,
                    SiteRuleDecision("unavailable", "idle", "Site 未参与检测"), now,
                )
                state.last_error = None
                return state.evaluation
            camera_states = {member.camera_id: camera_availability(
                member, self.latest_snapshots.get(member.camera_id), now, stale_seconds(config)) for member in members}
            absence = state.absence.evaluate(config, self.latest_snapshots, camera_states, now)
            phone = aggregate_positive("phone", self.latest_snapshots, camera_states)
            prone = aggregate_positive("prone", self.latest_snapshots, camera_states)
            vehicle, completed = self._evaluate_vehicle(state, camera_states, now)
            ready = sum(value == CameraAvailability.READY for value in camera_states.values())
            status = "healthy" if ready == len(members) else "degraded" if ready else "unavailable"
            state.evaluation = SiteEvaluation(status, camera_states, absence, phone, prone, vehicle, now)
            state.last_error = None
            try:
                self._dispatch_evaluation(state, completed, now)
            finally:
                # 已闭合事件不会再次进入状态机，其他通道失败时也必须释放剩余证据。
                for outcome in completed:
                    token = state.episode_tokens.pop(outcome.episode_id, None)
                    if token is not None:
                        self.evidence.cancel_episode(token)
            return state.evaluation

    def _dispatch_evaluation(self, state: SiteRuntimeState, completed: tuple[VehicleEpisodeOutcome, ...],
                             now: float) -> None:
        site_id, config, evaluation = state.config.site_id, state.config, state.evaluation
        source = self._site_source(site_id)
        if self.evidence.should_sample(source, now):
            self.evidence.record_frame(source, self.get_site_frame(site_id), now)
        for kind, rule, decision in ((GUARD_ABSENT_VIOLATION_TYPE, "absence", evaluation.absence),
                                     (GUARD_PHONE_USE_VIOLATION_TYPE, "phone", evaluation.phone),
                                     (GUARD_PRONE_SLEEP_VIOLATION_TYPE, "prone", evaluation.prone)):
            if decision.state == "alarm":
                self._dispatch(state, kind, rule, decision)
        for outcome in completed:
            token = state.episode_tokens.pop(outcome.episode_id, None)
            if outcome.should_alarm:
                decision = self._vehicle_alarm(config, outcome)
                self._dispatch(state, GUARD_VEHICLE_INSPECTION_MISSING_VIOLATION_TYPE,
                               "vehicle", decision, episode=outcome, token=token)
            elif token is not None:
                self.evidence.cancel_episode(token)

    def _evaluate_vehicle(self, state: SiteRuntimeState, camera_states: dict[int, CameraAvailability],
                          now: float) -> tuple[SiteRuleDecision, tuple[VehicleEpisodeOutcome, ...]]:
        config, policy = state.config, state.config.policy
        if not config.enabled or not policy.vehicle_inspection_enabled:
            return SiteRuleDecision("unavailable", "idle", "车辆检查未启用"), ()
        snapshot = self.latest_snapshots.get(policy.vehicle_camera_id)
        if (camera_states.get(policy.vehicle_camera_id) != CameraAvailability.READY
                or snapshot is None or not snapshot.vehicle.available or snapshot.guard_count is None):
            # 看见一个保安不代表制服身份已全部判明，负证据必须排除其他未知人员靠近的可能。
            state.vehicle.mark_unknown()
            self._cancel_episodes(state)
            return SiteRuleDecision("unavailable", "unknown", "车辆检查 Camera 缺少完整证据"), ()
        updates = state.vehicle.update(snapshot, now, policy)
        if not state.vehicle.uncertain:
            for episode_id in updates.started:
                token = self.evidence.begin_episode(self._camera_source(snapshot.camera_id),
                                                    self._frames[snapshot.camera_id], snapshot.updated_at)
                if token is not None:
                    state.episode_tokens[episode_id] = token
        alarms = [outcome for outcome in updates.completed if outcome.should_alarm]
        if alarms:
            return self._vehicle_alarm(config, max(alarms, key=lambda item: item.confidence)), updates.completed
        if state.vehicle.uncertain:
            return SiteRuleDecision("unavailable", "unknown", "事件经过未知区间，不能认定无人检查"), updates.completed
        return SiteRuleDecision("available", "monitoring" if state.vehicle.monitoring else "idle",
                                "车辆事件观察中" if state.vehicle.monitoring else "无车辆事件"), updates.completed

    @staticmethod
    def _vehicle_alarm(config: GuardBehaviorRuntimeSiteConfig, outcome: VehicleEpisodeOutcome) -> SiteRuleDecision:
        camera_id = config.policy.vehicle_camera_id
        return SiteRuleDecision("available", "alarm", "车辆离开前未观察到保安靠近",
                                camera_id, (camera_id,), outcome.confidence, outcome.ended_at - outcome.started_at)

    def _dispatch(self, state: SiteRuntimeState, violation_type: int, rule: SiteRuleName,
                  decision: SiteRuleDecision, *, episode: VehicleEpisodeOutcome | None = None,
                  token: str | None = None) -> None:
        config = state.config
        policy = next(policy for policy in config.alarm_policies if policy.violation_type == violation_type)
        if not (policy.sql_enable or policy.wechat_enable or policy.horn_enable):
            if token is not None:
                self.evidence.cancel_episode(token)
            return
        primary = next(member for member in config.members if member.camera_id == decision.primary_camera_id)
        frame = self.get_site_frame(config.site_id) if rule == "absence" else self._frames[primary.camera_id].copy()
        source = self._site_source(config.site_id) if rule == "absence" else self._camera_source(primary.camera_id)
        metadata = {
            "site_id": config.site_id, "primary_camera_id": primary.camera_id,
            "offending_cameras": [self._camera_evidence(camera_id, rule) for camera_id in decision.offending_camera_ids],
            "duration_seconds": decision.duration_seconds,
        }
        if episode is not None:
            metadata["episode"] = asdict(episode)
        try:
            request = AlarmRequest(
                feature_name="guard_behavior", department=config.department,
                camera_id=primary.camera_id, camera_name=primary.camera_name, camera_key=primary.shm_name,
                frame=frame, violation_type=violation_type,
                subject_type="guard_behavior_site", subject_id=str(config.site_id), subject_name=config.site_name,
                cooldown_subject_type="guard_behavior_site", cooldown_subject_id=str(config.site_id),
                reason=decision.reason, metadata=metadata,
                alarm_config={"sql": {"enable": policy.sql_enable},
                              "wechat": {"enable": policy.wechat_enable, "parm": {"user": policy.wechat_user}},
                              "horn": {"enable": policy.horn_enable, "parm": {
                                  "horn_id": policy.horn_id, "horn_event_id": policy.horn_event_id}}},
                evidence=AlarmEvidenceRequest(source, "episode" if episode is not None else "clip", token),
            )
            self.dispatcher.maybe_dispatch(request, alarm_interval=policy.alarm_interval)
        except Exception:
            if token is not None:
                self.evidence.cancel_episode(token)
            raise

    def _camera_evidence(self, camera_id: int, rule: SiteRuleName) -> dict:
        snapshot = self.latest_snapshots[camera_id]
        values = {"camera_id": camera_id, "camera_name": snapshot.camera_name,
                  "guard_present": snapshot.guard_present}
        if rule in ("phone", "prone"):
            values.update(asdict(getattr(snapshot, rule)))
        return values

    def get_site_frame(self, site_id: int) -> np.ndarray | None:
        with self._lock:
            state = self.sites.get(site_id)
            members = expected_members(state.config) if state is not None else ()
            if not members:
                return None
            columns = ceil(sqrt(len(members)))
            canvas = np.zeros((ceil(len(members) / columns) * TILE_HEIGHT, columns * TILE_WIDTH, 3), dtype=np.uint8)
            for index, member in enumerate(members):
                y, x = (index // columns) * TILE_HEIGHT, (index % columns) * TILE_WIDTH
                frame = self._frames.get(member.camera_id)
                if frame is not None:
                    scale = min(TILE_WIDTH / frame.shape[1], TILE_HEIGHT / frame.shape[0])
                    width, height = max(1, round(frame.shape[1] * scale)), max(1, round(frame.shape[0] * scale))
                    tile = cv2.resize(frame, (width, height))
                    left, top = x + (TILE_WIDTH - width) // 2, y + (TILE_HEIGHT - height) // 2
                    canvas[top:top + height, left:left + width] = tile
                status = camera_availability(member, self.latest_snapshots.get(member.camera_id),
                                             self._clock(), stale_seconds(state.config))
                cv2.putText(canvas, f"Camera {member.camera_id} {status.value}", (x + 8, y + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
            return canvas

    def get_site_status(self, site_id: int) -> SiteEvaluation | None:
        with self._lock:
            state = self.sites.get(site_id)
            evaluation = state.evaluation if state is not None else None
            return replace(evaluation, camera_states=dict(evaluation.camera_states)) if evaluation is not None else None

    def _cancel_episodes(self, state: SiteRuntimeState) -> None:
        for token in state.episode_tokens.values():
            self.evidence.cancel_episode(token)
        state.episode_tokens.clear()

    @staticmethod
    def _camera_source(camera_id: int) -> str:
        return f"guard_behavior/camera/{camera_id}"

    @staticmethod
    def _site_source(site_id: int) -> str:
        return f"guard_behavior/site/{site_id}"

    def _run(self) -> None:
        while not self._stop_event.wait(EVALUATION_INTERVAL_SECONDS):
            with self._lock:
                site_ids = tuple(self.sites)
            for site_id in site_ids:
                try:
                    self.evaluate_after_camera_update(site_id)
                except Exception as exc:
                    with self._lock:
                        state = self.sites.get(site_id)
                        if state is not None:
                            state.last_error = str(exc)
                    logger.exception(f"[GuardSite] Site {site_id} 评估失败")
