# 文件说明：封装业务服务的业务规则与持久化访问。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""platform/inference/config_manager.py — 模型 CRUD"""
from __future__ import annotations
from typing import Optional

from core.db import session_scope, get_session
from core.logger import logger
from .orm import AiModel
from .model_paths import resolve_model_path


YOLO_DETECTOR_WORKER = "platform.inference.workers.yolo_detector.YoloDetectorWorker"


# 功能：定义 `ModelConfigManager` 类，封装业务服务相关的状态、约束与操作
# 参数：无。
# 返回：ModelConfigManager；返回新建的 `ModelConfigManager` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ModelConfigManager:

    # 功能：读取或查询 `list_models` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `enabled_only`（bool）：`enabled_only` 对应的业务输入值；默认值为 `False`
    # 返回：list[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`get_session`、`session.query`、`q.filter`、`AiModel.enable.is_`、`self._to_dict`、`q.all`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_models(self, enabled_only: bool = False) -> list[dict]:
        session = get_session()
        try:
            q = session.query(AiModel)
            if enabled_only:
                q = q.filter(AiModel.enable.is_(True))
            return [self._to_dict(m) for m in q.all()]
        finally:
            session.close()

    # 功能：读取或查询 `get_model` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `model_id`（int）：模型唯一标识
    # 返回：Optional[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`get_session`、`session.query(AiModel).get`、`session.query`、`self._to_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_model(self, model_id: int) -> Optional[dict]:
        session = get_session()
        try:
            m = session.query(AiModel).get(model_id)
            return self._to_dict(m) if m else None
        finally:
            session.close()

    # 功能：读取或查询 `get_model_by_name` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `name`（str）：业务对象名称
    # 返回：Optional[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`get_session`、`session.query(AiModel).filter_by(name=name).first`、`session.query(AiModel).filter_by`、`session.query`、`self._to_dict`、`session.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_model_by_name(self, name: str) -> Optional[dict]:
        session = get_session()
        try:
            m = session.query(AiModel).filter_by(name=name).first()
            return self._to_dict(m) if m else None
        finally:
            session.close()

    # 功能：创建或构建 `create_model` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `payload`（dict）：接口或事件携带的业务数据
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`AiModel`、`payload.get`、`bool`、`session.add`、`session.flush`、`self._to_dict`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def create_model(self, payload: dict) -> dict:
        with session_scope() as session:
            m = AiModel(
                name=payload["name"],
                type=payload.get("type", "yolo"),
                path=payload["path"],
                import_path=payload.get("import_path"),
                description=payload.get("description"),
                enable=bool(payload.get("enable", True)),
            )
            session.add(m)
            session.flush()
            return self._to_dict(m)

    # 功能：更新或保存 `update_model` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `model_id`（int）：模型唯一标识
    #   - `payload`（dict）：接口或事件携带的业务数据
    # 返回：Optional[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`session.query(AiModel).get`、`session.query`、`setattr`、`bool`、`self._to_dict`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_model(self, model_id: int, payload: dict) -> Optional[dict]:
        with session_scope() as session:
            m = session.query(AiModel).get(model_id)
            if m is None:
                return None
            for f in ("name", "type", "path", "import_path", "description"):
                if f in payload:
                    setattr(m, f, payload[f])
            if "enable" in payload:
                m.enable = bool(payload["enable"])
            return self._to_dict(m)

    # 功能：删除或清理 `delete_model` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `model_id`（int）：模型唯一标识
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`session_scope`、`session.query(AiModel).get`、`session.query`、`session.delete`。
    # 副作用/注意事项：可能读取或修改数据库事务。
    def delete_model(self, model_id: int) -> bool:
        with session_scope() as session:
            m = session.query(AiModel).get(model_id)
            if m is None:
                return False
            session.delete(m)
            return True

    # 功能：修正常见内置模型的旧版运行配置；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::start` 调用本符号
    #   - 内部调用：`session_scope`、`session.query(AiModel).filter_by(name='yolo_face').first`、`session.query(AiModel).filter_by`、`session.query`、`bool`、`logger.info`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def normalize_builtin_models(self) -> int:
        """修正常见内置模型的旧版运行配置。

        旧库里的 yolo_face 可能仍指向已不存在的旧 worker,且处于禁用状态。
        这里只修已有模型行,不创建新模型,避免覆盖现场自定义模型清单。
        """
        patched = 0
        with session_scope() as session:
            face_model = session.query(AiModel).filter_by(name="yolo_face").first()
            if face_model is None:
                return 0

            if face_model.import_path != YOLO_DETECTOR_WORKER:
                face_model.import_path = YOLO_DETECTOR_WORKER
                patched += 1
            if not bool(face_model.enable):
                face_model.enable = True
                patched += 1

        if patched:
            logger.info("[ModelConfigManager] 已修正内置模型 yolo_face 的运行配置")
        return patched

    # 功能：转换或规范化 `_to_dict` 对应的业务服务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `m`（AiModel）：`m` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/config_manager.py` 的 `ModelConfigManager::list_models` 调用本符号；`AiVision/platform/inference/config_manager.py`
    #         的 `ModelConfigManager::get_model` 调用本符号；`AiVision/platform/inference/config_manager.py` 的 `ModelConfigManager::get_model_by_name`
    #         调用本符号；`AiVision/platform/inference/config_manager.py` 的 `ModelConfigManager::create_model` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`resolve_model_path`、`bool`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _to_dict(m: AiModel) -> dict:
        resolution = resolve_model_path({
            "name": m.name,
            "path": m.path,
        })
        return {
            "id": m.id,
            "name": m.name,
            "type": m.type,
            "path": resolution.path,
            "effective_path": resolution.path,
            "path_source": resolution.source,
            "database_path": resolution.database_path,
            "import_path": m.import_path,
            "description": m.description,
            "enable": bool(m.enable),
        }


model_config_manager = ModelConfigManager()
