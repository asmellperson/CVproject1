"""管理员现场喇叭配置、状态及无声连接测试。"""
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from auth.auth import require_admin
from AiVision.api.deps import get_horn_runtime_manager, get_horn_service
from AiVision.core.logger import logger
from AiVision.platform.alarm_device.schema import (
    HornConnectionResult, HornConnectionTest, HornCreate, HornResponse,
    HornRuntimeStatus, HornUpdate,
)
from AiVision.platform.alarm_device.service import HornInUseError


class HornRoute(APIRoute):
    """凭据路由单独屏蔽校验原始输入、SQL 参数和设备异常文本。"""
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except (RequestValidationError, ValidationError) as exc:
                errors = [{"loc": error["loc"], "type": error["type"],
                           "msg": "喇叭配置字段无效"} for error in exc.errors()]
                return JSONResponse(status_code=422, content={"detail": errors})
            except HornInUseError:
                raise HTTPException(409, "喇叭仍被功能或物流通道配置引用，请先解除绑定") from None
            except IntegrityError:
                raise HTTPException(409, "喇叭名称重复或配置存在关联冲突") from None
            except SQLAlchemyError:
                logger.warning("[HornAPI] 数据库操作失败")
                raise HTTPException(503, "喇叭配置数据库暂时不可用") from None
            except HTTPException:
                raise
            except Exception:
                logger.warning("[HornAPI] 喇叭操作失败")
                raise HTTPException(500, "喇叭操作失败") from None

        return safe_handler


router = APIRouter(prefix="/api/horns", tags=["horns"], route_class=HornRoute,
                   dependencies=[Depends(require_admin)])


def _require_horn(service, horn_id):
    config = service.get_horn(horn_id)
    if config is None:
        raise HTTPException(404, "喇叭不存在")
    return config


def _response(config, runtime):
    return dict(config, runtime=runtime.status(config))


@router.get("", response_model=list[HornResponse])
def list_horns(service=Depends(get_horn_service), runtime=Depends(get_horn_runtime_manager)):
    return [_response(config, runtime) for config in service.list_horns()]


@router.post("", response_model=HornResponse, status_code=201)
def create_horn(payload: HornCreate, service=Depends(get_horn_service),
                runtime=Depends(get_horn_runtime_manager)):
    return _response(service.create_horn(payload.write_values()), runtime)


@router.post("/test-connection", response_model=HornConnectionResult)
def test_connection(payload: HornConnectionTest, service=Depends(get_horn_service),
                    runtime=Depends(get_horn_runtime_manager)):
    values = payload.write_values()
    horn_id = values.pop("horn_id", None)
    if horn_id is not None:
        configs = service.runtime_configs(horn_id)
        if not configs:
            raise HTTPException(404, "喇叭不存在")
        config = configs[0]
    else:
        config = {"username": "admin"}
    for key, value in values.items():
        if key != "password" or value:
            config[key] = value
    if not config.get("url") or not config.get("password"):
        raise HTTPException(422, "测试连接需要设备地址和密码")
    # 同步路由由 FastAPI 在线程池执行；永远不调用保存、心跳启动或播放接口。
    result = runtime.test_connection(config)
    return {"success": bool(result.get("online")), "runtime": result}


@router.get("/{horn_id}", response_model=HornResponse)
def get_horn(horn_id: int, service=Depends(get_horn_service),
             runtime=Depends(get_horn_runtime_manager)):
    return _response(_require_horn(service, horn_id), runtime)


@router.patch("/{horn_id}", response_model=HornResponse)
def update_horn(horn_id: int, payload: HornUpdate, service=Depends(get_horn_service),
                runtime=Depends(get_horn_runtime_manager)):
    config = service.update_horn(horn_id, payload.write_values())
    if config is None:
        raise HTTPException(404, "喇叭不存在")
    return _response(config, runtime)


@router.delete("/{horn_id}", status_code=204)
def delete_horn(horn_id: int, service=Depends(get_horn_service)):
    if not service.delete_horn(horn_id):
        raise HTTPException(404, "喇叭不存在")
    return Response(status_code=204)


@router.get("/{horn_id}/status", response_model=HornRuntimeStatus)
def horn_status(horn_id: int, service=Depends(get_horn_service),
                runtime=Depends(get_horn_runtime_manager)):
    return runtime.status(_require_horn(service, horn_id))
