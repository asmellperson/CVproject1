from pathlib import Path

from src import db
from src.config import (
    AppConfig,
    ClassConfig,
    ModelConfig,
    RoomConfig,
    RuleConfig,
    RuntimeConfig,
    VideoConfig,
    WeChatConfig,
    resolve_runtime_paths,
)


def _config() -> AppConfig:
    return AppConfig(
        video=VideoConfig(
            source="recordings/example.mp4",
            output_dir="outputs",
        ),
        models=ModelConfig(
            detector_model="models/person_phone.pt",
            vehicle_detector_model="yolo11n.pt",
            uniform_cls_model="models/uniform.pt",
            pose_model_task="models/pose.engine",
            tracker="bytetrack.yaml",
        ),
        room=RoomConfig(),
        rules=RuleConfig(),
        classes=ClassConfig(),
        runtime=RuntimeConfig(),
        wechat=WeChatConfig(),
    )


def test_runtime_paths_are_anchored_without_changing_persisted_config(tmp_path):
    project_root = tmp_path / "guard_room"
    (project_root / "recordings").mkdir(parents=True)
    (project_root / "recordings" / "example.mp4").touch()
    config = _config()

    runtime_config = resolve_runtime_paths(config, project_root)

    assert runtime_config.video.output_dir == str(project_root / "outputs")
    assert runtime_config.video.source == str(project_root / "recordings" / "example.mp4")
    assert runtime_config.models.detector_model == str(project_root / "models" / "person_phone.pt")
    assert runtime_config.models.uniform_cls_model == str(project_root / "models" / "uniform.pt")
    assert runtime_config.models.pose_model_task == str(project_root / "models" / "pose.engine")
    assert runtime_config.models.vehicle_detector_model == "yolo11n.pt"
    assert runtime_config.models.tracker == "bytetrack.yaml"

    assert config.video.output_dir == "outputs"
    assert config.models.detector_model == "models/person_phone.pt"


def test_runtime_paths_keep_urls_device_indexes_and_absolute_paths(tmp_path):
    config = _config()
    config.video.source = "rtsp://camera/live"
    config.video.source_cam1 = "0"
    config.video.output_dir = str(tmp_path / "absolute-output")

    runtime_config = resolve_runtime_paths(config, Path("/unused"))

    assert runtime_config.video.source == "rtsp://camera/live"
    assert runtime_config.video.source_cam1 == "0"
    assert runtime_config.video.output_dir == str(tmp_path / "absolute-output")


def test_default_sqlite_database_is_anchored_to_guard_room_module(monkeypatch):
    monkeypatch.setattr(db, "_database_url_override", None)
    for name in (
        "GUARD_ROOM_DATABASE_URL",
        "MYSQL_DB_URL",
        "MYSQL_DB_USER",
        "MYSQL_DB_PASSWORD",
        "MYSQL_DB_NAME",
    ):
        monkeypatch.delenv(name, raising=False)

    module_root = Path(db.__file__).resolve().parents[1]
    assert db._database_url() == f"sqlite:///{module_root / 'guard_room.db'}"
