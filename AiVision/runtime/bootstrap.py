"""启动阶段的 ORM 注册、缺失表创建及数据库结构核验。"""


def bootstrap_database():
    """创建全新表并只读核验正式配置和业务表；历史结构必须先离线迁移。"""
    from AiVision.core.db import Base, get_engine
    from AiVision.core.logger import logger
    from AiVision.features.registry import all_specs
    from AiVision.core import system_config as _system_config_orm  # noqa: F401
    from AiVision.alarms.devices import orm as _alarm_device_orm  # noqa: F401
    from AiVision.cameras import orm as _camera_orm  # noqa: F401
    from AiVision.features.logistics_channel.orm import LogisticsChannel, LogisticsChannelCamera
    from AiVision.alarms.records import orm as _violation_orm  # noqa: F401
    from AiVision.features.face_recognition.library.orm import FaceEmbedding, FacePerson
    from AiVision.features.guard_behavior.orm import (
        GuardBehaviorSite, GuardBehaviorSiteCamera,
        GuardBehaviorSitePolicy, GuardBehaviorAlarmPolicy,
    )
    from AiVision.core.schema import assert_table_matches

    specs = all_specs()  # 注册表及其他业务 ORM 必须在创建表之前完成导入。
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    with engine.connect() as connection:
        for spec in specs.values():
            assert_table_matches(connection, spec.orm_class.__table__)
        for model in (
            LogisticsChannel, LogisticsChannelCamera, FacePerson, FaceEmbedding,
            GuardBehaviorSite, GuardBehaviorSiteCamera,
            GuardBehaviorSitePolicy, GuardBehaviorAlarmPolicy,
        ):
            assert_table_matches(connection, model.__table__)
    logger.info("[DB] 功能配置和业务表结构核验通过")
