# 文件说明：包含监控展示、接口访问的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import importlib


features_module = importlib.import_module("AiVision.api.features")
orchestrator_module = importlib.import_module("AiVision.platform.orchestrator")


# 功能：定义 `FakeCameraRuntimeManager` 类，封装监控展示、接口访问相关的状态、约束与操作
# 参数：
#   - `running`（未显式标注）：`running` 对应的业务输入值
# 返回：FakeCameraRuntimeManager；返回新建的 `FakeCameraRuntimeManager` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_monitor_status_api.py` 的 `build_orchestrator` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeCameraRuntimeManager:
    # 功能：初始化或配置 `__init__` 对应的监控展示、接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `running`（未显式标注）：`running` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, running):
        self._running = running

    # 功能：读取或查询 `list_running` 对应的监控展示、接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`list`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_running(self):
        return list(self._running)


# 功能：定义 `FakeConsumer` 类，封装监控展示、接口访问相关的状态、约束与操作
# 参数：
#   - `snapshot`（未显式标注）：`snapshot` 对应的业务输入值
# 返回：FakeConsumer；返回新建的 `FakeConsumer` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeConsumer:
    # 功能：初始化或配置 `__init__` 对应的监控展示、接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `snapshot`（未显式标注）：`snapshot` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, snapshot):
        self._snapshot = snapshot

    # 功能：读取或查询 `get_monitor_status` 对应的监控展示、接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_key`（未显式标注）：`camera_key` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`dict`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_monitor_status(self, camera_key):
        return dict(self._snapshot) if self._snapshot else None


# 功能：创建或构建 `build_orchestrator` 对应的监控展示、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `running`（未显式标注）：`running` 对应的业务输入值；默认值为 `('cam1',)`
#   - `snapshot`（未显式标注）：`snapshot` 对应的业务输入值；默认值为 `None`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_monitor_status_api.py` 的 `test_orchestrator_returns_fresh_typed_snapshot`
#         调用本符号；`AiVision/tests/test_logistics_monitor_status_api.py` 的 `test_orchestrator_returns_unknown_for_stale_snapshot` 调用本符号
#   - 内部调用：`object.__new__`、`FakeCameraRuntimeManager`、`FakeConsumer`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def build_orchestrator(*, running=("cam1",), snapshot=None):
    orchestrator = object.__new__(orchestrator_module.Orchestrator)
    orchestrator.camera_runtime_manager = FakeCameraRuntimeManager(running)
    orchestrator.consumers = {
        "detect_logistics_single_person": FakeConsumer(snapshot),
    }
    return orchestrator


# 功能：验证 `test_orchestrator_returns_fresh_typed_snapshot` 对应的监控展示、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`build_orchestrator`、`orchestrator.get_feature_monitor_status`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_orchestrator_returns_fresh_typed_snapshot(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 101.0)
    orchestrator = build_orchestrator(
        snapshot={
            "count": 1,
            "alarm": False,
            "reason": "normal",
            "duration_seconds": 12.5,
            "threshold_seconds": 30.0,
            "updated_at_s": 100.0,
        }
    )

    response = orchestrator.get_feature_monitor_status(
        "cam1",
        "detect_logistics_single_person",
    )

    assert response["camera_key"] == "cam1"
    assert response["online"] is True
    assert response["count"] == 1
    assert response["alarm"] is False
    assert response["reason"] == "normal"
    assert response["duration_seconds"] == 12.5
    assert response["threshold_seconds"] == 30.0
    assert response["updated_at"]


# 功能：验证 `test_orchestrator_returns_unknown_for_stale_snapshot` 对应的监控展示、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`build_orchestrator`、`orchestrator.get_feature_monitor_status`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_orchestrator_returns_unknown_for_stale_snapshot(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 120.0)
    orchestrator = build_orchestrator(
        running=(),
        snapshot={
            "count": 2,
            "alarm": True,
            "reason": "multiple",
            "duration_seconds": 18.0,
            "threshold_seconds": 10.0,
            "updated_at_s": 100.0,
        },
    )

    response = orchestrator.get_feature_monitor_status(
        "cam1",
        "detect_logistics_single_person",
    )

    assert response["online"] is False
    assert response["count"] is None
    assert response["alarm"] is False
    assert response["reason"] == "unknown"
    assert response["duration_seconds"] is None
    assert response["threshold_seconds"] is None


# 功能：验证 `test_feature_status_delegates_to_read_only_orchestrator` 对应的监控展示、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`features_module.get_feature_status`、`CameraConfigManager`、`StatusOrchestrator`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_feature_status_delegates_to_read_only_orchestrator():
    expected = {
        "camera_key": "cam1",
        "feature": "detect_logistics_single_person",
        "online": True,
        "count": 1,
        "alarm": False,
        "reason": "normal",
        "updated_at": "2026-08-06T10:40:46+08:00",
    }

    # 功能：定义 `StatusOrchestrator` 类，封装监控展示、接口访问相关的状态、约束与操作
    # 参数：无。
    # 返回：StatusOrchestrator；返回新建的 `StatusOrchestrator` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_monitor_status_api.py` 的 `test_compat_status_delegates_to_read_only_orchestrator`
    #         实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class StatusOrchestrator:
        # 功能：读取或查询 `get_feature_monitor_status` 对应的监控展示、接口访问逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `camera_key`（未显式标注）：`camera_key` 对应的业务输入值
        #   - `feature`（未显式标注）：`feature` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def get_feature_monitor_status(self, camera_key, feature):
            assert camera_key == "cam1"
            assert feature == "detect_logistics_single_person"
            return expected

    # 功能：定义 `CameraConfigManager` 类，封装监控展示、接口访问相关的状态、约束与操作
    # 参数：无。
    # 返回：CameraConfigManager；返回新建的 `CameraConfigManager` 实例。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class CameraConfigManager:
        # 功能：读取或查询 `get_camera` 对应的监控展示、接口访问逻辑；输入由参数提供，处理结果见返回值说明
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

    response = features_module.get_feature_status(
        key="cam1",
        feature="detect_logistics_single_person",
        user={"role": "viewer", "departments": ["general_electric"]},
        camera_config_manager=CameraConfigManager(),
        orchestrator=StatusOrchestrator(),
    )

    assert response == expected
