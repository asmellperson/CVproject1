# 文件说明：包含状态管理的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import (
    AppConfig,
    ClassConfig,
    ModelConfig,
    RoomConfig,
    RuleConfig,
    RuntimeConfig,
    VideoConfig,
    WeChatConfig,
)
from src.state import AppState
from src.types import Detection


# 功能：实现 `_config` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：AppConfig；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig`、`VideoConfig`、`ModelConfig`、`RoomConfig`、`RuleConfig`、`ClassConfig`、`RuntimeConfig`、`WeChatConfig`。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
def _config() -> AppConfig:
    return AppConfig(
        video=VideoConfig(source="rtsp://camera"),
        models=ModelConfig(detector_model="models/test.pt"),
        room=RoomConfig(),
        rules=RuleConfig(),
        classes=ClassConfig(),
        runtime=RuntimeConfig(),
        wechat=WeChatConfig(enable=False),
    )


# 功能：验证 `test_status_reports_guards_separately_from_all_detected_people` 对应的状态管理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppState`、`_config`、`Detection`、`state.update_frame`、`np.zeros`、`SimpleNamespace`、`state.get_status`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_status_reports_guards_separately_from_all_detected_people():
    state = AppState(_config(), config_path="test.yaml")
    visitor = Detection(cls_id=0, conf=0.91, bbox=(0, 0, 20, 40), track_id=1)
    guard = Detection(cls_id=0, conf=0.87, bbox=(30, 0, 50, 40), track_id=2)

    state.update_frame(
        np.zeros((64, 64, 3), dtype=np.uint8),
        frame_count=1,
        fps=6.5,
        timestamp_s=1.0,
        persons=[visitor, guard],
        guards=[guard],
        guard_confidence=0.93,
        phones=[],
        pose_features={},
        decisions={
            "absent": SimpleNamespace(active=False),
            "phone": SimpleNamespace(active=False),
            "prone_sleep": SimpleNamespace(active=False),
            "vehicle_unattended": SimpleNamespace(active=False),
        },
        pose_enabled=False,
    )

    status = state.get_status()
    assert status["counts"]["persons"] == 2
    assert status["counts"]["guards"] == 1
    assert len(status["persons"]) == 2
    assert len(status["guards"]) == 1
    assert status["metrics"]["guard_confidence"] == 0.93
