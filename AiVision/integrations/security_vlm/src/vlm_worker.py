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
import json
import math
import os
import pickle
import queue
import shutil
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
from PIL import Image, ImageDraw, ImageFont

import cv2
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from departments import SECURITY_DEPARTMENTS, require_department  # noqa: E402
from camera_registry import validate_camera_id  # noqa: E402
from frame_hub import ResultStore  # noqa: E402


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
# 功能：更新或保存 `set_process_title` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `title`（str）：`title` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`setproctitle`、`str`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def set_process_title(title: str) -> None:
    try:
        from setproctitle import setproctitle
        setproctitle(str(title))
    except Exception:
        pass


# 功能：读取或查询 `load_yaml` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
# 返回：Dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`open`、`yaml.safe_load`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# 功能：计算或解析 `resolve_path` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `p`（str）：`p` 对应的业务输入值
#   - `base`（Path）：`base` 对应的业务输入值
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Path`、`pp.is_absolute`、`pp.resolve`、`(base / pp).resolve`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def resolve_path(p: str, base: Path) -> Path:
    pp = Path(p)
    return pp.resolve() if pp.is_absolute() else (base / pp).resolve()


# 功能：定义 `VLMWorkerPaths` 类，封装后台任务相关的状态、约束与操作
# 参数：
#   - `runtime_dir`（Path）：`runtime_dir` 对应的业务输入值
#   - `departments_root`（Path）：`departments_root` 对应的业务输入值
#   - `legacy_camera_root`（Path）：`legacy_camera_root` 对应的业务输入值
#   - `data_root`（Path）：`data_root` 对应的业务输入值
# 返回：VLMWorkerPaths；返回新建的 `VLMWorkerPaths` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class VLMWorkerPaths:
    runtime_dir: Path
    departments_root: Path
    legacy_camera_root: Path
    data_root: Path

    # 功能：实现 `from_config` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `cfg`（dict）：运行配置对象
    #   - `project_root`（Path）：`project_root` 对应的业务输入值
    #   - `departments_root`（str | Path | None）：`departments_root` 对应的业务输入值；默认值为 `None`
    #   - `legacy_camera_root`（str | Path | None）：`legacy_camera_root` 对应的业务输入值；默认值为 `None`
    # 返回：'VLMWorkerPaths'；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_worker_paths_resolve_relative_roots_from_project_and_keep_exact_root` 调用本符号
    #   - 内部调用：`Path`、`cfg.get`、`resolve_path`、`departments_cfg.get`、`runtime_cfg.get`、`cls`、`str`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @classmethod
    def from_config(
        cls,
        cfg: dict,
        project_root: Path,
        *,
        departments_root: str | Path | None = None,
        legacy_camera_root: str | Path | None = None,
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
        configured_legacy = (
            legacy_camera_root
            if legacy_camera_root is not None
            else runtime_cfg.get("camera_root", runtime_dir / "cameras")
        )
        return cls(
            runtime_dir=runtime_dir,
            departments_root=resolve_path(str(configured_departments), base),
            legacy_camera_root=resolve_path(str(configured_legacy), base),
            data_root=resolve_path(
                str(departments_cfg.get("data_root", "data/departments")),
                base,
            ),
        )


# 功能：已由目录结构认证的待处理任务身份；输入与输出详见下方说明
# 参数：
#   - `department`（str）：业务部门名称或标识
#   - `camera_id`（str）：摄像头唯一标识
#   - `path`（Path）：目标路径
#   - `legacy`（bool）：`legacy` 对应的业务输入值
# 返回：PendingTask；返回新建的 `PendingTask` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_flat_processing_task`
#         实例化本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_existing_tasks_by_camera`
#         实例化本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_claim_pending_dir` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class PendingTask:
    """已由目录结构认证的待处理任务身份。"""

    department: str
    camera_id: str
    path: Path
    legacy: bool = False

    # 功能：初始化或配置 `__post_init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`object.__setattr__`、`require_department`、`validate_camera_id`、`Path`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def __post_init__(self) -> None:
        object.__setattr__(self, "department", require_department(self.department))
        object.__setattr__(self, "camera_id", validate_camera_id(self.camera_id))
        object.__setattr__(self, "path", Path(self.path))


# 功能：在 worker 取任务时按事业部、摄像头两级轮询的线程安全队列；输入与输出详见下方说明
# 参数：无。
# 返回：DepartmentFairTaskQueue；返回新建的 `DepartmentFairTaskQueue` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DepartmentFairTaskQueue:
    """在 worker 取任务时按事业部、摄像头两级轮询的线程安全队列。"""

    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`threading.Condition`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(self) -> None:
        self.maxsize = 0
        self._condition = threading.Condition()
        self._queues: dict[str, dict[str, deque]] = {
            department: {} for department in SECURITY_DEPARTMENTS
        }
        self._camera_order: dict[str, list[str]] = {
            department: [] for department in SECURITY_DEPARTMENTS
        }
        self._last_camera: dict[str, str | None] = {
            department: None for department in SECURITY_DEPARTMENTS
        }
        self._department_cursor = 0
        self._qsize = 0
        self._unfinished_tasks = 0

    # 功能：更新或保存 `put` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `item`（PendingTask）：`item` 对应的业务输入值
    #   - `block`（bool）：`block` 对应的业务输入值；默认值为 `True`
    #   - `timeout`（float | None）：允许操作等待的最长秒数；默认值为 `None`
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentFairTaskQueue::put_nowait` 调用本符号
    #   - 内部调用：`isinstance`、`TypeError`、`department_queues.get`、`deque`、`self._camera_order[item.department].append`、`camera_queue.append`、`self._condition.notify`。
    # 副作用/注意事项：会更新当前实例的运行状态；校验或执行失败时会主动抛出异常。
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

    # 功能：更新或保存 `put_nowait` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `item`（PendingTask）：`item` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/service.py` 的 `AsyncViolationWriter::enqueue` 调用本符号；`AiVision/core/alarm/dispatcher.py` 的
    #         `AlarmDispatcher::_execute` 调用本符号
    #   - 内部调用：`self.put`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def put_nowait(self, item: PendingTask) -> None:
        self.put(item, block=False)

    # 功能：读取或查询 `get` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `block`（bool）：`block` 对应的业务输入值；默认值为 `True`
    #   - `timeout`（float | None）：允许操作等待的最长秒数；默认值为 `None`
    # 返回：PendingTask；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentFairTaskQueue::get_nowait` 调用本符号
    #   - 内部调用：`ValueError`、`time.monotonic`、`float`、`self._condition.wait`、`self._select_department`、`self._select_camera`、`self._queues[department][camera_id].popleft`。
    # 副作用/注意事项：会更新当前实例的运行状态；校验或执行失败时会主动抛出异常。
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

    # 功能：读取或查询 `get_nowait` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：PendingTask；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_multicamera_scanner_round_robins_and_deduplicates_full_paths`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_scanner_discovers_new_department_and_legacy_pending_paths`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_department_processing_collision_stays_in_department`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_same_named_tasks_in_two_departments_do_not_collide` 调用本符号；另有 8 处静态调用
    #   - 内部调用：`self.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_nowait(self) -> PendingTask:
        return self.get(block=False)

    # 功能：实现 `_select_department` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentFairTaskQueue::get` 调用本符号
    #   - 内部调用：`len`、`range`、`any`、`self._queues[department].values`。
    # 副作用/注意事项：会更新当前实例的运行状态；校验或执行失败时会主动抛出异常。
    def _select_department(self) -> str:
        department_count = len(SECURITY_DEPARTMENTS)
        for offset in range(department_count):
            index = (self._department_cursor + offset) % department_count
            department = SECURITY_DEPARTMENTS[index]
            if any(self._queues[department].values()):
                self._department_cursor = (index + 1) % department_count
                return department
        raise queue.Empty

    # 功能：实现 `_select_camera` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentFairTaskQueue::get` 调用本符号
    #   - 内部调用：`order.index`、`len`、`range`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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

    # 功能：实现 `task_done` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `process_queued_item`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_worker_get_fairly_selects_late_department_after_general_backlog`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_worker_get_fairly_selects_late_camera_after_camera_backlog`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_scanner_unifies_recovered_and_pending_with_one_prefetch_per_camera` 调用本符号；另有 3 处静态调用
    #   - 内部调用：`ValueError`、`self._condition.notify_all`。
    # 副作用/注意事项：会更新当前实例的运行状态；校验或执行失败时会主动抛出异常。
    def task_done(self) -> None:
        with self._condition:
            if self._unfinished_tasks <= 0:
                raise ValueError("task_done() called too many times")
            self._unfinished_tasks -= 1
            if self._unfinished_tasks == 0:
                self._condition.notify_all()

    # 功能：实现 `join` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `_load_banner_font`
    #         调用本符号；`AiVision/platform/visual_services/managed.py` 的 `ManagedVisualServices::_validate_config_paths`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的 `_write_config`
    #         调用本符号；`AiVision/platform/violation/service.py` 的 `AsyncViolationWriter::stop` 调用本符号；另有 32 处静态调用
    #   - 内部调用：`self._condition.wait`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def join(self) -> None:
        with self._condition:
            while self._unfinished_tasks:
                self._condition.wait()

    # 功能：实现 `unfinished_tasks` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def unfinished_tasks(self) -> int:
        with self._condition:
            return self._unfinished_tasks

    # 功能：实现 `qsize` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentFairTaskQueue::empty`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_scanner_unifies_recovered_and_pending_with_one_prefetch_per_camera`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_worker.py` 的
    #         `test_department_fair_queue_concurrent_semantics_and_counts` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def qsize(self) -> int:
        with self._condition:
            return self._qsize

    # 功能：实现 `empty` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_scanner_rejects_and_cleans_unknown_department_pending`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_department_scanner_uses_exact_root_and_does_not_scan_nested_decoy`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_worker.py` 的
    #         `test_department_fair_queue_concurrent_semantics_and_counts`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_worker.py` 的
    #         `test_shutdown_drains_task_put_after_global_stop_during_scanner_scan` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`self.qsize`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def empty(self) -> bool:
        return self.qsize() == 0

    # 功能：实现 `full` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_frame_hub.py` 的
    #         `test_frame_hub_resolution_change_keeps_old_mapping_safe`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_frame_hub.py` 的
    #         `test_frame_hub_reader_retries_when_meta_precedes_slots` 调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_inactive_detection_window_still_composes_live_preview_frames`
    #         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_alarm_incident_reopens_after_recovery_without_resetting_cooldown` 调用本符号；另有 3 处静态调用
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def full(self) -> bool:
        return False

    # 功能：检查或判断 `has_queued` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_has_prefetched_task` 调用本符号
    #   - 内部调用：`require_department`、`validate_camera_id`、`bool`、`self._queues[department].get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def has_queued(self, department: str, camera_id: str) -> bool:
        department = require_department(department)
        camera_id = validate_camera_id(camera_id)
        with self._condition:
            return bool(self._queues[department].get(camera_id))

    # 功能：实现 `department_counts` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict[str, int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `queued_department_counts` 调用本符号
    #   - 内部调用：`sum`、`len`、`department_queues.values`、`self._queues.items`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def department_counts(self) -> dict[str, int]:
        with self._condition:
            return {
                department: sum(
                    len(camera_queue)
                    for camera_queue in department_queues.values()
                )
                for department, department_queues in self._queues.items()
            }


# 功能：兼容旧 pending；缺少事业部时归入通用电气；输入与输出详见下方说明
# 参数：
#   - `payload`（dict）：接口或事件携带的业务数据
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `validate_pending_payload_department` 调用本符号
#   - 内部调用：`require_department`、`payload.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def payload_department(payload: dict) -> str:
    """兼容旧 pending；缺少事业部时归入通用电气。"""
    return require_department(
        payload.get("department", SECURITY_DEPARTMENTS[0])
    )


# 功能：返回 pending 来源事业部及其是否属于新版事业部目录；输入与输出详见下方说明
# 参数：
#   - `pending_dir`（Path）：`pending_dir` 对应的业务输入值
# 返回：tuple[str, bool]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `MultiCameraPendingScanner::pending_dirs`
#         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `MultiCameraPendingScanner::_processing_dir_for` 调用本符号
#   - 内部调用：`Path`、`ValueError`、`require_department`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def pending_directory_origin(pending_dir: Path) -> tuple[str, bool]:
    """返回 pending 来源事业部及其是否属于新版事业部目录。"""
    path = Path(pending_dir)
    cameras_dir = path.parent.parent
    if path.name != "pending" or cameras_dir.name != "cameras":
        raise ValueError(f"无效 pending 目录结构: {path}")
    department_dir = cameras_dir.parent
    if department_dir.parent.name == "departments":
        return require_department(department_dir.name), True
    return SECURITY_DEPARTMENTS[0], False


# 功能：从持久化 processing 路径恢复任务来源事业部；输入与输出详见下方说明
# 参数：
#   - `processing_dir`（Path）：`processing_dir` 对应的业务输入值
# 返回：tuple[str, bool]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `validate_pending_payload_department`
#         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `MultiCameraPendingScanner::processing_dirs` 调用本符号
#   - 内部调用：`Path`、`ValueError`、`require_department`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def processing_directory_origin(processing_dir: Path) -> tuple[str, bool]:
    """从持久化 processing 路径恢复任务来源事业部。"""
    path = Path(processing_dir)
    if path.name != "processing" or path.parent.name != "global":
        raise ValueError(f"无效 processing 目录结构: {path}")
    department_dir = path.parent.parent
    if department_dir.parent.name == "departments":
        return require_department(department_dir.name), True
    return SECURITY_DEPARTMENTS[0], False


# 功能：以 processing 路径为准校验 payload 事业部，兼容旧全局任务；输入与输出详见下方说明
# 参数：
#   - `payload`（dict）：接口或事件携带的业务数据
#   - `task_path`（Path）：`task_path` 对应的业务输入值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `normalize_pending_payload` 调用本符号
#   - 内部调用：`isinstance`、`ValueError`、`Path`、`payload_department`、`processing_directory_origin`、`require_department`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
def validate_pending_payload_department(payload: dict, task_path: Path) -> str:
    """以 processing 路径为准校验 payload 事业部，兼容旧全局任务。"""
    if not isinstance(payload, dict):
        raise ValueError("pending payload 必须是字典")
    task_parent = Path(task_path).parent
    if (
        task_parent.name != "processing"
        or task_parent.parent.name != "global"
    ):
        return payload_department(payload)
    source_department, department_scoped = processing_directory_origin(
        task_parent
    )
    if not department_scoped:
        return payload_department(payload)
    if "department" not in payload:
        raise ValueError(
            f"新版 pending payload 缺少 department: {task_path}"
        )
    declared_department = require_department(payload["department"])
    if declared_department != source_department:
        raise ValueError(
            "pending payload department 与来源事业部不一致: "
            f"来源 {source_department}, payload {declared_department}"
        )
    return source_department


# 功能：删除无法安全归属的任务及恢复标记，避免重启后无限重试；输入与输出详见下方说明
# 参数：
#   - `task_path`（Path | PendingTask）：`task_path` 对应的业务输入值
#   - `reason`（Exception）：`reason` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `load_validated_pending_task`
#         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_cleanup_unknown_departments`
#         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_existing_tasks_by_camera`
#         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_pending_candidates_by_camera`
#         调用本符号；另有 1 处静态调用
#   - 内部调用：`isinstance`、`Path`、`print`、`path.with_suffix`、`target.unlink`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：实现 `_finite_pending_timestamp` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（dict）：接口或事件携带的业务数据
#   - `field_name`（str）：`field_name` 对应的业务输入值
#   - `default`（float）：`default` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `normalize_pending_payload` 调用本符号
#   - 内部调用：`payload.get`、`isinstance`、`TypeError`、`float`、`ValueError`、`math.isfinite`、`datetime.fromtimestamp`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：实现 `_safe_pending_identifier` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（Any）：待转换、校验或写入的值
#   - `field_name`（str）：`field_name` 对应的业务输入值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `normalize_pending_payload`
#         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentAccumulator::record` 调用本符号
#   - 内部调用：`isinstance`、`value.strip`、`ValueError`、`len`、`Path`、`any`、`ord`、`character.isascii`、`character.isalnum`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：校验并规范化 process_one 后续会使用的 pending 字段；输入与输出详见下方说明
# 参数：
#   - `payload`（dict）：接口或事件携带的业务数据
#   - `task_path`（Path | PendingTask）：`task_path` 对应的业务输入值
#   - `now_ts`（float | None）：`now_ts` 对应的业务输入值；默认值为 `None`
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `load_validated_pending_task` 调用本符号
#   - 内部调用：`isinstance`、`Path`、`ValueError`、`require_department`、`validate_pending_payload_department`、`time.time`、`float`、`dict`、`_safe_pending_identifier`、`validate_camera_id`
#          等共 15 个调用。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def normalize_pending_payload(
    payload: dict,
    task_path: Path | PendingTask,
    *,
    now_ts: float | None = None,
) -> dict:
    """校验并规范化 process_one 后续会使用的 pending 字段。"""
    trusted_task = task_path if isinstance(task_path, PendingTask) else None
    path = trusted_task.path if trusted_task is not None else Path(task_path)
    if not isinstance(payload, dict):
        raise ValueError("pending payload 必须是字典")
    if trusted_task is not None:
        if trusted_task.legacy:
            if (
                "department" in payload
                and require_department(payload["department"])
                != SECURITY_DEPARTMENTS[0]
            ):
                raise ValueError("旧版 pending 任务只能归属 general_electric")
            department = SECURITY_DEPARTMENTS[0]
        else:
            if "department" not in payload:
                raise ValueError("新版 pending payload 缺少 department")
            department = require_department(payload["department"])
            if department != trusted_task.department:
                raise ValueError(
                    "pending payload department 与来源路径不一致"
                )
    else:
        department = validate_pending_payload_department(payload, path)
    if "session_id" not in payload:
        raise ValueError("pending payload 缺少 session_id")
    current_ts = time.time() if now_ts is None else float(now_ts)
    normalized = dict(payload)
    normalized["department"] = department
    normalized["session_id"] = _safe_pending_identifier(
        payload["session_id"],
        "session_id",
    )
    declared_camera_id = validate_camera_id(
        payload.get(
            "camera_id",
            trusted_task.camera_id if trusted_task is not None else "legacy-default",
        )
    )
    if trusted_task is not None and declared_camera_id != trusted_task.camera_id:
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


