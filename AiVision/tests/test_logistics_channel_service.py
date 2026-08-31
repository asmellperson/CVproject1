# 文件说明：包含业务服务的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from contextlib import contextmanager
from datetime import time, timezone
import importlib.util
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Query, sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from features import all_specs
from platform.alarm_device.orm import AiHornConfig
from platform.camera.orm import AiCameraConfig
from platform.camera.service import CameraService
from platform.logistics_channel.constants import (
    DEFAULT_STATUS_STALE_SECONDS,
    LOGISTICS_FEATURES,
    MAX_CAMERAS_PER_CHANNEL,
    require_logistics_feature,
)
from platform.logistics_channel.orm import LogisticsChannel, LogisticsChannelCamera
from platform.logistics_channel.service import LogisticsChannelService, MigrationSummary
from platform.logistics_channel.schema import (
    LogisticsChannelAlarm,
    LogisticsChannelConfigUpdate,
    LogisticsChannelDetailResponse,
    LogisticsChannelMemberCreate,
    LogisticsChannelMemberOrder,
    LogisticsChannelStatusResponse,
    LogisticsFeatureName,
)


# 功能：验证 `test_logistics_channel_service_module_exists` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`importlib.util.find_spec`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_logistics_channel_service_module_exists():
    assert importlib.util.find_spec("platform.logistics_channel.service") is not None


# 功能：验证 `test_logistics_channel_package_exports_service_without_hiding_state_exports` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`isinstance`、`callable`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_logistics_channel_package_exports_service_without_hiding_state_exports():
    import platform.logistics_channel as package

    assert package.LogisticsChannelService is LogisticsChannelService
    assert package.MigrationSummary is MigrationSummary
    assert isinstance(package.logistics_channel_service, LogisticsChannelService)
    assert callable(package.classify_channel)


# 功能：实现 `service_db` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`create_engine`、`sessionmaker`、`all_specs().values`、`all_specs`、`Base.metadata.create_all`、`monkeypatch.setattr`、`FakeCache`、`FakeEventBus`、`SimpleNamespace`、`LogisticsChannelService`
#          等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.fixture
def service_db(monkeypatch):
    import platform.camera.service as camera_service_module
    import platform.logistics_channel.service as channel_service_module

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # 功能：实现 `enable_sqlite_foreign_keys` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `dbapi_connection`（未显式标注）：`dbapi_connection` 对应的业务输入值
    #   - `_connection_record`（未显式标注）：`_connection_record` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`dbapi_connection.cursor`、`cursor.execute`、`cursor.close`、`event.listens_for`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    tables = [
        AiCameraConfig.__table__,
        AiHornConfig.__table__,
        *(spec.orm_class.__table__ for spec in all_specs().values()),
        LogisticsChannel.__table__,
        LogisticsChannelCamera.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)

    transaction_state = {"committed": True}

    # 功能：验证 `test_session_scope` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`factory`、`session.commit`、`session.rollback`、`session.close`。
    # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
    @contextmanager
    def test_session_scope():
        session = factory()
        transaction_state["committed"] = False
        try:
            yield session
            session.commit()
            transaction_state["committed"] = True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(channel_service_module, "session_scope", test_session_scope, raising=False)
    monkeypatch.setattr(channel_service_module, "get_session", factory, raising=False)
    monkeypatch.setattr(camera_service_module, "session_scope", test_session_scope)
    monkeypatch.setattr(camera_service_module, "get_session", factory)

    notifications = []

    # 功能：定义 `FakeCache` 类，封装业务服务相关的状态、约束与操作
    # 参数：无。
    # 返回：FakeCache；返回新建的 `FakeCache` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的 `service_db` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeCache:
        # 功能：实现 `reload` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`notifications.append`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def reload(self):
            assert transaction_state["committed"] is True
            notifications.append(("cache", "reload"))

        # 功能：实现 `refresh_camera` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `camera_id`（未显式标注）：摄像头唯一标识
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`notifications.append`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def refresh_camera(self, camera_id):
            assert transaction_state["committed"] is True
            notifications.append(("cache", "camera", camera_id))

        # 功能：实现 `refresh_function` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `camera_id`（未显式标注）：摄像头唯一标识
        #   - `feature_name`（未显式标注）：`feature_name` 对应的业务输入值
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`notifications.append`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def refresh_function(self, camera_id, feature_name):
            assert transaction_state["committed"] is True
            notifications.append(("cache", "feature", camera_id, feature_name))

    # 功能：定义 `FakeEventBus` 类，封装业务服务相关的状态、约束与操作
    # 参数：无。
    # 返回：FakeEventBus；返回新建的 `FakeEventBus` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的 `service_db` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeEventBus:
        # 功能：发送或分发 `publish` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `event`（未显式标注）：待处理的事件对象
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`notifications.append`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def publish(self, event):
            assert transaction_state["committed"] is True
            notifications.append(("event", event))

    fake_cache = FakeCache()
    fake_bus = FakeEventBus()
    monkeypatch.setattr(channel_service_module, "config_cache", fake_cache, raising=False)
    monkeypatch.setattr(channel_service_module, "config_event_bus", fake_bus, raising=False)
    monkeypatch.setattr(camera_service_module, "config_cache", fake_cache)
    monkeypatch.setattr(camera_service_module, "config_event_bus", fake_bus)

    yield SimpleNamespace(
        service=LogisticsChannelService(),
        camera_service=CameraService(),
        engine=engine,
        factory=factory,
        notifications=notifications,
    )
    engine.dispose()


# 功能：实现 `_seed_camera` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `name`（未显式标注）：业务对象名称
#   - `department`（未显式标注）：业务部门名称或标识；默认值为 `'general_electric'`
#   - `enabled_features`（未显式标注）：`enabled_features` 对应的业务输入值；默认值为 `()`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的 `test_camera_list_loads_feature_states_in_fixed_query_count`
#         调用本符号；`AiVision/tests/test_logistics_channel_service.py` 的
#         `test_add_existing_camera_enforces_nine_member_limit_and_rolls_back_tenth`
#         调用本符号；`AiVision/tests/test_logistics_channel_service.py` 的
#         `test_camera_membership_is_unique_within_feature_but_isolated_across_features`
#         调用本符号；`AiVision/tests/test_logistics_channel_service.py` 的 `test_feature_membership_events_always_include_camera_shm_name`
#         调用本符号；另有 12 处静态调用
#   - 内部调用：`service_db.factory.begin`、`AiCameraConfig`、`session.add`、`session.flush`、`all_specs().items`、`all_specs`、`spec.orm_class`。
# 副作用/注意事项：可能读取或修改数据库事务。
def _seed_camera(service_db, name, *, department="general_electric", enabled_features=()):
    with service_db.factory.begin() as session:
        camera = AiCameraConfig(
            name=name,
            url=f"rtsp://example/{name}",
            shm_name=f"shm_{name}",
            department=department,
            enable=True,
        )
        session.add(camera)
        session.flush()
        for feature_name, spec in all_specs().items():
            session.add(spec.orm_class(
                camera_id=camera.id,
                enable=feature_name in enabled_features,
            ))
        camera_id = camera.id
    return camera_id


# 功能：实现 `_events` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `change_type`（未显式标注）：`change_type` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的 `test_combined_channel_update_is_atomic_and_publishes_once`
#         调用本符号；`AiVision/tests/test_logistics_channel_service.py` 的 `test_feature_membership_events_always_include_camera_shm_name`
#         调用本符号；`AiVision/tests/test_logistics_channel_service.py` 的
#         `test_set_member_enabled_is_atomic_preserves_config_and_notifies_channel_once`
#         调用本符号；`AiVision/tests/test_logistics_channel_service.py` 的
#         `test_create_camera_and_bind_is_atomic_uses_feature_department_and_notifies_after_commit` 调用本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _events(service_db, change_type):
    return [
        item[1]
        for item in service_db.notifications
        if item[0] == "event" and item[1].change_type == change_type
    ]


# 功能：验证 `test_camera_list_loads_feature_states_in_fixed_query_count` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_seed_camera`、`event.listen`、`service_db.camera_service.list_cameras`、`event.remove`、`len`、`all_specs`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_list_loads_feature_states_in_fixed_query_count(service_db):
    first_id = _seed_camera(
        service_db,
        "camera-one",
        enabled_features=("detect_human",),
    )
    second_id = _seed_camera(
        service_db,
        "camera-two",
        enabled_features=("detect_phone",),
    )
    select_statements: list[str] = []

    # 功能：实现 `track_selects` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `_connection`（未显式标注）：`_connection` 对应的业务输入值
    #   - `_cursor`（未显式标注）：`_cursor` 对应的业务输入值
    #   - `statement`（未显式标注）：`statement` 对应的业务输入值
    #   - `_parameters`（未显式标注）：`_parameters` 对应的业务输入值
    #   - `_context`（未显式标注）：`_context` 对应的业务输入值
    #   - `_many`（未显式标注）：`_many` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`statement.lstrip().upper().startswith`、`statement.lstrip().upper`、`statement.lstrip`、`select_statements.append`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def track_selects(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(service_db.engine, "before_cursor_execute", track_selects)
    try:
        cameras = service_db.camera_service.list_cameras()
    finally:
        event.remove(service_db.engine, "before_cursor_execute", track_selects)

    cameras_by_id = {camera["camera_id"]: camera for camera in cameras}
    assert cameras_by_id[first_id]["functions"]["detect_human"] is True
    assert cameras_by_id[first_id]["functions"]["detect_phone"] is False
    assert cameras_by_id[second_id]["functions"]["detect_phone"] is True
    assert len(select_statements) == 1 + len(all_specs())


