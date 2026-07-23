import importlib
import sys
from types import SimpleNamespace


sys.modules.pop("platform", None)
orchestrator_module = importlib.import_module("platform.orchestrator")
Orchestrator = orchestrator_module.Orchestrator


def _orchestrator(
    monkeypatch,
    *,
    raw,
    raw_updated_at,
    annotated,
    annotated_updated_at,
):
    instance = object.__new__(Orchestrator)
    instance.consumers = {
        "detect_logistics_single_person": SimpleNamespace(
            result_dict={"logistics": annotated} if annotated is not None else {},
            result_updated_at={"logistics": annotated_updated_at} if annotated is not None else {},
        )
    }
    monkeypatch.setattr(
        orchestrator_module.frame_reader_registry,
        "latest_frames",
        {"logistics": raw} if raw is not None else {},
    )
    monkeypatch.setattr(
        orchestrator_module.frame_reader_registry,
        "latest_frame_times",
        {"logistics": raw_updated_at} if raw_updated_at else {},
    )
    return instance


def test_missing_raw_frame_does_not_return_expired_annotated_frame(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    annotated = object()
    instance = _orchestrator(
        monkeypatch,
        raw=None,
        raw_updated_at=0.0,
        annotated=annotated,
        annotated_updated_at=90.0,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (None, 90.0)


def test_fresh_annotated_frame_is_preferred(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    raw, annotated = object(), object()
    instance = _orchestrator(
        monkeypatch,
        raw=raw,
        raw_updated_at=99.0,
        annotated=annotated,
        annotated_updated_at=99.5,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (annotated, 99.5)


def test_expired_annotated_frame_falls_back_to_fresh_raw(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    raw, annotated = object(), object()
    instance = _orchestrator(
        monkeypatch,
        raw=raw,
        raw_updated_at=99.0,
        annotated=annotated,
        annotated_updated_at=90.0,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (raw, 99.0)


def test_all_expired_frames_return_latest_known_timestamp(monkeypatch):
    monkeypatch.setattr(orchestrator_module.time, "time", lambda: 100.0)
    instance = _orchestrator(
        monkeypatch,
        raw=object(),
        raw_updated_at=80.0,
        annotated=object(),
        annotated_updated_at=90.0,
    )

    assert instance.get_camera_frame_info(
        "logistics", feature="detect_logistics_single_person"
    ) == (None, 90.0)
