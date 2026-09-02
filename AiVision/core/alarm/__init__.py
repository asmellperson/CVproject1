# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
core/alarm/ — 告警通道模块
包含喇叭（音频告警）、微信通知、SQL 记录等多种告警通道，以及统一分发器。
所有外部代码应通过本包的公共接口（__all__）访问，而非直接引入子模块。
"""

# 从子模块中导入核心类与单例对象，统一暴露为包级接口
from .dispatcher import AlarmDispatcher, alarm_dispatcher  # 告警分发器类 & 全局单例
from .horn import Horn                                      # 喇叭（音频/蜂鸣）告警通道
from .wechat import WeChatNotifier                          # 微信消息推送通道

# 声明公共 API，限定 `from AiVision.core.alarm import *` 可导入的符号
# - AlarmDispatcher : 分发器类，供需要自定义实例的场景使用
# - alarm_dispatcher: 模块级全局单例，供直接调用
# - Horn            : 音频告警通道，向本地设备播放告警音
# - WeChatNotifier  : 微信通道，通过企业微信/微信推送告警消息
__all__ = ["AlarmDispatcher", "alarm_dispatcher", "Horn", "WeChatNotifier"]
