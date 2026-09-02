# 文件说明：包含运行时、接口访问的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from types import SimpleNamespace

from api import exception_alerts as exception_alerts_api
from api import runtime as runtime_api


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


def test_global_capability_routes_are_not_registered():
    assert all("/capabilities" not in route.path for route in runtime_api.router.routes)


def test_runtime_router_only_exposes_health_and_status():
    paths = {route.path for route in runtime_api.router.routes}

    assert paths == {"/api/runtime/health", "/api/runtime/status"}


def test_exception_alert_router_exposes_get_and_put():
    routes = {
        (route.path, method)
        for route in exception_alerts_api.router.routes
        for method in route.methods
    }

    assert routes == {
        ("/api/exception-alert", "GET"),
        ("/api/exception-alert", "PUT"),
    }


def test_exception_alert_handlers_keep_system_config_contract(monkeypatch):
    expected = {
        "wechat_enable": True,
        "wechat_user": "operator",
        "repeat_interval_minutes": 30,
    }
    saved = []
    monkeypatch.setattr(
        exception_alerts_api.system_config_service,
        "get_exception_alert",
        lambda: expected,
    )
    monkeypatch.setattr(
        exception_alerts_api.system_config_service,
        "save_exception_alert",
        lambda payload: saved.append(payload) or payload,
    )

    assert exception_alerts_api.get_exception_alert() == expected
    payload = exception_alerts_api.ExceptionAlertSettings(**expected)
    assert exception_alerts_api.update_exception_alert(payload, _user={}) == expected
    assert saved == [expected]
