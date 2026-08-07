"""物流通道领域模型。"""

from .state import (
    CameraSnapshot,
    CameraSnapshotStore,
    ChannelDecision,
    ChannelPresenceState,
    PersonDetection,
    classify_channel,
    deduplicate_person_detections,
    intersection_over_union,
    translate_person_detection,
)

__all__ = [
    "CameraSnapshot",
    "CameraSnapshotStore",
    "ChannelDecision",
    "ChannelPresenceState",
    "PersonDetection",
    "classify_channel",
    "deduplicate_person_detections",
    "intersection_over_union",
    "translate_person_detection",
    "LogisticsChannelService",
    "MigrationSummary",
    "logistics_channel_service",
]


def __getattr__(name: str):
    """延迟导出数据库服务，避免 ORM 初始化期间形成包级循环导入。"""
    if name in {
        "LogisticsChannelService",
        "MigrationSummary",
        "logistics_channel_service",
    }:
        from .service import (
            LogisticsChannelService,
            MigrationSummary,
            logistics_channel_service,
        )

        return {
            "LogisticsChannelService": LogisticsChannelService,
            "MigrationSummary": MigrationSummary,
            "logistics_channel_service": logistics_channel_service,
        }[name]
    raise AttributeError(name)
