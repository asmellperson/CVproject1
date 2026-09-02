# 文件说明：实现视频帧消费与检测的帧消费、判定与告警衔接逻辑。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_face/consumer.py — 人脸逗留检测"""
from AiVision.features._base.dwell_consumer import DwellDetectionConsumer


# 功能：人脸逗留 — 用 yolo_face 模型,所有 detection 都视为人脸；输入与输出详见下方说明
# 参数：无。
# 返回：FaceConsumer；返回新建的 `FaceConsumer` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FaceConsumer(DwellDetectionConsumer):
    """人脸逗留 — 用 yolo_face 模型,所有 detection 都视为人脸"""
    REQUIRED_DETECTION_TYPE = None  # face 模型本身只检测人脸,不需要再过滤