# 功能：读取并校验 pending；坏任务立即丢弃，调用方必须在 None 时早退；输入与输出详见下方说明
# 参数：
#   - `task_path`（Path | PendingTask）：`task_path` 对应的业务输入值
# 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTaskProcessor::process` 调用本符号
#   - 内部调用：`isinstance`、`Path`、`path.open`、`pickle.load`、`normalize_pending_payload`、`discard_invalid_pending_task`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def load_validated_pending_task(
    task_path: Path | PendingTask,
) -> dict | None:
    """读取并校验 pending；坏任务立即丢弃，调用方必须在 None 时早退。"""
    path = task_path.path if isinstance(task_path, PendingTask) else Path(task_path)
    try:
        with path.open("rb") as file:
            payload = pickle.load(file)
        return normalize_pending_payload(payload, task_path)
    except Exception as exc:
        # pickle 反序列化可能传播导入/属性等多种异常；统一记录并丢弃，
        # 防止 processing 中的坏文件在每次重启后再次进入队列。
        discard_invalid_pending_task(path, exc)
        return None


# 功能：更新或保存 `atomic_write_json` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
#   - `payload`（Dict[str, Any]）：接口或事件携带的业务数据
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Path`、`target.parent.mkdir`、`target.with_name`、`uuid.uuid4`、`temp_path.write_text`、`json.dumps`、`temp_path.replace`、`temp_path.unlink`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：实现 `_signal_handler` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `signum`（未显式标注）：`signum` 对应的业务输入值
#   - `frame`（未显式标注）：待处理的视频图像帧
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_STOP.set`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _signal_handler(signum, frame):
    _STOP.set()


