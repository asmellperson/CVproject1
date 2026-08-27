from features import all_specs
from features.detect_human import SPEC as HUMAN_SPEC
from features.detect_human_haoda import SPEC as HAODA_HUMAN_SPEC


def test_haoda_human_detection_reuses_algorithm_with_independent_config_table():
    assert HAODA_HUMAN_SPEC.name == "detect_human_haoda"
    assert HUMAN_SPEC.display_name == "人员违规逗留检测"
    assert HAODA_HUMAN_SPEC.display_name == "人员违规逗留检测（皓达公司）"
    assert all_specs()["detect_human_haoda"] is HAODA_HUMAN_SPEC
    assert HAODA_HUMAN_SPEC.consumer_cls is HUMAN_SPEC.consumer_cls
    assert HAODA_HUMAN_SPEC.config_schema is HUMAN_SPEC.config_schema
    assert HAODA_HUMAN_SPEC.required_models == HUMAN_SPEC.required_models
    assert HAODA_HUMAN_SPEC.orm_class is not HUMAN_SPEC.orm_class
    assert HAODA_HUMAN_SPEC.orm_class.__tablename__ == "ai_camera_config_detect_human_haoda"
    assert HAODA_HUMAN_SPEC.departments == ("haoda_company",)


def test_haoda_human_detection_defaults_to_disabled_without_camera_migration():
    config = HAODA_HUMAN_SPEC.config_schema()

    assert config.enable is False
    assert config.alarm.sql.enable is False
    assert config.alarm.horn.enable is False
    assert config.alarm.wechat.enable is False
