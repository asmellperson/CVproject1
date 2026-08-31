# 文件说明：包含`test_managed_visual_services` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from platform.visual_services import ManagedVisualServices

import httpx
from fastapi import FastAPI, Request

from api.app import create_app


# 功能：实现 `_config_files` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（Path）：`tmp_path` 对应的业务输入值
# 返回：tuple[Path, Path]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_managed_visual_services.py` 的 `_manager` 调用本符号
#   - 内部调用：`guard.write_text`、`security.write_text`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _config_files(tmp_path: Path) -> tuple[Path, Path]:
    guard = tmp_path / "guard.yaml"
    security = tmp_path / "security.yaml"
    guard.write_text("guard: true\n", encoding="utf-8")
    security.write_text("security: true\n", encoding="utf-8")
    return guard, security


# 功能：实现 `_factory` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `events`（list[str]）：`events` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_managed_visual_services.py` 的 `_manager` 调用本符号；`AiVision/tests/test_managed_visual_services.py` 的
#         `test_missing_child_config_fails_parent_startup` 调用本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _factory(name: str, events: list[str]):
    # 功能：创建或构建 `create` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `config_path`（Path）：`config_path` 对应的业务输入值
    # 返回：FastAPI；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`events.append`、`FastAPI`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def create(config_path: Path) -> FastAPI:
        events.append(f"create:{name}:{config_path.name}")

        # 功能：实现 `lifespan` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `_app`（FastAPI）：`_app` 对应的业务输入值
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`events.append`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            events.append(f"start:{name}")
            try:
                yield
            finally:
                events.append(f"stop:{name}")

        app = FastAPI(lifespan=lifespan)

        # 功能：实现 `probe` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `value`（str）：待转换、校验或写入的值
        #   - `request`（Request）：当前 HTTP 请求及上下文
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：由 FastAPI 按 `app.get('/probe/{value}')` 注册，并在请求到达时调用以生成接口响应
        #   - 内部调用：`app.get`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        @app.get("/probe/{value}")
        async def probe(value: str, request: Request):
            return {
                "service": name,
                "value": value,
                "root_path": request.scope["root_path"],
            }

        return app

    return create


# 功能：实现 `_manager` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（Path）：`tmp_path` 对应的业务输入值
#   - `events`（list[str]）：`events` 对应的业务输入值
# 返回：ManagedVisualServices；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_managed_visual_services.py` 的 `test_visual_apps_are_called_in_process_and_share_parent_port`
#         调用本符号；`AiVision/tests/test_managed_visual_services.py` 的 `test_unbound_managed_app_returns_service_unavailable`
#         调用本符号；`AiVision/tests/test_managed_visual_services.py` 的 `test_aivision_registers_both_managed_route_trees` 调用本符号
#   - 内部调用：`_config_files`、`ManagedVisualServices`、`_factory`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _manager(tmp_path: Path, events: list[str]) -> ManagedVisualServices:
    guard, security = _config_files(tmp_path)
    return ManagedVisualServices(
        guard_room_config_path=guard,
        security_vlm_config_path=security,
        guard_room_factory=_factory("guard", events),
        security_vlm_factory=_factory("security", events),
    )


# 功能：验证 `test_visual_apps_are_called_in_process_and_share_parent_port` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_manager`、`FastAPI`、`parent.mount`、`asyncio.run`、`scenario`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_visual_apps_are_called_in_process_and_share_parent_port(tmp_path):
    events: list[str] = []
    manager = _manager(tmp_path, events)

    parent = FastAPI()
    parent.mount("/guard", manager.guard_room)
    parent.mount("/security", manager.security_vlm)

    # 功能：实现 `scenario` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`manager.lifespan`、`httpx.ASGITransport`、`httpx.AsyncClient`、`client.get`、`guard.json`、`security.json`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    async def scenario():
        async with manager.lifespan():
            transport = httpx.ASGITransport(app=parent)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://aivision.test",
            ) as client:
                guard = await client.get("/guard/probe/room-a")
                security = await client.get("/security/probe/checkpoint-a")

            assert guard.status_code == 200
            assert guard.json() == {
                "service": "guard",
                "value": "room-a",
                "root_path": "/guard",
            }
            assert security.status_code == 200
            assert security.json()["service"] == "security"
            assert manager.guard_room.app is not None
            assert manager.security_vlm.app is not None

    asyncio.run(scenario())

    assert manager.guard_room.app is None
    assert manager.security_vlm.app is None
    assert events == [
        "create:guard:guard.yaml",
        "create:security:security.yaml",
        "start:guard",
        "start:security",
        "stop:security",
        "stop:guard",
    ]


# 功能：验证 `test_unbound_managed_app_returns_service_unavailable` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_manager`、`FastAPI`、`parent.mount`、`asyncio.run`、`scenario`、`response.json`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_unbound_managed_app_returns_service_unavailable(tmp_path):
    manager = _manager(tmp_path, [])
    parent = FastAPI()
    parent.mount("/guard", manager.guard_room)

    # 功能：实现 `scenario` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`httpx.ASGITransport`、`httpx.AsyncClient`、`client.get`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    async def scenario():
        transport = httpx.ASGITransport(app=parent)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://aivision.test",
        ) as client:
            return await client.get("/guard/api/health")

    response = asyncio.run(scenario())
    assert response.status_code == 503
    assert response.json() == {"detail": "guard_room 尚未由 AiVision 初始化"}


# 功能：验证 `test_aivision_registers_both_managed_route_trees` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_manager`、`create_app`、`getattr(route, 'path', '').startswith`、`getattr`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_aivision_registers_both_managed_route_trees(tmp_path):
    manager = _manager(tmp_path, [])
    app = create_app(managed_visual_services=manager)

    mounted_paths = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v2/integrations")
    }

    assert mounted_paths == {
        "/api/v2/integrations/guard-room",
        "/api/v2/integrations/security-vlm",
    }


# 功能：验证 `test_missing_child_config_fails_parent_startup` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ManagedVisualServices`、`_factory`、`asyncio.run`、`scenario`、`str`、`AssertionError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def test_missing_child_config_fails_parent_startup(tmp_path):
    manager = ManagedVisualServices(
        guard_room_config_path=tmp_path / "missing-guard.yaml",
        security_vlm_config_path=tmp_path / "missing-security.yaml",
        guard_room_factory=_factory("guard", []),
        security_vlm_factory=_factory("security", []),
    )

    # 功能：实现 `scenario` 对应的`test_managed_visual_services` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`manager.lifespan`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def scenario():
        async with manager.lifespan():
            pass

    try:
        asyncio.run(scenario())
    except FileNotFoundError as exc:
        assert "missing-guard.yaml" in str(exc)
        assert "missing-security.yaml" in str(exc)
    else:
        raise AssertionError("缺少托管子应用配置时 AiVision 应拒绝启动")
