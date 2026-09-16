from dataclasses import FrozenInstanceError, replace
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

from AiVision.core import db
import AiVision.features.registry as features
from AiVision.departments.department_registry import DEPARTMENT_SPECS, require_department
from AiVision.departments.service import DepartmentService
from AiVision.features.logistics_channel.constants import LOGISTICS_FEATURES
from auth.user_store import UserStore, UserValidationError


def test_department_registry_is_immutable_and_preserves_existing_catalog():
    assert [(spec.name, spec.display_name) for spec in DEPARTMENT_SPECS.values()] == [
        ("general_electric", "通用电气事业部"),
        ("electronics_electrician", "电子电工事业部"),
        ("electrical_components", "电气部件事业部"),
        ("research_institute", "福达新材院"),
        ("precious_metal_recycling", "伟达子公司"),
        ("haoda_company", "皓达子公司"),
        ("fulida_company", "福力达子公司"),
    ]
    with pytest.raises(TypeError):
        DEPARTMENT_SPECS["new"] = next(iter(DEPARTMENT_SPECS.values()))
    with pytest.raises(FrozenInstanceError):
        DEPARTMENT_SPECS["general_electric"].display_name = "changed"


def test_registry_can_be_imported_without_loading_features_or_database():
    environment = {key: value for key, value in os.environ.items() if not key.startswith("MYSQL_")}
    subprocess.run([
        sys.executable, "-B", "-c",
        "import sys; from AiVision.departments import DEPARTMENT_SPECS; "
        "assert DEPARTMENT_SPECS; assert 'AiVision.features' not in sys.modules; "
        "assert 'AiVision.core.db' not in sys.modules",
    ], env=environment, check=True)


@pytest.mark.parametrize("name", ["unknown", "all", "", " general_electric", "ge", "general-electric", "通用电气", "weida_company", "haoda", None, []])
def test_registry_rejects_unregistered_departments(name):
    with pytest.raises(ValueError, match="unknown department"):
        require_department(name)


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
def test_every_department_has_all_platform_features(department):
    service = DepartmentService()
    assert {item["name"] for item in service.get_features_by_department(department)} == set(features.all_specs())
    for spec in features.all_specs().values():
        assert "departments" not in spec.__dataclass_fields__
    assert LOGISTICS_FEATURES == {"detect_logistics_single_person"}


@pytest.mark.parametrize("department", [None, "", "all", "unknown"])
def test_feature_catalog_requires_registered_department(department):
    with pytest.raises(ValueError, match="unknown department"):
        DepartmentService().get_features_by_department(department)


def test_feature_registry_rejects_duplicate_names_without_changing_registered_specs():
    before = features.all_specs()
    spec = before["detect_phone"]
    with pytest.raises(ValueError, match="重复的 FeatureSpec.name"):
        features._build_registry((spec, replace(spec, display_name="duplicate")))
    assert features.all_specs() == before


def test_schema_verification_leaves_historical_department_tables_untouched(monkeypatch):
    from AiVision.runtime.bootstrap import bootstrap_database

    engine = create_engine("sqlite://")
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ai_department (name TEXT, display_name TEXT)"))
        connection.execute(text("CREATE TABLE ai_feature_department (feature_name TEXT, department TEXT)"))
        connection.execute(text("INSERT INTO ai_department VALUES ('legacy', '旧部门')"))
        connection.execute(text("INSERT INTO ai_feature_department VALUES ('detect_phone', 'legacy')"))
    try:
        bootstrap_database()
        assert "ai_department" not in db.Base.metadata.tables
        assert "ai_feature_department" not in db.Base.metadata.tables
        assert {"ai_department", "ai_feature_department"} <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.execute(text("SELECT * FROM ai_department")).all() == [("legacy", "旧部门")]
            assert connection.execute(text("SELECT * FROM ai_feature_department")).all() == [("detect_phone", "legacy")]
        assert "legacy" not in {item.name for item in DepartmentService().list_departments()}
    finally:
        engine.dispose()


def test_user_store_accepts_only_registered_departments(tmp_path):
    store = UserStore(database_path=tmp_path / "users.db")
    for index, name in enumerate(DEPARTMENT_SPECS):
        user = store.create_user(employee_id=str(index), name=name, role="viewer", departments=[name], password_hash="test-hash")
        assert user["departments"] == [name]
    with pytest.raises(UserValidationError, match="有效事业部"):
        store.create_user(employee_id="invalid", name="invalid", role="viewer", departments=["unknown"], password_hash="test-hash")
    with pytest.raises(UserValidationError, match="有效事业部"):
        store.update_user("0", actor_employee_id="admin", name="user", role="viewer", departments=["unknown"], enabled=True)
    assert store.get_user_record("0")["departments"] == ["general_electric"]
