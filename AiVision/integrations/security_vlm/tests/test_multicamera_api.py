# 文件说明：包含接口访问的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import json
from pathlib import Path

import httpx
import pytest
import yaml

from AiVision.integrations.security_vlm.src import camera_registry
from AiVision.integrations.security_vlm.src import main

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
    #   - 内部调用：`set`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        self.running = set()
        self.shutdown_called = False

    # 功能：启动或执行 `start` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（未显式标注）：业务部门名称或标识
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的 `FakeRuntimeManager::restart` 调用本符号
    #   - 内部调用：`self.running.add`、`self._result`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def start(self, department, camera_id):
        self.running.add((department, camera_id))
        return self._result(department, camera_id, True, "running")

    # 功能：停止并释放 `stop` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（未显式标注）：业务部门名称或标识
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.running.discard`、`self._result`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def stop(self, department, camera_id):
        self.running.discard((department, camera_id))
        return self._result(department, camera_id, True, "stopped")

    # 功能：实现 `restart` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（未显式标注）：业务部门名称或标识
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.start`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def restart(self, department, camera_id):
        return self.start(department, camera_id)

    # 功能：启动或执行 `start_all` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（未显式标注）：业务部门名称或标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def start_all(self, department):
        return {"ok": True, "results": {}}

    # 功能：停止并释放 `stop_all` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（未显式标注）：业务部门名称或标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def stop_all(self, department):
        self.running = {
            key for key in self.running if key[0] != department
        }
        return {"ok": True, "results": {}}

    # 功能：检查或判断 `is_running` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（未显式标注）：业务部门名称或标识
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的 `FakeRuntimeManager::status`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的 `FakeRuntimeManager::_result` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def is_running(self, department, camera_id):
        return (department, camera_id) in self.running

    # 功能：实现 `status` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（未显式标注）：业务部门名称或标识
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.is_running`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def status(self, department, camera_id):
        running = self.is_running(department, camera_id)
        return {
            "department": department,
            "camera_id": camera_id,
            "running": running,
            "desired_running": running,
            "workers": {
                "capture": running,
                "detector": running,
                "session": running,
            },
            "last_error": "",
            "restart_at": None,
        }

    # 功能：实现 `reconcile` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def reconcile(self):
        return None

    # 功能：停止并释放 `shutdown` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.running.clear`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def shutdown(self):
        self.shutdown_called = True
        self.running.clear()

    # 功能：实现 `_result` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（未显式标注）：业务部门名称或标识
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `ok`（未显式标注）：`ok` 对应的业务输入值
    #   - `message`（未显式标注）：用于展示、记录或发送的文本消息
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的 `FakeRuntimeManager::start`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的 `FakeRuntimeManager::stop` 调用本符号
    #   - 内部调用：`self.is_running`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _result(self, department, camera_id, ok, message):
        return {
            "ok": ok,
            "department": department,
            "camera_id": camera_id,
            "running": self.is_running(department, camera_id),
            "desired_running": self.is_running(department, camera_id),
            "message": message,
        }


