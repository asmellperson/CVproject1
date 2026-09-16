import pytest
from AiVision.departments.department_registry import DEPARTMENT_SPECS
# 文件说明：包含运行时的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。



from AiVision.integrations.guard_room.src.db import configure_for_tests
from AiVision.integrations.guard_room.src.runtime_manager import GuardRoomRuntimeManager
from AiVision.integrations.guard_room.src.service import GuardRoomService
from AiVision.integrations.guard_room.src.types import AlarmEvent


# 功能：定义 `FakeRuntime` 类，封装运行时相关的状态、约束与操作
# 参数：
#   - `config`（未显式标注）：运行配置对象
#   - `state`（未显式标注）：`state` 对应的业务输入值
#   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
# 返回：FakeRuntime；返回新建的 `FakeRuntime` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeRuntime:
    # 功能：初始化或配置 `__init__` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `config`（未显式标注）：运行配置对象
    #   - `state`（未显式标注）：`state` 对应的业务输入值
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, config, state, **kwargs):
        self.config = config
        self.state = state
        self.kwargs = kwargs
        self.start_calls = 0
        self.stop_calls = 0

    # 功能：启动或执行 `start` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.state.mark_running`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def start(self):
        self.start_calls += 1
        self.state.mark_running(True)

    # 功能：停止并释放 `stop` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.state.mark_running`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def stop(self):
        self.stop_calls += 1
        self.state.mark_running(False)


# 功能：实现 `_service` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_runtime_manager.py` 的
#         `test_runtime_manager_starts_and_stops_one_site_without_affecting_another`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_runtime_manager.py` 的
#         `test_runtime_manager_shutdown_preserves_desired_enabled_state`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_runtime_manager.py` 的
#         `test_runtime_manager_enriches_status_frame_and_alarms_with_site_metadata` 调用本符号
#   - 内部调用：`configure_for_tests`、`GuardRoomService`、`service.ensure_schema`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _service(tmp_path):
    configure_for_tests(f"sqlite:///{tmp_path / 'guard_room_runtime.db'}")
    service = GuardRoomService()
    service.ensure_schema()
    return service


# 功能：验证 `test_runtime_manager_starts_and_stops_one_site_without_affecting_another` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_service`、`service.create_site`、`service.update_site_config`、`service.create_camera`、`GuardRoomRuntimeManager`、`manager.start`、`manager.get_status`、`manager.stop`、`service.get_site`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_runtime_manager_starts_and_stops_one_site_without_affecting_another(tmp_path):
    service = _service(tmp_path)
    site_a = service.create_site("一厂区南门保安室", department="general_electric")
    site_b = service.create_site("二厂区值班室", department="haoda_company")
    for site in (site_a, site_b):
        service.update_site_config(site["id"], {"wechat": {"enable": False}})
        service.create_camera(site["id"], name="左侧", rtsp_url=f"rtsp://{site['id']}-1")
        service.create_camera(site["id"], name="右侧", rtsp_url=f"rtsp://{site['id']}-2")

    manager = GuardRoomRuntimeManager(service, runtime_cls=FakeRuntime)

    started = manager.start(site_a["id"])
    assert started["running"] is True
    assert started["site_id"] == site_a["id"]
    assert manager.get_status(site_a["id"])["running"] is True
    assert manager.get_status(site_b["id"])["running"] is False

    stopped = manager.stop(site_a["id"])
    assert stopped["running"] is False
    assert manager.get_status(site_a["id"])["running"] is False
    assert service.get_site(site_a["id"])["enabled"] is False
    assert service.get_site(site_b["id"])["enabled"] is True


# 功能：验证 `test_runtime_manager_shutdown_preserves_desired_enabled_state` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_service`、`service.create_site`、`service.update_site_config`、`service.create_camera`、`GuardRoomRuntimeManager`、`manager.start`、`manager.stop_all`、`service.get_site`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_runtime_manager_shutdown_preserves_desired_enabled_state(tmp_path):
    service = _service(tmp_path)
    site = service.create_site("默认开启保安室", department="general_electric")
    service.update_site_config(site["id"], {"wechat": {"enable": False}})
    service.create_camera(site["id"], name="入口", rtsp_url="rtsp://camera-1")
    manager = GuardRoomRuntimeManager(service, runtime_cls=FakeRuntime)

    manager.start(site["id"])
    manager.stop_all()

    assert service.get_site(site["id"])["enabled"] is True


# 功能：验证 `test_runtime_manager_enriches_status_frame_and_alarms_with_site_metadata` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_service`、`service.create_site`、`service.update_site_config`、`service.create_camera`、`GuardRoomRuntimeManager`、`manager.start`、`manager.get_state`、`state.add_alarm`、`AlarmEvent`、`manager.get_status`
#          等共 13 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
def test_runtime_manager_enriches_status_frame_and_alarms_with_site_metadata(tmp_path, department):
    service = _service(tmp_path)
    site = service.create_site("仓库岗亭", department=department)
    service.update_site_config(site["id"], {"wechat": {"enable": False}})
    service.create_camera(site["id"], name="左侧", rtsp_url="rtsp://camera-1")
    service.create_camera(site["id"], name="右侧", rtsp_url="rtsp://camera-2")
    manager = GuardRoomRuntimeManager(service, runtime_cls=FakeRuntime)

    manager.start(site["id"])
    state = manager.get_state(site["id"])
    state.add_alarm(
        AlarmEvent(
            event_type="absent",
            timestamp_s=1.0,
            frame_index=3,
            track_id=None,
            confidence=0.9,
            reason="测试报警",
            camera_name="仓库岗亭",
        )
    )

    status = manager.get_status(site["id"])
    assert status["site_id"] == site["id"]
    assert status["site_name"] == "仓库岗亭"
    assert status["last_alarm"]["site_id"] == site["id"]
    assert manager.get_latest_frame(site["id"]).startswith(b"\xff\xd8")
    assert manager.get_alarms(site["id"], limit=10)[0]["site_name"] == "仓库岗亭"

    assert status["department"] == department
    assert status["last_alarm"]["department"] == department
    assert manager.get_alarms(site["id"])[0]["department"] == department
