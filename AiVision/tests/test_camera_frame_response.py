# 文件说明：包含摄像头、视频帧的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import asyncio
import importlib
import sys

import anyio.to_thread
import httpx
import numpy as np
import pytest
from fastapi import FastAPI, HTTPException


sys.modules.pop("platform", None)
cameras_module = importlib.import_module("api.v2.cameras")
compat_module = importlib.import_module("api.compat")
get_camera_frame_jpg = cameras_module.get_camera_frame_jpg
compat_get_camera_frame_jpg = compat_module.compat_get_camera_frame_jpg


# 功能：定义 `FrameOrchestrator` 类，封装摄像头、视频帧相关的状态、约束与操作
# 参数：
#   - `frame`（未显式标注）：待处理的视频图像帧
# 返回：FrameOrchestrator；返回新建的 `FrameOrchestrator` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_camera_frame_response.py` 的 `test_frame_response_exposes_original_dimensions_when_preview_is_resized`
#         实例化本符号；`AiVision/tests/test_camera_frame_response.py` 的 `test_slow_frame_response_logs_lookup_and_encode_timings` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FrameOrchestrator:
    # 功能：初始化或配置 `__init__` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `frame`（未显式标注）：待处理的视频图像帧
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, frame):
        self.frame = frame

    # 功能：读取或查询 `get_camera_frame_info` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（未显式标注）：用于查询、分组或缓存的键
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值；默认值为 `None`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_camera_frame_info(self, key, feature=None):
        return self.frame, 123.0


# 功能：定义 `FrameCameraService` 类，封装摄像头、视频帧相关的状态、约束与操作
# 参数：无。
# 返回：FrameCameraService；返回新建的 `FrameCameraService` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_camera_frame_response.py` 的 `test_frame_response_exposes_original_dimensions_when_preview_is_resized`
#         实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FrameCameraService:
    # 功能：读取或查询 `get_camera` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（未显式标注）：用于查询、分组或缓存的键
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_camera(self, key):
        return {"shm_name": key, "department": "general_electric"}


# 功能：定义 `PermissionCameraService` 类，封装摄像头、视频帧相关的状态、约束与操作
# 参数：无。
# 返回：PermissionCameraService；返回新建的 `PermissionCameraService` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_camera_frame_response.py` 的 `test_v2_and_compat_camera_reads_are_scoped_by_department` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class PermissionCameraService:
    # 功能：初始化或配置 `__init__` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        self.cameras = [
            {
                "id": "camera_1", "camera_id": 1, "name": "本部门摄像头",
                "shm_name": "camera_1", "url": "rtsp://general/one",
                "enabled": True, "department": "general_electric", "functions": {},
            },
            {
                "id": "camera_2", "camera_id": 2, "name": "其他部门摄像头",
                "shm_name": "camera_2", "url": "rtsp://other/two",
                "enabled": True, "department": "electronics_electrician", "functions": {},
            },
            {
                "id": "camera_3", "camera_id": 3, "name": "未授权部门摄像头",
                "shm_name": "camera_3", "url": "rtsp://unauthorized/three",
                "enabled": True, "department": "electrical_components", "functions": {},
            },
            {
                "id": "camera_4", "camera_id": 4, "name": "历史通用电气摄像头",
                "shm_name": "camera_4", "url": "rtsp://legacy/general",
                "enabled": True, "department": None, "functions": {"detect_human": True},
            },
            {
                "id": "camera_5", "camera_id": 5, "name": "历史研究院摄像头",
                "shm_name": "camera_5", "url": "rtsp://legacy/research",
                "enabled": True, "department": "", "functions": {"detect_face": True},
            },
        ]

    # 功能：读取或查询 `list_cameras` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `department`（未显式标注）：业务部门名称或标识；默认值为 `None`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`list`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_cameras(self, department=None):
        if department is None:
            return list(self.cameras)
        return [
            item for item in self.cameras
            if department in cameras_module.camera_access_departments(item)
        ]

    # 功能：读取或查询 `get_camera` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（未显式标注）：用于查询、分组或缓存的键
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`str`、`dict`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_camera(self, key):
        key = str(key)
        for item in self.cameras:
            if key in {item["id"], item["shm_name"], item["name"], str(item["camera_id"])}:
                return dict(item)
        return None


