"""
================================================================================
detector_worker.py —— YOLO + ByteTrack 检测/跟踪子进程
================================================================================
职责:
    1. 阻塞等待 FrameHub 就绪
    2. 加载 YOLO 模型 (默认 yolo11s.pt)
    3. 主循环: 从 FrameHub 拉最新帧 → model.track() → 把 tracks 写到
       tracker_latest.json,供 session/web 使用
 
关键设计:
    - 用 ultralytics 内置的 ByteTrack (tracker=bytetrack.yaml),
      不需要自己手写关联,model.track(persist=True) 会自动维护 track_id。
    - 推理本身被 target_infer_fps 限频,避免吃满 GPU 也产生不出更多有效信息。
      (摄像头 25fps,实际推理 8-12fps 已经够 session 判断)
    - 每个新帧只过一次 YOLO,结果写到 tracker_latest.json (覆盖式),
      下游 (session_worker) 用 frame_id 判断「是否新结果」。
 
输出 (写到 ResultStore):
    tracker_latest:
      {
        ok, frame_id, ts, forward_ms, forward_ms_avg,
        track_count, tracks: [{track_id,x1,y1,x2,y2,score}, ...],
        frame_meta: {height,width,channels,slot_idx,frame_id}
      }
    tracker_status:
      {ok, frame_id, fps, forward_ms_avg, track_count, ts}
================================================================================
"""
import argparse
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List
 
import yaml
 
sys.path.insert(0, str(Path(__file__).resolve().parent))
from frame_hub import FrameHubReader, ResultStore, framehub_wait_timeout  # noqa: E402
from ultralytics_compat import yolo_precision_kwargs  # noqa: E402
 
 
# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def set_process_title(title: str) -> None:
    try:
        from setproctitle import setproctitle
        setproctitle(str(title))
    except Exception:
        pass
 
 
def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
 
 
def resolve_path(p: str, base: Path) -> Path:
    pp = Path(p)
    return pp.resolve() if pp.is_absolute() else (base / pp).resolve()
 
 
_STOP = threading.Event()
 
 
def _signal_handler(signum, frame):
    _STOP.set()
 
 
# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------
def main():
    set_process_title("security_vlm[detector]")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=str)
    args = parser.parse_args()
 
    project_root = Path(__file__).resolve().parent.parent
    config_path = resolve_path(args.config, project_root)
    cfg = load_yaml(config_path)
 
    # 公共目录 / 状态存储 -----------------------------------------------
    runtime_dir = Path(cfg["runtime"]["dir"]).resolve()
    store = ResultStore(runtime_dir)
 
    # YOLO 配置 ---------------------------------------------------------
    yolo_cfg = cfg["yolo"]
    result_key = str(yolo_cfg.get("result_key", "tracker_latest"))
    status_key = str(yolo_cfg.get("status_key", "tracker_status"))
 
    # 信号 --------------------------------------------------------------
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
 
    store.write(status_key, {"ok": False, "message": "starting", "ts": time.time()})
 
    # 等 FrameHub (capture_worker) 就绪 ---------------------------------
    print("[detector] 等待 FrameHub 就绪...", flush=True)
    try:
        hub = FrameHubReader(
            runtime_dir,
            wait_timeout_sec=framehub_wait_timeout(cfg),
        )
    except Exception as e:
        store.write(status_key, {"ok": False, "message": f"framehub_timeout: {e}",
                                 "ts": time.time()})
        print(f"[detector] FrameHub 超时: {e}", flush=True)
        return
    print(f"[detector] FrameHub 就绪: {hub.width}x{hub.height}", flush=True)
 
    # 加载 YOLO ---------------------------------------------------------
    print("[detector] 加载 YOLO 模型...", flush=True)
    try:
        from ultralytics import YOLO
        model = YOLO(str(yolo_cfg["model"]))
    except Exception as e:
        store.write(status_key, {"ok": False, "message": f"yolo_load_failed: {e}",
                                 "ts": time.time()})
        print(f"[detector] YOLO 加载失败: {e}", flush=True)
        return
 
    # 推理参数 (从 YAML 读) ---------------------------------------------
    device       = str(yolo_cfg.get("device", "cuda:0"))
    conf         = float(yolo_cfg.get("conf", 0.35))         # 置信度阈值
    iou          = float(yolo_cfg.get("iou", 0.60))          # NMS IoU
    imgsz        = int(yolo_cfg.get("imgsz", 640))           # 输入分辨率
    half         = bool(yolo_cfg.get("half", True))          # FP16 推理
    verbose      = bool(yolo_cfg.get("verbose", False))
    person_cls   = int(yolo_cfg.get("person_class_id", 0))   # COCO 中 person=0
    tracker_yaml = str(yolo_cfg.get("tracker", "bytetrack.yaml"))
    persist      = bool(yolo_cfg.get("persist", True))       # 跨帧保持 track_id
 
    poll_sec = float(cfg.get("workers", {}).get("poll_interval_sec", 0.01))
 
    # 限频: 推理上限不超过 camera_fps_hint (默认 10 fps)
    # 既能匹配 capture 的写入频率,也避免 GPU 跑空转
    target_infer_fps = float(cfg.get("runtime", {}).get("camera_fps_hint", 10.0))
    target_infer_fps = max(1.0, target_infer_fps)
    min_infer_interval = 1.0 / target_infer_fps
 
    # 预热一次 read,避免第一次推理时 memmap 还没就位
    try:
        _ = hub.read_frame()
    except Exception:
        pass
 
    # 运行时统计 --------------------------------------------------------
    last_frame_id = -1
    last_status_ts = 0.0
    fps_counter = 0
    fps_window_start = time.time()
    forward_ms_avg = 0.0     # 推理耗时滑动平均 (用于性能监控)
    last_infer_ts = 0.0
 
    store.write(status_key, {"ok": True, "message": "running", "ts": time.time()})
    print("[detector] 进入主循环", flush=True)
 
    try:
        while not _STOP.is_set():
            # 1) 看 FrameHub 是否有新帧 -----------------------------------
            meta = hub.get_latest_meta()
            frame_id = int(meta.get("frame_id", -1))
            if frame_id < 0 or frame_id == last_frame_id:
                time.sleep(poll_sec)
                continue
 
            # 2) 限频: 距离上次推理不到 1/target_infer_fps 秒 → 跳过 ------
            now = time.time()
            if now - last_infer_ts < min_infer_interval:
                # 标记当前帧已"看过",避免下次循环又判它是新帧
                last_frame_id = frame_id
                time.sleep(0.001)
                continue
 
            # 3) 拉帧 ----------------------------------------------------
            try:
                frame = hub.read_frame(meta)
            except Exception as e:
                print(f"[detector] 读帧失败: {e}", flush=True)
                time.sleep(0.05)
                continue
 
            # 4) YOLO + ByteTrack 推理 -----------------------------------
            t0 = time.time()
            try:
                results = model.track(
                    frame,
                    persist=persist,        # 跨帧保持 track_id
                    classes=[person_cls],   # 只跟踪 person
                    conf=conf,
                    iou=iou,
                    imgsz=imgsz,
                    device=device,
                    tracker=tracker_yaml,
                    verbose=verbose,
                    **yolo_precision_kwargs(half),
                )
            except Exception as e:
                print(f"[detector] YOLO 推理失败: {e}", flush=True)
                store.write(status_key, {"ok": False, "message": f"infer_failed: {e}",
                                         "ts": time.time()})
                time.sleep(0.2)
                continue
            forward_ms = (time.time() - t0) * 1000.0
            # EMA 平滑: new = 0.8*old + 0.2*current
            forward_ms_avg = (0.8 * forward_ms_avg + 0.2 * forward_ms
                              if forward_ms_avg > 0 else forward_ms)
 
            # 5) 把 results 转成纯 dict (方便 JSON 序列化) ---------------
            tracks: List[Dict[str, Any]] = []
            if results and results[0].boxes is not None:
                boxes = results[0].boxes
                xyxy   = boxes.xyxy.cpu().numpy() if boxes.xyxy is not None else []
                ids    = boxes.id.cpu().numpy()   if boxes.id   is not None else None
                scores = boxes.conf.cpu().numpy() if boxes.conf is not None else None
                for i, bx in enumerate(xyxy):
                    x1, y1, x2, y2 = [float(v) for v in bx[:4]]
                    # ByteTrack 偶尔不分配 id (新出现且未 confirm),用负数兜底
                    tid = int(ids[i]) if ids is not None else -(i + 1)
                    sc = float(scores[i]) if scores is not None else 0.0
                    tracks.append({
                        "track_id": tid,
                        "x1": round(x1, 2), "y1": round(y1, 2),
                        "x2": round(x2, 2), "y2": round(y2, 2),
                        "score": round(sc, 4),
                    })
 
            # 6) 写最新结果 ----------------------------------------------
            payload = {
                "ok": True,
                "frame_id": frame_id,
                "ts": time.time(),
                "forward_ms": round(forward_ms, 2),
                "forward_ms_avg": round(forward_ms_avg, 2),
                "track_count": len(tracks),
                "tracks": tracks,
                # frame_meta 一并带上,session_worker 可据此 read_frame
                "frame_meta": {
                    "height":   int(meta["height"]),
                    "width":    int(meta["width"]),
                    "channels": int(meta["channels"]),
                    "slot_idx": int(meta["slot_idx"]),
                    "frame_id": frame_id,
                },
            }
            store.write(result_key, payload)
            last_frame_id = frame_id
            last_infer_ts = time.time()
            fps_counter += 1
 
            # 7) 每 2 秒一次心跳 (fps + 平均推理耗时) ---------------------
            now = time.time()
            if now - fps_window_start >= 2.0:
                fps = fps_counter / (now - fps_window_start)
                fps_counter = 0
                fps_window_start = now
                if now - last_status_ts > 2.0:
                    store.write(status_key, {
                        "ok": True, "frame_id": frame_id,
                        "fps": round(fps, 2),
                        "forward_ms_avg": round(forward_ms_avg, 2),
                        "track_count": len(tracks),
                        "ts": now,
                    })
                    last_status_ts = now
 
    except Exception as e:
        print(f"[detector] 主循环异常: {e}", flush=True)
        store.write(status_key, {"ok": False, "message": str(e), "ts": time.time()})
    finally:
        print("[detector] 退出", flush=True)
        store.write(status_key, {"ok": False, "message": "stopped", "ts": time.time()})
 
 
if __name__ == "__main__":
    main()
