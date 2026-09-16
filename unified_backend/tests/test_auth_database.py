# 文件说明：包含认证授权的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations


import pytest
from starlette.requests import Request

from auth.auth import (
    AuthError,
    change_own_password,
    create_auth_user,
    create_token,
    decode_token,
    get_current_user_from_request,
    get_token_expire_hours,
    verify_login,
)


# 功能：实现 `_request_with_token` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `token`（str）：用于认证或续接请求的令牌
# 返回：Request；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_auth_database.py` 的 `test_database_user_login_and_token_version`
#         调用本符号；`unified_backend/tests/test_auth_database.py` 的 `test_version_one_token_without_auth_version_remains_compatible`
#         调用本符号
#   - 内部调用：`Request`、`f'aicv_auth_token={token}'.encode`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _request_with_token(token: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/auth/me",
            "raw_path": b"/api/auth/me",
            "query_string": b"",
            "headers": [
                (
                    b"cookie",
                    f"aicv_auth_token={token}".encode("utf-8"),
                )
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 5000),
        }
    )


# 功能：初始化或配置 `_configure_database_user` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：`unified_backend/tests/test_auth_database.py` 的 `test_database_user_login_and_token_version`
#         调用本符号；`unified_backend/tests/test_auth_database.py` 的 `test_version_one_token_without_auth_version_remains_compatible`
#         调用本符号
#   - 内部调用：`monkeypatch.setenv`、`create_auth_user`、`str`。
# 副作用/注意事项：会创建和写入临时 SQLite 用户数据库。
def _configure_database_user(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "AUTH_USERS_DB",
        str(tmp_path / "runtime" / "auth_users.db"),
    )
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret-with-at-least-32-characters")
    create_auth_user(
        employee_id="10001",
        name="管理员",
        role="admin",
        departments=["all"],
        password="database-password",
    )


# 功能：验证 `test_database_user_login_and_token_version` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_configure_database_user`、`verify_login`、`create_token`、`get_current_user_from_request`、`_request_with_token`、`change_own_password`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_database_user_login_and_token_version(monkeypatch, tmp_path):
    _configure_database_user(monkeypatch, tmp_path)

    user = verify_login("10001", "database-password")
    assert user is not None
    assert user["auth_version"] == 1
    assert user["departments"] == ["all"]
    token = create_token(user)
    assert get_current_user_from_request(_request_with_token(token))["employee_id"] == "10001"

    changed = change_own_password(
        "10001",
        "database-password",
        "new-password",
    )
    assert changed["auth_version"] == 2

    with pytest.raises(AuthError, match="登录状态已失效"):
        get_current_user_from_request(_request_with_token(token))
    assert verify_login("10001", "database-password") is None
    assert verify_login("10001", "new-password") is not None


# 功能：验证 `test_version_one_token_without_auth_version_remains_compatible` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_configure_database_user`、`verify_login`、`create_token`、`get_current_user_from_request`、`_request_with_token`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_version_one_token_without_auth_version_remains_compatible(monkeypatch, tmp_path):
    _configure_database_user(monkeypatch, tmp_path)
    user = verify_login("10001", "database-password")
    assert user is not None

    legacy_token = create_token(
        {
            "employee_id": user["employee_id"],
            "name": user["name"],
            "role": user["role"],
            "departments": user["departments"],
        }
    )

    assert "department" not in decode_token(legacy_token)
    assert get_current_user_from_request(
        _request_with_token(legacy_token)
    )["auth_version"] == 1


def test_fulida_user_login_preserves_explicit_department(monkeypatch, tmp_path):
    _configure_database_user(monkeypatch, tmp_path)
    create_auth_user(employee_id="fulida", name="福力达用户", role="viewer", departments=["fulida_company"], password="fulida-password")
    user = verify_login("fulida", "fulida-password")
    assert user["departments"] == ["fulida_company"]
    assert "department" not in user
    assert get_current_user_from_request(_request_with_token(create_token(user)))["departments"] == ["fulida_company"]



@pytest.mark.parametrize("value", ["", "0", "never", "permanent", "forever"])
def test_persistent_token_values_remain_supported(monkeypatch, value):
    monkeypatch.setenv("AUTH_TOKEN_EXPIRE_HOURS", value)
    assert get_token_expire_hours() is None


@pytest.mark.parametrize("value", ["invalid", "-1", "1.5"])
def test_invalid_token_expiry_fails_fast(monkeypatch, value):
    monkeypatch.setenv("AUTH_TOKEN_EXPIRE_HOURS", value)
    with pytest.raises(ValueError, match="AUTH_TOKEN_EXPIRE_HOURS"):
        get_token_expire_hours()


def test_positive_token_expiry_is_returned(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN_EXPIRE_HOURS", "24")
    assert get_token_expire_hours() == 24
