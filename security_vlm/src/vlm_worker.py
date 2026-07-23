"""
================================================================================
vlm_worker.py —— Qwen-VL 合规判定子进程
================================================================================
职责:
    1. 启动时清理 pending_queue_dir 里残留的过期 .pkl
    2. 后台 PendingScanner 线程持续扫描该目录, 把新出现的 .pkl 路径丢进队列
    3. N 个 worker 线程并发处理: 取出 .pkl → 调 Qwen-VL → 解析 → 落盘
    4. 不合规会额外保存关键帧拼图到 clips_dir
    5. 维护一个内存 history (deque) + 累计计数, 写到 vlm_history.json /
       vlm_latest_stats.json 供前端读

成本守护:
    BudgetGuard 按"次"扣预算 (estimated_cost_per_call), 超过 daily_limit 拒调。
    日期变更时自动归零。

输出:
    - {results_dir}/<session_id>.json     (每个 session 一个详细结果)
    - {clips_dir}/<session_id>.jpg        (不合规的关键帧拼图)
    - vlm_status.json / vlm_latest_stats.json / vlm_history.json
================================================================================
"""
import argparse
import json
import os
import pickle
import queue
import signal
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from PIL import Image, ImageDraw, ImageFont

import cv2
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frame_hub import ResultStore  # noqa: E402


# ---------------------------------------------------------------------------
# 通用工具
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
# 预算守护
# ---------------------------------------------------------------------------
class BudgetGuard:
    """
    按"次数 * 单价"估算每日开销, 超出 daily_limit 拒绝调用。
    跨天自动重置 (检查日期字符串)。
    线程安全 (内部用 lock)。
    """

    def __init__(self, daily_limit: float, est_cost_per_call: float):
        self.daily_limit = float(daily_limit)
        self.est_cost = float(est_cost_per_call)
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.spent = 0.0
        self.call_count = 0
        self.lock = threading.Lock()

    def try_consume(self) -> bool:
        """成功扣费 → True; 超预算 → False (调用方应放弃本次调用)"""
        with self.lock:
            today = datetime.now().strftime("%Y-%m-%d")
            if today != self.date:
                # 跨天重置
                self.date = today
                self.spent = 0.0
                self.call_count = 0
            if self.spent + self.est_cost > self.daily_limit:
                return False
            self.spent += self.est_cost
            self.call_count += 1
            return True

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "date": self.date,
                "call_count": self.call_count,
                "spent_yuan": round(self.spent, 2),
                "daily_limit_yuan": self.daily_limit,
            }


