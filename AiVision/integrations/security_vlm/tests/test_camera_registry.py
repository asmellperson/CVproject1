# 文件说明：包含摄像头、资源注册的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import json
import multiprocessing
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

try:
    import camera_registry
except ModuleNotFoundError:
    camera_registry = None


# 功能：创建或构建 `_process_create_cameras` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `registry_path`（未显式标注）：`registry_path` 对应的业务输入值
#   - `start_event`（未显式标注）：`start_event` 对应的业务输入值
#   - `results`（未显式标注）：`results` 对应的业务输入值
#   - `prefix`（未显式标注）：`prefix` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`camera_registry.CameraRegistry`、`start_event.wait`、`range`、`registry.create`、`prefix.lower`、`results.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _process_create_cameras(registry_path, start_event, results, prefix):
    registry = camera_registry.CameraRegistry(registry_path)
    original_read = registry._read_unlocked

    # 功能：读取或查询 `slow_read` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`original_read`、`time.sleep`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def slow_read():
        payload = original_read()
        time.sleep(0.1)
        return payload

    registry._read_unlocked = slow_read
    start_event.wait()
    for index in range(3):
        try:
            registry.create(
                f"{prefix} {index}",
                f"rtsp://{prefix.lower()}-{index}/stream",
            )
        except ValueError:
            results.put("full")
        else:
            results.put("created")


# 功能：验证 `test_camera_registry_module_exists` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_registry_module_exists():
    assert camera_registry is not None, "camera_registry module is required"


# 功能：验证 `test_create_read_and_redact_camera` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`camera_registry.CameraRegistry`、`registry.create`、`registry.get`、`registry.public`、`json.dumps`、`pytest.mark.skipif`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_create_read_and_redact_camera(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "config" / "cameras.json")

    created = registry.create(
        "安检工位一号",
        "rtsp://admin:secret@172.16.0.10:554/streaming/channels/101",
    )

    assert created["camera_id"]
    assert registry.get(created["camera_id"])["name"] == "安检工位一号"
    public = registry.public(created)
    assert public["rtsp_url"] == "rtsp://***:***@172.16.0.10:554/streaming/channels/101"
    assert public["has_rtsp_url"] is True
    assert "secret" not in json.dumps(public, ensure_ascii=False)


# 功能：验证 `test_rejects_empty_duplicate_names_and_non_rtsp_urls` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`camera_registry.CameraRegistry`、`registry.create`、`pytest.raises`、`pytest.mark.skipif`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_rejects_empty_duplicate_names_and_non_rtsp_urls(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "cameras.json")
    registry.create("Camera A", "rtsp://camera-a/stream")

    with pytest.raises(ValueError, match="名称"):
        registry.create("  ", "rtsp://camera-b/stream")
    with pytest.raises(ValueError, match="已存在"):
        registry.create("camera a", "rtsp://camera-b/stream")
    with pytest.raises(ValueError, match="RTSP"):
        registry.create("Camera B", "http://camera-b/stream")


# 功能：验证 `test_update_blank_url_preserves_secret_and_delete_returns_record` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`camera_registry.CameraRegistry`、`registry.create`、`registry.update`、`registry.delete`、`registry.get`、`pytest.mark.skipif`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_update_blank_url_preserves_secret_and_delete_returns_record(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "cameras.json")
    created = registry.create("Camera A", "rtsps://user:pass@camera-a/stream")

    updated = registry.update(
        created["camera_id"],
        name="Camera A East",
        rtsp_url="",
    )

    assert updated["name"] == "Camera A East"
    assert updated["rtsp_url"] == "rtsps://user:pass@camera-a/stream"
    assert registry.delete(created["camera_id"])["camera_id"] == created["camera_id"]
    assert registry.get(created["camera_id"]) is None


