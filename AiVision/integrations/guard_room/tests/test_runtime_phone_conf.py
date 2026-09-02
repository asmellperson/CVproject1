# 文件说明：包含运行时的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。


import numpy as np


from AiVision.integrations.guard_room.src.config import AppConfig, ClassConfig, ModelConfig, RoomConfig, RuleConfig, RuntimeConfig, VideoConfig, WeChatConfig
from AiVision.integrations.guard_room.src.runtime import GuardRoomRuntime
from AiVision.integrations.guard_room.src.state import AppState
from AiVision.integrations.guard_room.src.types import Detection


# 功能：定义 `_Boxes` 类，封装运行时相关的状态、约束与操作
# 参数：无。
# 返回：_Boxes；返回新建的 `_Boxes` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的 `_Result` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class _Boxes:
    xyxy = None
    conf = None


# 功能：定义 `_Result` 类，封装运行时相关的状态、约束与操作
# 参数：无。
# 返回：_Result；返回新建的 `_Result` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的 `FakeDetector::predict` 实例化本符号
#   - 内部调用：`_Boxes`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class _Result:
    boxes = _Boxes()


# 功能：定义 `FakeDetector` 类，封装运行时相关的状态、约束与操作
# 参数：无。
# 返回：FakeDetector；返回新建的 `FakeDetector` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeDetector:
    # 功能：初始化或配置 `__init__` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        self.conf = None

    # 功能：实现 `predict` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`_Result`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def predict(self, **kwargs):
        self.conf = kwargs["conf"]
        return [_Result()]


# 功能：验证 `test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig`、`VideoConfig`、`ModelConfig`、`RoomConfig`、`RuleConfig`、`ClassConfig`、`RuntimeConfig`、`WeChatConfig`、`GuardRoomRuntime`、`AppState`
#          等共 14 个调用。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
def test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf():
    cfg = AppConfig(
        video=VideoConfig(source="rtsp://camera"),
        models=ModelConfig(
            detector_model="models/person_phone.pt",
            detector_conf=0.5,
            phone_conf=0.35,
            device="cpu",
        ),
        room=RoomConfig(),
        rules=RuleConfig(),
        classes=ClassConfig(play_phone=1),
        runtime=RuntimeConfig(),
        wechat=WeChatConfig(enable=False),
    )
    runtime = GuardRoomRuntime(cfg, AppState(cfg, config_path="test.yaml"))
    detector = FakeDetector()

    runtime._detect_phones_in_person_regions(
        detector,
        np.zeros((120, 120, 3), dtype=np.uint8),
        [Detection(cls_id=0, conf=0.9, bbox=(30, 20, 70, 100), track_id=1)],
    )

    assert detector.conf == 0.35