# ---------------------------------------------------------------------------
# 预算守护
# ---------------------------------------------------------------------------
# 功能：按"次数 * 单价"估算每日开销, 超出 daily_limit 拒绝调用；输入与输出详见下方说明
# 参数：
#   - `daily_limit`（float）：`daily_limit` 对应的业务输入值
#   - `est_cost_per_call`（float）：`est_cost_per_call` 对应的业务输入值
#   - `initial_state`（Dict[str, Any] | None）：`initial_state` 对应的业务输入值；默认值为 `None`
#   - `on_change`（未显式标注）：`on_change` 对应的业务输入值；默认值为 `None`
# 返回：BudgetGuard；返回新建的 `BudgetGuard` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class BudgetGuard:
    """
    按"次数 * 单价"估算每日开销, 超出 daily_limit 拒绝调用。
    跨天自动重置 (检查日期字符串)。
    线程安全 (内部用 lock)。
    """

    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `daily_limit`（float）：`daily_limit` 对应的业务输入值
    #   - `est_cost_per_call`（float）：`est_cost_per_call` 对应的业务输入值
    #   - `initial_state`（Dict[str, Any] | None）：`initial_state` 对应的业务输入值；默认值为 `None`
    #   - `on_change`（未显式标注）：`on_change` 对应的业务输入值；默认值为 `None`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`float`、`datetime.now().strftime`、`datetime.now`、`threading.Lock`、`str`、`initial.get`、`max`、`int`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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

    # 功能：成功扣费 → True; 超预算 → False (调用方应放弃本次调用)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `VLMJudge::judge`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_worker.py` 的
    #         `test_budget_guard_restores_same_day_and_persists_each_consumption`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_worker.py` 的
    #         `test_budget_persistence_snapshots_never_move_backwards_under_concurrency` 调用本符号
    #   - 内部调用：`datetime.now().strftime`、`datetime.now`、`self.on_change`、`self._snapshot_unlocked`。
    # 副作用/注意事项：会更新当前实例的运行状态。
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
            if self.on_change is not None:
                # 与计数更新共用同一把锁，确保并发持久化不会以旧快照覆盖新快照。
                self.on_change(self._snapshot_unlocked())
            return True

    # 功能：实现 `snapshot` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：Dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._snapshot_unlocked`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return self._snapshot_unlocked()

    # 功能：实现 `_snapshot_unlocked` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：Dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `BudgetGuard::try_consume`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `BudgetGuard::snapshot` 调用本符号
    #   - 内部调用：`round`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
# 功能：封装 dashscope 多模态调用:；输入与输出详见下方说明
# 参数：
#   - `cfg`（Dict[str, Any]）：运行配置对象
#   - `budget`（BudgetGuard）：`budget` 对应的业务输入值
#   - `tmp_dir`（Path）：`tmp_dir` 对应的业务输入值
# 返回：VLMJudge；返回新建的 `VLMJudge` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class VLMJudge:
    """
    封装 dashscope 多模态调用:
    1) 把每张关键帧 resize + 写到临时 jpg
    2) 拼成 messages, 调 MultiModalConversation.call
    3) 解析返回的 JSON (兼容 markdown 包裹)
    4) try-finally 删临时 jpg, 不留垃圾
    """

    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `cfg`（Dict[str, Any]）：运行配置对象
    #   - `budget`（BudgetGuard）：`budget` 对应的业务输入值
    #   - `tmp_dir`（Path）：`tmp_dir` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`int`、`cfg['vlm'].get`、`float`、`Path`、`self.tmp_dir.mkdir`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件。
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

    # 功能：临时 jpg, dashscope 用 file:// 协议读；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    #   - `session_id`（str）：`session_id` 对应业务对象的唯一标识
    #   - `idx`（int）：`idx` 对应的业务输入值
    #   - `department`（str）：业务部门名称或标识
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `VLMJudge::judge` 调用本符号
    #   - 内部调用：`require_department`、`department_dir.mkdir`、`max`、`cv2.resize`、`int`、`cv2.imwrite`、`str`、`path.absolute`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def _save_frame(
        self,
        frame: np.ndarray,
        session_id: str,
        idx: int,
        department: str,
    ) -> str:
        """临时 jpg, dashscope 用 file:// 协议读"""
        department_dir = self.tmp_dir / require_department(department)
        department_dir.mkdir(parents=True, exist_ok=True)
        path = department_dir / f"{session_id}_{idx}.jpg"
        h, w = frame.shape[:2]
        if max(h, w) > self.image_max_side:
            s = self.image_max_side / max(h, w)
            frame = cv2.resize(frame, (int(w * s), int(h * s)))
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, self.image_quality])
        return str(path.absolute())

    # 功能：返回 dict:；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `session_id`（str）：`session_id` 对应业务对象的唯一标识
    #   - `roi_name`（str）：`roi_name` 对应的业务输入值
    #   - `roi_box`（List[float]）：`roi_box` 对应的业务输入值
    #   - `keyframes`（List[np.ndarray]）：`keyframes` 对应的业务输入值
    #   - `department`（str）：业务部门名称或标识；默认值为 `SECURITY_DEPARTMENTS[0]`
    # 返回：Dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTaskProcessor::_process_locked`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_worker.py` 的 `test_vlm_judge_passes_request_timeout` 调用本符号
    #   - 内部调用：`self.budget.try_consume`、`enumerate`、`paths.append`、`self._save_frame`、`user_content.append`、`VLM_USER_PROMPT.format`、`len`、`time.time`、`self.MMC.call`、`round`
    #          等共 16 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def judge(
        self,
        session_id: str,
        roi_name: str,
        roi_box: List[float],
        keyframes: List[np.ndarray],
        *,
        department: str = SECURITY_DEPARTMENTS[0],
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
                paths.append(
                    self._save_frame(fr, session_id, i, department)
                )

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

    # 功能：尽力解析模型返回的 JSON:；输入与输出详见下方说明
    # 参数：
    #   - `text`（str）：`text` 对应的业务输入值
    # 返回：Optional[Dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `VLMJudge::judge` 调用本符号
    #   - 内部调用：`text.strip`、`t.startswith`、`t.split`、`len`、`t.lstrip().startswith`、`t.lstrip`、`t.strip`、`json.loads`、`t.index`、`t.rindex`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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
