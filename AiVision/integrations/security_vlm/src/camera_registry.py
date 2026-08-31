# 文件说明：实现摄像头、资源注册相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""Security VLM 摄像头注册表：校验、脱敏和原子持久化。"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from departments import require_department


CAMERA_ID_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
)


# 功能：校验可安全用于路径片段的摄像头 ID；输入与输出详见下方说明
# 参数：
#   - `camera_id`（str）：摄像头唯一标识
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`isinstance`、`CAMERA_ID_PATTERN.fullmatch`、`ValueError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def validate_camera_id(camera_id: str) -> str:
    """校验可安全用于路径片段的摄像头 ID。"""
    if (
        not isinstance(camera_id, str)
        or CAMERA_ID_PATTERN.fullmatch(camera_id) is None
    ):
        raise ValueError(
            "camera_id 必须以字母或数字开头和结尾，"
            "中间只能包含字母、数字、点、下划线和连字符"
        )
    return camera_id


# 功能：以 JSON 文件持久化安检模块独立维护的摄像头；输入与输出详见下方说明
# 参数：
#   - `path`（Path）：目标路径
#   - `department`（str）：业务部门名称或标识；默认值为 `'general_electric'`
# 返回：CameraRegistry；返回新建的 `CameraRegistry` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `DepartmentWorkspaceManager::get`
#         实例化本符号；`AiVision/integrations/security_vlm/src/department_workspace.py` 的 `_stage_validated_registry`
#         实例化本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `AppService::__init__` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class CameraRegistry:
    """以 JSON 文件持久化安检模块独立维护的摄像头。"""

    VERSION = 2
    MAX_CAMERAS = 4
    CAMERA_ID_PATTERN = CAMERA_ID_PATTERN

    # 功能：初始化或配置 `__init__` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `path`（Path）：目标路径
    #   - `department`（str）：业务部门名称或标识；默认值为 `'general_electric'`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`Path`、`self.path.with_name`、`require_department`、`threading.RLock`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(
        self,
        path: Path,
        department: str = "general_electric",
    ):
        self.path = Path(path)
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")
        self.department = require_department(department)
        self._lock = threading.RLock()

    # 功能：在注册表不存在时原子创建空的 v2 注册表；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.lock`、`self.path.exists`、`self._read_unlocked`、`self._write_unlocked`、`self._empty_payload`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def initialize(self) -> None:
        """在注册表不存在时原子创建空的 v2 注册表。"""
        with self.lock(exclusive=True):
            if self.path.exists():
                self._read_unlocked()
                return
            self._write_unlocked(self._empty_payload())

    # 功能：读取或查询 `list` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：list[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_camera_registry.py` 的
    #         `test_registry_persists_department_and_rejects_mismatch`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_camera_registry.py` 的
    #         `test_legacy_migration_is_idempotent_and_copies_roi`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_camera_registry.py` 的
    #         `test_migration_does_nothing_without_legacy_source` 调用本符号
    #   - 内部调用：`self.lock`、`copy.deepcopy`、`self._read_unlocked`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list(self) -> list[dict]:
        with self.lock(exclusive=False):
            return copy.deepcopy(self._read_unlocked()["cameras"])

    # 功能：读取或查询 `get` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.validate_camera_id`、`self.lock`、`self._read_unlocked`、`copy.deepcopy`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get(self, camera_id: str) -> dict | None:
        wanted = self.validate_camera_id(camera_id)
        with self.lock(exclusive=False):
            for camera in self._read_unlocked()["cameras"]:
                if camera["camera_id"] == wanted:
                    return copy.deepcopy(camera)
        return None

    # 功能：创建或构建 `create` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `name`（str）：业务对象名称
    #   - `rtsp_url`（str）：`rtsp_url` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._validate_name`、`self._validate_rtsp_url`、`self.lock`、`self._read_unlocked`、`len`、`ValueError`、`self._ensure_unique_name`、`time.time`、`str`、`uuid.uuid4`
    #          等共 13 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
    def create(self, name: str, rtsp_url: str) -> dict:
        normalized_name = self._validate_name(name)
        normalized_url = self._validate_rtsp_url(rtsp_url)
        with self.lock(exclusive=True):
            payload = self._read_unlocked()
            if len(payload["cameras"]) >= self.MAX_CAMERAS:
                raise ValueError(f"最多只能添加 {self.MAX_CAMERAS} 台摄像头")
            self._ensure_unique_name(payload["cameras"], normalized_name)
            now = time.time()
            camera = {
                "camera_id": str(uuid.uuid4()),
                "name": normalized_name,
                "rtsp_url": normalized_url,
                "created_at": now,
                "updated_at": now,
            }
            payload["cameras"].append(camera)
            self._write_unlocked(payload)
            return copy.deepcopy(camera)

    # 功能：更新或保存 `update` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（str）：摄像头唯一标识
    #   - `name`（str | None）：业务对象名称；默认值为 `None`
    #   - `rtsp_url`（str | None）：`rtsp_url` 对应的业务输入值；默认值为 `None`
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.lock`、`self._read_unlocked`、`self._find_unlocked`、`self._validate_name`、`self._ensure_unique_name`、`str(rtsp_url).strip`、`str`、`self._validate_rtsp_url`、`time.time`、`self._write_unlocked`
    #          等共 11 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def update(
        self,
        camera_id: str,
        *,
        name: str | None = None,
        rtsp_url: str | None = None,
    ) -> dict:
        with self.lock(exclusive=True):
            payload = self._read_unlocked()
            camera = self._find_unlocked(payload["cameras"], camera_id)
            if name is not None:
                normalized_name = self._validate_name(name)
                self._ensure_unique_name(
                    payload["cameras"],
                    normalized_name,
                    exclude_camera_id=camera["camera_id"],
                )
                camera["name"] = normalized_name
            if rtsp_url is not None and str(rtsp_url).strip():
                camera["rtsp_url"] = self._validate_rtsp_url(rtsp_url)
            camera["updated_at"] = time.time()
            self._write_unlocked(payload)
            return copy.deepcopy(camera)

    # 功能：删除或清理 `delete` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.lock`、`self._read_unlocked`、`self._find_unlocked`、`self._write_unlocked`、`copy.deepcopy`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def delete(self, camera_id: str) -> dict:
        with self.lock(exclusive=True):
            payload = self._read_unlocked()
            camera = self._find_unlocked(payload["cameras"], camera_id)
            payload["cameras"] = [
                item
                for item in payload["cameras"]
                if item["camera_id"] != camera["camera_id"]
            ]
            self._write_unlocked(payload)
            return copy.deepcopy(camera)

    # 功能：实现 `public` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera`（dict）：摄像头配置或实体
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_camera_registry.py` 的 `test_create_read_and_redact_camera`
    #         调用本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `AppService::get_camera_state`
    #         调用本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `create_app::department_create_camera`
    #         调用本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `create_app::department_update_camera` 调用本符号；另有 4 处静态调用
    #   - 内部调用：`copy.deepcopy`、`str`、`result.get`、`self._redact_rtsp_url`、`bool`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def public(self, camera: dict) -> dict:
        result = copy.deepcopy(camera)
        raw_url = str(result.get("rtsp_url", "") or "")
        result["rtsp_url"] = self._redact_rtsp_url(raw_url)
        result["has_rtsp_url"] = bool(raw_url)
        return result

    # 功能：检查或判断 `validate_rtsp_url` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `rtsp_url`（str）：`rtsp_url` 对应的业务输入值
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/main.py` 的 `create_app::department_test_camera`
    #         调用本符号；`AiVision/integrations/security_vlm/src/main.py` 的 `create_app::test_camera` 调用本符号
    #   - 内部调用：`cls._validate_rtsp_url`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @classmethod
    def validate_rtsp_url(cls, rtsp_url: str) -> str:
        return cls._validate_rtsp_url(rtsp_url)

    # 功能：检查或判断 `validate_camera_id` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::migrate_legacy`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::_validate_camera_records`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::_find_unlocked` 调用本符号
    #   - 内部调用：`validate_camera_id`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def validate_camera_id(camera_id: str) -> str:
        return validate_camera_id(camera_id)

    # 功能：首次升级时把旧单路配置迁移为固定 ID 的摄像头记录；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `cfg`（dict）：运行配置对象
    #   - `staff_dir`（Path）：`staff_dir` 对应的业务输入值
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_camera_registry.py` 的
    #         `test_legacy_migration_is_idempotent_and_copies_roi`
    #         调用本符号；`AiVision/integrations/security_vlm/tests/test_camera_registry.py` 的
    #         `test_migration_does_nothing_without_legacy_source` 调用本符号；`AiVision/integrations/security_vlm/src/main.py` 的
    #         `AppService::__init__` 调用本符号
    #   - 内部调用：`self.lock`、`ValueError`、`self.path.exists`、`cfg.get`、`str(data_cfg.get('input_video', '') or
    #          '').strip`、`str`、`data_cfg.get`、`self._validate_rtsp_url`、`time.time`、`self._write_unlocked` 等共 17 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
    def migrate_legacy(self, cfg: dict, staff_dir: Path) -> dict | None:
        """首次升级时把旧单路配置迁移为固定 ID 的摄像头记录。"""
        with self.lock(exclusive=True):
            if self.department != "general_electric":
                raise ValueError("旧单路配置只能迁移到通用电气事业部")
            if self.path.exists():
                return None
            data_cfg = cfg.get("data", {}) or {}
            source = str(data_cfg.get("input_video", "") or "").strip()
            if not source:
                return None
            source = self._validate_rtsp_url(source)
            now = time.time()
            camera = {
                "camera_id": "legacy-default",
                "name": "默认安检摄像头",
                "rtsp_url": source,
                "created_at": now,
                "updated_at": now,
            }
            self._write_unlocked({
                "version": self.VERSION,
                "department": self.department,
                "cameras": [camera],
            })

            staff_path = Path(staff_dir)
            legacy_video_id = self.validate_camera_id(
                data_cfg.get("video_id", "stream") or "stream"
            )
            legacy_roi_path = staff_path / f"{legacy_video_id}_staff_rois.json"
            migrated_roi_path = staff_path / "legacy-default_staff_rois.json"
            if legacy_roi_path.exists() and not migrated_roi_path.exists():
                migrated_roi_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy_roi_path, migrated_roi_path)
            return copy.deepcopy(camera)

    # 功能：读取或查询 `_read_unlocked` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::initialize`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::list`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::get`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::create` 调用本符号；另有 6 处静态调用
    #   - 内部调用：`self.path.exists`、`self._empty_payload`、`json.loads`、`self.path.read_text`、`RuntimeError`、`isinstance`、`payload.get`、`self._validate_camera_records`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def _read_unlocked(self) -> dict:
        if not self.path.exists():
            return self._empty_payload()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"摄像头注册表读取失败: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("摄像头注册表格式无效")
        cameras = payload.get("cameras")
        if payload.get("version") != self.VERSION or not isinstance(cameras, list):
            raise RuntimeError("摄像头注册表格式无效")
        stored_department = payload.get("department")
        if stored_department != self.department:
            raise RuntimeError(
                "摄像头注册表事业部不匹配: "
                f"期望 {self.department}, 实际 {stored_department!r}"
            )
        self._validate_camera_records(cameras)
        return {
            "version": self.VERSION,
            "department": self.department,
            "cameras": cameras,
        }

    # 功能：更新或保存 `_write_unlocked` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `payload`（dict）：接口或事件携带的业务数据
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::initialize`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::create`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::update`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::delete` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`self.path.parent.mkdir`、`self.path.with_name`、`uuid.uuid4`、`temp_path.write_text`、`json.dumps`、`os.chmod`、`temp_path.replace`、`temp_path.unlink`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    def _write_unlocked(self, payload: dict) -> None:
        persisted = {
            "version": self.VERSION,
            "department": self.department,
            "cameras": payload["cameras"],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(
            f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(persisted, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.chmod(temp_path, 0o600)
            temp_path.replace(self.path)
        finally:
            temp_path.unlink(missing_ok=True)

    # 功能：实现 `_empty_payload` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::initialize`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::_read_unlocked` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _empty_payload(self) -> dict:
        return {
            "version": self.VERSION,
            "department": self.department,
            "cameras": [],
        }

    # 功能：检查或判断 `_validate_camera_records` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `cameras`（list[dict]）：`cameras` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::_read_unlocked` 调用本符号
    #   - 内部调用：`len`、`RuntimeError`、`set`、`isinstance`、`cls.validate_camera_id`、`camera.get`、`str(camera.get('name', '') or
    #          '').strip`、`str`、`name.casefold`、`cls._validate_rtsp_url` 等共 13 个调用。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @classmethod
    def _validate_camera_records(cls, cameras: list[dict]) -> None:
        if len(cameras) > cls.MAX_CAMERAS:
            raise RuntimeError("摄像头注册表格式无效: 摄像头数量超过限制")
        camera_ids: set[str] = set()
        names: set[str] = set()
        for camera in cameras:
            if not isinstance(camera, dict):
                raise RuntimeError("摄像头注册表格式无效: 摄像头记录必须是对象")
            try:
                camera_id = cls.validate_camera_id(camera.get("camera_id"))
            except ValueError as exc:
                raise RuntimeError(
                    "摄像头注册表格式无效: camera_id 无效"
                ) from exc
            name = str(camera.get("name", "") or "").strip()
            if not name:
                raise RuntimeError("摄像头注册表格式无效: 摄像头字段缺失")
            if camera_id in camera_ids or name.casefold() in names:
                raise RuntimeError("摄像头注册表格式无效: 摄像头记录重复")
            try:
                cls._validate_rtsp_url(camera.get("rtsp_url", ""))
                float(camera["created_at"])
                float(camera["updated_at"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("摄像头注册表格式无效: 摄像头字段无效") from exc
            camera_ids.add(camera_id)
            names.add(name.casefold())

    # 功能：检查或判断 `_validate_name` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `name`（str）：业务对象名称
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::create`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::update` 调用本符号
    #   - 内部调用：`str(name or '').strip`、`str`、`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @staticmethod
    def _validate_name(name: str) -> str:
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("摄像头名称不能为空")
        return normalized

    # 功能：检查或判断 `_validate_rtsp_url` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `rtsp_url`（str）：`rtsp_url` 对应的业务输入值
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::create`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::update`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::validate_rtsp_url`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::migrate_legacy` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`str(rtsp_url or '').strip`、`str`、`urlsplit`、`parsed.scheme.lower`、`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @staticmethod
    def _validate_rtsp_url(rtsp_url: str) -> str:
        normalized = str(rtsp_url or "").strip()
        parsed = urlsplit(normalized)
        if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.netloc:
            raise ValueError("摄像头地址必须是有效的 RTSP/RTSPS 地址")
        return normalized

    # 功能：检查或判断 `_ensure_unique_name` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cameras`（list[dict]）：`cameras` 对应的业务输入值
    #   - `name`（str）：业务对象名称
    #   - `exclude_camera_id`（str | None）：`exclude_camera_id` 对应业务对象的唯一标识；默认值为 `None`
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::create`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::update` 调用本符号
    #   - 内部调用：`name.casefold`、`camera.get`、`str(camera.get('name', '')).strip().casefold`、`str(camera.get('name',
    #          '')).strip`、`str`、`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @staticmethod
    def _ensure_unique_name(
        cameras: list[dict],
        name: str,
        *,
        exclude_camera_id: str | None = None,
    ) -> None:
        wanted = name.casefold()
        for camera in cameras:
            if camera.get("camera_id") == exclude_camera_id:
                continue
            if str(camera.get("name", "")).strip().casefold() == wanted:
                raise ValueError(f"摄像头名称已存在: {name}")

    # 功能：读取或查询 `_find_unlocked` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `cameras`（list[dict]）：`cameras` 对应的业务输入值
    #   - `camera_id`（str）：摄像头唯一标识
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::update`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::delete` 调用本符号
    #   - 内部调用：`cls.validate_camera_id`、`camera.get`、`KeyError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @classmethod
    def _find_unlocked(cls, cameras: list[dict], camera_id: str) -> dict:
        wanted = cls.validate_camera_id(camera_id)
        for camera in cameras:
            if camera.get("camera_id") == wanted:
                return camera
        raise KeyError(f"摄像头不存在: {wanted}")

    # 功能：实现 `lock` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `exclusive`（bool）：`exclusive` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::initialize`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::list`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::get`
    #         调用本符号；`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::create` 调用本符号；另有 6 处静态调用
    #   - 内部调用：`self.path.parent.mkdir`、`os.open`、`os.fchmod`、`fcntl.flock`、`os.close`。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件。
    @contextmanager
    def lock(self, *, exclusive: bool):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            descriptor = os.open(
                self.lock_path,
                os.O_CREAT | os.O_RDWR,
                0o600,
            )
            try:
                os.fchmod(descriptor, 0o600)
                operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(descriptor, operation)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    # 功能：实现 `_redact_rtsp_url` 对应的摄像头、资源注册逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `rtsp_url`（str）：`rtsp_url` 对应的业务输入值
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/src/camera_registry.py` 的 `CameraRegistry::public` 调用本符号
    #   - 内部调用：`rtsp_url.rsplit`、`prefix.split`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _redact_rtsp_url(rtsp_url: str) -> str:
        if "@" not in rtsp_url:
            return rtsp_url
        prefix, location = rtsp_url.rsplit("@", 1)
        scheme = prefix.split("://", 1)[0]
        return f"{scheme}://***:***@{location}"