# ---------------------------------------------------------------------------
# Prompt (System / User)
# ---------------------------------------------------------------------------
VLM_SYSTEM_PROMPT = """你是安检合规审核员,负责审核厂区安检工位的监控录像截图。

# 你看到的是什么
按时间顺序排列的若干张监控截图,采样自同一段安检过程,时间跨度 5-30 秒。
画面中通常有 1 名安检员(穿制服或反光背心)和 1 名被检人。

# 重要前提:监控视角的局限
你看到的是远距离监控,分辨率有限,动作细节模糊。这是正常的——
即使你看不清安检员的手具体放在哪里、做什么动作,只要场景**整体看起来像在进行安检**,
就应该认为安检在正常进行。

# 你的判定任务
**只判定一件事:这段画面是否显示"安检流程正在进行"。**

不需要判定上身/腰/腿是否每段都检查完,因为:
- 这是采样画面,不是完整录像,某些动作可能在采样间隔之间发生
- 监控视角无法看清每个动作细节
- 真实安检中安检员并不一定每次都做完三段

# 合规的判断特征(满足任一即可判合规)
- 安检员靠近被检人,且双方姿态显示存在互动(不是各自站着)
- 安检员的手臂/身体处于检查姿态(伸手、弯腰、蹲下、手持探测器等)
- 被检人配合姿态(张开双臂、抬手、转身、保持站立不动让对方检查)
- 多张图中安检员相对于被检人的位置/姿态有变化(说明在移动检查)

# 不合规的判断特征(必须明确看到才判不合规)
- 画面中只有一个人(完全没有安检对)
- 两人都在做和安检无关的事(明显在交谈、看手机、玩闹等)
- 两人各自站着,全程没有任何互动迹象(整组图都没有任何动作)
- 安检员明显离开了岗位,被检人独自通过
- 两人距离过远,完全没有接近过

# 判定原则(非常重要,请严格遵守)
1. **善意默认**: 如果不确定,判合规。监控质量差不是判不合规的理由。
2. **整体观感优先**: 不要纠结单帧细节,看整体动态。
3. **不要追求"看清动作"**: 看不清不等于没发生。
4. **只在明确证据下判不合规**: 必须能在 reason 里清楚说出"我看到了 XXX,所以不是在做安检"。
5. **关注被检人姿态**: 被检人若有张臂、抬手、配合站立的姿态,几乎可以确定是在被检查。

# 输出 JSON

{
  "scene_summary": "整组画面的客观描述,3-5 句话,描述两人的位置、姿态、动作变化",
  "staff_visible": true 或 false,
  "passenger_visible": true 或 false,
  "interaction_observed": true 或 false,
  "passenger_cooperation_posture": true 或 false,
  "non_compliance_evidence": "如果判不合规,必须在这里写清楚明确的证据;如果判合规,填 null",
  "reason": "综合分析,2-3 句",
  "compliant": true 或 false,
  "confidence": 0.0 到 1.0
}

# 机械判定规则(不要主观放宽或收紧)
- 如果 staff_visible 和 passenger_visible 任一为 false → compliant = false
- 如果 non_compliance_evidence 不为 null → compliant = false
- 否则 compliant = true (默认合规)
"""

VLM_USER_PROMPT = """以下是某安检工位的 {n_frames} 张监控截图,按时间顺序排列。

请判定这段过程是否显示"安检在正常进行"。

记住:
- 监控看不清细节是正常的,不要因此判不合规
- 默认倾向合规,除非看到明确的违规证据
- 严格按 JSON 格式输出,不要 markdown 包裹
"""

