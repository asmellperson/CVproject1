"""
================================================================================
main.py —— Web 主进程 (FastAPI)
================================================================================
职责:
    1. 启动时按顺序拉起 4 个 worker 子进程 (capture/detector/session/vlm)
    2. 提供 REST API:
         GET  /              服务信息
         GET  /health        所有 worker 状态 + 历史 + 统计 (前端轮询)
         GET  /api/history   只返回历史
         GET  /api/rois      读 ROI 配置
         POST /api/rois      保存 ROI 配置 (前端绘制后调用)
         GET  /video/original 原始 MJPEG 流
         GET  /video/rule     带 ROI / 人体框 / 统计 banner 的 MJPEG 流
    3. 退出时反向终止 worker

MJPEG 渲染:
    web 端两路视频都是从 FrameHub 读最新帧, 按 6fps 限流 + 长边 960 缩放
    + JPEG 编码后通过 multipart 流式推送。"rule" 流额外叠加 ROI / tracks /
    统计信息 (从 ResultStore 实时读)。

ROI 热加载:
    POST /api/rois 把 JSON 写到 staff_identity_dir/<video_id>_staff_rois.json,
    session_worker 通过 mtime 检测自动重新加载, 不需要重启进程。
================================================================================
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List

import cv2
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# 把 src/ 加入 import 路径, 让 frame_hub 能被找到
sys.path.insert(0, str(Path(__file__).resolve().parent))
from frame_hub import FrameHubReader, ResultStore  # noqa: E402


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
    """前端传来的 ROI 数据格式，一个字典，键为工位名，值为 [x1,y1,x2,y2] 坐标列表"""
    staff_rois: Dict[str, List[float]]


# ---------------------------------------------------------------------------
# 业务服务: 管理 worker 子进程、读写共享状态、处理 ROI 持久化与缓存
# ---------------------------------------------------------------------------
class AppService:
    """
    封装主进程所有状态管理与业务逻辑。
    包括：
        - 子进程生命周期管理
        - FrameHubReader 懒加载
        - ROI 配置的读写与缓存（带 mtime 检测）
        - 聚合各 worker 状态供前端 /health 接口使用
    """
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.project_root = Path(__file__).resolve().parent.parent
        self.cfg = load_yaml(config_path)

        # /dev/shm 共享目录
        self.runtime_dir = Path(self.cfg["runtime"]["dir"]).resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.store = ResultStore(self.runtime_dir)  # # 用于从共享内存读取各 worker 最新状态的存储对象

        # 子进程句柄,键为 worker 名称，值为 subprocess.Popen 对象
        self.procs: Dict[str, subprocess.Popen] = {}

        # ROI 持久化路径
        staff_dir = Path(self.cfg["data"]["staff_identity_dir"])
        staff_dir.mkdir(parents=True, exist_ok=True)
        self.video_id = str(self.cfg["data"].get("video_id", "stream"))
        self.roi_json_path = staff_dir / f"{self.video_id}_staff_rois.json"

        # FrameHubReader 懒加载 (capture 启动后才能打开)
        self._frame_hub: FrameHubReader | None = None

        # ROI 缓存，用于 MJPEG 渲染时高频读取，通过 mtime 判断是否需重新加载
        self._roi_cache: Dict[str, List[float]] | None = None
        self._roi_cache_mtime = 0.0

    def is_running(self) -> bool:
        """只要有 worker 进程存活，就认为检测功能处于开启状态。"""
        return any(p.poll() is None for p in self.procs.values())

    def _clear_frame_hub(self):
        """worker 停止/重启后丢弃旧 reader，避免继续读旧共享内存句柄。"""
        self._frame_hub = None

    # ---- FrameHub 懒加载 ----
    def get_frame_hub(self):
        """
        获取 FrameHubReader 实例。
        若 capture 尚未启动（共享内存文件未就绪）则返回 None；
        一旦成功打开则缓存复用。
        """
        if self._frame_hub is not None:
            return self._frame_hub
        try:
            # 等待超时设为 1 秒，若共享内存未就绪会抛异常
            self._frame_hub = FrameHubReader(self.runtime_dir, wait_timeout_sec=1.0)
            return self._frame_hub
        except Exception:
            return None

    # ---- ROI 读写 ----
    def _roi_load(self) -> Dict[str, List[float]]:
        """
        从 JSON 文件读取 ROI 配置，若读取失败或文件不存在，
        则回退到配置文件中的 staff_rois。
        返回格式：{ 工位名: [x1,y1,x2,y2] }
        """
        if self.roi_json_path.exists():
            try:
                raw = json.loads(self.roi_json_path.read_text(encoding="utf-8"))
                rois = raw.get("staff_rois", {})
                if isinstance(rois, dict):
                    # 确保坐标值为浮点数列表且长度至少为4
                    return {
                        str(k): [float(v[0]), float(v[1]), float(v[2]), float(v[3])]
                        for k, v in rois.items()
                        if isinstance(v, list) and len(v) >= 4
                    }
            except Exception:
                pass
        # 回退到配置文件
        return dict(self.cfg.get("staff_rois", {}) or {})

    def _roi_save(self, rois: Dict[str, List[float]]):
        """
        前端保存 ROI 时调用：将 ROI 字典写入 JSON 文件。
        session_worker 通过监控该文件的 mtime 自动热加载，无需重启。
        """
        # 归一化坐标：保留两位小数，只取前四个值
        normalized = {}
        for k, v in rois.items():
            if isinstance(v, list) and len(v) >= 4:
                normalized[str(k)] = [round(float(x), 2) for x in v[:4]]
        payload = {
            "video_id": self.video_id,
            "video_path": str(self.cfg["data"]["input_video"]),
            "roi_method": "frontend_canvas",
            "staff_rois": normalized,
        }
        self.roi_json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_rois_cached(self) -> Dict[str, List[float]]:
        """
        带 mtime【modification time（文件最后修改时间）】 缓存的 ROI 读取。
        用于 MJPEG 渲染等高频调用，避免频繁读取磁盘。
        """
        try:
            if self.roi_json_path.exists():
                # 记录文件的最后修改时间
                mtime = self.roi_json_path.stat().st_mtime
                # 若文件未修改且缓存存在，直接返回缓存
                if self._roi_cache is not None and mtime == self._roi_cache_mtime:
                    return self._roi_cache
                # 否则重新加载并更新缓存
                self._roi_cache = self._roi_load()
                self._roi_cache_mtime = mtime
                return self._roi_cache
        except Exception:
            pass
        return self._roi_cache if self._roi_cache is not None else self._roi_load()

    # ---- worker 子进程管理 ----
    def start_workers(self):
        """
        按依赖顺序启动 4 个 worker 子进程：
            capture  → detector → session → vlm
        每个进程启动后休眠 0.3 秒，避免同时抢占资源。
        """
        if self.is_running():
            return
        self._clear_frame_hub()
        worker_py = str(self.cfg["envs"]["worker_python"])
        scripts = [
            ("capture",  "capture_worker.py"),    # 必须先起 (产出 FrameHub)
            ("detector", "detector_worker.py"),   # 依赖 capture
            ("session",  "session_worker.py"),    # 依赖 detector
            ("vlm",      "vlm_worker.py"),        # 独立, 扫文件队列
        ]
        env = os.environ.copy()
        for name, script in scripts:
            path = self.project_root / "src" / script
            print(f"[main] 启动 {name}: {path}", flush=True)
            # 启动一个子进程来运行worker程序
            self.procs[name] = subprocess.Popen(
                [worker_py, str(path), "--config", str(self.config_path)],    # 要执行的命令和参数
                cwd=str(self.project_root),    # 在那个文件夹里运行
                env=env,                       # 环境变量设置
            )
            time.sleep(0.3)  # 给前一个 worker 一点启动时间
        self.store.write("runtime_control", {
            "enabled": True,
            "message": "running",
            "ts": time.time(),
        })

    def stop_workers(self):
        """
        反向终止子进程，顺序为 vlm → session → detector → capture。
        先尝试 SIGTERM 优雅退出，等待最多 10 秒，若未退出则 kill。
        """
        order = ["vlm", "session", "detector", "capture"]
        for name in order:
            p = self.procs.get(name)
            # 如果进程不存在或已经退出，跳过
            if p is None or p.poll() is not None:
                continue
            print(f"[main] 终止 {name}...", flush=True)
            try:
                p.terminate()    # 让它结束
            except Exception:
                pass
        for name in order:
            p = self.procs.get(name)
            if p is None:
                continue
            try:
                p.wait(timeout=10)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self.procs.clear()
        self._clear_frame_hub()
        now = time.time()
        self.store.write("runtime_control", {
            "enabled": False,
            "message": "stopped",
            "ts": now,
        })
        for key in ("capture_status", "tracker_status", "session_status", "vlm_status"):
            self.store.write(key, {"ok": False, "message": "stopped", "ts": now})

    # ---- 聚合状态供前端轮询 ----
    def get_state(self) -> Dict[str, Any]:
        """
        从 ResultStore 读取各 worker 的最新状态，整合为一个大字典返回。
        供 /health 接口使用。
        """
        capture     = self.store.read("capture_status", {}) or {}
        detector    = self.store.read("tracker_status", {}) or {}
        sess_latest = self.store.read("session_latest", {}) or {}
        vlm_status  = self.store.read("vlm_status", {}) or {}
        vlm_stats   = self.store.read("vlm_latest_stats", {}) or {}
        history     = (self.store.read("vlm_history", {}) or {}).get("items", [])
        running = self.is_running()
        stopped_status = {"ok": False, "message": "stopped", "ts": time.time()}
        return {
            "running": running,
            "ts":      time.time(),
            "capture": capture if running else stopped_status,
            "detector": detector if running else stopped_status,
            "session": sess_latest if running else stopped_status,
            "vlm":     vlm_status if running else stopped_status,
            "stats":   vlm_stats,
            "history": history[:200],    # 限制最多返回200条历史记录，避免数据量过大
            "staff_rois": sess_latest.get("staff_rois") or self._roi_load(),
        }


# ---------------------------------------------------------------------------
# MJPEG 渲染辅助: 在 frame 上叠加 ROI / 人体框 / 统计 banner
# ---------------------------------------------------------------------------
def _overlay_on_frame(frame, service: "AppService"):
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
        sess_latest = service.store.read("session_latest", {}) or {}
        tracker     = service.store.read("tracker_latest", {}) or {}
        vlm_stats   = service.store.read("vlm_latest_stats", {}) or {}

        # ROI 直接从配置文件读
        rois = service.get_rois_cached()
        per_roi = sess_latest.get("per_roi") or {}
        tracks = tracker.get("tracks") or []

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

        # 1) 画 ROI 框 + 工位名 + 是否处于 session 的 标识
        for idx, (name, roi) in enumerate(sorted(rois.items())):
            if not roi or len(roi) < 4:
                continue
            x1 = int(roi[0] * sx); y1 = int(roi[1] * sy)
            x2 = int(roi[2] * sx); y2 = int(roi[3] * sy)
            color = palette[idx % len(palette)]
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

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
            x1 = int(float(t["x1"]) * sx); y1 = int(float(t["y1"]) * sy)
            x2 = int(float(t["x2"]) * sx); y2 = int(float(t["y2"]) * sy)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"id={t.get('track_id', '-')}",
                        (x1, max(16, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # 3) 顶部统计 banner
        header = (f"total={vlm_stats.get('total', 0)} "
                  f"ok={vlm_stats.get('compliant', 0)} "
                  f"no={vlm_stats.get('non_compliant', 0)} "
                  f"rate={vlm_stats.get('rate', 0)}% "
                  f"queue={vlm_stats.get('queue', 0)}")
        cv2.putText(frame, header, (14, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.66, (255, 240, 120), 2)
    except Exception:
        # 渲染失败不要把整路 MJPEG 流弄崩
        pass
    return frame


# ---------------------------------------------------------------------------
# 创建 FastAPI app
# ---------------------------------------------------------------------------
def create_app(config_path: Path) -> FastAPI:
    """
    工厂函数，创建并配置 FastAPI 应用。
    包含生命周期管理、路由注册、MJPEG 流生成器等。
    """
    service = AppService(config_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        FastAPI 生命周期上下文管理器。
        启动时：拉起所有 worker 子进程
        关闭时：反向终止所有 worker
        """
        # 启动: 拉起所有 worker; 退出: 反向终止
        service.start_workers()
        try:
            yield
        finally:
            service.stop_workers()

    app = FastAPI(title="Security VLM Inspection", lifespan=lifespan)
    # 允许跨域请求，便于前端开发
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
        """前端每 2s 轮询, 拿全量状态（所有 worker + 历史 + 统计）"""
        return JSONResponse(service.get_state())

    @app.get("/api/history")
    async def history(limit: int = 100):
        """仅返回历史记录和统计信息，用于前端展示历史列表"""
        st = service.get_state()
        return JSONResponse({
            "date":  time.strftime("%Y-%m-%d", time.localtime()),
            "stats": st.get("stats", {}),
            "history": st.get("history", [])[:max(1, int(limit))],
        })

    # ---- ROI 接口 ----
    @app.get("/api/rois")
    async def get_rois():
        """获取当前 ROI 配置，供前端画布展示"""
        rois = service._roi_load()
        return JSONResponse({
            "staff_rois":      rois,
            "available_slots": list(rois.keys())
                              or list(service.cfg.get("staff_rois", {}).keys()),
            "video_id":        service.video_id,
        })

    @app.post("/api/rois")
    async def save_rois(req: ROIRequest):
        """前端绘制完 ROI 后调用此接口保存，session_worker 将自动热加载"""
        if not isinstance(req.staff_rois, dict):
            raise HTTPException(status_code=400, detail="staff_rois must be dict")
        service._roi_save(req.staff_rois)
        rois = service._roi_load()
        return JSONResponse({
            "ok": True,
            "staff_rois":      rois,
            "available_slots": list(rois.keys()),
            "video_id":        service.video_id,
        })

    # ---- 检测总开关 ----
    @app.post("/api/control/start")
    async def control_start():
        """开启安检流程规范检测。已开启时幂等，不重复拉起 worker。"""
        service.start_workers()
        return JSONResponse({"success": True, "running": True})

    @app.post("/api/control/stop")
    async def control_stop():
        """关闭安检流程规范检测，终止所有 worker，避免继续产生 VLM 调用费用。"""
        service.stop_workers()
        return JSONResponse({"success": True, "running": False})

    @app.post("/api/control/restart")
    async def control_restart():
        """重启安检流程规范检测。"""
        service.stop_workers()
        service.start_workers()
        return JSONResponse({"success": True, "running": True})

    # ---- MJPEG 流生成器 ----
    async def _mjpeg(kind: str):
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

            hub = service.get_frame_hub()
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
                    frame = _overlay_on_frame(frame, service)

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
                print(f"[mjpeg] {kind} error: {e}", flush=True)
                await asyncio.sleep(0.1)

    @app.get("/video/{kind}")
    async def video(kind: str):
        """
        路由：根据 kind 返回原始或带标注的 MJPEG 视频流。
        """
        if kind not in {"original", "rule"}:
            return JSONResponse({"ok": False, "message": "invalid kind"},
                                status_code=404)
        return StreamingResponse(
            _mjpeg(kind),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    return app


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    """解析命令行参数，加载配置，启动 uvicorn 服务器"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    config_path = (resolve_path(args.config, project_root) if args.config
                   else project_root / "configs" / "config.yaml")
    cfg = load_yaml(config_path)

    import uvicorn
    uvicorn.run(
        create_app(config_path),
        host=str(args.host or cfg["web"]["host"]),
        port=int(args.port or cfg["web"]["port"]),
        reload=False,                 # 生产环境不启用热重载
        access_log=False,             # 关闭访问日志，减少输出噪音
        log_level="warning",          # 仅输出警告及以上级别日志
    )


if __name__ == "__main__":
    main()
