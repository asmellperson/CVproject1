"""人员库迁移的独立导入、延迟注册、CLI 配置定位及 unit 契约。"""
import configparser
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from test_alarm_device_package import isolated_environment


REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY = "AiVision.features.recognize_face.library"
NO_EXTERNAL = """
from contextlib import ExitStack
import importlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch

attempts = []
def forbid(target):
    def called(*args, **kwargs):
        attempts.append(target)
        raise AssertionError('unexpected external operation: ' + target)
    return called

class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'onnxruntime', 'insightface', 'ultralytics'}:
            return forbid(fullname)()

sys.meta_path.insert(0, NoModels())
stack = ExitStack()
for target in ('sqlalchemy.create_engine', 'sqlalchemy.engine.Engine.connect', 'sqlite3.connect',
               'pymysql.connect', 'requests.sessions.Session.request', 'socket.socket.connect',
               'socket.create_connection', 'socket.socket.connect_ex',
               'multiprocessing.process.BaseProcess.start', 'subprocess.Popen',
               'cv2.imread', 'cv2.imwrite', 'cv2.VideoWriter'):
    stack.enter_context(patch(target, side_effect=forbid(target)))
"""


def run_isolated(program, tmp_path, *args, env=None, cwd=None):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(program), *map(str, args)],
        env=env or isolated_environment(tmp_path), cwd=cwd or tmp_path,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "加载 features." not in result.stderr
    assert not (tmp_path / "auth.sqlite").exists()
    return result


@pytest.mark.parametrize("entry", [
    LIBRARY, *(f"{LIBRARY}.{name}" for name in ("constants", "orm", "index", "service", "sync", "embedding")),
    "AiVision.inference.model_registry", "AiVision.inference.workers.face_recognizer",
    "AiVision.inference.model_paths", "AiVision.features", "AiVision.features.recognize_face",
    "AiVision.api.routes.face_recognition", "AiVision.api.routes.models", "AiVision.runtime.orchestrator",
])
def test_import_orders_share_features_models_and_library_classes_without_running_business(entry, tmp_path):
    program = NO_EXTERNAL + """
stack.enter_context(patch('threading.Thread.start', side_effect=forbid('thread start')))
stack.enter_context(patch('dotenv.load_dotenv', side_effect=forbid('dotenv load')))
importlib.import_module(sys.argv[1])
from AiVision import features
specs = features.all_specs()
assert set(specs) == {'blocks', 'detect_door', 'detect_face', 'detect_human', 'detect_logistics_single_person', 'detect_phone', 'recognize_face'}
from AiVision.features import recognize_face
from AiVision.features.recognize_face import consumer, orm as recognition_orm, records, schema
from AiVision.features.recognize_face import library
from AiVision.features.recognize_face.library import constants, orm, index, service, sync, embedding
from AiVision.inference import model_registry, model_paths, insightface_detector
from AiVision.inference.workers import face_recognizer
from AiVision.core import db, system_config
from sqlalchemy.orm import configure_mappers
import gc
import pickle

root = Path(sys.argv[2]) / 'AiVision/features/recognize_face/library'
for module in (library, constants, orm, index, service, sync, embedding):
    assert Path(module.__file__).parent == root
    assert sum(getattr(item, '__file__', None) == module.__file__ for item in list(sys.modules.values())) == 1
assert library.HIKVISION_SOURCES == ('one', 'two')
assert service.HIKVISION_SOURCES is sync.HIKVISION_SOURCES is embedding.HIKVISION_SOURCES is library.HIKVISION_SOURCES
assert service.PersonSyncError is sync.PersonSyncError is embedding.PersonSyncError is library.PersonSyncError
assert recognition_orm.FacePerson is service.FacePerson is orm.FacePerson
assert recognition_orm.FaceEmbedding is service.FaceEmbedding is orm.FaceEmbedding
assert face_recognizer.FaceIndex is index.FaceIndex
assert embedding.photo_signature is service.photo_signature is index.photo_signature
assert model_registry.MODEL_SPECS['insightface'].worker_class is face_recognizer.FaceRecognizerWorker
assert constants.DETECTION_MODEL_FILE is insightface_detector.DETECTION_MODEL_FILE
assert specs['recognize_face'] is recognize_face.SPEC is features.get_spec('recognize_face')
assert recognize_face.FaceRecognitionConsumer is consumer.FaceRecognitionConsumer is specs['recognize_face'].consumer_cls
assert recognize_face.FaceRecognitionConfig is recognition_orm.FaceRecognitionConfig is specs['recognize_face'].orm_class
assert recognize_face.FaceRecognitionConfigSchema is schema.FaceRecognitionConfigSchema is specs['recognize_face'].config_schema
assert records.FaceRecognitionRecord is recognition_orm.FaceRecognitionRecord
configure_mappers()
for cls in (orm.FacePerson, orm.FaceEmbedding):
    assert [m.class_ for m in db.Base.registry.mappers if m.local_table.name == cls.__tablename__] == [cls]
    assert db.Base.metadata.tables[cls.__tablename__] is cls.__table__
for cls in (orm.FacePerson, orm.FaceEmbedding, index.FaceIndex, index.IndexedPerson, library.PersonSyncError):
    assert pickle.loads(pickle.dumps(cls)) is cls
assert not any(isinstance(item, index.FaceIndex) for item in gc.get_objects())
assert db._engine is None and db._session_factory is None
assert model_paths._PROJECT_ROOT == Path(sys.argv[2]) / 'AiVision'
old = "AiVision.platform"
assert importlib.util.find_spec(old) is None
assert not any(name == old or name.startswith(old + '.') for name in sys.modules)
assert attempts == [], attempts
"""
    run_isolated(program, tmp_path, entry, REPO_ROOT)


