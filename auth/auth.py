"""后端服务共享的认证与授权模块。

这里集中维护 Guard Room 和 AiVision 共用的 JWT、Cookie、用户数据库、
登录校验和角色检查逻辑。各服务自己的 auth.py 只作为兼容入口，从这里重新导出。
登录流程：
    登录页面 -> employee_id+password -> verify_login() -> _verify_password () -> 登录成功 -> create_token() -> JWT -> set_auth_cookie() -> 浏览器保存aicv_auth_token
访问API
    浏览器自带JwT -> token_from_request() -> decode_token() -> 验证JWT -> 根据sub重新查用户数据库 -> 检查enabled -> 检查auth_version -> get_current_user() -> 进入业务API
管理员接口：
    get_current_user() -> require_admin() -> role==admin
退出：
    logout -> clear_auth_cookie() -> Cookie删除
"""
from __future__ import annotations

#JWT：Header.payload.Signature:其中Header和payload都会Python dict->json->base64编码
import base64                  
import hashlib                  # 提供哈希算法（这里主要用hashlib.sha256负责JWT签名和haslib.pbkdf2_hmac负责密码哈希）
import hmac                     # 带密钥的消息摘要
import json
import logging                  # 认证模块自己的日志记录器
import os
import threading               # 加锁，确保同一时间只有一个线程能初始化
import time                    # JWT时间
from pathlib import Path       # 用于处理用户数据库文件路径
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status    # request：浏览器发来的http请求，response：服务器返回给浏览器的响应
from pydantic import BaseModel

# 使用user_store做用户数据库CRUD
from auth.user_store import (
    UserConflictError,         
    UserNotFoundError,
    UserStore,
    UserStoreError,
    UserValidationError,
    default_database_path,
    hash_password,
)
# 浏览器登录后的Cookie名字
COOKIE_NAME = "aicv_auth_token"
JWT_ALGORITHM = "HS256"                            # 当前JWT使用HMAC-SHA256签名（这个不是加密内容，JWT主要靠Signature防止别人篡改）
DEV_AUTH_SECRET = "dev-aicv-auth-secret-change-me" # 开发环境兜底JWT密钥（如果.env没写AUTH_SECRET,就会退回这个默认值）
# 默认持久化Cookie最长可以存60秒*60（1小时）*24（一天）*365（1年）*20（20年）
PERSISTENT_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365 * 20

logger = logging.getLogger("auth.auth")             # 认证模块日志器
_warned_default_auth_secret = False                 # 这个是为了AUTH_SECRET 没配置时，警告只打印一次。
_user_store_lock = threading.Lock()
_user_store_signature: Path | None = None           # 当前_user_store 使用的是哪个数据库文件。
_user_store: UserStore | None = None                # 缓存_user_store对象

# 登录请求数据模型
class LoginRequest(BaseModel):
    employee_id: str
    password: str

# 修改密码的数据模型：和管理重置密码不一样，用户自己修改密码必须先验证旧密码，才能改新密码
class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

# 认证异常
class AuthError(Exception):
    """认证或授权失败。"""

def _b64url_encode(data: bytes) -> str:
    """把bytes编码成适合放进URL/JWT的Base64字符串(编码不是加密)"""
    # base64.urlsafe_b64encode(data):普通的Base64里面可能出现+，-等，urlsafe_b64encode会使用URL更安全的字符形式
    # Base64编码后经常有=或者==，JWT的Base64URL规范通常把结尾的=号去掉，rstrip(b"=")表示删除右边连续的等号
    # 最后转成python字符串
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _b64url_decode(data: str) -> bytes:
    """解码：
    JWT字符串->补回=->交bytes->Base64URL解码，得到原始的bytes
    """
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))

def _json_b64(data: dict[str, Any]) -> str:
    """把一个Python字典转换成JWT可以使用的Base64URL字符串
    """
    # 字典变json（json.dumps），去掉不必要的空格（separators=(",", ":")），并且确保jWT payload里出现中文用户名（ensure_ascii=False）
    return _b64url_encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