# ---------------------------------------------------------------------------
# VLM 调用封装
# ---------------------------------------------------------------------------
class VLMJudge:
    """
    封装 dashscope 多模态调用:
    1) 把每张关键帧 resize + 写到临时 jpg
    2) 拼成 messages, 调 MultiModalConversation.call
    3) 解析返回的 JSON (兼容 markdown 包裹)
    4) try-finally 删临时 jpg, 不留垃圾
    """

    def __init__(self, cfg: Dict[str, Any], budget: BudgetGuard, tmp_dir: Path):
        import dashscope
        from dashscope import MultiModalConversation

        self.dashscope = dashscope
        self.MMC = MultiModalConversation
        self.api_key = cfg["vlm"]["api_key"]
        self.model = cfg["vlm"]["model"]
        self.image_max_side = int(cfg["vlm"].get("image_max_side", 960))
        self.image_quality = int(cfg["vlm"].get("image_jpeg_quality", 85))
        self.api_timeout = float(cfg["vlm"].get("api_timeout_sec", 45))
        self.budget = budget
        self.tmp_dir = Path(tmp_dir)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        dashscope.api_key = self.api_key

    def _save_frame(self, frame: np.ndarray, session_id: str, idx: int) -> str:
        """临时 jpg, dashscope 用 file:// 协议读"""
        path = self.tmp_dir / f"{session_id}_{idx}.jpg"
        h, w = frame.shape[:2]
        if max(h, w) > self.image_max_side:
            s = self.image_max_side / max(h, w)
            frame = cv2.resize(frame, (int(w * s), int(h * s)))
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, self.image_quality])
        return str(path.absolute())

    def judge(
        self,
        session_id: str,
        roi_name: str,
        roi_box: List[float],
        keyframes: List[np.ndarray],
    ) -> Dict[str, Any]:
        """
        返回 dict:
            成功: {staff_description,..., compliant, confidence, reason, _latency_sec, _usage}
            失败: {error: "...", _latency_sec?: ...}
        """
        if not keyframes:
            return {"error": "no_keyframes"}
        if not self.budget.try_consume():
            return {"error": "budget_exceeded"}

        paths: List[str] = []
        try:
            # 1) 关键帧 → 临时 jpg
            for i, fr in enumerate(keyframes):
                paths.append(self._save_frame(fr, session_id, i))

            # 2) 组装 messages: 多张图 + 一段 prompt
            user_content = [{"image": f"file://{p}"} for p in paths]
            user_content.append({
                "text": VLM_USER_PROMPT.format(
                    n_frames=len(paths),
                    roi_name=roi_name,
                    roi_box=roi_box,
                )
            })
            messages = [
                {"role": "system", "content": [{"text": VLM_SYSTEM_PROMPT}]},
                {"role": "user",   "content": user_content},
            ]

            # 3) 调 API; DashScope 使用 request_timeout 控制 HTTP 请求总超时
            t0 = time.time()
            response = self.MMC.call(
                model=self.model,
                messages=messages,
                request_timeout=self.api_timeout,
            )
            latency = time.time() - t0

            if response.status_code != 200:
                return {"error": f"api_error: {response.code} {response.message}",
                        "_latency_sec": round(latency, 2)}

            # 4) 提取文本 (Qwen 有时返回 list[dict], 有时直接字符串)
            content = response.output.choices[0].message.content
            text = ""
            if isinstance(content, list):
                for it in content:
                    if isinstance(it, dict) and "text" in it:
                        text += it["text"]
            else:
                text = str(content)

            result = self._parse_json(text)
            if result is None:
                return {"error": "parse_failed", "raw_text": text[:500],
                        "_latency_sec": round(latency, 2)}

            result["_latency_sec"] = round(latency, 2)
            if getattr(response, "usage", None):
                result["_usage"] = {
                    "input_tokens":  response.usage.get("input_tokens", 0),
                    "output_tokens": response.usage.get("output_tokens", 0),
                }
            return result

        except Exception as e:
            return {"error": f"exception: {e}"}
        finally:
            # 删除临时 jpg
            for p in paths:
                try:
                    os.remove(p)
                except Exception:
                    pass

    @staticmethod
    def _parse_json(text: str) -> Optional[Dict[str, Any]]:
        """
        尽力解析模型返回的 JSON:
        - 去掉 ```json ... ``` markdown 包裹
        - 直接 json.loads, 失败则截取首个 {...} 段再 loads
        """
        t = text.strip()
        if t.startswith("```"):
            parts = t.split("```")
            if len(parts) >= 2:
                t = parts[1]
                if t.lstrip().startswith("json"):
                    t = t.lstrip()[4:]
        t = t.strip()
        try:
            return json.loads(t)
        except Exception:
            pass
        try:
            s = t.index("{")
            e = t.rindex("}") + 1
            return json.loads(t[s:e])
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Pending 目录扫描线程
# ---------------------------------------------------------------------------
class PendingScanner(threading.Thread):
    """
    后台线程: 周期 glob pending_queue_dir/*.pkl, 把新文件丢进 task_q。
    用 self.seen 集合去重, 避免重复入队。
    """

    def __init__(self, pending_dir: Path, q: queue.Queue, poll_sec: float = 0.5):
        super().__init__(daemon=True)
        self.pending_dir = pending_dir
        self.q = q
        self.poll_sec = poll_sec
        self.seen: set = set()
        self._stop = False

    def run(self):
        while not self._stop:
            try:
                for p in sorted(self.pending_dir.glob("*.pkl")):
                    if p.name in self.seen:
                        continue
                    self.seen.add(p.name)
                    self.q.put(p)
            except Exception as e:
                print(f"[vlm-scan] 扫描异常: {e}", flush=True)
            time.sleep(self.poll_sec)

    def stop(self):
        self._stop = True