# 功能：验证 `test_concurrent_creates_keep_registry_json_valid` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`camera_registry.CameraRegistry`、`ThreadPoolExecutor`、`list`、`executor.map`、`range`、`json.loads`、`registry_path.read_text`、`len`、`registry_path.stat`、`pytest.mark.skipif`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_concurrent_creates_keep_registry_json_valid(tmp_path):
    registry_path = tmp_path / "cameras.json"
    registry = camera_registry.CameraRegistry(registry_path)

    # 功能：创建或构建 `create` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `index`（未显式标注）：`index` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`registry.create`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def create(index):
        return registry.create(f"Camera {index}", f"rtsp://camera-{index}/stream")

    with ThreadPoolExecutor(max_workers=8) as executor:
        created = list(executor.map(create, range(4)))

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["department"] == "general_electric"
    assert len(payload["cameras"]) == 4
    assert len({item["camera_id"] for item in created}) == 4
    assert registry_path.stat().st_mode & 0o777 == 0o600


# 功能：验证 `test_two_registry_instances_do_not_lose_concurrent_creates` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`camera_registry.CameraRegistry`、`ThreadPoolExecutor`、`list`、`executor.map`、`zip`、`sum`、`len`、`camera_registry.CameraRegistry(registry_path).list`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_two_registry_instances_do_not_lose_concurrent_creates(tmp_path):
    registry_path = tmp_path / "cameras.json"
    registries = [
        camera_registry.CameraRegistry(registry_path),
        camera_registry.CameraRegistry(registry_path),
    ]
    for registry in registries:
        original_read = registry._read_unlocked

        def slow_read(original_read=original_read):
            payload = original_read()
            time.sleep(0.05)
            return payload

        registry._read_unlocked = slow_read

    # 功能：创建或构建 `create_pair` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `item`（未显式标注）：`item` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`registry.create`、`prefix.lower`、`range`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def create_pair(item):
        registry, prefix = item
        return [
            registry.create(
                f"{prefix} {index}",
                f"rtsp://{prefix.lower()}-{index}/stream",
            )
            for index in range(2)
        ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                create_pair,
                zip(registries, ("InstanceA", "InstanceB")),
            )
        )

    assert sum(len(items) for items in results) == 4
    assert len(camera_registry.CameraRegistry(registry_path).list()) == 4


# 功能：验证 `test_two_processes_share_capacity_without_lost_creates` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`multiprocessing.get_context`、`context.Event`、`context.Queue`、`context.Process`、`process.start`、`start_event.set`、`results.get`、`range`、`process.join`、`outcomes.count`
#          等共 13 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_two_processes_share_capacity_without_lost_creates(tmp_path):
    registry_path = tmp_path / "cameras.json"
    context = multiprocessing.get_context("fork")
    start_event = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_process_create_cameras,
            args=(registry_path, start_event, results, prefix),
        )
        for prefix in ("ProcessA", "ProcessB")
    ]
    for process in processes:
        process.start()
    start_event.set()
    outcomes = [results.get(timeout=5) for _index in range(6)]
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0

    assert outcomes.count("created") == 4
    assert outcomes.count("full") == 2
    assert len(camera_registry.CameraRegistry(registry_path).list()) == 4


# 功能：验证 `test_registry_rejects_more_than_four_cameras` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`camera_registry.CameraRegistry`、`range`、`registry.create`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_registry_rejects_more_than_four_cameras(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "cameras.json")
    for index in range(4):
        registry.create(f"Camera {index}", f"rtsp://camera-{index}/stream")

    with pytest.raises(ValueError, match="4"):
        registry.create("Camera 5", "rtsp://camera-5/stream")


# 功能：验证 `test_registry_persists_department_and_rejects_mismatch` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`camera_registry.CameraRegistry`、`registry.create`、`json.loads`、`registry_path.read_text`、`pytest.raises`、`mismatched.list`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_registry_persists_department_and_rejects_mismatch(tmp_path):
    registry_path = tmp_path / "cameras.json"
    registry = camera_registry.CameraRegistry(
        registry_path,
        department="electrical_components",
    )
    registry.create("Camera A", "rtsp://camera-a/stream")

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["department"] == "electrical_components"

    mismatched = camera_registry.CameraRegistry(
        registry_path,
        department="precious_metal_recycling",
    )
    with pytest.raises(RuntimeError, match="事业部"):
        mismatched.list()


