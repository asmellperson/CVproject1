# 文件说明：实现`vehicle_behavior` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""车辆无人值守报警规则。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .behavior import RuleDecision
from .config import AppConfig
from .types import Detection


# 功能：一次车辆出现在画面内的周期状态；输入与输出详见下方说明
# 参数：
#   - `active`（bool）：`active` 对应的业务输入值
#   - `started_at`（float）：`started_at` 对应的业务输入值
#   - `last_vehicle_seen_ts`（float）：`last_vehicle_seen_ts` 对应的业务输入值
#   - `missing_started_at`（float | None）：`missing_started_at` 对应的业务输入值
#   - `guard_seen_near_vehicle`（bool）：`guard_seen_near_vehicle` 对应的业务输入值
#   - `best_vehicle_conf`（float）：`best_vehicle_conf` 对应的业务输入值
#   - `primary_vehicle_track_id`（int | None）：`primary_vehicle_track_id` 对应业务对象的唯一标识
#   - `first_vehicle_center`（Tuple[float, float] | None）：`first_vehicle_center` 对应的业务输入值
#   - `last_vehicle_center`（Tuple[float, float] | None）：`last_vehicle_center` 对应的业务输入值
# 返回：VehicleEpisodeState；返回新建的 `VehicleEpisodeState` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::__init__`
#         实例化本符号；`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::update`
#         实例化本符号；`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_mark_vehicle_present` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class VehicleEpisodeState:
    """一次车辆出现在画面内的周期状态。"""

    active: bool = False
    started_at: float = 0.0
    last_vehicle_seen_ts: float = 0.0
    missing_started_at: float | None = None
    guard_seen_near_vehicle: bool = False
    best_vehicle_conf: float = 0.0
    primary_vehicle_track_id: int | None = None
    first_vehicle_center: Tuple[float, float] | None = None
    last_vehicle_center: Tuple[float, float] | None = None


# 功能：短时保存已由保安检查过的车辆，用于车辆检测断续后的状态继承；输入与输出详见下方说明
# 参数：
#   - `active`（bool）：`active` 对应的业务输入值
#   - `remembered_at`（float）：`remembered_at` 对应的业务输入值
#   - `last_vehicle_center`（Tuple[float, float] | None）：`last_vehicle_center` 对应的业务输入值
# 返回：RecentCheckedVehicleState；返回新建的 `RecentCheckedVehicleState` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::__init__`
#         实例化本符号；`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_remember_checked_vehicle`
#         实例化本符号；`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的
#         `VehicleBehaviorEngine::_matches_recent_checked_vehicle` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class RecentCheckedVehicleState:
    """短时保存已由保安检查过的车辆，用于车辆检测断续后的状态继承。"""

    active: bool = False
    remembered_at: float = 0.0
    last_vehicle_center: Tuple[float, float] | None = None


