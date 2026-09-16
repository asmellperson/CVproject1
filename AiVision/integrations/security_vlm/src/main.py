# 文件说明：作为程序启动入口并装配依赖。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""安检 API：事业部工作区隔离摄像头、ROI、结果和运行状态。"""
import asyncio
import json
import logging
import math
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from auth.auth import get_current_user

from AiVision.integrations.security_vlm.src.frame_hub import FrameHubReader, ResultStore
from AiVision.integrations.security_vlm.src.roi_geometry import (
    bbox_belongs_to_normalized_roi,
    normalize_roi_points,
    scale_roi_mapping,
    validate_rois,
)
from AiVision.integrations.security_vlm.src.camera_registry import CameraRegistry
from AiVision.integrations.security_vlm.src.camera_runtime import CameraRuntimeManager, CameraRuntimePaths
from AiVision.integrations.security_vlm.src.department_workspace import (
    DepartmentWorkspaceManager,
)
from AiVision.integrations.security_vlm.src.departments import DEPARTMENTS, require_department


LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_path(p: str, base: Path) -> Path:
    pp = Path(p)
    return pp.resolve() if pp.is_absolute() else (base / pp).resolve()


# ---------------------------------------------------------------------------
# Pydantic 模型定义
# ---------------------------------------------------------------------------
class ROIRequest(BaseModel):
    """接收多边形 ROI，几何约束由服务端统一校验。"""

    staff_rois: Dict[str, Any]


class CameraCreateRequest(BaseModel):
    name: str
    rtsp_url: str


class CameraUpdateRequest(BaseModel):
    name: str | None = None
    rtsp_url: str | None = None


class CameraTestRequest(BaseModel):
    rtsp_url: str


class CaptureDimensionsUnavailable(RuntimeError):
    """摄像头尚未产生可用于 ROI 校验的原始画面尺寸。"""


def probe_camera(rtsp_url: str) -> Dict[str, Any]:
    """用 ffprobe 检查 RTSP 视频流，错误信息不回显包含凭据的地址。"""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height",
        "-of",
        "json",
        str(rtsp_url),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        streams = (json.loads(result.stdout or "{}").get("streams") or [])
        stream = streams[0] if streams else {}
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))
        codec_name = str(stream.get("codec_name", "") or "")
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        raise RuntimeError("无法连接摄像头或读取视频信息") from exc
    if width <= 0 or height <= 0 or not codec_name:
        raise RuntimeError("摄像头未返回有效视频流")
    return {
        "codec_name": codec_name,
        "width": width,
        "height": height,
    }


