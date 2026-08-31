# 文件说明：实现视频帧消费与检测的帧消费、判定与告警衔接逻辑。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""电子电工物流通道单人检测消费者。"""

from features._base.logistics_single_person_consumer import LogisticsSinglePersonConsumerBase


# 功能：电子电工模块的共享物流单人检测适配类；输入与输出详见下方说明
# 参数：无。
# 返回：LogisticsSinglePersonElectronicsElectricianConsumer；返回新建的 `LogisticsSinglePersonElectronicsElectricianConsumer` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsSinglePersonElectronicsElectricianConsumer(LogisticsSinglePersonConsumerBase):
    """电子电工模块的共享物流单人检测适配类。"""
