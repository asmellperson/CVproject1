import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.auth import get_current_user
from AiVision.core import db
from AiVision.features.registry import all_specs
from AiVision.departments.department_registry import DEPARTMENT_SPECS


departments_api = importlib.import_module("AiVision.api.routes.departments")
DepartmentService = importlib.import_module(
    "AiVision.departments.service"
).DepartmentService


def test_department_api_only_exposes_read_routes():
    routes = {
        (method, route.path)
        for route in departments_api.router.routes
        for method in route.methods or set()
    }

    assert routes == {
        ("GET", "/api/departments"),
        ("GET", "/api/departments/{name}/features"),
    }


def test_department_internal_management_methods_are_removed():
    for method_name in (
        "create_department",
        "update_department",
        "delete_department",
        "set_feature_departments",
        "remove_feature_department",
        "get_department",
        "ensure_seed_data",
    ):
        assert not hasattr(DepartmentService, method_name)


@pytest.fixture
def client_without_database(monkeypatch):
    def no_database(*args, **kwargs):
        raise AssertionError("department metadata must not access the database")

    for name in ("get_engine", "get_session", "session_scope"):
        monkeypatch.setattr(db, name, no_database)
    app = FastAPI()
    app.include_router(departments_api.router)
    app.include_router(importlib.import_module("AiVision.api.routes.features").router)
    app.dependency_overrides[get_current_user] = lambda: {
        "role": "viewer", "departments": ["research_institute"],
    }
    with TestClient(app) as client:
        yield client


def test_department_catalog_keeps_query_contract_without_database(client_without_database):
    response = client_without_database.get("/api/departments")
    assert response.status_code == 200
    assert response.json() == [
        {"name": department.name, "display_name": department.display_name}
        for department in DEPARTMENT_SPECS.values()
    ]


def test_feature_queries_return_platform_catalog_without_department_metadata(client_without_database):
    client = client_without_database
    response = client.get("/api/features")
    assert response.status_code == 200
    items = {item["name"]: item for item in response.json()["features"]}
    for name, spec in all_specs().items():
        assert "departments" not in items[name]
        response = client.get(f"/api/features/{name}")
        assert response.status_code == 200
        assert "departments" not in response.json()
    for department in DEPARTMENT_SPECS:
        response = client.get(f"/api/departments/{department}/features")
        assert response.status_code == 200
        assert response.json() == [
            {"name": spec.name, "display_name": spec.display_name}
            for spec in all_specs().values()
        ]
    assert client.get("/api/departments/unknown/features").status_code == 400


def test_department_catalog_requires_login(client_without_database):
    client_without_database.app.dependency_overrides.clear()
    assert client_without_database.get("/api/departments").status_code == 401