# ---------------------------------------------------------------------------
# 业务服务: 管理 worker 子进程、读写共享状态、处理 ROI 持久化与缓存
# ---------------------------------------------------------------------------
class AppService:
    """摄像头注册、进程组、ROI、共享状态和画面读取的业务门面。"""

    def __init__(
        self,
        config_path: Path,
        *,
        workspace_manager: DepartmentWorkspaceManager | None = None,
        runtime_manager: CameraRuntimeManager | None = None,
        probe_func=probe_camera,
        offload_sync: bool = True,
    ):
        self.config_path = Path(config_path)
        self.project_root = Path(__file__).resolve().parent.parent
        self.cfg = load_yaml(self.config_path)
        self.runtime_dir = resolve_path(
            str(self.cfg["runtime"]["dir"]),
            self.project_root,
        )
        departments_cfg = self.cfg.get("departments", {}) or {}
        departments_runtime_root = (
            departments_cfg.get("runtime_root")
        )
        self.departments_runtime_root = (
            resolve_path(str(departments_runtime_root), self.project_root)
            if departments_runtime_root
            else self.runtime_dir / "departments"
        )
        departments_data_root = departments_cfg.get(
            "data_root",
            "data/departments",
        )
        self.departments_data_root = resolve_path(
            str(departments_data_root),
            self.project_root,
        )
        self.workspace_manager = workspace_manager or DepartmentWorkspaceManager(
            self.departments_data_root, self.departments_runtime_root
        )
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_manager = runtime_manager or CameraRuntimeManager(
            base_cfg=self.cfg,
            project_root=self.project_root,
            base_config_path=self.config_path,
            camera_provider=lambda department: self.workspace(department).registry.list(),
        )
        self.probe_func = probe_func
        self.offload_sync = offload_sync
        self._frame_hubs: Dict[tuple[str, str], FrameHubReader] = {}
        self._roi_caches: Dict[
            tuple[str, str],
            tuple[
                float,
                tuple[float, float] | None,
                Dict[str, List[List[float]]],
            ],
        ] = {}

    def workspace(self, department: str):
        """所有业务数据均从显式指定的事业部工作区读取。"""
        return self.workspace_manager.get(require_department(department))

    def mark_stopped(self):
        for department in DEPARTMENTS:
            self.workspace(department).result_store.write(
                "runtime_control",
                {"enabled": False, "message": "stopped", "ts": time.time()},
            )

    def shutdown(self) -> None:
        self.runtime_manager.shutdown()
        self._frame_hubs.clear()

    def camera_runtime_dir(self, camera_id: str, department: str) -> Path:
        return CameraRuntimePaths(self.departments_runtime_root, department, camera_id).runtime_dir

    def camera_store(self, camera_id: str, department: str) -> ResultStore:
        return ResultStore(self.camera_runtime_dir(camera_id, department))

    def get_frame_hub(self, camera_id: str, department: str):
        key = (require_department(department), camera_id)
        if key in self._frame_hubs:
            return self._frame_hubs[key]
        try:
            hub = FrameHubReader(
                self.camera_runtime_dir(camera_id, department),
                wait_timeout_sec=1.0,
            )
            self._frame_hubs[key] = hub
            return hub
        except Exception as exc:
            LOGGER.debug("摄像头 %s 的 FrameHub 尚未就绪: %s", camera_id, exc)
            return None

    def roi_path(self, camera_id: str, department: str) -> Path:
        return self.workspace(department).roi_dir / f"{camera_id}_staff_rois.json"

    def _normalize_rois_for_read(
        self,
        camera_id: str,
        rois: Any,
    ) -> Dict[str, List[List[float]]]:
        if not isinstance(rois, dict):
            LOGGER.warning("摄像头 %s 的 staff_rois 不是字典", camera_id)
            return {}
        normalized = {}
        for name, values in rois.items():
            roi_name = str(name)
            try:
                normalized[roi_name] = normalize_roi_points(values)
            except (TypeError, ValueError, OverflowError) as exc:
                LOGGER.warning(
                    "忽略摄像头 %s 的无效 ROI '%s': %s",
                    camera_id,
                    roi_name,
                    exc,
                )
        return normalized

    def load_rois(self, camera_id: str, department: str) -> Dict[str, List[List[float]]]:
        path = self.roi_path(camera_id, department)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                normalized = self._normalize_rois_for_read(
                    camera_id,
                    raw.get("staff_rois", {}),
                )
                target_dimensions = self._capture_dimensions_or_none(
                    camera_id,
                    department,
                )
                if target_dimensions is None:
                    return normalized
                source_dimensions = self._roi_source_dimensions(raw)
                if source_dimensions is None:
                    raise ValueError("ROI 文件必须包含源画面尺寸")
                return scale_roi_mapping(
                    normalized,
                    source_dimensions[0],
                    source_dimensions[1],
                    target_dimensions[0],
                    target_dimensions[1],
                )
            except (
                OSError,
                ValueError,
                TypeError,
                OverflowError,
                json.JSONDecodeError,
            ) as exc:
                LOGGER.warning("读取摄像头 %s 的 ROI 失败: %s", camera_id, exc)
        return {}

    @staticmethod
    def _roi_source_dimensions(raw: Dict[str, Any]) -> tuple[float, float] | None:
        width = raw.get("source_width")
        height = raw.get("source_height")
        if width is None and height is None:
            return None
        if (
            isinstance(width, bool)
            or isinstance(height, bool)
            or not isinstance(width, (int, float))
            or not isinstance(height, (int, float))
        ):
            raise ValueError("ROI 文件中的源画面尺寸无效")
        source_width = float(width)
        source_height = float(height)
        if (
            not math.isfinite(source_width)
            or not math.isfinite(source_height)
            or source_width <= 0
            or source_height <= 0
        ):
            raise ValueError("ROI 文件中的源画面尺寸无效")
        return source_width, source_height

    def _capture_dimensions_or_none(
        self,
        camera_id: str,
        department: str,
    ) -> tuple[float, float] | None:
        try:
            return self.capture_dimensions(camera_id, department)
        except CaptureDimensionsUnavailable:
            return None

    def capture_dimensions(self, camera_id: str, department: str) -> tuple[float, float]:
        status = self.camera_store(camera_id, department).read("capture_status", {}) or {}
        width_value = status.get("width", 0)
        height_value = status.get("height", 0)
        if (
            status.get("ok") is not True
            or isinstance(width_value, bool)
            or isinstance(height_value, bool)
            or not isinstance(width_value, (int, float))
            or not isinstance(height_value, (int, float))
        ):
            raise CaptureDimensionsUnavailable(
                "无法取得有效画面尺寸，请先连接并启动摄像头"
            )
        try:
            width = float(width_value)
            height = float(height_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CaptureDimensionsUnavailable(
                "无法取得有效画面尺寸，请先连接并启动摄像头"
            ) from exc
        if (
            not math.isfinite(width)
            or not math.isfinite(height)
            or width <= 0
            or height <= 0
        ):
            raise CaptureDimensionsUnavailable(
                "无法取得有效画面尺寸，请先连接并启动摄像头"
            )
        return width, height

    def save_rois(
        self,
        camera_id: str, rois: Dict[str, Any], department: str,
    ) -> Dict[str, List[List[float]]]:
        camera = self.workspace(department).registry.get(camera_id)
        if camera is None:
            raise KeyError(camera_id)
        width, height = self.capture_dimensions(camera_id, department)
        roi_cfg = self.cfg.get("roi", {}) or {}
        normalized = validate_rois(
            rois,
            width,
            height,
            roi_cfg.get("min_area_px", 2500),
            max_vertices=roi_cfg.get("max_vertices", 64),
        )
        payload = {
            "camera_id": camera_id,
            "camera_name": camera["name"],
            "roi_method": "frontend_canvas",
            "source_width": width,
            "source_height": height,
            "staff_rois": normalized,
        }
        path = self.roi_path(camera_id, department)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._roi_caches.pop((department, camera_id), None)
        return normalized

    def get_rois_cached(
        self,
        camera_id: str, department: str,
    ) -> Dict[str, List[List[float]]]:
        path = self.roi_path(camera_id, department)
        try:
            mtime = path.stat().st_mtime if path.exists() else -1.0
            key = (department, camera_id)
            dimensions = self._capture_dimensions_or_none(camera_id, department)
            cached = self._roi_caches.get(key)
            if (
                cached is not None
                and cached[0] == mtime
                and cached[1] == dimensions
            ):
                return cached[2]
            rois = self.load_rois(camera_id, department)
            self._roi_caches[key] = (mtime, dimensions, rois)
            return rois
        except OSError as exc:
            LOGGER.warning("检查摄像头 %s 的 ROI 缓存失败: %s", camera_id, exc)
            return self.load_rois(camera_id, department)

    def get_camera_state(self, camera_id: str, department: str) -> Dict[str, Any]:
        workspace = self.workspace(department)
        camera = workspace.registry.get(camera_id)
        if camera is None:
            raise KeyError(camera_id)
        process_status = self.runtime_manager.status(
            department,
            camera_id,
        )
        running = bool(process_status["running"])
        store = self.camera_store(camera_id, department)
        stopped_status = {"ok": False, "message": "stopped", "ts": time.time()}
        session = store.read("session_latest", {}) or {}
        public = workspace.registry.public(camera)
        public.update({
            "running": running,
            "desired_running": process_status["desired_running"],
            "workers": process_status["workers"],
            "last_error": process_status["last_error"],
            "restart_at": process_status["restart_at"],
            "capture": (
                store.read("capture_status", {}) or {}
                if running else stopped_status
            ),
            "detector": (
                store.read("tracker_status", {}) or {}
                if running else stopped_status
            ),
            "session": session if running else stopped_status,
            "staff_rois": session.get("staff_rois") or self.load_rois(camera_id, department),
        })
        return public

    def get_state(self, department: str) -> Dict[str, Any]:
        workspace = self.workspace(department)
        self.runtime_manager.reconcile()
        cameras = [
            self.get_camera_state(camera["camera_id"], department)
            for camera in workspace.registry.list()
        ]
        history = (
            workspace.result_store.read("vlm_history", {}) or {}
        ).get("items", [])
        vlm = workspace.result_store.read("vlm_status", {}) or {}
        vlm_runtime = self.runtime_manager.vlm_status()
        vlm = {**vlm, **vlm_runtime}
        if vlm_runtime["desired_running"] and not vlm_runtime["running"]:
            vlm.update({
                "ok": False,
                "message": (
                    vlm_runtime["last_error"]
                    or "VLM worker 正在等待自动重启"
                ),
                "degraded": True,
            })
        elif vlm_runtime["running"]:
            vlm["degraded"] = False
        state = {
            "department": department,
            "running": any(camera["running"] for camera in cameras),
            "ts": time.time(),
            "cameras": cameras,
            "vlm": vlm,
            "stats": workspace.result_store.read("vlm_latest_stats", {}) or {},
            "history": history[:200],
        }
        return state

    def delete_camera(self, department: str, camera_id: str) -> dict:
        """先停止摄像头，再归档当前事业部的 ROI 和摄像头运行数据。"""
        workspace = self.workspace(department)
        camera = workspace.registry.get(camera_id)
        if camera is None:
            raise KeyError(camera_id)
        stopped = self.runtime_manager.stop(department, camera_id)
        if not stopped.get("ok"):
            raise RuntimeError(stopped.get("message", "停止摄像头失败"))
        archive = workspace.archive_dir / camera_id / str(int(time.time() * 1000))
        archive.mkdir(parents=True, exist_ok=False)
        for source in (self.roi_path(camera_id, department), self.camera_runtime_dir(camera_id, department)):
            if source.exists():
                target = archive / source.name
                try:
                    shutil.move(str(source), str(target))
                except OSError as exc:
                    raise RuntimeError(f"归档摄像头数据失败: {source}") from exc
        deleted = workspace.registry.delete(camera_id)
        self._frame_hubs.pop((department, camera_id), None)
        self._roi_caches.pop((department, camera_id), None)
        return deleted


# ---------------------------------------------------------------------------
# MJPEG 渲染辅助: 在 frame 上叠加 ROI / 人体框 / 统计 banner
# ---------------------------------------------------------------------------
def _overlay_on_frame(
    frame,
    service: "AppService",
    camera_id: str,
    department: str,
):
    """
    用于 /video/rule 流。frame 此时已经被缩放到 max_side=960,
    所以 ROI / 人体框需要按比例缩放后再画。

    绘制内容：
        1. 各工位 ROI 框，并标注工位名及是否处于 session 状态
        2. YOLO 检测到的人体跟踪框
        3. 顶部统计信息 banner（总人数、合规/不合规数、合规率、待处理队列长度）
    """
    try:
        # 读取最新状态
        camera_store = service.camera_store(camera_id, department)
        global_store = service.workspace(department).result_store
        sess_latest = camera_store.read("session_latest", {}) or {}
        tracker = camera_store.read("tracker_latest", {}) or {}
        vlm_stats = global_store.read("vlm_latest_stats", {}) or {}

        # ROI 直接从配置文件读
        rois = service.get_rois_cached(camera_id, department)

        per_roi = sess_latest.get("per_roi") or {}
        tracks = tracker.get("tracks") or []
        enter_overlap_ratio = min(
            1.0,
            max(
                0.0,
                float(
                    service.cfg.get("session", {}).get(
                        "roi_enter_overlap_ratio",
                        0.30,
                    )
                ),
            ),
        )

        # 计算 frame 已经被缩放的比例（原始尺寸来自 tracker 元数据）
        orig_meta = tracker.get("frame_meta") or {}
        orig_w = int(orig_meta.get("width", frame.shape[1]))
        orig_h = int(orig_meta.get("height", frame.shape[0]))
        cur_h, cur_w = frame.shape[:2]
        sx = cur_w / max(1, orig_w)   # X方向缩放系数
        sy = cur_h / max(1, orig_h)   # Y方向缩放系数

        # 颜色板，用于不同 ROI 的框颜色
        palette = [(59, 130, 246), (16, 185, 129), (245, 158, 11),
                   (236, 72, 153), (168, 85, 247)]

        # 1) 先在同一透明层填充全部 ROI，再统一混合并画边界/标签。
        normalized_rois = {}
        draw_items = []
        roi_overlay = frame.copy()
        for idx, (name, roi) in enumerate(sorted(rois.items())):
            try:
                points = normalize_roi_points(roi)
            except (TypeError, ValueError, OverflowError) as exc:
                LOGGER.warning(
                    "摄像头 %s 的 ROI '%s' 无法叠加: %s",
                    camera_id,
                    name,
                    exc,
                )
                continue
            scaled_points = np.asarray(
                [
                    [int(round(x * sx)), int(round(y * sy))]
                    for x, y in points
                ],
                dtype=np.int32,
            )
            x1 = int(scaled_points[:, 0].min())
            y1 = int(scaled_points[:, 1].min())
            color = palette[idx % len(palette)]
            cv2.fillPoly(roi_overlay, [scaled_points], color)
            normalized_rois[name] = points
            draw_items.append((name, scaled_points, x1, y1, color))

        if draw_items:
            cv2.addWeighted(roi_overlay, 0.18, frame, 0.82, 0, frame)
        for name, scaled_points, x1, y1, color in draw_items:
            cv2.polylines(frame, [scaled_points], True, color, 2)
            info = per_roi.get(name, {})
            active = info.get("active_session_id")
            badge = "SESSION" if active else "idle"
            bc = (0, 0, 255) if active else color     # 有活动 session 时文字用红色强调
            cv2.putText(frame,
                        f"{name} [{badge}] in={info.get('persons_in_roi', 0)}",
                        (x1 + 4, max(22, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.58, bc, 2)

        # 2) 画 YOLO 人体框
        for t in tracks:
            person_box = [
                float(t["x1"]),
                float(t["y1"]),
                float(t["x2"]),
                float(t["y2"]),
            ]
            belongs_to_roi = any(
                bbox_belongs_to_normalized_roi(
                    person_box,
                    roi,
                    enter_overlap_ratio,
                )
                for roi in normalized_rois.values()
            )
            color = (0, 255, 0) if belongs_to_roi else (128, 128, 128)
            thickness = 2 if belongs_to_roi else 1
            x1 = int(person_box[0] * sx)
            y1 = int(person_box[1] * sy)
            x2 = int(person_box[2] * sx)
            y2 = int(person_box[3] * sy)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
            cv2.putText(frame, f"id={t.get('track_id', '-')}",
                        (x1, max(16, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        # 3) 顶部统计 banner
        header = (f"total={vlm_stats.get('total', 0)} "
                  f"ok={vlm_stats.get('compliant', 0)} "
                  f"no={vlm_stats.get('non_compliant', 0)} "
                  f"rate={vlm_stats.get('rate', 0)}% "
                  f"queue={vlm_stats.get('queue', 0)}")
        cv2.putText(frame, header, (14, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.66, (255, 240, 120), 2)
    except Exception as exc:
        # 渲染失败不要把整路 MJPEG 流弄崩
        LOGGER.warning("摄像头 %s 的规则画面叠加失败: %s", camera_id, exc)
    return frame


# ---------------------------------------------------------------------------
# 创建 FastAPI app
# ---------------------------------------------------------------------------
def create_app(
    config_path: Path,
    *,
    service: AppService | None = None,
) -> FastAPI:
    """
    工厂函数，创建并配置 FastAPI 应用。
    包含生命周期管理、路由注册、MJPEG 流生成器等。
    """
    service = service or AppService(config_path)

    async def run_blocking(func, *args, **kwargs):
        if service.offload_sync:
            return await asyncio.to_thread(func, *args, **kwargs)
        return func(*args, **kwargs)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        FastAPI 生命周期上下文管理器。
        启动时：只启动 API，不自动拉起 worker 子进程
        关闭时：反向终止所有 worker
        """
        service.mark_stopped()
        try:
            yield
        finally:
            service.shutdown()

    def authorize_department(request: Request, user: dict = Depends(get_current_user)) -> None:
        # 子应用直接访问时也校验归属，不能只依赖统一网关的权限过滤。
        department = request.path_params.get("department")
        if department is not None:
            try:
                require_department(department)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if user.get("role") == "admin":
            return
        departments = user.get("departments")
        if (
            user.get("role") != "viewer"
            or not isinstance(departments, list)
            or department is None
            or department not in departments
            or request.method not in {"GET", "HEAD"}
            or request.url.path.rstrip("/").endswith("/credentials")
        ):
            raise HTTPException(status_code=403, detail="无权访问该事业部安检资源")

    app = FastAPI(
        title="Security VLM Inspection",
        lifespan=lifespan,
        dependencies=[Depends(authorize_department)],
    )
    # 允许跨域请求，便于前端开发
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def department_or_400(department: str) -> str:
        try:
            return require_department(department)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def department_camera(department: str, camera_id: str) -> dict:
        department = department_or_400(department)
        camera = service.workspace(department).registry.get(camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="摄像头不存在")
        return camera

    def invalidate_frame_hubs(
        department: str,
        camera_id: str | None = None,
    ) -> None:
        department = require_department(department)
        for key in list(service._frame_hubs):
            if key[0] == department and (
                camera_id is None or key[1] == camera_id
            ):
                service._frame_hubs.pop(key, None)

    # 所有检测接口都要求显式事业部上下文。
    @app.get("/api/departments/{department}/cameras")
    async def department_cameras(department: str):
        department = department_or_400(department)
        state = await run_blocking(service.get_state, department)
        return JSONResponse({"department": department, "cameras": state["cameras"]})

    @app.post("/api/departments/{department}/cameras")
    async def department_create_camera(department: str, req: CameraCreateRequest):
        department = department_or_400(department)
        registry = service.workspace(department).registry
        try:
            camera = await run_blocking(registry.create, req.name, req.rtsp_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "camera": registry.public(camera)}, status_code=201)

    @app.get("/api/departments/{department}/cameras/{camera_id}")
    async def department_get_camera(department: str, camera_id: str):
        department_camera(department, camera_id)
        return JSONResponse({"camera": await run_blocking(service.get_camera_state, camera_id, department)})

    @app.put("/api/departments/{department}/cameras/{camera_id}")
    async def department_update_camera(department: str, camera_id: str, req: CameraUpdateRequest):
        department_camera(department, camera_id)
        status = await run_blocking(service.runtime_manager.status, department, camera_id)
        if status.get("desired_running"):
            raise HTTPException(status_code=409, detail="请先关闭摄像头检测再修改配置")
        try:
            camera = await run_blocking(service.workspace(department).registry.update, camera_id, name=req.name, rtsp_url=req.rtsp_url)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        invalidate_frame_hubs(department, camera_id)
        return JSONResponse({"ok": True, "camera": service.workspace(department).registry.public(camera)})

    @app.delete("/api/departments/{department}/cameras/{camera_id}")
    async def department_delete_camera(department: str, camera_id: str):
        department_camera(department, camera_id)
        try:
            camera = await run_blocking(service.delete_camera, department, camera_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "camera": service.workspace(department).registry.public(camera)})

    @app.get("/api/departments/{department}/cameras/{camera_id}/credentials")
    async def department_credentials(department: str, camera_id: str):
        camera = department_camera(department, camera_id)
        return JSONResponse({"camera": {key: camera[key] for key in ("camera_id", "name", "rtsp_url")}})

    @app.post("/api/departments/{department}/cameras/test")
    async def department_test_camera(department: str, req: CameraTestRequest):
        department_or_400(department)
        try:
            details = await run_blocking(service.probe_func, CameraRegistry.validate_rtsp_url(req.rtsp_url))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail="无法连接摄像头或读取视频信息") from exc
        return JSONResponse({"ok": True, **details})

    @app.post("/api/departments/{department}/cameras/{camera_id}/control/{action}")
    async def department_camera_control(department: str, camera_id: str, action: str):
        department_camera(department, camera_id)
        if action not in {"start", "stop", "restart"}:
            raise HTTPException(status_code=404, detail="invalid action")
        result = await run_blocking(getattr(service.runtime_manager, action), department, camera_id)
        invalidate_frame_hubs(department, camera_id)
        return JSONResponse(result, status_code=200 if result["ok"] else 500)

    @app.post("/api/departments/{department}/cameras/control/{action}")
    async def department_all_control(department: str, action: str):
        department_or_400(department)
        if action not in {"start-all", "stop-all"}:
            raise HTTPException(status_code=404, detail="invalid action")
        method = service.runtime_manager.start_all if action == "start-all" else service.runtime_manager.stop_all
        invalidate_frame_hubs(department)
        result = await run_blocking(method, department)
        return JSONResponse(result, status_code=200 if result["ok"] else 207)

    @app.get("/api/departments/{department}/cameras/{camera_id}/rois")
    async def department_get_rois(department: str, camera_id: str):
        department_camera(department, camera_id)
        rois = await run_blocking(service.load_rois, camera_id, department)
        return JSONResponse({"department": department, "camera_id": camera_id, "staff_rois": rois, "available_slots": list(rois)})

    @app.put("/api/departments/{department}/cameras/{camera_id}/rois")
    @app.post("/api/departments/{department}/cameras/{camera_id}/rois")
    async def department_save_rois(department: str, camera_id: str, req: ROIRequest):
        department_camera(department, camera_id)
        try:
            rois = await run_blocking(service.save_rois, camera_id, req.staff_rois, department)
        except CaptureDimensionsUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, TypeError, OverflowError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({
            "ok": True,
            "department": department,
            "camera_id": camera_id,
            "staff_rois": rois,
            "available_slots": list(rois),
        })

    @app.get("/api/departments/{department}/health")
    async def department_state(department: str):
        department = department_or_400(department)
        return JSONResponse(await run_blocking(service.get_state, department))

    @app.get("/api/departments/{department}/history")
    async def department_history(department: str, limit: int = 100, camera_id: str | None = None):
        department = department_or_400(department)
        state = await run_blocking(service.get_state, department)
        items = state["history"]
        if camera_id is not None:
            department_camera(department, camera_id)
            items = [item for item in items if str(item.get("camera_id")) == camera_id]
        return JSONResponse({"date": time.strftime("%Y-%m-%d"), "stats": state["stats"], "history": items[:max(1, limit)]})

    # ---- 基础信息 ----
    @app.get("/")
    async def root():
        """返回服务信息；页面统一由 unified_frontend 提供。"""
        return {
            "name": "security-vlm-api",
            "ok": True,
            "health": "/health",
            "frontend": "https://aicv.fudar.com",
        }

    # ---- 数据接口 ----
    @app.get("/health")
    async def health():
        """平台健康端点只返回各事业部运行摘要。"""
        summaries = {}
        for department in DEPARTMENTS:
            state = await run_blocking(service.get_state, department)
            cameras = state["cameras"]
            summaries[department] = {
                "department": department,
                "running": state["running"],
                "camera_count": len(cameras),
                "online_camera_count": sum(bool(camera["running"]) for camera in cameras),
                "vlm": state["vlm"],
            }
        return JSONResponse({"ok": True, "departments": summaries})

    # ---- MJPEG 流生成器 ----
    async def _mjpeg(
        camera_id: str,
        kind: str,
        department: str,
    ):
        """
        MJPEG 流生成器，统一限速 6fps，长边最大 960，JPEG 质量可配置。
        kind 参数：
            "original": 仅缩放 + JPEG 编码
            "rule":     额外叠加 ROI / 人体框 / 统计信息
        输出格式符合 multipart/x-mixed-replace 协议。
        """
        last_frame_id = -1           # 用于去重，避免重复推送同一帧
        jpeg_quality = int(service.cfg.get("web", {}).get("jpeg_quality", 55))
        target_stream_fps = 6.0
        min_stream_interval = 1.0 / target_stream_fps
        last_push_ts = 0.0
        max_side = 960

        while True:
            now = time.time()
            # 控制推流帧率
            if now - last_push_ts < min_stream_interval:
                await asyncio.sleep(0.005)
                continue

            hub = service.get_frame_hub(camera_id, department)
            if hub is None:
                # capture 还没起来, 慢一点轮询
                await asyncio.sleep(0.2)
                continue

            try:
                meta = hub.get_latest_meta()
                frame_id = int(meta.get("frame_id", -1))
                if frame_id < 0 or frame_id == last_frame_id:
                    await asyncio.sleep(0.01)
                    continue

                frame = hub.read_frame(meta)

                # 长边 > max_side 时缩放, 减小推流带宽
                h, w = frame.shape[:2]
                if max(h, w) > max_side:
                    s = max_side / max(h, w)
                    frame = cv2.resize(frame, (int(w * s), int(h * s)))

                if kind == "rule":
                    frame = _overlay_on_frame(
                        frame,
                        service,
                        camera_id,
                        department,
                    )

                ok, buf = cv2.imencode(
                    ".jpg", frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
                )
                if not ok:
                    await asyncio.sleep(0.02)
                    continue

                data = buf.tobytes()
                last_frame_id = frame_id
                last_push_ts = time.time()

                # multipart/x-mixed-replace 边界格式
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + data + b"\r\n"
                )
            except Exception as e:
                print(f"[mjpeg] {camera_id}/{kind} error: {e}", flush=True)
                await asyncio.sleep(0.1)

    @app.get(
        "/api/departments/{department}/video/{camera_id}/{kind}"
    )
    async def department_camera_video(
        department: str,
        camera_id: str,
        kind: str,
    ):
        department_camera(department, camera_id)
        if kind not in {"original", "rule"}:
            raise HTTPException(status_code=404, detail="invalid kind")
        return StreamingResponse(
            _mjpeg(camera_id, kind, department),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    return app
