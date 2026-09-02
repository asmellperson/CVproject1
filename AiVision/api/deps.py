# 文件说明：定义`deps` 模块的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
api/deps.py
FastAPI 依赖注入入口。

API 层只通过 service / orchestrator 暴露能力，不持有业务状态。
"""
from __future__ import annotations

from fastapi import HTTPException, status


# 功能：返回已由 main.py 初始化的 Orchestrator；输入与输出详见下方说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`get_orchestrator`、`HTTPException`、`str`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def get_current_orchestrator():
    """返回已由 main.py 初始化的 Orchestrator。"""
    try:
        from AiVision.platform.orchestrator import get_orchestrator
        return get_orchestrator()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


# 功能：读取或查询 `get_camera_config_manager` 对应的`deps` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def get_camera_config_manager():
    from AiVision.platform.camera.config_manager import camera_config_manager
    return camera_config_manager


# 功能：读取或查询 `get_feature_config_manager` 对应的`deps` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def get_feature_config_manager():
    from AiVision.features._base.config_manager import feature_config_manager
    return feature_config_manager


# 功能：读取或查询 `get_model_config_manager` 对应的`deps` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def get_model_config_manager():
    from AiVision.platform.inference.config_manager import model_config_manager
    return model_config_manager


# 功能：读取或查询 `get_department_service` 对应的`deps` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def get_department_service():
    from AiVision.platform.department.service import department_service
    return department_service


# 功能：读取或查询 `get_logistics_channel_service` 对应的`deps` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def get_logistics_channel_service():
    from AiVision.platform.logistics_channel.service import logistics_channel_service
    return logistics_channel_service
