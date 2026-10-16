"""在启动运行资源前注册业务 ORM、创建缺失表并只读核验既有结构。

由 main.py 显式调用，必须先导入各功能与业务模型再执行 metadata.create_all()。
创建缺失表不等于迁移已有表，类型或约束不一致时应先执行对应离线迁移。
"""


def bootstrap_database():
    """创建全新表并只读核验正式配置和业务表；历史结构必须先离线迁移。"""
    from AiVision.core.db import Base, get_engine
    from AiVision.core.logger import logger
    from AiVision.features.registry import all_specs
    from AiVision.core import system_config as _system_config_orm  # noqa: F401
    from AiVision.alarms.devices import orm as _alarm_device_orm  # noqa: F401
    from AiVision.cameras import orm as _camera_orm  # noqa: F401
    from AiVision.features.logistics_channel.orm import LogisticsChannel, LogisticsChannelCamera
    from AiVision.alarms.records.orm import AiAlarmDisposition
    from AiVision.features.face_recognition.library.orm import FaceEmbedding, FacePerson, FacePersonAuthorization
    from AiVision.features.security_inspection.orm import InspectionSession, InspectionSessionImage
    from AiVision.features.visual_language_detection.orm import VisualLanguageEventORM
    from AiVision.features.guard_behavior.orm import (
        GuardBehaviorSite, GuardBehaviorSiteCamera,
        GuardBehaviorSitePolicy, GuardBehaviorAlarmPolicy,
    )
    from auth.orm import AuthUser, AccessViewer, ExternalClient
    from AiVision.core.schema import assert_table_matches

    specs = all_specs()  # 注册表及其他业务 ORM 必须在创建表之前完成导入。
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    with engine.connect() as connection:
        for spec in specs.values():
            assert_table_matches(connection, spec.orm_class.__table__)
        for model in (
            LogisticsChannel, LogisticsChannelCamera, FacePerson, FaceEmbedding, FacePersonAuthorization,
            GuardBehaviorSite, GuardBehaviorSiteCamera,
            GuardBehaviorSitePolicy, GuardBehaviorAlarmPolicy,
            InspectionSession, InspectionSessionImage, VisualLanguageEventORM,
            AuthUser, AccessViewer, ExternalClient, AiAlarmDisposition,
        ):
            assert_table_matches(connection, model.__table__)
    logger.info("[DB] 功能配置和业务表结构核验通过")
