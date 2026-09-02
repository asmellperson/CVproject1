# 文件说明：定义`models` 模块的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
api/models.py
推理模型配置 CRUD。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.auth import require_admin
from AiVision.api.deps import get_model_config_manager


router = APIRouter(prefix="/api/models", tags=["models"])


# 功能：定义 `ModelUpdateRequest` 类，封装`models` 模块相关的状态、约束与操作
# 参数：
#   - `name`（str | None）：业务对象名称
#   - `type`（str | None）：`type` 对应的业务输入值
#   - `path`（str | None）：目标路径
#   - `import_path`（str | None）：`import_path` 对应的业务输入值
#   - `description`（str | None）：`description` 对应的业务输入值
#   - `enable`（bool | None）：`enable` 对应的业务输入值
# 返回：ModelUpdateRequest；返回新建的 `ModelUpdateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ModelUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1)
    type: str | None = Field(None, min_length=1)
    path: str | None = Field(None, min_length=1)
    import_path: str | None = None
    description: str | None = None
    enable: bool | None = None


# 功能：定义 `ModelCreateRequest` 类，封装`models` 模块相关的状态、约束与操作
# 参数：
#   - `name`（str）：业务对象名称
#   - `type`（str）：`type` 对应的业务输入值
#   - `path`（str）：目标路径
#   - `import_path`（str | None）：`import_path` 对应的业务输入值
#   - `description`（str | None）：`description` 对应的业务输入值
#   - `enable`（bool）：`enable` 对应的业务输入值
# 返回：ModelCreateRequest；返回新建的 `ModelCreateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ModelCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    type: str = Field("yolo", min_length=1)
    path: str = Field(..., min_length=1)
    import_path: str | None = None
    description: str | None = None
    enable: bool = True


# 功能：读取或查询 `list_models` 对应的`models` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `model_config_manager`（未显式标注）：`model_config_manager` 对应的业务输入值；默认值为 `Depends(get_model_config_manager)`
# 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`model_config_manager.list_models`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("")
def list_models(model_config_manager=Depends(get_model_config_manager)) -> list[dict[str, Any]]:
    return model_config_manager.list_models(enabled_only=False)


# 功能：创建或构建 `create_model` 对应的`models` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（ModelCreateRequest）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `model_config_manager`（未显式标注）：`model_config_manager` 对应的业务输入值；默认值为 `Depends(get_model_config_manager)`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.post('')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`model_config_manager.create_model`、`payload.model_dump`、`router.post`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.post("")
def create_model(
    payload: ModelCreateRequest,
    _user: dict = Depends(require_admin),
    model_config_manager=Depends(get_model_config_manager),
) -> dict[str, Any]:
    return model_config_manager.create_model(payload.model_dump())


# 功能：读取或查询 `get_model` 对应的`models` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `model_id`（int）：模型唯一标识
#   - `model_config_manager`（未显式标注）：`model_config_manager` 对应的业务输入值；默认值为 `Depends(get_model_config_manager)`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{model_id}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`model_config_manager.get_model`、`HTTPException`、`router.get`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.get("/{model_id}")
def get_model(model_id: int, model_config_manager=Depends(get_model_config_manager)) -> dict[str, Any]:
    model = model_config_manager.get_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    return model


# 功能：实现 `patch_model` 对应的`models` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `model_id`（int）：模型唯一标识
#   - `payload`（ModelUpdateRequest）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `model_config_manager`（未显式标注）：`model_config_manager` 对应的业务输入值；默认值为 `Depends(get_model_config_manager)`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.patch('/{model_id}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`model_config_manager.update_model`、`payload.model_dump`、`HTTPException`、`router.patch`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.patch("/{model_id}")
def patch_model(
    model_id: int,
    payload: ModelUpdateRequest,
    _user: dict = Depends(require_admin),
    model_config_manager=Depends(get_model_config_manager),
) -> dict[str, Any]:
    model = model_config_manager.update_model(model_id, payload.model_dump(exclude_none=True))
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    return model