BASE_FEATURE = "detect_logistics_single_person"
EE_FEATURE = "detect_logistics_single_person_electronics_electrician"


# 功能：验证 `test_channel_crud_is_scoped_by_feature` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`pytest.raises`、`service.update_channel`、`service.update_config`、`time`、`service.get_channel`、`service.list_channels`、`service.delete_channel`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_channel_crud_is_scoped_by_feature(service_db):
    service = service_db.service
    created = service.create_channel(BASE_FEATURE, "收货通道")
    service.create_channel(EE_FEATURE, "收货通道")

    with pytest.raises(ValueError, match="已存在"):
        service.create_channel(BASE_FEATURE, "收货通道")

    updated = service.update_channel(
        BASE_FEATURE,
        created["id"],
        {"name": "卸货通道", "enabled": False, "sort_order": 7},
    )
    configured = service.update_config(
        BASE_FEATURE,
        created["id"],
        {
            "detection_start": time(7, 30),
            "detection_end": time(19, 30),
            "confidence_threshold": 0.42,
            "empty_grace_seconds": 4.0,
            "multi_grace_seconds": 3.0,
            "alarm_interval": 8.0,
            "alarm": {
                "sql_enable": True,
                "horn": {"enabled": False},
                "wechat": {"enabled": True, "user": "operator"},
            },
        },
    )

    assert updated["name"] == "卸货通道"
    assert updated["enabled"] is False
    assert updated["sort_order"] == 7
    assert configured["config"]["confidence_threshold"] == 0.42
    assert configured["config"]["empty_grace_seconds"] == 4.0
    assert configured["config"]["alarm"]["wechat"]["user"] == "operator"
    assert service.get_channel(BASE_FEATURE, created["id"])["id"] == created["id"]
    assert [item["name"] for item in service.list_channels(BASE_FEATURE)["items"]] == ["卸货通道"]
    assert service.delete_channel(BASE_FEATURE, created["id"]) is True
    assert service.get_channel(BASE_FEATURE, created["id"]) is None


# 功能：验证 `test_combined_channel_update_is_atomic_and_publishes_once` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`service_db.notifications.clear`、`monkeypatch.setattr`、`pytest.raises`、`service.update_channel_and_config`、`service.get_channel`、`_events`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_combined_channel_update_is_atomic_and_publishes_once(service_db, monkeypatch):
    service = service_db.service
    created = service.create_channel(BASE_FEATURE, "原名称")
    service_db.notifications.clear()

    original_apply_config = service._apply_config_values

    # 功能：实现 `fail_after_metadata` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `_channel`（未显式标注）：`_channel` 对应的业务输入值
    #   - `_values`（未显式标注）：`_values` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def fail_after_metadata(_channel, _values):
        raise ValueError("模拟配置更新失败")

    monkeypatch.setattr(service, "_apply_config_values", fail_after_metadata)
    with pytest.raises(ValueError, match="模拟配置更新失败"):
        service.update_channel_and_config(
            BASE_FEATURE,
            created["id"],
            {"name": "不应提交"},
            {"empty_grace_seconds": 9.0},
        )

    unchanged = service.get_channel(BASE_FEATURE, created["id"])
    assert unchanged["name"] == "原名称"
    assert unchanged["config"]["empty_grace_seconds"] == 2.0
    assert service_db.notifications == []

    monkeypatch.setattr(service, "_apply_config_values", original_apply_config)
    updated = service.update_channel_and_config(
        BASE_FEATURE,
        created["id"],
        {"name": "已提交"},
        {"empty_grace_seconds": 4.0},
    )
    assert updated["name"] == "已提交"
    assert updated["config"]["empty_grace_seconds"] == 4.0
    events = _events(service_db, "logistics_channel_updated")
    assert len(events) == 1


# 功能：验证 `test_every_feature_scoped_entry_rejects_unknown_feature` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `method`（未显式标注）：`method` 对应的业务输入值
#   - `args`（未显式标注）：`args` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`getattr(service_db.service, method)`、`getattr`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("list_channels", ()),
        ("get_channel", (1,)),
        ("create_channel", ("通道",)),
        ("update_channel", (1, {})),
        ("delete_channel", (1,)),
        ("update_config", (1, {})),
        ("add_existing_camera", (1, 1)),
        ("create_camera_and_bind", (1, {"name": "相机", "url": "rtsp://example"})),
        ("move_camera", (1, 1)),
        ("reorder_members", (1, [])),
        ("remove_camera", (1, 1)),
    ],
)
def test_every_feature_scoped_entry_rejects_unknown_feature(service_db, method, args):
    with pytest.raises(ValueError, match="不支持的物流检测功能"):
        getattr(service_db.service, method)("blocks", *args)


# 功能：验证 `test_add_existing_camera_enforces_nine_member_limit_and_rolls_back_tenth` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`_seed_camera`、`range`、`service.add_existing_camera`、`len`、`pytest.raises`、`service.get_channel`、`service_db.factory`、`session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_ids[9]).one`、`session.query(all_specs()[BASE_FEATURE].orm_class).filter_by`
#          等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_add_existing_camera_enforces_nine_member_limit_and_rolls_back_tenth(service_db):
    service = service_db.service
    channel = service.create_channel(BASE_FEATURE, "九路通道")
    camera_ids = [_seed_camera(service_db, f"camera-{index}") for index in range(10)]

    for camera_id in camera_ids[:9]:
        detail = service.add_existing_camera(BASE_FEATURE, channel["id"], camera_id)
        assert len(detail["members"]) <= MAX_CAMERAS_PER_CHANNEL

    with pytest.raises(ValueError, match="最多.*9.*路"):
        service.add_existing_camera(BASE_FEATURE, channel["id"], camera_ids[9])

    detail = service.get_channel(BASE_FEATURE, channel["id"])
    assert [member["camera_id"] for member in detail["members"]] == camera_ids[:9]
    with service_db.factory() as session:
        cfg = session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_ids[9]).one()
        assert cfg.enable is False


# 功能：验证 `test_camera_membership_is_unique_within_feature_but_isolated_across_features` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_seed_camera`、`service.create_channel`、`service.add_existing_camera`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_membership_is_unique_within_feature_but_isolated_across_features(service_db):
    service = service_db.service
    camera_id = _seed_camera(service_db, "shared-camera")
    first = service.create_channel(BASE_FEATURE, "一号")
    second = service.create_channel(BASE_FEATURE, "二号")
    other_feature = service.create_channel(EE_FEATURE, "一号")
    service.add_existing_camera(BASE_FEATURE, first["id"], camera_id)

    with pytest.raises(ValueError, match="已绑定"):
        service.add_existing_camera(BASE_FEATURE, second["id"], camera_id)

    detail = service.add_existing_camera(EE_FEATURE, other_feature["id"], camera_id)
    assert [member["camera_id"] for member in detail["members"]] == [camera_id]


# 功能：验证 `test_feature_membership_events_always_include_camera_shm_name` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_seed_camera`、`service.create_channel`、`service_db.notifications.clear`、`service.add_existing_camera`、`_events`、`service.move_camera`、`service.remove_camera`、`service.delete_channel`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_feature_membership_events_always_include_camera_shm_name(service_db):
    service = service_db.service
    camera_id = _seed_camera(service_db, "event-camera")
    source = service.create_channel(BASE_FEATURE, "事件来源")
    target = service.create_channel(BASE_FEATURE, "事件目标")

    service_db.notifications.clear()
    service.add_existing_camera(BASE_FEATURE, source["id"], camera_id)
    assert [event.camera_name for event in _events(service_db, f"{BASE_FEATURE}_enabled")] == [
        "shm_event-camera"
    ]

    service_db.notifications.clear()
    service.move_camera(BASE_FEATURE, camera_id, target["id"])
    assert [event.camera_name for event in _events(service_db, f"{BASE_FEATURE}_enabled")] == [
        "shm_event-camera"
    ]

    service_db.notifications.clear()
    assert service.remove_camera(BASE_FEATURE, target["id"], camera_id) is True
    assert [event.camera_name for event in _events(service_db, f"{BASE_FEATURE}_disabled")] == [
        "shm_event-camera"
    ]

    service.add_existing_camera(BASE_FEATURE, target["id"], camera_id)
    service_db.notifications.clear()
    assert service.delete_channel(BASE_FEATURE, target["id"]) is True
    assert [event.camera_name for event in _events(service_db, f"{BASE_FEATURE}_disabled")] == [
        "shm_event-camera"
    ]


