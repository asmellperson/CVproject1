# 文件说明：实现后台任务相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
================================================================================
vlm_worker.py —— Qwen-VL 合规判定子进程
================================================================================
职责:
    1. 按事业部、摄像头公平扫描 pending，并原子认领到 processing
    2. N 个 worker 线程并发处理 PendingTask，校验路径与 payload 复合身份
    3. 调 Qwen-VL、解析结果，并写入对应事业部的持久结果分区
    4. 不合规关键帧、历史、统计和状态均按事业部隔离

成本守护:
    BudgetGuard 按"次"扣预算 (estimated_cost_per_call), 超过 daily_limit 拒调。
    日期变更时自动归零，预算状态保存在 data_root/_shared。

输出:
    - {data_root}/{department}/results/{camera_id}/{session_id}.json
    - {data_root}/{department}/results/clips/{camera_id}/{session_id}.jpg
    - {data_root}/{department}/results/vlm_state.json
    - {data_root}/{department}/results/vlm_status.json
    - {data_root}/{department}/results/vlm_latest_stats.json
    - {data_root}/{department}/results/vlm_history.json
    - {data_root}/_shared/vlm_budget.json
================================================================================
"""
import argparse
import base64
import json
import math
import os
import pickle
import queue
import signal
import sys
import threading
import time
import traceback
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit
from PIL import Image, ImageDraw, ImageFont

import cv2
import numpy as np
import requests
import yaml

from AiVision.integrations.security_vlm.src.departments import DEPARTMENTS, require_department
from AiVision.integrations.security_vlm.src.camera_registry import validate_camera_id
from AiVision.integrations.security_vlm.src.frame_hub import ResultStore


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


@dataclass(frozen=True)
class VLMWorkerPaths:
    runtime_dir: Path
    departments_root: Path
    data_root: Path

    @classmethod
    def from_config(
        cls,
        cfg: dict,
        project_root: Path,
        *,
        departments_root: str | Path | None = None,
    ) -> "VLMWorkerPaths":
        base = Path(project_root)
        runtime_cfg = cfg.get("runtime", {}) or {}
        departments_cfg = cfg.get("departments", {}) or {}
        runtime_dir = resolve_path(runtime_cfg["dir"], base)
        configured_departments = (
            departments_root
            if departments_root is not None
            else departments_cfg.get(
                "runtime_root",
                runtime_dir / "departments",
            )
        )
        return cls(
            runtime_dir=runtime_dir,
            departments_root=resolve_path(str(configured_departments), base),
            data_root=resolve_path(
                str(departments_cfg.get("data_root", "data/departments")),
                base,
            ),
        )


@dataclass(frozen=True)
class PendingTask:
    """已由目录结构认证的待处理任务身份。"""

    department: str
    camera_id: str
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "department", require_department(self.department))
        object.__setattr__(self, "camera_id", validate_camera_id(self.camera_id))
        object.__setattr__(self, "path", Path(self.path))


class DepartmentFairTaskQueue:
    """在 worker 取任务时按事业部、摄像头两级轮询的线程安全队列。"""

    def __init__(self) -> None:
        self.maxsize = 0
        self._condition = threading.Condition()
        self._queues: dict[str, dict[str, deque]] = {
            department: {} for department in DEPARTMENTS
        }
        self._camera_order: dict[str, list[str]] = {
            department: [] for department in DEPARTMENTS
        }
        self._last_camera: dict[str, str | None] = {
            department: None for department in DEPARTMENTS
        }
        self._department_cursor = 0
        self._qsize = 0
        self._unfinished_tasks = 0

    def put(
        self,
        item: PendingTask,
        block: bool = True,
        timeout: float | None = None,
    ) -> None:
        del block, timeout
        if not isinstance(item, PendingTask):
            raise TypeError("DepartmentFairTaskQueue 只接受 PendingTask")
        with self._condition:
            department_queues = self._queues[item.department]
            camera_queue = department_queues.get(item.camera_id)
            if camera_queue is None:
                camera_queue = deque()
                department_queues[item.camera_id] = camera_queue
                self._camera_order[item.department].append(item.camera_id)
            camera_queue.append(item)
            self._qsize += 1
            self._unfinished_tasks += 1
            self._condition.notify()

    def put_nowait(self, item: PendingTask) -> None:
        self.put(item, block=False)

    def get(
        self,
        block: bool = True,
        timeout: float | None = None,
    ) -> PendingTask:
        if timeout is not None and timeout < 0:
            raise ValueError("'timeout' must be a non-negative number")
        deadline = (
            None if timeout is None else time.monotonic() + float(timeout)
        )
        with self._condition:
            while self._qsize == 0:
                if not block:
                    raise queue.Empty
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                self._condition.wait(remaining)
            department = self._select_department()
            camera_id = self._select_camera(department)
            item = self._queues[department][camera_id].popleft()
            self._last_camera[department] = camera_id
            self._qsize -= 1
            return item

    def get_nowait(self) -> PendingTask:
        return self.get(block=False)

    def _select_department(self) -> str:
        department_count = len(DEPARTMENTS)
        for offset in range(department_count):
            index = (self._department_cursor + offset) % department_count
            department = DEPARTMENTS[index]
            if any(self._queues[department].values()):
                self._department_cursor = (index + 1) % department_count
                return department
        raise queue.Empty

    def _select_camera(self, department: str) -> str:
        order = self._camera_order[department]
        last_camera = self._last_camera[department]
        start = (
            (order.index(last_camera) + 1) % len(order)
            if last_camera in order
            else 0
        )
        for offset in range(len(order)):
            camera_id = order[(start + offset) % len(order)]
            if self._queues[department][camera_id]:
                return camera_id
        raise queue.Empty

    def task_done(self) -> None:
        with self._condition:
            if self._unfinished_tasks <= 0:
                raise ValueError("task_done() called too many times")
            self._unfinished_tasks -= 1
            if self._unfinished_tasks == 0:
                self._condition.notify_all()

    def join(self) -> None:
        with self._condition:
            while self._unfinished_tasks:
                self._condition.wait()

    @property
    def unfinished_tasks(self) -> int:
        with self._condition:
            return self._unfinished_tasks

    def qsize(self) -> int:
        with self._condition:
            return self._qsize

    def empty(self) -> bool:
        return self.qsize() == 0

    def full(self) -> bool:
        return False

    def has_queued(self, department: str, camera_id: str) -> bool:
        department = require_department(department)
        camera_id = validate_camera_id(camera_id)
        with self._condition:
            return bool(self._queues[department].get(camera_id))

    def department_counts(self) -> dict[str, int]:
        with self._condition:
            return {
                department: sum(
                    len(camera_queue)
                    for camera_queue in department_queues.values()
                )
                for department, department_queues in self._queues.items()
            }


def discard_invalid_pending_task(
    task_path: Path | PendingTask,
    reason: Exception,
) -> None:
    """删除无法安全归属的任务及恢复标记，避免重启后无限重试。"""
    path = task_path.path if isinstance(task_path, PendingTask) else Path(task_path)
    print(
        f"[vlm] 拒绝无效 pending 任务 {path}: {reason}",
        file=sys.stderr,
        flush=True,
    )
    for target in (
        path,
        path.with_suffix(f"{path.suffix}.started"),
        path.with_suffix(f"{path.suffix}.recovered"),
    ):
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            print(
                f"[vlm] 清理无效任务失败 {target}: {exc}",
                file=sys.stderr,
                flush=True,
            )


def _finite_pending_timestamp(
    payload: dict,
    field_name: str,
    default: float,
) -> float:
    raw_value = payload.get(field_name, default)
    if isinstance(raw_value, bool):
        raise TypeError(f"pending payload {field_name} 必须是有限数字")
    try:
        value = float(raw_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"pending payload {field_name} 无法转换为数字"
        ) from exc
    if not math.isfinite(value):
        raise ValueError(f"pending payload {field_name} 必须是有限数字")
    try:
        datetime.fromtimestamp(value)
    except (OSError, OverflowError, ValueError) as exc:
        raise ValueError(
            f"pending payload {field_name} 超出时间戳范围"
        ) from exc
    return value


def _safe_pending_identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"pending payload 缺少有效 {field_name}")
    identifier = value.strip()
    if (
        len(identifier) > 192
        or identifier in {".", ".."}
        or Path(identifier).name != identifier
        or any(
            character == "\x00"
            or ord(character) < 32
            or ord(character) == 127
            for character in identifier
        )
        or any(
            not (
                character.isascii()
                and (
                    character.isalnum()
                    or character in "._-"
                )
            )
            for character in identifier
        )
    ):
        raise ValueError(
            f"pending payload {field_name} 必须是最多 192 字符的路径安全标识"
        )
    return identifier


def normalize_pending_payload(
    payload: dict,
    task_path: PendingTask,
    *,
    now_ts: float | None = None,
) -> dict:
    """校验并规范化 process_one 后续会使用的 pending 字段。"""
    if not isinstance(task_path, PendingTask):
        raise TypeError("pending 任务必须携带已验证的事业部和摄像头身份")
    if not isinstance(payload, dict):
        raise ValueError("pending payload 必须是字典")
    department = require_department(payload.get("department"))
    if department != task_path.department:
        raise ValueError("pending payload department 与来源路径不一致")
    if "session_id" not in payload:
        raise ValueError("pending payload 缺少 session_id")
    current_ts = time.time() if now_ts is None else float(now_ts)
    normalized = dict(payload)
    normalized["department"] = department
    normalized["session_id"] = _safe_pending_identifier(
        payload["session_id"],
        "session_id",
    )
    declared_camera_id = validate_camera_id(payload.get("camera_id"))
    if declared_camera_id != task_path.camera_id:
        raise ValueError("pending payload camera_id 与来源路径不一致")
    normalized["camera_id"] = declared_camera_id
    normalized["camera_name"] = str(
        payload.get("camera_name", normalized["camera_id"])
    )
    normalized["roi_name"] = str(payload.get("roi_name", ""))

    roi_box = payload.get("roi_box")
    if roi_box is None:
        normalized["roi_box"] = []
    elif isinstance(roi_box, (list, tuple)):
        normalized["roi_box"] = list(roi_box)
    else:
        raise TypeError("pending payload roi_box 必须是列表")

    keyframes = payload.get("keyframes")
    if keyframes is None:
        normalized["keyframes"] = []
    elif isinstance(keyframes, (list, tuple)):
        normalized["keyframes"] = list(keyframes)
    else:
        raise TypeError("pending payload keyframes 必须是列表")

    normalized["enqueue_ts"] = _finite_pending_timestamp(
        payload,
        "enqueue_ts",
        current_ts,
    )
    normalized["start_ts"] = _finite_pending_timestamp(
        payload,
        "start_ts",
        current_ts,
    )
    normalized["end_ts"] = _finite_pending_timestamp(
        payload,
        "end_ts",
        current_ts,
    )
    return normalized


def load_validated_pending_task(
    task_path: PendingTask,
) -> dict | None:
    """读取并校验 pending；坏任务立即丢弃，调用方必须在 None 时早退。"""
    path = task_path.path
    try:
        with path.open("rb") as file:
            payload = pickle.load(file)
        return normalize_pending_payload(payload, task_path)
    except Exception as exc:
        # pickle 反序列化可能传播导入/属性等多种异常；统一记录并丢弃，
        # 防止 processing 中的坏文件在每次重启后再次进入队列。
        discard_invalid_pending_task(path, exc)
        return None


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(target)
    finally:
        temp_path.unlink(missing_ok=True)


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

    def __init__(
        self,
        daily_limit: float,
        est_cost_per_call: float,
        initial_state: Dict[str, Any] | None = None,
        on_change=None,
    ):
        self.daily_limit = float(daily_limit)
        self.est_cost = float(est_cost_per_call)
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.spent = 0.0
        self.call_count = 0
        self.lock = threading.Lock()
        self.on_change = on_change
        initial = initial_state or {}
        if str(initial.get("date", "")) == self.date:
            self.spent = max(0.0, float(initial.get("spent_yuan", 0.0)))
            self.call_count = max(0, int(initial.get("call_count", 0)))

    def try_consume(self) -> bool:
        """成功扣费 → True; 超预算 → False (调用方应放弃本次调用)"""
        with self.lock:
            today = datetime.now().strftime("%Y-%m-%d")
            if today != self.date:
                # 跨天重置
                self.date = today
                self.spent = 0.0
                self.call_count = 0
            if self.est_cost > 0 and self.spent + self.est_cost > self.daily_limit:
                return False
            self.spent += self.est_cost
            self.call_count += 1
            if self.on_change is not None:
                # 与计数更新共用同一把锁，确保并发持久化不会以旧快照覆盖新快照。
                self.on_change(self._snapshot_unlocked())
            return True

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> Dict[str, Any]:
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
    """通过内部千问的 Chat Completions 接口发送 JPEG 图片并解析合规结果。"""

    def __init__(self, cfg: Dict[str, Any], budget: BudgetGuard, tmp_dir: Path):
        vlm = cfg["vlm"]
        self.base_url = os.getenv("SECURITY_VLM_BASE_URL", str(vlm.get("base_url") or "")).strip().rstrip("/")
        self.model = os.getenv("SECURITY_VLM_MODEL", str(vlm.get("model") or "")).strip()
        self.api_key = os.getenv("SECURITY_VLM_API_KEY", str(vlm.get("api_key") or "")).strip()
        url = urlsplit(self.base_url)
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("请配置 vlm.base_url / SECURITY_VLM_BASE_URL 为内部模型接口地址（例如 http://127.0.0.1:18100/v1）")
        if not self.model:
            raise ValueError("请配置 vlm.model / SECURITY_VLM_MODEL 为内部模型服务名称")
        self.image_max_side = max(1, int(vlm.get("image_max_side", 960)))
        self.image_quality = max(1, min(100, int(vlm.get("image_jpeg_quality", 85))))
        self.api_timeout = float(vlm.get("api_timeout_sec", 45))
        self.max_tokens = int(vlm.get("max_tokens", 2048))
        if self.api_timeout <= 0 or self.max_tokens <= 0:
            raise ValueError("vlm.api_timeout_sec 和 vlm.max_tokens 必须大于 0")
        self.temperature = float(vlm.get("temperature", 0.1))
        self.budget = budget

    def _encode_frame(self, frame: np.ndarray) -> str:
        """图片随请求传输，模型服务器无需访问本机文件系统。"""
        h, w = frame.shape[:2]
        if max(h, w) > self.image_max_side:
            s = self.image_max_side / max(h, w)
            frame = cv2.resize(frame, (max(1, int(w * s)), max(1, int(h * s))))
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.image_quality])
        if not ok:
            raise ValueError("关键帧 JPEG 编码失败")
        return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")

    def judge(
        self,
        session_id: str,
        roi_name: str,
        roi_box: List[float],
        keyframes: List[np.ndarray],
        *,
        department: str,
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

        t0 = time.monotonic()
        try:
            require_department(department)
            user_content = [
                {"type": "image_url", "image_url": {"url": self._encode_frame(frame)}}
                for frame in keyframes
            ]
            user_content.append({
                "type": "text",
                "text": VLM_USER_PROMPT.format(
                    n_frames=len(keyframes),
                    roi_name=roi_name,
                    roi_box=roi_box,
                )
            })
            messages = [
                {"role": "system", "content": VLM_SYSTEM_PROMPT},
                {"role": "user",   "content": user_content},
            ]

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            with requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                timeout=self.api_timeout,
                allow_redirects=False,
            ) as response:
                latency = time.monotonic() - t0
                if response.status_code != 200:
                    return {"error": f"api_error: HTTP {response.status_code}",
                            "_latency_sec": round(latency, 2)}
                payload = response.json()

            content = payload["choices"][0]["message"].get("content") or ""
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
            if payload.get("usage"):
                result["_usage"] = {
                    "input_tokens": payload["usage"].get("prompt_tokens", 0),
                    "output_tokens": payload["usage"].get("completion_tokens", 0),
                }
            return result

        except requests.Timeout:
            return {"error": "api_timeout", "_latency_sec": round(time.monotonic() - t0, 2)}
        except requests.ConnectionError:
            return {"error": "api_connection_failed", "_latency_sec": round(time.monotonic() - t0, 2)}
        except Exception as e:
            return {"error": f"exception: {e}", "_latency_sec": round(time.monotonic() - t0, 2)}

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
            result = json.loads(t)
        except (ValueError, TypeError):
            try:
                s = t.index("{")
                e = t.rindex("}") + 1
                result = json.loads(t[s:e])
            except (ValueError, TypeError):
                return None
        return result if isinstance(result, dict) else None


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
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            try:
                for p in sorted(self.pending_dir.glob("*.pkl")):
                    if p.name in self.seen:
                        continue
                    self.seen.add(p.name)
                    self.q.put(p)
            except Exception as e:
                print(f"[vlm-scan] 扫描异常: {e}", flush=True)
            self._stop_event.wait(self.poll_sec)

    def stop(self):
        self._stop_event.set()


class DepartmentPendingScanner(threading.Thread):
    """按事业部、再按摄像头轮询，并原子认领到无歧义 processing 路径。"""

    def __init__(
        self,
        departments_root: Path,
        q: queue.Queue,
        poll_sec: float = 0.5,
    ):
        super().__init__(daemon=True)
        self.departments_root = Path(departments_root)
        self.q = q
        self.poll_sec = poll_sec
        self.seen: set[str] = set()
        self._department_cursor = 0
        self._last_scanned_camera: dict[str, str | None] = {
            department: None for department in DEPARTMENTS
        }
        self._source_cursors: dict[tuple[str, str], bool] = {}
        self._stop_event = threading.Event()

    def pending_dirs(self) -> list[Path]:
        directories = []
        for department in DEPARTMENTS:
            cameras_dir = self.departments_root / department / "cameras"
            directories.extend(
                path
                for path in sorted(cameras_dir.glob("*/pending"))
                if path.is_dir()
            )
        return directories

    def processing_dirs(self) -> list[Path]:
        directories = [
            self.departments_root / department / "global" / "processing"
            for department in DEPARTMENTS
        ]
        return directories

    @staticmethod
    def _identity(path: Path) -> str:
        return str(path.resolve())

    def _all_existing_paths(self) -> set[str]:
        paths = {
            self._identity(path)
            for pending_dir in self.pending_dirs()
            for path in pending_dir.glob("*.pkl")
        }
        for processing_dir in self.processing_dirs():
            paths.update(
                self._identity(path)
                for path in processing_dir.glob("*.pkl")
            )
            paths.update(
                self._identity(path)
                for path in processing_dir.glob("*/*.pkl")
            )
        return paths

    def _cleanup_unknown_departments(self) -> None:
        if not self.departments_root.is_dir():
            return
        for department_dir in self.departments_root.iterdir():
            if (
                not department_dir.is_dir()
                or department_dir.name in DEPARTMENTS
            ):
                continue
            reason = ValueError(
                f"未知安检事业部: {department_dir.name}"
            )
            for task_path in department_dir.glob(
                "cameras/*/pending/*.pkl"
            ):
                discard_invalid_pending_task(task_path, reason)
            for task_path in department_dir.glob(
                "global/processing/**/*.pkl"
            ):
                discard_invalid_pending_task(task_path, reason)

    def _existing_tasks_by_camera(
        self,
        department: str,
    ) -> dict[str, PendingTask]:
        processing_dir = (
            self.departments_root / department / "global" / "processing"
        )
        tasks = []
        for path in sorted(processing_dir.glob("*/*.pkl")):
            if self._identity(path) in self.seen:
                continue
            try:
                tasks.append(PendingTask(
                    department,
                    path.parent.name,
                    path,
                ))
            except ValueError as exc:
                discard_invalid_pending_task(path, exc)
        tasks_by_camera: dict[str, list[PendingTask]] = {}
        for task in tasks:
            tasks_by_camera.setdefault(task.camera_id, []).append(task)
        return {
            camera_id: camera_tasks[0]
            for camera_id, camera_tasks in tasks_by_camera.items()
        }

    def _pending_camera_dirs(self, department: str) -> list[Path]:
        directories = [
            path
            for path in sorted(
                (
                    self.departments_root
                    / department
                    / "cameras"
                ).glob("*/pending")
            )
            if path.is_dir() and any(path.glob("*.pkl"))
        ]
        return directories

    def _pending_candidates_by_camera(
        self,
        department: str,
    ) -> dict[str, Path]:
        candidates = {}
        for pending_dir in self._pending_camera_dirs(department):
            try:
                camera_id = validate_camera_id(pending_dir.parent.name)
            except ValueError as exc:
                for invalid_path in pending_dir.glob("*.pkl"):
                    discard_invalid_pending_task(invalid_path, exc)
                continue
            candidates.setdefault(camera_id, pending_dir)
        return candidates

    def _claim_pending_dir(
        self,
        department: str,
        camera_id: str,
        pending_dir: Path,
    ) -> PendingTask | None:
        if self._stop_event.is_set():
            return None
        source = next(iter(sorted(pending_dir.glob("*.pkl"))), None)
        if source is None:
            return None
        processing_dir = self.departments_root / department / "global" / "processing" / camera_id
        processing_dir.mkdir(parents=True, exist_ok=True)
        target = processing_dir / source.name
        if target.exists():
            target = processing_dir / (
                f"{source.stem}.{time.time_ns()}{source.suffix}"
            )
        try:
            source.replace(target)
        except FileNotFoundError:
            return None
        if self._stop_event.is_set():
            # 已认领的任务留在 processing，供下次启动恢复；绝不在 stop 后入队。
            return None
        return PendingTask(department, camera_id, target)

    def _has_prefetched_task(self, department: str, camera_id: str) -> bool:
        has_queued = getattr(self.q, "has_queued", None)
        return bool(
            callable(has_queued)
            and has_queued(department, camera_id)
        )

    def _next_candidate(self, department: str) -> PendingTask | None:
        recovered = self._existing_tasks_by_camera(department)
        pending = self._pending_candidates_by_camera(department)
        camera_ids = sorted(set(recovered) | set(pending))
        camera_ids = [
            camera_id
            for camera_id in camera_ids
            if not self._has_prefetched_task(department, camera_id)
        ]
        if not camera_ids:
            return None
        last_camera = self._last_scanned_camera[department]
        start = (
            (camera_ids.index(last_camera) + 1) % len(camera_ids)
            if last_camera in camera_ids
            else next(
                (
                    index
                    for index, camera_id in enumerate(camera_ids)
                    if last_camera is not None and camera_id > last_camera
                ),
                0,
            )
        )
        camera_id = camera_ids[start]
        self._last_scanned_camera[department] = camera_id

        recovered_task = recovered.get(camera_id)
        pending_candidate = pending.get(camera_id)
        source_key = (department, camera_id)
        prefer_pending = self._source_cursors.get(source_key, False)
        self._source_cursors[source_key] = not prefer_pending
        if prefer_pending and pending_candidate is not None:
            task = self._claim_pending_dir(
                department,
                camera_id,
                pending_candidate,
            )
            if task is not None:
                return task
        if recovered_task is not None:
            return recovered_task
        if pending_candidate is not None:
            return self._claim_pending_dir(
                department,
                camera_id,
                pending_candidate,
            )
        return None

    def scan_once(self) -> None:
        if self._stop_event.is_set():
            return
        self._cleanup_unknown_departments()
        self.seen.intersection_update(self._all_existing_paths())
        offset = self._department_cursor % len(DEPARTMENTS)
        departments = (
            list(DEPARTMENTS[offset:])
            + list(DEPARTMENTS[:offset])
        )
        self._department_cursor = (offset + 1) % len(DEPARTMENTS)
        for department in departments:
            if self._stop_event.is_set():
                return
            task = self._next_candidate(department)
            if task is None:
                continue
            identity = self._identity(task.path)
            if identity in self.seen:
                continue
            if self._stop_event.is_set():
                return
            self.seen.add(identity)
            if self._stop_event.is_set():
                self.seen.discard(identity)
                return
            self.q.put(task)

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.scan_once()
            except Exception as exc:
                print(
                    f"[vlm-scan] 事业部公平扫描异常: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
            self._stop_event.wait(self.poll_sec)

    def stop(self) -> None:
        self._stop_event.set()


# ---------------------------------------------------------------------------
# 关键帧拼图 (横向 N 张 + 顶部状态 banner)
# ---------------------------------------------------------------------------
_FONT_CANDIDATES = (
    os.environ.get("SECURITY_VLM_FONT_PATH", "").strip(),
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_FONT_FALLBACK_WARNED = False


def _load_banner_font(font_size: int):
    global _FONT_FALLBACK_WARNED
    errors = []
    for font_path in _FONT_CANDIDATES:
        if not font_path:
            continue
        try:
            return ImageFont.truetype(font_path, font_size)
        except (OSError, ValueError) as exc:
            errors.append(f"{font_path}: {exc}")

    if not _FONT_FALLBACK_WARNED:
        print(
            "[vlm] 未找到可用的横幅字体，已降级为 Pillow 默认字体；"
            f"可通过 SECURITY_VLM_FONT_PATH 指定字体。尝试结果: {'; '.join(errors)}",
            file=sys.stderr,
            flush=True,
        )
        _FONT_FALLBACK_WARNED = True
    return ImageFont.load_default()


def _draw_text_pil(img_bgr, text, xy, font_size=24, color=(255, 255, 255)):
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    draw = ImageDraw.Draw(pil_img)

    font = _load_banner_font(font_size)

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


class DepartmentResultStores:
    """四事业部持久结果仓库，以及唯一的共享预算仓库。"""

    def __init__(self, data_root: Path):
        self.data_root = Path(data_root).resolve()
        self._stores = {
            department: ResultStore(self.results_dir(department))
            for department in DEPARTMENTS
        }
        self.budget_store = ResultStore(self.data_root / "_shared")

    def results_dir(self, department: str) -> Path:
        return self.data_root / require_department(department) / "results"

    def clips_dir(self, department: str) -> Path:
        return self.results_dir(department) / "clips"

    def get(self, department: str) -> ResultStore:
        return self._stores[require_department(department)]


def read_strict_result_object(
    store: ResultStore,
    key: str,
    *,
    quarantine_corrupt: bool = False,
) -> dict:
    """严格读取状态对象；共享状态损坏时可保留证据后重新初始化。"""
    path = store._path(key)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON 顶层必须为对象")
        return payload
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(
            f"[vlm] 状态文件损坏 {path}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        if quarantine_corrupt:
            backup = path.with_name(
                f"{path.stem}.corrupt.{time.time_ns()}{path.suffix}"
            )
            try:
                path.replace(backup)
            except OSError as move_exc:
                raise RuntimeError(
                    f"无法隔离损坏的共享状态文件 {path}"
                ) from move_exc
        return {}


class DepartmentWorkspaceStateError(RuntimeError):
    """单事业部持久状态损坏，必须保留任务以避免数据丢失。"""


class DepartmentAccumulator:
    """单事业部历史和当日统计的线程安全累计器。"""

    def __init__(
        self,
        department: str,
        store: ResultStore,
        *,
        max_history: int,
        budget_snapshot=None,
    ):
        self.department = require_department(department)
        self.store = store
        self.max_history = max(1, int(max_history))
        self._budget_snapshot = budget_snapshot
        self._lock = threading.RLock()
        self.disabled = False
        existing_state = self._strict_read("vlm_state")
        existing_state = existing_state or {}
        existing_history = existing_state.get("history")
        if existing_history is not None and not isinstance(
            existing_history,
            list,
        ):
            self._mark_disabled("vlm_state.history 必须是列表")
            existing_history = None
        if not isinstance(existing_history, list):
            history_payload = self._strict_read("vlm_history") or {}
            existing_history = history_payload.get("items", [])
            if not isinstance(existing_history, list):
                self._mark_disabled("vlm_history.items 必须是列表")
                existing_history = []
        self.history = deque(
            [
                item
                for item in existing_history
                if isinstance(item, dict)
                and item.get("department", self.department) == self.department
            ],
            maxlen=self.max_history,
        )
        today = datetime.now().strftime("%Y-%m-%d")
        existing_stats = self._strict_read("vlm_latest_stats") or {}
        state_counts = existing_state.get("counts")
        if state_counts is not None and not isinstance(state_counts, dict):
            self._mark_disabled("vlm_state.counts 必须是对象")
            state_counts = None
        restored = (
            state_counts if isinstance(state_counts, dict) else existing_stats
        )
        restored_date = str(
            existing_state.get("date", existing_stats.get("date", ""))
        )
        try:
            self.counts = {
                "compliant": int(restored.get("compliant", 0))
                if restored_date == today
                else 0,
                "non_compliant": int(restored.get("non_compliant", 0))
                if restored_date == today
                else 0,
                "error": int(restored.get("error", 0))
                if restored_date == today
                else 0,
            }
        except (TypeError, ValueError, OverflowError) as exc:
            self._mark_disabled(f"统计计数无效: {exc}")
            self.counts = {
                "compliant": 0,
                "non_compliant": 0,
                "error": 0,
            }
        self.date = today

    def _mark_disabled(self, message: str) -> None:
        self.disabled = True
        try:
            self.store.write("workspace_error", {
                "department": self.department,
                "message": message,
                "ts": time.time(),
            })
        except OSError:
            print(
                f"[vlm] 写入事业部 {self.department} 状态损坏标记失败",
                file=sys.stderr,
                flush=True,
            )

    def _strict_read(self, key: str) -> dict | None:
        """不把损坏状态静默降级为默认值，避免覆盖原始证据。"""
        path = self.store._path(key)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON 顶层必须为对象")
            return value
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self._mark_disabled(
                f"{key} 状态损坏，已隔离该事业部累计器: {exc}"
            )
            return None

    def _roll_date(self) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.date:
            self.counts = {
                "compliant": 0,
                "non_compliant": 0,
                "error": 0,
            }
            self.date = today
        return today

    def record(
        self,
        record: dict,
        *,
        queue_size: int = 0,
    ) -> bool:
        if self.disabled:
            raise DepartmentWorkspaceStateError(
                f"{self.department} 结果状态损坏，任务保留等待修复"
            )
        if record.get("department") != self.department:
            raise ValueError("结果事业部与累计器不一致")
        camera_id = validate_camera_id(record.get("camera_id"))
        session_id = _safe_pending_identifier(
            record.get("session_id"),
            "session_id",
        )
        result = record.get("result") or {}
        with self._lock:
            self._roll_date()
            duplicate = any(
                item.get("camera_id") == camera_id
                and item.get("session_id") == session_id
                for item in self.history
            )
            if not duplicate:
                status = (
                    "error"
                    if "error" in result
                    else (
                        "compliant"
                        if result.get("compliant")
                        else "non_compliant"
                    )
                )
                self.counts[status] += 1
                self.history.appendleft({
                    "time": record.get("time", ""),
                    "session_id": session_id,
                    "department": self.department,
                    "camera_id": camera_id,
                    "camera_name": record.get("camera_name", camera_id),
                    "roi_name": record.get("roi_name", ""),
                    "duration_sec": record.get("duration_sec", 0),
                    "status": status,
                    "upper_checked": result.get("upper_checked"),
                    "middle_checked": result.get("middle_checked"),
                    "lower_checked": result.get("lower_checked"),
                    "arms_open": result.get("arms_open"),
                    "reason": result.get("reason", ""),
                    "error": result.get("error"),
                })
            self.write(queue_size=queue_size)
            return not duplicate

    def write(self, *, queue_size: int = 0) -> None:
        with self._lock:
            if self.disabled:
                raise DepartmentWorkspaceStateError(
                    f"{self.department} 结果状态损坏，拒绝覆盖"
                )
            current_date = self._roll_date()
            history = list(self.history)
            total = self.counts["compliant"] + self.counts["non_compliant"]
            stats = {
                "department": self.department,
                "date": current_date,
                "ts": time.time(),
                "total": total,
                "calls": sum(self.counts.values()),
                **self.counts,
                "rate": (
                    round(self.counts["compliant"] / total * 100.0, 2)
                    if total
                    else 0.0
                ),
                "queue": max(0, int(queue_size)),
            }
            if self._budget_snapshot is not None:
                stats["budget"] = self._budget_snapshot()
            self.store.write("vlm_state", {
                "department": self.department,
                "date": current_date,
                "counts": dict(self.counts),
                "history": history,
            })
            self.store.write("vlm_history", {"items": history})
            self.store.write("vlm_latest_stats", stats)


class DepartmentAccumulators:
    """为各事业部持有独立累计器。"""

    def __init__(
        self,
        stores: DepartmentResultStores,
        *,
        max_history: int,
        budget_snapshot=None,
    ):
        self._items = {
            department: DepartmentAccumulator(
                department,
                stores.get(department),
                max_history=max_history,
                budget_snapshot=budget_snapshot,
            )
            for department in DEPARTMENTS
        }

    def get(self, department: str) -> DepartmentAccumulator:
        return self._items[require_department(department)]

    def write_all(self, queue_sizes: dict[str, int] | None = None) -> None:
        sizes = queue_sizes or {}
        for department, accumulator in self._items.items():
            if accumulator.disabled:
                continue
            try:
                accumulator.write(queue_size=sizes.get(department, 0))
            except (
                OSError,
                TypeError,
                ValueError,
                DepartmentWorkspaceStateError,
            ) as exc:
                accumulator._mark_disabled(
                    f"累计状态写入失败，已隔离: {exc}"
                )


class _TaskLockEntry:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.users = 0


class PendingTaskProcessor:
    """一个可测试的认领任务处理单元，负责校验、判定、持久化和清理。"""

    def __init__(
        self,
        *,
        stores: DepartmentResultStores,
        accumulators: DepartmentAccumulators,
        judge,
        queue_timeout: float,
        save_clip_only_non_compliant: bool = True,
    ):
        self.stores = stores
        self.accumulators = accumulators
        self.judge = judge
        self.queue_timeout = float(queue_timeout)
        self.save_clip_only_non_compliant = bool(
            save_clip_only_non_compliant
        )
        self._locks_guard = threading.Lock()
        self._task_locks: dict[
            tuple[str, str, str],
            _TaskLockEntry,
        ] = {}

    @contextmanager
    def _hold_task_lock(self, task_key: tuple[str, str, str]):
        with self._locks_guard:
            entry = self._task_locks.get(task_key)
            if entry is None:
                entry = _TaskLockEntry()
                self._task_locks[task_key] = entry
            entry.users += 1
        try:
            entry.lock.acquire()
            try:
                yield
            finally:
                entry.lock.release()
        finally:
            with self._locks_guard:
                entry.users -= 1
                if (
                    entry.users == 0
                    and self._task_locks.get(task_key) is entry
                ):
                    del self._task_locks[task_key]

    @staticmethod
    def _cleanup(task: PendingTask) -> None:
        for target in (
            task.path,
            task.path.with_suffix(f"{task.path.suffix}.started"),
            task.path.with_suffix(f"{task.path.suffix}.recovered"),
        ):
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                print(
                    f"[vlm] 清理完成任务失败 {target}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

    @staticmethod
    def _completion_matches(record: dict, payload: dict) -> bool:
        return all(
            record.get(field) == payload[field]
            for field in ("department", "camera_id", "session_id")
        )

    def process(
        self,
        task: PendingTask,
        *,
        now_ts: float | None = None,
    ) -> bool:
        payload = load_validated_pending_task(task)
        if payload is None:
            return False
        task_key = (
            payload["department"],
            payload["camera_id"],
            payload["session_id"],
        )
        with self._hold_task_lock(task_key):
            return self._process_locked(
                task,
                payload,
                time.time() if now_ts is None else float(now_ts),
            )

    def _process_locked(
        self,
        task: PendingTask,
        payload: dict,
        now_ts: float,
    ) -> bool:
        department = payload["department"]
        camera_id = payload["camera_id"]
        session_id = payload["session_id"]
        result_path = (
            self.stores.results_dir(department)
            / camera_id
            / f"{session_id}.json"
        )
        started_marker = task.path.with_suffix(
            f"{task.path.suffix}.started"
        )
        recovered_marker = task.path.with_suffix(
            f"{task.path.suffix}.recovered"
        )
        record = None
        if result_path.exists():
            try:
                record = json.loads(result_path.read_text(encoding="utf-8"))
                if not isinstance(record, dict):
                    raise ValueError("completion JSON 顶层必须为对象")
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                print(f"[vlm] completion 记录损坏，保留任务等待人工处理: {exc}", file=sys.stderr, flush=True)
                return False
            if not self._completion_matches(record, payload):
                print("[vlm] completion record 复合身份不匹配，保留任务和标记", file=sys.stderr, flush=True)
                return False

        waited = now_ts - payload["enqueue_ts"]
        if (
            record is None
            and waited > self.queue_timeout
            and not started_marker.exists()
            and not recovered_marker.exists()
        ):
            self._cleanup(task)
            return False

        if record is None:
            if started_marker.exists():
                result = {
                    "error": (
                        "VLM 进程在判定期间异常中断；"
                        "为避免重复调用和重复计费，本任务未自动重试"
                    )
                }
            else:
                started_marker.parent.mkdir(parents=True, exist_ok=True)
                started_marker.touch(exist_ok=True)
                result = self.judge.judge(
                    session_id,
                    payload["roi_name"],
                    payload["roi_box"],
                    payload["keyframes"],
                    department=department,
                )
            duration = payload["end_ts"] - payload["start_ts"]
            record = {
                "session_id": session_id,
                "department": department,
                "camera_id": camera_id,
                "camera_name": payload["camera_name"],
                "roi_name": payload["roi_name"],
                "start_ts": payload["start_ts"],
                "end_ts": payload["end_ts"],
                "duration_sec": round(duration, 2),
                "n_keyframes": len(payload["keyframes"]),
                "result": result,
                "judged_ts": now_ts,
                "time": datetime.fromtimestamp(
                    payload["end_ts"]
                ).strftime("%Y-%m-%d %H:%M:%S"),
            }
            atomic_write_json(result_path, record)
        else:
            result = record.get("result") or {}

        if (
            "error" not in result
            and (
                not self.save_clip_only_non_compliant
                or not result.get("compliant")
            )
        ):
            save_clip(
                payload["keyframes"],
                result,
                session_id,
                self.stores.clips_dir(department) / camera_id,
            )
        self.accumulators.get(department).record(record)
        self._cleanup(task)
        return True


# ---------------------------------------------------------------------------
# 启动时清理过期 / 残留任务
# ---------------------------------------------------------------------------
def cleanup_stale_pending(pending_dir: Path, now_ts: float, queue_timeout: float):
    """
    删除真正超过 queue_timeout 的任务；进程重启前已产生但未超时的任务保留。
    """
    removed = 0
    for p in pending_dir.glob("*.pkl"):
        try:
            with open(p, "rb") as f:
                payload = pickle.load(f)
            enq_ts = float(payload.get("enqueue_ts", p.stat().st_mtime))
            if (now_ts - enq_ts) > queue_timeout:
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
    return removed


def mark_recovered_processing(processing_dir: Path) -> int:
    """标记启动前已认领但尚未开始的任务，使其恢复时不受旧 TTL 影响。"""
    marked = 0
    for task_path in Path(processing_dir).glob("*.pkl"):
        started = task_path.with_suffix(f"{task_path.suffix}.started")
        marker = task_path.with_suffix(f"{task_path.suffix}.recovered")
        if not started.exists() and not marker.exists():
            marker.touch()
            marked += 1
    for task_path in Path(processing_dir).glob("*/*.pkl"):
        started = task_path.with_suffix(f"{task_path.suffix}.started")
        marker = task_path.with_suffix(f"{task_path.suffix}.recovered")
        if not started.exists() and not marker.exists():
            marker.touch()
            marked += 1
    return marked


def process_queued_item(task_q: queue.Queue, process_one, item=None) -> None:
    """处理一个已入队任务,隔离异常并确保队列完成计数正确。"""
    queued_item = task_q.get() if item is None else item
    try:
        process_one(queued_item)
    except Exception:
        print(f"[vlm] worker 任务异常: {queued_item}", file=sys.stderr, flush=True)
        traceback.print_exc()
    finally:
        task_q.task_done()


def run_task_worker(
    task_q,
    process_one,
    stop_event: threading.Event,
    *,
    poll_sec: float = 0.5,
) -> None:
    """使用独立停止事件消费任务；全局进程信号不直接终止 worker。"""
    while not stop_event.is_set():
        try:
            item = task_q.get(timeout=poll_sec)
        except queue.Empty:
            continue
        process_queued_item(task_q, process_one, item)


def shutdown_task_workers(
    scanner: threading.Thread,
    task_q,
    worker_stop: threading.Event,
    workers: list[threading.Thread],
    *,
    drain_timeout_sec: float = 120.0,
    poll_sec: float = 0.5,
    worker_join_timeout_sec: float = 1.0,
    scanner_join_timeout_sec: float = 2.0,
) -> bool:
    """停止唯一生产者后有界排空队列，再通知并等待 worker 退出。"""
    scanner.stop()
    scanner.join(timeout=max(0.0, float(scanner_join_timeout_sec)))

    deadline = time.monotonic() + max(0.0, float(drain_timeout_sec))
    while task_q.unfinished_tasks > 0:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(max(0.001, float(poll_sec)), remaining))

    drained = task_q.unfinished_tasks == 0
    worker_stop.set()
    for worker in workers:
        worker.join(timeout=max(0.0, float(worker_join_timeout_sec)))
    return (
        drained
        and not scanner.is_alive()
        and all(not worker.is_alive() for worker in workers)
    )


def queued_department_counts(task_q: queue.Queue) -> dict[str, int]:
    if isinstance(task_q, DepartmentFairTaskQueue):
        return task_q.department_counts()
    counts = {department: 0 for department in DEPARTMENTS}
    with task_q.mutex:
        for item in task_q.queue:
            if isinstance(item, PendingTask):
                counts[item.department] += 1
    return counts


def vlm_max_concurrent(vlm_cfg: dict) -> int:
    value = int(vlm_cfg.get("max_concurrent", 3))
    if value <= 0:
        raise ValueError("vlm.max_concurrent 必须是正整数")
    return value


# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------
def main():
    set_process_title("security_vlm[vlm]")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=str)
    parser.add_argument(
        "--departments-root",
        type=str,
        help="精确的事业部运行根目录",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    config_path = resolve_path(args.config, project_root)
    cfg = load_yaml(config_path)

    paths = VLMWorkerPaths.from_config(
        cfg,
        project_root,
        departments_root=args.departments_root,
    )
    runtime_dir = paths.runtime_dir
    stores = DepartmentResultStores(paths.data_root)

    vlm_cfg = cfg["vlm"]
    out_cfg = cfg["output"]
    status_key      = str(vlm_cfg.get("status_key", "vlm_status"))
    queue_timeout   = float(vlm_cfg.get("queue_timeout_sec", 60))
    max_concurrent  = vlm_max_concurrent(vlm_cfg)
    scheduling = str(
        vlm_cfg.get("scheduling", "department_round_robin")
    )
    if scheduling != "department_round_robin":
        raise ValueError(
            "vlm.scheduling 仅支持 department_round_robin"
        )

    save_only_non = bool(out_cfg.get("save_clip_only_non_compliant", True))
    max_history   = int(out_cfg.get("max_history_items", 300))

    paths.departments_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = runtime_dir / "vlm_tmp"
    task_q = DepartmentFairTaskQueue()
    scanner = DepartmentPendingScanner(
        paths.departments_root,
        task_q,
        poll_sec=0.5,
    )

    # 仅清理真正超时的任务，重启前未完成且仍有效的任务继续处理。
    startup_ts = time.time()
    for discovered_processing_dir in scanner.processing_dirs():
        mark_recovered_processing(discovered_processing_dir)
    cleanup_dirs = scanner.pending_dirs()
    for cleanup_dir in cleanup_dirs:
        cleanup_stale_pending(cleanup_dir, startup_ts, queue_timeout)

    budget_state = read_strict_result_object(
        stores.budget_store, "vlm_budget", quarantine_corrupt=True,
    )
    budget = BudgetGuard(
        daily_limit=float(cfg["budget"]["daily_limit_yuan"]),
        est_cost_per_call=float(cfg["budget"]["estimated_cost_per_call"]),
        initial_state=budget_state,
        on_change=lambda snapshot: stores.budget_store.write(
            "vlm_budget",
            snapshot,
        ),
    )
    stores.budget_store.write("vlm_budget", budget.snapshot())
    judge = VLMJudge(cfg, budget, tmp_dir)
    accumulators = DepartmentAccumulators(
        stores,
        max_history=max_history,
        budget_snapshot=budget.snapshot,
    )
    processor = PendingTaskProcessor(
        stores=stores,
        accumulators=accumulators,
        judge=judge,
        queue_timeout=queue_timeout,
        save_clip_only_non_compliant=save_only_non,
    )

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # 任务队列 + 扫描线程
    scanner.start()

    def write_stats_and_history() -> None:
        """持久化各事业部各自的统计和历史。"""
        accumulators.write_all(queued_department_counts(task_q))

    def process_one(task: PendingTask) -> None:
        if not isinstance(task, PendingTask):
            raise TypeError("VLM 任务队列只接受 PendingTask")
        processor.process(task)

    def write_statuses(ok: bool, message: str) -> None:
        queue_sizes = queued_department_counts(task_q)
        for department in DEPARTMENTS:
            stores.get(department).write(status_key, {
                "ok": ok,
                "department": department,
                "message": message,
                "ts": time.time(),
                "queue": queue_sizes[department],
            })

    worker_stop = threading.Event()
    threads = []
    for _ in range(max_concurrent):
        t = threading.Thread(
            target=run_task_worker,
            args=(task_q, process_one, worker_stop),
            daemon=True,
        )
        t.start()
        threads.append(t)

    write_statuses(True, "running")
    write_stats_and_history()
    watched_path = paths.departments_root
    print(
        f"[vlm] 就绪, 并发 {max_concurrent}, 开始监听 {watched_path}",
        flush=True,
    )

    # 主线程: 周期心跳 (queue size 在变, 顺便刷新 stats)
    try:
        while not _STOP.is_set():
            write_stats_and_history()
            write_statuses(True, "running")
            time.sleep(2.0)
    except Exception as e:
        print(f"[vlm] 主循环异常: {e}", flush=True)
        write_statuses(False, str(e))
    finally:
        # 先确保扫描生产者停止，再让 worker 排空所有已认领任务。
        print("[vlm] 退出中, 等待队列清空...", flush=True)
        drained = shutdown_task_workers(
            scanner,
            task_q,
            worker_stop,
            threads,
        )
        if task_q.unfinished_tasks > 0:
            print(
                f"[vlm] 排空超时，保留 {task_q.unfinished_tasks} 个任务供下次恢复",
                flush=True,
            )
        elif not drained:
            print("[vlm] worker 未能在关闭期限内全部退出", flush=True)
        write_stats_and_history()
        write_statuses(False, "stopped")


if __name__ == "__main__":
    main()
