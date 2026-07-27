"""Security VLM 摄像头注册表：校验、脱敏和原子持久化。"""

from __future__ import annotations

import copy
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit


class CameraRegistry:
    """以 JSON 文件持久化安检模块独立维护的摄像头。"""

    VERSION = 1
    MAX_CAMERAS = 4

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def list(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._read_unlocked()["cameras"])

    def get(self, camera_id: str) -> dict | None:
        with self._lock:
            for camera in self._read_unlocked()["cameras"]:
                if camera["camera_id"] == str(camera_id):
                    return copy.deepcopy(camera)
        return None

    def create(self, name: str, rtsp_url: str) -> dict:
        normalized_name = self._validate_name(name)
        normalized_url = self._validate_rtsp_url(rtsp_url)
        with self._lock:
            payload = self._read_unlocked()
            if len(payload["cameras"]) >= self.MAX_CAMERAS:
                raise ValueError(f"最多只能添加 {self.MAX_CAMERAS} 台摄像头")
            self._ensure_unique_name(payload["cameras"], normalized_name)
            now = time.time()
            camera = {
                "camera_id": str(uuid.uuid4()),
                "name": normalized_name,
                "rtsp_url": normalized_url,
                "created_at": now,
                "updated_at": now,
            }
            payload["cameras"].append(camera)
            self._write_unlocked(payload)
            return copy.deepcopy(camera)

    def update(
        self,
        camera_id: str,
        *,
        name: str | None = None,
        rtsp_url: str | None = None,
    ) -> dict:
        with self._lock:
            payload = self._read_unlocked()
            camera = self._find_unlocked(payload["cameras"], camera_id)
            if name is not None:
                normalized_name = self._validate_name(name)
                self._ensure_unique_name(
                    payload["cameras"],
                    normalized_name,
                    exclude_camera_id=camera["camera_id"],
                )
                camera["name"] = normalized_name
            if rtsp_url is not None and str(rtsp_url).strip():
                camera["rtsp_url"] = self._validate_rtsp_url(rtsp_url)
            camera["updated_at"] = time.time()
            self._write_unlocked(payload)
            return copy.deepcopy(camera)

    def delete(self, camera_id: str) -> dict:
        with self._lock:
            payload = self._read_unlocked()
            camera = self._find_unlocked(payload["cameras"], camera_id)
            payload["cameras"] = [
                item
                for item in payload["cameras"]
                if item["camera_id"] != camera["camera_id"]
            ]
            self._write_unlocked(payload)
            return copy.deepcopy(camera)

    def public(self, camera: dict) -> dict:
        result = copy.deepcopy(camera)
        raw_url = str(result.get("rtsp_url", "") or "")
        result["rtsp_url"] = self._redact_rtsp_url(raw_url)
        result["has_rtsp_url"] = bool(raw_url)
        return result

    @classmethod
    def validate_rtsp_url(cls, rtsp_url: str) -> str:
        return cls._validate_rtsp_url(rtsp_url)

    def migrate_legacy(self, cfg: dict, staff_dir: Path) -> dict | None:
        """首次升级时把旧单路配置迁移为固定 ID 的摄像头记录。"""
        with self._lock:
            if self.path.exists():
                return None
            data_cfg = cfg.get("data", {}) or {}
            source = str(data_cfg.get("input_video", "") or "").strip()
            if not source:
                return None
            source = self._validate_rtsp_url(source)
            now = time.time()
            camera = {
                "camera_id": "legacy-default",
                "name": "默认安检摄像头",
                "rtsp_url": source,
                "created_at": now,
                "updated_at": now,
            }
            self._write_unlocked({
                "version": self.VERSION,
                "cameras": [camera],
            })

            staff_path = Path(staff_dir)
            legacy_video_id = str(data_cfg.get("video_id", "stream") or "stream")
            legacy_roi_path = staff_path / f"{legacy_video_id}_staff_rois.json"
            migrated_roi_path = staff_path / "legacy-default_staff_rois.json"
            if legacy_roi_path.exists() and not migrated_roi_path.exists():
                migrated_roi_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy_roi_path, migrated_roi_path)
            return copy.deepcopy(camera)

    def _read_unlocked(self) -> dict:
        if not self.path.exists():
            return {"version": self.VERSION, "cameras": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"摄像头注册表读取失败: {exc}") from exc
        cameras = payload.get("cameras")
        if payload.get("version") != self.VERSION or not isinstance(cameras, list):
            raise RuntimeError("摄像头注册表格式无效")
        return {"version": self.VERSION, "cameras": cameras}

    def _write_unlocked(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(
            f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.chmod(temp_path, 0o600)
            temp_path.replace(self.path)
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_name(name: str) -> str:
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("摄像头名称不能为空")
        return normalized

    @staticmethod
    def _validate_rtsp_url(rtsp_url: str) -> str:
        normalized = str(rtsp_url or "").strip()
        parsed = urlsplit(normalized)
        if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.netloc:
            raise ValueError("摄像头地址必须是有效的 RTSP/RTSPS 地址")
        return normalized

    @staticmethod
    def _ensure_unique_name(
        cameras: list[dict],
        name: str,
        *,
        exclude_camera_id: str | None = None,
    ) -> None:
        wanted = name.casefold()
        for camera in cameras:
            if camera.get("camera_id") == exclude_camera_id:
                continue
            if str(camera.get("name", "")).strip().casefold() == wanted:
                raise ValueError(f"摄像头名称已存在: {name}")

    @staticmethod
    def _find_unlocked(cameras: list[dict], camera_id: str) -> dict:
        wanted = str(camera_id)
        for camera in cameras:
            if camera.get("camera_id") == wanted:
                return camera
        raise KeyError(f"摄像头不存在: {wanted}")

    @staticmethod
    def _redact_rtsp_url(rtsp_url: str) -> str:
        if "@" not in rtsp_url:
            return rtsp_url
        prefix, location = rtsp_url.rsplit("@", 1)
        scheme = prefix.split("://", 1)[0]
        return f"{scheme}://***:***@{location}"
