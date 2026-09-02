# 文件说明：封装业务服务的业务规则与持久化访问。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
features/_base/config_manager.py
通用功能配置读写服务 — 替代旧 SQL 类里 5 个 save_xxx_config_by_shm_name 方法。

旧代码: save_blocks_config_by_shm_name / save_door_config_by_shm_name / 
        save_face_config_by_shm_name / save_phone_config_by_shm_name / 
        save_human_config_by_shm_name — 每个 80 行,完全相同的逻辑只换字段名。

新代码: 一个 save_config(spec, shm_name, payload) 通过 SPEC.orm_class 反射搞定。
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy import or_

from AiVision.core.db import session_scope, get_session
from AiVision.core.events import config_event_bus, ConfigChangeEvent
from AiVision.core.cache import config_cache
from AiVision.features._base.spec import FeatureSpec
from AiVision.platform.camera.orm import AiCameraConfig


# 功能：所有功能配置的 CRUD 入口；输入与输出详见下方说明
# 参数：无。
# 返回：FeatureConfigManager；返回新建的 `FeatureConfigManager` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FeatureConfigManager:
    """所有功能配置的 CRUD 入口。
    
    通过 FeatureSpec.orm_class 反射目标表,所以一份代码服务所有功能。
    """

    # ---------- Read ----------

    # 功能：读取指定摄像头的指定功能配置；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `spec`（FeatureSpec）：`spec` 对应的业务输入值
    #   - `shm_name`（str）：摄像头共享内存名称
    # 返回：Optional[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/config_manager.py` 的 `FeatureConfigManager::save_config` 调用本符号
    #   - 内部调用：`get_session`、`self._get_camera_by_key`、`session.query(spec.orm_class).filter_by(camera_id=camera.id).first`、`session.query(spec.orm_class).filter_by`、`session.query`、`self._camera_to_dict`、`cfg.to_value_dict`、`cfg.to_alarm_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_config(self, spec: FeatureSpec, shm_name: str) -> Optional[dict]:
        """读取指定摄像头的指定功能配置。
        
        返回前端需要的统一格式:
            {
                "camera": {"id", "name", "shm_name", "enable"},
                "feature": "blocks",
                "config": {"enable", "value", "alarm"}
            }
        """
        session = get_session()
        try:
            camera = self._get_camera_by_key(session, shm_name)
            if camera is None:
                return None

            cfg = (
                session.query(spec.orm_class)
                .filter_by(camera_id=camera.id)
                .first()
            )
            # 没有记录时返回默认空配置(前端可以填初始值)
            if cfg is None:
                return {
                    "camera": self._camera_to_dict(camera),
                    "feature": spec.name,
                    "config": {
                        "enable": False,
                        "value": {},
                        "alarm": {
                            "sql": {"enable": False, "parm": {}},
                            "horn": {"enable": False, "parm": {}},
                            "wechat": {"enable": False, "parm": {"user": ""}},
                        },
                    },
                }

            return {
                "camera": self._camera_to_dict(camera),
                "feature": spec.name,
                "config": {
                    "enable": cfg.enable,
                    "value": cfg.to_value_dict(),
                    "alarm": cfg.to_alarm_dict(),
                },
            }
        finally:
            session.close()

    # ---------- Write ----------

    # 功能：写入功能配置。已校验过的 payload 来自 API 层；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `spec`（FeatureSpec）：`spec` 对应的业务输入值
    #   - `shm_name`（str）：摄像头共享内存名称
    #   - `payload`（dict）：接口或事件携带的业务数据
    # 返回：Optional[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`self._get_camera_by_key`、`session.query(spec.orm_class).filter_by(camera_id=camera.id).first`、`session.query(spec.orm_class).filter_by`、`session.query`、`bool`、`spec.orm_class`、`session.add`、`session.flush`、`payload.get`
    #          等共 16 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def save_config(
        self,
        spec: FeatureSpec,
        shm_name: str,
        payload: dict,
    ) -> Optional[dict]:
        """写入功能配置。已校验过的 payload 来自 API 层。
        
        payload 形状:
            {
                "enable": bool,
                "value": {功能特有字段},
                "alarm": {sql, horn, wechat}
            }
        """
        with session_scope() as session:
            camera = self._get_camera_by_key(session, shm_name)
            if camera is None:
                return None

            cfg = (
                session.query(spec.orm_class)
                .filter_by(camera_id=camera.id)
                .first()
            )
            old_enable = bool(cfg.enable) if cfg is not None else False
            if cfg is None:
                cfg = spec.orm_class(camera_id=camera.id)
                session.add(cfg)
                session.flush()

            new_enable = bool(payload.get("enable", False))
            cfg.enable = new_enable
            cfg.apply_value_dict(payload.get("value") or {})
            cfg.apply_alarm_dict(payload.get("alarm") or {})

            # 提交后刷新缓存 + 发事件
            camera_id = camera.id
            camera_shm = camera.shm_name
            session.flush()  # 确保 ORM 字段都已落库

        # session_scope 已 commit,这里从数据库重载配置缓存后再发热更新事件。
        # 前端按功能添加/删除摄像头本质是更新 enable,consumer 收到事件时必须读到最新数据库值。
        config_cache.reload()
        config_event_bus.publish(ConfigChangeEvent(
            change_type=f"{spec.name}_config_updated",
            camera_id=camera_id,
            camera_name=camera_shm,
        ))
        if old_enable != new_enable:
            action = "enabled" if new_enable else "disabled"
            config_event_bus.publish(ConfigChangeEvent(
                change_type=f"{spec.name}_{action}",
                camera_id=camera_id,
                camera_name=camera_shm,
            ))

        # 重新读一次返回
        return self.get_config(spec, shm_name)

    # ---------- Helpers ----------

    # 功能：支持 shm_name / name / 数字 id / 'camera_{id}' 多种 key 格式；输入与输出详见下方说明
    # 参数：
    #   - `session`（未显式标注）：数据库会话或运行会话
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：Optional[AiCameraConfig]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/config_manager.py` 的 `FeatureConfigManager::get_config` 调用本符号；`AiVision/features/_base/config_manager.py` 的
    #         `FeatureConfigManager::save_config` 调用本符号
    #   - 内部调用：`(key or
    #          '').strip`、`key.isdigit`、`filters.append`、`int`、`key.startswith`、`key.removeprefix('camera_').isdigit`、`key.removeprefix`、`session.query(AiCameraConfig).filter(or_(*filters)).first`、`session.query(AiCameraConfig).filter`、`session.query`
    #          等共 11 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    @staticmethod
    def _get_camera_by_key(session, key: str) -> Optional[AiCameraConfig]:
        """支持 shm_name / name / 数字 id / 'camera_{id}' 多种 key 格式"""
        key = (key or "").strip()
        if not key:
            return None
        filters = [AiCameraConfig.shm_name == key, AiCameraConfig.name == key]
        if key.isdigit():
            filters.append(AiCameraConfig.id == int(key))
        elif key.startswith("camera_") and key.removeprefix("camera_").isdigit():
            filters.append(AiCameraConfig.id == int(key.removeprefix("camera_")))
        return session.query(AiCameraConfig).filter(or_(*filters)).first()

    # 功能：转换或规范化 `_camera_to_dict` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `camera`（AiCameraConfig）：摄像头配置或实体
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/config_manager.py` 的 `FeatureConfigManager::get_config` 调用本符号
    #   - 内部调用：`bool`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _camera_to_dict(camera: AiCameraConfig) -> dict:
        return {
            "id": camera.id,
            "name": camera.name,
            "shm_name": camera.shm_name or f"camera_{camera.id}",
            "enable": bool(camera.enable),
        }


# 单例,API 层和 Orchestrator 共用
feature_config_manager = FeatureConfigManager()
