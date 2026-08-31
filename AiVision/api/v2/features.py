# 文件说明：定义`features` 模块的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
api/v2/features.py
功能元数据与配置 CRUD。

实际路由由 features._base.api.create_features_router 统一生成，避免 5 个 feature
重复写配置 API。
"""
from __future__ import annotations

from features._base.api import create_features_router
from features._base.service import feature_config_service
from platform.camera.service import camera_service
from platform.department.service import department_service

router = create_features_router(
    feature_config_service,
    department_service,
    camera_service,
)