@pytest.mark.parametrize("entry", [
    "AiVision.features", "AiVision.features.recognize_face", LIBRARY,
    *(f"{LIBRARY}.{name}" for name in ("constants", "index", "sync", "embedding")),
])
def test_library_entry_import_does_not_require_settings_or_discover_features(entry, tmp_path):
    env = isolated_environment(tmp_path)
    for key in list(env):
        if key.startswith(("MYSQL_", "HIKVISION_")) or key == "DATA_PATH":
            env.pop(key)
    program = NO_EXTERNAL + """
stack.enter_context(patch('threading.Thread.start', side_effect=forbid('thread start')))
stack.enter_context(patch('dotenv.load_dotenv', side_effect=forbid('dotenv load')))
importlib.import_module(sys.argv[1])
from AiVision import features
assert features._REGISTRY == {} and not features._discovered
assert 'AiVision.core.settings' not in sys.modules
assert 'AiVision.core.db' not in sys.modules
assert 'AiVision.features.recognize_face.consumer' not in sys.modules
assert attempts == [], attempts
"""
    run_isolated(program, tmp_path, entry, env=env)


@pytest.mark.parametrize("entry", [f"{LIBRARY}.sync", f"{LIBRARY}.embedding"])
@pytest.mark.parametrize("working_directory", ["elsewhere", "other/deeper/path"])
def test_cli_loads_original_env_before_settings_from_other_working_directories(entry, working_directory, tmp_path):
    cwd = tmp_path / working_directory
    cwd.mkdir(parents=True)
    config = tmp_path / "temporary.env"
    config.write_text(
        "SQL_ENABLE=false\nMYSQL_DB_URL=127.0.0.1\nMYSQL_DB_PORT=1\nMYSQL_DB_USER=test-only\n"
        "MYSQL_DB_PASSWORD=unused-test-value\nMYSQL_DB_NAME=file-value\n"
        f"DATA_PATH={tmp_path / 'media'}\n"
    )
    env = isolated_environment(tmp_path)
    for key in list(env):
        if key.startswith(("MYSQL_", "HIKVISION_")) or key in ("DATA_PATH", "SQL_ENABLE"):
            env.pop(key)
    env["MYSQL_DB_NAME"] = "process-priority"
    program = NO_EXTERNAL + """
import runpy
import dotenv
real_load = dotenv.load_dotenv
calls = []
def load_temporary(dotenv_path=None, **kwargs):
    assert 'AiVision.core.settings' not in sys.modules
    assert Path(dotenv_path) == Path(sys.argv[2]) / 'AiVision/.env'
    assert kwargs == {'override': False}
    calls.append(dotenv_path)
    return real_load(sys.argv[3], **kwargs)
stack.enter_context(patch('dotenv.load_dotenv', side_effect=load_temporary))
stack.enter_context(patch('threading.Thread.start', side_effect=forbid('thread start')))
try:
    runpy.run_module(sys.argv[1], run_name='__main__')
except SystemExit as exc:
    assert exc.code == 1  # SQL disabled: verify initialization, never synchronize or generate.
else:
    raise AssertionError('CLI must return its disabled-SQL exit code')
assert len(calls) == 1
from AiVision.core.settings import settings
assert settings.db.name == 'process-priority' and settings.db.user == 'test-only'
assert settings.db.enable is False
assert Path(settings.storage.data_path) == Path(sys.argv[3]).parent / 'media'
from AiVision.features import all_specs
assert set(all_specs()) == {'blocks', 'detect_door', 'detect_face', 'detect_human', 'detect_logistics_single_person', 'detect_phone', 'recognize_face'}
assert attempts == [], attempts
"""
    run_isolated(program, tmp_path, entry, REPO_ROOT, config, env=env, cwd=cwd)


