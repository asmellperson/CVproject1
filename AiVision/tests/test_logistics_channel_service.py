from AiVision.departments.department_registry import DEPARTMENT_SPECS
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

from AiVision.core.db import Base
from AiVision.features.registry import all_specs
from AiVision.alarms.devices.orm import AiHornConfig
from AiVision.cameras.orm import AiCameraConfig
from AiVision.cameras.config_manager import CameraConfigManager
from AiVision.features._shared.config_manager import FeatureConfigManager
from AiVision.features.logistics_channel.constants import (
    LOGISTICS_FEATURES,
    MAX_CAMERAS_PER_CHANNEL,
    require_logistics_feature,
)
from AiVision.features.logistics_channel.orm import LogisticsChannel, LogisticsChannelCamera
from AiVision.features.logistics_channel.service import LogisticsChannelService
import AiVision.features.logistics_channel.membership_transaction as transaction_module
from AiVision.features.logistics_channel.schema import (
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
    assert importlib.util.find_spec("AiVision.features.logistics_channel.service") is not None


def test_logistics_spec_owns_registration_and_package_is_inert():
    import AiVision.features.logistics_channel as package

    from AiVision.features.logistics_channel.spec import SPEC

    assert SPEC is all_specs()[BASE_FEATURE]
    assert "SPEC" not in vars(package)
    assert "LogisticsChannelService" not in vars(package)
    assert "logistics_channel_service" not in vars(package)
    assert "__getattr__" not in vars(package)


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
    import AiVision.cameras.config_manager as camera_config_manager_module
    import AiVision.features.logistics_channel.service as channel_service_module

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

    monkeypatch.setattr(transaction_module, "session_scope", test_session_scope, raising=False)
    monkeypatch.setattr(channel_service_module, "get_session", factory, raising=False)
    monkeypatch.setattr(transaction_module, "session_scope", test_session_scope)
    monkeypatch.setattr(transaction_module, "get_session", factory)
    monkeypatch.setattr(camera_config_manager_module, "session_scope", test_session_scope)
    monkeypatch.setattr(camera_config_manager_module, "get_session", factory)

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
    monkeypatch.setattr(camera_config_manager_module, "config_cache", fake_cache)
    monkeypatch.setattr(camera_config_manager_module, "config_event_bus", fake_bus)

    yield SimpleNamespace(
        service=LogisticsChannelService(),
        camera_config_manager=CameraConfigManager(),
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
#         `test_create_camera_and_bind_is_atomic_uses_channel_department_and_notifies_after_commit` 调用本符号
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
#   - 内部调用：`_seed_camera`、`event.listen`、`service_db.camera_config_manager.list_cameras`、`event.remove`、`len`、`all_specs`。
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
        cameras = service_db.camera_config_manager.list_cameras()
    finally:
        event.remove(service_db.engine, "before_cursor_execute", track_selects)

    cameras_by_id = {camera["camera_id"]: camera for camera in cameras}
    assert cameras_by_id[first_id]["functions"]["detect_human"] is True
    assert cameras_by_id[first_id]["functions"]["detect_phone"] is False
    assert cameras_by_id[second_id]["functions"]["detect_phone"] is True
    assert len(select_statements) == 1 + len(all_specs())


# 功能：人员逗留不推断空归属；显式事业部优先，其他功能的既有查询规则保持不变。
# 参数：
#   - `service_db`（未显式标注）：隔离的摄像头与物流服务测试数据库
# 返回：None；通过断言验证按事业部查询结果。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（由 pytest 自动发现执行）
#   - 内部调用：`_seed_camera`、`service_db.camera_config_manager.list_cameras`、`set`。
# 副作用/注意事项：仅写入测试内存数据库，不修改生产数据。
def test_camera_list_requires_explicit_human_department_and_preserves_other_feature_visibility(service_db):
    unassigned_id = _seed_camera(
        service_db,
        "unassigned-human",
        department=None,
        enabled_features=("detect_human",),
    )
    for department in ("general_electric", "haoda_company"):
        _seed_camera(
            service_db,
            f"human-{department}",
            department=department,
            enabled_features=("detect_human",),
        )
    _seed_camera(
        service_db,
        "legacy-research",
        department=None,
        enabled_features=("detect_face",),
    )
    _seed_camera(
        service_db,
        "legacy-shared",
        department=None,
        enabled_features=("detect_phone",),
    )
    # 已有不一致记录的显式归属仍优先；列表不能根据功能重分配其事业部。
    _seed_camera(
        service_db,
        "explicit-research",
        department="research_institute",
        enabled_features=("detect_human",),
    )

    general_names = {
        camera["name"]
        for camera in service_db.camera_config_manager.list_cameras("general_electric")
    }
    research_names = {
        camera["name"]
        for camera in service_db.camera_config_manager.list_cameras("research_institute")
    }
    haoda_names = {
        camera["name"]
        for camera in service_db.camera_config_manager.list_cameras("haoda_company")
    }

    assert general_names == {"human-general_electric"}
    assert haoda_names == {"human-haoda_company"}
    assert research_names == {"explicit-research"}
    # 未归属记录仍可通过未过滤清单维护，但不会因此补填或扩大可见事业部。
    unassigned = next(
        camera for camera in service_db.camera_config_manager.list_cameras()
        if camera["camera_id"] == unassigned_id
    )
    assert unassigned["department"] is None
    assert unassigned["functions"]["detect_human"] is True
    with service_db.factory() as session:
        assert session.get(AiCameraConfig, unassigned_id).department is None


BASE_FEATURE = "detect_logistics_single_person"
EE_FEATURE = BASE_FEATURE


# 功能：验证物流摄像头清单使用固定次数批量查询，并按摄像头 ID 合并跨功能成员关系。
# 参数：
#   - `service_db`：隔离的物流通道与摄像头测试数据库
# 返回：None；通过断言验证安全字段、去重结果、成员关系和查询次数。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（由 pytest 自动发现执行）
#   - 内部调用：`_seed_camera`、`service.create_channel`、`service.add_existing_camera`、`event.listen`、`service.list_camera_inventory`、`event.remove`。
# 副作用/注意事项：只读写测试内存数据库；断言响应不包含摄像头 URL。
def test_logistics_camera_inventory_batches_and_deduplicates_memberships(service_db):
    shared_camera_id = _seed_camera(
        service_db,
        "shared-logistics-camera",
        department="general_electric",
    )
    ee_camera_id = _seed_camera(
        service_db,
        "ee-logistics-camera",
        department="electronics_electrician",
    )
    base_channel = service_db.service.create_channel(BASE_FEATURE, "通用物流通道", department="general_electric")
    ee_channel = service_db.service.create_channel(EE_FEATURE, "电子电工物流通道", department="electronics_electrician")
    service_db.service.add_existing_camera(
        BASE_FEATURE,
        base_channel["id"],
        shared_camera_id,
    )
    service_db.service.add_existing_camera(
        EE_FEATURE,
        ee_channel["id"],
        ee_camera_id,
    )
    select_statements: list[str] = []

    # 功能：记录清单读取期间的 SELECT 语句，验证 eager loading 查询次数固定。
    # 参数：
    #   - `_connection`、`_cursor`、`_parameters`、`_context`、`_many`：SQLAlchemy 事件上下文，本测试不读取
    #   - `statement`（str）：当前执行的 SQL 文本
    # 返回：None；仅在 SELECT 时追加记录。
    # 调用关系：
    #   - 调用方：SQLAlchemy `before_cursor_execute` 事件触发本函数
    #   - 内部调用：`statement.lstrip`、`str.startswith`、`select_statements.append`。
    # 副作用/注意事项：仅修改测试局部列表，不影响 SQL 执行。
    def track_selects(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(service_db.engine, "before_cursor_execute", track_selects)
    try:
        items = service_db.service.list_camera_inventory([BASE_FEATURE, EE_FEATURE])
    finally:
        event.remove(service_db.engine, "before_cursor_execute", track_selects)

    assert [item["camera_id"] for item in items] == [shared_camera_id, ee_camera_id]
    assert len(items[0]["memberships"]) == 1
    assert items[1]["department"] == "electronics_electrician"
    assert all("url" not in item for item in items)
    assert len(select_statements) == 3


# 功能：验证 `test_channel_crud_is_scoped_by_feature` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`pytest.raises`、`service.update_channel_and_config`、`time`、`service.get_channel`、`service.list_channels`、`service.delete_channel`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_channel_crud_is_scoped_by_feature(service_db):
    service = service_db.service
    created = service.create_channel(BASE_FEATURE, "收货通道", department="general_electric")
    service.create_channel(EE_FEATURE, "收货通道", department="electronics_electrician")

    with pytest.raises(ValueError, match="已存在"):
        service.create_channel(BASE_FEATURE, "收货通道", department="general_electric")

    updated = service.update_channel_and_config(
        BASE_FEATURE,
        created["id"],
        {"name": "卸货通道", "enabled": False, "sort_order": 7},
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
    assert updated["config"]["confidence_threshold"] == 0.42
    assert updated["config"]["empty_grace_seconds"] == 4.0
    assert updated["config"]["alarm"]["wechat"]["user"] == "operator"
    assert service.get_channel(BASE_FEATURE, created["id"])["id"] == created["id"]
    assert [item["name"] for item in service.list_channels(BASE_FEATURE, departments=["general_electric"])["items"]] == ["卸货通道"]
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
    created = service.create_channel(BASE_FEATURE, "原名称", department="general_electric")
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
        ("create_channel", ("通道", "general_electric")),
        ("delete_channel", (1,)),
        ("update_channel_and_config", (1, {}, {})),
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
    channel = service.create_channel(BASE_FEATURE, "九路通道", department="general_electric")
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
    first = service.create_channel(BASE_FEATURE, "一号", department="general_electric")
    second = service.create_channel(BASE_FEATURE, "二号", department="general_electric")
    other_feature = service.create_channel(EE_FEATURE, "一号", department="electronics_electrician")
    service.add_existing_camera(BASE_FEATURE, first["id"], camera_id)

    with pytest.raises(ValueError, match="已绑定"):
        service.add_existing_camera(BASE_FEATURE, second["id"], camera_id)

    with pytest.raises(ValueError, match="已绑定|department"):
        service.add_existing_camera(BASE_FEATURE, other_feature["id"], camera_id)
    with pytest.raises(ValueError, match="department"):
        service.move_camera(BASE_FEATURE, camera_id, other_feature["id"])
    assert service.get_channel(BASE_FEATURE, first["id"])["members"][0]["camera_id"] == camera_id


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
    source = service.create_channel(BASE_FEATURE, "事件来源", department="general_electric")
    target = service.create_channel(BASE_FEATURE, "事件目标", department="general_electric")

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
    source = service.create_channel(BASE_FEATURE, "锁来源", department="general_electric")
    target = service.create_channel(BASE_FEATURE, "锁目标", department="general_electric")
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

    service = service_db.service
    camera_id = _seed_camera(service_db, "discover-before-write")
    channel = service.create_channel(BASE_FEATURE, "发现先于写", department="general_electric")
    original_get_session = transaction_module.get_session
    original_scope = transaction_module.session_scope
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
        #   - 调用方：`AiVision/features/logistics_channel/membership_transaction.py` 的成员关系事务锁查询。
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

    monkeypatch.setattr(transaction_module, "get_session", tracked_get_session)
    monkeypatch.setattr(transaction_module, "session_scope", tracked_write_scope)

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
#   - 内部调用：`service.create_channel`、`transaction_module._MembershipDiscovery`、`transaction_module._DiscoveredMembership`、`monkeypatch.setattr`、`service._run_membership_transaction`、`sorted`、`tuple`、`len`、`id`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_membership_change_retries_with_new_discovery_and_channel_lock_set(service_db, monkeypatch):

    service = service_db.service
    source_one = service.create_channel(BASE_FEATURE, "重试锁集合一", department="general_electric")
    source_two = service.create_channel(BASE_FEATURE, "重试锁集合二", department="general_electric")
    target = service.create_channel(BASE_FEATURE, "重试锁集合目标", department="general_electric")
    discoveries = [
        transaction_module._MembershipDiscovery(
            members=(transaction_module._DiscoveredMembership(
                member_id=10,
                channel_id=source_one["id"],
                camera_id=7,
                feature_name=BASE_FEATURE,
            ),),
            camera_scope=(7,),
            channel_scope=(),
        ),
        transaction_module._MembershipDiscovery(
            members=(transaction_module._DiscoveredMembership(
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
    #         调用本符号；`AiVision/cameras/config_manager.py` 的 `CameraConfigManager::_run_write_transaction`
    #         调用本符号；`AiVision/features/logistics_channel/service.py` 的 `LogisticsChannelService::_run_write_transaction`
    #         调用本符号；`AiVision/features/logistics_channel/service.py` 的 `LogisticsChannelService::_run_membership_transaction` 调用本符号
    #   - 内部调用：`write_sessions.append`、`sorted`、`service._lock_channels`、`locked_channel_sets.append`、`tuple`、`len`、`transaction_module._MembershipLockSetChanged`、`list`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
    def operation(session, discovery):
        write_sessions.append(session)
        channel_ids = sorted({target["id"], *discovery.member_channel_ids})
        locked = service._lock_channels(session, channel_ids)
        locked_channel_sets.append(tuple(locked))
        if len(write_sessions) == 1:
            raise transaction_module._MembershipLockSetChanged()
        return list(locked)

    monkeypatch.setattr(transaction_module, "sleep", lambda _: None)
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

    attempts = []

    # 功能：实现 `discover` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`attempts.append`、`transaction_module._MembershipDiscovery`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def discover():
        attempts.append("discover")
        return transaction_module._MembershipDiscovery(
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
    #   - 内部调用：`transaction_module._MembershipLockSetChanged`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def always_changed(session, discovery):
        raise transaction_module._MembershipLockSetChanged()

    monkeypatch.setattr(transaction_module, "sleep", lambda _: None)
    with pytest.raises(transaction_module._MembershipLockSetChanged):
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
    channel = service.create_channel(BASE_FEATURE, "锁定行容量", department="general_electric")
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
    source = service.create_channel(BASE_FEATURE, "来源", department="general_electric")
    target = service.create_channel(BASE_FEATURE, "目标", department="general_electric")
    camera_ids = [_seed_camera(service_db, f"route-{index}") for index in range(3)]
    with service_db.factory.begin() as session:
        retained_cfg = (
            session.query(all_specs()[BASE_FEATURE].orm_class)
            .filter_by(camera_id=camera_ids[1])
            .one()
        )
        retained_cfg.roi_pos = [[0.1, 0.2], [0.3, 0.2], [0.3, 0.4]]
        retained_cfg.IOU_THR = 0.66
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
        assert cfg.roi_pos == [[0.1, 0.2], [0.3, 0.2], [0.3, 0.4]]
        assert cfg.IOU_THR == 0.66


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
    source = service.create_channel(BASE_FEATURE, "来源", department="general_electric")
    target = service.create_channel(BASE_FEATURE, "满载目标", department="general_electric")
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
    channel = service.create_channel(BASE_FEATURE, "成员启停", department="general_electric")
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
    channel = service.create_channel(BASE_FEATURE, "待删除", department="general_electric")
    camera_id = _seed_camera(service_db, "kept-camera")
    service.add_existing_camera(BASE_FEATURE, channel["id"], camera_id)

    assert service.delete_channel(BASE_FEATURE, channel["id"]) is True
    with service_db.factory() as session:
        assert session.get(AiCameraConfig, camera_id) is not None
        assert session.query(LogisticsChannelCamera).filter_by(camera_id=camera_id).count() == 0
        cfg = session.query(all_specs()[BASE_FEATURE].orm_class).filter_by(camera_id=camera_id).one()
        assert cfg.enable is False


# 功能：验证 `test_create_camera_and_bind_is_atomic_uses_channel_department_and_notifies_after_commit` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service.create_channel`、`service_db.notifications.clear`、`service.create_camera_and_bind`、`service_db.factory`、`session.get`、`all_specs().items`、`all_specs`、`session.query(spec.orm_class).filter_by(camera_id=camera_id).one`、`session.query(spec.orm_class).filter_by`、`session.query`
#          等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_create_camera_and_bind_is_atomic_uses_channel_department_and_notifies_after_commit(service_db):
    service = service_db.service
    channel = service.create_channel(BASE_FEATURE, "新相机", department="general_electric")
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
    channel = service.create_channel(BASE_FEATURE, "满载", department="general_electric")
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
    channel = service.create_channel(BASE_FEATURE, "强制回滚", department="general_electric")
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
    channel = service_db.service.create_channel(EE_FEATURE, "电子电工", department="electronics_electrician")
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
    channel = service_db.service.create_channel(BASE_FEATURE, "空部门", department="general_electric")
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


# 功能：验证 `test_camera_config_manager_create_camera_allows_missing_shm_name_and_keeps_return_contract` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`service_db.camera_config_manager.create_camera`、`set`、`all_specs`、`all`、`result['functions'].values`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_config_manager_create_camera_allows_missing_shm_name_and_keeps_return_contract(service_db):
    result = service_db.camera_config_manager.create_camera({
        "department": "general_electric",
        "name": "普通相机",
        "url": "rtsp://example/plain",
    })

    assert result["camera_id"] > 0
    assert result["id"] == f"camera_{result['camera_id']}"
    assert result["shm_name"] == result["id"]
    assert set(result["functions"]) == set(all_specs())
    assert all(enabled is False for enabled in result["functions"].values())


def test_camera_create_inserts_default_features_without_selecting_them(service_db):
    selects = []

    def track_selects(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(service_db.engine, "before_cursor_execute", track_selects)
    try:
        with service_db.factory() as session:
            camera = service_db.camera_config_manager.create_camera_record(session, {
                "department": "general_electric",
                "name": "direct-defaults", "url": "rtsp://example/defaults",
            })
            camera_id = camera.id
            session.commit()
    finally:
        event.remove(service_db.engine, "before_cursor_execute", track_selects)

    for spec in all_specs().values():
        assert not any(spec.orm_class.__tablename__ in sql for sql in selects)
        with service_db.factory() as session:
            config = session.query(spec.orm_class).filter_by(camera_id=camera_id).one()
            assert config.enable is False
    with service_db.factory() as session:
        assert session.get(AiCameraConfig, camera_id).function_config == {}


def test_camera_create_feature_unique_conflict_rolls_back_camera(service_db, monkeypatch):
    import AiVision.cameras.config_manager as module

    spec = next(iter(all_specs().values()))
    monkeypatch.setattr(module, "all_specs", lambda: {"first": spec, "duplicate": spec})
    with pytest.raises(ValueError, match="约束冲突"):
        service_db.camera_config_manager.create_camera({
        "department": "general_electric",
            "name": "feature-conflict", "url": "rtsp://example/conflict",
        })
    with service_db.factory() as session:
        assert session.query(AiCameraConfig).count() == 0
        assert session.query(spec.orm_class).count() == 0
    assert service_db.notifications == []


def test_camera_enabled_boundary_and_single_refresh(service_db):
    manager = service_db.camera_config_manager
    camera = manager.create_camera({
        "department": "general_electric",
        "name": "enabled-boundary", "url": "rtsp://example/enabled", "enable": False,
    })
    assert camera["enabled"] is True
    assert len([item for item in service_db.notifications if item[:2] == ("cache", "feature")]) == len(all_specs())

    service_db.notifications.clear()
    updated = manager.update_camera(camera["shm_name"], {"enabled": False, "enable": True})
    assert updated["enabled"] is False
    assert service_db.notifications[0] == ("cache", "camera", camera["camera_id"])
    assert len(service_db.notifications) == 2
    assert service_db.notifications[1][1].new_value["enabled"] is False
    assert manager.update_camera(camera["shm_name"], {"enable": True})["enabled"] is False


def test_ensure_feature_configs_only_fills_missing_disabled_rows(service_db):
    camera_id = _seed_camera(service_db, "ensure-defaults", enabled_features=("detect_human",))
    missing_spec = all_specs()["detect_phone"]
    with service_db.factory() as session:
        session.query(missing_spec.orm_class).filter_by(camera_id=camera_id).delete()
        session.commit()
    assert service_db.camera_config_manager.ensure_feature_configs() == 1
    assert service_db.camera_config_manager.ensure_feature_configs() == 0
    with service_db.factory() as session:
        assert session.query(missing_spec.orm_class).filter_by(camera_id=camera_id).one().enable is False
        assert session.query(all_specs()["detect_human"].orm_class).filter_by(camera_id=camera_id).one().enable is True
    with pytest.raises(TypeError):
        service_db.camera_config_manager.ensure_feature_configs(enable_all=True)


@pytest.mark.parametrize("key,expected_id", [
    ("camera_12", 5), ("warehouse", 12), ("12", 30), ("5", 5),
    ("camera_30", 30), ("  warehouse  ", 12), ("unknown", None), ("", None), ("²", None),
    (12, 12), (5, 5), (999, None),
])
def test_camera_and_feature_key_precedence_agree(service_db, key, expected_id):
    with service_db.factory() as session:
        session.add_all([
            AiCameraConfig(id=5, name="A", shm_name="camera_12", url="synthetic"),
            AiCameraConfig(id=12, name="camera_12", shm_name="warehouse", url="synthetic"),
            AiCameraConfig(id=20, name="warehouse", shm_name="twenty", url="synthetic"),
            AiCameraConfig(id=30, name="12", shm_name="thirty", url="synthetic"),
        ])
        session.commit()
        for resolve in (CameraConfigManager._get_orm_by_key, FeatureConfigManager._get_camera_by_key):
            camera = resolve(session, key)
            assert (camera.id if camera is not None else None) == expected_id


def test_camera_delete_cleans_legacy_feature_rows_before_event(service_db, monkeypatch):
    import AiVision.cameras.config_manager as camera_module
    from AiVision.core.cache import ConfigCache
    import AiVision.core.cache as cache_module

    camera_id = _seed_camera(service_db, "delete-target")
    other_id = _seed_camera(service_db, "delete-survivor")
    with service_db.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 0
    spec = next(iter(all_specs().values()))
    orphan_id = 9999
    with service_db.factory() as session:
        session.add(spec.orm_class(camera_id=orphan_id, enable=False))
        session.commit()

    cache = ConfigCache()
    monkeypatch.setattr(cache_module, "get_session", service_db.factory)
    cache.init()
    monkeypatch.setattr(camera_module, "config_cache", cache)
    monkeypatch.setattr(cache, "reload", lambda: pytest.fail("single delete must not reload all cameras"))
    events = []

    def observe(event_value):
        assert cache.get_camera_config(camera_id) is None
        assert not any(key[0] == camera_id for key in cache.get_all_function_configs())
        with service_db.factory() as session:
            assert session.get(AiCameraConfig, camera_id) is None
            for feature in all_specs().values():
                assert session.query(feature.orm_class).filter_by(camera_id=camera_id).count() == 0
        events.append(event_value)

    monkeypatch.setattr(camera_module.config_event_bus, "publish", observe)
    assert service_db.camera_config_manager.delete_camera("delete-target") is True
    assert [item.change_type for item in events] == ["camera_removed"]
    assert cache.get_camera_config(other_id) is not None
    assert cache.get_function_config(orphan_id, spec.name) is not None
    with service_db.factory() as session:
        assert session.query(spec.orm_class).filter_by(camera_id=orphan_id).count() == 1
    assert service_db.camera_config_manager.delete_camera("delete-target") is False
    assert len(events) == 1


def test_camera_delete_feature_failure_rolls_back_entire_transaction(service_db):
    camera_id = _seed_camera(service_db, "delete-rollback")
    table = list(all_specs().values())[1].orm_class.__tablename__

    def fail_delete(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("DELETE") and table in statement:
            raise RuntimeError("synthetic feature delete failure")

    event.listen(service_db.engine, "before_cursor_execute", fail_delete)
    try:
        with pytest.raises(RuntimeError, match="synthetic feature delete"):
            service_db.camera_config_manager.delete_camera("delete-rollback")
    finally:
        event.remove(service_db.engine, "before_cursor_execute", fail_delete)
    with service_db.factory() as session:
        assert session.get(AiCameraConfig, camera_id) is not None
        for spec in all_specs().values():
            assert session.query(spec.orm_class).filter_by(camera_id=camera_id).count() == 1
    assert service_db.notifications == []


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
@pytest.mark.parametrize("feature", [name for name in all_specs() if name != "detect_logistics_single_person"])
def test_create_feature_camera_enables_only_target_atomically(service_db, department, feature):
    """所有正式事业部均可创建任意普通功能摄像头，且只启用当前功能。"""
    result = service_db.camera_config_manager.create_camera_for_feature(
        feature,
        {
            "name": "人员逗留新增相机",
            "url": "rtsp://example/human",
            "fps": 7,
            "department": department,
        },
    )

    assert result["department"] == department
    assert result["functions"][feature] is True
    assert all(
        enabled is (feature_name == feature)
        for feature_name, enabled in result["functions"].items()
    )
    event_types = [
        item[1].change_type
        for item in service_db.notifications
        if item[0] == "event"
    ]
    assert event_types.count("camera_added") == 1
    assert event_types.count(f"{feature}_enabled") == 1


@pytest.mark.parametrize("department", [None, "", "unknown"])
def test_create_human_camera_rejects_missing_or_mismatched_department_without_writes(service_db, department):
    payload = {"name": "未合法选择事业部", "url": "rtsp://example/human"}
    if department is not None:
        payload["department"] = department
    message = "unknown department"
    with pytest.raises(ValueError, match=message):
        service_db.camera_config_manager.create_camera_for_feature("detect_human", payload)

    with service_db.factory() as session:
        assert session.query(AiCameraConfig).count() == 0
        for spec in all_specs().values():
            assert session.query(spec.orm_class).count() == 0
    assert service_db.notifications == []


# 功能：验证 `test_camera_config_manager_create_camera_for_feature_requires_valid_department` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`service_db.camera_config_manager.create_camera_for_feature`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_config_manager_create_camera_for_feature_requires_valid_department(service_db):
    with pytest.raises(ValueError, match="unknown department"):
        service_db.camera_config_manager.create_camera_for_feature(
            "detect_phone",
            {
                "name": "缺少事业部",
                "url": "rtsp://example/no-department",
            },
        )

    with pytest.raises(ValueError, match="unknown department"):
        service_db.camera_config_manager.create_camera_for_feature(
            "detect_face",
            {
                "name": "事业部不匹配",
                "url": "rtsp://example/wrong-department",
                "department": "unknown",
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

    original_scope = transaction_module.session_scope
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

    monkeypatch.setattr(transaction_module, "session_scope", flaky_scope)
    monkeypatch.setattr(transaction_module, "sleep", lambda _: None, raising=False)

    result = service_db.service.create_channel(BASE_FEATURE, f"重试-{error_code}", department="general_electric")

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

    original_scope = transaction_module.session_scope
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

    monkeypatch.setattr(transaction_module, "session_scope", always_deadlocked)
    monkeypatch.setattr(transaction_module, "sleep", lambda _: None, raising=False)

    with pytest.raises(OperationalError):
        service_db.service.create_channel(BASE_FEATURE, "重试耗尽", department="general_electric")
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

    original_scope = transaction_module.session_scope
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

    monkeypatch.setattr(transaction_module, "session_scope", unavailable)

    with pytest.raises(OperationalError):
        service_db.service.create_channel(BASE_FEATURE, "不重试", department="general_electric")
    assert len(attempts) == 1


# 功能：验证 `test_camera_create_retries_mysql_deadlock_with_new_session` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`service_db.camera_config_manager.create_camera`、`len`、`id`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_camera_create_retries_mysql_deadlock_with_new_session(service_db, monkeypatch):
    import AiVision.cameras.config_manager as camera_config_manager_module

    original_scope = camera_config_manager_module.session_scope
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

    monkeypatch.setattr(camera_config_manager_module, "session_scope", deadlock_once)
    monkeypatch.setattr(camera_config_manager_module, "sleep", lambda _: None)

    result = service_db.camera_config_manager.create_camera({
        "department": "general_electric",
        "name": "摄像头重试",
        "url": "rtsp://example/camera-retry",
    })

    assert result["name"] == "摄像头重试"
    assert len({id(session) for session in sessions}) == 2


# 功能：验证 `test_camera_config_manager_translates_commit_integrity_errors` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service_db`（未显式标注）：`service_db` 对应的业务输入值
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `message`（未显式标注）：用于展示、记录或发送的文本消息
#   - `expected`（未显式标注）：`expected` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`pytest.raises`、`service_db.camera_config_manager.create_camera`、`isinstance`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Duplicate entry for key 'ai_camera_config.name'", "name"),
        ("Duplicate entry for key 'ai_camera_config.shm_name'", "shm_name"),
        ("foreign key constraint fails", "数据约束冲突"),
    ],
)
def test_camera_config_manager_translates_commit_integrity_errors(
    service_db,
    monkeypatch,
    message,
    expected,
):
    import AiVision.cameras.config_manager as camera_config_manager_module

    original_scope = camera_config_manager_module.session_scope

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

    monkeypatch.setattr(camera_config_manager_module, "session_scope", integrity_failure)
    with pytest.raises(ValueError, match=expected) as raised:
        service_db.camera_config_manager.create_camera({
        "department": "general_electric",
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

    channel = service_db.service.create_channel(BASE_FEATURE, "并发绑定", department="general_electric")
    original_scope = transaction_module.session_scope

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

    monkeypatch.setattr(transaction_module, "session_scope", name_conflict)
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
    ("method", "payload", "config", "field"),
    [
        ("update_channel_and_config", {"enabled": None}, {}, "enabled"),
        ("update_channel_and_config", {"sort_order": None}, {}, "sort_order"),
        ("update_channel_and_config", {}, {"alarm_interval": None}, "alarm_interval"),
        ("update_channel_and_config", {}, {"detection_start": None}, "detection_start"),
        ("update_channel_and_config", {}, {"confidence_threshold": None}, "confidence_threshold"),
    ],
)
def test_updates_reject_explicit_none_for_not_null_fields(
    service_db,
    method,
    payload,
    config,
    field,
):
    channel = service_db.service.create_channel(BASE_FEATURE, f"非空-{method}-{field}", department="general_electric")
    with pytest.raises(ValueError, match=field):
        args = (BASE_FEATURE, channel["id"], payload)
        args += (config,)
        getattr(service_db.service, method)(*args)


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
    import AiVision.features.logistics_channel.service as channel_service_module

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
    result = service_db.service.create_channel(BASE_FEATURE, "通知失败仍保留", department="general_electric")

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
    from AiVision.core.settings import RuntimeSettings
    assert RuntimeSettings().logistics_status_stale_seconds == 5.0
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
    channel = service_db.service.create_channel(BASE_FEATURE, "级联测试", department="general_electric")
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

    assert "uq_logistics_channel_feature_department_name" in channel_constraints
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
     department="general_electric")
    channel.cameras = [LogisticsChannelCamera(id=7, channel_id=1, camera_id=9, enabled=True, sort_order=0)]

    response = LogisticsChannelDetailResponse.model_validate(channel)

    assert response.config.confidence_threshold == 0.42
    assert response.config.alarm.horn.horn_id == 3
    assert response.config.alarm.wechat.user == "operator"
    assert response.members[0].camera_id == 9


@pytest.mark.parametrize("department", ["unknown", "all", " general_electric"])
def test_camera_api_rejects_unregistered_department_without_writes(service_db, department):
    from fastapi import HTTPException
    from AiVision.api.routes.cameras import CameraCreateRequest, CameraUpdateRequest, create_camera, patch_camera

    manager = service_db.camera_config_manager
    with pytest.raises(HTTPException) as error:
        create_camera(
            CameraCreateRequest(name="invalid", url="rtsp://example/invalid", shm_name="invalid", department=department),
            _user={"role": "admin"}, camera_config_manager=manager,
        )
    assert error.value.status_code == 400
    with service_db.factory() as session:
        assert session.query(AiCameraConfig).count() == 0
    camera_id = _seed_camera(service_db, "existing")
    service_db.notifications.clear()
    with pytest.raises(HTTPException) as error:
        patch_camera(
            str(camera_id), CameraUpdateRequest(department=department),
            _user={"role": "admin"}, camera_config_manager=manager,
        )
    assert error.value.status_code == 400
    with service_db.factory() as session:
        assert session.get(AiCameraConfig, camera_id).department == "general_electric"
    assert service_db.notifications == []


def test_camera_create_and_update_can_select_every_registered_department(service_db):
    from AiVision.departments.department_registry import DEPARTMENT_SPECS

    manager = service_db.camera_config_manager
    for index, department in enumerate(DEPARTMENT_SPECS):
        camera = manager.create_camera({
            "name": f"registered-{index}", "url": "rtsp://example/camera", "department": department,
        })
        assert camera["department"] == department
        updated = manager.update_camera(camera["shm_name"], {"department": "research_institute"})
        assert updated["department"] == "research_institute"


def test_camera_without_department_is_not_visible_regardless_of_enabled_features(service_db):
    from AiVision.cameras.config_manager import camera_access_departments
    manager = service_db.camera_config_manager
    camera = manager.create_camera({"department": "general_electric", "name": "unassigned", "url": "rtsp://example/unassigned"})
    with service_db.factory.begin() as session:
        session.get(AiCameraConfig, camera["camera_id"]).department = None
        for spec in all_specs().values():
            session.query(spec.orm_class).filter_by(camera_id=camera["camera_id"]).one().enable = True
    assert camera_access_departments(manager.get_camera(camera["shm_name"])) == set()
    for department in DEPARTMENT_SPECS:
        assert manager.list_cameras(department) == []


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
def test_bound_camera_department_cannot_change_until_unbound(service_db, department):
    service = service_db.service
    manager = service_db.camera_config_manager
    target_department = "fulida_company" if department != "fulida_company" else "general_electric"
    camera_id = _seed_camera(service_db, "bound", department=department)
    channel = service.create_channel(BASE_FEATURE, "绑定归属", department)
    service.add_existing_camera(BASE_FEATURE, channel["id"], camera_id)
    assert manager.update_camera(str(camera_id), {"department": department})["department"] == department
    service_db.notifications.clear()
    with pytest.raises(ValueError, match="摄像头已绑定物流通道，请先解除物流通道绑定后再修改事业部"):
        manager.update_camera(str(camera_id), {"department": target_department, "name": "禁止部分写入"})
    assert manager.get_camera(camera_id)["name"] == "bound"
    assert manager.get_camera(camera_id)["department"] == department
    assert service_db.notifications == []
    assert service.get_channel(BASE_FEATURE, channel["id"])["members"][0]["camera_id"] == camera_id
    service.remove_camera(BASE_FEATURE, channel["id"], camera_id)
    assert manager.update_camera(str(camera_id), {"department": target_department})["department"] == target_department
    with pytest.raises(ValueError, match="事业部"):
        service.add_existing_camera(BASE_FEATURE, channel["id"], camera_id)
    target = service.create_channel(BASE_FEATURE, "新归属", target_department)
    service.add_existing_camera(BASE_FEATURE, target["id"], camera_id)


def test_department_change_reads_membership_under_camera_write_lock(service_db, monkeypatch):
    from sqlalchemy.orm import Session

    camera_id = _seed_camera(service_db, "locked")
    channel = service_db.service.create_channel(BASE_FEATURE, "并发绑定", "general_electric")
    original_refresh = Session.refresh
    original_execute = Session.execute
    observations = []

    def refresh(session, instance, *args, **kwargs):
        original_refresh(session, instance, *args, **kwargs)
        if isinstance(instance, AiCameraConfig) and kwargs.get("with_for_update"):
            observations.append("camera_locked")
            # 模拟取得摄像头锁前已提交的绑定，后续必须以当前读拒绝改归属。
            session.add(LogisticsChannelCamera(channel_id=channel["id"], camera_id=camera_id))
            session.flush()

    def execute(session, statement, *args, **kwargs):
        if "logistics_channel_camera" in str(statement) and getattr(statement, "_for_update_arg", None) is not None:
            assert session.in_transaction()
            assert observations == ["camera_locked"]
            observations.append("membership_locked")
        return original_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", refresh)
    monkeypatch.setattr(Session, "execute", execute)
    with pytest.raises(ValueError, match="先解除物流通道绑定"):
        service_db.camera_config_manager.update_camera(str(camera_id), {"department": "fulida_company"})
    assert observations == ["camera_locked", "membership_locked"]
    assert service_db.camera_config_manager.get_camera(camera_id)["department"] == "general_electric"