# 功能：验证 `test_existing_member_writes_use_channels_then_cameras_lock_order` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_seed_camera`、`service.create_channel`、`monkeypatch.setattr`、`service.add_existing_camera`、`calls.clear`、`service.move_camera`、`tuple`、`sorted`、`service.remove_camera`、`service.reorder_members`
#          等共 11 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_existing_member_writes_use_channels_then_cameras_lock_order(service_db, monkeypatch):
    service = service_db.service
    camera_id = _seed_camera(service_db, "lock-order")
    source = service.create_channel(BASE_FEATURE, "锁来源")
    target = service.create_channel(BASE_FEATURE, "锁目标")
    calls = []
    original_lock_channels = service._lock_channels
    original_lock_cameras = service._lock_cameras

    # 功能：实现 `record_channels` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `channel_ids`（未显式标注）：`channel_ids` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`calls.append`、`tuple`、`sorted`、`original_lock_channels`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def record_channels(session, channel_ids):
        calls.append(("channels", tuple(sorted(channel_ids))))
        return original_lock_channels(session, channel_ids)

    # 功能：实现 `record_cameras` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `camera_ids`（未显式标注）：`camera_ids` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`calls.append`、`tuple`、`sorted`、`original_lock_cameras`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def record_cameras(session, camera_ids):
        calls.append(("cameras", tuple(sorted(camera_ids))))
        return original_lock_cameras(session, camera_ids)

    monkeypatch.setattr(service, "_lock_channels", record_channels)
    monkeypatch.setattr(service, "_lock_cameras", record_cameras)

    service.add_existing_camera(BASE_FEATURE, source["id"], camera_id)
    assert [kind for kind, _ in calls] == ["channels", "cameras"]

    calls.clear()
    service.move_camera(BASE_FEATURE, camera_id, target["id"])
    assert [kind for kind, _ in calls] == ["channels", "cameras"]
    assert calls[0][1] == tuple(sorted((source["id"], target["id"])))

    calls.clear()
    service.remove_camera(BASE_FEATURE, target["id"], camera_id)
    assert [kind for kind, _ in calls] == ["channels", "cameras"]

    service.add_existing_camera(BASE_FEATURE, target["id"], camera_id)
    calls.clear()
    service.reorder_members(BASE_FEATURE, target["id"], [camera_id])
    assert [kind for kind, _ in calls] == ["channels", "cameras"]

    calls.clear()
    service.delete_channel(BASE_FEATURE, target["id"])
    assert [kind for kind, _ in calls] == ["channels", "cameras"]


# 功能：验证 `test_membership_locking_sql_is_current_read_without_channel_join` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service_db.factory`、`service_db.service._build_membership_lock_query`、`str(query.statement.compile(dialect=mysql.dialect(),
#          compile_kwargs={'literal_binds': True})).upper`、`str`、`query.statement.compile`、`mysql.dialect`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_membership_locking_sql_is_current_read_without_channel_join(service_db):
    with service_db.factory() as session:
        query = service_db.service._build_membership_lock_query(
            session,
            member_ids=(1, 2),
            camera_ids=(3,),
            channel_ids=(4, 5),
        )
        sql = str(query.statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )).upper()

    assert " FOR UPDATE" in sql
    assert " JOIN " not in sql
    assert "AI_LOGISTICS_CHANNEL_CAMERA" in sql


# 功能：验证 `test_discovery_session_closes_before_formal_write_and_no_plain_read_occurs_inside` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_seed_camera`、`service.create_channel`、`monkeypatch.setattr`、`service.add_existing_camera`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_discovery_session_closes_before_formal_write_and_no_plain_read_occurs_inside(
    service_db,
    monkeypatch,
):
    import platform.logistics_channel.service as channel_service_module

    service = service_db.service
    camera_id = _seed_camera(service_db, "discover-before-write")
    channel = service.create_channel(BASE_FEATURE, "发现先于写")
    original_get_session = channel_service_module.get_session
    original_scope = channel_service_module.session_scope
    tracked_sessions = []
    formal_reads = []

    # 功能：定义 `TrackingSession` 类，封装业务服务相关的状态、约束与操作
    # 参数：
    #   - `wrapped`（未显式标注）：`wrapped` 对应的业务输入值
    # 返回：TrackingSession；返回新建的 `TrackingSession` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的
    #         `test_discovery_session_closes_before_formal_write_and_no_plain_read_occurs_inside::tracked_get_session` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class TrackingSession:
        # 功能：初始化或配置 `__init__` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `wrapped`（未显式标注）：`wrapped` 对应的业务输入值
        # 返回：None；初始化当前实例，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：会更新当前实例的运行状态。
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.closed = False

        # 功能：实现 `__getattr__` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `name`（未显式标注）：业务对象名称
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`getattr`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        # 功能：停止并释放 `close` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self.wrapped.close`。
        # 副作用/注意事项：会更新当前实例的运行状态。
        def close(self):
            self.closed = True
            self.wrapped.close()

    # 功能：读取或查询 `tracked_get_session` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`TrackingSession`、`original_get_session`、`tracked_sessions.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def tracked_get_session():
        tracked = TrackingSession(original_get_session())
        tracked_sessions.append(tracked)
        return tracked

    # 功能：定义 `TrackingQuery` 类，封装业务服务相关的状态、约束与操作
    # 参数：
    #   - `wrapped`（未显式标注）：`wrapped` 对应的业务输入值
    # 返回：TrackingQuery；返回新建的 `TrackingQuery` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的
    #         `test_discovery_session_closes_before_formal_write_and_no_plain_read_occurs_inside::FormalSession::query` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class TrackingQuery:
        # 功能：初始化或配置 `__init__` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `wrapped`（未显式标注）：`wrapped` 对应的业务输入值
        # 返回：None；初始化当前实例，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：会更新当前实例的运行状态。
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.locking = False

        # 功能：更新或保存 `with_for_update` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `*args`（未显式标注）：`args` 对应的业务输入值
        #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：`AiVision/platform/logistics_channel/service.py` 的
        #         `LogisticsChannelService::migrate_existing_feature_cameras::migrate_one`
        #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_lock_channels`
        #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_lock_cameras`
        #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_lock_migration_camera`
        #         调用本符号；另有 1 处静态调用
        #   - 内部调用：`self.wrapped.with_for_update`。
        # 副作用/注意事项：会更新当前实例的运行状态。
        def with_for_update(self, *args, **kwargs):
            self.locking = True
            self.wrapped = self.wrapped.with_for_update(*args, **kwargs)
            return self

        # 功能：实现 `__getattr__` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `name`（未显式标注）：业务对象名称
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`getattr`、`callable`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def __getattr__(self, name):
            attribute = getattr(self.wrapped, name)
            if not callable(attribute):
                return attribute

            # 功能：实现 `invoke` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
            # 参数：
            #   - `*args`（未显式标注）：`args` 对应的业务输入值
            #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
            # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
            # 调用关系：
            #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
            #   - 内部调用：`formal_reads.append`、`attribute`、`isinstance`。
            # 副作用/注意事项：会更新当前实例的运行状态。
            def invoke(*args, **kwargs):
                if name in {"all", "first", "one", "scalar"}:
                    formal_reads.append(self.locking)
                result = attribute(*args, **kwargs)
                if isinstance(result, Query):
                    self.wrapped = result
                    return self
                return result

            return invoke

    # 功能：定义 `FormalSession` 类，封装业务服务相关的状态、约束与操作
    # 参数：
    #   - `wrapped`（未显式标注）：`wrapped` 对应的业务输入值
    # 返回：FormalSession；返回新建的 `FormalSession` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的
    #         `test_discovery_session_closes_before_formal_write_and_no_plain_read_occurs_inside::tracked_write_scope` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FormalSession:
        # 功能：初始化或配置 `__init__` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `wrapped`（未显式标注）：`wrapped` 对应的业务输入值
        # 返回：None；初始化当前实例，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：会更新当前实例的运行状态。
        def __init__(self, wrapped):
            self.wrapped = wrapped

        # 功能：读取或查询 `query` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `*entities`（未显式标注）：`entities` 对应的业务输入值
        #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`TrackingQuery`、`self.wrapped.query`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def query(self, *entities, **kwargs):
            return TrackingQuery(self.wrapped.query(*entities, **kwargs))

        # 功能：实现 `__getattr__` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `name`（未显式标注）：业务对象名称
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`getattr`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def __getattr__(self, name):
            return getattr(self.wrapped, name)

    # 功能：更新或保存 `tracked_write_scope` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`original_scope`、`FormalSession`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @contextmanager
    def tracked_write_scope():
        assert tracked_sessions and tracked_sessions[-1].closed is True
        with original_scope() as session:
            yield FormalSession(session)

    monkeypatch.setattr(channel_service_module, "get_session", tracked_get_session)
    monkeypatch.setattr(channel_service_module, "session_scope", tracked_write_scope)

    service.add_existing_camera(BASE_FEATURE, channel["id"], camera_id)

    assert tracked_sessions[0].closed is True
    assert formal_reads[:3] == [True, True, True]
    assert False not in formal_reads[:3]


