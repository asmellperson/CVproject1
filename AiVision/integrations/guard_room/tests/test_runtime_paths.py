# 文件说明：包含运行时的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：实现 `_config` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：AppConfig；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AppConfig`、`VideoConfig`、`ModelConfig`、`RoomConfig`、`RuleConfig`、`ClassConfig`、`RuntimeConfig`、`WeChatConfig`。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
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


# 功能：验证 `test_runtime_paths_are_anchored_without_changing_persisted_config` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`(project_root / 'recordings').mkdir`、`(project_root / 'recordings' /
#          'example.mp4').touch`、`_config`、`resolve_runtime_paths`、`str`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
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


# 功能：验证 `test_runtime_paths_keep_urls_device_indexes_and_absolute_paths` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_config`、`str`、`resolve_runtime_paths`、`Path`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_runtime_paths_keep_urls_device_indexes_and_absolute_paths(tmp_path):
    config = _config()
    config.video.source = "rtsp://camera/live"
    config.video.source_cam1 = "0"
    config.video.output_dir = str(tmp_path / "absolute-output")

    runtime_config = resolve_runtime_paths(config, Path("/unused"))

    assert runtime_config.video.source == "rtsp://camera/live"
    assert runtime_config.video.source_cam1 == "0"
    assert runtime_config.video.output_dir == str(tmp_path / "absolute-output")


# 功能：验证 `test_default_sqlite_database_is_anchored_to_guard_room_module` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`monkeypatch.delenv`、`Path(db.__file__).resolve`、`Path`、`db._database_url`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