# 功能：后台线程: 周期 glob pending_queue_dir/*.pkl, 把新文件丢进 task_q；输入与输出详见下方说明
# 参数：
#   - `pending_dir`（Path）：`pending_dir` 对应的业务输入值
#   - `q`（queue.Queue）：`q` 对应的业务输入值
#   - `poll_sec`（float）：`poll_sec` 对应的业务输入值；默认值为 `0.5`
# 返回：PendingScanner；返回新建的 `PendingScanner` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class PendingScanner(threading.Thread):
    """
    后台线程: 周期 glob pending_queue_dir/*.pkl, 把新文件丢进 task_q。
    用 self.seen 集合去重, 避免重复入队。
    """

    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `pending_dir`（Path）：`pending_dir` 对应的业务输入值
    #   - `q`（queue.Queue）：`q` 对应的业务输入值
    #   - `poll_sec`（float）：`poll_sec` 对应的业务输入值；默认值为 `0.5`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().__init__`、`super`、`set`、`threading.Event`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(self, pending_dir: Path, q: queue.Queue, poll_sec: float = 0.5):
        super().__init__(daemon=True)
        self.pending_dir = pending_dir
        self.q = q
        self.poll_sec = poll_sec
        self.seen: set = set()
        self._stop_event = threading.Event()

    # 功能：启动或执行 `run` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.is_set`、`sorted`、`self.pending_dir.glob`、`self.seen.add`、`self.q.put`、`print`、`self._stop_event.wait`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：停止并释放 `stop` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.set`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def stop(self):
        self._stop_event.set()


# 功能：按事业部、再按摄像头轮询，并原子认领到无歧义 processing 路径；输入与输出详见下方说明
# 参数：
#   - `departments_root`（Path）：`departments_root` 对应的业务输入值
#   - `q`（queue.Queue）：`q` 对应的业务输入值
#   - `poll_sec`（float）：`poll_sec` 对应的业务输入值；默认值为 `0.5`
#   - `legacy_camera_root`（Path | None）：`legacy_camera_root` 对应的业务输入值；默认值为 `None`
# 返回：DepartmentPendingScanner；返回新建的 `DepartmentPendingScanner` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DepartmentPendingScanner(threading.Thread):
    """按事业部、再按摄像头轮询，并原子认领到无歧义 processing 路径。"""

    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `departments_root`（Path）：`departments_root` 对应的业务输入值
    #   - `q`（queue.Queue）：`q` 对应的业务输入值
    #   - `poll_sec`（float）：`poll_sec` 对应的业务输入值；默认值为 `0.5`
    #   - `legacy_camera_root`（Path | None）：`legacy_camera_root` 对应的业务输入值；默认值为 `None`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().__init__`、`super`、`Path`、`set`、`threading.Event`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(
        self,
        departments_root: Path,
        q: queue.Queue,
        poll_sec: float = 0.5,
        *,
        legacy_camera_root: Path | None = None,
    ):
        super().__init__(daemon=True)
        self.departments_root = Path(departments_root)
        self.legacy_camera_root = (
            Path(legacy_camera_root)
            if legacy_camera_root is not None
            else None
        )
        self.q = q
        self.poll_sec = poll_sec
        self.seen: set[str] = set()
        self._department_cursor = 0
        self._last_scanned_camera: dict[str, str | None] = {
            department: None for department in SECURITY_DEPARTMENTS
        }
        self._source_cursors: dict[tuple[str, str], bool] = {}
        self._stop_event = threading.Event()

    # 功能：实现 `pending_dirs` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：list[Path]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_all_existing_paths` 调用本符号
    #   - 内部调用：`directories.extend`、`sorted`、`cameras_dir.glob`、`path.is_dir`、`self.legacy_camera_root.glob`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def pending_dirs(self) -> list[Path]:
        directories = []
        for department in SECURITY_DEPARTMENTS:
            cameras_dir = self.departments_root / department / "cameras"
            directories.extend(
                path
                for path in sorted(cameras_dir.glob("*/pending"))
                if path.is_dir()
            )
        if self.legacy_camera_root is not None:
            directories.extend(
                path
                for path in sorted(self.legacy_camera_root.glob("*/pending"))
                if path.is_dir()
            )
        return directories

    # 功能：实现 `processing_dirs` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：list[Path]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_all_existing_paths` 调用本符号
    #   - 内部调用：`directories.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def processing_dirs(self) -> list[Path]:
        directories = [
            self.departments_root / department / "global" / "processing"
            for department in SECURITY_DEPARTMENTS
        ]
        if self.legacy_camera_root is not None:
            directories.append(
                self.legacy_camera_root.parent / "global" / "processing"
            )
        return directories

    # 功能：实现 `_identity` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `path`（Path）：目标路径
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_all_existing_paths`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_existing_tasks_by_camera`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::scan_once` 调用本符号
    #   - 内部调用：`str`、`path.resolve`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _identity(path: Path) -> str:
        return str(path.resolve())

    # 功能：实现 `_all_existing_paths` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：set[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::scan_once` 调用本符号
    #   - 内部调用：`self._identity`、`self.pending_dirs`、`pending_dir.glob`、`self.processing_dirs`、`paths.update`、`processing_dir.glob`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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

    # 功能：删除或清理 `_cleanup_unknown_departments` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::scan_once` 调用本符号
    #   - 内部调用：`self.departments_root.is_dir`、`self.departments_root.iterdir`、`department_dir.is_dir`、`ValueError`、`department_dir.glob`、`discard_invalid_pending_task`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _cleanup_unknown_departments(self) -> None:
        if not self.departments_root.is_dir():
            return
        for department_dir in self.departments_root.iterdir():
            if (
                not department_dir.is_dir()
                or department_dir.name in SECURITY_DEPARTMENTS
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

    # 功能：实现 `_flat_processing_task` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `path`（Path）：目标路径
    #   - `legacy`（bool）：`legacy` 对应的业务输入值
    # 返回：PendingTask；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_existing_tasks_by_camera` 调用本符号
    #   - 内部调用：`path.open`、`pickle.load`、`validate_camera_id`、`payload.get`、`path.name.startswith`、`PendingTask`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
    def _flat_processing_task(
        self,
        department: str,
        path: Path,
        *,
        legacy: bool,
    ) -> PendingTask:
        camera_id = "legacy-default"
        try:
            with path.open("rb") as file:
                payload = pickle.load(file)
            declared = validate_camera_id(payload.get("camera_id", camera_id))
            if legacy or path.name.startswith(f"{declared}__"):
                camera_id = declared
        except Exception:
            # 坏任务仍需入队，由统一校验路径负责记录并清理。
            pass
        return PendingTask(department, camera_id, path, legacy=legacy)

    # 功能：实现 `_existing_tasks_by_camera` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：dict[str, PendingTask]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_next_candidate` 调用本符号
    #   - 内部调用：`sorted`、`processing_dir.glob`、`self._identity`、`tasks.append`、`PendingTask`、`discard_invalid_pending_task`、`tasks.extend`、`self._flat_processing_task`、`legacy_processing.glob`、`tasks_by_camera.setdefault(task.camera_id,
    #          []).append` 等共 12 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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
        tasks.extend(
            self._flat_processing_task(department, path, legacy=False)
            for path in sorted(processing_dir.glob("*.pkl"))
            if self._identity(path) not in self.seen
        )
        if department == SECURITY_DEPARTMENTS[0] and self.legacy_camera_root is not None:
            legacy_processing = (
                self.legacy_camera_root.parent / "global" / "processing"
            )
            for path in sorted(legacy_processing.glob("*/*.pkl")):
                if self._identity(path) in self.seen:
                    continue
                try:
                    tasks.append(PendingTask(
                        department,
                        path.parent.name,
                        path,
                        legacy=True,
                    ))
                except ValueError as exc:
                    discard_invalid_pending_task(path, exc)
            tasks.extend(
                self._flat_processing_task(department, path, legacy=True)
                for path in sorted(legacy_processing.glob("*.pkl"))
                if self._identity(path) not in self.seen
            )
        tasks_by_camera: dict[str, list[PendingTask]] = {}
        for task in tasks:
            tasks_by_camera.setdefault(task.camera_id, []).append(task)
        return {
            camera_id: camera_tasks[0]
            for camera_id, camera_tasks in tasks_by_camera.items()
        }

    # 功能：实现 `_pending_camera_dirs` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：list[tuple[Path, bool]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_pending_candidates_by_camera`
    #         调用本符号
    #   - 内部调用：`sorted`、`(self.departments_root / department /
    #          'cameras').glob`、`path.is_dir`、`any`、`path.glob`、`directories.extend`、`self.legacy_camera_root.glob`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _pending_camera_dirs(self, department: str) -> list[tuple[Path, bool]]:
        directories = [
            (path, False)
            for path in sorted(
                (
                    self.departments_root
                    / department
                    / "cameras"
                ).glob("*/pending")
            )
            if path.is_dir() and any(path.glob("*.pkl"))
        ]
        if (
            department == SECURITY_DEPARTMENTS[0]
            and self.legacy_camera_root is not None
        ):
            directories.extend(
                (path, True)
                for path in sorted(self.legacy_camera_root.glob("*/pending"))
                if path.is_dir() and any(path.glob("*.pkl"))
            )
        return directories

    # 功能：实现 `_pending_candidates_by_camera` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：dict[str, tuple[Path, bool]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_next_candidate` 调用本符号
    #   - 内部调用：`self._pending_camera_dirs`、`validate_camera_id`、`pending_dir.glob`、`discard_invalid_pending_task`、`candidates.setdefault`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _pending_candidates_by_camera(
        self,
        department: str,
    ) -> dict[str, tuple[Path, bool]]:
        candidates = {}
        for pending_dir, legacy in self._pending_camera_dirs(department):
            try:
                camera_id = validate_camera_id(pending_dir.parent.name)
            except ValueError as exc:
                for invalid_path in pending_dir.glob("*.pkl"):
                    discard_invalid_pending_task(invalid_path, exc)
                continue
            candidates.setdefault(camera_id, (pending_dir, legacy))
        return candidates

    # 功能：实现 `_claim_pending_dir` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `camera_id`（str）：摄像头唯一标识
    #   - `pending_dir`（Path）：`pending_dir` 对应的业务输入值
    #   - `legacy`（bool）：`legacy` 对应的业务输入值
    # 返回：PendingTask | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_next_candidate` 调用本符号
    #   - 内部调用：`self._stop_event.is_set`、`next`、`iter`、`sorted`、`pending_dir.glob`、`processing_dir.mkdir`、`target.exists`、`time.time_ns`、`source.replace`、`PendingTask`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
    def _claim_pending_dir(
        self,
        department: str,
        camera_id: str,
        pending_dir: Path,
        legacy: bool,
    ) -> PendingTask | None:
        if self._stop_event.is_set():
            return None
        source = next(iter(sorted(pending_dir.glob("*.pkl"))), None)
        if source is None:
            return None
        processing_dir = (
            (
                self.legacy_camera_root.parent
                if legacy and self.legacy_camera_root is not None
                else self.departments_root / department
            )
            / "global"
            / "processing"
            / camera_id
        )
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
        return PendingTask(department, camera_id, target, legacy=legacy)

    # 功能：检查或判断 `_has_prefetched_task` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::_next_candidate` 调用本符号
    #   - 内部调用：`getattr`、`bool`、`callable`、`has_queued`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _has_prefetched_task(self, department: str, camera_id: str) -> bool:
        has_queued = getattr(self.q, "has_queued", None)
        return bool(
            callable(has_queued)
            and has_queued(department, camera_id)
        )

    # 功能：实现 `_next_candidate` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：PendingTask | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::scan_once` 调用本符号
    #   - 内部调用：`self._existing_tasks_by_camera`、`self._pending_candidates_by_camera`、`sorted`、`set`、`self._has_prefetched_task`、`camera_ids.index`、`len`、`next`、`enumerate`、`recovered.get`
    #          等共 13 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务。
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
                *pending_candidate,
            )
            if task is not None:
                return task
        if recovered_task is not None:
            return recovered_task
        if pending_candidate is not None:
            return self._claim_pending_dir(
                department,
                camera_id,
                *pending_candidate,
            )
        return None

    # 功能：实现 `scan_once` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentPendingScanner::run` 调用本符号
    #   - 内部调用：`self._stop_event.is_set`、`self._cleanup_unknown_departments`、`self.seen.intersection_update`、`self._all_existing_paths`、`len`、`list`、`self._next_candidate`、`self._identity`、`self.seen.add`、`self.seen.discard`
    #          等共 11 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def scan_once(self) -> None:
        if self._stop_event.is_set():
            return
        self._cleanup_unknown_departments()
        self.seen.intersection_update(self._all_existing_paths())
        offset = self._department_cursor % len(SECURITY_DEPARTMENTS)
        departments = (
            list(SECURITY_DEPARTMENTS[offset:])
            + list(SECURITY_DEPARTMENTS[:offset])
        )
        self._department_cursor = (offset + 1) % len(SECURITY_DEPARTMENTS)
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

    # 功能：启动或执行 `run` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.is_set`、`self.scan_once`、`print`、`self._stop_event.wait`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：停止并释放 `stop` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.set`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def stop(self) -> None:
        self._stop_event.set()


