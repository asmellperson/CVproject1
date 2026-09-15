import logging
import os
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATA_PATH", "/tmp/aivision-test-data")
os.environ.setdefault("MYSQL_DB_URL", "127.0.0.1")
os.environ.setdefault("MYSQL_DB_USER", "test")
os.environ.setdefault("MYSQL_DB_PASSWORD", "test")
os.environ.setdefault("MYSQL_DB_NAME", "test")

from AiVision.core import cache as cache_module
from AiVision.core import db as db_module
from AiVision.runtime import process_cleanup
from AiVision.core import video_encoding
from AiVision.core.cache import ConfigCache
from AiVision.core.events import ConfigChangeEvent, ConfigEventBus
from AiVision.core.logger import _Logger


@pytest.mark.parametrize(
    ("debug_features", "expected_messages"),
    [
        ("", set()),
        ("phone", {"phone message"}),
        ("all", {"phone message", "blocks message"}),
    ],
)
def test_feature_debug_only_emits_whitelisted_messages(
    monkeypatch, caplog, debug_features, expected_messages
):
    monkeypatch.setenv("DEBUG_FEATURES", debug_features)
    test_logger = _Logger()

    with caplog.at_level(logging.DEBUG):
        test_logger.debug("direct debug")
        test_logger.set_debug_message("phone", "phone message")
        test_logger.set_debug_message("blocks", "blocks message")

    messages = {record.getMessage() for record in caplog.records}
    assert "direct debug" not in messages
    assert {message for message in messages if message.endswith("message")} == {
        f"[{feature}] {message}"
        for feature, message in (
            ("phone", "phone message"),
            ("blocks", "blocks message"),
        )
        if message in expected_messages
    }


class _FakeCameraSession:
    def __init__(self, camera):
        self.camera = camera
        self.get_calls = []
        self.closed = False

    def get(self, model, camera_id):
        self.get_calls.append((model, camera_id))
        return self.camera

    def close(self):
        self.closed = True


def test_refresh_camera_reenriches_and_removes_related_function_cache(monkeypatch):
    cache = ConfigCache()
    cache._camera_cache = {
        1: {"id": 1, "name": "old", "enable": True, "department": "old"},
        2: {"id": 2, "name": "other", "enable": True, "department": "other"},
    }
    cache._function_cache = {
        (1, "phone"): {
            "camera_id": 1,
            "enable": True,
            "name": "old",
            "shm_name": "old-shm",
            "camera_enable": True,
            "department": "old",
        },
        (1, "blocks"): {"camera_id": 1, "enable": False},
        (2, "phone"): {"camera_id": 2, "enable": True, "name": "other"},
    }
    updated_camera = {
        "id": 1,
        "name": "updated",
        "shm_name": "updated-shm",
        "enable": False,
        "department": "research",
    }
    update_session = _FakeCameraSession(updated_camera)
    delete_session = _FakeCameraSession(None)
    sessions = iter((update_session, delete_session))
    monkeypatch.setattr(cache_module, "get_session", lambda: next(sessions))
    monkeypatch.setattr(cache, "_orm_to_dict", lambda camera: dict(camera))

    cache.refresh_camera(1)

    for feature_name in ("phone", "blocks"):
        config = cache._function_cache[(1, feature_name)]
        assert config["name"] == "updated"
        assert config["shm_name"] == "updated-shm"
        assert config["camera_enable"] is False
        assert config["department"] == "research"
        assert "departments" not in config
    assert cache._function_cache[(2, "phone")]["name"] == "other"
    assert update_session.get_calls[0][1] == 1
    assert update_session.closed

    cache.refresh_camera(1)

    assert 1 not in cache._camera_cache
    assert all(camera_id != 1 for camera_id, _feature in cache._function_cache)
    assert (2, "phone") in cache._function_cache
    assert delete_session.closed


def test_event_bus_deduplicates_preserves_order_and_unsubscribes():
    bus = ConfigEventBus()
    calls = []

    def exact(_event):
        calls.append("exact")

    def prefix(_event):
        calls.append("prefix")

    def wildcard(_event):
        calls.append("wildcard")

    for _ in range(2):
        bus.subscribe("phone_enabled", exact)
        bus.subscribe_prefix("phone_", prefix)
        bus.subscribe_wildcard(wildcard)
        bus.subscribe_wildcard(exact)

    event = ConfigChangeEvent(change_type="phone_enabled", camera_id=1)
    bus.publish(event)
    assert calls == ["exact", "prefix", "wildcard"]

    bus.unsubscribe_prefix("phone_", prefix)
    bus.unsubscribe_prefix("phone_", prefix)
    bus.unsubscribe_wildcard(wildcard)
    bus.unsubscribe_wildcard(wildcard)
    calls.clear()
    bus.publish(event)
    assert calls == ["exact"]

    bus.unsubscribe("phone_enabled", exact)
    bus.unsubscribe_wildcard(exact)
    calls.clear()
    bus.publish(event)
    assert calls == []


def test_event_bus_listener_failure_keeps_traceback_and_continues(caplog):
    bus = ConfigEventBus()
    calls = []

    def failing(_event):
        raise RuntimeError("listener failed")

    bus.subscribe("camera_updated", failing)
    bus.subscribe("camera_updated", lambda _event: calls.append("continued"))

    with caplog.at_level(logging.ERROR):
        bus.publish(ConfigChangeEvent(change_type="camera_updated"))

    assert calls == ["continued"]
    record = next(record for record in caplog.records if "监听器执行失败" in record.getMessage())
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError


