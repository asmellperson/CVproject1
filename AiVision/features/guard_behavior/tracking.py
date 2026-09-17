"""官方 ByteTrack 的单摄入口，仅扩展轨迹 ID 的分配边界。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import yaml

from .state import TrackedPerson


_TRACK_BUFFER_REFERENCE_FPS = 30


@lru_cache(maxsize=1)
def _tracker_types():
    # Ultralytics 在缺少 lap 时会尝试安装；提前检查，保持运行过程离线。
    try:
        import lap
        if not lap.__version__:
            raise ImportError("lap 版本信息缺失")
    except (ImportError, AttributeError) as exc:
        raise RuntimeError("BYTETracker 需要已安装的本地 lap 依赖，禁止运行时下载安装") from exc

    from ultralytics.engine.results import Boxes
    from ultralytics.trackers.byte_tracker import BYTETracker, STrack

    class CameraSTrack(STrack):
        def __init__(self, xywh, score, cls, allocate_id):
            super().__init__(xywh, score, cls)
            self._allocate_id = allocate_id

        def next_id(self):
            return self._allocate_id()

    class LocalBYTETracker(BYTETracker):
        def __init__(self, args):
            # 官方构造函数会动态调用 reset_id，必须先建立实例计数器。
            self.next_track_id = 1
            super().__init__(args)

        def _allocate_id(self):
            track_id = self.next_track_id
            self.next_track_id += 1
            return track_id

        def reset_id(self):
            # 不触碰 BaseTrack 的全局计数器，也不影响其他 Camera。
            self.next_track_id = 1

        def init_track(self, results, img=None):
            if len(results) == 0:
                return []
            boxes = np.concatenate([results.xywh, np.arange(len(results)).reshape(-1, 1)], axis=-1)
            return [CameraSTrack(box, score, cls, self._allocate_id)
                    for box, score, cls in zip(boxes, results.conf, results.cls)]

    return LocalBYTETracker, Boxes


def _default_arguments() -> SimpleNamespace:
    import ultralytics

    path = Path(ultralytics.__file__).resolve().parent / "cfg" / "trackers" / "bytetrack.yaml"
    if not path.is_file():
        raise RuntimeError(f"Ultralytics 包内 ByteTrack 默认配置不存在: {path}")
    values = yaml.safe_load(path.read_text(encoding="utf-8"))
    required = {"tracker_type", "track_high_thresh", "track_low_thresh", "new_track_thresh",
                "track_buffer", "match_thresh", "fuse_score"}
    if not isinstance(values, dict) or not required <= values.keys() or values["tracker_type"] != "bytetrack":
        raise RuntimeError("Ultralytics 包内 ByteTrack 默认配置不完整")
    return SimpleNamespace(**values)


class CameraByteTracker:
    """一个实例仅属于一路 Camera，Consumer 负责按 camera_id 创建和销毁。"""

    def __init__(self, fps: float):
        tracker_type, self._boxes_type = _tracker_types()
        args = _default_arguments()
        # 上游直接接收缓冲帧数；在边界保留按 Camera FPS 换算的丢失保留时长。
        args.track_buffer = int(max(1, round(fps)) / _TRACK_BUFFER_REFERENCE_FPS * args.track_buffer)
        self.tracker = tracker_type(args)

    def reset(self) -> None:
        # 官方 reset 负责轨迹、Kalman 与帧号清理；只覆盖其 ID 重置动作。
        self.tracker.reset()

    def update(self, persons: list[dict], frame_shape: tuple[int, ...]) -> list[TrackedPerson]:
        values = np.asarray([[*person["bbox"], person["confidence"], 0.] for person in persons], dtype=np.float32)
        boxes = self._boxes_type(values.reshape(-1, 6), orig_shape=frame_shape[:2])
        rows = self.tracker.update(boxes)
        matched = {}
        for row in rows:
            if len(row) != 8:
                raise ValueError("BYTETracker 人体输出必须包含 bbox、ID、score、class 和检测索引")
            index = int(row[7])
            if index < 0 or index >= len(persons) or index in matched:
                raise ValueError("BYTETracker 返回了无效的检测索引")
            matched[index] = TrackedPerson(tuple(float(value) for value in row[:4]), float(row[5]), int(row[4]))
        # 尚未激活的检测仍需制服识别；保留无 ID 目标，禁止将其当作无人。
        return [matched[index] if index in matched else TrackedPerson(
            tuple(float(value) for value in person["bbox"]), float(person["confidence"]), None,
        ) for index, person in enumerate(persons)]