# 功能：以轮询顺序扫描所有摄像头的 pending 队列；输入与输出详见下方说明
# 参数：
#   - `camera_root`（Path）：`camera_root` 对应的业务输入值
#   - `q`（queue.Queue）：`q` 对应的业务输入值
#   - `poll_sec`（float）：`poll_sec` 对应的业务输入值；默认值为 `0.5`
#   - `processing_dir`（Path | None）：`processing_dir` 对应的业务输入值；默认值为 `None`
# 返回：MultiCameraPendingScanner；返回新建的 `MultiCameraPendingScanner` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class MultiCameraPendingScanner(threading.Thread):
    """以轮询顺序扫描所有摄像头的 pending 队列。"""

    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_root`（Path）：`camera_root` 对应的业务输入值
    #   - `q`（queue.Queue）：`q` 对应的业务输入值
    #   - `poll_sec`（float）：`poll_sec` 对应的业务输入值；默认值为 `0.5`
    #   - `processing_dir`（Path | None）：`processing_dir` 对应的业务输入值；默认值为 `None`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().__init__`、`super`、`Path`、`self.processing_dir.mkdir`、`set`、`threading.Event`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
    def __init__(
        self,
        camera_root: Path,
        q: queue.Queue,
        poll_sec: float = 0.5,
        processing_dir: Path | None = None,
    ):
        super().__init__(daemon=True)
        self.camera_root = Path(camera_root)
        self.processing_dir = (
            Path(processing_dir)
            if processing_dir is not None
            else (
                self.camera_root.parent
                if self.camera_root.name == "cameras"
                else self.camera_root
            )
            / "global"
            / "processing"
        )
        self.processing_dir.mkdir(parents=True, exist_ok=True)
        self.q = q
        self.poll_sec = poll_sec
        self.seen: set[str] = set()
        self._camera_cursor = 0
        self._stop_event = threading.Event()
        self._invalid_source_warnings: set[str] = set()

    # 功能：实现 `pending_dirs` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：list[Path]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `MultiCameraPendingScanner::processing_dirs`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `MultiCameraPendingScanner::scan_once` 调用本符号
    #   - 内部调用：`self.camera_root.glob`、`path.is_dir`、`sorted`、`pending_directory_origin`、`self._warn_invalid_source`、`path.glob`、`discard_invalid_pending_task`、`accepted.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def pending_dirs(self) -> list[Path]:
        if self.camera_root.name == "cameras":
            patterns = ("*/pending",)
        elif self.camera_root.name == "departments":
            patterns = ("*/cameras/*/pending",)
        else:
            patterns = (
                "cameras/*/pending",
                "departments/*/cameras/*/pending",
            )
        candidates = {
            path
            for pattern in patterns
            for path in self.camera_root.glob(pattern)
            if path.is_dir()
        }
        accepted = []
        for path in sorted(candidates):
            try:
                pending_directory_origin(path)
            except ValueError as exc:
                self._warn_invalid_source(path, exc)
                for task_path in path.glob("*.pkl"):
                    discard_invalid_pending_task(task_path, exc)
                continue
            accepted.append(path)
        return accepted

    # 功能：实现 `processing_dirs` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `pending_dirs`（list[Path] | None）：`pending_dirs` 对应的业务输入值；默认值为 `None`
    # 返回：list[Path]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `MultiCameraPendingScanner::scan_once` 调用本符号
    #   - 内部调用：`self.pending_dirs`、`discovered.add`、`self._processing_dir_for`、`patterns.append`、`self.camera_root.glob`、`path.is_dir`、`processing_directory_origin`、`self._warn_invalid_source`、`sorted`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def processing_dirs(self, pending_dirs: list[Path] | None = None) -> list[Path]:
        discovered = {self.processing_dir}
        for pending_dir in pending_dirs or self.pending_dirs():
            discovered.add(self._processing_dir_for(pending_dir))
        patterns = ["global/processing"]
        if self.camera_root.name == "departments":
            patterns.append("*/global/processing")
        elif self.camera_root.name != "cameras":
            patterns.append("departments/*/global/processing")
        for pattern in patterns:
            for path in self.camera_root.glob(pattern):
                if not path.is_dir():
                    continue
                try:
                    processing_directory_origin(path)
                except ValueError as exc:
                    self._warn_invalid_source(path, exc)
                    continue
                discovered.add(path)
        return sorted(discovered)

    # 功能：实现 `_processing_dir_for` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `pending_dir`（Path）：`pending_dir` 对应的业务输入值
    # 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `MultiCameraPendingScanner::processing_dirs`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `MultiCameraPendingScanner::scan_once` 调用本符号
    #   - 内部调用：`pending_directory_origin`、`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def _processing_dir_for(self, pending_dir: Path) -> Path:
        department, department_scoped = pending_directory_origin(pending_dir)
        if department_scoped:
            department_root = pending_dir.parent.parent.parent
            if department_root.name != department:
                raise ValueError("pending 来源事业部路径不一致")
            return department_root / "global" / "processing"
        return self.processing_dir

    # 功能：实现 `_warn_invalid_source` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `path`（Path）：目标路径
    #   - `exc`（Exception）：`exc` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `MultiCameraPendingScanner::pending_dirs`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `MultiCameraPendingScanner::processing_dirs` 调用本符号
    #   - 内部调用：`str`、`Path(path).absolute`、`Path`、`self._invalid_source_warnings.add`、`print`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _warn_invalid_source(self, path: Path, exc: Exception) -> None:
        identity = str(Path(path).absolute())
        if identity in self._invalid_source_warnings:
            return
        self._invalid_source_warnings.add(identity)
        print(
            f"[vlm-scan] 忽略无效事业部目录 {path}: {exc}",
            file=sys.stderr,
            flush=True,
        )

    # 功能：实现 `scan_once` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `MultiCameraPendingScanner::run` 调用本符号
    #   - 内部调用：`self.pending_dirs`、`self.processing_dirs`、`str`、`path.resolve`、`processing_dir.glob`、`pending_dir.glob`、`self.seen.intersection_update`、`sorted`、`self.seen.add`、`self.q.put`
    #          等共 17 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
    def scan_once(self) -> None:
        pending_dirs = self.pending_dirs()
        processing_dirs = self.processing_dirs(pending_dirs)
        existing = {
            str(path.resolve())
            for path in (
                [
                    processing_path
                    for processing_dir in processing_dirs
                    for processing_path in processing_dir.glob("*.pkl")
                ]
                + [
                    pending_path
                    for pending_dir in pending_dirs
                    for pending_path in pending_dir.glob("*.pkl")
                ]
            )
        }
        self.seen.intersection_update(existing)
        for processing_dir in processing_dirs:
            for path in sorted(processing_dir.glob("*.pkl")):
                identity = str(path.resolve())
                if identity not in self.seen:
                    self.seen.add(identity)
                    self.q.put(path)

        if not pending_dirs:
            return
        offset = self._camera_cursor % len(pending_dirs)
        ordered_dirs = pending_dirs[offset:] + pending_dirs[:offset]
        self._camera_cursor = (offset + 1) % len(pending_dirs)

        for pending_dir in ordered_dirs:
            for path in sorted(pending_dir.glob("*.pkl")):
                identity = str(path.resolve())
                if identity in self.seen:
                    continue
                camera_id = pending_dir.parent.name
                processing_dir = self._processing_dir_for(pending_dir)
                processing_dir.mkdir(parents=True, exist_ok=True)
                claimed_path = processing_dir / f"{camera_id}__{path.name}"
                if claimed_path.exists():
                    claimed_path = processing_dir / (
                        f"{camera_id}__{time.time_ns()}__{path.name}"
                    )
                try:
                    path.replace(claimed_path)
                except FileNotFoundError:
                    continue
                claimed_identity = str(claimed_path.resolve())
                self.seen.add(claimed_identity)
                self.q.put(claimed_path)
                break

    # 功能：启动或执行 `run` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.is_set`、`self.scan_once`、`print`、`self._stop_event.wait`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def run(self):
        while not self._stop_event.is_set():
            try:
                self.scan_once()
            except Exception as exc:
                print(f"[vlm-scan] 多摄像头扫描异常: {exc}", flush=True)
            self._stop_event.wait(self.poll_sec)

    # 功能：停止并释放 `stop` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.set`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def stop(self):
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


