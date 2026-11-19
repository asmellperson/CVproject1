"""授权查询期限独立于数据库快照的授权有效期。"""

from threading import Event
from types import SimpleNamespace

import pytest

from AiVision.features._shared import authorization_refresh
from AiVision.features._shared.authorization_refresh import AuthorizationRefresh


@pytest.fixture
def refresh(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(authorization_refresh, "time", SimpleNamespace(monotonic=lambda: clock.now))
    return AuthorizationRefresh("authorization-test", snapshot_seconds=2.0), clock


def test_slow_thread_start_leaves_time_for_fresh_sql_read(refresh, monkeypatch):
    refresh, clock = refresh
    queued, start = Event(), Event()
    enqueue = refresh._worker.jobs.put_nowait

    def delayed_enqueue(run):
        def wait_for_scheduler():
            queued.set()
            assert start.wait(1)
            run()

        enqueue(wait_for_scheduler)

    def query(mark):
        mark()
        return {1: {123}}

    monkeypatch.setattr(refresh._worker.jobs, "put_nowait", delayed_enqueue)
    assert refresh.submit((1,), query)
    task = refresh._lookup
    try:
        assert queued.wait(1)
        clock.now = 103.0
        assert refresh.poll() is None
    finally:
        start.set()
        task.future.result(timeout=1)
    result = refresh.poll()
    assert result.sampled_at == 103.0 and result.value == {1: {123}}
    assert refresh.poll() is None


def test_sql_read_before_deadline_can_be_delivered_after_connection_cleanup(refresh):
    refresh, clock = refresh
    read, close = Event(), Event()

    def query(mark):
        clock.now = 107.5
        mark()
        read.set()
        assert close.wait(1)
        return {1: {123}}

    assert refresh.submit((1,), query)
    task = refresh._lookup
    try:
        assert read.wait(1)
        clock.now = 108.5
        assert refresh.poll() is None
    finally:
        close.set()
        task.future.result(timeout=1)
    result = refresh.poll()
    assert result.sampled_at == 107.5 and result.completed_at == 108.5
    assert result.value == {1: {123}}


def test_completed_query_cannot_renew_already_expired_authorization(refresh):
    refresh, clock = refresh

    def query(mark):
        mark()
        return {1: {123}}

    assert refresh.submit((1,), query)
    refresh._lookup.future.result(timeout=1)
    clock.now = 102.0
    result = refresh.poll()
    assert result.error == "ExpiredSnapshot" and result.value is None


@pytest.mark.parametrize("observed_before_completion", [True, False])
def test_late_read_is_discarded_even_with_no_early_timeout_poll(refresh, observed_before_completion):
    refresh, clock = refresh
    running, late_read = Event(), Event()

    def query(mark):
        running.set()
        assert late_read.wait(1)
        mark()
        return {1: {123}}

    assert refresh.submit((1,), query)
    task = refresh._lookup
    try:
        assert running.wait(1)
        clock.now = 108.1
        if observed_before_completion:
            failure = refresh.poll()
            assert failure.error == "TimeoutError" and failure.value is None
            assert not refresh.submit((1,), query)
    finally:
        late_read.set()
        task.future.result(timeout=1)
    result = refresh.poll()
    if observed_before_completion:
        assert result is None
    else:
        assert result.error == "TimeoutError" and result.value is None