def get_auth_secret() -> str:
    """读取 JWT 签名密钥，未配置时回退到开发默认值。"""
    global _warned_default_auth_secret
    secret = os.getenv("AUTH_SECRET")
    if secret:
        return secret
    if not _warned_default_auth_secret:
        logger.warning("AUTH_SECRET is not set; using insecure development default secret.")
        _warned_default_auth_secret = True
    return DEV_AUTH_SECRET

# JWT是用户身份凭证，Cookie是浏览器保存和自动携带的JWT的容器
def get_token_expire_hours() -> int | None:
    """读取 Token 有效期小时数。

    空值、0、never、permanent 或 forever 表示 Token 不主动过期。
    账号禁用后仍会被拒绝，因为每次请求都会重新读取用户记录。
    """
    raw = os.getenv("AUTH_TOKEN_EXPIRE_HOURS", "").strip()
    if not raw or raw.lower() in {"0", "never", "permanent", "forever"}:
        return None
    try:
        hours = int(raw)
    except ValueError as exc:
        raise ValueError(
            "AUTH_TOKEN_EXPIRE_HOURS 必须是正整数，或 0/never/permanent/forever"
            f"，当前值为 {raw!r}"
        ) from exc
    if hours < 0:
        raise ValueError(
            "AUTH_TOKEN_EXPIRE_HOURS 不能为负数"
            f"，当前值为 {raw!r}"
        )
    if hours == 0:
        return None
    return hours

def get_auth_cookie_max_age_seconds() -> int:
    """觉得浏览器Cookie最长保存多久，与JWT过期时间保存一致"""
    expire_hours = get_token_expire_hours()
    if expire_hours is None:   # 如果Token不主动过期，就保存20年
        return PERSISTENT_COOKIE_MAX_AGE_SECONDS        
    return expire_hours * 3600

def get_auth_users_database_path() -> Path:
    """获取认证用户数据库文件路径，在这里：user_store.default_database_path()"""
    return default_database_path()

def get_user_store() -> UserStore:
    """获取全局共用的UserStore，如果还没有就创建一个"""
    global _user_store
    global _user_store_signature              # 当前用户数据库文件的路径，比如/xxx/auth_users.db
    signature = get_auth_users_database_path()
    # UserStore已经创建并且当前数据库路径没有变化
    if _user_store is not None and _user_store_signature == signature:
        return _user_store
    with _user_store_lock:
        # UserStore没有被创建或者数据库路径有变化
        if _user_store is None or _user_store_signature != signature:
            # 重新创建UserStore
            _user_store = UserStore(database_path=signature)
            _user_store_signature = signature
        return _user_store

def load_auth_users() -> list[dict[str, Any]]:
    """获取全部认证用户"""
    try:
        # UserStore的list_users中获取全部用户
        return get_user_store().list_users()
    except UserStoreError as exc:
        logger.error("Auth user database unavailable: %s", exc)
        raise AuthError(str(exc)) from exc

def _public_user(item: dict[str, Any]) -> dict[str, Any]:
    """把数据库里完整的用户记录，转换成认证系统允许对外使用的用户对象
    这里为什么不使用enabled：因为通常进入这里的用户已经默认是enabled，所以不太需要再带一次enabled=True
    """
    departments = item.get("departments")
    if not isinstance(departments, list):
        departments = []
    return {
        "employee_id": str(item.get("employee_id", "")).strip(),
        "name": str(item.get("name", "")),
        "role": str(item.get("role", "viewer")),
        "departments": departments,
        "auth_version": int(item.get("auth_version", 1) or 1),
    }

