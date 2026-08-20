from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.v2 import runtime as runtime_api


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


def test_capability_route_maps_runtime_conflict():
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
