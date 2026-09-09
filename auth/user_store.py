"""SQLite 用户存储、旧库迁移和用户数据读写。"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3                                # Python自带的SQLite操作库 
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

from AiVision.platform.department.department_registry import DEPARTMENT_SPECS

# 两级角色权限
ALLOWED_ROLES = {"admin", "viewer"}
# 普通用户允许访问的事业部
ALLOWED_VIEWER_DEPARTMENTS = frozenset(DEPARTMENT_SPECS)
LEGACY_DEFAULT_PASSWORD = "Fuda@2026"
PASSWORD_HASH_ITERATIONS = 260_000
# 把各种旧名字，中文名字，简称统一成标准事业部编码
DEPARTMENT_ALIASES = {
    "ge": "general_electric",
    "general": "general_electric",
    "通用电气": "general_electric",
    "研究院": "research_institute",
    "人工智能研究院": "research_institute",
    "福达新材院": "research_institute",
    "电子电工": "electronics_electrician",
    "电气部件": "electrical_components",
    "weida": "precious_metal_recycling",
    "weida_company": "precious_metal_recycling",
    "weida-company": "precious_metal_recycling",
    "weida company": "precious_metal_recycling",
    "伟达": "precious_metal_recycling",
    "伟达公司": "precious_metal_recycling",
    "贵金属回收": "precious_metal_recycling",
    "皓达公司": "haoda_company",
    "皓达": "haoda_company",
}

# ========= 四个异常类 ==========
class UserStoreError(RuntimeError):
    """总异常"""

class UserValidationError(UserStoreError):
    """用户提交的数据本身不合法"""

class UserConflictError(UserStoreError):
    """数据格式没问题，但和已有业务状态冲突"""

class UserNotFoundError(UserStoreError):
    """目标用户不存在"""

def default_database_path() -> Path:
    """SQLite数据库的路径"""
    raw = os.getenv("AUTH_USERS_DB")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "runtime" / "auth" / "auth_users.db"

# ================ 数据合法性 ============================
def _normalize_required(value: object, label: str) -> str:
    """清洗数据"""
    normalized = str(value or "").strip()
    if not normalized:
        raise UserValidationError(f"{label}不能为空")
    return normalized

def _normalize_role_departments(
    role: object,
    departments: object,
) -> tuple[str, list[str]]:
    """统一验证角色，并把部门数据标准化"""
    # role和departments列表
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in ALLOWED_ROLES:
        raise UserValidationError("角色必须是 admin 或 viewer")
    if normalized_role == "admin":
        return normalized_role, ["all"]                     # 管理员不会绑定具体事业部

    if isinstance(departments, (list, tuple)):
        raw_departments = list(departments)
    else:
        raise UserValidationError("事业部必须是数组")

    normalized_departments: list[str] = []
    for raw_department in raw_departments:
        # 部门别名转换
        normalized_department = str(raw_department or "").strip()
        normalized_department = DEPARTMENT_ALIASES.get(
            normalized_department,
            DEPARTMENT_ALIASES.get(
                normalized_department.lower(),
                normalized_department,
            ),
        )
        # 检查事业部是否合法
        if normalized_department not in ALLOWED_VIEWER_DEPARTMENTS:
            raise UserValidationError("普通用户必须选择有效事业部")
        # 去重
        if normalized_department not in normalized_departments:
            normalized_departments.append(normalized_department)
    if not normalized_departments:
        raise UserValidationError("普通用户必须至少选择一个有效事业部")
    return normalized_role, normalized_departments

# ================= 部门兼容 =====================
def _encode_departments(departments: list[str]) -> str:
    """把Python的部门列表转换成SQLite可以保存的字符串"""
    # Python list -> json.dumps() -> 字符串 -> SQLite TEXT
    return json.dumps(departments, ensure_ascii=False, separators=(",", ":"))

def _decode_departments(value: object) -> list[str]:
    """把数据库里的departments TEXT重新变成Python列表"""
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, list) and decoded:
        return [str(item) for item in decoded]
    return []

def _legacy_default_password() -> str:
    """仅供初始化时迁移无密码哈希的旧账号。"""
    return os.getenv("AUTH_DEFAULT_PASSWORD", LEGACY_DEFAULT_PASSWORD)

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def hash_password(
    password: str,
    *,
    salt: str | None = None,
    iterations: int = PASSWORD_HASH_ITERATIONS,
) -> str:
    """生成用户数据库使用的 PBKDF2-HMAC-SHA256 密码哈希。"""
    salt = salt or secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt}${_b64url_encode(digest)}"

def _public_user(row: sqlite3.Row) -> dict[str, Any]:
    """把SQLite查询出来的一行Row，转换成普通Python字典"""
    return {
        "employee_id": row["employee_id"],
        "name": row["name"],
        "role": row["role"],
        "departments": _decode_departments(row["departments"]),
        "enabled": bool(row["enabled"]),                  # 返回enabled，但是不返回password_hash
        "auth_version": int(row["auth_version"]),
    }

def _user_record(row: sqlite3.Row) -> dict[str, Any]:
    """补回password_hash"""
    item = _public_user(row)
    item["password_hash"] = row["password_hash"]
    return item

class UserStore:
    def __init__(
        self,
        *,
        database_path: str | Path | None = None,
    ):
        """创建一个UserStore数据库管理对象"""
        self.database_path = Path(database_path or default_database_path())
        self._initialize_lock = threading.Lock()
        self._initialized = False                # 当前这个UserStore有没有完成数据库初始化

     # ====================== SQLite初始化 ======================
    def _connect(self) -> sqlite3.Connection:
        """创建一次SQLite数据库连接，并做一些通用设置"""
        # 连接auth_users.db,数据库被其他线程占用时，最多等待约10秒
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row              # 用了sqlite3.row后可以row['employee_id']这样去访问，通过字段名去访问
        # 遇到数据库锁，不要马上报database is locked，等最多10000ms
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")            # 开启SQLite外键约束
        return connection

    def initialize(self) -> None:
        """第一次使用UserStore时，创建数据库目录，创建auth_user表，并兼容升级旧数据库结构"""
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            # 创建数据库目录
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            # 建立连接
            connection = self._connect()
            try:
                # SQLite在有多个读写请求时，WAL模式通常比默认模式更适合开发
                connection.execute("PRAGMA journal_mode = WAL")
                # 开始一个写事务，并提前获得写锁
                connection.execute("BEGIN IMMEDIATE")
                # 创建auth_users表
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_users (
                        employee_id TEXT PRIMARY KEY,               
                        name TEXT NOT NULL UNIQUE,
                        role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
                        department TEXT NOT NULL,
                        departments TEXT NOT NULL DEFAULT '[]',
                        enabled INTEGER NOT NULL DEFAULT 1,
                        password_hash TEXT,
                        auth_version INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                # 获取当前表的列
                columns = {
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(auth_users)"
                    ).fetchall()
                }
                # 检查旧数据库有没有departments
                if "departments" not in columns:
                    # 运行时的数据迁移
                    connection.execute(
                        "ALTER TABLE auth_users "
                        "ADD COLUMN departments TEXT NOT NULL DEFAULT '[]'"
                    )
                if "password_hash" not in columns:
                    connection.execute(
                        "ALTER TABLE auth_users ADD COLUMN password_hash TEXT"
                    )
                for row in connection.execute(
                    "SELECT employee_id, role, department, departments, password_hash "
                    "FROM auth_users"
                ).fetchall():
                    migrated_departments = _decode_departments(row["departments"])
                    if not migrated_departments:
                        legacy_department = str(row["department"] or "").strip()
                        migrated_departments = [legacy_department] if legacy_department else []
                    role, departments = _normalize_role_departments(
                        row["role"],
                        migrated_departments,
                    )
                    password_hash = str(row["password_hash"] or "").strip()
                    if not password_hash:
                        password_hash = hash_password(_legacy_default_password())
                    connection.execute(
                        "UPDATE auth_users "
                        "SET role = ?, department = ?, departments = ?, password_hash = ? "
                        "WHERE employee_id = ?",
                        (
                            role,
                            departments[0],
                            _encode_departments(departments),
                            password_hash,
                            row["employee_id"],
                        ),
                    )
                connection.commit()
                self._initialized = True
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
    # ===================== 查询 ========================
    def list_users(self) -> list[dict[str, Any]]:
        """查询所有用户"""
        self.initialize()
        with closing(self._connect()) as connection:       # closing:with结束以后自动执行connection.close()
            # SQL查询
            rows = connection.execute(
                """
                SELECT employee_id, name, role, departments, enabled,
                       password_hash, auth_version
                FROM auth_users
                ORDER BY employee_id
                """
            ).fetchall()
        # _public_user()不会返回password_hash(密码哈希)
        return [_public_user(row) for row in rows]

    def get_user_record(self, employee_id: str) -> dict[str, Any]:
        """根据工号获取一个用户的完整内部记录,主要给内部认证使用"""
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT employee_id, name, role, departments, enabled,
                       password_hash, auth_version
                FROM auth_users
                WHERE employee_id = ?
                """,
                (str(employee_id).strip(),),
            ).fetchone()
        if row is None:
            raise UserNotFoundError("用户不存在")
        return _user_record(row)                  # _user_recode():有password_hash,

    def find_enabled_user(self, identifier: str) -> dict[str, Any] | None:
        """查找一个启用状态用户"""
        self.initialize()
        normalized = str(identifier).strip()
        if not normalized:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT employee_id, name, role, departments, enabled,
                       password_hash, auth_version
                FROM auth_users
                WHERE enabled = 1 AND (employee_id = ? OR name = ?)
                LIMIT 1
                """,
                (normalized, normalized),
            ).fetchone()
        return _user_record(row) if row is not None else None             # 有password_hash

     # ================== 写操作 =====================
    def create_user(
        self,
        *,
        employee_id: str,
        name: str,
        role: str,
        password_hash: str,
        departments: list[str] | None,
    ) -> dict[str, Any]:
        """在SQL里创建一条用户记录"""
        self.initialize()
        normalized_employee_id = _normalize_required(employee_id, "工号")
        normalized_name = _normalize_required(name, "姓名")
        normalized_role, normalized_departments = _normalize_role_departments(
            role,
            departments,
        )
        if not password_hash:
            raise UserValidationError("密码哈希不能为空")

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            # 检查工号重复
            if connection.execute(
                "SELECT 1 FROM auth_users WHERE employee_id = ?",
                (normalized_employee_id,),
            ).fetchone():
                raise UserConflictError("工号已存在")
            # 检查姓名重复
            if connection.execute(
                "SELECT 1 FROM auth_users WHERE name = ?",
                (normalized_name,),
            ).fetchone():
                raise UserConflictError("姓名已存在")
            # 新用户默认启用，并且初始登录凭证版本为1
            connection.execute(
                """
                INSERT INTO auth_users(
                    employee_id, name, role, department, departments, enabled,
                    password_hash, auth_version
                ) VALUES (?, ?, ?, ?, ?, 1, ?, 1)
                """,
                (
                    normalized_employee_id,
                    normalized_name,
                    normalized_role,
                    normalized_departments[0],
                    _encode_departments(normalized_departments),
                    password_hash,
                ),
            )
            # 成功提交，失败抛异常rollback
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        # 重新从数据库拿刚刚创建的新记录
        return _public_without_password(
            self.get_user_record(normalized_employee_id)
        )

    def update_user(
        self,
        employee_id: str,
        *,
        actor_employee_id: str,
        name: str,
        role: str,
        enabled: bool,
        departments: list[str] | None,
    ) -> dict[str, Any]:
        """管理员修改用户基本权限资料，同时保证不能禁用自己，不能重名，不能让系统失去最后一个有效管理员"""
        self.initialize()
        normalized_employee_id = _normalize_required(employee_id, "工号")
        normalized_actor = _normalize_required(actor_employee_id, "当前管理员工号")
        normalized_name = _normalize_required(name, "姓名")
        normalized_role, normalized_departments = _normalize_role_departments(
            role,
            departments,
        )
        normalized_enabled = bool(enabled)

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            # 查数据库里的原始用户
            current = connection.execute(
                "SELECT * FROM auth_users WHERE employee_id = ?",
                (normalized_employee_id,),
            ).fetchone()
            if current is None:
                raise UserNotFoundError("用户不存在")
            # 不允许管理员禁用自己
            if normalized_employee_id == normalized_actor and not normalized_enabled:
                raise UserConflictError("不能禁用当前登录管理员")
            # 检查姓名重复
            duplicate_name = connection.execute(
                """
                SELECT 1 FROM auth_users
                WHERE name = ? AND employee_id <> ?
                """,
                (normalized_name, normalized_employee_id),
            ).fetchone()
            if duplicate_name:
                raise UserConflictError("姓名已存在")
            # 修改是否在移除一个有效的管理员，防止最后一个管理员消失
            removes_enabled_admin = (
                bool(current["enabled"])
                and current["role"] == "admin"
                and (not normalized_enabled or normalized_role != "admin")
            )
            # 不能变更最后一个已启用的管理员
            if removes_enabled_admin and self._enabled_admin_count(connection) <= 1:
                raise UserConflictError("不能变更最后一个已启用管理员")
            # 修改
            connection.execute(
                """
                UPDATE auth_users
                SET name = ?, role = ?, department = ?, departments = ?, enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE employee_id = ?
                """,
                (
                    normalized_name,
                    normalized_role,
                    normalized_departments[0],
                    _encode_departments(normalized_departments),
                    int(normalized_enabled),                     # SQLite仍然使用1和0
                    normalized_employee_id,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return _public_without_password(self.get_user_record(normalized_employee_id))

    def update_password_hash(
        self,
        employee_id: str,
        password_hash: str,
    ) -> dict[str, Any]:
        """修改用户密码哈希，并让这个用户之前所有的JWT登录凭证失效"""
        self.initialize()
        normalized_employee_id = _normalize_required(employee_id, "工号")
        if not password_hash:
            raise UserValidationError("密码哈希不能为空")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE auth_users
                SET password_hash = ?, auth_version = auth_version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE employee_id = ?
                """,
                (password_hash, normalized_employee_id),
            )
            if cursor.rowcount == 0:
                raise UserNotFoundError("用户不存在")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return _public_without_password(self.get_user_record(normalized_employee_id))

    def delete_user(
        self,
        employee_id: str,
        *,
        actor_employee_id: str,
    ) -> None:
        """管理员删除一个指定用户"""
        self.initialize()
        normalized_employee_id = _normalize_required(employee_id, "工号")
        normalized_actor = _normalize_required(actor_employee_id, "当前管理员工号")
        if normalized_employee_id == normalized_actor:
            raise UserConflictError("不能删除当前登录管理员")

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            # 目标用户必须存在
            current = connection.execute(
                "SELECT * FROM auth_users WHERE employee_id = ?",
                (normalized_employee_id,),
            ).fetchone()
            if current is None:
                raise UserNotFoundError("用户不存在")
            if (
                bool(current["enabled"])
                and current["role"] == "admin"
                and self._enabled_admin_count(connection) <= 1
            ):
                raise UserConflictError("不能删除最后一个已启用管理员")
            # 执行删除操作
            connection.execute(
                "DELETE FROM auth_users WHERE employee_id = ?",
                (normalized_employee_id,),
            )
            connection.commit()
        except Exception:
            # 关闭连接
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _enabled_admin_count(connection: sqlite3.Connection) -> int:
        """统计当前还有多少个启用状态的管理员"""
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM auth_users
            WHERE role = 'admin' AND enabled = 1
            """
        ).fetchone()
        return int(row["count"])

def _public_without_password(record: dict[str, Any]) -> dict[str, Any]:
    """从内部完整记录中删除password_hash"""
    return {
        key: value
        for key, value in record.items()
        if key != "password_hash"
    }


__all__ = [
    "ALLOWED_ROLES",
    "ALLOWED_VIEWER_DEPARTMENTS",
    "UserConflictError",
    "UserNotFoundError",
    "UserStore",
    "UserStoreError",
    "UserValidationError",
    "default_database_path",
    "hash_password",
]