def test_cleanup_redacts_url_credentials_and_returns_match_count(monkeypatch, caplog):
    hit = process_cleanup._ProcessHit(
        pid=123,
        reason="ffmpeg-rtsp-rawvideo",
        cmdline=(
            "ffmpeg -i rtsp://camera-user:camera-password@host/live"
            "?token=secret-token&username=operator -f rawvideo"
        ),
    )
    signals = []
    monkeypatch.setattr(
        process_cleanup,
        "_find_residual_processes",
        lambda *_args: [hit],
    )
    monkeypatch.setattr(
        process_cleanup,
        "_safe_kill",
        lambda pid, sent_signal: signals.append((pid, sent_signal)),
    )
    monkeypatch.setattr(process_cleanup, "_is_alive", lambda _pid: False)

    with caplog.at_level(logging.WARNING):
        matched = process_cleanup.cleanup_aivision_residual_processes(
            {"camera-1"},
            {"rtsp://camera-user:camera-password@host/live"},
            set(),
            terminate_timeout=0.01,
        )

    output = "\n".join(record.getMessage() for record in caplog.records)
    assert matched == 1
    assert signals == [(123, signal.SIGTERM)]
    assert "camera-user" not in output
    assert "camera-password" not in output
    assert "secret-token" not in output
    assert "operator" not in output
    assert "rtsp://***:***@host/live?token=***&username=***" in output


def test_video_probe_requires_h264_and_yuv420p(monkeypatch, tmp_path):
    path = tmp_path / "alarm.mp4"
    path.write_bytes(b"original")
    commands = []

    def fake_run(command, *, timeout):
        commands.append((command, timeout))
        return SimpleNamespace(
            returncode=0,
            stdout="codec_name=h264\npix_fmt=yuv420p\n",
            stderr="",
        )

    monkeypatch.setattr(video_encoding, "_run", fake_run)

    assert video_encoding.ensure_browser_compatible_mp4(path) == path.resolve()
    assert len(commands) == 1
    assert "stream=codec_name,pix_fmt" in commands[0][0]


def test_non_yuv420p_video_is_transcoded_without_risking_original(monkeypatch, tmp_path):
    path = tmp_path / "alarm.mp4"
    path.write_bytes(b"original")
    commands = []

    def fake_run(command, *, timeout):
        commands.append(command)
        if command[0] == "ffprobe":
            return SimpleNamespace(
                returncode=0,
                stdout="codec_name=h264\npix_fmt=yuv444p\n",
                stderr="",
            )
        Path(command[-1]).write_bytes(b"converted")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_encoding, "_run", fake_run)

    video_encoding.ensure_browser_compatible_mp4(path)

    assert path.read_bytes() == b"converted"
    ffmpeg_command = commands[1]
    assert "-an" in ffmpeg_command
    assert ffmpeg_command[ffmpeg_command.index("-pix_fmt") + 1] == "yuv420p"


def test_failed_video_transcode_preserves_original(monkeypatch, tmp_path):
    path = tmp_path / "alarm.mp4"
    path.write_bytes(b"original")

    def fake_run(command, *, timeout):
        if command[0] == "ffprobe":
            return SimpleNamespace(
                returncode=0,
                stdout="codec_name=h264\npix_fmt=yuv444p\n",
                stderr="",
            )
        return SimpleNamespace(returncode=1, stdout="", stderr="encoding failed")

    monkeypatch.setattr(video_encoding, "_run", fake_run)

    with pytest.raises(video_encoding.VideoEncodingError, match="encoding failed"):
        video_encoding.ensure_browser_compatible_mp4(path)

    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    ("database_name", "charset", "message"),
    [
        ("invalid-name", "utf8mb4", "MYSQL_DB_NAME"),
        ("valid_name", "latin1", "MYSQL_DB_CHARSET"),
    ],
)
def test_database_creation_rejects_unsafe_identifiers(
    monkeypatch, database_name, charset, message
):
    monkeypatch.setattr(db_module.settings.db, "name", database_name)
    monkeypatch.setattr(db_module.settings.db, "charset", charset)
    monkeypatch.setattr(
        db_module,
        "create_engine",
        lambda *_args, **_kwargs: pytest.fail("invalid config reached create_engine"),
    )

    with pytest.raises(ValueError, match=message):
        db_module._ensure_database_exists()


def test_database_creation_uses_validated_matching_charset_and_collation(monkeypatch):
    calls = []

    class FakeResult:
        @staticmethod
        def fetchone():
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, parameters=None):
            calls.append((str(statement), parameters))
            return FakeResult()

        def commit(self):
            calls.append(("commit", None))

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            calls.append(("dispose", None))

    monkeypatch.setattr(db_module.settings.db, "name", "valid_name")
    monkeypatch.setattr(db_module.settings.db, "charset", "utf8mb4")
    monkeypatch.setattr(db_module, "create_engine", lambda *_args, **_kwargs: FakeEngine())

    db_module._ensure_database_exists()

    assert calls[0] == (
        "SHOW DATABASES LIKE :database_name",
        {"database_name": "valid_name"},
    )
    assert calls[1] == (
        "CREATE DATABASE `valid_name` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
        None,
    )
    assert calls[-2:] == [("commit", None), ("dispose", None)]
