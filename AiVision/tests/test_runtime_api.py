# 文件说明：包含运行时、接口访问的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.v2 import runtime as runtime_api


# 功能：验证 `test_health_exposes_model_worker_watchdog_state` 对应的运行时、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`SimpleNamespace`、`runtime_api.health`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_health_exposes_model_worker_watchdog_state():
    model_workers = [{
        "model_name": "yolo_human",
        "status": "running",
        "running": True,
    }]
    orchestrator = SimpleNamespace(runtime_status=lambda: {
        "started": True,
        "running_models": ["yolo_human"],
        "inference": {
            "workers": {
                "watchdog_running": True,
                "models": model_workers,
            }
        },
    })

    result = runtime_api.health(orchestrator)

    assert result["ok"] is True
    assert result["worker_watchdog_running"] is True
    assert result["model_workers"] == model_workers


# 功能：验证 `test_capability_routes_list_start_and_stop` 对应的运行时、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`SimpleNamespace`、`calls.append`、`runtime_api.list_capabilities`、`runtime_api.stop_capability`、`runtime_api.start_capability`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_capability_routes_list_start_and_stop():
    calls = []
    status = {
        "feature": "blocks",
        "display_name": "区域入侵检测",
        "enabled": True,
        "running": True,
        "state": "running",
    }
    orchestrator = SimpleNamespace(
        list_feature_runtime_statuses=lambda: [status],
        set_feature_enabled=lambda feature, enabled: calls.append((feature, enabled)) or {
            **status,
            "enabled": enabled,
            "running": enabled,
            "state": "running" if enabled else "stopped",
        },
    )
    assert runtime_api.list_capabilities(orchestrator) == {"items": [status]}
    assert runtime_api.stop_capability("blocks", orchestrator, {"role": "admin"})["state"] == "stopped"
    assert runtime_api.start_capability("blocks", orchestrator, {"role": "admin"})["state"] == "running"
    assert calls == [("blocks", False), ("blocks", True)]


# 功能：验证 `test_capability_route_maps_runtime_conflict` 对应的运行时、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`runtime_api.start_capability`、`SimpleNamespace`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_capability_route_maps_runtime_conflict():
    # 功能：实现 `fail` 对应的运行时、接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `_feature`（未显式标注）：`_feature` 对应的业务输入值
    #   - `_enabled`（未显式标注）：`_enabled` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`RuntimeError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def fail(_feature, _enabled):
        raise RuntimeError("依赖模型未启动")

    with pytest.raises(HTTPException) as raised:
        runtime_api.start_capability(
            "blocks",
            SimpleNamespace(set_feature_enabled=fail),
            {"role": "admin"},
        )

    assert raised.value.status_code == 409
    assert raised.value.detail == "依赖模型未启动"


# 功能：验证 `test_capability_write_routes_require_admin_dependency` 对应的运行时、接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`route.path.endswith`、`len`、`any`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_capability_write_routes_require_admin_dependency():
    write_routes = [
        route
        for route in runtime_api.router.routes
        if route.path.endswith(("/start", "/stop"))
    ]

    assert len(write_routes) == 2
    for route in write_routes:
        assert any(
            dependency.call is runtime_api.require_admin
            for dependency in route.dependant.dependencies
        )
