# 文件说明：封装业务服务的业务规则与持久化访问。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""Service layer for Guard Room sites, cameras, and per-site config."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy import inspect, text

from .config import (
    AppConfig,
    ClassConfig,
    ModelConfig,
    RoomConfig,
    RuleConfig,
    RuntimeConfig,
    VideoConfig,
    WeChatConfig,
)
from .db import create_all_tables, get_session, session_scope
from .orm import GuardRoomCamera, GuardRoomSite, GuardRoomSiteConfig


MAX_CAMERAS_PER_SITE = 9
DEFAULT_DEPARTMENT = "general_electric"


# 功能：CRUD and configuration assembly for guard-room monitoring sites；输入与输出详见下方说明
# 参数：
#   - `default_config_path`（str | Path | None）：`default_config_path` 对应的业务输入值；默认值为 `None`
#   - `project_root`（str | Path | None）：`project_root` 对应的业务输入值；默认值为 `None`
# 返回：GuardRoomService；返回新建的 `GuardRoomService` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_runtime_manager.py` 的 `_service`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_site_api.py` 的
#         `test_app_lifespan_starts_enabled_sites_and_preserves_disabled_sites`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_site_api.py` 的
#         `test_first_enabled_camera_starts_an_enabled_site_after_app_startup`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_site_service.py` 的
#         `test_site_service_creates_site_cameras_and_app_config` 实例化本符号；另有 6 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class GuardRoomService:
    """CRUD and configuration assembly for guard-room monitoring sites."""

    # 功能：初始化或配置 `__init__` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `default_config_path`（str | Path | None）：`default_config_path` 对应的业务输入值；默认值为 `None`
    #   - `project_root`（str | Path | None）：`project_root` 对应的业务输入值；默认值为 `None`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path`、`Path(__file__).resolve`、`Path(project_root).resolve`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(
        self,
        default_config_path: str | Path | None = None,
        *,
        project_root: str | Path | None = None,
    ):
        self.default_config_path = Path(default_config_path) if default_config_path else (
            Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"
        )
        self.project_root = (
            Path(project_root).resolve()
            if project_root is not None
            else Path(__file__).resolve().parents[1]
        )

    # ---------- Schema ----------

    # 功能：Create guard-room tables if they do not already exist；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/tests/test_runtime_manager.py` 的 `_service`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_site_api.py` 的
    #         `test_app_lifespan_starts_enabled_sites_and_preserves_disabled_sites`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_site_api.py` 的
    #         `test_first_enabled_camera_starts_an_enabled_site_after_app_startup`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_site_service.py` 的
    #         `test_site_service_creates_site_cameras_and_app_config` 调用本符号；另有 6 处静态调用
    #   - 内部调用：`create_all_tables`、`self._ensure_department_schema`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def ensure_schema(self) -> None:
        """Create guard-room tables if they do not already exist."""
        create_all_tables()
        self._ensure_department_schema()

    # ---------- Sites ----------

    # 功能：读取或查询 `list_sites` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `include_cameras`（bool）：`include_cameras` 对应的业务输入值；默认值为 `True`
    #   - `department`（str | None）：业务部门名称或标识；默认值为 `None`
    # 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`get_session`、`session.query`、`self._normalize_department`、`query.filter`、`query.order_by(GuardRoomSite.sort_order,
    #          GuardRoomSite.id).all`、`query.order_by`、`self._site_to_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_sites(self, include_cameras: bool = True, department: str | None = None) -> list[dict[str, Any]]:
        session = get_session()
        try:
            query = session.query(GuardRoomSite)
            normalized_department = self._normalize_department(department, required=False)
            if normalized_department:
                query = query.filter(GuardRoomSite.department == normalized_department)
            rows = query.order_by(GuardRoomSite.sort_order, GuardRoomSite.id).all()
            return [self._site_to_dict(row, include_cameras=include_cameras) for row in rows]
        finally:
            session.close()

    # 功能：读取或查询 `get_site` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `include_config`（bool）：`include_config` 对应的业务输入值；默认值为 `True`
    # 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_site`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::update_site` 调用本符号
    #   - 内部调用：`get_session`、`session.get`、`self._site_to_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_site(self, site_id: int, include_config: bool = True) -> dict[str, Any] | None:
        session = get_session()
        try:
            site = session.get(GuardRoomSite, site_id)
            if site is None:
                return None
            return self._site_to_dict(site, include_cameras=True, include_config=include_config)
        finally:
            session.close()

    # 功能：创建或构建 `create_site` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `name`（str）：业务对象名称
    #   - `enabled`（bool）：是否启用相应能力；默认值为 `True`
    #   - `department`（str | None）：业务部门名称或标识；默认值为 `None`
    #   - `description`（str | None）：`description` 对应的业务输入值；默认值为 `None`
    #   - `sort_order`（int | None）：`sort_order` 对应的业务输入值；默认值为 `None`
    #   - `config`（dict[str, Any] | AppConfig | None）：运行配置对象；默认值为 `None`
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._required_text`、`self._normalize_department`、`session_scope`、`session.query(GuardRoomSite).filter_by(name=name,
    #          department=department).first`、`session.query(GuardRoomSite).filter_by`、`session.query`、`ValueError`、`self._next_site_sort_order`、`GuardRoomSite`、`bool`
    #          等共 21 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
    def create_site(
        self,
        name: str,
        *,
        enabled: bool = True,
        department: str | None = None,
        description: str | None = None,
        sort_order: int | None = None,
        config: dict[str, Any] | AppConfig | None = None,
    ) -> dict[str, Any]:
        name = self._required_text(name, "保安室名称")
        department = self._normalize_department(department)
        with session_scope() as session:
            if session.query(GuardRoomSite).filter_by(name=name, department=department).first():
                raise ValueError(f"保安室名称已存在: {name}")

            if sort_order is None:
                sort_order = self._next_site_sort_order(session, department)

            site = GuardRoomSite(
                name=name,
                department=department,
                enabled=bool(enabled),
                description=(description or "").strip() or None,
                sort_order=int(sort_order),
            )
            session.add(site)
            session.flush()

            sections = self._config_sections(config)
            sections["wechat"]["camera_name"] = name
            session.query(GuardRoomSiteConfig).filter_by(site_id=site.id).delete()
            session.add(GuardRoomSiteConfig(site_id=site.id, **self._sections_to_orm_kwargs(sections)))
            site_id = site.id

        created = self.get_site(site_id)
        if created is None:
            raise RuntimeError("创建保安室后读取失败")
        return created

    # 功能：更新或保存 `update_site` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
    # 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`session.get`、`self._required_text`、`session.query(GuardRoomSite).filter(GuardRoomSite.name == name,
    #          GuardRoomSite.department == site.department, GuardRoomSite.id !=
    #          site_id).first`、`session.query(GuardRoomSite).filter`、`session.query`、`ValueError`、`dict`、`str(wechat.get('camera_name')
    #          or '').strip`、`str` 等共 13 个调用。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；校验或执行失败时会主动抛出异常。
    def update_site(self, site_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        with session_scope() as session:
            site = session.get(GuardRoomSite, site_id)
            if site is None:
                return None

            if "name" in payload:
                name = self._required_text(payload["name"], "保安室名称")
                duplicate = (
                    session.query(GuardRoomSite)
                    .filter(
                        GuardRoomSite.name == name,
                        GuardRoomSite.department == site.department,
                        GuardRoomSite.id != site_id,
                    )
                    .first()
                )
                if duplicate:
                    raise ValueError(f"保安室名称已存在: {name}")
                site.name = name
                if site.config is not None:
                    wechat = dict(site.config.wechat_json or {})
                    if not str(wechat.get("camera_name") or "").strip():
                        wechat["camera_name"] = name
                        site.config.wechat_json = wechat

            for field_name in ("enabled", "sort_order", "description"):
                if field_name in payload:
                    setattr(site, field_name, payload[field_name])

        return self.get_site(site_id)

    # 功能：删除或清理 `delete_site` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`session.get`、`session.delete`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def delete_site(self, site_id: int) -> bool:
        with session_scope() as session:
            site = session.get(GuardRoomSite, site_id)
            if site is None:
                return False
            session.delete(site)
        return True

    # ---------- Cameras ----------

    # 功能：创建或构建 `create_camera` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `name`（str）：业务对象名称
    #   - `rtsp_url`（str）：`rtsp_url` 对应的业务输入值
    #   - `enabled`（bool）：是否启用相应能力；默认值为 `True`
    #   - `sort_order`（int | None）：`sort_order` 对应的业务输入值；默认值为 `None`
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._required_text`、`session_scope`、`session.get`、`ValueError`、`session.query(GuardRoomCamera).filter_by(site_id=site_id).count`、`session.query(GuardRoomCamera).filter_by`、`session.query`、`session.query(GuardRoomCamera).filter_by(site_id=site_id,
    #          name=name).first`、`self._next_camera_sort_order`、`GuardRoomCamera` 等共 16 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务；校验或执行失败时会主动抛出异常。
    def create_camera(
        self,
        site_id: int,
        *,
        name: str,
        rtsp_url: str,
        enabled: bool = True,
        sort_order: int | None = None,
    ) -> dict[str, Any]:
        name = self._required_text(name, "摄像头名称")
        rtsp_url = self._required_text(rtsp_url, "RTSP 地址")

        with session_scope() as session:
            site = session.get(GuardRoomSite, site_id)
            if site is None:
                raise ValueError(f"保安室不存在: {site_id}")

            camera_count = session.query(GuardRoomCamera).filter_by(site_id=site_id).count()
            if camera_count >= MAX_CAMERAS_PER_SITE:
                raise ValueError("每个保安室最多只能添加 9 路摄像头")

            if session.query(GuardRoomCamera).filter_by(site_id=site_id, name=name).first():
                raise ValueError(f"摄像头名称已存在: {name}")

            if sort_order is None:
                sort_order = self._next_camera_sort_order(session, site_id)

            camera = GuardRoomCamera(
                site_id=site_id,
                name=name,
                rtsp_url=rtsp_url,
                enabled=bool(enabled),
                sort_order=int(sort_order),
            )
            session.add(camera)
            session.flush()
            camera_id = camera.id

        created = self.get_camera(camera_id)
        if created is None:
            raise RuntimeError("创建摄像头后读取失败")
        return created

    # 功能：读取或查询 `list_cameras` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `enabled_only`（bool）：`enabled_only` 对应的业务输入值；默认值为 `False`
    # 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`get_session`、`session.query(GuardRoomCamera).filter_by`、`session.query`、`query.filter_by`、`query.order_by(GuardRoomCamera.sort_order,
    #          GuardRoomCamera.id).all`、`query.order_by`、`self._camera_to_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_cameras(self, site_id: int, enabled_only: bool = False) -> list[dict[str, Any]]:
        session = get_session()
        try:
            query = session.query(GuardRoomCamera).filter_by(site_id=site_id)
            if enabled_only:
                query = query.filter_by(enabled=True)
            cameras = query.order_by(GuardRoomCamera.sort_order, GuardRoomCamera.id).all()
            return [self._camera_to_dict(camera) for camera in cameras]
        finally:
            session.close()

    # 功能：读取或查询 `get_camera` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_camera`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::update_camera` 调用本符号
    #   - 内部调用：`get_session`、`session.get`、`self._camera_to_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_camera(self, camera_id: int) -> dict[str, Any] | None:
        session = get_session()
        try:
            camera = session.get(GuardRoomCamera, camera_id)
            return self._camera_to_dict(camera) if camera is not None else None
        finally:
            session.close()

    # 功能：更新或保存 `update_camera` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
    # 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`session.get`、`self._required_text`、`session.query(GuardRoomCamera).filter(GuardRoomCamera.site_id ==
    #          camera.site_id, GuardRoomCamera.name == name, GuardRoomCamera.id !=
    #          camera_id).first`、`session.query(GuardRoomCamera).filter`、`session.query`、`ValueError`、`setattr`、`self.get_camera`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def update_camera(self, camera_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        with session_scope() as session:
            camera = session.get(GuardRoomCamera, camera_id)
            if camera is None:
                return None

            if "name" in payload:
                name = self._required_text(payload["name"], "摄像头名称")
                duplicate = (
                    session.query(GuardRoomCamera)
                    .filter(
                        GuardRoomCamera.site_id == camera.site_id,
                        GuardRoomCamera.name == name,
                        GuardRoomCamera.id != camera_id,
                    )
                    .first()
                )
                if duplicate:
                    raise ValueError(f"摄像头名称已存在: {name}")
                camera.name = name

            if "rtsp_url" in payload:
                camera.rtsp_url = self._required_text(payload["rtsp_url"], "RTSP 地址")
            for field_name in ("enabled", "sort_order"):
                if field_name in payload:
                    setattr(camera, field_name, payload[field_name])

        return self.get_camera(camera_id)

    # 功能：删除或清理 `delete_camera` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`session.get`、`session.delete`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def delete_camera(self, camera_id: int) -> bool:
        with session_scope() as session:
            camera = session.get(GuardRoomCamera, camera_id)
            if camera is None:
                return False
            session.delete(camera)
        return True

    # ---------- Config ----------

    # 功能：读取或查询 `get_site_config` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::update_site_config` 调用本符号
    #   - 内部调用：`get_session`、`session.query(GuardRoomSiteConfig).filter_by(site_id=site_id).first`、`session.query(GuardRoomSiteConfig).filter_by`、`session.query`、`self._config_to_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_site_config(self, site_id: int) -> dict[str, Any] | None:
        session = get_session()
        try:
            cfg = session.query(GuardRoomSiteConfig).filter_by(site_id=site_id).first()
            return self._config_to_dict(cfg) if cfg is not None else None
        finally:
            session.close()

    # 功能：更新或保存 `update_site_config` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `patch`（dict[str, Any]）：`patch` 对应的业务输入值
    # 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`session.get`、`self._config_sections`、`session.add`、`GuardRoomSiteConfig`、`self._sections_to_orm_kwargs`、`session.flush`、`dict`、`getattr`、`current.update`
    #          等共 13 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def update_site_config(self, site_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
        with session_scope() as session:
            site = session.get(GuardRoomSite, site_id)
            if site is None:
                return None
            if site.config is None:
                sections = self._config_sections(None)
                session.add(GuardRoomSiteConfig(site_id=site_id, **self._sections_to_orm_kwargs(sections)))
                session.flush()

            cfg = site.config
            for section in ("video", "models", "room", "rules", "classes", "runtime", "wechat"):
                if section not in patch:
                    continue
                current = dict(getattr(cfg, f"{section}_json") or {})
                current.update(dict(patch.get(section) or {}))
                setattr(cfg, f"{section}_json", current)

        return self.get_site_config(site_id)

    # 功能：Build an ``AppConfig`` for one site from DB config and cameras；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `site_id`（int）：保安室站点唯一标识
    #   - `enabled_only`（bool）：`enabled_only` 对应的业务输入值；默认值为 `True`
    # 返回：AppConfig；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::_get_or_create_context`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_site_service.py` 的
    #         `test_site_service_creates_site_cameras_and_app_config`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
    #         `test_site_config_persists_vehicle_detector_model_from_db`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
    #         `test_site_config_persists_vehicle_camera_and_roi_from_db` 调用本符号
    #   - 内部调用：`get_session`、`session.get`、`ValueError`、`session.query(GuardRoomCamera).filter_by`、`session.query`、`query.filter_by`、`query.order_by(GuardRoomCamera.sort_order,
    #          GuardRoomCamera.id).all`、`query.order_by`、`len`、`self._config_to_dict` 等共 15 个调用。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；校验或执行失败时会主动抛出异常。
    def build_app_config(self, site_id: int, *, enabled_only: bool = True) -> AppConfig:
        """Build an ``AppConfig`` for one site from DB config and cameras."""
        session = get_session()
        try:
            site = session.get(GuardRoomSite, site_id)
            if site is None:
                raise ValueError(f"保安室不存在: {site_id}")
            if site.config is None:
                raise ValueError(f"保安室缺少配置: {site_id}")

            query = session.query(GuardRoomCamera).filter_by(site_id=site_id)
            if enabled_only:
                query = query.filter_by(enabled=True)
            cameras = query.order_by(GuardRoomCamera.sort_order, GuardRoomCamera.id).all()
            if len(cameras) > MAX_CAMERAS_PER_SITE:
                raise ValueError("每个保安室最多只能启用 9 路摄像头")

            sections = self._config_to_dict(site.config)
            sections["video"] = self._with_camera_sources(sections["video"], cameras)
            sections["wechat"] = dict(sections["wechat"] or {})
            sections["wechat"]["camera_name"] = sections["wechat"].get("camera_name") or site.name
            return self._app_config_from_sections(sections)
        finally:
            session.close()

    # ---------- Helpers ----------

    # 功能：读取或查询 `_load_default_config` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：AppConfig；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_config_sections` 调用本符号
    #   - 内部调用：`AppConfig.from_yaml`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _load_default_config(self) -> AppConfig:
        return AppConfig.from_yaml(self.default_config_path)

    # 功能：实现 `_config_sections` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `config`（dict[str, Any] | AppConfig | None）：运行配置对象
    # 返回：dict[str, dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_site`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::update_site_config`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_site_service.py` 的
    #         `test_site_service_replaces_orphan_config_when_sqlite_reuses_site_id` 调用本符号
    #   - 内部调用：`self._load_default_config().to_dict`、`self._load_default_config`、`isinstance`、`config.to_dict`、`deepcopy`、`config.items`、`data[section].update`、`dict`、`data.get`、`self._without_camera_sources`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _config_sections(self, config: dict[str, Any] | AppConfig | None) -> dict[str, dict[str, Any]]:
        if config is None:
            data = self._load_default_config().to_dict()
        elif isinstance(config, AppConfig):
            data = config.to_dict()
        else:
            base = self._load_default_config().to_dict()
            data = deepcopy(base)
            for section, values in config.items():
                if section in data and isinstance(values, dict):
                    data[section].update(values)

        sections = {
            "video": dict(data.get("video") or {}),
            "models": dict(data.get("models") or {}),
            "room": dict(data.get("room") or {}),
            "rules": dict(data.get("rules") or {}),
            "classes": dict(data.get("classes") or {}),
            "runtime": dict(data.get("runtime") or {}),
            "wechat": dict(data.get("wechat") or {}),
        }
        sections["video"] = self._without_camera_sources(sections["video"])
        return sections

    # 功能：转换或规范化 `_sections_to_orm_kwargs` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `sections`（dict[str, dict[str, Any]]）：`sections` 对应的业务输入值
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_site`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::update_site_config`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_site_service.py` 的
    #         `test_site_service_replaces_orphan_config_when_sqlite_reuses_site_id` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _sections_to_orm_kwargs(sections: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {
            "video_json": sections["video"],
            "models_json": sections["models"],
            "room_json": sections["room"],
            "rules_json": sections["rules"],
            "classes_json": sections["classes"],
            "runtime_json": sections["runtime"],
            "wechat_json": sections["wechat"],
        }

    # 功能：转换或规范化 `_config_to_dict` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cfg`（GuardRoomSiteConfig | None）：运行配置对象
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::get_site_config`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::build_app_config`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_site_to_dict` 调用本符号
    #   - 内部调用：`dict`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _config_to_dict(cfg: GuardRoomSiteConfig | None) -> dict[str, Any]:
        if cfg is None:
            return {}
        return {
            "video": dict(cfg.video_json or {}),
            "models": dict(cfg.models_json or {}),
            "room": dict(cfg.room_json or {}),
            "rules": dict(cfg.rules_json or {}),
            "classes": dict(cfg.classes_json or {}),
            "runtime": dict(cfg.runtime_json or {}),
            "wechat": dict(cfg.wechat_json or {}),
        }

    # 功能：实现 `_without_camera_sources` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `video`（dict[str, Any]）：`video` 对应的业务输入值
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_config_sections`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_with_camera_sources` 调用本符号
    #   - 内部调用：`dict`、`range`、`cleaned.pop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _without_camera_sources(video: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(video or {})
        cleaned["source"] = ""
        for idx in range(1, MAX_CAMERAS_PER_SITE + 1):
            cleaned.pop(f"source_cam{idx}", None)
        return cleaned

    # 功能：实现 `_with_camera_sources` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `video`（dict[str, Any]）：`video` 对应的业务输入值
    #   - `cameras`（list[GuardRoomCamera]）：`cameras` 对应的业务输入值
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::build_app_config` 调用本符号
    #   - 内部调用：`GuardRoomService._without_camera_sources`、`enumerate`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _with_camera_sources(video: dict[str, Any], cameras: list[GuardRoomCamera]) -> dict[str, Any]:
        next_video = GuardRoomService._without_camera_sources(video)
        for idx, camera in enumerate(cameras[:MAX_CAMERAS_PER_SITE], start=1):
            next_video[f"source_cam{idx}"] = camera.rtsp_url
        if cameras:
            next_video["source"] = cameras[0].rtsp_url
        return next_video

    # 功能：实现 `_app_config_from_sections` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `sections`（dict[str, dict[str, Any]]）：`sections` 对应的业务输入值
    # 返回：AppConfig；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::build_app_config` 调用本符号
    #   - 内部调用：`dict`、`sections.get`、`video_data.pop`、`list`、`video_data.keys`、`key.startswith`、`key.removeprefix('source_cam').isdigit`、`key.removeprefix`、`VideoConfig`、`GuardRoomService._known_fields`
    #          等共 19 个调用。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；可能启动、等待或停止线程/进程资源。
    @staticmethod
    def _app_config_from_sections(sections: dict[str, dict[str, Any]]) -> AppConfig:
        video_data = dict(sections.get("video") or {})
        source_cam_values = {
            key: video_data.pop(key)
            for key in list(video_data.keys())
            if key.startswith("source_cam") and key.removeprefix("source_cam").isdigit()
        }

        video = VideoConfig(**GuardRoomService._known_fields(VideoConfig, video_data))
        for key, value in source_cam_values.items():
            setattr(video, key, value)

        return AppConfig(
            video=video,
            models=ModelConfig(**GuardRoomService._known_fields(ModelConfig, sections.get("models") or {})),
            room=RoomConfig(**GuardRoomService._known_fields(RoomConfig, sections.get("room") or {})),
            rules=RuleConfig(**GuardRoomService._known_fields(RuleConfig, sections.get("rules") or {})),
            classes=ClassConfig(**GuardRoomService._known_fields(ClassConfig, sections.get("classes") or {})),
            runtime=RuntimeConfig(**GuardRoomService._known_fields(RuntimeConfig, sections.get("runtime") or {})),
            wechat=WeChatConfig(**GuardRoomService._known_fields(WeChatConfig, sections.get("wechat") or {})),
        )

    # 功能：实现 `_known_fields` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `values`（dict[str, Any]）：`values` 对应的业务输入值
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_app_config_from_sections` 调用本符号
    #   - 内部调用：`fields`、`dict(values or {}).items`、`dict`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _known_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {field.name for field in fields(cls)}
        return {key: value for key, value in dict(values or {}).items() if key in allowed}

    # 功能：转换或规范化 `_site_to_dict` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `site`（GuardRoomSite）：`site` 对应的业务输入值
    #   - `include_cameras`（bool）：`include_cameras` 对应的业务输入值；默认值为 `True`
    #   - `include_config`（bool）：`include_config` 对应的业务输入值；默认值为 `False`
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::list_sites`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::get_site` 调用本符号
    #   - 内部调用：`bool`、`len`、`sum`、`site.created_at.isoformat`、`site.updated_at.isoformat`、`GuardRoomService._camera_to_dict`、`GuardRoomService._config_to_dict`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _site_to_dict(
        site: GuardRoomSite,
        *,
        include_cameras: bool = True,
        include_config: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "id": site.id,
            "department": site.department or DEFAULT_DEPARTMENT,
            "name": site.name,
            "enabled": bool(site.enabled),
            "sort_order": site.sort_order,
            "description": site.description,
            "camera_count": len(site.cameras),
            "enabled_camera_count": sum(1 for camera in site.cameras if camera.enabled),
            "created_at": site.created_at.isoformat() if site.created_at else None,
            "updated_at": site.updated_at.isoformat() if site.updated_at else None,
        }
        if include_cameras:
            payload["cameras"] = [GuardRoomService._camera_to_dict(camera) for camera in site.cameras]
        if include_config:
            payload["config"] = GuardRoomService._config_to_dict(site.config)
        return payload

    # 功能：转换或规范化 `_camera_to_dict` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `camera`（GuardRoomCamera）：摄像头配置或实体
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::list_cameras`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::get_camera` 调用本符号
    #   - 内部调用：`bool`、`camera.created_at.isoformat`、`camera.updated_at.isoformat`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _camera_to_dict(camera: GuardRoomCamera) -> dict[str, Any]:
        return {
            "id": camera.id,
            "site_id": camera.site_id,
            "name": camera.name,
            "rtsp_url": camera.rtsp_url,
            "enabled": bool(camera.enabled),
            "sort_order": camera.sort_order,
            "created_at": camera.created_at.isoformat() if camera.created_at else None,
            "updated_at": camera.updated_at.isoformat() if camera.updated_at else None,
        }

    # 功能：实现 `_next_site_sort_order` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `department`（str | None）：业务部门名称或标识；默认值为 `None`
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_site` 调用本符号
    #   - 内部调用：`session.query`、`func.max`、`query.filter`、`query.scalar`、`int`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _next_site_sort_order(session, department: str | None = None) -> int:
        query = session.query(func.max(GuardRoomSite.sort_order))
        if department:
            query = query.filter(GuardRoomSite.department == department)
        value = query.scalar()
        return int(value or 0) + 1

    # 功能：实现 `_next_camera_sort_order` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `site_id`（int）：保安室站点唯一标识
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_camera` 调用本符号
    #   - 内部调用：`session.query(func.max(GuardRoomCamera.sort_order)).filter_by(site_id=site_id).scalar`、`session.query(func.max(GuardRoomCamera.sort_order)).filter_by`、`session.query`、`func.max`、`int`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _next_camera_sort_order(session, site_id: int) -> int:
        value = session.query(func.max(GuardRoomCamera.sort_order)).filter_by(site_id=site_id).scalar()
        return int(value or 0) + 1

    # 功能：实现 `_required_text` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `value`（Any）：待转换、校验或写入的值
    #   - `label`（str）：`label` 对应的业务输入值
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_site`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::update_site`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_camera`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::update_camera` 调用本符号
    #   - 内部调用：`str(value or '').strip`、`str`、`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @staticmethod
    def _required_text(value: Any, label: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{label}不能为空")
        return text

    # 功能：转换或规范化 `_normalize_department` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `department`（str | None）：业务部门名称或标识
    #   - `required`（bool）：`required` 对应的业务输入值；默认值为 `True`
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::list_sites`
    #         调用本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::create_site` 调用本符号
    #   - 内部调用：`str(department or '').strip`、`str`、`aliases.get`、`text_value.lower`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _normalize_department(department: str | None, *, required: bool = True) -> str:
        text_value = str(department or "").strip()
        if not text_value:
            if required:
                return DEFAULT_DEPARTMENT
            return ""
        aliases = {
            "ge": "general_electric",
            "general-electric": "general_electric",
            "general electric": "general_electric",
            "electronics-electrician": "electronics_electrician",
            "electronics electrician": "electronics_electrician",
        }
        return aliases.get(text_value, aliases.get(text_value.lower(), text_value))

    # 功能：检查或判断 `_ensure_department_schema` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::ensure_schema` 调用本符号
    #   - 内部调用：`get_engine`、`inspect`、`inspector.get_table_names`、`inspector.get_columns`、`engine.begin`、`conn.execute`、`text`、`inspector.get_indexes`、`inspector.get_unique_constraints`、`str`
    #          等共 11 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务。
    @staticmethod
    def _ensure_department_schema() -> None:
        from .db import get_engine

        engine = get_engine()
        inspector = inspect(engine)
        if "guard_room_site" not in inspector.get_table_names():
            return

        columns = {column["name"] for column in inspector.get_columns("guard_room_site")}
        dialect = engine.dialect.name
        with engine.begin() as conn:
            if "department" not in columns:
                if dialect == "mysql":
                    conn.execute(text(
                        "ALTER TABLE guard_room_site "
                        "ADD COLUMN department VARCHAR(100) NOT NULL DEFAULT 'general_electric' COMMENT '所属部门'"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE guard_room_site "
                        "ADD COLUMN department VARCHAR(100) NOT NULL DEFAULT 'general_electric'"
                    ))
                conn.execute(text(
                    "UPDATE guard_room_site SET department = 'general_electric' "
                    "WHERE department IS NULL OR department = ''"
                ))

            indexes = inspector.get_indexes("guard_room_site") + inspector.get_unique_constraints("guard_room_site")
            index_names = {str(index.get("name") or "") for index in indexes}
            if dialect == "mysql":
                for index_name in ("name", "ix_guard_room_site_name"):
                    if index_name in index_names:
                        try:
                            conn.execute(text(f"ALTER TABLE guard_room_site DROP INDEX {index_name}"))
                        except Exception:
                            pass
                if "ix_guard_room_site_department" not in index_names:
                    conn.execute(text("CREATE INDEX ix_guard_room_site_department ON guard_room_site (department)"))
                if "uq_guard_room_site_department_name" not in index_names:
                    conn.execute(text(
                        "CREATE UNIQUE INDEX uq_guard_room_site_department_name "
                        "ON guard_room_site (department, name)"
                    ))


guard_room_service = GuardRoomService()
