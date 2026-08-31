# 文件说明：实现`guard_gate` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

# guard_gate.py
"""
保安识别结果平滑模块。

制服分类模型在逐帧推理时可能因遮挡、运动模糊等原因产生单帧漏识别，
GuardGate 通过"保持窗口"（hold_seconds）将识别结果在时间轴上平滑：
一旦某帧识别为保安，后续 hold_seconds 内均视为保安，避免状态频繁抖动。
"""
from __future__ import annotations

from typing import Dict


# 功能：逐目标的保安识别结果保持器；输入与输出详见下方说明
# 参数：
#   - `hold_seconds`（float）：`hold_seconds` 对应的时间间隔或时长；默认值为 `1.0`
# 返回：GuardGate；返回新建的 `GuardGate` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class GuardGate:
    """逐目标的保安识别结果保持器。

    每个 track_id 独立维护一个最近识别为保安的时间戳；
    当前帧未识别为保安时，若距上次正识别不超过 hold_seconds，
    仍返回 True（视为保安在场）。
    """

    # 功能：hold_seconds: 正识别结果的保持时长（秒）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `hold_seconds`（float）：`hold_seconds` 对应的时间间隔或时长；默认值为 `1.0`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, hold_seconds: float = 1.0):
        """
        Args:
            hold_seconds: 正识别结果的保持时长（秒）。
                          应与视频帧率匹配：10fps 时设 1.0 约等于保持 10 帧。
        """
        self.hold_seconds = hold_seconds
        self.last_positive_ts: Dict[int, float] = {}   # track_id → 最近一次识别为保安的时间戳

    # 功能：查询目标当前是否应视为保安（含保持窗口）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `track_id`（int | None）：目标跟踪标识
    #   - `timestamp_s`（float）：以秒表示的流时间戳
    #   - `is_guard_now`（bool）：`is_guard_now` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.last_positive_ts.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def keep(self, track_id: int | None, timestamp_s: float, is_guard_now: bool) -> bool:
        """查询目标当前是否应视为保安（含保持窗口）。

        track_id 为 None 时（目标尚未分配跟踪 ID），直接透传本帧识别结果，不做平滑。

        Args:
            track_id:     目标跟踪 ID；None 表示无跟踪信息。
            timestamp_s:  当前帧的流时间戳（秒）。
            is_guard_now: 制服分类模型对本帧的原始判断结果。

        Returns:
            True 表示当前应视为保安（本帧正识别，或仍在保持窗口内）。
        """
        if track_id is None:
            return is_guard_now     # 无跟踪 ID，无法跨帧平滑，直接返回原始结果

        if is_guard_now:
            self.last_positive_ts[track_id] = timestamp_s  # 更新最近正识别时间戳
            return True

        # 本帧未识别为保安：检查是否仍在保持窗口内
        last_ts = self.last_positive_ts.get(track_id, -1e9)    # 未曾识别过则视为无穷久前
        return (timestamp_s - last_ts) <= self.hold_seconds