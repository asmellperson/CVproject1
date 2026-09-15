"""事业部包独立导入、共享定义和延迟依赖验证；不连接数据库或外部服务。"""
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from test_alarm_device_package import isolated_environment


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("entry", [
    "AiVision.departments", "AiVision.departments.department_registry", "AiVision.departments.service",
    "auth.user_store", "auth.auth", "AiVision.features", "AiVision.cameras.config_manager",
    "AiVision.alarms.validation", "AiVision.alarms.records.orm", "AiVision.api.deps",
    "AiVision.api.routes.departments", "AiVision.api.routes.alarms", "AiVision.api.routes.logistics_channels",
    "AiVision.runtime.orchestrator",
])
def test_fresh_imports_share_department_definitions_and_preserve_lazy_dependencies(entry, tmp_path):
    program = textwrap.dedent("""
        from contextlib import ExitStack
        import importlib
        import importlib.util
        from pathlib import Path
        import sys
        from unittest.mock import patch

        attempts = []
        def forbid(target):
            def called(*args, **kwargs):
                attempts.append(target)
                raise AssertionError("unexpected import operation: " + target)
            return called

        with ExitStack() as stack:
            for target in (
                "sqlalchemy.create_engine", "sqlalchemy.engine.Engine.connect", "sqlite3.connect", "pymysql.connect",
                "requests.sessions.Session.request", "socket.create_connection", "socket.socket.connect",
                "socket.socket.connect_ex", "threading.Thread.start", "multiprocessing.process.BaseProcess.start",
                "subprocess.Popen", "cv2.VideoWriter", "cv2.imwrite", "cv2.imread",
                "apscheduler.schedulers.background.BackgroundScheduler.start",
            ):
                stack.enter_context(patch(target, side_effect=forbid(target)))
            entry = sys.argv[1]
            importlib.import_module(entry)
            if entry in ("AiVision.departments", "AiVision.departments.department_registry", "auth.user_store"):
                assert "AiVision.features" not in sys.modules
                assert "AiVision.core.db" not in sys.modules
                assert "AiVision.departments.service" not in sys.modules
            if entry in ("AiVision.alarms.validation", "AiVision.alarms.records.orm", "AiVision.api.deps"):
                assert "AiVision.features" not in sys.modules
                assert "AiVision.departments.service" not in sys.modules

            from auth import user_store
            from AiVision import departments, features
            from AiVision.departments import department_registry as registry, service
            from AiVision.cameras import config_manager
            from AiVision.alarms import validation
            from AiVision.api.routes import departments as departments_api
            from AiVision.api import deps
            from AiVision.core import db
            from AiVision.runtime import orchestrator

            root = Path(sys.argv[2]) / "AiVision/departments"
            for module, filename in (
                (departments, "__init__.py"), (registry, "department_registry.py"), (service, "service.py"),
            ):
                assert Path(module.__file__) == root / filename
                assert sum(getattr(loaded, "__file__", None) == module.__file__ for loaded in list(sys.modules.values())) == 1
            assert departments.DEPARTMENT_SPECS is service.DEPARTMENT_SPECS is user_store.DEPARTMENT_SPECS is registry.DEPARTMENT_SPECS
            assert departments.DepartmentSpec is service.DepartmentSpec is registry.DepartmentSpec
            assert departments.require_department is features.require_department is config_manager.require_department is validation.require_department is registry.require_department
            assert departments.__all__ == ["DEPARTMENT_SPECS", "DepartmentSpec", "require_department"]
            assert registry.DepartmentSpec.__module__ == "AiVision.departments.department_registry"
            assert service.DepartmentService.__module__ == "AiVision.departments.service"
            assert departments_api.DepartmentService is service.DepartmentService
            assert deps.get_department_service() is service.department_service
            assert service.all_specs is features.all_specs and service.get_spec is features.get_spec
            assert [spec.name for spec in service.department_service.list_departments()] == [
                "general_electric", "research_institute", "electronics_electrician",
                "electrical_components", "precious_metal_recycling", "haoda_company",
            ]
            assert user_store.ALLOWED_VIEWER_DEPARTMENTS == registry.DEPARTMENT_SPECS.keys()
            expected_membership = {
                "blocks": ("research_institute",),
                "detect_door": ("general_electric",),
                "detect_face": ("research_institute",),
                "detect_human": ("general_electric", "haoda_company"),
                "detect_logistics_single_person": (
                    "general_electric", "electronics_electrician", "electrical_components", "precious_metal_recycling",
                ),
                "detect_phone": ("general_electric", "research_institute"),
                "recognize_face": ("electronics_electrician",),
            }
            assert {name: spec.departments for name, spec in features.all_specs().items()} == expected_membership
            for department in expected_membership["detect_human"]:
                validation.validate_alarm_identity(5, "detect_human", department)
            for department in (None, "", "unknown", "research_institute"):
                try:
                    validation.validate_alarm_identity(5, "detect_human", department)
                except ValueError:
                    rejected = True
                else:
                    rejected = False
                assert rejected, department
            assert db._engine is None and db._session_factory is None
            assert "ai_department" not in db.Base.metadata.tables
            assert "ai_feature_department" not in db.Base.metadata.tables
            assert orchestrator.violation_writer._thread is orchestrator.violation_writer._scheduler is None
            assert orchestrator.alarm_evidence_recorder._writer_threads == []
            assert orchestrator.alarm_evidence_recorder._sampler_thread is None
            old_package = "AiVision.platform"
            assert importlib.util.find_spec(old_package) is None
            assert not any(name == old_package or name.startswith(old_package + ".") for name in sys.modules)
            assert attempts == [], attempts
            print("department definitions and lazy imports verified")
    """)
    result = subprocess.run(
        [sys.executable, "-c", program, entry, str(REPO_ROOT)], cwd=tmp_path,
        env=isolated_environment(tmp_path), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "department definitions and lazy imports verified"
    assert "加载 features." not in result.stderr
    assert not (tmp_path / "auth.sqlite").exists()
    assert list((tmp_path / "media").iterdir()) == []
