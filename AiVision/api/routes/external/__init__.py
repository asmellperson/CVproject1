"""外部系统统一路由入口，全部子路由均要求系统凭证。"""

from fastapi import APIRouter, Depends

from auth.external import EXTERNAL_API_PREFIX, get_external_client
from .security_inspection import router as inspection_router

router = APIRouter(prefix=EXTERNAL_API_PREFIX, dependencies=[Depends(get_external_client)])
router.include_router(inspection_router)
