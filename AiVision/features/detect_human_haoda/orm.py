# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""皓达公司人员违规逗留检测的独立配置表。"""

from features._base.orm import FeatureConfigBase
from features.detect_human.orm import HumanConfigFieldsMixin


# 功能：定义 `HaodaHumanConfigORM` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：HaodaHumanConfigORM；返回新建的 `HaodaHumanConfigORM` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class HaodaHumanConfigORM(HumanConfigFieldsMixin, FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_human_haoda"
