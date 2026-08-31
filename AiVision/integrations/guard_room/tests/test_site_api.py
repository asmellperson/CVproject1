# 文件说明：包含接口访问的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import configure_for_tests
from src.server import CameraCreateRequest, CameraUpdateRequest, SiteCreateRequest, create_app
from src.service import GuardRoomService


# 功能：实现 `_app` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_site_api.py` 的 `test_site_api_routes_create_site_and_camera`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_site_api.py` 的 `test_site_api_routes_scope_sites_by_department`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_site_api.py` 的 `test_site_api_routes_update_and_delete_camera` 调用本符号
#   - 内部调用：`configure_for_tests`、`create_app`、`str`、`Path(__file__).resolve`、`Path`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _app(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_api.db'}")
    return create_app(str(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"))


# 功能：实现 `_route_endpoint` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `app`（未显式标注）：`app` 对应的业务输入值
#   - `path`（str）：目标路径
#   - `method`（str）：`method` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_site_api.py` 的 `test_site_api_routes_create_site_and_camera`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_site_api.py` 的 `test_site_api_routes_scope_sites_by_department`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_site_api.py` 的 `test_site_api_routes_update_and_delete_camera`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_site_api.py` 的
#         `test_site_api_routes_expose_runtime_controls_and_read_models` 调用本符号；另有 1 处静态调用
#   - 内部调用：`method.upper`、`getattr`、`set`、`AssertionError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _route_endpoint(app, path: str, method: str):
    method = method.upper()
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


# 功能：定义 `FakeRuntimeManager` 类，封装接口访问相关的状态、约束与操作
# 参数：无。
# 返回：FakeRuntimeManager；返回新建的 `FakeRuntimeManager` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeRuntimeManager:
    # 功能：初始化或配置 `__init__` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        self.started = []
        self.stopped = []
        self.restarted = []
        self.stop_all_calls = 0

    # 功能：启动或执行 `start` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.started.append`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def start(self, site_id: int):
        self.started.append(site_id)
        return {"site_id": site_id, "site_name": "测试保安室", "running": True}

    # 功能：停止并释放 `stop` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.stopped.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def stop(self, site_id: int):
        self.stopped.append(site_id)
        return {"site_id": site_id, "site_name": "测试保安室", "running": False}

    # 功能：实现 `restart` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.restarted.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def restart(self, site_id: int):
        self.restarted.append(site_id)
        return {"site_id": site_id, "site_name": "测试保安室", "running": True, "restarted": True}

    # 功能：读取或查询 `get_status` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_status(self, site_id: int):
        return {"site_id": site_id, "site_name": "测试保安室", "running": False}

    # 功能：读取或查询 `get_latest_frame` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_latest_frame(self, site_id: int):
        return b"jpeg-bytes"

    # 功能：读取或查询 `get_camera_frame` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`f'{site_id}:{camera_id}:jpeg'.encode`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_camera_frame(self, site_id: int, camera_id: str):
        return f"{site_id}:{camera_id}:jpeg".encode()

    # 功能：读取或查询 `get_alarms` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `limit`（int）：返回或处理的最大记录数；默认值为 `50`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_alarms(self, site_id: int, limit: int = 50):
        return [{"id": "alarm-1", "site_id": site_id, "site_name": "测试保安室"}]

    # 功能：读取或查询 `get_statistics` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_statistics(self, site_id: int):
        return {"site_id": site_id, "site_name": "测试保安室", "summary": {"total": 0}}

    # 功能：停止并释放 `stop_all` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def stop_all(self):
        self.stop_all_calls += 1


# 功能：验证 `test_site_api_routes_create_site_and_camera` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_app`、`_route_endpoint`、`create_site`、`SiteCreateRequest`、`list_sites`、`create_camera`、`CameraCreateRequest`、`get_site`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_site_api_routes_create_site_and_camera(tmp_path):
    app = _app(tmp_path)

    create_site = _route_endpoint(app, "/api/sites", "POST")
    list_sites = _route_endpoint(app, "/api/sites", "GET")
    get_site = _route_endpoint(app, "/api/sites/{site_id}", "GET")
    create_camera = _route_endpoint(app, "/api/sites/{site_id}/cameras", "POST")

    site = create_site(SiteCreateRequest(name="一厂区南门保安室"), _user={"role": "admin"})
    assert site["name"] == "一厂区南门保安室"
    assert site["camera_count"] == 0

    listed = list_sites()
    assert [item["name"] for item in listed["items"]] == ["一厂区南门保安室"]

    camera = create_camera(
        site["id"],
        CameraCreateRequest(name="门口左侧", rtsp_url="rtsp://camera-1"),
        _user={"role": "admin"},
    )
    assert camera["sort_order"] == 1

    detail = get_site(site["id"])
    assert detail["cameras"][0]["name"] == "门口左侧"


# 功能：验证 `test_site_api_routes_scope_sites_by_department` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_app`、`_route_endpoint`、`create_site`、`SiteCreateRequest`、`list_sites`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_site_api_routes_scope_sites_by_department(tmp_path):
    app = _app(tmp_path)

    create_site = _route_endpoint(app, "/api/sites", "POST")
    list_sites = _route_endpoint(app, "/api/sites", "GET")

    create_site(
        SiteCreateRequest(name="通用电气保安室", department="general_electric"),
        _user={"role": "admin", "department": "all"},
    )
    create_site(
        SiteCreateRequest(name="电子电工保安室", department="electronics_electrician"),
        _user={"role": "admin", "department": "all"},
    )

    assert [item["name"] for item in list_sites(department="general_electric")["items"]] == ["通用电气保安室"]
    assert [item["name"] for item in list_sites(department="electronics_electrician")["items"]] == ["电子电工保安室"]

    multi_department_viewer = {
        "role": "viewer",
        "department": "general_electric",
        "departments": ["general_electric", "electronics_electrician"],
    }
    assert [item["name"] for item in list_sites(
        department="electronics_electrician",
        _user=multi_department_viewer,
    )["items"]] == ["电子电工保安室"]
    with pytest.raises(HTTPException) as caught:
        list_sites(department="electrical_components", _user=multi_department_viewer)
    assert caught.value.status_code == 403


# 功能：验证 `test_site_api_routes_update_and_delete_camera` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_app`、`_route_endpoint`、`create_site`、`SiteCreateRequest`、`create_camera`、`CameraCreateRequest`、`update_camera`、`CameraUpdateRequest`、`delete_camera`、`get_site`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_site_api_routes_update_and_delete_camera(tmp_path):
    app = _app(tmp_path)

    create_site = _route_endpoint(app, "/api/sites", "POST")
    create_camera = _route_endpoint(app, "/api/sites/{site_id}/cameras", "POST")
    update_camera = _route_endpoint(app, "/api/cameras/{camera_id}", "PUT")
    delete_camera = _route_endpoint(app, "/api/cameras/{camera_id}", "DELETE")
    get_site = _route_endpoint(app, "/api/sites/{site_id}", "GET")

    site = create_site(SiteCreateRequest(name="二厂区值班室"), _user={"role": "admin"})
    camera = create_camera(
        site["id"],
        CameraCreateRequest(name="旧名称", rtsp_url="rtsp://old"),
        _user={"role": "admin"},
    )

    updated = update_camera(
        camera["id"],
        CameraUpdateRequest(name="门口右侧", rtsp_url="rtsp://new", enabled=False),
        _user={"role": "admin"},
    )
    assert updated["name"] == "门口右侧"
    assert updated["rtsp_url"] == "rtsp://new"
    assert updated["enabled"] is False

    assert delete_camera(camera["id"], _user={"role": "admin"}) == {"success": True}
    assert get_site(site["id"])["cameras"] == []


# 功能：验证 `test_site_api_routes_expose_runtime_controls_and_read_models` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`configure_for_tests`、`FakeRuntimeManager`、`create_app`、`str`、`Path(__file__).resolve`、`Path`、`_route_endpoint`、`start`、`stop`、`restart`
#          等共 15 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_site_api_routes_expose_runtime_controls_and_read_models(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_api_runtime.db'}")
    manager = FakeRuntimeManager()
    app = create_app(
        str(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"),
        runtime_manager=manager,
    )

    start = _route_endpoint(app, "/api/sites/{site_id}/control/start", "POST")
    stop = _route_endpoint(app, "/api/sites/{site_id}/control/stop", "POST")
    restart = _route_endpoint(app, "/api/sites/{site_id}/control/restart", "POST")
    status = _route_endpoint(app, "/api/sites/{site_id}/status", "GET")
    frame = _route_endpoint(app, "/api/sites/{site_id}/frame.jpg", "GET")
    camera_frame = _route_endpoint(app, "/api/sites/{site_id}/cameras/{camera_id}/frame.jpg", "GET")
    alarms = _route_endpoint(app, "/api/sites/{site_id}/alarms", "GET")
    statistics = _route_endpoint(app, "/api/sites/{site_id}/statistics", "GET")

    assert start(7, _user={"role": "admin"})["running"] is True
    assert stop(7, _user={"role": "admin"})["running"] is False
    assert restart(7, _user={"role": "admin"})["restarted"] is True
    assert manager.restarted == [7]
    assert status(7)["site_name"] == "测试保安室"
    assert frame(7).body == b"jpeg-bytes"
    assert camera_frame(7, "cam2").body == b"7:cam2:jpeg"
    assert alarms(7)["items"][0]["site_id"] == 7
    assert statistics(7)["summary"]["total"] == 0


# 功能：验证 `test_app_lifespan_starts_enabled_sites_and_preserves_disabled_sites` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`configure_for_tests`、`GuardRoomService`、`service.ensure_schema`、`service.create_site`、`service.create_camera`、`FakeRuntimeManager`、`create_app`、`str`、`Path(__file__).resolve`、`Path`
#          等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_app_lifespan_starts_enabled_sites_and_preserves_disabled_sites(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_api_lifespan.db'}")
    service = GuardRoomService()
    service.ensure_schema()
    enabled = service.create_site("默认开启")
    disabled = service.create_site("手动关闭", enabled=False)
    service.create_camera(enabled["id"], name="入口", rtsp_url="rtsp://enabled")
    service.create_camera(disabled["id"], name="入口", rtsp_url="rtsp://disabled")
    manager = FakeRuntimeManager()
    app = create_app(
        str(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"),
        guard_room_service=service,
        runtime_manager=manager,
    )

    # 功能：启动或执行 `run_lifespan` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`app.router.lifespan_context`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def run_lifespan():
        async with app.router.lifespan_context(app):
            assert manager.started == [enabled["id"]]

    asyncio.run(run_lifespan())

    assert manager.stop_all_calls == 1


# 功能：验证 `test_first_enabled_camera_starts_an_enabled_site_after_app_startup` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`configure_for_tests`、`GuardRoomService`、`service.ensure_schema`、`service.create_site`、`FakeRuntimeManager`、`create_app`、`str`、`Path(__file__).resolve`、`Path`、`_route_endpoint`
#          等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_first_enabled_camera_starts_an_enabled_site_after_app_startup(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_api_first_camera.db'}")
    service = GuardRoomService()
    service.ensure_schema()
    site = service.create_site("待添加摄像头")
    manager = FakeRuntimeManager()
    app = create_app(
        str(Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"),
        guard_room_service=service,
        runtime_manager=manager,
    )
    create_camera = _route_endpoint(app, "/api/sites/{site_id}/cameras", "POST")

    # 功能：启动或执行 `run_lifespan` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`app.router.lifespan_context`、`create_camera`、`CameraCreateRequest`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def run_lifespan():
        async with app.router.lifespan_context(app):
            assert manager.started == []
            create_camera(
                site["id"],
                CameraCreateRequest(name="入口", rtsp_url="rtsp://camera"),
                _user={"role": "admin"},
            )
            assert manager.restarted == [site["id"]]

    asyncio.run(run_lifespan())