def _find_enabled_user_record(identifier: str) -> dict[str, Any] | None:
    """在数据库寻找一个当前启用的用户"""
    # 输入清洗
    identifier = str(identifier).strip()
    if not identifier:
        return None
    try:
        # find_enabled_user：如果用户存在enabled=False，就不允许登录
        return get_user_store().find_enabled_user(identifier)
    except UserStoreError as exc:
        logger.error("Auth user database unavailable: %s", exc)
        raise AuthError(str(exc)) from exc

def find_enabled_user(identifier: str) -> dict[str, Any] | None:
    """数据库查询启用用户，拿到完整数据库记录，经过_public_user去掉passsword_hash等内部字段，返回标准user"""
    item = _find_enabled_user_record(identifier)
    if item is None:
        return None
    return _public_user(item)

def _verify_password(password: str, stored_hash: str | None) -> bool:
    """
    判断用户输入的密码是不是正确
    思路：
        输入密码
        用相同salt和算法重新hash
        比较结果
    """
    if not isinstance(stored_hash, str) or not stored_hash:
        return False
    try:
        # 假设数据库：pbkdf2_sha256$260000$abc123$XYZ...
        # algorithm:pbkdf2_sha256,interations_raw:260000,salt:abc123,digest:XYZ
        algorithm, iterations_raw, salt, digest = stored_hash.split("$", 3)
        # 当前代码只接受这个密码哈希算法
        if algorithm != "pbkdf2_sha256":
            return False
        # 用户登录输入password，重新算一次哈希，得到expected
        expected = hash_password(
            password,
            salt=salt,
            iterations=int(iterations_raw),
        ).rsplit("$", 1)[-1]
    except (TypeError, ValueError, OverflowError):
        return False
    # 和digest比较结果，安全场景下比较密码哈希、签名，不用普通 ==，优先 compare_digest()
    return hmac.compare_digest(expected, digest)

def change_own_password(employee_id: str, current_password: str, new_password: str) -> dict[str, Any]:
    """
    用户自己修改代码
    流程：
        用户输入旧密码+新密码
        找到用户
        确认账号enabled
        验证旧密码
        校验新密码长度
        生成新的password_hash
        写数据库
        返回最新用户信息
    """
    employee_id = str(employee_id).strip()
    if len(new_password) < 6:
        raise AuthError("新密码至少需要 6 位")
    try:
        # 找完整用户记录
        item = get_user_store().get_user_record(employee_id)
        # 查找账号状态，已停用账号不能自己修改密码
        if not item.get("enabled", False):
            raise AuthError("user disabled or not allowed")
        # 验证旧密码
        if not _verify_password(current_password, item.get("password_hash")):
            raise AuthError("当前密码不正确")
        # 保存新密码
        updated = get_user_store().update_password_hash(
            employee_id,
            hash_password(new_password),
        )
        # 返回用户安全信息
        return _public_user(updated)
    except UserNotFoundError as exc:
        raise AuthError("user disabled or not allowed") from exc
    except UserStoreError as exc:
        raise AuthError(str(exc)) from exc

