# 文件说明：包含运行时、接口访问的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from types import SimpleNamespace

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
