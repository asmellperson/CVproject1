from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from AiVision.api import models as models_api
from AiVision.api.deps import get_inference_runtime_manager
from auth.auth import require_admin


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(models_api.router)
    service = SimpleNamespace(
        list_models=lambda: [],
        update_model_path=lambda name, path: {
            "configuration_saved": True, "name": name, "path": path, "load_status": "loading",
        },
    )
    app.dependency_overrides[get_inference_runtime_manager] = lambda: service
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    with TestClient(app) as http:
        yield http, service, app


def test_routes_only_expose_fixed_list_and_local_path_update():
    assert {(route.path, tuple(sorted(route.methods))) for route in models_api.router.routes} == {
        ("/api/models", ("GET",)),
        ("/api/models/{model_name}/path", ("PATCH",)),
    }


def test_list_fixed_models_without_database(client):
    http, _, _ = client
    assert http.get("/api/models").json() == []


def test_path_save_and_list_use_local_yaml_and_real_runtime_state(client, tmp_path, monkeypatch):
    from AiVision.platform.inference import model_paths
    from AiVision.platform.inference.runtime_manager import InferenceRuntimeManager

    http, service, _ = client
    manager = InferenceRuntimeManager()
    service.list_models = manager.list_models
    service.update_model_path = manager.update_model_path
    config = tmp_path / "model_paths.yaml"
    weight = tmp_path / "model.pt"
    weight.write_bytes(b"test")
    monkeypatch.setattr(model_paths.settings.model_paths, "config_path", str(config))
    model_paths.clear_model_paths_cache()
    try:
        response = http.patch("/api/models/yolo_human/path", json={"path": str(weight)})
        assert response.status_code == 202
        assert response.json()["configuration_saved"] is True
        assert response.json()["load_status"] == "not_started"
        items = {item["name"]: item for item in http.get("/api/models").json()}
        assert set(items) == {"yolo_human", "yolo_phone", "yolo_face"}
        assert items["yolo_human"]["path"] == str(weight)
        assert items["yolo_human"]["runtime"]["running"] is False
        assert items["yolo_human"]["runtime"]["status"] == "not_started"
        assert "enable" not in items["yolo_human"]
        assert "database_path" not in items["yolo_human"]
        assert config.exists()
    finally:
        model_paths.clear_model_paths_cache()


def test_path_update_returns_saved_separately_from_loading(client):
    http, service, _ = client
    calls = []

    def update(name, path):
        calls.append((name, path))
        return {"configuration_saved": True, "name": name, "path": path, "load_status": "loading"}

    service.update_model_path = update
    response = http.patch("/api/models/yolo_human/path", json={"path": "/models/new.pt"})
    assert response.status_code == 202
    assert response.json()["configuration_saved"] is True
    assert response.json()["load_status"] == "loading"
    assert calls == [("yolo_human", "/models/new.pt")]


@pytest.mark.parametrize("field,value", [
    ("name", "new"), ("type", "other"), ("import_path", "custom.Worker"),
    ("description", "{}"), ("enable", False),
])
def test_path_endpoint_rejects_dynamic_model_fields(client, field, value):
    http, service, _ = client
    service.update_model_path = lambda *_: pytest.fail("invalid payload reached service")
    assert http.patch("/api/models/yolo_human/path", json={"path": "/model.pt", field: value}).status_code == 422


@pytest.mark.parametrize("error,status", [
    (KeyError("unknown"), 404), (ValueError("missing file"), 422),
    (RuntimeError("reload busy"), 409), (OSError("read-only filesystem"), 500),
])
def test_path_update_reports_errors(client, error, status):
    http, service, _ = client

    def fail(*args):
        raise error

    service.update_model_path = fail
    assert http.patch("/api/models/yolo_human/path", json={"path": "/model.pt"}).status_code == status


def test_viewer_cannot_save_model_paths(client):
    http, service, app = client

    def denied():
        raise HTTPException(status_code=403, detail="admin required")

    app.dependency_overrides[require_admin] = denied
    service.update_model_path = lambda *_: pytest.fail("viewer reached write service")
    assert http.patch("/api/models/yolo_human/path", json={"path": "/model.pt"}).status_code == 403


@pytest.mark.parametrize("method,path", [
    ("post", "/api/models"), ("delete", "/api/models/yolo_human"),
    ("patch", "/api/models/7"), ("get", "/api/models/7"),
])
def test_removed_crud_is_not_available(client, method, path):
    http, _, _ = client
    assert getattr(http, method)(path).status_code in (404, 405)