# 功能：读取或查询 `_load_banner_font` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `font_size`（int）：`font_size` 对应的数量或大小
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `_draw_text_pil` 调用本符号
#   - 内部调用：`ImageFont.truetype`、`errors.append`、`print`、`'; '.join`、`ImageFont.load_default`。
# 副作用/注意事项：会修改全局或闭包状态；可能启动、等待或停止线程/进程资源。
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


# 功能：绘制或渲染 `_draw_text_pil` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `img_bgr`（未显式标注）：`img_bgr` 对应的业务输入值
#   - `text`（未显式标注）：`text` 对应的业务输入值
#   - `xy`（未显式标注）：`xy` 对应的业务输入值
#   - `font_size`（未显式标注）：`font_size` 对应的数量或大小；默认值为 `24`
#   - `color`（未显式标注）：`color` 对应的业务输入值；默认值为 `(255, 255, 255)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `save_clip` 调用本符号
#   - 内部调用：`cv2.cvtColor`、`Image.fromarray`、`ImageDraw.Draw`、`_load_banner_font`、`draw.text`、`str`、`np.array`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：更新或保存 `save_clip` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `keyframes`（List[np.ndarray]）：`keyframes` 对应的业务输入值
#   - `result`（Dict[str, Any]）：`result` 对应的业务输入值
#   - `session_id`（str）：`session_id` 对应业务对象的唯一标识
#   - `out_dir`（Path）：`out_dir` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTaskProcessor::_process_locked` 调用本符号
#   - 内部调用：`frames.append`、`cv2.resize`、`int`、`max`、`np.zeros`、`np.vstack`、`padded.append`、`np.hstack`、`str`、`result.get` 等共 13 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：四事业部持久结果仓库，以及唯一的共享预算仓库；输入与输出详见下方说明
# 参数：
#   - `data_root`（Path）：`data_root` 对应的业务输入值
# 返回：DepartmentResultStores；返回新建的 `DepartmentResultStores` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DepartmentResultStores:
    """四事业部持久结果仓库，以及唯一的共享预算仓库。"""

    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `data_root`（Path）：`data_root` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path(data_root).resolve`、`Path`、`ResultStore`、`self.results_dir`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, data_root: Path):
        self.data_root = Path(data_root).resolve()
        self._stores = {
            department: ResultStore(self.results_dir(department))
            for department in SECURITY_DEPARTMENTS
        }
        self.budget_store = ResultStore(self.data_root / "_shared")

    # 功能：实现 `results_dir` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentResultStores::__init__`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentResultStores::clips_dir`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTaskProcessor::_process_locked`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_department_results_accumulators_are_fully_isolated` 调用本符号；另有 3 处静态调用
    #   - 内部调用：`require_department`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def results_dir(self, department: str) -> Path:
        return self.data_root / require_department(department) / "results"

    # 功能：实现 `clips_dir` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTaskProcessor::_process_locked` 调用本符号
    #   - 内部调用：`self.results_dir`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def clips_dir(self, department: str) -> Path:
        return self.results_dir(department) / "clips"

    # 功能：读取或查询 `get` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：ResultStore；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_department`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get(self, department: str) -> ResultStore:
        return self._stores[require_department(department)]


# 功能：严格读取状态对象；共享状态损坏时可保留证据后重新初始化；输入与输出详见下方说明
# 参数：
#   - `store`（ResultStore）：`store` 对应的业务输入值
#   - `key`（str）：用于查询、分组或缓存的键
#   - `quarantine_corrupt`（bool）：`quarantine_corrupt` 对应的业务输入值；默认值为 `False`
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 调用本符号
#   - 内部调用：`store._path`、`path.exists`、`json.loads`、`path.read_text`、`isinstance`、`ValueError`、`print`、`path.with_name`、`time.time_ns`、`path.replace`
#          等共 11 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
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


# 功能：单事业部持久状态损坏，必须保留任务以避免数据丢失；输入与输出详见下方说明
# 参数：无。
# 返回：DepartmentWorkspaceStateError；返回新建的 `DepartmentWorkspaceStateError` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentAccumulator::record`
#         实例化本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentAccumulator::write` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DepartmentWorkspaceStateError(RuntimeError):
    """单事业部持久状态损坏，必须保留任务以避免数据丢失。"""


