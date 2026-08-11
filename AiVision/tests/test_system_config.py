import pytest

from core.system_config import SystemConfigService


def test_exception_alert_defaults_to_one_hour_repeat_interval(monkeypatch):
    service = SystemConfigService()
    monkeypatch.setattr(service, "_get_value", lambda _key: None)

    assert service.get_exception_alert() == {
        "wechat_enable": False,
        "wechat_user": "",
        "repeat_interval_minutes": 60,
    }


def test_exception_alert_saves_repeat_interval(monkeypatch):
    service = SystemConfigService()
    saved = []
    monkeypatch.setattr(service, "_set_value", lambda key, value: saved.append((key, value)))

    result = service.save_exception_alert(
        {
            "wechat_enable": True,
            "wechat_user": " operator ",
            "repeat_interval_minutes": 120,
        }
    )

    assert result["repeat_interval_minutes"] == 120
    assert saved == [(service.EXCEPTION_ALERT_KEY, result)]


@pytest.mark.parametrize("value", [0, 4, 1441, "invalid"])
def test_exception_alert_rejects_invalid_repeat_interval(monkeypatch, value):
    service = SystemConfigService()
    monkeypatch.setattr(service, "_set_value", lambda *_args: None)

    with pytest.raises(ValueError, match="repeat_interval_minutes"):
        service.save_exception_alert(
            {
                "wechat_enable": False,
                "wechat_user": "",
                "repeat_interval_minutes": value,
            }
        )


def test_feature_runtime_states_default_to_enabled(monkeypatch):
    service = SystemConfigService()
    monkeypatch.setattr(service, "_get_value", lambda _key: None)

    assert service.get_feature_runtime_states(["blocks", "detect_face"]) == {
        "blocks": True,
        "detect_face": True,
    }


def test_feature_runtime_state_preserves_other_features(monkeypatch):
    service = SystemConfigService()
    saved = []
    monkeypatch.setattr(
        service,
        "_get_value",
        lambda _key: {"blocks": False, "detect_face": True},
    )
    monkeypatch.setattr(service, "_set_value", lambda key, value: saved.append((key, value)))

    assert service.save_feature_runtime_state("detect_human", False) is False
    assert saved == [
        (
            service.FEATURE_RUNTIME_KEY,
            {"blocks": False, "detect_face": True, "detect_human": False},
        )
    ]