def test_concurrent_first_queries_and_public_exports_share_one_registration(tmp_path):
    program = NO_EXTERNAL + """
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from AiVision import features
from AiVision.features import recognize_face
barrier = Barrier(8)
def query(i):
    barrier.wait(timeout=10)
    if i % 4 == 0:
        return features.all_specs()['recognize_face']
    if i % 4 == 1:
        return features.get_spec('recognize_face')
    if i % 4 == 2:
        assert len(features.list_orm_classes()) == 7
        return features.get_spec('recognize_face')
    return recognize_face.SPEC
with ThreadPoolExecutor(max_workers=8) as executor:
    results = list(executor.map(query, range(8)))
assert all(item is recognize_face.SPEC for item in results)
assert len(features.all_specs()) == 7
assert attempts == [], attempts
"""
    run_isolated(program, tmp_path)


def test_units_preserve_deployment_paths_schedule_and_service_link():
    root = REPO_ROOT / "AiVision/features/recognize_face/library"
    unit = configparser.ConfigParser(interpolation=None)
    unit.read(root / "hikvision-face-library-sync.service")
    assert unit["Service"]["ExecStart"] == (
        "/root/miniconda3/envs/aivision/bin/python -m AiVision.features.recognize_face.library.sync"
    )
    assert dict(unit["Service"]) == {
        "type": "oneshot", "user": "root", "workingdirectory": "/srv/Fuda_CVPreject",
        "environment": "PYTHONUNBUFFERED=1", "execstart": unit["Service"]["ExecStart"],
        "timeoutstartsec": "8min", "timeoutstopsec": "30s", "killmode": "control-group",
        "remainafterexit": "no", "standardoutput": "journal", "standarderror": "journal",
        "syslogidentifier": "hikvision-face-library-sync",
    }
    timer = configparser.ConfigParser(interpolation=None)
    timer.read(root / "hikvision-face-library-sync.timer")
    assert dict(timer["Timer"]) == {
        "onbootsec": "2min", "onunitactivesec": "10min", "accuracysec": "1s",
        "unit": "hikvision-face-library-sync.service",
    }
    assert timer["Install"]["WantedBy"] == "timers.target"