# 功能：单事业部历史和当日统计的线程安全累计器；输入与输出详见下方说明
# 参数：
#   - `department`（str）：业务部门名称或标识
#   - `store`（ResultStore）：`store` 对应的业务输入值
#   - `max_history`（int）：`max_history` 对应的业务输入值
#   - `budget_snapshot`（未显式标注）：`budget_snapshot` 对应的业务输入值；默认值为 `None`
# 返回：DepartmentAccumulator；返回新建的 `DepartmentAccumulator` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentAccumulators::__init__` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DepartmentAccumulator:
    """单事业部历史和当日统计的线程安全累计器。"""

    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    #   - `store`（ResultStore）：`store` 对应的业务输入值
    #   - `max_history`（int）：`max_history` 对应的业务输入值
    #   - `budget_snapshot`（未显式标注）：`budget_snapshot` 对应的业务输入值；默认值为 `None`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_department`、`max`、`int`、`threading.RLock`、`self._strict_read`、`existing_state.get`、`isinstance`、`self._mark_disabled`、`history_payload.get`、`deque`
    #          等共 16 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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

    # 功能：实现 `_mark_disabled` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `message`（str）：用于展示、记录或发送的文本消息
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentAccumulator::__init__`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentAccumulator::_strict_read`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentAccumulators::write_all` 调用本符号
    #   - 内部调用：`self.store.write`、`time.time`、`print`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件。
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

    # 功能：不把损坏状态静默降级为默认值，避免覆盖原始证据；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentAccumulator::__init__` 调用本符号
    #   - 内部调用：`self.store._path`、`path.exists`、`json.loads`、`path.read_text`、`isinstance`、`ValueError`、`self._mark_disabled`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
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

    # 功能：实现 `_roll_date` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentAccumulator::record`
    #         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentAccumulator::write` 调用本符号
    #   - 内部调用：`datetime.now().strftime`、`datetime.now`。
    # 副作用/注意事项：会更新当前实例的运行状态。
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

    # 功能：实现 `record` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `record`（dict）：`record` 对应的业务输入值
    #   - `queue_size`（int）：`queue_size` 对应的数量或大小；默认值为 `0`
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTaskProcessor::_process_locked`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_department_results_accumulators_are_fully_isolated`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_corrupt_department_state_is_isolated_and_preserved` 调用本符号
    #   - 内部调用：`DepartmentWorkspaceStateError`、`record.get`、`ValueError`、`validate_camera_id`、`_safe_pending_identifier`、`self._roll_date`、`any`、`item.get`、`result.get`、`self.history.appendleft`
    #          等共 11 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
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

    # 功能：更新或保存 `write` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `queue_size`（int）：`queue_size` 对应的数量或大小；默认值为 `0`
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `DepartmentAccumulator::record` 调用本符号
    #   - 内部调用：`DepartmentWorkspaceStateError`、`self._roll_date`、`list`、`time.time`、`sum`、`self.counts.values`、`round`、`max`、`int`、`self._budget_snapshot`
    #          等共 12 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
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


# 功能：为四个事业部持有独立累计器；输入与输出详见下方说明
# 参数：
#   - `stores`（DepartmentResultStores）：`stores` 对应的业务输入值
#   - `max_history`（int）：`max_history` 对应的业务输入值
#   - `budget_snapshot`（未显式标注）：`budget_snapshot` 对应的业务输入值；默认值为 `None`
# 返回：DepartmentAccumulators；返回新建的 `DepartmentAccumulators` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DepartmentAccumulators:
    """为四个事业部持有独立累计器。"""

    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `stores`（DepartmentResultStores）：`stores` 对应的业务输入值
    #   - `max_history`（int）：`max_history` 对应的业务输入值
    #   - `budget_snapshot`（未显式标注）：`budget_snapshot` 对应的业务输入值；默认值为 `None`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`DepartmentAccumulator`、`stores.get`。
    # 副作用/注意事项：会更新当前实例的运行状态。
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
            for department in SECURITY_DEPARTMENTS
        }

    # 功能：读取或查询 `get` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（str）：业务部门名称或标识
    # 返回：DepartmentAccumulator；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`require_department`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get(self, department: str) -> DepartmentAccumulator:
        return self._items[require_department(department)]

    # 功能：更新或保存 `write_all` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `queue_sizes`（dict[str, int] | None）：`queue_sizes` 对应的业务输入值；默认值为 `None`
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main::write_stats_and_history`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_corrupt_department_state_is_isolated_and_preserved` 调用本符号
    #   - 内部调用：`self._items.items`、`accumulator.write`、`sizes.get`、`accumulator._mark_disabled`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：定义 `_TaskLockEntry` 类，封装后台任务相关的状态、约束与操作
# 参数：无。
# 返回：_TaskLockEntry；返回新建的 `_TaskLockEntry` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTaskProcessor::_hold_task_lock` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class _TaskLockEntry:
    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`threading.Lock`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.users = 0