# 功能：车辆周期内未见保安靠近则报警；输入与输出详见下方说明
# 参数：
#   - `config`（AppConfig）：运行配置对象
# 返回：VehicleBehaviorEngine；返回新建的 `VehicleBehaviorEngine` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
#         `test_vehicle_behavior_does_not_alarm_when_guard_appears_before_vehicle_leaves`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
#         `test_vehicle_behavior_keeps_checked_state_after_short_vehicle_detection_drop`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
#         `test_vehicle_behavior_reassociates_checked_vehicle_that_reappears_along_exit_direction`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
#         `test_vehicle_behavior_does_not_reuse_checked_state_after_reassociate_window` 实例化本符号；另有 6 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class VehicleBehaviorEngine:
    """车辆周期内未见保安靠近则报警。

    语义：
      - 车辆出现时开始一个周期；
      - 周期内只要有保安出现在车辆附近，周期判定为合格；
      - 车辆连续消失超过 vehicle_occlusion_seconds 后结束周期；
      - 若周期结束时从未见保安靠近，则触发报警。
    """

    # 功能：初始化或配置 `__init__` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `config`（AppConfig）：运行配置对象
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`VehicleEpisodeState`、`RecentCheckedVehicleState`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, config: AppConfig):
        self.cfg = config
        self.episode = VehicleEpisodeState()
        self.recent_checked_vehicle = RecentCheckedVehicleState()

    # 功能：更新或保存 `update` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `timestamp_s`（float）：以秒表示的流时间戳
    #   - `frame_shape`（tuple[int, int, int]）：`frame_shape` 对应的业务输入值
    #   - `guards`（List[Detection]）：`guards` 对应的业务输入值
    #   - `vehicles`（List[Detection]）：`vehicles` 对应的业务输入值
    # 返回：RuleDecision；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._mark_vehicle_present`、`RuleDecision`、`max`、`min`、`self._matches_exit_direction`、`self._remember_checked_vehicle`、`VehicleEpisodeState`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def update(
        self,
        *,
        timestamp_s: float,
        frame_shape: tuple[int, int, int],
        guards: List[Detection],
        vehicles: List[Detection],
    ) -> RuleDecision:
        if vehicles:
            self._mark_vehicle_present(timestamp_s, frame_shape, guards, vehicles)
            return RuleDecision()

        if not self.episode.active:
            return RuleDecision()

        if self.episode.missing_started_at is None:
            self.episode.missing_started_at = timestamp_s
            return RuleDecision()

        missing_for = timestamp_s - self.episode.missing_started_at
        if missing_for < self.cfg.rules.vehicle_occlusion_seconds:
            return RuleDecision()

        duration_s = max(0.0, self.episode.last_vehicle_seen_ts - self.episode.started_at)
        guard_seen = self.episode.guard_seen_near_vehicle
        conf = max(0.72, min(0.95, self.episode.best_vehicle_conf or 0.72))
        exit_direction_matched = self._matches_exit_direction(frame_shape)
        if guard_seen:
            self._remember_checked_vehicle(timestamp_s)
        self.episode = VehicleEpisodeState()

        if guard_seen or not exit_direction_matched:
            return RuleDecision()

        return RuleDecision(
            active=True,
            reason=f"车辆停留期间未见保安靠近，车辆出现约 {duration_s:.1f}s",
            confidence=conf,
            track_id=None,
        )

    # 功能：实现 `_mark_vehicle_present` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `timestamp_s`（float）：以秒表示的流时间戳
    #   - `frame_shape`（tuple[int, int, int]）：`frame_shape` 对应的业务输入值
    #   - `guards`（List[Detection]）：`guards` 对应的业务输入值
    #   - `vehicles`（List[Detection]）：`vehicles` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::update` 调用本符号
    #   - 内部调用：`self._select_episode_vehicle`、`self._representative_vehicle`、`self._matches_recent_checked_vehicle`、`VehicleEpisodeState`、`self._is_unrelated_vehicle`、`max`、`any`、`self._guard_near_vehicle`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def _mark_vehicle_present(
        self,
        timestamp_s: float,
        frame_shape: tuple[int, int, int],
        guards: List[Detection],
        vehicles: List[Detection],
    ) -> None:
        vehicle = self._select_episode_vehicle(vehicles, frame_shape)
        if vehicle is None:
            vehicle = self._representative_vehicle(vehicles)

        if not self.episode.active or vehicle is None:
            inherited_guard_seen = self._matches_recent_checked_vehicle(vehicle, timestamp_s, frame_shape)
            self.episode = VehicleEpisodeState(
                active=True,
                started_at=timestamp_s,
                last_vehicle_seen_ts=timestamp_s,
                guard_seen_near_vehicle=inherited_guard_seen,
                primary_vehicle_track_id=vehicle.track_id if vehicle is not None else None,
                first_vehicle_center=vehicle.center if vehicle is not None else None,
            )
        elif self.episode.active and self._is_unrelated_vehicle(vehicle, frame_shape):
            self.episode = VehicleEpisodeState(
                active=True,
                started_at=timestamp_s,
                last_vehicle_seen_ts=timestamp_s,
                primary_vehicle_track_id=vehicle.track_id,
                first_vehicle_center=vehicle.center,
            )

        self.episode.last_vehicle_seen_ts = timestamp_s
        self.episode.missing_started_at = None
        self.episode.best_vehicle_conf = max(self.episode.best_vehicle_conf, vehicle.conf if vehicle is not None else 0.0)
        self.episode.primary_vehicle_track_id = vehicle.track_id if vehicle is not None else None
        self.episode.last_vehicle_center = vehicle.center if vehicle is not None else None

        if vehicle is not None and any(self._guard_near_vehicle(guard, vehicle) for guard in guards):
            self.episode.guard_seen_near_vehicle = True

    # 功能：实现 `_matches_exit_direction` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame_shape`（tuple[int, int, int]）：`frame_shape` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::update` 调用本符号
    #   - 内部调用：`str(getattr(self.cfg.rules, 'vehicle_exit_direction', 'any') or 'any').strip().lower`、`str(getattr(self.cfg.rules,
    #          'vehicle_exit_direction', 'any') or 'any').strip`、`str`、`getattr`、`float`、`max`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _matches_exit_direction(self, frame_shape: tuple[int, int, int]) -> bool:
        direction = str(getattr(self.cfg.rules, "vehicle_exit_direction", "any") or "any").strip().lower()
        if direction in {"", "any", "none", "off"}:
            return True

        first = self.episode.first_vehicle_center
        last = self.episode.last_vehicle_center
        if first is None or last is None:
            return False

        height, width = frame_shape[:2]
        min_ratio = float(getattr(self.cfg.rules, "vehicle_direction_min_delta_ratio", 0.03) or 0.03)
        dx = last[0] - first[0]
        dy = last[1] - first[1]
        min_x = max(1.0, width * min_ratio)
        min_y = max(1.0, height * min_ratio)

        if direction in {"right", "left_to_right", "east"}:
            return dx >= min_x
        if direction in {"left", "right_to_left", "west"}:
            return dx <= -min_x
        if direction in {"down", "top_to_bottom", "south"}:
            return dy >= min_y
        if direction in {"up", "bottom_to_top", "north"}:
            return dy <= -min_y

        return True

    # 功能：实现 `_remember_checked_vehicle` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `timestamp_s`（float）：以秒表示的流时间戳
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::update` 调用本符号
    #   - 内部调用：`RecentCheckedVehicleState`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def _remember_checked_vehicle(self, timestamp_s: float) -> None:
        self.recent_checked_vehicle = RecentCheckedVehicleState(
            active=True,
            remembered_at=timestamp_s,
            last_vehicle_center=self.episode.last_vehicle_center,
        )

    # 功能：实现 `_matches_recent_checked_vehicle` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `vehicle`（Detection | None）：`vehicle` 对应的业务输入值
    #   - `timestamp_s`（float）：以秒表示的流时间戳
    #   - `frame_shape`（tuple[int, int, int]）：`frame_shape` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_mark_vehicle_present` 调用本符号
    #   - 内部调用：`float`、`getattr`、`RecentCheckedVehicleState`、`self._center_distance`、`self._vehicle_association_max_distance`、`self._continues_exit_direction`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def _matches_recent_checked_vehicle(
        self,
        vehicle: Detection | None,
        timestamp_s: float,
        frame_shape: tuple[int, int, int],
    ) -> bool:
        if vehicle is None or not self.recent_checked_vehicle.active:
            return False

        max_age_s = float(getattr(self.cfg.rules, "vehicle_reassociate_seconds", 10.0) or 10.0)
        if timestamp_s - self.recent_checked_vehicle.remembered_at > max_age_s:
            self.recent_checked_vehicle = RecentCheckedVehicleState()
            return False

        previous = self.recent_checked_vehicle.last_vehicle_center
        if previous is None:
            return False

        if self._center_distance(previous, vehicle.center) <= self._vehicle_association_max_distance(frame_shape):
            return True

        return self._continues_exit_direction(previous, vehicle.center, frame_shape)

    # 功能：实现 `_continues_exit_direction` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `previous`（Tuple[float, float]）：`previous` 对应的业务输入值
    #   - `current`（Tuple[float, float]）：`current` 对应的业务输入值
    #   - `frame_shape`（tuple[int, int, int]）：`frame_shape` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_matches_recent_checked_vehicle`
    #         调用本符号
    #   - 内部调用：`str(getattr(self.cfg.rules, 'vehicle_exit_direction', 'any') or 'any').strip().lower`、`str(getattr(self.cfg.rules,
    #          'vehicle_exit_direction', 'any') or
    #          'any').strip`、`str`、`getattr`、`float`、`max`、`self._vehicle_association_max_distance`、`abs`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _continues_exit_direction(
        self,
        previous: Tuple[float, float],
        current: Tuple[float, float],
        frame_shape: tuple[int, int, int],
    ) -> bool:
        direction = str(getattr(self.cfg.rules, "vehicle_exit_direction", "any") or "any").strip().lower()
        if direction in {"", "any", "none", "off"}:
            return False

        height, width = frame_shape[:2]
        min_ratio = float(getattr(self.cfg.rules, "vehicle_direction_min_delta_ratio", 0.03) or 0.03)
        dx = current[0] - previous[0]
        dy = current[1] - previous[1]
        min_x = max(1.0, width * min_ratio)
        min_y = max(1.0, height * min_ratio)
        cross_axis_limit = self._vehicle_association_max_distance(frame_shape) * 0.5

        if direction in {"right", "left_to_right", "east"}:
            return dx >= min_x and abs(dy) <= cross_axis_limit
        if direction in {"left", "right_to_left", "west"}:
            return dx <= -min_x and abs(dy) <= cross_axis_limit
        if direction in {"down", "top_to_bottom", "south"}:
            return dy >= min_y and abs(dx) <= cross_axis_limit
        if direction in {"up", "bottom_to_top", "north"}:
            return dy <= -min_y and abs(dx) <= cross_axis_limit

        return False

    # 功能：实现 `_representative_vehicle` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `vehicles`（List[Detection]）：`vehicles` 对应的业务输入值
    # 返回：Detection | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_mark_vehicle_present`
    #         调用本符号；`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的
    #         `VehicleBehaviorEngine::_representative_vehicle_center`
    #         调用本符号；`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_select_episode_vehicle`
    #         调用本符号
    #   - 内部调用：`max`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _representative_vehicle(vehicles: List[Detection]) -> Detection | None:
        if not vehicles:
            return None
        return max(vehicles, key=lambda det: (det.bbox[2] - det.bbox[0]) * (det.bbox[3] - det.bbox[1]) * max(det.conf, 0.01))

    # 功能：实现 `_representative_vehicle_center` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `vehicles`（List[Detection]）：`vehicles` 对应的业务输入值
    # 返回：Tuple[float, float] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`VehicleBehaviorEngine._representative_vehicle`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _representative_vehicle_center(vehicles: List[Detection]) -> Tuple[float, float] | None:
        vehicle = VehicleBehaviorEngine._representative_vehicle(vehicles)
        return vehicle.center if vehicle is not None else None

    # 功能：实现 `_select_episode_vehicle` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `vehicles`（List[Detection]）：`vehicles` 对应的业务输入值
    #   - `frame_shape`（tuple[int, int, int]）：`frame_shape` 对应的业务输入值
    # 返回：Detection | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_mark_vehicle_present` 调用本符号
    #   - 内部调用：`self._representative_vehicle`、`self._vehicle_association_max_distance`、`min`、`self._center_distance`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _select_episode_vehicle(
        self,
        vehicles: List[Detection],
        frame_shape: tuple[int, int, int],
    ) -> Detection | None:
        if not vehicles:
            return None

        track_id = self.episode.primary_vehicle_track_id
        if track_id is not None:
            for vehicle in vehicles:
                if vehicle.track_id == track_id:
                    return vehicle

        previous = self.episode.last_vehicle_center
        if previous is None:
            return self._representative_vehicle(vehicles)

        max_distance = self._vehicle_association_max_distance(frame_shape)
        nearest = min(vehicles, key=lambda det: self._center_distance(previous, det.center))
        if self._center_distance(previous, nearest.center) <= max_distance:
            return nearest

        return self._representative_vehicle(vehicles)

    # 功能：检查或判断 `_is_unrelated_vehicle` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `vehicle`（Detection）：`vehicle` 对应的业务输入值
    #   - `frame_shape`（tuple[int, int, int]）：`frame_shape` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_mark_vehicle_present` 调用本符号
    #   - 内部调用：`self._center_distance`、`self._vehicle_association_max_distance`、`self._moved_against_exit_direction`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _is_unrelated_vehicle(self, vehicle: Detection, frame_shape: tuple[int, int, int]) -> bool:
        previous = self.episode.last_vehicle_center
        if previous is None:
            return False
        if self.episode.primary_vehicle_track_id is not None and vehicle.track_id == self.episode.primary_vehicle_track_id:
            return False
        if self._center_distance(previous, vehicle.center) <= self._vehicle_association_max_distance(frame_shape):
            return False
        return self._moved_against_exit_direction(frame_shape)

    # 功能：实现 `_moved_against_exit_direction` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame_shape`（tuple[int, int, int]）：`frame_shape` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_is_unrelated_vehicle` 调用本符号
    #   - 内部调用：`str(getattr(self.cfg.rules, 'vehicle_exit_direction', 'any') or 'any').strip().lower`、`str(getattr(self.cfg.rules,
    #          'vehicle_exit_direction', 'any') or 'any').strip`、`str`、`getattr`、`float`、`max`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _moved_against_exit_direction(self, frame_shape: tuple[int, int, int]) -> bool:
        direction = str(getattr(self.cfg.rules, "vehicle_exit_direction", "any") or "any").strip().lower()
        if direction in {"", "any", "none", "off"}:
            return False

        first = self.episode.first_vehicle_center
        last = self.episode.last_vehicle_center
        if first is None or last is None:
            return False

        height, width = frame_shape[:2]
        min_ratio = float(getattr(self.cfg.rules, "vehicle_direction_min_delta_ratio", 0.03) or 0.03)
        dx = last[0] - first[0]
        dy = last[1] - first[1]
        min_x = max(1.0, width * min_ratio)
        min_y = max(1.0, height * min_ratio)

        if direction in {"right", "left_to_right", "east"}:
            return dx <= -min_x
        if direction in {"left", "right_to_left", "west"}:
            return dx >= min_x
        if direction in {"down", "top_to_bottom", "south"}:
            return dy <= -min_y
        if direction in {"up", "bottom_to_top", "north"}:
            return dy >= min_y

        return False

    # 功能：实现 `_vehicle_association_max_distance` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `frame_shape`（tuple[int, int, int]）：`frame_shape` 对应的业务输入值
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_matches_recent_checked_vehicle`
    #         调用本符号；`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_continues_exit_direction`
    #         调用本符号；`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_select_episode_vehicle`
    #         调用本符号；`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_is_unrelated_vehicle`
    #         调用本符号
    #   - 内部调用：`max`、`min`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _vehicle_association_max_distance(frame_shape: tuple[int, int, int]) -> float:
        height, width = frame_shape[:2]
        return max(120.0, min(width, height) * 0.5)

    # 功能：实现 `_center_distance` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `a`（Tuple[float, float]）：`a` 对应的业务输入值
    #   - `b`（Tuple[float, float]）：`b` 对应的业务输入值
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_matches_recent_checked_vehicle`
    #         调用本符号；`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_select_episode_vehicle`
    #         调用本符号；`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_is_unrelated_vehicle`
    #         调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _center_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    # 功能：实现 `_guard_near_vehicle` 对应的`vehicle_behavior` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `guard`（Detection）：`guard` 对应的业务输入值
    #   - `vehicle`（Detection）：`vehicle` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/vehicle_behavior.py` 的 `VehicleBehaviorEngine::_mark_vehicle_present` 调用本符号
    #   - 内部调用：`float`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _guard_near_vehicle(self, guard: Detection, vehicle: Detection) -> bool:
        gx1, gy1, gx2, gy2 = guard.bbox
        foot = ((gx1 + gx2) / 2.0, gy2)
        vx1, vy1, vx2, vy2 = vehicle.bbox
        pad = float(self.cfg.rules.vehicle_near_px)
        expanded = (vx1 - pad, vy1 - pad, vx2 + pad, vy2 + pad)

        if expanded[0] <= foot[0] <= expanded[2] and expanded[1] <= foot[1] <= expanded[3]:
            return True

        return not (
            gx2 < expanded[0]
            or gx1 > expanded[2]
            or gy2 < expanded[1]
            or gy1 > expanded[3]
        )