# 功能：创建或构建 `make_service` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `input_video`（未显式标注）：`input_video` 对应的业务输入值；默认值为 `''`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的
#         `test_department_cameras_are_isolated_and_legacy_is_deprecated`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的
#         `test_department_update_and_bulk_control_invalidate_frame_hub_cache`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的
#         `test_camera_crud_redaction_and_running_conflicts`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的
#         `test_department_capacity_same_id_roi_history_and_delete_are_isolated` 调用本符号；另有 5 处静态调用
#   - 内部调用：`str`、`config_path.write_text`、`yaml.safe_dump`、`camera_registry.CameraRegistry`、`Path`、`FakeRuntimeManager`、`main.AppService`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def make_service(tmp_path, *, input_video=""):
    config = {
        "project": {"root": str(tmp_path)},
        "envs": {"worker_python": "/env/bin/python"},
        "runtime": {"dir": str(tmp_path / "runtime")},
        "departments": {
            "data_root": str(tmp_path / "departments"),
            "runtime_root": str(tmp_path / "runtime" / "departments"),
        },
        "web": {},
        "data": {
            "input_video": input_video,
            "video_id": "stream",
            "camera_registry_path": str(tmp_path / "config" / "cameras.json"),
            "staff_identity_dir": str(tmp_path / "staff_rois"),
        },
        "staff_rois": {"security_staff_1": [1, 2, 3, 4]},
        "roi": {"min_area_px": 100, "max_vertices": 64},
        "session": {},
        "vlm": {},
        "output": {},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True),
        encoding="utf-8",
    )
    registry = camera_registry.CameraRegistry(
        Path(config["data"]["camera_registry_path"])
    )
    runtime_manager = FakeRuntimeManager()
    service = main.AppService(
        config_path,
        registry=registry,
        runtime_manager=runtime_manager,
        probe_func=lambda _url: {
            "codec_name": "hevc",
            "width": 2560,
            "height": 1440,
        },
        offload_sync=False,
    )
    return service, runtime_manager


# 功能：更新或保存 `set_capture_dimensions` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service`（未显式标注）：`service` 对应的业务输入值
#   - `camera_id`（未显式标注）：摄像头唯一标识
#   - `width`（未显式标注）：`width` 对应的业务输入值；默认值为 `200`
#   - `height`（未显式标注）：`height` 对应的业务输入值；默认值为 `100`
#   - `department`（未显式标注）：业务部门名称或标识；默认值为 `main.GENERAL_ELECTRIC`
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的
#         `test_department_capacity_same_id_roi_history_and_delete_are_isolated`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的 `test_camera_scoped_rois_and_history_filter`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的
#         `test_legacy_hikvision_roi_migrates_and_mixed_streams_scale_independently`
#         调用本符号；`AiVision/integrations/security_vlm/tests/test_multicamera_api.py` 的
#         `test_roi_save_requires_capture_dimensions_and_validates_geometry` 调用本符号
#   - 内部调用：`service.camera_store(camera_id, department).write`、`service.camera_store`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def set_capture_dimensions(
    service,
    camera_id,
    width=200,
    height=100,
    department=main.GENERAL_ELECTRIC,
):
    service.camera_store(camera_id, department).write(
        "capture_status",
        {"ok": True, "width": width, "height": height},
    )


# 功能：验证 `test_department_cameras_are_isolated_and_legacy_is_deprecated` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`make_service`、`main.create_app`、`httpx.ASGITransport`、`httpx.AsyncClient`、`client.get`、`client.post`、`created.json`、`legacy.json`。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
@pytest.mark.asyncio
async def test_department_cameras_are_isolated_and_legacy_is_deprecated(tmp_path):
    service, _runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    base = "/api/departments"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for department in (
            "general_electric", "electronics_electrician",
            "electrical_components", "precious_metal_recycling",
        ):
            response = await client.get(f"{base}/{department}/cameras")
            assert response.status_code == 200
        created = await client.post(
            f"{base}/electronics_electrician/cameras",
            json={"name": "same", "rtsp_url": "rtsp://camera-a/stream"},
        )
        assert created.status_code == 201
        camera_id = created.json()["camera"]["camera_id"]
        assert (await client.get(
            f"{base}/general_electric/cameras/{camera_id}"
        )).status_code == 404
        legacy = await client.get("/api/cameras")
        assert legacy.headers["Deprecation"] == "true"
        assert legacy.json()["cameras"] == []
        assert (await client.get(f"{base}/unknown/cameras")).status_code == 400


