# 文件说明：实现`consensus` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

# consensus.py
"""
多摄像头行为共识模块。

将多路摄像头的判断结果汇聚后统一裁决，输出最终报警决策：

    absent     —— 所有在线摄像头均未见到保安，且持续超过阈值；
    phone      —— 任意一路摄像头检测到玩手机即报警（任一命中策略）；
    prone_sleep —— 任意一路摄像头检测到趴睡即报警（任一命中策略）。
    vehicle_unattended —— 任意一路摄像头检测到车辆离开前无人靠近即报警。

离岗裁决采用"持久化保安出现时间戳"策略：
    - 引入 guard_hold_seconds 宽限期，容忍保安短暂走出画面或被遮挡；
    - no_guard_started_at 以"各路摄像头最后一次见到保安的最大值"为起点，
      避免因摄像头先后切换导致计时器被过早触发。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .behavior import RuleDecision


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

# 功能：单路摄像头在某一帧的完整判断结果，作为共识层的输入单元；输入与输出详见下方说明
# 参数：
#   - `camera_id`（str）：摄像头唯一标识
#   - `camera_online`（bool）：`camera_online` 对应的业务输入值
#   - `guard_present`（bool）：`guard_present` 对应的业务输入值
#   - `phone`（RuleDecision）：`phone` 对应的业务输入值
#   - `prone_sleep`（RuleDecision）：`prone_sleep` 对应的业务输入值
#   - `vehicle_unattended`（RuleDecision）：`vehicle_unattended` 对应的业务输入值
# 返回：CameraDecisionBundle；返回新建的 `CameraDecisionBundle` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class CameraDecisionBundle:
    """单路摄像头在某一帧的完整判断结果，作为共识层的输入单元。

    Attributes:
        camera_id:      摄像头标识，与 AppConfig.video.source_cam* 的键对应。
        camera_online:  摄像头当前是否在线；离线时本 bundle 在共识计算中被忽略。
        guard_present:  本帧是否检测到保安（含制服识别结果）。
        phone:          手机使用规则的判断结果。
        prone_sleep:    趴睡规则的判断结果。
        vehicle_unattended: 车辆无人值守规则的判断结果。
    """
    camera_id: str
    camera_online: bool
    guard_present: bool
    phone: RuleDecision
    prone_sleep: RuleDecision
    vehicle_unattended: RuleDecision


# ---------------------------------------------------------------------------
# 共识引擎
# ---------------------------------------------------------------------------

# 功能：多路摄像头行为共识引擎；输入与输出详见下方说明
# 参数：
#   - `guard_hold_seconds`（float）：`guard_hold_seconds` 对应的时间间隔或时长；默认值为 `1.3`
#   - `absent_alarm_seconds`（float）：`absent_alarm_seconds` 对应的时间间隔或时长；默认值为 `60.0`
#   - `behavior_sync_seconds`（float）：`behavior_sync_seconds` 对应的时间间隔或时长；默认值为 `1.5`
# 返回：MultiCameraConsensus；返回新建的 `MultiCameraConsensus` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_run_loop` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class MultiCameraConsensus:
    """多路摄像头行为共识引擎。

    每帧调用 update()，传入各路摄像头的判断 bundle，返回统一的报警裁决结果。

    裁决策略：
        离岗  —— 所有在线摄像头均在宽限期外未见保安，且持续时长超过阈值（"全否"策略）；
        手机  —— 任一在线摄像头命中即报警，取最高置信度（"任一"策略）；
        趴睡  —— 同手机，任一命中即报警（"任一"策略）。

    """

    # 功能：guard_hold_seconds:    保安出现后的时间戳保持窗口（秒）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `guard_hold_seconds`（float）：`guard_hold_seconds` 对应的时间间隔或时长；默认值为 `1.3`
    #   - `absent_alarm_seconds`（float）：`absent_alarm_seconds` 对应的时间间隔或时长；默认值为 `60.0`
    #   - `behavior_sync_seconds`（float）：`behavior_sync_seconds` 对应的时间间隔或时长；默认值为 `1.5`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(
        self,
        guard_hold_seconds: float = 1.3,
        absent_alarm_seconds: float = 60.0,
        behavior_sync_seconds: float = 1.5,
    ):
        """
        Args:
            guard_hold_seconds:    保安出现后的时间戳保持窗口（秒）。
                                   窗口内视为"保安仍在场"，容忍短暂走出画面。
            absent_alarm_seconds:  所有摄像头均未见保安后，触发离岗报警的持续时长阈值（秒）。
            behavior_sync_seconds: 预留参数，用于未来多摄像头行为结论的时间对齐窗口（秒）。
        """
        self.guard_hold_seconds = guard_hold_seconds
        self.absent_alarm_seconds = absent_alarm_seconds
        self.behavior_sync_seconds = behavior_sync_seconds

        # 各摄像头最近一次出现相应事件的时间戳；未曾出现的键不存在（用 -1e9 作缺省）
        self.last_guard_seen_ts: Dict[str, float] = {}
        self.last_phone_seen_ts: Dict[str, float] = {}
        self.last_prone_seen_ts: Dict[str, float] = {}
        self.last_vehicle_seen_ts: Dict[str, float] = {}

        # 记录"全部摄像头均未见保安"状态的起始时间戳；None 表示当前有摄像头看到保安
        self.no_guard_started_at: float | None = None

    # 功能：执行一次多摄像头共识裁决；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `timestamp_s`（float）：以秒表示的流时间戳
    #   - `cameras`（Dict[str, CameraDecisionBundle]）：`cameras` 对应的业务输入值
    # 返回：Dict[str, RuleDecision]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`RuleDecision`、`cameras.items`、`online_cameras.items`、`self.last_guard_seen_ts.get`、`online_cameras.keys`、`any`、`recent_guard.values`、`max`、`'/'.join`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def update(
        self,
        timestamp_s: float,
        cameras: Dict[str, CameraDecisionBundle],
    ) -> Dict[str, RuleDecision]:
        """执行一次多摄像头共识裁决。

        Args:
            timestamp_s: 当前帧的流时间戳（秒），须单调递增。
            cameras:     摄像头 ID → CameraDecisionBundle 的字典，
                         包含本帧各路摄像头的判断结果（在线与否均需传入）。

        Returns:
            规则名 → RuleDecision 的字典，键固定为
            {"absent", "phone", "prone_sleep", "vehicle_unattended"}，未触发时 active=False。
        """
        results = {
            "absent": RuleDecision(),
            "phone": RuleDecision(),
            "prone_sleep": RuleDecision(),
            "vehicle_unattended": RuleDecision(),
        }

        # 过滤离线摄像头：离线摄像头不参与任何裁决，避免因断流误判为"无人"
        online_cameras = {k: v for k, v in cameras.items() if v.camera_online}

        if not online_cameras:
            # 所有摄像头均离线：无法做任何判断，重置离岗计时器防止断流后立即误报
            self.no_guard_started_at = None
            return results

        # ── 更新各事件的最近出现时间戳 ───────────────────────────────────
        # 仅在事件为正（active/guard_present）时更新，负样本不覆盖历史记录
        for cam_id, bundle in online_cameras.items():
            if bundle.guard_present:
                self.last_guard_seen_ts[cam_id] = timestamp_s
            if bundle.phone.active:
                self.last_phone_seen_ts[cam_id] = timestamp_s
            if bundle.prone_sleep.active:
                self.last_prone_seen_ts[cam_id] = timestamp_s
            if bundle.vehicle_unattended.active:
                self.last_vehicle_seen_ts[cam_id] = timestamp_s

        # ── 离岗裁决（"全否"策略 + 宽限期）─────────────────────────────
        # 对每路在线摄像头判断是否仍在宽限期内（最近见到保安 ≤ guard_hold_seconds 前）
        recent_guard = {
            cam_id: (timestamp_s - self.last_guard_seen_ts.get(cam_id, -1e9)) <= self.guard_hold_seconds
            for cam_id in online_cameras.keys()
        }
        any_guard_present_recently = any(recent_guard.values())

        if any_guard_present_recently:
            # 至少一路摄像头仍在宽限期内 → 保安在场，重置离岗计时器
            self.no_guard_started_at = None
        else:
            # 所有在线摄像头均已超出宽限期
            if self.no_guard_started_at is None:
                # 首次进入"全部未见"状态：以各摄像头最后一次见到保安的最大值为起点，
                # 而非当前时间戳，避免因摄像头切换导致计时器被重置后重新计时。
                seen_times = [
                    self.last_guard_seen_ts[cam_id]
                    for cam_id in online_cameras.keys()
                    if cam_id in self.last_guard_seen_ts
                ]
                if seen_times:
                    self.no_guard_started_at = max(seen_times)  # 以最晚见到保安的时刻为起点
                else:
                    self.no_guard_started_at = timestamp_s      # 从未见过保安，从本帧开始计时

            missing_for = timestamp_s - self.no_guard_started_at
            if missing_for >= self.absent_alarm_seconds:
                results["absent"] = RuleDecision(
                    active=True,
                    reason=f"连续 {missing_for:.0f}s 未见到保安",
                    confidence=0.90,    # 固定置信度：离岗是确定性判断，不依赖检测模型分数
                    track_id=None,      # 离岗无具体目标
                )

        # ── 手机裁决（"任一命中"策略）───────────────────────────────────
        active_phone_cams = [
            cam_id for cam_id, bundle in online_cameras.items()
            if bundle.phone.active
        ]
        if active_phone_cams:
            # 多路同时命中时取最高置信度，摄像头名称拼接便于追溯报警来源
            best_conf = max(
                online_cameras[cam_id].phone.confidence
                for cam_id in active_phone_cams
            )
            cam_label = "/".join(active_phone_cams)
            results["phone"] = RuleDecision(
                active=True,
                reason=f"{cam_label} 检测到玩手机",
                confidence=best_conf,
                track_id=None,
            )

        # ── 趴睡裁决（"任一命中"策略）───────────────────────────────────
        active_prone_cams = [
            cam_id for cam_id, bundle in online_cameras.items()
            if bundle.prone_sleep.active
        ]
        if active_prone_cams:
            best_conf = max(
                online_cameras[cam_id].prone_sleep.confidence
                for cam_id in active_prone_cams
            )
            cam_label = "/".join(active_prone_cams)
            results["prone_sleep"] = RuleDecision(
                active=True,
                reason=f"{cam_label} 检测到趴睡",
                confidence=best_conf,
                track_id=None,
            )

        # ── 车辆无人值守裁决（"任一命中"策略）─────────────────────────────
        active_vehicle_cams = [
            cam_id for cam_id, bundle in online_cameras.items()
            if bundle.vehicle_unattended.active
        ]
        if active_vehicle_cams:
            best_conf = max(
                online_cameras[cam_id].vehicle_unattended.confidence
                for cam_id in active_vehicle_cams
            )
            cam_label = "/".join(active_vehicle_cams)
            results["vehicle_unattended"] = RuleDecision(
                active=True,
                reason=f"{cam_label} 检测到车辆无人值守",
                confidence=best_conf,
                track_id=None,
            )

        return results
