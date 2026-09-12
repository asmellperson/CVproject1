"""人员同步的事务、分页完整性与环境配置测试，使用内存数据库和虚构人员。"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from AiVision.connectors.hikvision import HikvisionError, HikvisionPerson, HikvisionPersons, PersonPage
from AiVision.core import db
from AiVision.platform.face_library import service, sync
from AiVision.platform.face_library.orm import FacePerson
from AiVision.platform.face_library.service import FaceLibraryService, SyncCounts


def person(person_id="person-a", **values):
    return HikvisionPerson.model_validate({"personId": person_id, **values})


def page(number, total, persons, size=1):
    return PersonPage(pageNo=number, pageSize=size, total=total, list=persons)


def remote(*pages):
    api = Mock(spec=HikvisionPersons)
    api.list_persons.side_effect = pages
    return api


@pytest.fixture
def library(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    FacePerson.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db, "get_session", factory)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(service, "get_session", factory)
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def collect_statements(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    yield SimpleNamespace(service=FaceLibraryService(), factory=factory, engine=engine, statements=statements)
    engine.dispose()


def test_same_id_is_independent_between_sources_and_unique_within_source(library):
    for source in ("one", "two"):
        assert library.service.apply_snapshot(source, [person()]).inserted == 1
    first = library.service.get_person("one", "person-a")
    second = library.service.get_person("two", "person-a")
    assert first.id != second.id
    with pytest.raises(IntegrityError), library.factory.begin() as session:
        session.add(FacePerson(hik_source="one", hik_person_id="person-a", last_synced_at=datetime.now()))


def test_insert_preserves_independent_codes_and_raw_picture_fields(library):
    uri = "/pic?opaque=abc*def+ghi%2F&raw=value"
    counts = library.service.apply_snapshot("one", [person(
        personName="测试人员", personCode="person-code", jobNo="job-number", orgIndexCode="org-code",
        personPhoto={"picUri": uri, "serverIndexCode": "image-server"},
    )])
    assert counts == SyncCounts(total=1, inserted=1)
    stored = library.service.get_person("one", "person-a")
    assert stored.person_name == "测试人员"
    assert stored.person_code == "person-code"
    assert stored.job_no == "job-number"
    assert stored.org_index_code == "org-code"
    assert stored.pic_uri == uri
    assert stored.server_index_code == "image-server"
    assert stored.is_active is True
    assert all(value is not None for value in (stored.created_at, stored.updated_at, stored.last_synced_at))


@pytest.mark.parametrize("values, field, expected", [
    ({"personName": "修改姓名"}, "person_name", "修改姓名"),
    ({"personCode": "code"}, "person_code", "code"),
    ({"jobNo": "job"}, "job_no", "job"),
    ({"orgIndexCode": "org"}, "org_index_code", "org"),
    ({"personPhoto": {"picUri": "/pic?raw=data"}}, "pic_uri", "/pic?raw=data"),
    ({"personPhoto": {"serverIndexCode": "server"}}, "server_index_code", "server"),
])
def test_changed_field_updates_existing_person(library, values, field, expected):
    library.service.apply_snapshot("one", [person()])
    initial = library.service.get_person("one", "person-a")
    assert library.service.apply_snapshot("one", [person(**values)]) == SyncCounts(total=1, updated=1)
    stored = library.service.get_person("one", "person-a")
    assert getattr(stored, field) == expected
    assert stored.id == initial.id
    assert stored.created_at == initial.created_at


def test_identical_snapshot_emits_no_updates_and_keeps_timestamps(library):
    people = [person(personCode="code", jobNo="job", personPhoto={"picUri": "/pic?raw=data"})]
    library.service.apply_snapshot("one", people)
    timestamp = datetime(2020, 1, 1)
    with library.factory.begin() as session:
        stored = session.query(FacePerson).one()
        stored.created_at = stored.updated_at = stored.last_synced_at = timestamp
    library.statements.clear()
    assert library.service.apply_snapshot("one", people) == SyncCounts(total=1, unchanged=1)
    assert not any(sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for sql in library.statements)
    stored = library.service.get_person("one", "person-a")
    assert stored.created_at == stored.updated_at == stored.last_synced_at == timestamp


def test_missing_person_is_deactivated_only_for_completed_source(library):
    library.service.apply_snapshot("one", [person(), person("person-b")])
    library.service.apply_snapshot("two", [person("person-b")])
    counts = sync.sync_source("one", remote(page(1, 1, [person()])), library.service, page_size=1)
    assert counts == SyncCounts(total=1, unchanged=1, deactivated=1)
    assert library.service.get_person("one", "person-a").is_active is True
    assert library.service.get_person("one", "person-b").is_active is False
    assert library.service.get_person("two", "person-b").is_active is True
    assert len(library.service.list_persons("one", is_active=False)) == 1
    assert library.service.apply_snapshot("one", [person()]).deactivated == 0
    assert library.service.apply_snapshot("one", [person(), person("person-b")]).updated == 1
    assert library.service.get_person("one", "person-b").is_active is True


@pytest.mark.parametrize("source", ["one", "two"])
def test_empty_snapshot_with_active_person_is_rejected_without_writes(library, source):
    library.service.apply_snapshot(source, [person(personName="保持姓名"), person("inactive")])
    timestamp = datetime(2020, 1, 1)
    with library.factory.begin() as session:
        for stored in session.query(FacePerson).all():
            stored.is_active = stored.hik_person_id != "inactive"
            stored.created_at = stored.updated_at = stored.last_synced_at = timestamp
    before = [
        {column.name: getattr(stored, column.name) for column in FacePerson.__table__.columns}
        for stored in library.service.list_persons(source)
    ]
    library.statements.clear()
    with pytest.raises(sync.PersonSyncError, match="完整分页总数为 0"):
        sync.sync_source(source, remote(page(1, 0, [])), library.service, page_size=1)
    assert not any(sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for sql in library.statements)
    after = [
        {column.name: getattr(stored, column.name) for column in FacePerson.__table__.columns}
        for stored in library.service.list_persons(source)
    ]
    assert after == before


def test_service_rejects_empty_snapshot_with_active_person(library):
    library.service.apply_snapshot("one", [person()])
    with pytest.raises(sync.PersonSyncError):
        library.service.apply_snapshot("one", [])
    assert library.service.get_person("one", "person-a").is_active is True


@pytest.mark.parametrize("source, other_source", [("one", "two"), ("two", "one")])
def test_first_empty_sync_succeeds_even_if_other_source_has_active_people(library, source, other_source):
    library.service.apply_snapshot(other_source, [person()])
    library.statements.clear()
    assert sync.sync_source(source, remote(page(1, 0, [])), library.service, page_size=1) == SyncCounts(total=0)
    assert not any(sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for sql in library.statements)
    assert library.service.list_persons(source) == []
    assert library.service.get_person(other_source, "person-a").is_active is True


def test_empty_snapshot_with_only_inactive_people_keeps_them_unchanged(library):
    library.service.apply_snapshot("one", [person()])
    timestamp = datetime(2020, 1, 1)
    with library.factory.begin() as session:
        stored = session.query(FacePerson).one()
        stored.is_active = False
        stored.created_at = stored.updated_at = stored.last_synced_at = timestamp
    library.statements.clear()
    assert sync.sync_source("one", remote(page(1, 0, [])), library.service, page_size=1) == SyncCounts(total=0)
    assert not any(sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for sql in library.statements)
    stored = library.service.get_person("one", "person-a")
    assert stored.is_active is False
    assert stored.created_at == stored.updated_at == stored.last_synced_at == timestamp


def test_fetches_every_page_before_any_database_operation(library):
    library.statements.clear()
    api = remote(page(1, 2, [person()]), page(2, 2, [person("person-b")]))
    pages = api.list_persons.side_effect

    def fetch(**kwargs):
        assert library.statements == []
        return next(pages)

    api.list_persons.side_effect = fetch
    assert sync.sync_source("one", api, library.service, page_size=1) == SyncCounts(total=2, inserted=2)
    assert [call.kwargs["page_no"] for call in api.list_persons.call_args_list] == [1, 2]


def test_mid_pagination_failure_does_not_change_or_deactivate_any_person(library):
    library.service.apply_snapshot("one", [person(personName="保持姓名"), person("person-b")])
    library.statements.clear()
    api = remote(page(1, 2, [person(personName="不得写入")]), HikvisionError("HTTP 503", status_code=503))
    with pytest.raises(sync.PersonSyncError, match="第 2 页失败"):
        sync.sync_source("one", api, library.service, page_size=1)
    assert library.statements == []
    assert library.service.get_person("one", "person-a").person_name == "保持姓名"
    assert all(stored.is_active for stored in library.service.list_persons("one"))


@pytest.mark.parametrize("pages", [
    [page(1, 2, [person()]), page(2, 3, [person("person-b")])],
    [page(1, 2, [person()]), page(2, 2, [])],
    [page(1, 2, [person()]), page(2, 2, [person()])],
    [page(1, 2, [person()]), page(1, 2, [person("person-b")])],
    [page(1, 2, [person()], size=2)],
])
def test_inconsistent_pagination_never_starts_database_work(library, pages):
    library.service.apply_snapshot("one", [person()])
    library.statements.clear()
    with pytest.raises(sync.PersonSyncError):
        sync.sync_source("one", remote(*pages), library.service, page_size=1)
    assert library.statements == []
    assert library.service.get_person("one", "person-a").is_active is True


def test_database_failure_rolls_back_insert_update_and_deactivation(library):
    library.service.apply_snapshot("one", [person(personName="保持姓名"), person("missing")])

    def fail_after_update(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("UPDATE"):
            raise OperationalError("update failed", {}, Exception("simulated database failure"))

    event.listen(library.engine, "after_cursor_execute", fail_after_update)
    try:
        with pytest.raises(OperationalError):
            library.service.apply_snapshot("one", [person(personName="不得写入"), person("person-b")])
    finally:
        event.remove(library.engine, "after_cursor_execute", fail_after_update)
    assert library.service.get_person("one", "person-a").person_name == "保持姓名"
    assert library.service.get_person("one", "missing").is_active is True
    assert library.service.get_person("one", "person-b") is None


@pytest.mark.parametrize("photo", [None, {}, {"picUri": None, "serverIndexCode": None}])
def test_nullable_fields_insert_and_clear_without_fabricated_values(library, photo):
    library.service.apply_snapshot("one", [person(
        personName="待清除", personCode="code", jobNo="job", orgIndexCode="org",
        personPhoto={"picUri": "/pic?raw=data", "serverIndexCode": "server"},
    )])
    assert library.service.apply_snapshot("one", [person(personPhoto=photo)]).updated == 1
    library.service.apply_snapshot("two", [person(personPhoto=photo)])
    for source in ("one", "two"):
        stored = library.service.get_person(source, "person-a")
        assert all(getattr(stored, field) is None for field in (
            "person_name", "person_code", "job_no", "org_index_code", "pic_uri", "server_index_code",
        ))


def test_duplicate_snapshot_is_rejected_before_transaction(library):
    library.statements.clear()
    with pytest.raises(ValueError, match="duplicate"):
        library.service.apply_snapshot("one", [person(), person()])
    assert library.statements == []


def configure_sources(monkeypatch):
    for source in ("ONE", "TWO"):
        monkeypatch.setenv(f"HIKVISION_{source}_BASE_URL", f"https://{source.lower()}.example")
        monkeypatch.setenv(f"HIKVISION_{source}_APP_KEY", f"test-{source}-key")
        monkeypatch.setenv(f"HIKVISION_{source}_APP_SECRET", f"test-{source}-secret")
        monkeypatch.setenv(f"HIKVISION_{source}_PAGE_SIZE", "1")
        monkeypatch.delenv(f"HIKVISION_{source}_VERIFY_TLS", raising=False)


def test_settings_read_each_source_and_tls_from_environment(monkeypatch):
    configure_sources(monkeypatch)
    for source in ("ONE", "TWO"):
        config = sync.HikvisionSyncSettings(_env_prefix=f"HIKVISION_{source}_")
        assert config.client_config().app_key == f"test-{source}-key"
        assert config.client_config().app_secret == f"test-{source}-secret"
        assert config.client_config().verify_tls is True
        assert f"test-{source}-secret" not in repr(config)
    monkeypatch.setenv("HIKVISION_ONE_VERIFY_TLS", "false")
    assert sync.HikvisionSyncSettings(_env_prefix="HIKVISION_ONE_").client_config().verify_tls is False
    assert sync.HikvisionSyncSettings(_env_prefix="HIKVISION_TWO_").client_config().verify_tls is True


@pytest.mark.parametrize("empty_result", [False, True])
def test_cli_continues_two_after_one_fails_and_reports_nonzero(library, monkeypatch, tmp_path, capsys, empty_result):
    configure_sources(monkeypatch)
    monkeypatch.setattr(sync, "_ENV_FILE", tmp_path / ".env")
    library.service.apply_snapshot("one", [person()])
    sources = []

    def api(client):
        sources.append(client.config.base_url)
        if client.config.base_url == "https://one.example":
            if empty_result:
                return remote(page(1, 0, []))
            return remote(page(1, 2, [person()]), HikvisionError("HTTP 503"))
        return remote(page(1, 1, [person()]))

    monkeypatch.setattr(sync, "HikvisionPersons", api)
    assert sync.main() == 1
    assert sources == ["https://one.example", "https://two.example"]
    assert library.service.get_person("one", "person-a").is_active is True
    assert library.service.get_person("two", "person-a").is_active is True
    output = capsys.readouterr().out
    assert "one:" in output and "失败 1" in output
    assert "two:\n总数 1\n新增 1\n更新 0\n未变化 0\n停用 0\n失败 0" in output
    assert inspect(library.engine).get_table_names() == ["ai_face_person"]


def test_database_errors_do_not_expose_sql_parameters():
    exc = OperationalError("sql with /pic?private=address", {"secret": "sensitive-value"}, Exception(2003, "private"))
    assert sync._error_summary(exc) == "OperationalError，数据库错误码 2003"


def test_successful_cli_reports_counts_without_picture_urls_or_credentials(
    library, monkeypatch, tmp_path, capsys, caplog,
):
    configure_sources(monkeypatch)
    monkeypatch.setattr(sync, "_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(sync, "HikvisionPersons", lambda client: remote(page(1, 1, [person(
        personPhoto={"picUri": "/pic?private=address"},
    )])))
    assert sync.main() == 0
    output = capsys.readouterr().out + caplog.text
    assert output.count("总数 1\n新增 1\n更新 0\n未变化 0\n停用 0\n失败 0") == 2
    assert "/pic?" not in output
    assert "test-ONE-secret" not in output
    assert "test-TWO-secret" not in output