# 功能：验证 `test_department_update_and_bulk_control_invalidate_frame_hub_cache` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`make_service`、`main.create_app`、`httpx.ASGITransport`、`httpx.AsyncClient`、`(await client.post(base, json={'name': 'A',
#          'rtsp_url': 'rtsp://camera-a/Streaming/Channels/101'})).json`、`client.post`、`object`、`client.put`。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
@pytest.mark.asyncio
async def test_department_update_and_bulk_control_invalidate_frame_hub_cache(
    tmp_path,
):
    service, _runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    department = "electronics_electrician"
    base = f"/api/departments/{department}/cameras"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        camera = (await client.post(
            base,
            json={"name": "A", "rtsp_url": "rtsp://camera-a/Streaming/Channels/101"},
        )).json()["camera"]
        camera_id = camera["camera_id"]
        cache_key = (department, camera_id)

        service._frame_hubs[cache_key] = object()
        updated = await client.put(
            f"{base}/{camera_id}",
            json={"rtsp_url": "rtsp://camera-a/Streaming/Channels/102"},
        )
        assert updated.status_code == 200
        assert cache_key not in service._frame_hubs

        service._frame_hubs[cache_key] = object()
        stopped = await client.post(f"{base}/control/stop-all")
        assert stopped.status_code == 200
        assert cache_key not in service._frame_hubs


