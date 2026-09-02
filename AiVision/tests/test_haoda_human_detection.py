# 文件说明：包含`test_haoda_human_detection` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from AiVision.features import all_specs
from AiVision.features.detect_human import SPEC as HUMAN_SPEC
from AiVision.features.detect_human_haoda import SPEC as HAODA_HUMAN_SPEC


# 功能：验证 `test_haoda_human_detection_reuses_algorithm_with_independent_config_table` 对应的`test_haoda_human_detection`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`all_specs`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：验证 `test_haoda_human_detection_defaults_to_disabled_without_camera_migration` 对应的`test_haoda_human_detection`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`HAODA_HUMAN_SPEC.config_schema`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_haoda_human_detection_defaults_to_disabled_without_camera_migration():
    config = HAODA_HUMAN_SPEC.config_schema()

    assert config.enable is False
    assert config.alarm.sql.enable is False
    assert config.alarm.horn.enable is False
    assert config.alarm.wechat.enable is False