def create_token(user: dict[str, Any]) -> str:
    """登录成功以后，根据当前用户生成一张JWT身份认证"""
    now = int(time.time())
    # payload就是JWT里面真正携带的用户信息
    payload: dict[str, Any] = {
        "sub": user["employee_id"],                # 拿员工工号作为用户唯一身份（最重要的身份字段）
        "name": user.get("name", ""),              # 用户名     
        "role": user.get("role", "viewer"),        # 权限
        "departments": user.get("departments"),    # 部门
        "auth_version": int(user.get("auth_version", 1) or 1),  # 用户登录凭证版本号
        "iat": now,                                # 时间
    }
    expire_hours = get_token_expire_hours()
    if expire_hours is not None:
        payload["exp"] = now + expire_hours * 3600     # 不为空，过期时间就是24小时，为空不过期，也就是持久化token
    # JWT_ALGORITHM = "HS256"
    header = {"typ": "JWT", "alg": JWT_ALGORITHM}
    # header和payload经过Base64URL后就是JWT的前两段（xxxx.yyyy）
    signing_input = f"{_json_b64(header)}.{_json_b64(payload)}"
    # 输入AUTH_SECRET以及上面的JWT前两段使用HMAC-SHA256生成signature(zzzz)
    signature = hmac.new(
        get_auth_secret().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    # 最终xxxx.yyyyy.zzzzz
    return f"{signing_input}.{_b64url_encode(signature)}"

def decode_token(token: str) -> dict[str, Any]:
    """检查一个JWT是不是服务器自己签发的、有没有被修改、有没有过期、然后返回Payload"""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".", 2)
        # 重新构造前两段
        signing_input = f"{header_b64}.{payload_b64}"
        # 服务器重新计算一次签名
        expected = hmac.new(
            get_auth_secret().encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        # 将Token第三段进行Base64URL解码取出Token里的真实签名
        actual = _b64url_decode(signature_b64)
        # 比较签名
        if not hmac.compare_digest(expected, actual):
            raise AuthError("invalid token signature")
        # 解Header
        header = json.loads(_b64url_decode(header_b64))
        # 要求必须是HS256
        if header.get("alg") != JWT_ALGORITHM:
            raise AuthError("unsupported token algorithm")
        # 解Payload
        payload = json.loads(_b64url_decode(payload_b64))
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError("invalid token") from exc
    
    exp = payload.get("exp")
    if exp is not None:
        try:
            if int(exp) < int(time.time()):        # token过期时间小于当前时间，就过期
                raise AuthError("token expired")
        except (TypeError, ValueError) as exc:
            raise AuthError("invalid token") from exc
    return payload

def token_from_request(request: Request) -> str | None:
    """从当前HTTP请求中找到JWT """
    # 第一种来源是Authorization Header(一般是API，脚本调用使用)
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):    # 确认是不是Bearer Token
        return auth_header[7:].strip()               # 得到真正的JWT
    # 第二种来源是Cookie（浏览器正常登录后，大部分请求走的是cookie->aicv_auth_token）
    return request.cookies.get(COOKIE_NAME)          

def get_current_user_from_request(request: Request) -> dict[str, Any]:
    """负责拿Token->验Token->查数据库->检查账号->检查auth_version->返回当前用户"""
    # 拿Token
    token = token_from_request(request)
    if not token:
        raise AuthError("not authenticated")
    # 验JWT：decode_token内部拆三段，验签、检查算法、检查exp、返回Payload
    payload = decode_token(token)
    # 使用sub查数据库
    user = find_enabled_user(str(payload.get("sub", "")))
    if user is None:
        raise AuthError("user disabled or not allowed")
    try:
        # 从JWT拿登录时的版本
        token_auth_version = int(payload.get("auth_version", 1) or 1)
    except (TypeError, ValueError) as exc:
        raise AuthError("invalid token") from exc
    if token_auth_version != int(user.get("auth_version", 1) or 1):
        raise AuthError("登录状态已失效，请重新登录")
    # 返回数据库最新的用户对象
    return user