# 功能：验证 `test_membership_change_retries_with_new_discovery_and_channel_lock_set` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`channel_service_module._MembershipDiscovery`、`channel_service_module._DiscoveredMembership`、`monkeypatch.setattr`、`service._run_membership_transaction`、`sorted`、`tuple`、`len`、`id`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_membership_change_retries_with_new_discovery_and_channel_lock_set(service_db, monkeypatch):
    import platform.logistics_channel.service as channel_service_module

    service = service_db.service
    source_one = service.create_channel(BASE_FEATURE, "重试锁集合一")
    source_two = service.create_channel(BASE_FEATURE, "重试锁集合二")
    target = service.create_channel(BASE_FEATURE, "重试锁集合目标")
    discoveries = [
        channel_service_module._MembershipDiscovery(
            members=(channel_service_module._DiscoveredMembership(
                member_id=10,
                channel_id=source_one["id"],
                camera_id=7,
                feature_name=BASE_FEATURE,
            ),),
            camera_scope=(7,),
            channel_scope=(),
        ),
        channel_service_module._MembershipDiscovery(
            members=(channel_service_module._DiscoveredMembership(
                member_id=10,
                channel_id=source_two["id"],
                camera_id=7,
                feature_name=BASE_FEATURE,
            ),),
            camera_scope=(7,),
            channel_scope=(),
        ),
    ]
    discovery_calls = []
    write_sessions = []
    locked_channel_sets = []

    # 功能：实现 `discover` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`len`、`discovery_calls.append`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def discover():
        result = discoveries[len(discovery_calls)]
        discovery_calls.append(result)
        return result

    # 功能：实现 `operation` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `discovery`（未显式标注）：`discovery` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`unified_frontend/src/components/security-vlm/SecurityCameraDialog.tsx` 的 `SecurityCameraDialog`
    #         调用本符号；`AiVision/platform/camera/service.py` 的 `CameraService::_run_write_transaction`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_run_write_transaction`
    #         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::_run_membership_transaction` 调用本符号
    #   - 内部调用：`write_sessions.append`、`sorted`、`service._lock_channels`、`locked_channel_sets.append`、`tuple`、`len`、`channel_service_module._MembershipLockSetChanged`、`list`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
    def operation(session, discovery):
        write_sessions.append(session)
        channel_ids = sorted({target["id"], *discovery.member_channel_ids})
        locked = service._lock_channels(session, channel_ids)
        locked_channel_sets.append(tuple(locked))
        if len(write_sessions) == 1:
            raise channel_service_module._MembershipLockSetChanged()
        return list(locked)

    monkeypatch.setattr(channel_service_module, "sleep", lambda _: None)
    result = service._run_membership_transaction(discover, operation)

    assert result == sorted((source_two["id"], target["id"]))
    assert locked_channel_sets == [
        tuple(sorted((source_one["id"], target["id"]))),
        tuple(sorted((source_two["id"], target["id"]))),
    ]
    assert len({id(session) for session in write_sessions}) == 2


# 功能：验证 `test_membership_change_retry_has_total_limit` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`pytest.raises`、`service_db.service._run_membership_transaction`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_membership_change_retry_has_total_limit(service_db, monkeypatch):
    import platform.logistics_channel.service as channel_service_module

    attempts = []

    # 功能：实现 `discover` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`attempts.append`、`channel_service_module._MembershipDiscovery`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def discover():
        attempts.append("discover")
        return channel_service_module._MembershipDiscovery(
            members=(),
            camera_scope=(),
            channel_scope=(),
        )

    # 功能：实现 `always_changed` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `discovery`（未显式标注）：`discovery` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`channel_service_module._MembershipLockSetChanged`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def always_changed(session, discovery):
        raise channel_service_module._MembershipLockSetChanged()

    monkeypatch.setattr(channel_service_module, "sleep", lambda _: None)
    with pytest.raises(channel_service_module._MembershipLockSetChanged):
        service_db.service._run_membership_transaction(discover, always_changed)
    assert attempts == ["discover", "discover", "discover"]


# 功能：验证 `test_capacity_and_sort_use_same_locked_membership_rows` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`_seed_camera`、`range`、`service.add_existing_camera`、`monkeypatch.setattr`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_capacity_and_sort_use_same_locked_membership_rows(service_db, monkeypatch):
    service = service_db.service
    channel = service.create_channel(BASE_FEATURE, "锁定行容量")
    camera_ids = [_seed_camera(service_db, f"locked-capacity-{index}") for index in range(10)]
    for camera_id in camera_ids[:8]:
        service.add_existing_camera(BASE_FEATURE, channel["id"], camera_id)

    locked_row_ids = []
    capacity_row_ids = []
    sort_row_ids = []
    original_lock_state = service._lock_membership_state
    original_capacity = service._require_capacity
    original_next_sort = service._next_sort_order

    # 功能：实现 `track_lock_state` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`original_lock_state`、`locked_row_ids.append`、`id`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def track_lock_state(*args, **kwargs):
        state = original_lock_state(*args, **kwargs)
        locked_row_ids.append(id(state.members))
        return state

    # 功能：实现 `track_capacity` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `members`（未显式标注）：`members` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`capacity_row_ids.append`、`id`、`original_capacity`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def track_capacity(members, channel_id):
        capacity_row_ids.append(id(members))
        return original_capacity(members, channel_id)

    # 功能：实现 `track_sort` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `members`（未显式标注）：`members` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`sort_row_ids.append`、`id`、`original_next_sort`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def track_sort(members, channel_id):
        sort_row_ids.append(id(members))
        return original_next_sort(members, channel_id)

    monkeypatch.setattr(service, "_lock_membership_state", track_lock_state)
    monkeypatch.setattr(service, "_require_capacity", track_capacity)
    monkeypatch.setattr(service, "_next_sort_order", track_sort)

    service.add_existing_camera(BASE_FEATURE, channel["id"], camera_ids[8])
    with pytest.raises(ValueError, match="最多.*9.*路"):
        service.add_existing_camera(BASE_FEATURE, channel["id"], camera_ids[9])

    assert capacity_row_ids == locked_row_ids
    assert sort_row_ids == locked_row_ids[:1]


# 功能：验证 `test_move_reorder_and_remove_preserve_camera_config` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`_seed_camera`、`range`、`service_db.factory.begin`、`session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_ids[1]).one`、`session.query(all_specs()[BASE_FEATURE].orm_class).filter_by`、`session.query`、`all_specs`、`service.add_existing_camera`、`service.move_camera`
#          等共 20 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_move_reorder_and_remove_preserve_camera_config(service_db):
    service = service_db.service
    source = service.create_channel(BASE_FEATURE, "来源")
    target = service.create_channel(BASE_FEATURE, "目标")
    camera_ids = [_seed_camera(service_db, f"route-{index}") for index in range(3)]
    with service_db.factory.begin() as session:
        retained_cfg = (
            session.query(all_specs()[BASE_FEATURE].orm_class)
            .filter_by(camera_id=camera_ids[1])
            .one()
        )
        retained_cfg.roi_pos = [[10, 20], [30, 40]]
        retained_cfg.CONF_THRESHOLD = 0.66
    for camera_id in camera_ids:
        service.add_existing_camera(BASE_FEATURE, source["id"], camera_id)

    service.move_camera(BASE_FEATURE, camera_ids[0], target["id"])
    assert [m["camera_id"] for m in service.get_channel(BASE_FEATURE, target["id"])["members"]] == [camera_ids[0]]
    with service_db.factory() as session:
        cfg = session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_ids[0]).one()
        assert cfg.enable is True
        memberships = (
            session.query(LogisticsChannelCamera)
            .join(LogisticsChannel)
            .filter(LogisticsChannel.feature_name == BASE_FEATURE, LogisticsChannelCamera.camera_id == camera_ids[0])
            .count()
        )
        assert memberships == 1

    with pytest.raises(ValueError, match="全部成员"):
        service.reorder_members(BASE_FEATURE, source["id"], [camera_ids[1]])
    reordered = service.reorder_members(BASE_FEATURE, source["id"], [camera_ids[2], camera_ids[1]])
    assert [m["camera_id"] for m in reordered["members"]] == [camera_ids[2], camera_ids[1]]

    assert service.remove_camera(BASE_FEATURE, source["id"], camera_ids[1]) is True
    with service_db.factory() as session:
        assert session.get(AiCameraConfig, camera_ids[1]) is not None
        cfg = session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_ids[1]).one()
        assert cfg.enable is False
        assert cfg.roi_pos == [[10, 20], [30, 40]]
        assert cfg.CONF_THRESHOLD == 0.66


# 功能：验证 `test_move_to_full_channel_fails_without_losing_original_binding` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`_seed_camera`、`service.add_existing_camera`、`range`、`pytest.raises`、`service.move_camera`、`service.get_channel`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_move_to_full_channel_fails_without_losing_original_binding(service_db):
    service = service_db.service
    source = service.create_channel(BASE_FEATURE, "来源")
    target = service.create_channel(BASE_FEATURE, "满载目标")
    moving_id = _seed_camera(service_db, "moving")
    service.add_existing_camera(BASE_FEATURE, source["id"], moving_id)
    for index in range(MAX_CAMERAS_PER_CHANNEL):
        camera_id = _seed_camera(service_db, f"full-{index}")
        service.add_existing_camera(BASE_FEATURE, target["id"], camera_id)

    with pytest.raises(ValueError, match="最多.*9.*路"):
        service.move_camera(BASE_FEATURE, moving_id, target["id"])

    assert [m["camera_id"] for m in service.get_channel(BASE_FEATURE, source["id"])["members"]] == [moving_id]


