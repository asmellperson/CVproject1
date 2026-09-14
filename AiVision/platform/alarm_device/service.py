"""
platform/alarm_device/service.py
喇叭设备 CRUD；提交成功后通知 HornRuntimeManager 热同步。

职责：
    数据库配置层：
        查喇叭
        新增喇叭
        修改喇叭
        删除喇叭
    运行时配置：
        仅向 HornRuntimeManager 提供内部凭据；公开查询只返回 password_set。
"""
from __future__ import annotations
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from AiVision.core.db import session_scope, get_session          # session_scope:自动提交，异常回退，以及最后关闭与数据库的会话，get_session:自己创建一个数据Session
from .schema import HornCreate, HornUpdate
from .orm import AiHornConfig                           # 数据库里的配置

class HornInUseError(ValueError):
    """设备仍被告警配置引用，不允许删除。"""


class HornService:
    def __init__(self, runtime_manager=None):
        self._runtime_manager = runtime_manager

    def _sync_after_commit(self, horn_id: int):
        runtime = self._runtime_manager
        if runtime is None:
            from .runtime_manager import horn_runtime_manager
            runtime = horn_runtime_manager
        runtime.sync(horn_id)

    def list_horns(self, enabled_only: bool = False) -> list[dict]:
        """查询所有喇叭配置"""
        # 创建数据库会话
        session = get_session()
        try:
            # 构建查询对象q
            q = session.query(AiHornConfig)
            # 查询语句
            if enabled_only:
                q = q.filter(AiHornConfig.enable.is_(True))
            # q.all：执行查询
            return [self._to_dict(h) for h in q.all()]
        finally:
            session.close()

    def get_horn(self, horn_id: int) -> Optional[dict]:
        """根据数据库主键ID查一个喇叭"""
        session = get_session()
        try:
            # 找到dict，没找到None
            h = session.get(AiHornConfig, horn_id)
            return self._to_dict(h) if h else None
        finally:
            session.close()

    def create_horn(self, payload: dict) -> dict:
        """新增喇叭"""
        payload = HornCreate.model_validate(payload).write_values()
        # 开启数据库事务
        with session_scope() as session:
            # 内存对象
            h = AiHornConfig(
                name=payload["name"],
                url=payload["url"],
                username=payload.get("username", "admin"),
                password=payload["password"],
                enable=bool(payload.get("enable", True)),
                description=payload.get("description"),
            )
            # 告诉SQLAIchemy：我要新增这个对象，此时是pending（等待INSERT）
            session.add(h)
            # 构造SQL语句
            session.flush()
            result = self._to_dict(h)
        self._sync_after_commit(result["id"])
        return result

    def update_horn(self, horn_id: int, payload: dict) -> Optional[dict]:
        """更新数据库"""
        payload = HornUpdate.model_validate(payload).write_values()
        with session_scope() as session:
            h = session.get(AiHornConfig, horn_id, with_for_update=True)
            if h is None:
                return None
            # 这些字段允许被修改
            for f in ("name", "url", "username", "password", "description"):
                # 只有payload里真正传来的字段才改
                if f in payload and (f != "password" or payload[f]):
                    setattr(h, f, payload[f])
            # 单独处理enable
            if "enable" in payload:
                h.enable = bool(payload["enable"])
            result = self._to_dict(h)
        self._sync_after_commit(horn_id)
        return result

    def delete_horn(self, horn_id: int) -> bool:
        """删除喇叭"""
        with session_scope() as session:
            h = session.get(AiHornConfig, horn_id, with_for_update=True)
            if h is None:
                return False
            from AiVision.features import all_specs
            from AiVision.features._base.orm import FeatureConfigBase
            from AiVision.features.detect_logistics_single_person.orm import LogisticsChannel

            # 包括停用的功能/通道配置；存在引用时不依赖外键 SET NULL 隐式解绑。
            models = [
                spec.orm_class for spec in all_specs().values()
                if issubclass(spec.orm_class, FeatureConfigBase)
            ]
            models.append(LogisticsChannel)
            for model in models:
                if session.query(model).filter(model.horn_id == horn_id).with_for_update().first() is not None:
                    raise HornInUseError("喇叭仍被功能或物流通道配置引用，请先解除绑定")
            session.delete(h)
        self._sync_after_commit(horn_id)
        return True

    # ---------- Runtime ----------
    def runtime_configs(self, horn_id: int | None = None) -> list[dict]:
        """内部凭据读取，仅供运行管理器/连接测试；不能用于 API 查询响应。"""
        session = get_session()
        try:
            query = session.query(AiHornConfig)
            if horn_id is not None:
                query = query.filter(AiHornConfig.id == horn_id)
            return [dict(self._to_dict(h), url=h.url, password=h.password) for h in query.all()]
        finally:
            session.close()

    @staticmethod
    def _to_dict(h: AiHornConfig) -> dict:
        """ORM对象转普通字典"""
        # 兼容历史地址中夹带认证信息的记录；公开读取也不能泄露 URL 中的凭据。
        try:
            address = urlsplit(h.url)
            public_url = urlunsplit((address.scheme, address.netloc.rsplit("@", 1)[-1],
                                     address.path, "", ""))
        except ValueError:
            public_url = ""
        return {
            "id": h.id,
            "name": h.name,
            "url": public_url,
            "username": h.username,
            "password_set": bool(h.password),
            "enable": bool(h.enable),
            "description": h.description,
        }


horn_service = HornService()
