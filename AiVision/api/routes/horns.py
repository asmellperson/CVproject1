"""管理员喇叭配置、SIP 服务、AAC 素材和现场试播。"""
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Response, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from auth.auth import require_admin, require_config_manager
from auth.feature_permissions import require_department_write_access
from AiVision.api.deps import get_horn_runtime_manager, get_horn_service, get_horn_audio_service, get_horn_sip_service
from AiVision.core.logger import logger
from AiVision.alarms.devices.schema import (
    HornConnectionResult, HornConnectionTest, HornCreate, HornResponse,
    HornRuntimeStatus, HornUpdate,
    HornAudioResponse, HornPlaybackTest, HornPlaybackResult, SipServerConfig, SipServerResponse,
    HornUsage, HornDeleteRequest,
)
from AiVision.alarms.devices.service import HornInUseError, HornConfigError
from AiVision.alarms.devices.audio import HornAudioError
from AiVision.alarms.devices.sip_protocol import SipAudioError
from AiVision.core.settings import settings
from AiVision.departments import require_department


class HornRoute(APIRoute):
    """凭据路由单独屏蔽校验原始输入、SQL 参数和设备异常文本。"""
    def get_route_handler(self):
        """为所有设备路由包裹专用异常转换，避免凭据出现在通用错误详情中。"""
        handler = super().get_route_handler()

        async def safe_handler(request):
            """保留字段位置和错误类型，同时屏蔽输入值、数据库参数及设备异常原文。"""
            try:
                return await handler(request)
            except (RequestValidationError, ValidationError) as exc:
                errors = [{"loc": error["loc"], "type": error["type"],
                           "msg": "喇叭配置字段无效"} for error in exc.errors()]
                return JSONResponse(status_code=422, content={"detail": errors})
            except HornInUseError as exc:
                raise HTTPException(409, {"message": str(exc), "usage": exc.usage.model_dump()}) from None
            except (HornAudioError, HornConfigError) as exc:
                raise HTTPException(422, str(exc)) from None
            except SipAudioError as exc:
                raise HTTPException(409, str(exc)) from None
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
                   dependencies=[Depends(require_config_manager)])


def _horn_scope(department: str | None = None, unassigned: bool = False,
                user: dict = Depends(require_config_manager)):
    """管理员仍须明确当前事业部；未归属设备仅通过独立清理入口读取。"""
    if unassigned and department is not None:
        raise HTTPException(422, "事业部和待分配范围不能同时指定")
    if not unassigned:
        try:
            department = require_department(department)
        except ValueError:
            raise HTTPException(422, "请选择当前事业部") from None
    require_department_write_access(user, department)
    return {"department": department, "unassigned": unassigned}


def _require_horn(service, horn_id, scope):
    """取得设备公开配置，不存在时统一返回 404。"""
    config = service.get_horn(horn_id)
    if config is None or config["department"] != scope["department"]:
        raise HTTPException(404, "喇叭不存在")
    return config


def _response(config, runtime):
    """将脱敏配置与当前运行状态组合为设备响应。"""
    return dict(config, runtime=runtime.status(config))


@router.get("", response_model=list[HornResponse])
def list_horns(scope=Depends(_horn_scope), service=Depends(get_horn_service), runtime=Depends(get_horn_runtime_manager)):
    """列出设备公开配置及当前运行状态。"""
    return [_response(config, runtime) for config in service.list_horns(**scope)]


@router.post("", response_model=HornResponse, status_code=201)
def create_horn(payload: HornCreate, service=Depends(get_horn_service),
                runtime=Depends(get_horn_runtime_manager), user=Depends(require_config_manager)):
    """保存经校验的设备配置，返回脱敏资料与热同步状态。"""
    require_department_write_access(user, payload.department)
    return _response(service.create_horn(payload.write_values()), runtime)


@router.post("/test-connection", response_model=HornConnectionResult)
def test_connection(payload: HornConnectionTest, service=Depends(get_horn_service),
                    runtime=Depends(get_horn_runtime_manager), scope=Depends(_horn_scope)):
    """合并已存或临时连接参数，仅检查认证，不保存、不启动心跳也不播放。"""
    values = payload.write_values()
    horn_id = values.pop("horn_id", None)
    if horn_id is not None:
        _require_horn(service, horn_id, scope)
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


@router.get("/sip-server", response_model=SipServerResponse, dependencies=[Depends(require_admin)])
def get_sip_server(service=Depends(get_horn_sip_service)):
    """读取集中 SIP 服务参数和实际监听状态。"""
    return service.public()


