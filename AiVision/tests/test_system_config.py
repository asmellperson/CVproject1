# 文件说明：包含配置的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import pytest

from core.system_config import SystemConfigService


# 功能：验证 `test_exception_alert_defaults_to_one_hour_repeat_interval` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`SystemConfigService`、`monkeypatch.setattr`、`service.get_exception_alert`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_exception_alert_defaults_to_one_hour_repeat_interval(monkeypatch):
    service = SystemConfigService()
    monkeypatch.setattr(service, "_get_value", lambda _key: None)

    assert service.get_exception_alert() == {
        "wechat_enable": False,
        "wechat_user": "",
        "repeat_interval_minutes": 60,
    }


# 功能：验证 `test_exception_alert_saves_repeat_interval` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`SystemConfigService`、`monkeypatch.setattr`、`saved.append`、`service.save_exception_alert`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：验证 `test_exception_alert_rejects_invalid_repeat_interval` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `value`（未显式标注）：待转换、校验或写入的值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`SystemConfigService`、`monkeypatch.setattr`、`pytest.raises`、`service.save_exception_alert`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：验证 `test_feature_runtime_states_default_to_enabled` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`SystemConfigService`、`monkeypatch.setattr`、`service.get_feature_runtime_states`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_feature_runtime_states_default_to_enabled(monkeypatch):
    service = SystemConfigService()
    monkeypatch.setattr(service, "_get_value", lambda _key: None)

    assert service.get_feature_runtime_states(["blocks", "detect_face"]) == {
        "blocks": True,
        "detect_face": True,
    }


# 功能：验证 `test_feature_runtime_state_preserves_other_features` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`SystemConfigService`、`monkeypatch.setattr`、`saved.append`、`service.save_feature_runtime_state`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