# 功能：验证 `test_set_member_enabled_is_atomic_preserves_config_and_notifies_channel_once` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`_seed_camera`、`service.add_existing_camera`、`service_db.notifications.clear`、`service.set_member_enabled`、`len`、`_events`、`service_db.factory`、`session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_id).one`、`session.query(all_specs()[BASE_FEATURE].orm_class).filter_by`
#          等共 13 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_set_member_enabled_is_atomic_preserves_config_and_notifies_channel_once(service_db):
    service = service_db.service
    channel = service.create_channel(BASE_FEATURE, "成员启停")
    camera_id = _seed_camera(service_db, "toggle-member")
    service.add_existing_camera(BASE_FEATURE, channel["id"], camera_id)
    service_db.notifications.clear()

    disabled = service.set_member_enabled(BASE_FEATURE, channel["id"], camera_id, False)
    assert disabled["members"][0]["enabled"] is False
    assert len(_events(service_db, "logistics_channel_updated")) == 1
    assert _events(service_db, f"{BASE_FEATURE}_disabled") == []
    with service_db.factory() as session:
        cfg = session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_id).one()
        assert cfg.enable is True

    service_db.notifications.clear()
    enabled = service.set_member_enabled(BASE_FEATURE, channel["id"], camera_id, True)
    assert enabled["members"][0]["enabled"] is True
    assert len(_events(service_db, "logistics_channel_updated")) == 1

    with pytest.raises(ValueError, match="成员不存在"):
        service.set_member_enabled(BASE_FEATURE, channel["id"], camera_id + 1000, False)


# 功能：验证 `test_delete_channel_disables_members_without_deleting_global_cameras` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`_seed_camera`、`service.add_existing_camera`、`service.delete_channel`、`service_db.factory`、`session.get`、`session.query(LogisticsChannelCamera).filter_by(camera_id=camera_id).count`、`session.query(LogisticsChannelCamera).filter_by`、`session.query`、`session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_id).one`
#          等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_delete_channel_disables_members_without_deleting_global_cameras(service_db):
    service = service_db.service
    channel = service.create_channel(BASE_FEATURE, "待删除")
    camera_id = _seed_camera(service_db, "kept-camera")
    service.add_existing_camera(BASE_FEATURE, channel["id"], camera_id)

    assert service.delete_channel(BASE_FEATURE, channel["id"]) is True
    with service_db.factory() as session:
        assert session.get(AiCameraConfig, camera_id) is not None
        assert session.query(LogisticsChannelCamera).filter_by(camera_id=camera_id).count() == 0
        cfg = session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_id).one()
        assert cfg.enable is False


# 功能：验证 `test_create_camera_and_bind_is_atomic_uses_feature_department_and_notifies_after_commit` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`service_db.notifications.clear`、`service.create_camera_and_bind`、`service_db.factory`、`session.get`、`all_specs().items`、`all_specs`、`session.query(spec.orm_class).filter_by(camera_id=camera_id).one`、`session.query(spec.orm_class).filter_by`、`session.query`
#          等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_create_camera_and_bind_is_atomic_uses_feature_department_and_notifies_after_commit(service_db):
    service = service_db.service
    channel = service.create_channel(BASE_FEATURE, "新相机")
    service_db.notifications.clear()

    detail = service.create_camera_and_bind(
        BASE_FEATURE,
        channel["id"],
        {"name": "入口相机", "url": "rtsp://example/new", "fps": 6},
    )
    camera_id = detail["members"][0]["camera_id"]
    with service_db.factory() as session:
        camera = session.get(AiCameraConfig, camera_id)
        assert camera.shm_name == f"camera_{camera_id}"
        assert camera.department == "general_electric"
        for feature_name, spec in all_specs().items():
            cfg = session.query(spec.orm_class).filter_by(camera_id=camera_id).one()
            assert cfg.enable is (feature_name == BASE_FEATURE)

    event_types = [item[1].change_type for item in service_db.notifications if item[0] == "event"]
    cache_notifications = [item for item in service_db.notifications if item[0] == "cache"]
    assert cache_notifications == [("cache", "reload")]
    assert event_types.count("camera_added") == 1
    assert f"{BASE_FEATURE}_enabled" in event_types
    assert "logistics_channel_updated" in event_types
    assert _events(service_db, f"{BASE_FEATURE}_enabled")[0].camera_name == f"camera_{camera_id}"


# 功能：验证 `test_create_camera_and_bind_rolls_back_camera_and_notifications_when_channel_is_full` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`range`、`_seed_camera`、`service.add_existing_camera`、`service_db.notifications.clear`、`pytest.raises`、`service.create_camera_and_bind`、`service_db.factory`、`session.query(AiCameraConfig).filter_by(name='不应保留').first`、`session.query(AiCameraConfig).filter_by`
#          等共 11 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_create_camera_and_bind_rolls_back_camera_and_notifications_when_channel_is_full(service_db):
    service = service_db.service
    channel = service.create_channel(BASE_FEATURE, "满载")
    for index in range(MAX_CAMERAS_PER_CHANNEL):
        camera_id = _seed_camera(service_db, f"capacity-{index}")
        service.add_existing_camera(BASE_FEATURE, channel["id"], camera_id)
    service_db.notifications.clear()

    with pytest.raises(ValueError, match="最多.*9.*路"):
        service.create_camera_and_bind(
            BASE_FEATURE,
            channel["id"],
            {"name": "不应保留", "url": "rtsp://example/rollback"},
        )

    with service_db.factory() as session:
        assert session.query(AiCameraConfig).filter_by(name="不应保留").first() is None
    assert service_db.notifications == []


# 功能：验证 `test_create_camera_and_bind_rolls_back_all_rows_when_member_flush_fails` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`monkeypatch.setattr`、`service_db.notifications.clear`、`pytest.raises`、`service.create_camera_and_bind`、`service_db.factory`、`session.query(AiCameraConfig).filter_by(name='事务回滚相机').first`、`session.query(AiCameraConfig).filter_by`、`session.query`、`session.query(LogisticsChannelCamera).filter_by(channel_id=channel['id']).count`
#          等共 14 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_create_camera_and_bind_rolls_back_all_rows_when_member_flush_fails(service_db, monkeypatch):
    service = service_db.service
    channel = service.create_channel(BASE_FEATURE, "强制回滚")
    original_bind = service._insert_locked_member

    # 功能：实现 `bind_then_fail` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`original_bind`、`RuntimeError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def bind_then_fail(*args, **kwargs):
        original_bind(*args, **kwargs)
        raise RuntimeError("forced member flush failure")

    monkeypatch.setattr(service, "_insert_locked_member", bind_then_fail)
    service_db.notifications.clear()
    with pytest.raises(RuntimeError, match="forced member flush failure"):
        service.create_camera_and_bind(
            BASE_FEATURE,
            channel["id"],
            {"name": "事务回滚相机", "url": "rtsp://example/flush-rollback"},
        )

    with service_db.factory() as session:
        assert session.query(AiCameraConfig).filter_by(name="事务回滚相机").first() is None
        assert session.query(LogisticsChannelCamera).filter_by(channel_id=channel["id"]).count() == 0
        for spec in all_specs().values():
            assert session.query(spec.orm_class).count() == 0
    assert service_db.notifications == []


# 功能：验证 `test_create_camera_rejects_feature_department_mismatch` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service_db.service.create_channel`、`pytest.raises`、`service_db.service.create_camera_and_bind`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_create_camera_rejects_feature_department_mismatch(service_db):
    channel = service_db.service.create_channel(EE_FEATURE, "电子电工")
    with pytest.raises(ValueError, match="department"):
        service_db.service.create_camera_and_bind(
            EE_FEATURE,
            channel["id"],
            {
                "name": "部门不符",
                "url": "rtsp://example/mismatch",
                "department": "general_electric",
            },
        )


# 功能：验证 `test_create_camera_rejects_explicit_empty_department` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service_db.service.create_channel`、`pytest.raises`、`service_db.service.create_camera_and_bind`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_create_camera_rejects_explicit_empty_department(service_db):
    channel = service_db.service.create_channel(BASE_FEATURE, "空部门")
    with pytest.raises(ValueError, match="department"):
        service_db.service.create_camera_and_bind(
            BASE_FEATURE,
            channel["id"],
            {
                "name": "空部门相机",
                "url": "rtsp://example/empty-department",
                "department": "",
            },
        )


# 功能：验证 `test_camera_service_create_camera_allows_missing_shm_name_and_keeps_return_contract` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service_db.camera_service.create_camera`、`set`、`all_specs`、`all`、`result['functions'].values`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_service_create_camera_allows_missing_shm_name_and_keeps_return_contract(service_db):
    result = service_db.camera_service.create_camera({
        "name": "普通相机",
        "url": "rtsp://example/plain",
    })

    assert result["camera_id"] > 0
    assert result["id"] == f"camera_{result['camera_id']}"
    assert result["shm_name"] == result["id"]
    assert set(result["functions"]) == set(all_specs())
    assert all(enabled is False for enabled in result["functions"].values())


# 功能：验证 `test_camera_service_create_camera_for_feature_enables_only_target_atomically` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service_db.camera_service.create_camera_for_feature`、`all`、`result['functions'].items`、`event_types.count`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_service_create_camera_for_feature_enables_only_target_atomically(service_db):
    result = service_db.camera_service.create_camera_for_feature(
        "detect_human",
        {
            "name": "人员逗留新增相机",
            "url": "rtsp://example/human",
            "fps": 7,
        },
    )

    assert result["department"] == "general_electric"
    assert result["functions"]["detect_human"] is True
    assert all(
        enabled is (feature_name == "detect_human")
        for feature_name, enabled in result["functions"].items()
    )
    event_types = [
        item[1].change_type
        for item in service_db.notifications
        if item[0] == "event"
    ]
    assert event_types.count("camera_added") == 1
    assert event_types.count("detect_human_enabled") == 1


