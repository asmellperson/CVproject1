# 文件说明：实现视频帧消费与检测的帧消费、判定与告警衔接逻辑。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
features/detect_door/consumer.py
门禁状态检测 — 帧差法 + 双阶段告警(持续 N 秒触发首次,后续按间隔重复)。
"""
from __future__ import annotations
import time

import cv2
import numpy as np

from AiVision.features._base.consumer import BaseFunctionConsumer


# 功能：门禁检测 — 与 blocks 几乎一样的帧差,但用双阶段告警；输入与输出详见下方说明
# 参数：
#   - `*args`（未显式标注）：`args` 对应的业务输入值
#   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
# 返回：DoorConsumer；返回新建的 `DoorConsumer` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DoorConsumer(BaseFunctionConsumer):
    """门禁检测 — 与 blocks 几乎一样的帧差,但用双阶段告警"""

    # 功能：初始化或配置 `__init__` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().__init__`、`super`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pre_gray: dict[int, list] = {}
        self._bg_gray: dict[int, list] = {}
        self._candidate_state: dict[int, dict[int, dict]] = {}
        # 双阶段告警状态: camera_id → (continuous_start_ts, alarmed_once)
        self._alarm_state: dict[int, dict] = {}

    # 功能：处理 `_process` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `roi_list`（未显式标注）：`roi_list` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._value_config`、`self.config_cache.get`、`int`、`cfg.get`、`float`、`self._optional_ratio_threshold`、`max`、`len`、`cv2.cvtColor`、`range`
    #          等共 24 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _process(self, roi_list, camera_id):
        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        diff_thr = int(cfg.get("diff_threshold", 5))
        ratio_thr = float(cfg.get("threshold", 0.5))
        env_thr = self._optional_ratio_threshold(cfg.get("env_threshold", 1.0))
        env_diff_thr = int(cfg.get("diff_threshold_env", max(diff_thr * 2, 10)))
        stable_confirm_seconds = float(cfg.get("stable_confirm_seconds", 1.0))
        stable_confirm_hits = int(cfg.get("stable_confirm_hits", 3))
        bg_alpha = float(cfg.get("background_update_alpha", 0.05))
        global_motion_thr = float(cfg.get("global_motion_threshold", 0.22))
        min_local_ratio = float(cfg.get("min_local_change_ratio", 0.01))

        if (
            camera_id not in self._bg_gray
            or len(self._bg_gray[camera_id]) != len(roi_list)
            or camera_id not in self._pre_gray
            or len(self._pre_gray[camera_id]) != len(roi_list)
        ):
            initial = [
                cv2.cvtColor(self.blur_roi[camera_id][i], cv2.COLOR_BGR2GRAY)
                for i in range(len(roi_list))
            ]
            self._pre_gray[camera_id] = [item.copy() for item in initial]
            self._bg_gray[camera_id] = [item.copy() for item in initial]
            self._candidate_state.pop(camera_id, None)
            return [(False, {"ratio": 0.0}) for _ in roi_list]

        results = []
        now = time.time()
        for i in range(len(roi_list)):
            blur = self.blur_roi[camera_id][i]
            gray = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
            prev_diff = cv2.absdiff(gray, self._pre_gray[camera_id][i])
            bg_diff = cv2.absdiff(gray, self._bg_gray[camera_id][i])
            _, bin_prev = cv2.threshold(prev_diff, env_diff_thr, 255, cv2.THRESH_BINARY)
            _, bin_bg = cv2.threshold(bg_diff, diff_thr, 255, cv2.THRESH_BINARY)
            frame_motion_ratio = float(bin_prev.mean()) / 255.0
            ratio = float(bin_bg.mean()) / 255.0
            unstable_background = frame_motion_ratio > global_motion_thr or ratio > env_thr

            if unstable_background:
                self._reset_candidate(camera_id, i)
                results.append((False, {
                    "ratio": ratio,
                    "frame_motion_ratio": frame_motion_ratio,
                    "stable": False,
                    "reason": "background_unstable",
                }))
                self._pre_gray[camera_id][i] = gray
                continue

            raw_change = ratio >= ratio_thr and ratio >= min_local_ratio
            confirmed = self._update_candidate(camera_id, i, raw_change, now, stable_confirm_seconds, stable_confirm_hits)
            results.append((confirmed, {
                "ratio": ratio,
                "frame_motion_ratio": frame_motion_ratio,
                "hits": self._candidate_state.get(camera_id, {}).get(i, {}).get("hits", 0),
                "stable": True,
            }))
            if not raw_change:
                self._bg_gray[camera_id][i] = cv2.addWeighted(
                    gray,
                    bg_alpha,
                    self._bg_gray[camera_id][i],
                    1.0 - bg_alpha,
                    0,
                )
            self._pre_gray[camera_id][i] = gray
        return results

    # 功能：处理 `post_process` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `result`（未显式标注）：`result` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.frame_cache.get`、`self._get_roi_polygons`、`np.array`、`enumerate`、`len`、`np.zeros`、`cv2.fillPoly`、`cv2.merge`、`(frame
    #          * (1 - alpha) + color * alpha).astype`、`np.copyto`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def post_process(self, camera_id, result):
        frame = self.frame_cache.get(camera_id)
        if frame is None:
            return None
        roi_polygons = self._get_roi_polygons(camera_id)
        alpha = 0.3
        color = np.array([0, 255, 255], dtype=np.uint8)

        for i, (alarm, _msg) in enumerate(result):
            if not alarm or i >= len(roi_polygons):
                continue
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            poly = np.array(roi_polygons[i], dtype=np.int32)
            cv2.fillPoly(mask, [poly], 255)
            mask_3ch = cv2.merge([mask, mask, mask])
            overlay = (frame * (1 - alpha) + color * alpha).astype(np.uint8)
            np.copyto(frame, overlay, where=mask_3ch > 0)
        return frame

    # 功能：更新或保存 `_update_candidate` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `roi_index`（int）：`roi_index` 对应的业务输入值
    #   - `raw_change`（bool）：`raw_change` 对应的业务输入值
    #   - `now`（float）：`now` 对应的业务输入值
    #   - `seconds`（float）：`seconds` 对应的时间间隔或时长
    #   - `hits`（int）：`hits` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_door/consumer.py` 的 `DoorConsumer::_process` 调用本符号
    #   - 内部调用：`self._candidate_state.setdefault(camera_id,
    #          {}).setdefault`、`self._candidate_state.setdefault`、`int`、`state.get`、`float`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _update_candidate(self, camera_id: int, roi_index: int, raw_change: bool, now: float, seconds: float, hits: int) -> bool:
        state = self._candidate_state.setdefault(camera_id, {}).setdefault(
            roi_index,
            {"start": None, "hits": 0},
        )
        if not raw_change:
            state["start"] = None
            state["hits"] = 0
            return False
        if state["start"] is None:
            state["start"] = now
            state["hits"] = 0
        state["hits"] = int(state.get("hits", 0)) + 1
        return state["hits"] >= hits and now - float(state["start"]) >= seconds

    # 功能：实现 `_reset_candidate` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `roi_index`（int）：`roi_index` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_door/consumer.py` 的 `DoorConsumer::_process` 调用本符号
    #   - 内部调用：`self._candidate_state.setdefault(camera_id, {}).setdefault`、`self._candidate_state.setdefault`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _reset_candidate(self, camera_id: int, roi_index: int):
        state = self._candidate_state.setdefault(camera_id, {}).setdefault(
            roi_index,
            {"start": None, "hits": 0},
        )
        state["start"] = None
        state["hits"] = 0

    # 功能：实现 `_optional_ratio_threshold` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `value`（未显式标注）：待转换、校验或写入的值
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_door/consumer.py` 的 `DoorConsumer::_process` 调用本符号
    #   - 内部调用：`float`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _optional_ratio_threshold(value) -> float:
        value = float(value)
        return 1.0 if value > 1 else value

    # 功能：处理 `_process_static_frames` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `cfg`（dict）：运行配置对象
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        return True

    # 功能：双阶段:持续 first_alarm 秒才首次告警,后续 alarm_dispatcher 控冷却；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `result`（未显式标注）：`result` 对应的业务输入值
    #   - `cfg`（未显式标注）：运行配置对象
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`time.time`、`self._value_config(cfg).get`、`self._value_config`、`any`、`isinstance`、`self._alarm_state.setdefault`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _should_alarm(self, camera_id, result, cfg):
        """双阶段:持续 first_alarm 秒才首次告警,后续 alarm_dispatcher 控冷却"""
        now = time.time()
        first_alarm_threshold = self._value_config(cfg).get("first_alarm", 3.0)

        # 当前是否检测到变化
        has_change = any(item[0] for item in (result or []) if isinstance(item, (list, tuple)))

        state = self._alarm_state.setdefault(camera_id, {"start": None, "alarmed": False})

        if not has_change:
            # 状态恢复 — 重置
            state["start"] = None
            state["alarmed"] = False
            return False

        # 记录持续起点
        if state["start"] is None:
            state["start"] = now

        if not state["alarmed"]:
            # 第一阶段 — 等待持续时间到达
            if now - state["start"] >= first_alarm_threshold:
                state["alarmed"] = True
                return True
            return False

        # 第二阶段 — 已告警过,后续频率由 alarm_dispatcher 的冷却控制
        return True
