"""外部系统统一路由入口，数据和图片支持直接访问。"""

from fastapi import APIRouter

from auth.external import EXTERNAL_API_PREFIX
from .security_inspection import router as inspection_router
from .security_fence import router as fence_router

router = APIRouter(prefix=EXTERNAL_API_PREFIX)
router.include_router(inspection_router)
router.include_router(fence_router)
