# 文件说明：实现视频帧消费与检测的帧消费、判定与告警衔接逻辑。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
features/detect_phone/consumer.py
手机检测消费者 — 手机框需经过人体关联、连续命中与持续时间确认后告警。
"""
from __future__ import annotations
import time
import cv2

from AiVision.features._base.consumer import BaseFunctionConsumer


# 功能：手机检测 — 过滤孤立手机框，降低桌面手机、反光、背景误报；输入与输出详见下方说明
# 参数：
#   - `*args`（未显式标注）：`args` 对应的业务输入值
#   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
# 返回：PhoneConsumer；返回新建的 `PhoneConsumer` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class PhoneConsumer(BaseFunctionConsumer):
    """手机检测 — 过滤孤立手机框，降低桌面手机、反光、背景误报。"""

    PERSON_MODEL_NAME = "yolo_human"

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
        self._tracks: dict[int, dict[int, dict]] = {}
        self._next_track_id: dict[int, int] = {}

    # 功能：处理 `_process` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `roi_list`（未显式标注）：`roi_list` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._value_config`、`self.config_cache.get`、`float`、`cfg.get`、`bool`、`self._results_by_roi`、`self.dispatch_inference_sync`、`time.time`、`self._get_roi_offsets`、`range`
    #          等共 20 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _process(self, roi_list, camera_id):
        if not self.spec.required_models:
            return [(False, None) for _ in roi_list]
        cfg = self._value_config(self.config_cache.get(camera_id, {}))
        conf_thr = float(cfg.get("CONF_THRESHOLD", 0.7))
        iou_thr = float(cfg.get("IOU_THR", 0.5))
        require_person = bool(cfg.get("REQUIRE_PERSON_ASSOCIATION", True))
        person_available = self.PERSON_MODEL_NAME in self.infer_dict
        model_name = self.spec.required_models[0]
        phone_results = self._results_by_roi(self.dispatch_inference_sync(
            camera_id,
            model_name,
            roi_list,
            task_meta={"conf": conf_thr, "iou": iou_thr},
        ))
        person_results = {}
        if require_person and person_available:
            person_results = self._results_by_roi(self.dispatch_inference_sync(
                camera_id,
                self.PERSON_MODEL_NAME,
                roi_list,
                task_meta={
                    "conf": float(cfg.get("PERSON_CONF_THRESHOLD", 0.3)),
                    "iou": float(cfg.get("PERSON_IOU_THR", 0.3)),
                },
                timeout=0.6,
            ))

        results = []
        now = time.time()
        roi_offsets = self._get_roi_offsets(camera_id)
        for roi_index in range(len(roi_list)):
            phones = phone_results.get(roi_index, {}).get("detections", []) or []
            persons = person_results.get(roi_index, {}).get("detections", []) or []
            ox, oy = roi_offsets[roi_index] if roi_index < len(roi_offsets) else (0, 0)
            candidates = self._qualified_phone_detections(
                camera_id=camera_id,
                roi_index=roi_index,
                detections=phones,
                persons=persons,
                offset=(ox, oy),
                cfg=cfg,
                now=now,
                enforce_person=require_person and person_available,
            )
            results.append((any(item.get("confirmed") for item in candidates), candidates))
        self._prune_tracks(camera_id, now, float(cfg.get("TRACK_TTL_SECONDS", 2.0)))
        return results

    # 功能：处理 `post_process` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `result`（未显式标注）：`result` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.frame_cache.get`、`frame.copy`、`self._get_roi_offsets`、`enumerate`、`len`、`det.get`、`int`、`bool`、`cv2.rectangle`、`cv2.putText`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def post_process(self, camera_id, result):
        frame = self.frame_cache.get(camera_id)
        if frame is None:
            return None
        frame_copy = frame.copy()
        roi_offsets = self._get_roi_offsets(camera_id)

        for roi_index, (alarm, detections) in enumerate(result):
            if not detections:
                continue
            ox, oy = roi_offsets[roi_index] if roi_index < len(roi_offsets) else (0, 0)
            for det in detections:
                bbox = det.get("bbox", [])
                if len(bbox) < 4:
                    continue
                x1, y1, x2, y2 = (
                    int(bbox[0]) + ox, int(bbox[1]) + oy,
                    int(bbox[2]) + ox, int(bbox[3]) + oy,
                )
                conf = det.get("confidence", 0)
                confirmed = bool(det.get("confirmed"))
                color = (0, 255, 0) if confirmed else (0, 191, 255)
                label = "phone" if confirmed else "phone?"
                cv2.rectangle(frame_copy, (x1, y1), (x2, y2), color, 2)
                cv2.putText(
                    frame_copy,
                    f"{label} {conf:.2f} {int(det.get('hits', 1))}x",
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color,
                    2,
                )
        return frame_copy

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

    # 功能：读取或查询 `_get_roi_offsets` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：list[tuple[int, int]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_process`
    #         调用本符号；`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::post_process` 调用本符号
    #   - 内部调用：`offsets.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _get_roi_offsets(self, camera_id: int) -> list[tuple[int, int]]:
        offsets = []
        if camera_id in self._masks:
            for _mask, y_min, _y_max, x_min, _x_max in self._masks[camera_id]:
                offsets.append((x_min, y_min))
        return offsets

    # 功能：实现 `_results_by_roi` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `results`（list[dict]）：`results` 对应的业务输入值
    # 返回：dict[int, dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_process` 调用本符号
    #   - 内部调用：`int`、`item.get`、`enumerate`、`isinstance`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _results_by_roi(results: list[dict]) -> dict[int, dict]:
        return {
            int(item.get("roi_id", index)): item
            for index, item in enumerate(results or [])
            if isinstance(item, dict)
        }

    # 功能：实现 `_qualified_phone_detections` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `roi_index`（int）：`roi_index` 对应的业务输入值
    #   - `detections`（list[dict]）：`detections` 对应的业务输入值
    #   - `persons`（list[dict]）：`persons` 对应的业务输入值
    #   - `offset`（tuple[int, int]）：分页或序列中的起始偏移量
    #   - `cfg`（dict）：运行配置对象
    #   - `now`（float）：`now` 对应的业务输入值
    #   - `enforce_person`（bool）：`enforce_person` 对应的业务输入值
    # 返回：list[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_process` 调用本符号
    #   - 内部调用：`det.get`、`len`、`self._offset_bbox`、`self._is_near_person_hand_region`、`self._update_track`、`float`、`int`、`cfg.get`、`out.append`、`round`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _qualified_phone_detections(
        self,
        *,
        camera_id: int,
        roi_index: int,
        detections: list[dict],
        persons: list[dict],
        offset: tuple[int, int],
        cfg: dict,
        now: float,
        enforce_person: bool,
    ) -> list[dict]:
        out = []
        for det in detections:
            bbox = det.get("bbox", [])
            if len(bbox) < 4:
                continue
            global_bbox = self._offset_bbox(bbox, offset)
            if enforce_person and not self._is_near_person_hand_region(global_bbox, persons, offset, cfg):
                continue
            track = self._update_track(camera_id, roi_index, global_bbox, now, cfg)
            duration = now - float(track["first_seen"])
            confirmed = (
                int(track["hits"]) >= int(cfg.get("MIN_CONSECUTIVE_HITS", 3))
                and duration >= float(cfg.get("MIN_CONFIRM_SECONDS", 1.2))
            )
            out.append({
                **det,
                "track_id": track["id"],
                "hits": track["hits"],
                "duration": round(duration, 2),
                "confirmed": confirmed,
                "person_associated": enforce_person,
            })
        return out

    # 功能：实现 `_offset_bbox` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `bbox`（未显式标注）：`bbox` 对应的业务输入值
    #   - `offset`（tuple[int, int]）：分页或序列中的起始偏移量
    # 返回：tuple[float, float, float, float]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_qualified_phone_detections`
    #         调用本符号；`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_is_near_person_hand_region` 调用本符号
    #   - 内部调用：`float`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _offset_bbox(bbox, offset: tuple[int, int]) -> tuple[float, float, float, float]:
        ox, oy = offset
        return (
            float(bbox[0]) + ox,
            float(bbox[1]) + oy,
            float(bbox[2]) + ox,
            float(bbox[3]) + oy,
        )

    # 功能：检查或判断 `_is_near_person_hand_region` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `phone_bbox`（未显式标注）：`phone_bbox` 对应的业务输入值
    #   - `persons`（list[dict]）：`persons` 对应的业务输入值
    #   - `offset`（tuple[int, int]）：分页或序列中的起始偏移量
    #   - `cfg`（dict）：运行配置对象
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_qualified_phone_detections` 调用本符号
    #   - 内部调用：`float`、`cfg.get`、`person.get`、`len`、`self._offset_bbox`、`max`、`self._intersection_ratio`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _is_near_person_hand_region(self, phone_bbox, persons: list[dict], offset: tuple[int, int], cfg: dict) -> bool:
        expand = float(cfg.get("PERSON_EXPAND_RATIO", 0.18))
        max_y_ratio = float(cfg.get("HAND_REGION_MAX_Y_RATIO", 0.85))
        pcx = (phone_bbox[0] + phone_bbox[2]) / 2.0
        pcy = (phone_bbox[1] + phone_bbox[3]) / 2.0

        for person in persons:
            bbox = person.get("bbox", [])
            if len(bbox) < 4:
                continue
            x1, y1, x2, y2 = self._offset_bbox(bbox, offset)
            width = max(1.0, x2 - x1)
            height = max(1.0, y2 - y1)
            ex1 = x1 - width * expand
            ex2 = x2 + width * expand
            ey1 = y1 - height * expand
            ey2 = y1 + height * max_y_ratio
            if ex1 <= pcx <= ex2 and ey1 <= pcy <= ey2:
                return True
            if self._intersection_ratio(phone_bbox, (ex1, ey1, ex2, ey2)) >= float(cfg.get("MIN_PERSON_PHONE_OVERLAP", 0.08)):
                return True
        return False

    # 功能：更新或保存 `_update_track` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `roi_index`（int）：`roi_index` 对应的业务输入值
    #   - `bbox`（未显式标注）：`bbox` 对应的业务输入值
    #   - `now`（float）：`now` 对应的业务输入值
    #   - `cfg`（dict）：运行配置对象
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_qualified_phone_detections` 调用本符号
    #   - 内部调用：`self._tracks.setdefault`、`float`、`cfg.get`、`tracks.values`、`track.get`、`self._iou`、`self._center_distance_ratio`、`self._next_track_id.get`、`match.get`、`int`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _update_track(self, camera_id: int, roi_index: int, bbox, now: float, cfg: dict) -> dict:
        tracks = self._tracks.setdefault(camera_id, {})
        match = None
        min_iou = float(cfg.get("TRACK_IOU_THRESHOLD", 0.2))
        for track in tracks.values():
            if track.get("roi_index") != roi_index:
                continue
            if self._iou(bbox, track["bbox"]) >= min_iou or self._center_distance_ratio(bbox, track["bbox"]) <= 0.6:
                match = track
                break

        if match is None:
            track_id = self._next_track_id.get(camera_id, 1)
            self._next_track_id[camera_id] = track_id + 1
            match = {"id": track_id, "roi_index": roi_index, "bbox": bbox, "first_seen": now, "last_seen": now, "hits": 0}
            tracks[track_id] = match
        elif now - float(match.get("last_seen", 0.0)) > float(cfg.get("MAX_MISSED_SECONDS", 0.6)):
            match["first_seen"] = now
            match["hits"] = 0

        match["bbox"] = bbox
        match["last_seen"] = now
        match["hits"] = int(match.get("hits", 0)) + 1
        return match

    # 功能：删除或清理 `_prune_tracks` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `now`（float）：`now` 对应的业务输入值
    #   - `ttl`（float）：`ttl` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_process` 调用本符号
    #   - 内部调用：`self._tracks.get`、`tracks.items`、`float`、`track.get`、`tracks.pop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _prune_tracks(self, camera_id: int, now: float, ttl: float):
        tracks = self._tracks.get(camera_id)
        if not tracks:
            return
        stale = [track_id for track_id, track in tracks.items() if now - float(track.get("last_seen", 0.0)) > ttl]
        for track_id in stale:
            tracks.pop(track_id, None)

    # 功能：实现 `_area` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `bbox`（未显式标注）：`bbox` 对应的业务输入值
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_intersection_ratio`
    #         调用本符号；`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_iou` 调用本符号
    #   - 内部调用：`max`、`float`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _area(bbox) -> float:
        return max(0.0, float(bbox[2]) - float(bbox[0])) * max(0.0, float(bbox[3]) - float(bbox[1]))

    # 功能：实现 `_intersection_ratio` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `a`（未显式标注）：`a` 对应的业务输入值
    #   - `b`（未显式标注）：`b` 对应的业务输入值
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_is_near_person_hand_region` 调用本符号
    #   - 内部调用：`max`、`float`、`min`、`self._area`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _intersection_ratio(self, a, b) -> float:
        ix1 = max(float(a[0]), float(b[0]))
        iy1 = max(float(a[1]), float(b[1]))
        ix2 = min(float(a[2]), float(b[2]))
        iy2 = min(float(a[3]), float(b[3]))
        inter = self._area((ix1, iy1, ix2, iy2))
        return inter / max(1.0, self._area(a))

    # 功能：实现 `_iou` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `a`（未显式标注）：`a` 对应的业务输入值
    #   - `b`（未显式标注）：`b` 对应的业务输入值
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_update_track` 调用本符号
    #   - 内部调用：`max`、`float`、`min`、`self._area`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _iou(self, a, b) -> float:
        ix1 = max(float(a[0]), float(b[0]))
        iy1 = max(float(a[1]), float(b[1]))
        ix2 = min(float(a[2]), float(b[2]))
        iy2 = min(float(a[3]), float(b[3]))
        inter = self._area((ix1, iy1, ix2, iy2))
        union = self._area(a) + self._area(b) - inter
        return inter / max(1.0, union)

    # 功能：实现 `_center_distance_ratio` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `a`（未显式标注）：`a` 对应的业务输入值
    #   - `b`（未显式标注）：`b` 对应的业务输入值
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_update_track` 调用本符号
    #   - 内部调用：`float`、`max`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _center_distance_ratio(a, b) -> float:
        acx = (float(a[0]) + float(a[2])) / 2.0
        acy = (float(a[1]) + float(a[3])) / 2.0
        bcx = (float(b[0]) + float(b[2])) / 2.0
        bcy = (float(b[1]) + float(b[3])) / 2.0
        scale = max(float(a[2]) - float(a[0]), float(a[3]) - float(a[1]), 1.0)
        return (((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5) / scale
