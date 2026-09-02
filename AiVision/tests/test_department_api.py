import importlib
import sys


sys.modules.pop("platform", None)
departments_api = importlib.import_module("api.departments")
DepartmentService = importlib.import_module(
    "platform.department.service"
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


def test_department_internal_management_methods_remain_available():
    for method_name in (
        "create_department",
        "update_department",
        "delete_department",
        "set_feature_departments",
        "remove_feature_department",
    ):
        assert callable(getattr(DepartmentService, method_name))