# 功能：验证 `test_registry_rejects_v1_file_even_for_default_department` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`registry_path.write_text`、`json.dumps`、`pytest.raises`、`camera_registry.CameraRegistry(registry_path).list`、`camera_registry.CameraRegistry`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_registry_rejects_v1_file_even_for_default_department(tmp_path):
    registry_path = tmp_path / "cameras.json"
    registry_path.write_text(
        json.dumps({"version": 1, "cameras": []}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="格式"):
        camera_registry.CameraRegistry(registry_path).list()


# 功能：验证 `test_registry_rejects_malformed_camera_records` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`registry_path.write_text`、`json.dumps`、`pytest.raises`、`camera_registry.CameraRegistry(registry_path).list`、`camera_registry.CameraRegistry`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_registry_rejects_malformed_camera_records(tmp_path):
    registry_path = tmp_path / "cameras.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": 2,
                "department": "general_electric",
                "cameras": [{"broken": True}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="格式"):
        camera_registry.CameraRegistry(registry_path).list()


# 功能：验证 `test_registry_rejects_unsafe_persisted_camera_ids` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
#   - `camera_id`（未显式标注）：摄像头唯一标识
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`registry_path.write_text`、`json.dumps`、`pytest.raises`、`camera_registry.CameraRegistry(registry_path).list`、`camera_registry.CameraRegistry`、`pytest.mark.parametrize`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
@pytest.mark.parametrize(
    "camera_id",
    [
        123,
        ".",
        "..",
        "../escape",
        "camera/id",
        "camera id",
        "_leading",
        "trailing_",
        "-leading",
        "trailing-",
        ".leading",
        "trailing.",
    ],
)
def test_registry_rejects_unsafe_persisted_camera_ids(tmp_path, camera_id):
    registry_path = tmp_path / "cameras.json"
    camera = {
        "camera_id": camera_id,
        "name": "Camera A",
        "rtsp_url": "rtsp://camera-a/stream",
        "created_at": 1.0,
        "updated_at": 1.0,
    }
    registry_path.write_text(
        json.dumps(
            {
                "version": 2,
                "department": "general_electric",
                "cameras": [camera],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="camera_id"):
        camera_registry.CameraRegistry(registry_path).list()


# 功能：验证 `test_public_camera_id_validator_accepts_safe_identifier` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`camera_registry.validate_camera_id`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_public_camera_id_validator_accepts_safe_identifier():
    assert camera_registry.validate_camera_id("A.camera_1-test") == "A.camera_1-test"


# 功能：验证 `test_legacy_migration_is_idempotent_and_copies_roi` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`camera_registry.CameraRegistry`、`staff_dir.mkdir`、`legacy_roi.write_text`、`json.dumps`、`registry.migrate_legacy`、`len`、`registry.list`、`json.loads`、`registry.path.read_text`、`migrated_roi.read_text`
#          等共 13 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_legacy_migration_is_idempotent_and_copies_roi(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "config" / "cameras.json")
    staff_dir = tmp_path / "staff_rois"
    staff_dir.mkdir()
    legacy_roi = staff_dir / "stream_staff_rois.json"
    legacy_roi.write_text(
        json.dumps({"staff_rois": {"security_staff_1": [1, 2, 3, 4]}}),
        encoding="utf-8",
    )
    cfg = {
        "data": {
            "input_video": "rtsp://legacy-camera/stream",
            "video_id": "stream",
        },
    }

    first = registry.migrate_legacy(cfg, staff_dir)
    second = registry.migrate_legacy(cfg, staff_dir)

    assert first["camera_id"] == "legacy-default"
    assert second is None
    assert len(registry.list()) == 1
    payload = json.loads(registry.path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["department"] == "general_electric"
    migrated_roi = staff_dir / "legacy-default_staff_rois.json"
    assert migrated_roi.read_text(encoding="utf-8") == legacy_roi.read_text(encoding="utf-8")
    assert legacy_roi.exists()


# 功能：验证 `test_migration_does_nothing_without_legacy_source` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`camera_registry.CameraRegistry`、`registry.migrate_legacy`、`registry.list`、`pytest.mark.skipif`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.skipif(camera_registry is None, reason="camera_registry is not implemented")
def test_migration_does_nothing_without_legacy_source(tmp_path):
    registry = camera_registry.CameraRegistry(tmp_path / "cameras.json")

    assert registry.migrate_legacy({"data": {"input_video": ""}}, tmp_path) is None
    assert registry.list() == []