@router.put("/sip-server", response_model=SipServerResponse, dependencies=[Depends(require_admin)])
def save_sip_server(payload: SipServerConfig, service=Depends(get_horn_sip_service)):
    """保存并应用前端设置的本机地址与 UDP 端口。"""
    return service.save(payload)


@router.get("/audio", response_model=list[HornAudioResponse])
def list_audio(service=Depends(get_horn_audio_service)):
    """全局音频供所有设备和检测配置复用。"""
    return service.list_audio()


@router.post("/audio", response_model=HornAudioResponse, status_code=201, dependencies=[Depends(require_admin)])
async def upload_audio(request: Request, service=Depends(get_horn_audio_service)):
    """流式限制上传大小，AAC 转码交给线程池，不阻塞 API 事件循环。"""
    filename = unquote(request.headers.get("x-audio-filename", ""))
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > settings.alarm.horn_audio_max_bytes:
            raise HTTPException(413, "音频超过服务器允许的上传大小")
        content.extend(chunk)
    return await run_in_threadpool(service.upload, filename, bytes(content))


@router.delete("/audio/{audio_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_audio(audio_id: int, service=Depends(get_horn_audio_service)):
    """删除未被检测配置引用的服务器素材。"""
    if not service.delete(audio_id):
        raise HTTPException(404, "音频素材不存在")
    return Response(status_code=204)


@router.post("/{horn_id}/test-play", response_model=HornPlaybackResult)
def test_play(horn_id: int, payload: HornPlaybackTest, service=Depends(get_horn_service),
              runtime=Depends(get_horn_runtime_manager), scope=Depends(_horn_scope)):
    """手动试播与真实报警复用同一个控制器，明确报告音频发送结果。"""
    _require_horn(service, horn_id, scope)
    configs = service.runtime_configs(horn_id)
    if not configs:
        raise HTTPException(404, "喇叭不存在")
    config = configs[0]
    if not config["enable"]:
        raise HTTPException(409, "喇叭已停用，请启用设备后试播")
    result = runtime.test_play(config, payload.audio_id)
    return {**result, "message": ("音频已发送至所选喇叭，请现场确认声音内容。" if result["success"]
                                else result["runtime"].get("last_error") or "喇叭未完成播放，请检查设备状态")}


@router.get("/{horn_id}", response_model=HornResponse)
def get_horn(horn_id: int, service=Depends(get_horn_service),
             runtime=Depends(get_horn_runtime_manager), scope=Depends(_horn_scope)):
    """返回指定设备公开配置和实时状态。"""
    return _response(_require_horn(service, horn_id, scope), runtime)


@router.patch("/{horn_id}", response_model=HornResponse)
def update_horn(horn_id: int, payload: HornUpdate, service=Depends(get_horn_service),
                runtime=Depends(get_horn_runtime_manager), scope=Depends(_horn_scope),
                user=Depends(require_config_manager)):
    """保存明确提交的设备字段并返回实际配置及同步状态。"""
    _require_horn(service, horn_id, scope)
    if user["role"] != "admin" and "department" in payload.model_fields_set and payload.department != scope["department"]:
        raise HTTPException(403, "仅系统管理员可以变更喇叭所属事业部")
    config = service.update_horn(horn_id, payload.write_values(), expected_department=scope["department"])
    if config is None:
        raise HTTPException(404, "喇叭不存在")
    return _response(config, runtime)


@router.delete("/{horn_id}", status_code=204)
def delete_horn(horn_id: int, payload: HornDeleteRequest | None = None,
                service=Depends(get_horn_service), scope=Depends(_horn_scope)):
    """删除设备；有引用时须明确确认解绑，成功返回 204，不存在返回 404。"""
    _require_horn(service, horn_id, scope)
    if not service.delete_horn(horn_id, expected_department=scope["department"], **(payload.model_dump() if payload else {})):
        raise HTTPException(404, "喇叭不存在")
    return Response(status_code=204)


@router.get("/{horn_id}/status", response_model=HornRuntimeStatus)
def horn_status(horn_id: int, service=Depends(get_horn_service),
                runtime=Depends(get_horn_runtime_manager), scope=Depends(_horn_scope)):
    """确认设备存在后读取运行状态，不触发设备网络操作。"""
    return runtime.status(_require_horn(service, horn_id, scope))


@router.get("/{horn_id}/references", response_model=HornUsage)
def horn_references(horn_id: int, service=Depends(get_horn_service), scope=Depends(_horn_scope)):
    """展示当前范围设备的全部引用，帮助定位关闭告警后保留的绑定。"""
    _require_horn(service, horn_id, scope)
    usage = service.get_usage(horn_id)
    if usage is None:
        raise HTTPException(404, "喇叭不存在")
    return usage
