from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from AiVision.api import models as models_api


def _methods_for_path(router, path: str) -> set[str]:
    return {
        method
        for route in router.routes
        if route.path == path
        for method in route.methods
    }


def test_model_update_routes_only_expose_patch():
    assert _methods_for_path(models_api.router, "/api/models/{model_id}") == {
        "GET",
        "PATCH",
    }


def test_patch_handlers_keep_partial_update_contract():
    calls = []
    service = SimpleNamespace(
        update_model=lambda model_id, payload: calls.append((model_id, payload))
        or {"id": model_id, **payload},
    )

    payload = models_api.ModelUpdateRequest(path="models/new.pt")
    assert models_api.patch_model(7, payload, _user={}, model_config_manager=service) == {
        "id": 7,
        "path": "models/new.pt",
    }
    assert calls == [(7, {"path": "models/new.pt"})]


def test_patch_handlers_keep_not_found_contract():
    service = SimpleNamespace(update_model=lambda _model_id, _payload: None)
    with pytest.raises(HTTPException) as exc_info:
        models_api.patch_model(
            7,
            models_api.ModelUpdateRequest(path="missing.pt"),
            _user={},
            model_config_manager=service,
        )
    assert exc_info.value.status_code == 404