# 功能：验证 `test_app_service_resolves_department_roots_and_reads_general_results` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`fake_main.parent.mkdir`、`monkeypatch.setattr`、`str`、`config_path.write_text`、`yaml.safe_dump`、`camera_registry.CameraRegistry`、`main.AppService`、`FakeRuntimeManager`、`(project_root
#          / 'runtime').resolve`、`(project_root / 'runtime' / 'custom' / 'departments').resolve` 等共 12 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_app_service_resolves_department_roots_and_reads_general_results(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "security_vlm"
    fake_main = project_root / "src" / "main.py"
    fake_main.parent.mkdir(parents=True)
    monkeypatch.setattr(main, "__file__", str(fake_main))
    config = {
        "envs": {"worker_python": "/env/bin/python"},
        "runtime": {"dir": "runtime"},
        "departments": {
            "runtime_root": "runtime/custom/departments",
            "data_root": "data/custom/departments",
        },
        "data": {
            "camera_registry_path": "data/config/cameras.json",
            "staff_identity_dir": "data/annotations/staff_rois",
        },
        "session": {},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    registry = camera_registry.CameraRegistry(tmp_path / "cameras.json")

    service = main.AppService(
        config_path,
        registry=registry,
        runtime_manager=FakeRuntimeManager(),
        offload_sync=False,
    )

    assert service.runtime_dir == (project_root / "runtime").resolve()
    assert service.departments_runtime_root == (
        project_root / "runtime" / "custom" / "departments"
    ).resolve()
    assert service.departments_data_root == (
        project_root / "data" / "custom" / "departments"
    ).resolve()
    assert service.global_store.runtime_dir == (
        service.departments_data_root / "general_electric" / "results"
    )
    assert service.camera_runtime_dir("camera-a") == (
        service.departments_runtime_root
        / "general_electric"
        / "cameras"
        / "camera-a"
    )


# 功能：验证 `test_camera_crud_redaction_and_running_conflicts` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`make_service`、`main.create_app`、`httpx.ASGITransport`、`httpx.AsyncClient`、`client.post`、`created_response.json`、`client.get`、`credentials_response.json`、`client.put`、`client.delete`。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
@pytest.mark.asyncio
async def test_camera_crud_redaction_and_running_conflicts(tmp_path):
    service, runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created_response = await client.post(
            "/api/cameras",
            json={
                "name": "安检工位一号",
                "rtsp_url": "rtsp://admin:secret@camera-a/stream",
            },
        )
        assert created_response.status_code == 201
        camera = created_response.json()["camera"]
        camera_id = camera["camera_id"]
        assert camera["rtsp_url"] == "rtsp://***:***@camera-a/stream"
        assert "secret" not in (await client.get("/api/cameras")).text
        credentials_response = await client.get(
            f"/api/cameras/{camera_id}/credentials"
        )
        assert credentials_response.status_code == 200
        assert credentials_response.json()["camera"]["rtsp_url"] == (
            "rtsp://admin:secret@camera-a/stream"
        )
        assert (
            await client.get("/api/cameras/missing/credentials")
        ).status_code == 404

        assert (await client.put(
            f"/api/cameras/{camera_id}",
            json={"name": "一号工位", "rtsp_url": ""},
        )).status_code == 200
        assert (await client.post(
            f"/api/cameras/{camera_id}/control/start"
        )).status_code == 200
        assert (main.GENERAL_ELECTRIC, camera_id) in runtime_manager.running
        assert (await client.put(
            f"/api/cameras/{camera_id}",
            json={"name": "运行中不可改"},
        )).status_code == 409
        assert (await client.delete(f"/api/cameras/{camera_id}")).status_code == 409

        await client.post(f"/api/cameras/{camera_id}/control/stop")
        assert (await client.delete(f"/api/cameras/{camera_id}")).status_code == 200
        assert (await client.get(f"/api/cameras/{camera_id}")).status_code == 404


# 功能：验证 `test_department_capacity_same_id_roi_history_and_delete_are_isolated` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`make_service`、`main.create_app`、`httpx.ASGITransport`、`camera_registry.uuid.UUID`、`httpx.AsyncClient`、`monkeypatch.context`、`patch.setattr`、`(await
#          client.post(f'{base}/{electronics}/cameras', json={'name': '共享名称', 'rtsp_url':
#          'rtsp://electronics/stream'})).json`、`client.post`、`(await client.post(f'{base}/{components}/cameras', json={'name':
#          '共享名称', 'rtsp_url': 'rtsp://components/stream'})).json` 等共 30 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能发起网络请求或发送外部消息。
@pytest.mark.asyncio
async def test_department_capacity_same_id_roi_history_and_delete_are_isolated(
    tmp_path,
    monkeypatch,
):
    service, runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    base = "/api/departments"
    electronics = "electronics_electrician"
    components = "electrical_components"

    # 摄像头 ID 只需在事业部内唯一；相同 ID 在不同事业部也必须互不影响。
    fixed_uuid = camera_registry.uuid.UUID(
        "00000000-0000-0000-0000-000000000001"
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with monkeypatch.context() as patch:
            patch.setattr(camera_registry.uuid, "uuid4", lambda: fixed_uuid)
            electronics_camera = (await client.post(
                f"{base}/{electronics}/cameras",
                json={
                    "name": "共享名称",
                    "rtsp_url": "rtsp://electronics/stream",
                },
            )).json()["camera"]
            components_camera = (await client.post(
                f"{base}/{components}/cameras",
                json={
                    "name": "共享名称",
                    "rtsp_url": "rtsp://components/stream",
                },
            )).json()["camera"]
        camera_id = electronics_camera["camera_id"]
        assert camera_id == components_camera["camera_id"] == str(fixed_uuid)

        for index in range(3):
            response = await client.post(
                f"{base}/{electronics}/cameras",
                json={
                    "name": f"电子电工-{index}",
                    "rtsp_url": f"rtsp://electronics-{index}/stream",
                },
            )
            assert response.status_code == 201
        assert (await client.post(
            f"{base}/{electronics}/cameras",
            json={"name": "第五台", "rtsp_url": "rtsp://electronics-5/stream"},
        )).status_code == 400
        assert len((await client.get(
            f"{base}/{components}/cameras"
        )).json()["cameras"]) == 1

        set_capture_dimensions(
            service,
            camera_id,
            department=electronics,
        )
        polygon = [[10, 10], [150, 10], [170, 70], [20, 80]]
        saved = await client.put(
            f"{base}/{electronics}/cameras/{camera_id}/rois",
            json={"staff_rois": {"电子电工区域": polygon}},
        )
        assert saved.status_code == 200
        assert (await client.get(
            f"{base}/{components}/cameras/{camera_id}/rois"
        )).json()["staff_rois"] == {}

        service.workspace(electronics).result_store.write(
            "vlm_history",
            {"items": [{"camera_id": camera_id, "session_id": "electronics-1"}]},
        )
        service.workspace(electronics).result_store.write(
            "vlm_latest_stats",
            {"total": 1, "non_compliant": 1},
        )
        service.workspace(components).result_store.write(
            "vlm_history",
            {"items": [{"camera_id": camera_id, "session_id": "components-1"}]},
        )
        electronics_history = (await client.get(
            f"{base}/{electronics}/history"
        )).json()
        components_history = (await client.get(
            f"{base}/{components}/history"
        )).json()
        assert [item["session_id"] for item in electronics_history["history"]] == [
            "electronics-1"
        ]
        assert [item["session_id"] for item in components_history["history"]] == [
            "components-1"
        ]
        assert electronics_history["stats"]["non_compliant"] == 1
        assert components_history["stats"] == {}

        assert (await client.post(
            f"{base}/{electronics}/cameras/{camera_id}/control/start"
        )).status_code == 200
        assert (electronics, camera_id) in runtime_manager.running
        assert (components, camera_id) not in runtime_manager.running

        runtime_marker = service.camera_runtime_dir(camera_id, electronics)
        runtime_marker.mkdir(parents=True, exist_ok=True)
        (runtime_marker / "marker.json").write_text("{}", encoding="utf-8")
        deleted = await client.delete(
            f"{base}/{electronics}/cameras/{camera_id}"
        )
        assert deleted.status_code == 200
        assert (electronics, camera_id) not in runtime_manager.running
        assert (await client.get(
            f"{base}/{electronics}/cameras/{camera_id}"
        )).status_code == 404
        assert (await client.get(
            f"{base}/{components}/cameras/{camera_id}"
        )).status_code == 200
        assert (await client.get(
            f"{base}/{electronics}/history"
        )).json()["history"][0]["session_id"] == "electronics-1"

        archives = list(
            (service.workspace(electronics).archive_dir / camera_id).iterdir()
        )
        assert len(archives) == 1
        archived_names = {path.name for path in archives[0].iterdir()}
        assert f"{camera_id}_staff_rois.json" in archived_names
        assert camera_id in archived_names

        assert (await client.get(
            f"{base}/{components}/video/{camera_id}/invalid"
        )).status_code == 404


# 功能：验证 `test_camera_test_controls_health_and_unknown_ids` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`make_service`、`main.create_app`、`httpx.ASGITransport`、`httpx.AsyncClient`、`client.post`、`tested.json`、`(await
#          client.post('/api/cameras', json={'name': 'A', 'rtsp_url': 'rtsp://camera-a/stream'})).json`、`(await
#          client.post(f'/api/cameras/{camera_id}/control/start')).json`、`(await client.get('/health')).json`、`client.get`。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
@pytest.mark.asyncio
async def test_camera_test_controls_health_and_unknown_ids(tmp_path):
    service, _runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        tested = await client.post(
            "/api/cameras/test",
            json={"rtsp_url": "rtsp://admin:secret@camera-a/stream"},
        )
        assert tested.status_code == 200
        assert tested.json() == {
            "ok": True,
            "codec_name": "hevc",
            "width": 2560,
            "height": 1440,
        }
        assert "secret" not in tested.text
        assert (await client.post(
            "/api/cameras/test",
            json={"rtsp_url": "http://camera-a/stream"},
        )).status_code == 400

        camera_id = (await client.post(
            "/api/cameras",
            json={"name": "A", "rtsp_url": "rtsp://camera-a/stream"},
        )).json()["camera"]["camera_id"]
        assert (await client.post(
            f"/api/cameras/{camera_id}/control/start"
        )).json()["running"] is True
        health = (await client.get("/health")).json()
        assert health["running"] is True
        assert health["cameras"][0]["camera_id"] == camera_id
        assert health["cameras"][0]["running"] is True
        assert (await client.post("/api/cameras/control/stop-all")).status_code == 200
        assert (await client.post("/api/cameras/control/start-all")).status_code == 200
        assert (await client.post("/api/cameras/missing/control/start")).status_code == 404
        assert (await client.get("/video/missing/original")).status_code == 404


# 功能：验证 `test_camera_scoped_rois_and_history_filter` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`make_service`、`main.create_app`、`httpx.ASGITransport`、`httpx.AsyncClient`、`(await client.post('/api/cameras',
#          json={'name': 'A', 'rtsp_url': 'rtsp://camera-a/stream'})).json`、`client.post`、`(await client.post('/api/cameras',
#          json={'name': 'B', 'rtsp_url':
#          'rtsp://camera-b/stream'})).json`、`set_capture_dimensions`、`json.loads`、`service.roi_path(camera_a['camera_id']).read_text`
#          等共 18 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能发起网络请求或发送外部消息。
@pytest.mark.asyncio
async def test_camera_scoped_rois_and_history_filter(tmp_path):
    service, _runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        camera_a = (await client.post(
            "/api/cameras",
            json={"name": "A", "rtsp_url": "rtsp://camera-a/stream"},
        )).json()["camera"]
        camera_b = (await client.post(
            "/api/cameras",
            json={"name": "B", "rtsp_url": "rtsp://camera-b/stream"},
        )).json()["camera"]
        set_capture_dimensions(service, camera_a["camera_id"])

        saved = await client.post(
            f"/api/cameras/{camera_a['camera_id']}/rois",
            json={"staff_rois": {"工位 1": [10, 20, 30, 40]}},
        )
        assert saved.status_code == 200
        saved_payload = json.loads(
            service.roi_path(camera_a["camera_id"]).read_text(encoding="utf-8")
        )
        assert saved_payload["source_width"] == 200
        assert saved_payload["source_height"] == 100
        rectangle = [
            [10.0, 20.0],
            [30.0, 20.0],
            [30.0, 40.0],
            [10.0, 40.0],
        ]
        assert (await client.get(
            f"/api/cameras/{camera_a['camera_id']}/rois"
        )).json()["staff_rois"] == {"工位 1": rectangle}
        set_capture_dimensions(service, camera_a["camera_id"], width=100, height=50)
        assert (await client.get(
            f"/api/cameras/{camera_a['camera_id']}/rois"
        )).json()["staff_rois"] == {
            "工位 1": [[5.0, 10.0], [15.0, 10.0], [15.0, 20.0], [5.0, 20.0]],
        }
        set_capture_dimensions(service, camera_a["camera_id"])
        assert (await client.get(
            f"/api/cameras/{camera_b['camera_id']}/rois"
        )).json()["staff_rois"] == {
            "security_staff_1": [
                [1.0, 2.0],
                [3.0, 2.0],
                [3.0, 4.0],
                [1.0, 4.0],
            ]
        }

        polygon = [[5, 5], [150, 5], [180, 50], [100, 90], [10, 80]]
        polygon_saved = await client.post(
            f"/api/cameras/{camera_a['camera_id']}/rois",
            json={"staff_rois": {"多边形工位": polygon}},
        )
        assert polygon_saved.status_code == 200
        assert polygon_saved.json()["staff_rois"] == {
            "多边形工位": [[float(x), float(y)] for x, y in polygon]
        }
        assert (await client.get(
            f"/api/cameras/{camera_b['camera_id']}/rois"
        )).json()["staff_rois"] == {
            "security_staff_1": [
                [1.0, 2.0],
                [3.0, 2.0],
                [3.0, 4.0],
                [1.0, 4.0],
            ]
        }

        service.global_store.write(
            "vlm_history",
            {
                "items": [
                    {"camera_id": camera_a["camera_id"], "session_id": "a1"},
                    {"camera_id": camera_b["camera_id"], "session_id": "b1"},
                ],
            },
        )
        history = (await client.get(
            f"/api/history?camera_id={camera_a['camera_id']}"
        )).json()["history"]
        assert [item["session_id"] for item in history] == ["a1"]


# 功能：验证 `test_legacy_hikvision_roi_migrates_and_mixed_streams_scale_independently` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`make_service`、`main.create_app`、`httpx.ASGITransport`、`httpx.AsyncClient`、`(await client.post(base, json={'name':
#          '子码流工位', 'rtsp_url': 'rtsp://camera-a/Streaming/Channels/102'})).json`、`client.post`、`(await client.post(base,
#          json={'name': '主码流工位', 'rtsp_url':
#          'rtsp://camera-b/Streaming/Channels/101'})).json`、`set_capture_dimensions`、`service.roi_path(camera['camera_id'],
#          department).write_text`、`service.roi_path` 等共 18 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能发起网络请求或发送外部消息。
@pytest.mark.asyncio
async def test_legacy_hikvision_roi_migrates_and_mixed_streams_scale_independently(
    tmp_path,
):
    service, _runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    department = "electronics_electrician"
    base = f"/api/departments/{department}/cameras"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        sub_camera = (await client.post(
            base,
            json={
                "name": "子码流工位",
                "rtsp_url": "rtsp://camera-a/Streaming/Channels/102",
            },
        )).json()["camera"]
        main_camera = (await client.post(
            base,
            json={
                "name": "主码流工位",
                "rtsp_url": "rtsp://camera-b/Streaming/Channels/101",
            },
        )).json()["camera"]
        set_capture_dimensions(
            service,
            sub_camera["camera_id"],
            width=768,
            height=432,
            department=department,
        )
        set_capture_dimensions(
            service,
            main_camera["camera_id"],
            width=2560,
            height=1440,
            department=department,
        )
        old_roi = {
            "工位": [[100, 200], [2100, 200], [2100, 1200], [100, 1200]],
        }
        for camera in (sub_camera, main_camera):
            service.roi_path(camera["camera_id"], department).write_text(
                json.dumps({"staff_rois": old_roi}),
                encoding="utf-8",
            )

        sub_response = await client.get(f"{base}/{sub_camera['camera_id']}/rois")
        main_response = await client.get(f"{base}/{main_camera['camera_id']}/rois")

        assert sub_response.status_code == 200
        assert sub_response.json()["staff_rois"] == {
            "工位": [[30.0, 60.0], [630.0, 60.0], [630.0, 360.0], [30.0, 360.0]],
        }
        assert main_response.json()["staff_rois"] == old_roi

        migrated_path = service.roi_path(sub_camera["camera_id"], department)
        migrated = json.loads(migrated_path.read_text(encoding="utf-8"))
        assert migrated["source_width"] == 2560
        assert migrated["source_height"] == 1440
        assert migrated_path.with_name(
            f"{migrated_path.stem}.pre-dimension-migration.json"
        ).exists()


# 功能：验证 `test_roi_save_requires_capture_dimensions_and_validates_geometry` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`make_service`、`main.create_app`、`httpx.ASGITransport`、`httpx.AsyncClient`、`(await client.post('/api/cameras',
#          json={'name': 'A', 'rtsp_url':
#          'rtsp://camera-a/stream'})).json`、`client.post`、`missing_dimensions.json`、`float`、`service.camera_store(camera_id).write`、`service.camera_store`
#          等共 15 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能发起网络请求或发送外部消息。
@pytest.mark.asyncio
async def test_roi_save_requires_capture_dimensions_and_validates_geometry(tmp_path):
    service, _runtime_manager = make_service(tmp_path)
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        camera_id = (await client.post(
            "/api/cameras",
            json={"name": "A", "rtsp_url": "rtsp://camera-a/stream"},
        )).json()["camera"]["camera_id"]
        endpoint = f"/api/cameras/{camera_id}/rois"

        missing_dimensions = await client.post(
            endpoint,
            json={"staff_rois": {"工位": [10, 10, 50, 50]}},
        )
        assert missing_dimensions.status_code == 409
        assert "启动摄像头" in missing_dimensions.json()["detail"]

        invalid_capture_statuses = [
            {"ok": 1, "width": 200, "height": 100},
            {"ok": True, "width": "200", "height": 100},
            {"ok": True, "width": True, "height": 100},
            {"ok": True, "width": 10**400, "height": 100},
            {"ok": True, "width": float("inf"), "height": 100},
        ]
        for status in invalid_capture_statuses:
            service.camera_store(camera_id).write("capture_status", status)
            invalid_dimensions = await client.post(
                endpoint,
                json={"staff_rois": {"工位": [10, 10, 50, 50]}},
            )
            assert invalid_dimensions.status_code == 409, status

        set_capture_dimensions(service, camera_id)
        invalid_coordinates = [
            [True, 10, 50, 50],
            ["10", 10, 50, 50],
            [[0, 0], [10**400, 0], [0, 50]],
        ]
        for coordinates in invalid_coordinates:
            invalid_number = await client.post(
                endpoint,
                json={"staff_rois": {"数值错误": coordinates}},
            )
            assert invalid_number.status_code == 400, coordinates

        out_of_bounds = await client.post(
            endpoint,
            json={"staff_rois": {"越界工位": [[0, 0], [201, 0], [0, 50]]}},
        )
        assert out_of_bounds.status_code == 400
        assert "越界工位" in out_of_bounds.json()["detail"]
        assert "画面范围" in out_of_bounds.json()["detail"]

        too_small = await client.post(
            endpoint,
            json={"staff_rois": {"小工位": [[0, 0], [5, 0], [0, 5]]}},
        )
        assert too_small.status_code == 400
        assert "小工位" in too_small.json()["detail"]
        assert "面积" in too_small.json()["detail"]

        too_few_points = await client.post(
            endpoint,
            json={"staff_rois": {"少点工位": [[0, 0], [20, 0]]}},
        )
        assert too_few_points.status_code == 400
        assert "少点工位" in too_few_points.json()["detail"]

        rounded_duplicate = await client.post(
            endpoint,
            json={
                "staff_rois": {
                    "舍入重复": [[0, 0], [50, 0], [50.004, 0.004], [0, 50]]
                }
            },
        )
        assert rounded_duplicate.status_code == 400
        assert "重复" in rounded_duplicate.json()["detail"]


# 功能：验证 `test_legacy_config_migrates_camera_and_roi_aliases` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`staff_dir.mkdir`、`(staff_dir /
#          'stream_staff_rois.json').write_text`、`json.dumps`、`make_service`、`main.create_app`、`httpx.ASGITransport`、`httpx.AsyncClient`、`(await
#          client.get('/api/cameras')).json`、`client.get`、`(await client.get('/api/rois')).json` 等共 12 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能发起网络请求或发送外部消息。
@pytest.mark.asyncio
async def test_legacy_config_migrates_camera_and_roi_aliases(tmp_path):
    staff_dir = tmp_path / "staff_rois"
    staff_dir.mkdir()
    (staff_dir / "stream_staff_rois.json").write_text(
        json.dumps({"staff_rois": {"旧工位": [5, 6, 7, 8]}}),
        encoding="utf-8",
    )
    service, _runtime_manager = make_service(
        tmp_path,
        input_video="rtsp://legacy-camera/stream",
    )
    app = main.create_app(service.config_path, service=service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        cameras = (await client.get("/api/cameras")).json()["cameras"]
        assert cameras[0]["camera_id"] == "legacy-default"
        assert (await client.get("/api/rois")).json()["staff_rois"] == {
            "旧工位": [
                [5.0, 6.0],
                [7.0, 6.0],
                [7.0, 8.0],
                [5.0, 8.0],
            ]
        }
        paths = set(app.openapi()["paths"])
        assert "/video/{kind}" in paths
        assert "/video/{camera_id}/{kind}" in paths
