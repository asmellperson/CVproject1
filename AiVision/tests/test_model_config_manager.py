from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from AiVision.platform.inference import config_manager as config_manager_module
from AiVision.platform.inference.config_manager import (
    LEGACY_YOLO_DETECTOR_WORKER,
    YOLO_DETECTOR_WORKER,
    ModelConfigManager,
)
from AiVision.platform.inference.orm import AiModel


def _model(name: str, import_path: str, *, enable: bool = True) -> AiModel:
    return AiModel(
        name=name,
        type="yolo",
        path=f"/models/{name}.pt",
        import_path=import_path,
        enable=enable,
    )


def test_normalize_builtin_models_migrates_legacy_worker_paths(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    AiModel.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def test_session_scope():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(config_manager_module, "session_scope", test_session_scope)

    with test_session_scope() as session:
        session.add_all(
            [
                _model("yolo_human", LEGACY_YOLO_DETECTOR_WORKER),
                _model("yolo_phone", LEGACY_YOLO_DETECTOR_WORKER),
                _model("yolo_face", LEGACY_YOLO_DETECTOR_WORKER, enable=False),
                _model("custom_yolo", LEGACY_YOLO_DETECTOR_WORKER),
            ]
        )

    assert ModelConfigManager().normalize_builtin_models() == 4
    assert ModelConfigManager().normalize_builtin_models() == 0

    with test_session_scope() as session:
        models = {model.name: model for model in session.query(AiModel).all()}
        assert models["yolo_human"].import_path == YOLO_DETECTOR_WORKER
        assert models["yolo_phone"].import_path == YOLO_DETECTOR_WORKER
        assert models["yolo_face"].import_path == YOLO_DETECTOR_WORKER
        assert models["yolo_face"].enable is True
        assert models["custom_yolo"].import_path == LEGACY_YOLO_DETECTOR_WORKER


def test_normalize_builtin_models_preserves_custom_human_and_phone_workers(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    AiModel.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def test_session_scope():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(config_manager_module, "session_scope", test_session_scope)

    with test_session_scope() as session:
        session.add_all(
            [
                _model("yolo_human", "site.workers.CustomHumanWorker"),
                _model("yolo_phone", "site.workers.CustomPhoneWorker"),
            ]
        )

    assert ModelConfigManager().normalize_builtin_models() == 0

    with test_session_scope() as session:
        models = {model.name: model for model in session.query(AiModel).all()}
        assert models["yolo_human"].import_path == "site.workers.CustomHumanWorker"
        assert models["yolo_phone"].import_path == "site.workers.CustomPhoneWorker"
