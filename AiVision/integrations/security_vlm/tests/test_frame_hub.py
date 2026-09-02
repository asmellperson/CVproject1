# 文件说明：包含视频帧的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, Thread

import numpy as np
import pytest

from AiVision.integrations.security_vlm.src.frame_hub import FrameHubReader, FrameHubWriter, atomic_write_json, reset_frame_hub


# 功能：验证 `test_atomic_write_json_supports_concurrent_writers` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Barrier`、`Lock`、`ThreadPoolExecutor`、`list`、`executor.map`、`range`、`json.loads`、`target.read_text`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_atomic_write_json_supports_concurrent_writers(tmp_path):
    workers = 4
    rounds = 50
    barrier = Barrier(workers)
    failures = []
    failures_lock = Lock()
    target = tmp_path / "vlm_latest_stats.json"

    # 功能：更新或保存 `write_many` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `worker_id`（未显式标注）：`worker_id` 对应业务对象的唯一标识
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`range`、`barrier.wait`、`atomic_write_json`、`failures.append`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def write_many(worker_id):
        for index in range(rounds):
            barrier.wait()
            try:
                atomic_write_json(
                    target,
                    {"worker": worker_id, "index": index, "padding": "x" * 65536},
                )
            except Exception as exc:
                with failures_lock:
                    failures.append(exc)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(write_many, range(workers)))

    assert failures == []
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["worker"] in range(workers)
    assert payload["index"] in range(rounds)


# 功能：验证 `test_atomic_write_json_removes_temp_file_after_serialization_error` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`atomic_write_json`、`object`、`list`、`tmp_path.iterdir`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_atomic_write_json_removes_temp_file_after_serialization_error(tmp_path):
    target = tmp_path / "vlm_latest_stats.json"

    with pytest.raises(TypeError):
        atomic_write_json(target, {"not_json": object()})

    assert list(tmp_path.iterdir()) == []


# 功能：验证 `test_frame_hub_resolution_change_keeps_old_mapping_safe` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`np.full`、`FrameHubWriter`、`old_writer.write`、`FrameHubReader`、`reset_frame_hub`、`(tmp_path /
#          'frame_meta.json').exists`、`new_writer.write`、`np.array_equal`、`old_reader.read_frame`、`new_reader.read_frame`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_frame_hub_resolution_change_keeps_old_mapping_safe(tmp_path):
    old_frame = np.full((4, 6, 3), 7, dtype=np.uint8)
    old_writer = FrameHubWriter(tmp_path, height=4, width=6)
    old_writer.write(old_frame, frame_id=1)
    old_reader = FrameHubReader(tmp_path)

    reset_frame_hub(tmp_path)
    assert not (tmp_path / "frame_meta.json").exists()

    new_frame = np.full((2, 3, 3), 9, dtype=np.uint8)
    new_writer = FrameHubWriter(tmp_path, height=2, width=3)
    new_writer.write(new_frame, frame_id=1)
    new_reader = FrameHubReader(tmp_path)

    assert np.array_equal(old_reader.read_frame(), old_frame)
    assert np.array_equal(new_reader.read_frame(), new_frame)
    assert (new_reader.height, new_reader.width) == (2, 3)


# 功能：验证 `test_frame_hub_reader_retries_when_meta_precedes_slots` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`atomic_write_json`、`np.full`、`Thread`、`thread.start`、`FrameHubReader`、`thread.join`、`np.array_equal`、`reader.read_frame`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
def test_frame_hub_reader_retries_when_meta_precedes_slots(tmp_path):
    atomic_write_json(tmp_path / "frame_meta.json", {
        "height": 4,
        "width": 6,
        "channels": 3,
        "slot_idx": 0,
        "frame_id": -1,
    })
    frame = np.full((2, 3, 3), 11, dtype=np.uint8)

    # 功能：启动或执行 `start_writer` 对应的视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`time.sleep`、`FrameHubWriter`、`writer.write`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def start_writer():
        time.sleep(0.1)
        writer = FrameHubWriter(tmp_path, height=2, width=3)
        writer.write(frame, frame_id=1)

    thread = Thread(target=start_writer)
    thread.start()
    reader = FrameHubReader(tmp_path, wait_timeout_sec=1.0)
    thread.join()

    assert (reader.height, reader.width) == (2, 3)
    assert np.array_equal(reader.read_frame(), frame)
