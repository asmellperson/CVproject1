"""告警记录与证据包的导入顺序、共享注册、延迟校验与存储路径验证。"""
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from test_alarm_device_package import isolated_environment


REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRIES = [
    "AiVision.alarms", "AiVision.alarms.records", "AiVision.alarms.evidence",
    "AiVision.alarms.types", "AiVision.alarms.validation", "AiVision.alarms.records.orm",
    "AiVision.alarms.records.cleanup", "AiVision.alarms.records.service",
    "AiVision.alarms.evidence.evidence_recorder", "AiVision.features", "AiVision.core.db",
    "AiVision.alarms.dispatcher", "AiVision.api.alarms", "AiVision.api.logistics_channels",
    "AiVision.platform.orchestrator",
]


@pytest.mark.parametrize("entry,relative_data", [(entry, False) for entry in ENTRIES] + [
    ("AiVision.alarms.records.service", True),
])
def test_record_imports_share_registration_without_running_workers_or_cleanup(entry, relative_data, tmp_path):
    program = textwrap.dedent("""
        from contextlib import ExitStack
        import importlib
        import importlib.util
        import os
        from pathlib import Path
        import sys
        from unittest.mock import patch

        attempts = []
        def forbidden(target):
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
                "AiVision.core.media_cleanup.MediaCleaner.cleanup",
            ):
                stack.enter_context(patch(target, side_effect=forbidden(target)))
            entry = sys.argv[1]
            importlib.import_module(entry)
            if entry in ("AiVision.alarms", "AiVision.alarms.records", "AiVision.alarms.evidence"):
                assert {name for name in sys.modules if name == "AiVision.alarms" or name.startswith("AiVision.alarms.")} == {"AiVision.alarms", entry}
            if entry in (
                "AiVision.alarms.types", "AiVision.alarms.validation", "AiVision.alarms.records.orm",
                "AiVision.alarms.records.cleanup", "AiVision.alarms.records.service",
            ):
                assert not any(name == "AiVision.features" or name.startswith("AiVision.features.") for name in sys.modules)

            from sqlalchemy import event
            from sqlalchemy.orm import configure_mappers
            from AiVision.alarms import dispatcher, types, validation
            from AiVision.alarms.records import cleanup, orm, service
            from AiVision.alarms.evidence import evidence_recorder
            from AiVision.api import alarms, logistics_channels
            from AiVision.core import db, media_cleanup, system_config, video_encoding
            from AiVision.features import all_specs
            from AiVision.platform import orchestrator

            root = Path(sys.argv[2]) / "AiVision/alarms"
            for module, relative in (
                (orm, "records/orm.py"), (service, "records/service.py"), (cleanup, "records/cleanup.py"),
                (types, "types.py"), (validation, "validation.py"),
                (evidence_recorder, "evidence/evidence_recorder.py"),
            ):
                assert Path(module.__file__) == root / relative
                assert sum(getattr(loaded, "__file__", None) == module.__file__ for loaded in list(sys.modules.values())) == 1
            assert orm.validate_alarm_identity is service.validate_alarm_identity is dispatcher.validate_alarm_identity is validation.validate_alarm_identity
            assert validation.VIOLATION_TYPE_META is types.VIOLATION_TYPE_META is alarms.VIOLATION_TYPE_META
            assert orm.AiAlarmEvent is cleanup.AiAlarmEvent is service.AiAlarmEvent is alarms.AiAlarmEvent is logistics_channels.AiAlarmEvent
            assert orm.AiAlarmEvent.__tablename__ == "ai_violation_image"
            assert db.Base.metadata.tables["ai_violation_image"] is orm.AiAlarmEvent.__table__
            configure_mappers()
            assert [m.class_ for m in db.Base.registry.mappers if m.local_table.name == "ai_violation_image"] == [orm.AiAlarmEvent]
            assert event.contains(orm.AiAlarmEvent, "before_insert", orm._validate_new_alarm)
            assert len(orm.AiAlarmEvent.__mapper__.dispatch.before_insert) == 1
            assert set(orm.AiAlarmEvent.__table__.columns.keys()) == {
                "id", "image_path", "video_path", "video_status", "violation_type", "feature_name",
                "department", "camera_no", "subject_type", "subject_id", "subject_name", "reason",
                "event_metadata", "create_time",
            }
            assert set(all_specs()) == {
                "blocks", "detect_door", "detect_phone", "detect_face", "detect_human",
                "detect_logistics_single_person", "recognize_face",
            }
            for department in ("general_electric", "haoda_company"):
                validation.validate_alarm_identity(5, "detect_human", department)
            assert db._engine is None and db._session_factory is None
            writer = service.violation_writer
            recorder = evidence_recorder.alarm_evidence_recorder
            assert orchestrator.violation_writer is writer
            assert orchestrator.alarm_evidence_recorder is recorder
            assert writer._thread is writer._scheduler is None
            assert writer._queue.empty() and writer._queue.unfinished_tasks == 0
            assert recorder._sampler_thread is recorder._status_callback is None
            assert recorder._writer_threads == [] and recorder._tasks == [] and recorder._buffers == {}
            assert recorder._write_queue.empty() and recorder._write_queue.unfinished_tasks == 0
            assert cleanup.ViolationMediaCleaner.__bases__ == (media_cleanup.MediaCleaner,)
            assert evidence_recorder.ensure_browser_compatible_mp4 is video_encoding.ensure_browser_compatible_mp4
            data_root = Path(os.environ["DATA_PATH"]).resolve()
            assert writer._data_path == writer._media_cleaner.data_path == data_root
            assert recorder.output_dir == data_root / "alarm_clips"
            assert data_root.is_dir() and list(data_root.iterdir()) == []
            explicit = evidence_recorder.AlarmEvidenceRecorder("explicit-output")
            assert explicit.output_dir == Path.cwd() / "explicit-output/alarm_clips"
            assert not explicit.output_dir.exists()
            old_package = "AiVision.platform.violation"
            assert importlib.util.find_spec(old_package) is None
            assert not any(name == old_package or name.startswith(old_package + ".") for name in sys.modules)
            assert attempts == [], attempts
            print("record registration and paths verified without external operations")
    """)
    env = isolated_environment(tmp_path)
    if relative_data:
        env["DATA_PATH"] = "relative-media"
    result = subprocess.run([sys.executable, "-c", program, entry, str(REPO_ROOT)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "record registration and paths verified without external operations"
    assert "加载 features." not in result.stderr
    assert not (tmp_path / "auth.sqlite").exists()
