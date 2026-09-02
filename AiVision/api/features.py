# 文件说明：实现接口访问相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
api/features.py
通用功能配置 API — 替代旧代码里 5 个重复的 *_config_api.py。

旧代码: blocks_config_api.py / door_config_api.py / face_config_api.py / phone_config_api.py / human_config_api.py
        每个文件 100+ 行,只有功能名不同,实质代码一字不差。

新代码: 1 个路由处理所有功能。前端访问:
    GET  /api/features                         → 列出所有 feature 元数据
    GET  /api/features/{feature}               → 单个 feature 元数据
    GET  /api/features/{feature}/configs/{cam} → 读单个摄像头的配置
    PUT  /api/features/{feature}/configs/{cam} → 写单个摄像头的配置
    GET  /api/features/{feature}/cameras/{cam}/status → 读功能运行状态
"""
from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from auth.auth import get_current_user, require_admin
from AiVision.api.cameras import get_camera_for_user
from AiVision.api.deps import get_camera_config_manager, get_current_orchestrator
from AiVision.features import all_specs, get_spec
from AiVision.features._base.spec import FeatureSpec
from AiVision.features._base.config_manager import feature_config_manager
from AiVision.platform.camera.config_manager import camera_config_manager
from AiVision.platform.department.service import department_service


# ------------------------------------------------------------------ #
#  响应模型                                                             #
# ------------------------------------------------------------------ #

# 功能：单个功能的元数据，供前端动态生成导航菜单与功能入口；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `display_name`（str）：`display_name` 对应的业务输入值
#   - `required_models`（list[str]）：`required_models` 对应的业务输入值
#   - `violation_type`（int）：`violation_type` 对应的业务输入值
#   - `config_schema`（dict）：`config_schema` 对应的业务输入值
#   - `departments`（list[str]）：`departments` 对应的业务输入值
# 返回：FeatureMetaResponse；返回新建的 `FeatureMetaResponse` 实例。
# 调用关系：
#   - 调用方：`AiVision/api/features.py` 的 `_spec_to_meta` 实例化本符号；`AiVision/api/features.py` 的
#         `create_features_router::_spec_to_meta` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FeatureMetaResponse(BaseModel):
    """
    单个功能的元数据，供前端动态生成导航菜单与功能入口。

    config_schema: 由 spec.config_schema.model_json_schema() 生成的 JSON Schema，
                   前端可据此自动渲染配置表单，无需为每个功能单独编写 UI。
    """
    name: str
    display_name: str
    required_models: list[str]
    violation_type: int
    config_schema: dict
    departments: list[str] = []


# 功能：所有已注册功能的元数据列表，对应 GET /api/features 的响应体；输入与输出详见下方说明
# 参数：
#   - `features`（list[FeatureMetaResponse]）：`features` 对应的业务输入值
# 返回：FeaturesListResponse；返回新建的 `FeaturesListResponse` 实例。
# 调用关系：
#   - 调用方：`AiVision/api/features.py` 的 `create_features_router::list_features` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FeaturesListResponse(BaseModel):
    """所有已注册功能的元数据列表，对应 GET /api/features 的响应体。"""
    features: list[FeatureMetaResponse]


# 功能：统一的功能配置响应格式，替代旧代码中 5 个各自定义的响应类型；输入与输出详见下方说明
# 参数：
#   - `camera`（dict）：摄像头配置或实体
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `config`（dict）：运行配置对象
# 返回：FeatureConfigResponse；返回新建的 `FeatureConfigResponse` 实例。
# 调用关系：
#   - 调用方：`AiVision/api/features.py` 的 `create_features_router::get_feature_config` 实例化本符号；`AiVision/api/features.py` 的
#         `create_features_router::save_feature_config` 实例化本符号；`AiVision/api/logistics_channels.py` 的 `get_member_camera_config`
#         实例化本符号；`AiVision/api/logistics_channels.py` 的 `update_member_camera_config` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FeatureConfigResponse(BaseModel):
    """
    统一的功能配置响应格式，替代旧代码中 5 个各自定义的响应类型。

    字段说明:
        camera : 摄像头基础信息 {id, name, shm_name, enable}。
        feature: 功能名称，如 "blocks" / "detect_face"。
        config : 功能配置体 {enable, value: {...}, alarm: {sql, horn, wechat}}，
                 结构与数据库中 function_config JSON 的单功能节点一致。
    """
    camera: dict
    feature: str
    config: dict


# 功能：在功能配置页新建摄像头并立即启用当前功能；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `url`（str）：目标接口、媒体流或页面地址
#   - `shm_name`（str | None）：摄像头共享内存名称
#   - `fps`（int）：`fps` 对应的业务输入值
#   - `enabled`（bool）：是否启用相应能力
#   - `department`（str | None）：业务部门名称或标识
# 返回：FeatureCameraCreateRequest；返回新建的 `FeatureCameraCreateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FeatureCameraCreateRequest(BaseModel):
    """在功能配置页新建摄像头并立即启用当前功能。"""

    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    shm_name: str | None = Field(None, min_length=1)
    fps: int = Field(5, gt=0)
    enabled: bool = True
    department: str | None = None


# ------------------------------------------------------------------ #
#  内部工具函数                                                         #
# ------------------------------------------------------------------ #

# 功能：将 FeatureSpec 对象转换为 API 响应模型，集中处理 JSON Schema 序列化；输入与输出详见下方说明
# 参数：
#   - `spec`（FeatureSpec）：`spec` 对应的业务输入值
# 返回：FeatureMetaResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`FeatureMetaResponse`、`list`、`spec.config_schema.model_json_schema`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _spec_to_meta(spec: FeatureSpec) -> FeatureMetaResponse:
    """将 FeatureSpec 对象转换为 API 响应模型，集中处理 JSON Schema 序列化。"""
    return FeatureMetaResponse(
        name=spec.name,
        display_name=spec.display_name,
        required_models=list(spec.required_models),
        violation_type=spec.violation_type,
        config_schema=spec.config_schema.model_json_schema(),
    )


# 功能：按功能名查找已注册的 FeatureSpec，未找到时抛出 404；输入与输出详见下方说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
# 返回：FeatureSpec；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/features.py` 的 `create_features_router::get_feature_meta` 调用本符号；`AiVision/api/features.py` 的
#         `create_features_router::create_feature_camera` 调用本符号；`AiVision/api/features.py` 的
#         `create_features_router::get_feature_config` 调用本符号；`AiVision/api/features.py` 的
#         `create_features_router::save_feature_config` 调用本符号
#   - 内部调用：`get_spec`、`HTTPException`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _require_spec(feature: str) -> FeatureSpec:
    """
    按功能名查找已注册的 FeatureSpec，未找到时抛出 404。

    集中处理"功能不存在"的错误响应，避免每个路由重复判断。
    """
    spec = get_spec(feature)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown feature: {feature}")
    return spec


def get_feature_status(
    feature: str,
    key: str,
    user: dict = Depends(get_current_user),
    camera_config_manager=Depends(get_camera_config_manager),
    orchestrator=Depends(get_current_orchestrator),
):
    """读取指定摄像头的功能运行状态。"""
    get_camera_for_user(camera_config_manager, key, user)
    return orchestrator.get_feature_monitor_status(key, feature)


# ------------------------------------------------------------------ #
#  路由工厂                                                             #
# ------------------------------------------------------------------ #

# 功能：构造功能元数据查询 + 配置读写的统一 APIRouter；输入与输出详见下方说明
# 参数：
#   - `feature_config_manager`（未显式标注）：`feature_config_manager` 对应的业务输入值
#   - `dept_service`（未显式标注）：`dept_service` 对应的业务输入值；默认值为 `None`
#   - `camera_config_manager`（未显式标注）：`camera_config_manager` 对应的业务输入值；默认值为 `None`
# 返回：APIRouter；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`APIRouter`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def create_features_router(
    feature_config_manager,
    dept_service=None,
    camera_config_manager=None,
) -> APIRouter:
    """
    构造功能元数据查询 + 配置读写的统一 APIRouter。

    采用工厂函数而非模块级路由实例，原因是 feature_config_manager 需在应用启动时
    由外部注入（依赖 DB 连接与缓存），避免模块导入时产生副作用。

    Args:
        feature_config_manager: FeatureConfigManager 实例，封装跨功能的配置读写逻辑，
                         由调用方（通常是 Orchestrator 或 app 工厂）负责创建并传入。
        dept_service: DepartmentService 实例，可选，用于获取功能归属的部门列表。
        camera_config_manager: CameraConfigManager 实例，可选，用于原子创建摄像头并启用功能。

    Returns:
        挂载在 /api/features 下的 APIRouter，可直接 app.include_router()。
    """
    if camera_config_manager is None:
        from AiVision.platform.camera.config_manager import camera_config_manager as default_camera_config_manager

        camera_config_manager = default_camera_config_manager

    router = APIRouter(prefix="/api/features", tags=["features"])
    router.add_api_route(
        "/{feature}/cameras/{key}/status",
        get_feature_status,
        methods=["GET"],
    )

    # 功能：将 FeatureSpec 对象转换为 API 响应模型，集中处理 JSON Schema 序列化；输入与输出详见下方说明
    # 参数：
    #   - `spec`（FeatureSpec）：`spec` 对应的业务输入值
    # 返回：FeatureMetaResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`dept_service.get_departments_by_feature`、`hasattr`、`list`、`FeatureMetaResponse`、`spec.config_schema.model_json_schema`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _spec_to_meta(spec: FeatureSpec) -> FeatureMetaResponse:
        """将 FeatureSpec 对象转换为 API 响应模型，集中处理 JSON Schema 序列化。"""
        departments = []
        if dept_service:
            try:
                from AiVision.core.db import session_scope
                with session_scope() as session:
                    departments = dept_service.get_departments_by_feature(session, spec.name)
            except Exception:
                departments = list(spec.departments) if hasattr(spec, "departments") else []
        else:
            departments = list(spec.departments) if hasattr(spec, "departments") else []

        return FeatureMetaResponse(
            name=spec.name,
            display_name=spec.display_name,
            required_models=list(spec.required_models),
            violation_type=spec.violation_type,
            config_schema=spec.config_schema.model_json_schema(),
            departments=departments,
        )

    # 功能：列出所有已注册功能的元数据；输入与输出详见下方说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `router.get('', response_model=FeaturesListResponse)` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`FeaturesListResponse`、`_spec_to_meta`、`all_specs().values`、`all_specs`、`router.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @router.get("", response_model=FeaturesListResponse)
    def list_features():
        """
        列出所有已注册功能的元数据。

        前端通过此接口动态生成功能菜单，新增功能只需在 features 注册表注册，
        无需修改前端路由或后端路由代码。
        """
        return FeaturesListResponse(
            features=[_spec_to_meta(s) for s in all_specs().values()]
        )

    # 功能：返回单个功能的元数据，包含 JSON Schema 供前端按需渲染表单；输入与输出详见下方说明
    # 参数：
    #   - `feature`（Annotated[str, Path()]）：`feature` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `router.get('/{feature}', response_model=FeatureMetaResponse)` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Path`、`_spec_to_meta`、`_require_spec`、`router.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @router.get("/{feature}", response_model=FeatureMetaResponse)
    def get_feature_meta(feature: Annotated[str, Path()]):
        """返回单个功能的元数据，包含 JSON Schema 供前端按需渲染表单。"""
        return _spec_to_meta(_require_spec(feature))

    # 功能：新增摄像头并原子启用当前普通检测功能；输入与输出详见下方说明
    # 参数：
    #   - `feature`（str）：`feature` 对应的业务输入值
    #   - `payload`（FeatureCameraCreateRequest）：接口或事件携带的业务数据
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `router.post('/{feature}/cameras')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_require_spec`、`camera_config_manager.create_camera_for_feature`、`payload.model_dump`、`HTTPException`、`str`、`router.post`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @router.post("/{feature}/cameras")
    def create_feature_camera(
        feature: str,
        payload: FeatureCameraCreateRequest,
        _user: dict = Depends(require_admin),
    ) -> dict:
        """新增摄像头并原子启用当前普通检测功能。"""
        spec = _require_spec(feature)
        try:
            return camera_config_manager.create_camera_for_feature(
                spec.name,
                payload.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 功能：读取指定摄像头的功能配置；输入与输出详见下方说明
    # 参数：
    #   - `feature`（str）：`feature` 对应的业务输入值
    #   - `shm_name`（str）：摄像头共享内存名称
    #   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `router.get('/{feature}/configs/{shm_name}', response_model=FeatureConfigResponse)` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_require_spec`、`user.get`、`HTTPException`、`feature_config_manager.get_config`、`FeatureConfigResponse`、`router.get`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @router.get(
        "/{feature}/configs/{shm_name}",
        response_model=FeatureConfigResponse,
    )
    def get_feature_config(
        feature: str,
        shm_name: str,
        user: dict = Depends(get_current_user),
    ):
        """
        读取指定摄像头的功能配置。

        shm_name 为摄像头共享内存标识（即 ai_camera_config.shm_name），
        摄像头或对应功能配置不存在时返回 404。
        """
        spec = _require_spec(feature)
        # 物流通道为多摄像头、部门隔离资源。viewer 必须走物流通道的成员配置
        # 端点，后者同时校验 feature 部门和成员归属；这里禁止绕过归属校验。
        from AiVision.platform.logistics_channel.constants import LOGISTICS_FEATURES
        if feature in LOGISTICS_FEATURES and user.get("role") != "admin":
            raise HTTPException(
                status_code=403,
                detail="logistics camera config requires channel membership access",
            )
        result = feature_config_manager.get_config(spec, shm_name)
        if result is None:
            raise HTTPException(status_code=404, detail="camera or config not found")
        return FeatureConfigResponse(**result)

    # 功能：保存指定摄像头的功能配置（需管理员权限）；输入与输出详见下方说明
    # 参数：
    #   - `feature`（str）：`feature` 对应的业务输入值
    #   - `shm_name`（str）：摄像头共享内存名称
    #   - `payload`（dict）：接口或事件携带的业务数据
    #   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `router.put('/{feature}/configs/{shm_name}', response_model=FeatureConfigResponse)` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`_require_spec`、`spec.config_schema.model_validate(payload).model_dump`、`spec.config_schema.model_validate`、`HTTPException`、`feature_config_manager.save_config`、`FeatureConfigResponse`、`router.put`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @router.put(
        "/{feature}/configs/{shm_name}",
        response_model=FeatureConfigResponse,
    )
    def save_feature_config(
        feature: str,
        shm_name: str,
        payload: dict,
        _user: dict = Depends(require_admin),  # 写操作需管理员权限
    ):
        """
        保存指定摄像头的功能配置（需管理员权限）。

        校验流程:
            1. 通过 spec.config_schema（Pydantic 模型）校验 payload 结构与类型。
            2. 校验通过后调用 feature_config_manager.save_config() 持久化到数据库。
            3. 返回保存后的最新配置，供前端直接刷新本地状态。

        校验失败返回 400，摄像头不存在返回 404。
        """
        spec = _require_spec(feature)
        try:
            # 用各功能自定义的 Pydantic schema 校验入参，类型错误或缺字段时抛异常
            validated = spec.config_schema.model_validate(payload).model_dump()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"validation error: {e}")

        result = feature_config_manager.save_config(spec, shm_name, validated)
        if result is None:
            raise HTTPException(status_code=404, detail="camera not found")
        return FeatureConfigResponse(**result)

    return router


router = create_features_router(
    feature_config_manager,
    department_service,
    camera_config_manager,
)