# 功能：一个可测试的认领任务处理单元，负责校验、判定、持久化和清理；输入与输出详见下方说明
# 参数：
#   - `stores`（DepartmentResultStores）：`stores` 对应的业务输入值
#   - `accumulators`（DepartmentAccumulators）：`accumulators` 对应的业务输入值
#   - `judge`（未显式标注）：`judge` 对应的业务输入值
#   - `queue_timeout`（float）：`queue_timeout` 对应的业务输入值
#   - `save_clip_only_non_compliant`（bool）：`save_clip_only_non_compliant` 对应的业务输入值；默认值为 `True`
# 返回：PendingTaskProcessor；返回新建的 `PendingTaskProcessor` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class PendingTaskProcessor:
    """一个可测试的认领任务处理单元，负责校验、判定、持久化和清理。"""

    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `stores`（DepartmentResultStores）：`stores` 对应的业务输入值
    #   - `accumulators`（DepartmentAccumulators）：`accumulators` 对应的业务输入值
    #   - `judge`（未显式标注）：`judge` 对应的业务输入值
    #   - `queue_timeout`（float）：`queue_timeout` 对应的业务输入值
    #   - `save_clip_only_non_compliant`（bool）：`save_clip_only_non_compliant` 对应的业务输入值；默认值为 `True`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`float`、`bool`、`threading.Lock`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
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

    # 功能：实现 `_hold_task_lock` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `task_key`（tuple[str, str, str]）：`task_key` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTaskProcessor::process`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_worker.py` 的
    #         `test_pending_task_lock_entries_release_after_all_waiters_exit::first`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_worker.py` 的
    #         `test_pending_task_lock_entries_release_after_all_waiters_exit::second` 调用本符号
    #   - 内部调用：`self._task_locks.get`、`_TaskLockEntry`、`entry.lock.acquire`、`entry.lock.release`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：删除或清理 `_cleanup` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `task`（PendingTask）：`task` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTaskProcessor::_process_locked` 调用本符号
    #   - 内部调用：`task.path.with_suffix`、`target.unlink`、`print`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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

    # 功能：实现 `_completion_matches` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `record`（dict）：`record` 对应的业务输入值
    #   - `payload`（dict）：接口或事件携带的业务数据
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTaskProcessor::_process_locked` 调用本符号
    #   - 内部调用：`all`、`record.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _completion_matches(record: dict, payload: dict) -> bool:
        return all(
            record.get(field) == payload[field]
            for field in ("department", "camera_id", "session_id")
        )

    # 功能：处理 `process` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `task`（PendingTask）：`task` 对应的业务输入值
    #   - `now_ts`（float | None）：`now_ts` 对应的业务输入值；默认值为 `None`
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main::process_one`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_real_claim_process_partition_clip_history_stats_and_cleanup`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_completion_record_identity_mismatch_is_rejected_without_vlm_call`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_vlm_multicamera.py` 的
    #         `test_corrupt_completion_preserves_task_markers_and_result` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`load_validated_pending_task`、`self._hold_task_lock`、`self._process_locked`、`time.time`、`float`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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

    # 功能：处理 `_process_locked` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `task`（PendingTask）：`task` 对应的业务输入值
    #   - `payload`（dict）：接口或事件携带的业务数据
    #   - `now_ts`（float）：`now_ts` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `PendingTaskProcessor::process` 调用本符号
    #   - 内部调用：`self.stores.results_dir`、`task.path.with_suffix`、`result_path.exists`、`json.loads`、`result_path.read_text`、`isinstance`、`ValueError`、`print`、`self._completion_matches`、`started_marker.exists`
    #          等共 26 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
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
# 功能：删除真正超过 queue_timeout 的任务；进程重启前已产生但未超时的任务保留；输入与输出详见下方说明
# 参数：
#   - `pending_dir`（Path）：`pending_dir` 对应的业务输入值
#   - `now_ts`（float）：`now_ts` 对应的业务输入值
#   - `queue_timeout`（float）：`queue_timeout` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 调用本符号
#   - 内部调用：`pending_dir.glob`、`open`、`pickle.load`、`float`、`payload.get`、`p.stat`、`p.unlink`、`print`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：升级多摄像头时把旧单路待处理任务转移到全局 processing；输入与输出详见下方说明
# 参数：
#   - `legacy_pending_dir`（Path）：`legacy_pending_dir` 对应的业务输入值
#   - `processing_dir`（Path）：`processing_dir` 对应的业务输入值
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 调用本符号
#   - 内部调用：`Path`、`target_dir.mkdir`、`sorted`、`source_dir.glob`、`target_path.exists`、`time.time_ns`、`source_path.replace`、`shutil.move`、`str`、`print`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def migrate_legacy_pending(
    legacy_pending_dir: Path,
    processing_dir: Path,
) -> int:
    """升级多摄像头时把旧单路待处理任务转移到全局 processing。"""
    source_dir = Path(legacy_pending_dir)
    target_dir = Path(processing_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for source_path in sorted(source_dir.glob("*.pkl")):
        target_path = target_dir / f"legacy-default__{source_path.name}"
        if target_path.exists():
            target_path = target_dir / (
                f"legacy-default__{time.time_ns()}__{source_path.name}"
            )
        try:
            source_path.replace(target_path)
        except OSError:
            shutil.move(str(source_path), str(target_path))
        moved += 1
    if moved:
        print(f"[vlm] 已迁移旧 pending 任务 {moved} 个", flush=True)
    return moved


# 功能：标记启动前已认领但尚未开始的任务，使其恢复时不受旧 TTL 影响；输入与输出详见下方说明
# 参数：
#   - `processing_dir`（Path）：`processing_dir` 对应的业务输入值
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 调用本符号
#   - 内部调用：`Path(processing_dir).glob`、`Path`、`task_path.with_suffix`、`started.exists`、`marker.exists`、`marker.touch`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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


# 功能：处理一个已入队任务,隔离异常并确保队列完成计数正确；输入与输出详见下方说明
# 参数：
#   - `task_q`（queue.Queue）：`task_q` 对应的业务输入值
#   - `process_one`（未显式标注）：`process_one` 对应的业务输入值
#   - `item`（未显式标注）：`item` 对应的业务输入值；默认值为 `None`
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `run_task_worker` 调用本符号
#   - 内部调用：`task_q.get`、`process_one`、`print`、`traceback.print_exc`、`task_q.task_done`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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


# 功能：使用独立停止事件消费任务；全局进程信号不直接终止 worker；输入与输出详见下方说明
# 参数：
#   - `task_q`（未显式标注）：`task_q` 对应的业务输入值
#   - `process_one`（未显式标注）：`process_one` 对应的业务输入值
#   - `stop_event`（threading.Event）：`stop_event` 对应的业务输入值
#   - `poll_sec`（float）：`poll_sec` 对应的业务输入值；默认值为 `0.5`
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`stop_event.is_set`、`task_q.get`、`process_queued_item`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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


# 功能：停止唯一生产者后有界排空队列，再通知并等待 worker 退出；输入与输出详见下方说明
# 参数：
#   - `scanner`（threading.Thread）：`scanner` 对应的业务输入值
#   - `task_q`（未显式标注）：`task_q` 对应的业务输入值
#   - `worker_stop`（threading.Event）：`worker_stop` 对应的业务输入值
#   - `workers`（list[threading.Thread]）：`workers` 对应的业务输入值
#   - `drain_timeout_sec`（float）：`drain_timeout_sec` 对应的业务输入值；默认值为 `120.0`
#   - `poll_sec`（float）：`poll_sec` 对应的业务输入值；默认值为 `0.5`
#   - `worker_join_timeout_sec`（float）：`worker_join_timeout_sec` 对应的业务输入值；默认值为 `1.0`
#   - `scanner_join_timeout_sec`（float）：`scanner_join_timeout_sec` 对应的业务输入值；默认值为 `2.0`
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 调用本符号
#   - 内部调用：`scanner.stop`、`scanner.join`、`max`、`float`、`time.monotonic`、`time.sleep`、`min`、`worker_stop.set`、`worker.join`、`scanner.is_alive`
#          等共 12 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
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


# 功能：实现 `queued_department_counts` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `task_q`（queue.Queue）：`task_q` 对应的业务输入值
# 返回：dict[str, int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main::write_stats_and_history`
#         调用本符号；`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main::write_statuses` 调用本符号
#   - 内部调用：`isinstance`、`task_q.department_counts`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def queued_department_counts(task_q: queue.Queue) -> dict[str, int]:
    if isinstance(task_q, DepartmentFairTaskQueue):
        return task_q.department_counts()
    counts = {department: 0 for department in SECURITY_DEPARTMENTS}
    with task_q.mutex:
        for item in task_q.queue:
            if isinstance(item, PendingTask):
                counts[item.department] += 1
    return counts


# 功能：实现 `vlm_max_concurrent` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `vlm_cfg`（dict）：`vlm_cfg` 对应的业务输入值
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 调用本符号
#   - 内部调用：`int`、`vlm_cfg.get`、`ValueError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def vlm_max_concurrent(vlm_cfg: dict) -> int:
    value = int(vlm_cfg.get("max_concurrent", 3))
    if value <= 0:
        raise ValueError("vlm.max_concurrent 必须是正整数")
    return value


# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------
# 功能：实现 `main` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`set_process_title`、`argparse.ArgumentParser`、`parser.add_argument`、`parser.parse_args`、`Path(__file__).resolve`、`Path`、`resolve_path`、`load_yaml`、`VLMWorkerPaths.from_config`、`DepartmentResultStores`
#          等共 54 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
def main():
    set_process_title("security_vlm[vlm]")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=str)
    parser.add_argument(
        "--camera-root",
        type=str,
        help="旧版摄像头根目录；兼容扫描 <camera_id>/pending",
    )
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
        legacy_camera_root=args.camera_root,
    )
    runtime_dir = paths.runtime_dir
    stores = DepartmentResultStores(paths.data_root)
    # 旧固定 API 在 Task5 前只读取 GE 分区；该别名不参与其他事业部写入。
    store = stores.get(SECURITY_DEPARTMENTS[0])

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

    camera_root = paths.legacy_camera_root
    processing_dir = camera_root.parent / "global" / "processing"
    pending_dir = resolve_path(
        str(
            cfg["session"].get(
                "pending_queue_dir",
                runtime_dir / "session_pending",
            )
        ),
        project_root,
    )
    pending_dir.mkdir(parents=True, exist_ok=True)
    camera_root.mkdir(parents=True, exist_ok=True)
    paths.departments_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = runtime_dir / "vlm_tmp"
    task_q = DepartmentFairTaskQueue()
    scanner = DepartmentPendingScanner(
        paths.departments_root,
        task_q,
        poll_sec=0.5,
        legacy_camera_root=camera_root,
    )

    # 仅清理真正超时的任务，重启前未完成且仍有效的任务继续处理。
    startup_ts = time.time()
    migrate_legacy_pending(pending_dir, processing_dir)
    for discovered_processing_dir in scanner.processing_dirs():
        mark_recovered_processing(discovered_processing_dir)
    cleanup_dirs = scanner.pending_dirs()
    for cleanup_dir in cleanup_dirs:
        cleanup_stale_pending(cleanup_dir, startup_ts, queue_timeout)

    existing_state = read_strict_result_object(store, "vlm_state")
    existing_stats = read_strict_result_object(store, "vlm_latest_stats")
    embedded_state_budget = existing_state.get("budget", {})
    if not isinstance(embedded_state_budget, dict):
        embedded_state_budget = {}
    embedded_stats_budget = existing_stats.get("budget", {})
    if not isinstance(embedded_stats_budget, dict):
        embedded_stats_budget = {}
    budget_state = (
        read_strict_result_object(
            stores.budget_store,
            "vlm_budget",
            quarantine_corrupt=True,
        )
        # Task1 曾把旧全局预算迁入 GE；这里只做一次兼容恢复来源。
        or read_strict_result_object(store, "vlm_budget")
        or embedded_state_budget
        or embedded_stats_budget
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
    # 将 Task1 迁入 GE 的旧预算状态一次性固化为明确的全局共享状态。
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

    # 功能：持久化四个事业部各自的统计和历史；输入与输出详见下方说明
    # 参数：无。
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 调用本符号
    #   - 内部调用：`accumulators.write_all`、`queued_department_counts`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def write_stats_and_history() -> None:
        """持久化四个事业部各自的统计和历史。"""
        accumulators.write_all(queued_department_counts(task_q))

    # 功能：处理 `process_one` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `task`（PendingTask）：`task` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`isinstance`、`TypeError`、`processor.process`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
    def process_one(task: PendingTask) -> None:
        if not isinstance(task, PendingTask):
            raise TypeError("VLM 任务队列只接受 PendingTask")
        processor.process(task)

    # 功能：更新或保存 `write_statuses` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `ok`（bool）：`ok` 对应的业务输入值
    #   - `message`（str）：用于展示、记录或发送的文本消息
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `main` 调用本符号
    #   - 内部调用：`queued_department_counts`、`stores.get(department).write`、`stores.get`、`time.time`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def write_statuses(ok: bool, message: str) -> None:
        queue_sizes = queued_department_counts(task_q)
        for department in SECURITY_DEPARTMENTS:
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
