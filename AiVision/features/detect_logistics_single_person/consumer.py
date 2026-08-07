"""通用电气物流通道单人检测消费者。"""

from features._base.logistics_single_person_consumer import (
    LogisticsSinglePersonConsumerBase,
    build_monitor_snapshot,
)


class LogisticsSinglePersonConsumer(LogisticsSinglePersonConsumerBase):
    """通用电气模块的共享物流单人检测适配类。"""


__all__ = ["LogisticsSinglePersonConsumer", "build_monitor_snapshot"]
