"""告警领域迁移后的独立导入、单例身份和无外部副作用验证。"""
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from test_alarm_device_package import isolated_environment


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("entry", [
    "AiVision.alarms", "AiVision.alarms.devices", "AiVision.alarms.notifications",
    "AiVision.alarms.dispatcher", "AiVision.alarms.devices.horn",
    "AiVision.alarms.notifications.wechat", "AiVision.alarms.notifications.notification_image",
    "AiVision.api.routes.alarms", "AiVision.api.app", "AiVision.runtime.orchestrator",
    "AiVision.features._shared.consumer", "AiVision.features.logistics_channel.runtime",
    "AiVision.alarms.records.service",
    "AiVision.features.registry",
])
def test_fresh_alarm_imports_share_implementations_without_external_actions(entry, tmp_path):
    program = textwrap.dedent("""
        from contextlib import ExitStack
        import importlib
        import importlib.util
        from pathlib import Path
        import sys
        from unittest.mock import patch

        attempts = []
        def forbid(name):
            def called(*args, **kwargs):
                attempts.append(name)
                raise AssertionError("unexpected import side effect: " + name)
            return called

        with ExitStack() as stack:
            for target in (
                "sqlalchemy.create_engine", "sqlalchemy.engine.Engine.connect",
                "sqlite3.connect", "pymysql.connect",
                "requests.sessions.Session.request", "socket.create_connection",
                "socket.socket.connect", "socket.socket.connect_ex",
                "threading.Thread.start", "multiprocessing.process.BaseProcess.start", "subprocess.Popen",
            ):
                stack.enter_context(patch(target, side_effect=forbid(target)))

            entry = sys.argv[1]
            importlib.import_module(entry)
            if entry in ("AiVision.alarms", "AiVision.alarms.devices", "AiVision.alarms.notifications"):
                expected = {"AiVision", "AiVision.alarms", entry}
                assert {name for name in sys.modules if name == "AiVision" or name.startswith("AiVision.")} == expected

            from AiVision.alarms import dispatcher
            from AiVision.alarms.devices import horn, runtime_manager
            from AiVision.alarms.notifications import notification_image, wechat
            from AiVision.api.routes import alarms
            from AiVision.api import app
            from AiVision.core import db
            from AiVision.features._shared import consumer
            from AiVision.features.logistics_channel import runtime
            from AiVision.runtime import orchestrator
            from AiVision.alarms.records import service

            root = Path(sys.argv[2]) / "AiVision/alarms"
            for module, relative in (
                (dispatcher, "dispatcher.py"), (horn, "devices/horn.py"),
                (wechat, "notifications/wechat.py"), (notification_image, "notifications/notification_image.py"),
            ):
                assert Path(module.__file__) == root / relative
                assert sum(getattr(loaded, "__file__", None) == module.__file__
                           for loaded in list(sys.modules.values())) == 1
            assert runtime_manager.Horn is horn.Horn
            assert app.WeChatNotifier is orchestrator.WeChatNotifier is dispatcher.WeChatNotifier is wechat.WeChatNotifier
            assert dispatcher.issue_thumbnail_token is notification_image.issue_thumbnail_token
            assert alarms.verify_thumbnail_token is notification_image.verify_thumbnail_token
            assert alarms.thumbnail_response is notification_image.thumbnail_response
            assert consumer.AlarmRequest is runtime.AlarmRequest is dispatcher.AlarmRequest
            shared = dispatcher.alarm_dispatcher
            assert consumer.alarm_dispatcher is runtime.alarm_dispatcher is orchestrator.alarm_dispatcher is shared
            assert shared.wechat is shared.horn_runtime_manager is shared.violation_writer is None
            assert shared.evidence_recorder is None
            assert shared._wechat_thread is None and not shared._wechat_started
            assert shared._wechat_queue.empty() and shared._last_alarm == {}
            assert orchestrator.horn_runtime_manager is runtime_manager.horn_runtime_manager
            assert orchestrator.violation_writer is service.violation_writer
            assert not runtime_manager.horn_runtime_manager._active
            assert runtime_manager.horn_runtime_manager._threads == []
            assert db._engine is None and db._session_factory is None
            old_package = "AiVision.core.alarm"
            assert importlib.util.find_spec(old_package) is None
            assert not any(name == old_package or name.startswith(old_package + ".") for name in sys.modules)
            # 外部访问即使被实现捕获，也不能掩盖导入期间发生过调用。
            assert attempts == [], attempts
            print("alarm imports are inert and canonical")
    """)
    result = subprocess.run([sys.executable, "-c", program, entry, str(REPO_ROOT)],
                            cwd=tmp_path, env=isolated_environment(tmp_path),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "alarm imports are inert and canonical"
    assert "加载 features." not in result.stderr
    assert not (tmp_path / "auth.sqlite").exists()
