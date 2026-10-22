"""按已保存配置在实时采集帧绘制 ROI，不依赖检测请求或历史推理帧。"""
from dataclasses import dataclass
from threading import Lock

from AiVision.features._shared.roi import annotate_roi


@dataclass(frozen=True)
class _PreviewEntry:
    camera_key: str
    roi: list[list[float]]


class AgvPreview:
    """独立短锁只保护配置快照，取图不等待 AGV 采样期间的推理锁。"""

    def __init__(self, roi_color):
        self._roi_color = roi_color
        self._lock = Lock()
        self._entries: dict[int, _PreviewEntry] = {}

    def configure(self, camera_id: int, config: dict | None):
        entry = None
        if config and config.get("enable") and config.get("camera_enable", True):
            entry = _PreviewEntry(config["shm_name"], [list(point) for point in config.get("roi_pos", [])])
        with self._lock:
            if entry is None:
                self._entries.pop(camera_id, None)
            else:
                self._entries[camera_id] = entry

    def clear(self):
        with self._lock:
            self._entries.clear()

    def _entry(self, camera_key: str):
        with self._lock:
            return next((entry for entry in self._entries.values() if entry.camera_key == camera_key), None)

    def render(self, camera_key: str, frame):
        entry = self._entry(camera_key)
        if entry is None:
            return None
        annotated = annotate_roi(frame, entry.roi, self._roi_color)
        # 配置替换或停用发生在渲染期间时，不能返回旧配置的边框。
        return annotated if self._entry(camera_key) is entry else None