# ---------------------------------------------------------------------------
# 关键帧拼图 (横向 N 张 + 顶部状态 banner)
# ---------------------------------------------------------------------------
def _draw_text_pil(img_bgr, text, xy, font_size=24, color=(255, 255, 255)):
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    draw = ImageDraw.Draw(pil_img)

    font_path = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
    if font_path:
        font = ImageFont.truetype(font_path, font_size)
    else:
        font = ImageFont.load_default()

    # OpenCV 是 BGR，这里转成 RGB
    rgb_color = (color[2], color[1], color[0])
    draw.text(xy, str(text), font=font, fill=rgb_color)

    out = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    return out


def save_clip(keyframes: List[np.ndarray], result: Dict[str, Any],
              session_id: str, out_dir: Path):
    if not keyframes:
        return

    target_w = 480
    frames = []
    for f in keyframes:
        h, w = f.shape[:2]
        s = target_w / w
        frames.append(cv2.resize(f, (target_w, int(h * s))))

    max_h = max(f.shape[0] for f in frames)
    padded = []
    for f in frames:
        if f.shape[0] < max_h:
            pad = np.zeros((max_h - f.shape[0], f.shape[1], 3), dtype=np.uint8)
            f = np.vstack([f, pad])
        padded.append(f)
    grid = np.hstack(padded)

    # banner 高一点，给中文两行空间
    banner_h = 90
    banner = np.zeros((banner_h, grid.shape[1], 3), dtype=np.uint8)

    st = "NON_COMPLIANT"
    color = (0, 0, 255)
    if "error" in result:
        st = f"ERROR:{result['error'][:40]}"
        color = (0, 200, 200)

    title = f"{session_id}  [{st}]"
    reason = str(result.get("reason", "") or "")

    banner = _draw_text_pil(banner, title, (10, 8), font_size=28, color=color)
    banner = _draw_text_pil(banner, reason[:120], (10, 42), font_size=24, color=(255, 255, 255))

    out = np.vstack([banner, grid])
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / f"{session_id}.jpg"), out,
                [cv2.IMWRITE_JPEG_QUALITY, 85])

# ---------------------------------------------------------------------------
# 启动时清理过期 / 残留任务
# ---------------------------------------------------------------------------
def cleanup_stale_pending(pending_dir: Path, now_ts: float, queue_timeout: float):
    """
    上次进程崩溃 / 重启时, pending 目录可能残留大量 pkl。
    规则: 比启动早 1 秒以前的, 或排队时间已超 queue_timeout 的, 一律删。
    """
    removed = 0
    for p in pending_dir.glob("*.pkl"):
        try:
            with open(p, "rb") as f:
                payload = pickle.load(f)
            enq_ts = float(payload.get("enqueue_ts", p.stat().st_mtime))
            if enq_ts < now_ts - 1.0 or (now_ts - enq_ts) > queue_timeout:
                p.unlink(missing_ok=True)
                removed += 1
        except Exception:
            try:
                p.unlink(missing_ok=True)
                removed += 1
            except Exception:
                pass
    if removed > 0:
        print(f"[vlm] 启动时清理旧 pending 任务 {removed} 个", flush=True)


def process_queued_item(task_q: queue.Queue, process_one, item=None) -> None:
    """处理一个已入队任务,隔离异常并确保队列完成计数正确。"""
    queued_item = task_q.get() if item is None else item
    try:
        process_one(Path(queued_item))
    except Exception:
        print(f"[vlm] worker 任务异常: {queued_item}", file=sys.stderr, flush=True)
        traceback.print_exc()
    finally:
        task_q.task_done()


# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------
def main():
    set_process_title("security_vlm[vlm]")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=str)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    config_path = resolve_path(args.config, project_root)
    cfg = load_yaml(config_path)

    runtime_dir = Path(cfg["runtime"]["dir"]).resolve()
    store = ResultStore(runtime_dir)

    vlm_cfg = cfg["vlm"]
    out_cfg = cfg["output"]
    status_key      = str(vlm_cfg.get("status_key", "vlm_status"))
    queue_timeout   = float(vlm_cfg.get("queue_timeout_sec", 60))
    max_concurrent  = int(vlm_cfg.get("max_concurrent", 3))

    results_dir = resolve_path(out_cfg["results_dir"], project_root)
    clips_dir   = resolve_path(out_cfg["clips_dir"], project_root)
    save_only_non = bool(out_cfg.get("save_clip_only_non_compliant", True))
    max_history   = int(out_cfg.get("max_history_items", 300))
    results_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    pending_dir = Path(cfg["session"].get(
        "pending_queue_dir", str(runtime_dir / "session_pending"))).resolve()
    pending_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = runtime_dir / "vlm_tmp"

    # 启动清理上一次残留 pkl
    startup_ts = time.time()
    cleanup_stale_pending(pending_dir, startup_ts, queue_timeout)

    budget = BudgetGuard(
        daily_limit=float(cfg["budget"]["daily_limit_yuan"]),
        est_cost_per_call=float(cfg["budget"]["estimated_cost_per_call"]),
    )
    judge = VLMJudge(cfg, budget, tmp_dir)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # 任务队列 + 扫描线程
    task_q: queue.Queue = queue.Queue()
    scanner = PendingScanner(pending_dir, task_q, poll_sec=0.5)
    scanner.start()

    # 历史 + 计数 (内存)
    history: deque = deque(maxlen=max_history)
    counts = {"compliant": 0, "non_compliant": 0, "error": 0}
    counts_lock = threading.Lock()

    def write_stats_and_history():
        """把累计统计 + 历史写到磁盘, 供 web 读取"""
        total = counts["compliant"] + counts["non_compliant"]
        rate = round((counts["compliant"] / total) * 100.0, 2) if total > 0 else 0.0
        store.write("vlm_latest_stats", {
            "ts": time.time(),
            "total": total,
            "compliant":     counts["compliant"],
            "non_compliant": counts["non_compliant"],
            "error":         counts["error"],
            "rate":  rate,
            "queue": task_q.qsize(),
            "budget": budget.snapshot(),
        })
        store.write("vlm_history", {"items": list(history)})

    # ---- 单个任务的处理流程 ----
    def process_one(pkl_path: Path):
        # 1) 读 pickle
        try:
            with open(pkl_path, "rb") as f:
                payload = pickle.load(f)
        except Exception as e:
            print(f"[vlm] 读 pickle 失败 {pkl_path}: {e}", flush=True)
            try:
                pkl_path.unlink()
            except Exception:
                pass
            return

        session_id = str(payload["session_id"])
        roi_name   = str(payload.get("roi_name", ""))
        roi_box    = payload.get("roi_box") or []
        enq_ts     = float(payload.get("enqueue_ts", time.time()))
        keyframes  = payload.get("keyframes") or []

        # 2) 排队过久直接丢
        waited = time.time() - enq_ts
        if waited > queue_timeout:
            print(f"[vlm] 丢弃过期任务 {session_id} waited={waited:.1f}s", flush=True)
            try:
                pkl_path.unlink()
            except Exception:
                pass
            return

        # 3) 调 VLM
        print(f"[vlm] 开始判定 {session_id} (等待 {waited:.1f}s, "
              f"{len(keyframes)} 帧)", flush=True)
        result = judge.judge(session_id, roi_name, roi_box, keyframes)

        # 4) 累计计数
        with counts_lock:
            if "error" in result:
                counts["error"] += 1
            elif result.get("compliant"):
                counts["compliant"] += 1
            else:
                counts["non_compliant"] += 1

        # 5) 控制台日志
        if "error" in result:
            print(f"[vlm] ❌ {session_id} ERROR: {result['error']}", flush=True)
        else:
            tag = "✅合规" if result.get("compliant") else "❌不合规"
            print(f"[vlm] {tag} {session_id}  "
                  f"U={result.get('upper_checked')} M={result.get('middle_checked')} "
                  f"L={result.get('lower_checked')} A={result.get('arms_open')} "
                  f"conf={result.get('confidence')} lat={result.get('_latency_sec')}s",
                  flush=True)

        # 6) 写 results/<session_id>.json
        duration = float(payload.get("end_ts", time.time())) \
                 - float(payload.get("start_ts", time.time()))
        record = {
            "session_id": session_id,
            "roi_name":   roi_name,
            "start_ts":   payload.get("start_ts"),
            "end_ts":     payload.get("end_ts"),
            "duration_sec": round(duration, 2),
            "n_keyframes":  len(keyframes),
            "result":     result,
            "judged_ts":  time.time(),
            "time": datetime.fromtimestamp(
                payload.get("end_ts", time.time())
            ).strftime("%Y-%m-%d %H:%M:%S"),
        }
        (results_dir / f"{session_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

        # 7) 不合规保存关键帧拼图
        if "error" not in result:
            if not result.get("compliant") and save_only_non:
                save_clip(keyframes, result, session_id, clips_dir)
            elif not save_only_non:
                save_clip(keyframes, result, session_id, clips_dir)

        # 8) 写历史 (deque, 头插, 最新在前)
        history.appendleft({
            "time":       record["time"],
            "session_id": session_id,
            "roi_name":   roi_name,
            "duration_sec": record["duration_sec"],
            "status": ("compliant" if result.get("compliant")
                       else ("error" if "error" in result else "non_compliant")),
            "upper_checked":  result.get("upper_checked"),
            "middle_checked": result.get("middle_checked"),
            "lower_checked":  result.get("lower_checked"),
            "arms_open":      result.get("arms_open"),
            "reason": result.get("reason", ""),
            "error":  result.get("error"),
        })
        write_stats_and_history()

        # 9) 删除 pickle
        try:
            pkl_path.unlink()
        except Exception:
            pass

    # ---- worker 池 ----
    def worker_loop():
        while not _STOP.is_set():
            try:
                p = task_q.get(timeout=0.5)
            except queue.Empty:
                continue
            process_queued_item(task_q, process_one, p)

    threads = []
    for _ in range(max_concurrent):
        t = threading.Thread(target=worker_loop, daemon=True)
        t.start()
        threads.append(t)

    store.write(status_key, {"ok": True, "message": "running", "ts": time.time()})
    write_stats_and_history()
    print(f"[vlm] 就绪, 并发 {max_concurrent}, 开始监听 {pending_dir}", flush=True)

    # 主线程: 周期心跳 (queue size 在变, 顺便刷新 stats)
    try:
        while not _STOP.is_set():
            write_stats_and_history()
            store.write(status_key, {
                "ok": True, "ts": time.time(),
                "queue":  task_q.qsize(),
                "budget": budget.snapshot(),
            })
            time.sleep(2.0)
    except Exception as e:
        print(f"[vlm] 主循环异常: {e}", flush=True)
        store.write(status_key, {"ok": False, "message": str(e), "ts": time.time()})
    finally:
        # 退出前等队列清空 (最多 120s, 避免 session 数据丢失)
        print("[vlm] 退出中, 等待队列清空...", flush=True)
        scanner.stop()
        t0 = time.time()
        while not task_q.empty() and time.time() - t0 < 120:
            time.sleep(0.5)
        store.write(status_key, {"ok": False, "message": "stopped", "ts": time.time()})


if __name__ == "__main__":
    main()