# 功能：验证 `test_camera_service_create_camera_for_feature_requires_valid_department` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`service_db.camera_service.create_camera_for_feature`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_service_create_camera_for_feature_requires_valid_department(service_db):
    with pytest.raises(ValueError, match="department 是必填项"):
        service_db.camera_service.create_camera_for_feature(
            "detect_phone",
            {
                "name": "缺少事业部",
                "url": "rtsp://example/no-department",
            },
        )

    with pytest.raises(ValueError, match="department 必须属于当前功能"):
        service_db.camera_service.create_camera_for_feature(
            "detect_face",
            {
                "name": "事业部不匹配",
                "url": "rtsp://example/wrong-department",
                "department": "general_electric",
            },
        )


# 功能：验证 `test_write_transaction_retries_mysql_lock_errors_with_fresh_sessions` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `error_code`（未显式标注）：`error_code` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`service_db.service.create_channel`、`len`、`id`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("error_code", [1205, 1213])
def test_write_transaction_retries_mysql_lock_errors_with_fresh_sessions(
    service_db,
    monkeypatch,
    error_code,
):
    import platform.logistics_channel.service as channel_service_module

    original_scope = channel_service_module.session_scope
    attempts = []
    sessions = []

    # 功能：实现 `flaky_scope` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`attempts.append`、`object`、`original_scope`、`sessions.append`、`len`、`OperationalError`、`Exception`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @contextmanager
    def flaky_scope():
        attempts.append(object())
        with original_scope() as session:
            sessions.append(session)
            yield session
            if len(attempts) < 3:
                raise OperationalError("commit", {}, Exception(error_code, "lock failure"))

    monkeypatch.setattr(channel_service_module, "session_scope", flaky_scope)
    monkeypatch.setattr(channel_service_module, "sleep", lambda _: None, raising=False)

    result = service_db.service.create_channel(BASE_FEATURE, f"重试-{error_code}")

    assert result["name"] == f"重试-{error_code}"
    assert len(attempts) == 3
    assert len({id(session) for session in sessions}) == 3


# 功能：验证 `test_write_transaction_stops_after_retry_limit` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`pytest.raises`、`service_db.service.create_channel`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_write_transaction_stops_after_retry_limit(service_db, monkeypatch):
    import platform.logistics_channel.service as channel_service_module

    original_scope = channel_service_module.session_scope
    attempts = []

    # 功能：实现 `always_deadlocked` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`attempts.append`、`object`、`original_scope`、`OperationalError`、`Exception`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @contextmanager
    def always_deadlocked():
        attempts.append(object())
        with original_scope() as session:
            yield session
            raise OperationalError("commit", {}, Exception(1213, "deadlock"))

    monkeypatch.setattr(channel_service_module, "session_scope", always_deadlocked)
    monkeypatch.setattr(channel_service_module, "sleep", lambda _: None, raising=False)

    with pytest.raises(OperationalError):
        service_db.service.create_channel(BASE_FEATURE, "重试耗尽")
    assert len(attempts) == 3


# 功能：验证 `test_write_transaction_does_not_retry_other_operational_errors` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`pytest.raises`、`service_db.service.create_channel`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_write_transaction_does_not_retry_other_operational_errors(service_db, monkeypatch):
    import platform.logistics_channel.service as channel_service_module

    original_scope = channel_service_module.session_scope
    attempts = []

    # 功能：实现 `unavailable` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`attempts.append`、`object`、`original_scope`、`OperationalError`、`Exception`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @contextmanager
    def unavailable():
        attempts.append(object())
        with original_scope() as session:
            yield session
            raise OperationalError("commit", {}, Exception(2006, "server gone"))

    monkeypatch.setattr(channel_service_module, "session_scope", unavailable)

    with pytest.raises(OperationalError):
        service_db.service.create_channel(BASE_FEATURE, "不重试")
    assert len(attempts) == 1


# 功能：验证 `test_camera_create_retries_mysql_deadlock_with_new_session` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`service_db.camera_service.create_camera`、`len`、`id`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_create_retries_mysql_deadlock_with_new_session(service_db, monkeypatch):
    import platform.camera.service as camera_service_module

    original_scope = camera_service_module.session_scope
    sessions = []

    # 功能：实现 `deadlock_once` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`original_scope`、`sessions.append`、`len`、`OperationalError`、`Exception`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @contextmanager
    def deadlock_once():
        with original_scope() as session:
            sessions.append(session)
            yield session
            if len(sessions) == 1:
                raise OperationalError("commit", {}, Exception(1213, "deadlock"))

    monkeypatch.setattr(camera_service_module, "session_scope", deadlock_once)
    monkeypatch.setattr(camera_service_module, "sleep", lambda _: None)

    result = service_db.camera_service.create_camera({
        "name": "摄像头重试",
        "url": "rtsp://example/camera-retry",
    })

    assert result["name"] == "摄像头重试"
    assert len({id(session) for session in sessions}) == 2


# 功能：验证 `test_camera_service_translates_commit_integrity_errors` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `message`（未显式标注）：用于展示、记录或发送的文本消息
#   - `expected`（未显式标注）：`expected` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`pytest.raises`、`service_db.camera_service.create_camera`、`isinstance`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Duplicate entry for key 'ai_camera_config.name'", "name"),
        ("Duplicate entry for key 'ai_camera_config.shm_name'", "shm_name"),
        ("foreign key constraint fails", "数据约束冲突"),
    ],
)
def test_camera_service_translates_commit_integrity_errors(
    service_db,
    monkeypatch,
    message,
    expected,
):
    import platform.camera.service as camera_service_module

    original_scope = camera_service_module.session_scope

    # 功能：实现 `integrity_failure` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`original_scope`、`IntegrityError`、`Exception`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @contextmanager
    def integrity_failure():
        with original_scope() as session:
            yield session
            raise IntegrityError("commit", {}, Exception(message))

    monkeypatch.setattr(camera_service_module, "session_scope", integrity_failure)
    with pytest.raises(ValueError, match=expected) as raised:
        service_db.camera_service.create_camera({
            "name": "并发相机",
            "url": "rtsp://example/integrity",
        })
    assert isinstance(raised.value.__cause__, IntegrityError)


# 功能：验证 `test_create_camera_and_bind_translates_camera_integrity_error` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service_db.service.create_channel`、`monkeypatch.setattr`、`pytest.raises`、`service_db.service.create_camera_and_bind`、`isinstance`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_create_camera_and_bind_translates_camera_integrity_error(service_db, monkeypatch):
    import platform.logistics_channel.service as channel_service_module

    channel = service_db.service.create_channel(BASE_FEATURE, "并发绑定")
    original_scope = channel_service_module.session_scope

    # 功能：实现 `name_conflict` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`original_scope`、`IntegrityError`、`Exception`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @contextmanager
    def name_conflict():
        with original_scope() as session:
            yield session
            raise IntegrityError(
                "commit",
                {},
                Exception("Duplicate entry for key 'ai_camera_config.name'"),
            )

    monkeypatch.setattr(channel_service_module, "session_scope", name_conflict)
    with pytest.raises(ValueError, match="name") as raised:
        service_db.service.create_camera_and_bind(
            BASE_FEATURE,
            channel["id"],
            {"name": "并发绑定相机", "url": "rtsp://example/concurrent"},
        )
    assert isinstance(raised.value.__cause__, IntegrityError)


# 功能：验证 `test_updates_reject_explicit_none_for_not_null_fields` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `method`（未显式标注）：`method` 对应的业务输入值
#   - `payload`（未显式标注）：接口或事件携带的业务数据
#   - `field`（未显式标注）：`field` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service_db.service.create_channel`、`pytest.raises`、`getattr(service_db.service,
#          method)`、`getattr`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    ("method", "payload", "field"),
    [
        ("update_channel", {"enabled": None}, "enabled"),
        ("update_channel", {"sort_order": None}, "sort_order"),
        ("update_config", {"alarm_interval": None}, "alarm_interval"),
        ("update_config", {"detection_start": None}, "detection_start"),
        ("update_config", {"confidence_threshold": None}, "confidence_threshold"),
    ],
)
def test_updates_reject_explicit_none_for_not_null_fields(service_db, method, payload, field):
    channel = service_db.service.create_channel(BASE_FEATURE, f"非空-{method}-{field}")
    with pytest.raises(ValueError, match=field):
        getattr(service_db.service, method)(BASE_FEATURE, channel["id"], payload)