def get_current_user(request: Request) -> dict[str, Any]:
    """将认证层的AuthError转成FastAPI的HTTP401"""
    try:
        return get_current_user_from_request(request)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """依赖get_current_user完成认证"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin permission required")
    return user

def verify_login(employee_id: str, password: str) -> dict[str, Any] | None:
    """登录时根据工号和密码判断这个用户能不能登录"""
    # 调用_find_enabled_user_recode找enabled
    user_record = _find_enabled_user_record(employee_id)
    if user_record is None:
        return None
    # 验证密码
    if not _verify_password(password, user_record.get("password_hash")):
        return None
    # 密码正确，返回安全用户对象
    return _public_user(user_record)

def list_auth_users() -> list[dict[str, Any]]:
    """管理员查询所有认证用户"""
    return get_user_store().list_users()

def create_auth_user(
    *,
    employee_id: str,
    name: str,
    role: str,
    password: str,
    departments: list[str] | None,
) -> dict[str, Any]:
    """管理员创建新的用户"""
    if len(password) < 6:
        raise UserValidationError("初始密码至少需要 6 位")
    return get_user_store().create_user(
        employee_id=employee_id,
        name=name,
        role=role,
        password_hash=hash_password(password),
        departments=departments,
    )

def update_auth_user(
    employee_id: str,
    *,
    actor_employee_id: str,
    name: str,
    role: str,
    enabled: bool,
    departments: list[str] | None,
) -> dict[str, Any]:
    """管理员修改某个用户的基本信息、角色、部门和启用状态"""
    return get_user_store().update_user(
        employee_id,
        actor_employee_id=actor_employee_id,
        name=name,
        role=role,
        enabled=enabled,                          # 账号开关
        departments=departments,
    )

def reset_auth_user_password(
    employee_id: str,
    *,
    new_password: str,
) -> dict[str, Any]:
    """管理员重置某个用户密码，与change_own_password用户自己改密码不同，管理员重置不需要旧密码"""
    if len(new_password) < 6:
        raise UserValidationError("新密码至少需要 6 位")
    return get_user_store().update_password_hash(
        employee_id,
        hash_password(new_password),
    )

def delete_auth_user(
    employee_id: str,
    *,
    actor_employee_id: str,
) -> None:
    """管理员删除用户"""
    # 删除立即在UserStore.delete_user()
    get_user_store().delete_user(
        employee_id,
        actor_employee_id=actor_employee_id,
    )

# ------------------  下面函数判断JWT已经生成以后，怎么安全地放进浏览器，以及退出登录时怎么删除  --------------
def cookie_secure_for_request(request: Request) -> bool:
    """判读Cookie要不要设置Secure属性（Secure Cookie：浏览器只允许通过HTTPS发送这个Cookie）"""
    raw = os.getenv("AUTH_COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or "https" in {p.strip() for p in forwarded_proto.split(",")}

def set_auth_cookie(response: Response, token: str, request: Request) -> None:
    """登录成功以后，把JWT写入浏览器Cookie"""
    response.set_cookie(
        key=COOKIE_NAME,                            # COOKIE_NAME = "aicv_auth_token"
        value=token,                                # xxxx.yyyy.zzzz
        httponly=True,                              # 浏览器的JavaScript不能直接读取这个Cookie
        secure=cookie_secure_for_request(request),  # 生产HTTPS：True，本地HTTP开发：False
        samesite="lax",                             # 限制其他网站随意利用浏览器自动携带你的登录Cookie
        path="/",                                   # 表示这个Cookie对整个网站都有效
        max_age=get_auth_cookie_max_age_seconds(),  # JWT生命周期和Cookie生命周期尽量保持一致
    )

def clear_auth_cookie(response: Response, request: Request) -> None:
    """删除浏览器里的认证Cookie"""
    # 删除和创建时尽量保持一致
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=cookie_secure_for_request(request),
        samesite="lax",
    )

# 当前模块的公共接口
__all__ = [
    "AuthError",
    "ChangePasswordRequest",
    "COOKIE_NAME",
    "DEV_AUTH_SECRET",
    "JWT_ALGORITHM",
    "LoginRequest",
    "change_own_password",
    "clear_auth_cookie",
    "cookie_secure_for_request",
    "create_auth_user",
    "create_token",
    "decode_token",
    "delete_auth_user",
    "find_enabled_user",
    "get_auth_cookie_max_age_seconds",
    "get_auth_secret",
    "get_auth_users_database_path",
    "get_current_user",
    "get_current_user_from_request",
    "get_token_expire_hours",
    "get_user_store",
    "load_auth_users",
    "list_auth_users",
    "require_admin",
    "reset_auth_user_password",
    "set_auth_cookie",
    "token_from_request",
    "update_auth_user",
    "verify_login",
    "UserConflictError",
    "UserNotFoundError",
    "UserStoreError",
    "UserValidationError",
]
