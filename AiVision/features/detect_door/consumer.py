"""
features/detect_door/consumer.py
门禁状态检测 — 帧差法 + 双阶段告警(持续 N 秒触发首次,后续按间隔重复)。

结合了与上一张处理图比较和与参考背景比较两种方式：
    1、系统从摄像头画面中提取配置的ROI区域. 没有配置ROI时使用全帧, 公共处理层维护经过模糊处理的ROI图像, 门检测模块再将其转换成灰度图, 门检测也会再画面禁止时继续按间隔处理，以便累计持续时间

    2、首次处理时建立两份参考图像: 第一张有效的灰度图会分别保存为上一张处理图和参考背景图，本次不确认异常

    3、每次处理时, 同时观察短期运动和相对背景的变化， 这里的变化比例按ROI外接矩形剪裁图的总像素计算
        2.1: 比较当前图像与上一张处理图之间的差异, 用来观察画面最近是否发生了较大的运动, 默认将灰度差大于10的像素计为变化, 再计算这些像素所占的比例
        2.2: 比较当前图像与参考背景之前的差异，用来观察，用来观察当前状态是否偏离参考状态, 默认将灰度值大于5的像素计为变化, 再计算变化比例

    4、先过滤掉变化过于剧烈的画面, 如果当前图像相对于上一张处理图的变化比例超过默认的22%, 程序就把本次画面判为背景不稳定, 另一项检查是，相对背景的变化比例是否超过配置的环境上限
    默认 env_threshold 为 null，关闭该项过滤；配置为 0~1 时，仅当背景变化比例超过该值才过滤。 一旦判为背景不稳定，程序会清除连续确认状态，返回未确认的变化结果，并更新上一张处理图，供下一次比较
    参考背景保持不变，因此，门刚打开时的剧烈运动可能暂时被过滤，等画面稳定后，再判断是否持续偏离背景

    5、检查变化是否足够明显, 再进行连续确认
        通过环境检查后, 程序检查相对背景的变化比例是否同时达到threshold和min_local_change_ratio,默认分别为 50% 和 1% , 因此实际需要至少达到50%
        单次达到比例要求, 只表示这一次存在足够明显的变化, 程序还会记录第一次满足条件的时间，并累计连续满足的次数
        默认必须满足两个要求: 变化条件连续成立1秒, 并且累计满足至少3次,只达到次数、时间还不够，或者时间到了，次数还不够，都不会确认变化，这里的次数是处理次数
        中途只要有一次不在满足变化条件, 开始时间和累计次数就会清零, 通过这一步, _process()才返回"已经确认持续变化"的结果

    6、根据本次判断, 决定是否更新参考背景
        当环境稳定、且本次没有达到变化比例要求时, 程序会慢慢更新背景, 默认将当前灰度图按5% 的权重、旧背景按95% 的权重混合，形成新的参考背景
        如果已经达到变化条件, 背景更新就会暂停,包括仍在等待稳定确认的阶段

    7、把确认结果显示在画面上
        post_process()根据_process()的结果生成带标注的画面, 它会绘制ROI边框, 确认持续变化之后。还会在ROI内叠加黄色提示（黄色提示表示持续变化已经通过确认，实际报警还需要经过下一段等待时间）

    8、确认变化后, 开始首次报警计时
        _should_alarm()第一次收到确认变化的结果时, 会记录一个新的计时起点, 正常配置默认要求这种确认状态再连续维持60秒, 才允许提交首次报警
        相当于: 先通过"至少1秒,至少3次"的确认, 再开始60秒的首次报警等待, 如果在等待期间, 检测结果变回未确认状态, 这段首次报警计时也会清零

    9、异常持续时, 按冷却间隔重复提交报警
        首次报警等待通过后，只要确认变化的状态持续存在，持续就会允许提交报警，统一报警分发器根据同一摄像头，同一检测功能的上一次分发时间控制频率，默认两次报警分发至少间隔5秒
        分发器再结合通道开关和相关配置服务，处理告警记录、喇叭播放以及企业微信通知

    10、画面恢复或检测条件改变时，重置相应状态
        当画面重新接近参考背景、不在满足变化条件时，连续确认状态和首次报警计时都会清零，之后再次出现变化，需要重新走完整的确认和等待流程

    门原本关闭，程序保存关门背景；门打开时，剧烈运动可能先被过滤；门打开后静止下来，如果它仍然明显偏离背景，程序开始连续确认。默认确认通过后，画面出现黄色提示，再持续 60 秒才允许首次报警。门继续保持这一状态，就按冷却间隔重复报警；门关回接近参考背景的状态后，本轮判断和计时结束。

"""
from __future__ import annotations
import time

import cv2
import numpy as np

from AiVision.features._base.consumer import BaseFunctionConsumer