# 功能：验证 `test_v2_and_compat_camera_reads_are_scoped_by_department` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`PermissionCameraService`、`FastAPI`、`app.include_router`、`monkeypatch.setattr`、`asyncio.run`、`scenario`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_v2_and_compat_camera_reads_are_scoped_by_department(monkeypatch):
    service = PermissionCameraService()
    app = FastAPI()
    app.include_router(cameras_module.router)
    app.include_router(compat_module.router)
    app.dependency_overrides[cameras_module.get_camera_service] = lambda: service

    # 功能：启动或执行 `inline_run_sync` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `func`（未显式标注）：`func` 对应的业务输入值
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**_kwargs`（未显式标注）：`_kwargs` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`func`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def inline_run_sync(func, *args, **_kwargs):
        return func(*args)

    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)

    # 功能：实现 `scenario` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`httpx.ASGITransport`、`httpx.AsyncClient`、`client.get`、`default_list.json`、`camera_by_id.json`、`camera_by_shm.json`、`all_cameras.json`、`filtered.json`、`admin_camera.json`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            def unauthenticated():
                raise HTTPException(status_code=401, detail="not authenticated")

            app.dependency_overrides[cameras_module.get_current_user] = unauthenticated
            for prefix in ("/api/v2/cameras", "/api/aivision/cameras"):
                assert (await client.get(prefix)).status_code == 401
                assert (await client.get(f"{prefix}/1")).status_code == 401

            viewer = {"role": "viewer", "department": "general_electric"}
            app.dependency_overrides[cameras_module.get_current_user] = lambda: viewer
            for prefix in ("/api/v2/cameras", "/api/aivision/cameras"):
                default_list = await client.get(prefix)
                assert default_list.status_code == 200
                assert [item["camera_id"] for item in default_list.json()] == [1, 4]
                assert "url" not in default_list.json()[0]
                assert (await client.get(
                    prefix,
                    params={"department": "electronics_electrician"},
                )).status_code == 403
                camera_by_id = await client.get(f"{prefix}/1")
                camera_by_shm = await client.get(f"{prefix}/camera_1")
                assert camera_by_id.status_code == 200
                assert camera_by_shm.status_code == 200
                assert "url" not in camera_by_id.json()
                assert "url" not in camera_by_shm.json()
                assert (await client.get(f"{prefix}/camera_4")).status_code == 200
                assert (await client.get(f"{prefix}/2")).status_code == 403
                assert (await client.get(f"{prefix}/camera_2")).status_code == 403
                assert (await client.get(f"{prefix}/camera_5")).status_code == 403

            multi_department_viewer = {
                "role": "viewer",
                "department": "general_electric",
                "departments": ["general_electric", "electronics_electrician"],
            }
            app.dependency_overrides[cameras_module.get_current_user] = lambda: multi_department_viewer
            for prefix in ("/api/v2/cameras", "/api/aivision/cameras"):
                authorized_cameras = await client.get(prefix)
                assert authorized_cameras.status_code == 200
                assert [item["camera_id"] for item in authorized_cameras.json()] == [1, 2, 4]
                assert all("url" not in item for item in authorized_cameras.json())
                second_department = await client.get(
                    prefix,
                    params={"department": "electronics_electrician"},
                )
                assert second_department.status_code == 200
                assert [item["camera_id"] for item in second_department.json()] == [2]
                assert (await client.get(f"{prefix}/camera_2")).status_code == 200
                assert (await client.get(
                    prefix,
                    params={"department": "electrical_components"},
                )).status_code == 403
                assert (await client.get(f"{prefix}/camera_3")).status_code == 403

            research_viewer = {"role": "viewer", "department": "research_institute"}
            app.dependency_overrides[cameras_module.get_current_user] = lambda: research_viewer
            for prefix in ("/api/v2/cameras", "/api/aivision/cameras"):
                research_cameras = await client.get(prefix)
                assert [item["camera_id"] for item in research_cameras.json()] == [5]
                assert (await client.get(f"{prefix}/camera_5")).status_code == 200
                assert (await client.get(f"{prefix}/camera_4")).status_code == 403

            admin = {"role": "admin", "department": None}
            app.dependency_overrides[cameras_module.get_current_user] = lambda: admin
            for prefix in ("/api/v2/cameras", "/api/aivision/cameras"):
                all_cameras = await client.get(prefix)
                assert [item["camera_id"] for item in all_cameras.json()] == [1, 2, 3, 4, 5]
                assert [item["url"] for item in all_cameras.json()] == [
                    "rtsp://general/one",
                    "rtsp://other/two",
                    "rtsp://unauthorized/three",
                    "rtsp://legacy/general",
                    "rtsp://legacy/research",
                ]
                filtered = await client.get(
                    prefix,
                    params={"department": "electronics_electrician"},
                )
                assert [item["camera_id"] for item in filtered.json()] == [2]
                admin_camera = await client.get(f"{prefix}/camera_2")
                assert admin_camera.status_code == 200
                assert admin_camera.json()["url"] == "rtsp://other/two"

    asyncio.run(scenario())


# 功能：验证 `test_frame_response_exposes_original_dimensions_when_preview_is_resized` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `handler`（未显式标注）：负责处理事件或结果的回调函数
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`np.zeros`、`handler`、`FrameCameraService`、`FrameOrchestrator`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    "handler",
    [get_camera_frame_jpg, compat_get_camera_frame_jpg],
)
def test_frame_response_exposes_original_dimensions_when_preview_is_resized(handler):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

    response = handler(
        key="camera-1",
        feature="detect_human",
        quality=72,
        max_width=960,
        max_height=None,
        user={"role": "viewer", "department": "general_electric"},
        camera_service=FrameCameraService(),
        orchestrator=FrameOrchestrator(frame),
    )

    assert response.headers["x-frame-width"] == "1920"
    assert response.headers["x-frame-height"] == "1080"


# 功能：验证 `test_slow_frame_response_logs_lookup_and_encode_timings` 对应的摄像头、视频帧逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`np.zeros`、`iter`、`monkeypatch.setattr`、`next`、`cameras_module.build_camera_frame_response`、`FrameOrchestrator`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_slow_frame_response_logs_lookup_and_encode_timings(monkeypatch):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    warnings: list[str] = []
    monotonic_values = iter([0.0, 0.2, 0.2, 1.5, 1.5])

    monkeypatch.setattr(cameras_module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(cameras_module, "encode_frame_to_jpeg", lambda *args, **kwargs: b"jpeg")
    monkeypatch.setattr(cameras_module.logger, "warning", warnings.append)
    monkeypatch.setattr(cameras_module.settings.runtime, "slow_frame_log_seconds", 1.0)

    response = cameras_module.build_camera_frame_response(
        key="camera-1",
        feature="detect_human",
        quality=72,
        max_width=960,
        max_height=None,
        orchestrator=FrameOrchestrator(frame),
    )

    assert response.body == b"jpeg"
    assert len(warnings) == 1
    assert "key=camera-1" in warnings[0]
    assert "lookup=0.200s" in warnings[0]
    assert "encode=1.300s" in warnings[0]
    assert "total=1.500s" in warnings[0]