# 功能：验证 `test_migration_is_feature_isolated_copies_flat_fields_and_is_idempotent` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_seed_camera`、`service_db.factory.begin`、`session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_id).one`、`session.query(all_specs()[BASE_FEATURE].orm_class).filter_by`、`session.query`、`all_specs`、`session.add`、`LogisticsChannel`、`service_db.notifications.clear`、`service_db.service.migrate_existing_feature_cameras`
#          等共 18 个调用。
# 副作用/注意事项：可能读取或修改数据库事务。
def test_migration_is_feature_isolated_copies_flat_fields_and_is_idempotent(service_db):
    camera_id = _seed_camera(
        service_db,
        "迁移相机",
        enabled_features=(BASE_FEATURE, EE_FEATURE),
    )
    with service_db.factory.begin() as session:
        base_cfg = session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_id).one()
        base_cfg.empty_grace_seconds = 6.0
        base_cfg.multi_grace_seconds = 7.0
        base_cfg.CONF_THRESHOLD = 0.46
        base_cfg.alarm_interval = 12.0
        base_cfg.sql_enable = True
        base_cfg.horn_enable = True
        base_cfg.horn_id = None
        base_cfg.horn_event_id = 8
        base_cfg.wechat_enable = True
        base_cfg.wechat_user = "base-user"
        base_cfg.roi_pos = [[1, 2], [3, 4]]
        session.add(LogisticsChannel(name="迁移相机", feature_name=BASE_FEATURE))

    service_db.notifications.clear()
    first = service_db.service.migrate_existing_feature_cameras()
    first_notifications = list(service_db.notifications)
    second = service_db.service.migrate_existing_feature_cameras()

    assert isinstance(first, MigrationSummary)
    assert (first.created, first.failed) == (2, 0)
    assert first.skipped == 0
    assert second.created == 0
    assert second.skipped == 2
    assert [item for item in first_notifications if item == ("cache", "reload")] == [
        ("cache", "reload")
    ]
    migrated_enabled = [
        item[1]
        for item in first_notifications
        if item[0] == "event" and item[1].change_type.endswith("_enabled")
    ]
    assert sorted(event.camera_name for event in migrated_enabled) == [
        "shm_迁移相机",
        "shm_迁移相机",
    ]
    with service_db.factory() as session:
        base_channel = session.query(LogisticsChannel).filter_by(
            feature_name=BASE_FEATURE,
            name=f"迁移相机-{camera_id}",
        ).one()
        ee_channel = session.query(LogisticsChannel).filter_by(
            feature_name=EE_FEATURE,
            name="迁移相机",
        ).one()
        assert base_channel.confidence_threshold == 0.46
        assert base_channel.empty_grace_seconds == 6.0
        assert base_channel.multi_grace_seconds == 7.0
        assert base_channel.alarm_interval == 12.0
        assert base_channel.sql_enable is True
        assert base_channel.wechat_user == "base-user"
        assert ee_channel.id != base_channel.id
        base_cfg = session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_id).one()
        assert base_cfg.roi_pos == [[1, 2], [3, 4]]


# 功能：验证 `test_migration_rehearsal_covers_all_four_features_and_preserves_camera_configs` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`enumerate`、`sorted`、`_seed_camera`、`service_db.factory.begin`、`session.query(all_specs()[feature_name].orm_class).filter_by(camera_id=camera_id).one`、`session.query(all_specs()[feature_name].orm_class).filter_by`、`session.query`、`all_specs`、`session.get`、`session.add`
#          等共 20 个调用。
# 副作用/注意事项：可能读取或修改数据库事务；可能启动、等待或停止线程/进程资源。
def test_migration_rehearsal_covers_all_four_features_and_preserves_camera_configs(service_db):
    camera_ids: dict[str, int] = {}
    original_rois: dict[str, list[list[int]]] = {}
    for index, feature_name in enumerate(sorted(LOGISTICS_FEATURES), start=1):
        camera_id = _seed_camera(
            service_db,
            f"四模块迁移相机-{index}",
            enabled_features=(feature_name,),
        )
        roi = [[index, index + 1], [index + 20, index + 30]]
        with service_db.factory.begin() as session:
            cfg = session.query(all_specs()[feature_name].orm_class).filter_by(
                camera_id=camera_id,
            ).one()
            cfg.roi_pos = roi
        camera_ids[feature_name] = camera_id
        original_rois[feature_name] = roi

    collision_feature = sorted(LOGISTICS_FEATURES)[0]
    collision_camera_id = camera_ids[collision_feature]
    with service_db.factory.begin() as session:
        collision_camera = session.get(AiCameraConfig, collision_camera_id)
        session.add(LogisticsChannel(
            feature_name=collision_feature,
            name=collision_camera.name,
        ))

    first = service_db.service.migrate_existing_feature_cameras()
    second = service_db.service.migrate_existing_feature_cameras()

    assert (first.created, first.skipped, first.failed) == (4, 0, 0)
    assert (second.created, second.skipped, second.failed) == (0, 4, 0)
    with service_db.factory() as session:
        for feature_name, camera_id in camera_ids.items():
            memberships = (
                session.query(LogisticsChannelCamera)
                .join(LogisticsChannel)
                .filter(
                    LogisticsChannel.feature_name == feature_name,
                    LogisticsChannelCamera.camera_id == camera_id,
                )
                .all()
            )
            assert len(memberships) == 1
            cfg = session.query(all_specs()[feature_name].orm_class).filter_by(
                camera_id=camera_id,
            ).one()
            assert cfg.enable is True
            assert cfg.roi_pos == original_rois[feature_name]

        migrated_collision = (
            session.query(LogisticsChannel)
            .filter_by(
                feature_name=collision_feature,
                name=f"四模块迁移相机-1-{collision_camera_id}",
            )
            .one()
        )
        assert migrated_collision.cameras[0].camera_id == collision_camera_id


# 功能：验证 `test_migration_records_one_camera_failure_and_continues` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `caplog`（未显式标注）：`caplog` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_seed_camera`、`service_db.factory.begin`、`session.add_all`、`LogisticsChannel`、`service_db.service.migrate_existing_feature_cameras`、`len`、`service_db.factory`、`session.query(LogisticsChannelCamera).filter_by(camera_id=failed_camera_id).count`、`session.query(LogisticsChannelCamera).filter_by`、`session.query`
#          等共 11 个调用。
# 副作用/注意事项：可能读取或修改数据库事务。
def test_migration_records_one_camera_failure_and_continues(service_db, caplog):
    failed_camera_id = _seed_camera(
        service_db,
        "冲突相机",
        enabled_features=(BASE_FEATURE,),
    )
    successful_camera_id = _seed_camera(
        service_db,
        "可迁移相机",
        enabled_features=(BASE_FEATURE,),
    )
    with service_db.factory.begin() as session:
        session.add_all([
            LogisticsChannel(name="冲突相机", feature_name=BASE_FEATURE),
            LogisticsChannel(name=f"冲突相机-{failed_camera_id}", feature_name=BASE_FEATURE),
        ])

    summary = service_db.service.migrate_existing_feature_cameras()

    assert (summary.created, summary.failed) == (1, 1)
    assert len(summary.errors) == 1
    assert f"camera_id={failed_camera_id}" in summary.errors[0]
    assert "迁移失败" in caplog.text
    with service_db.factory() as session:
        assert session.query(LogisticsChannelCamera).filter_by(camera_id=failed_camera_id).count() == 0
        assert session.query(LogisticsChannelCamera).filter_by(camera_id=successful_camera_id).count() == 1


# 功能：验证 `test_migration_without_success_does_not_reload_cache` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service_db.notifications.clear`、`service_db.service.migrate_existing_feature_cameras`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_migration_without_success_does_not_reload_cache(service_db):
    service_db.notifications.clear()

    summary = service_db.service.migrate_existing_feature_cameras()

    assert summary.created == 0
    assert [item for item in service_db.notifications if item == ("cache", "reload")] == []


# 功能：验证 `test_notification_failure_is_logged_without_undoing_committed_channel` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `caplog`（未显式标注）：`caplog` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`FailingEventBus`、`service_db.service.create_channel`、`service_db.service.get_channel`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_notification_failure_is_logged_without_undoing_committed_channel(service_db, monkeypatch, caplog):
    import platform.logistics_channel.service as channel_service_module

    # 功能：定义 `FailingEventBus` 类，封装业务服务相关的状态、约束与操作
    # 参数：无。
    # 返回：FailingEventBus；返回新建的 `FailingEventBus` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的
    #         `test_notification_failure_is_logged_without_undoing_committed_channel` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FailingEventBus:
        # 功能：发送或分发 `publish` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `event`（未显式标注）：待处理的事件对象
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`RuntimeError`。
        # 副作用/注意事项：校验或执行失败时会主动抛出异常。
        def publish(self, event):
            raise RuntimeError("event bus unavailable")

    monkeypatch.setattr(channel_service_module, "config_event_bus", FailingEventBus())
    result = service_db.service.create_channel(BASE_FEATURE, "通知失败仍保留")

    assert service_db.service.get_channel(BASE_FEATURE, result["id"])["name"] == "通知失败仍保留"
    assert "通道通知失败" in caplog.text


# 功能：验证 `test_logistics_channel_has_required_python_defaults` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`time`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_logistics_channel_has_required_python_defaults():
    columns = LogisticsChannel.__table__.c

    assert columns.enabled.default.arg is True
    assert columns.detection_start.default.arg == time(8, 0)
    assert columns.detection_end.default.arg == time(20, 0)
    assert columns.confidence_threshold.default.arg == 0.3
    assert columns.empty_grace_seconds.default.arg == 2.0
    assert columns.multi_grace_seconds.default.arg == 1.0