class DoorConsumer(BaseFunctionConsumer):
    """门禁检测 — 上一帧/参考背景帧差、连续确认与双阶段告警"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 上一次处理的灰度图
        self._pre_gray: dict[int, np.ndarray] = {}
        # 参考背景图
        self._bg_gray: dict[int, np.ndarray] = {}
        # 变化从何时开始，已经连续满足多少次
        self._candidate_state: dict[int, dict] = {}
        # 双阶段告警状态: camera_id → (continuous_start_ts, alarmed_once)
        self._alarm_state: dict[int, dict] = {}

    def _process(self, roi, camera_id):
        cfg = self.config_cache[camera_id]
        diff_thr = cfg["diff_threshold"]
        ratio_thr = cfg["threshold"]
        env_thr = cfg["env_threshold"]
        env_diff_thr = cfg["diff_threshold_env"]
        stable_confirm_seconds = cfg["stable_confirm_seconds"]
        stable_confirm_hits = cfg["stable_confirm_hits"]
        bg_alpha = cfg["background_update_alpha"]
        global_motion_thr = cfg["global_motion_threshold"]
        min_local_ratio = cfg["min_local_change_ratio"]
        # self.blur_roi[camera_id]是父类缓存的模糊后的ROI图像
        gray = cv2.cvtColor(self.blur_roi[camera_id], cv2.COLOR_BGR2GRAY)
        # 先建立参考图，如果第一次还没有历史图像，就把当前图保存为上一张处理图，再保存一份作为参考背景
        # 这个只是保存初始化画面
        if camera_id not in self._bg_gray or camera_id not in self._pre_gray:
            self._pre_gray[camera_id] = gray.copy()
            self._bg_gray[camera_id] = gray.copy()
            self._candidate_state.pop(camera_id, None)
            return False, {"ratio": 0.0}

        now = time.time()
        # 计算当前图像与上一张图像的差值绝对值
        prev_diff = cv2.absdiff(gray, self._pre_gray[camera_id])
        # 计算当前图像与背景图像的差值绝对值
        bg_diff = cv2.absdiff(gray, self._bg_gray[camera_id])
        # 把图像差值转换成变化比例
        _, bin_prev = cv2.threshold(prev_diff, env_diff_thr, 255, cv2.THRESH_BINARY)
        _, bin_bg = cv2.threshold(bg_diff, diff_thr, 255, cv2.THRESH_BINARY)
        # 相对于上一帧的变化比例 （变化像素数/总像素数）
        frame_motion_ratio = float(bin_prev.mean()) / 255.0
        ratio = float(bin_bg.mean()) / 255.0
        # 检查画面是否过于激烈
        unstable_background = frame_motion_ratio > global_motion_thr or (env_thr is not None and ratio > env_thr)
        # 清楚连续确认状态，更新上一张图，并返回False
        if unstable_background:
            self._reset_candidate(camera_id)
            result = (False, {
                "ratio": ratio,
                "frame_motion_ratio": frame_motion_ratio,
                "stable": False,
                "reason": "background_unstable",
            })
            self._pre_gray[camera_id] = gray
            return result

        raw_change = ratio >= ratio_thr and ratio >= min_local_ratio
        # _update_candiate：1、第一次满足变化条件时，记录开始时间。2、每次连续满足，累计次数加1。3、中途不满足，就把开始时间和次数清零
        confirmed = self._update_candidate(camera_id, raw_change, now, stable_confirm_seconds, stable_confirm_hits)
        result = (confirmed, {
            "ratio": ratio,
            "frame_motion_ratio": frame_motion_ratio,
            "hits": self._candidate_state.get(camera_id, {}).get("hits", 0),
            "stable": True,
        })
        # 更新参考背景（新背景图=当前图*5% + 旧背景*95%）
        if not raw_change:
            self._bg_gray[camera_id] = cv2.addWeighted(
                gray,
                bg_alpha,
                self._bg_gray[camera_id],
                1.0 - bg_alpha,
                0,
            )
        # 更新上一张处理图（上一张图不断跟随处理过程更新，背景图有条件的缓慢更新）
        self._pre_gray[camera_id] = gray
        return result

    def post_process(self, camera_id, result):
        frame = self._annotated_frame(camera_id)
        if frame is None:
            return None
        alarm, _detail = result
        if alarm:
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            cv2.fillPoly(mask, [self._roi_polygon_cache[camera_id]], 255)
            color = np.array([0, 255, 255], dtype=np.uint8)
            overlay = (frame * 0.7 + color * 0.3).astype(np.uint8)
            np.copyto(frame, overlay, where=mask[:, :, None] > 0)
        return frame

    def _on_roi_changed(self, camera_id: int) -> None:
        super()._on_roi_changed(camera_id)
        for cache in (self._pre_gray, self._bg_gray, self._candidate_state, self._alarm_state):
            cache.pop(camera_id, None)

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        super()._clear_camera_state(camera_id, shm_name)
        for cache in (self._pre_gray, self._bg_gray, self._candidate_state, self._alarm_state):
            cache.pop(camera_id, None)

    def _update_candidate(self, camera_id: int, raw_change: bool, now: float, seconds: float, hits: int) -> bool:
        """画面变化是否已经连续满足指定的时间和次数"""
        state = self._candidate_state.setdefault(
            camera_id,
            {"start": None, "hits": 0},
        )
        # 本次没有满足变化条件，就全部重新计数
        if not raw_change:
            state["start"] = None
            state["hits"] = 0
            return False
        # 第一次满足条件时，记下开始时间
        if state["start"] is None:
            state["start"] = now
            state["hits"] = 0
        # 本次满足条件，次数加1
        state["hits"] = int(state.get("hits", 0)) + 1
        # 检测次数和时间是否同时达标
        return state["hits"] >= hits and now - float(state["start"]) >= seconds

    def _reset_candidate(self, camera_id: int):
        state = self._candidate_state.setdefault(
            camera_id,
            {"start": None, "hits": 0},
        )
        state["start"] = None
        state["hits"] = 0

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        return True

    def _should_alarm(self, camera_id, result, cfg):
        """双阶段:持续 first_alarm 秒才首次告警,后续 alarm_dispatcher 控冷却"""
        now = time.time()
        first_alarm_threshold = cfg["first_alarm"]

        # 当前是否检测到变化
        has_change = bool(result[0])

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