# 功能：验证 `test_unknown_logistics_feature_is_rejected` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`require_logistics_feature`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_unknown_logistics_feature_is_rejected():
    with pytest.raises(ValueError, match="不支持的物流检测功能"):
        require_logistics_feature("blocks")


# 功能：验证 `test_logistics_feature_literal_matches_feature_whitelist` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`set`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_logistics_feature_literal_matches_feature_whitelist():
    assert set(LogisticsFeatureName.__args__) == LOGISTICS_FEATURES


# 功能：验证 `test_status_constants_and_reasons_are_stable` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`set`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_status_constants_and_reasons_are_stable():
    assert DEFAULT_STATUS_STALE_SECONDS == 5.0
    assert set(LogisticsChannelStatusResponse.model_fields["reason"].annotation.__args__) == {
        "normal", "empty", "multiple", "unknown", "unconfigured", "inactive",
    }


# 功能：验证 `test_member_accepts_existing_camera_id_mode` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`LogisticsChannelMemberCreate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_member_accepts_existing_camera_id_mode():
    member = LogisticsChannelMemberCreate(camera_id=12)

    assert member.camera_id == 12
    assert member.name is None
    assert member.url is None


# 功能：验证 `test_member_existing_camera_mode_rejects_explicit_new_camera_fields` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`LogisticsChannelMemberCreate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_member_existing_camera_mode_rejects_explicit_new_camera_fields():
    with pytest.raises(ValidationError):
        LogisticsChannelMemberCreate(camera_id=12, shm_name="cam-12")
    with pytest.raises(ValidationError):
        LogisticsChannelMemberCreate(camera_id=12, fps=5)


# 功能：验证 `test_member_accepts_new_camera_name_url_mode` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`LogisticsChannelMemberCreate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_member_accepts_new_camera_name_url_mode():
    member = LogisticsChannelMemberCreate(name="入口摄像头", url="rtsp://example/cam", fps=5)

    assert member.camera_id is None
    assert member.name == "入口摄像头"
    assert member.url == "rtsp://example/cam"


# 功能：验证 `test_member_requires_exactly_one_camera_input_mode` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（未显式标注）：接口或事件携带的业务数据
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`LogisticsChannelMemberCreate`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"camera_id": 1, "name": "入口", "url": "rtsp://example/cam", "fps": 5},
        {"name": "入口", "url": "rtsp://example/cam", "fps": 0},
        {"name": "入口"},
    ],
)
def test_member_requires_exactly_one_camera_input_mode(payload):
    with pytest.raises(ValidationError):
        LogisticsChannelMemberCreate(**payload)


# 功能：验证 `test_member_rejects_unknown_fields_and_non_positive_camera_id` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`LogisticsChannelMemberCreate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_member_rejects_unknown_fields_and_non_positive_camera_id():
    with pytest.raises(ValidationError):
        LogisticsChannelMemberCreate(camera_id=0)
    with pytest.raises(ValidationError):
        LogisticsChannelMemberCreate(camera_id=1, unknown=True)


# 功能：验证 `test_member_order_limits_routes_to_nine_positive_unique_ids` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`LogisticsChannelMemberOrder`、`list`、`range`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_member_order_limits_routes_to_nine_positive_unique_ids():
    assert LogisticsChannelMemberOrder(camera_ids=list(range(1, MAX_CAMERAS_PER_CHANNEL + 1))).camera_ids
    with pytest.raises(ValidationError):
        LogisticsChannelMemberOrder(camera_ids=list(range(1, MAX_CAMERAS_PER_CHANNEL + 2)))
    with pytest.raises(ValidationError):
        LogisticsChannelMemberOrder(camera_ids=[0])
    with pytest.raises(ValidationError):
        LogisticsChannelMemberOrder(camera_ids=[1, 1])


# 功能：验证 `test_channel_config_requires_start_before_end` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`LogisticsChannelConfigUpdate`、`time`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_channel_config_requires_start_before_end():
    with pytest.raises(ValidationError):
        LogisticsChannelConfigUpdate(detection_start=time(20, 0), detection_end=time(8, 0))


# 功能：验证 `test_channel_config_validates_person_confidence_threshold` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`LogisticsChannelConfigUpdate`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_channel_config_validates_person_confidence_threshold():
    assert LogisticsChannelConfigUpdate().confidence_threshold == 0.3
    assert LogisticsChannelConfigUpdate(confidence_threshold=0.42).confidence_threshold == 0.42
    with pytest.raises(ValidationError):
        LogisticsChannelConfigUpdate(confidence_threshold=-0.01)
    with pytest.raises(ValidationError):
        LogisticsChannelConfigUpdate(confidence_threshold=1.01)


# 功能：验证 `test_channel_config_cannot_change_channel_enabled_state` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`LogisticsChannelConfigUpdate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_channel_config_cannot_change_channel_enabled_state():
    with pytest.raises(ValidationError):
        LogisticsChannelConfigUpdate(enabled=False)


# 功能：验证 `test_channel_wechat_config_does_not_accept_backend_credentials` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`LogisticsChannelConfigUpdate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_channel_wechat_config_does_not_accept_backend_credentials():
    with pytest.raises(ValidationError):
        LogisticsChannelConfigUpdate(
            alarm={"wechat": {"enabled": True, "user": "operator", "corp_id": "secret"}}
        )


# 功能：验证 `test_channel_config_rejects_aware_times_without_type_error` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`LogisticsChannelConfigUpdate`、`time`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_channel_config_rejects_aware_times_without_type_error():
    with pytest.raises(ValidationError):
        LogisticsChannelConfigUpdate(
            detection_start=time(8, 0, tzinfo=timezone.utc),
            detection_end=time(20, 0),
        )


# 功能：验证 `test_enabled_horn_requires_positive_device_and_event_ids` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`LogisticsChannelAlarm`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_enabled_horn_requires_positive_device_and_event_ids():
    with pytest.raises(ValidationError):
        LogisticsChannelAlarm(horn={"enabled": True})
    with pytest.raises(ValidationError):
        LogisticsChannelAlarm(horn={"enabled": False, "horn_id": 0})


# 功能：验证 `test_sqlite_fixture_enforces_camera_delete_member_cascade` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service_db.service.create_channel`、`_seed_camera`、`service_db.service.add_existing_camera`、`service_db.factory.begin`、`session.delete`、`session.get`、`service_db.factory`、`session.query(LogisticsChannelCamera).filter_by(camera_id=camera_id).count`、`session.query(LogisticsChannelCamera).filter_by`、`session.query`。
# 副作用/注意事项：可能读取或修改数据库事务。
def test_sqlite_fixture_enforces_camera_delete_member_cascade(service_db):
    channel = service_db.service.create_channel(BASE_FEATURE, "级联测试")
    camera_id = _seed_camera(service_db, "cascade-camera")
    service_db.service.add_existing_camera(BASE_FEATURE, channel["id"], camera_id)

    with service_db.factory.begin() as session:
        session.delete(session.get(AiCameraConfig, camera_id))

    with service_db.factory() as session:
        assert session.query(LogisticsChannelCamera).filter_by(camera_id=camera_id).count() == 0


# 功能：验证 `test_channel_orm_constraints_foreign_keys_and_relationships` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`next`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_channel_orm_constraints_foreign_keys_and_relationships():
    channel_constraints = {constraint.name for constraint in LogisticsChannel.__table__.constraints}
    member_constraints = {constraint.name for constraint in LogisticsChannelCamera.__table__.constraints}
    camera_fk = next(fk for fk in LogisticsChannelCamera.__table__.foreign_keys if fk.column.table.name == "ai_camera_config")
    channel_fk = next(fk for fk in LogisticsChannelCamera.__table__.foreign_keys if fk.column.table.name == "ai_logistics_channel")

    assert "uq_logistics_channel_feature_name" in channel_constraints
    assert "uq_logistics_channel_camera" in member_constraints
    assert camera_fk.ondelete == "CASCADE"
    assert channel_fk.ondelete == "CASCADE"
    assert LogisticsChannel.cameras.property.cascade.delete_orphan
    assert LogisticsChannel.cameras.property.passive_deletes is True


# 功能：验证 `test_detail_response_adapts_orm_flat_fields_and_camera_relationship` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`LogisticsChannel`、`time`、`LogisticsChannelCamera`、`LogisticsChannelDetailResponse.model_validate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_detail_response_adapts_orm_flat_fields_and_camera_relationship():
    channel = LogisticsChannel(
        id=1,
        name="收货通道",
        feature_name="detect_logistics_single_person",
        enabled=True,
        sort_order=2,
        detection_start=time(8, 0),
        detection_end=time(20, 0),
        confidence_threshold=0.42,
        empty_grace_seconds=2.0,
        multi_grace_seconds=1.0,
        alarm_interval=5.0,
        sql_enable=True,
        horn_enable=True,
        horn_id=3,
        horn_event_id=4,
        wechat_enable=True,
        wechat_user="operator",
    )
    channel.cameras = [LogisticsChannelCamera(id=7, channel_id=1, camera_id=9, enabled=True, sort_order=0)]

    response = LogisticsChannelDetailResponse.model_validate(channel)

    assert response.config.confidence_threshold == 0.42
    assert response.config.alarm.horn.horn_id == 3
    assert response.config.alarm.wechat.user == "operator"
    assert response.members[0].camera_id == 9
