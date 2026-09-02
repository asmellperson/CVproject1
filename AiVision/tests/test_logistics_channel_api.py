# 文件说明：包含接口访问的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import asyncio
import importlib
import sys
from copy import deepcopy

import anyio.to_thread
import httpx
import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import ResponseValidationError
from fastapi.routing import serialize_response

sys.modules.pop("platform", None)
api = importlib.import_module("api.logistics_channels")
compat_api = importlib.import_module("api.compat")

FEATURES = tuple(sorted(importlib.import_module(
    "platform.logistics_channel.constants"
).LOGISTICS_FEATURES))
ADMIN = {"role": "admin", "department": None}


# 功能：定义 `FakeService` 类，封装接口访问相关的状态、约束与操作
# 参数：无。
# 返回：FakeService；返回新建的 `FakeService` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeService:
    # 功能：初始化或配置 `__init__` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        self.channels = {feature: {} for feature in FEATURES}
        self.next_id = 1
        self.calls = []
        self.error = None

    # 功能：实现 `_raise` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_api.py` 的 `FakeService::create_channel`
    #         调用本符号；`AiVision/tests/test_logistics_channel_api.py` 的 `FakeService::update_channel`
    #         调用本符号；`AiVision/tests/test_logistics_channel_api.py` 的 `FakeService::update_config`
    #         调用本符号；`AiVision/tests/test_logistics_channel_api.py` 的 `FakeService::add_existing_camera` 调用本符号
    #   - 内部调用：`ValueError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def _raise(self):
        if self.error:
            raise ValueError(self.error)

    # 功能：读取或查询 `list_channels` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`deepcopy`、`self.channels[feature].values`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_channels(self, feature):
        return {"items": [deepcopy(value) for value in self.channels[feature].values()]}

    # 功能：按摄像头 ID 聚合指定物流功能的测试通道成员，模拟业务服务的安全清单输出。
    # 参数：
    #   - `self`：当前测试服务实例
    #   - `feature_names`（list[str] | tuple[str, ...]）：待汇总的授权物流功能
    # 返回：list[dict]；返回按物理摄像头去重的测试清单。
    # 调用关系：
    #   - 调用方：`list_logistics_camera_inventory` 路由调用本方法
    #   - 内部调用：`dict.setdefault`、`deepcopy`、`list.sort`。
    # 副作用/注意事项：仅读取当前实例的内存通道数据，不包含 RTSP 地址。
    def list_camera_inventory(self, feature_names):
        inventory = {}
        for feature in feature_names:
            for channel in self.channels[feature].values():
                for member in channel["members"]:
                    camera_id = member["camera_id"]
                    item = inventory.setdefault(camera_id, {
                        "camera_id": camera_id,
                        "name": f"物流摄像头 {camera_id}",
                        "shm_name": f"camera_{camera_id}",
                        "department": api.LOGISTICS_FEATURE_DEPARTMENTS[feature],
                        "enabled": True,
                        "memberships": [],
                    })
                    item["memberships"].append({
                        "feature_name": feature,
                        "channel_id": channel["id"],
                        "channel_name": channel["name"],
                        "enabled": bool(channel["enabled"] and member["enabled"]),
                    })
        items = list(inventory.values())
        for item in items:
            item["memberships"].sort(key=lambda membership: (
                membership["feature_name"],
                membership["channel_id"],
            ))
        items.sort(key=lambda item: item["camera_id"])
        return deepcopy(items)

    # 功能：读取或查询 `get_channel` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`deepcopy`、`self.channels[feature].get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_channel(self, feature, channel_id):
        return deepcopy(self.channels[feature].get(channel_id))

    # 功能：创建或构建 `create_channel` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `name`（未显式标注）：业务对象名称
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._raise`、`deepcopy`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def create_channel(self, feature, name):
        self._raise()
        channel_id = self.next_id
        self.next_id += 1
        value = {
            "id": channel_id, "name": name, "feature_name": feature,
            "enabled": True, "sort_order": 0,
            "config": {
                "detection_start": "08:00:00",
                "detection_end": "20:00:00",
                "confidence_threshold": 0.3,
                "empty_grace_seconds": 2,
                "multi_grace_seconds": 1,
                "alarm_interval": 5,
                "alarm": {},
            },
            "members": [],
        }
        self.channels[feature][channel_id] = value
        return deepcopy(value)

    # 功能：更新或保存 `update_channel` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    #   - `payload`（未显式标注）：接口或事件携带的业务数据
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_api.py` 的 `FakeService::update_channel_and_config` 调用本符号
    #   - 内部调用：`self._raise`、`self.channels[feature].get`、`value.update`、`deepcopy`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_channel(self, feature, channel_id, payload):
        self._raise()
        value = self.channels[feature].get(channel_id)
        if value is not None:
            value.update(payload)
        return deepcopy(value)

    # 功能：更新或保存 `update_config` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    #   - `payload`（未显式标注）：接口或事件携带的业务数据
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_api.py` 的 `FakeService::update_channel_and_config` 调用本符号
    #   - 内部调用：`self._raise`、`self.channels[feature].get`、`payload.model_dump`、`value['config'].update`、`self.calls.append`、`deepcopy`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_config(self, feature, channel_id, payload):
        self._raise()
        value = self.channels[feature].get(channel_id)
        if value is None:
            return None
        update = payload.model_dump(exclude_unset=True)
        value["config"].update(update)
        self.calls.append(("config", feature, channel_id, update))
        return deepcopy(value)

    # 功能：更新或保存 `update_channel_and_config` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    #   - `metadata`（未显式标注）：`metadata` 对应的业务输入值
    #   - `config`（未显式标注）：运行配置对象
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.update_channel`、`self.update_config`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_channel_and_config(self, feature, channel_id, metadata, config):
        value = self.update_channel(feature, channel_id, metadata)
        if value is None or config is None:
            return value
        return self.update_config(feature, channel_id, config)

    # 功能：删除或清理 `delete_channel` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.channels[feature].pop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def delete_channel(self, feature, channel_id):
        return self.channels[feature].pop(channel_id, None) is not None

    # 功能：创建或构建 `add_existing_camera` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_api.py` 的 `FakeService::create_camera_and_bind` 调用本符号
    #   - 内部调用：`self._raise`、`value['members'].append`、`len`、`deepcopy`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def add_existing_camera(self, feature, channel_id, camera_id):
        self._raise()
        value = self.channels[feature][channel_id]
        value["members"].append({
            "id": len(value["members"]) + 1, "channel_id": channel_id,
            "camera_id": camera_id, "enabled": True,
            "sort_order": len(value["members"]),
        })
        return deepcopy(value)

    # 功能：创建或构建 `create_camera_and_bind` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    #   - `payload`（未显式标注）：接口或事件携带的业务数据
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.calls.append`、`self.add_existing_camera`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def create_camera_and_bind(self, feature, channel_id, payload):
        self.calls.append(("create_camera", feature, channel_id, payload.name, payload.url))
        return self.add_existing_camera(feature, channel_id, 99)

    # 功能：实现 `reorder_members` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    #   - `camera_ids`（未显式标注）：`camera_ids` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`enumerate`、`deepcopy`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def reorder_members(self, feature, channel_id, camera_ids):
        value = self.channels[feature][channel_id]
        members = {member["camera_id"]: member for member in value["members"]}
        value["members"] = [members[camera_id] for camera_id in camera_ids]
        for index, member in enumerate(value["members"]):
            member["sort_order"] = index
        return deepcopy(value)

    # 功能：实现 `move_camera` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.calls.append`、`deepcopy`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def move_camera(self, feature, camera_id, channel_id):
        self.calls.append(("move", feature, camera_id, channel_id))
        return deepcopy(self.channels[feature][channel_id])

    # 功能：删除或清理 `remove_camera` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.channels[feature].get`、`len`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def remove_camera(self, feature, channel_id, camera_id):
        value = self.channels[feature].get(channel_id)
        if value is None:
            return False
        before = len(value["members"])
        value["members"] = [m for m in value["members"] if m["camera_id"] != camera_id]
        return len(value["members"]) != before

    # 功能：更新或保存 `set_member_enabled` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `enabled`（未显式标注）：是否启用相应能力
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.channels[feature].get`、`ValueError`、`next`、`self.calls.append`、`deepcopy`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def set_member_enabled(self, feature, channel_id, camera_id, enabled):
        value = self.channels[feature].get(channel_id)
        if value is None:
            raise ValueError(f"物流通道不存在: {channel_id}")
        member = next((m for m in value["members"] if m["camera_id"] == camera_id), None)
        if member is None:
            raise ValueError("通道摄像头成员不存在")
        member["enabled"] = enabled
        self.calls.append(("member_enabled", feature, channel_id, camera_id, enabled))
        return deepcopy(value)


# 功能：定义 `FakeFeatureService` 类，封装接口访问相关的状态、约束与操作
# 参数：无。
# 返回：FakeFeatureService；返回新建的 `FakeFeatureService` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_api.py` 的 `test_real_asgi_auth_permissions_and_endpoint_contracts`
#         实例化本符号；`AiVision/tests/test_logistics_channel_api.py` 的
#         `test_generic_feature_config_http_cannot_bypass_logistics_membership_guard`
#         实例化本符号；`AiVision/tests/test_logistics_channel_api.py` 的 `test_generic_feature_camera_create_uses_atomic_camera_service`
#         实例化本符号；`AiVision/tests/test_logistics_channel_api.py` 的
#         `test_legacy_logistics_config_reads_require_department_and_membership` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeFeatureService:
    # 功能：初始化或配置 `__init__` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        self.calls = []

    # 功能：实现 `_response` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `spec`（未显式标注）：`spec` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_api.py` 的 `FakeFeatureService::get_config`
    #         调用本符号；`AiVision/tests/test_logistics_channel_api.py` 的 `FakeFeatureService::save_config` 调用本符号
    #   - 内部调用：`str`、`raw_camera_id.startswith`、`raw_camera_id.removeprefix`、`int`、`spec.config_schema().model_dump`、`spec.config_schema`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    @staticmethod
    def _response(spec, camera_id):
        raw_camera_id = str(camera_id)
        if raw_camera_id.startswith("camera_"):
            raw_camera_id = raw_camera_id.removeprefix("camera_")
        return {
            "camera": {
                "id": int(raw_camera_id),
                "name": f"摄像头-{camera_id}",
                "shm_name": f"camera_{camera_id}",
                "enable": True,
            },
            "feature": spec.name,
            "config": spec.config_schema().model_dump(),
        }

    # 功能：读取或查询 `get_config` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `spec`（未显式标注）：`spec` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.calls.append`、`int`、`self._response`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_config(self, spec, camera_id):
        if camera_id == "missing":
            return None
        self.calls.append(("get", spec.name, int(camera_id)))
        return self._response(spec, camera_id)

    # 功能：更新或保存 `save_config` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `spec`（未显式标注）：`spec` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `payload`（未显式标注）：接口或事件携带的业务数据
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.calls.append`、`int`、`self._response`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def save_config(self, spec, camera_id, payload):
        self.calls.append(("save", spec.name, int(camera_id), payload))
        result = self._response(spec, camera_id)
        result["config"] = payload
        return result


# 功能：定义 `FakeOrchestrator` 类，封装接口访问相关的状态、约束与操作
# 参数：无。
# 返回：FakeOrchestrator；返回新建的 `FakeOrchestrator` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_api.py` 的 `test_real_asgi_auth_permissions_and_endpoint_contracts`
#         实例化本符号；`AiVision/tests/test_logistics_channel_api.py` 的 `test_status_response_and_composite_jpeg_semantics` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeOrchestrator:
    status = None
    frame = None

    # 功能：读取或查询 `get_logistics_channel_status` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`deepcopy`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_logistics_channel_status(self, feature, channel_id):
        return deepcopy(self.status)

    # 功能：读取或查询 `get_logistics_channel_frame` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（未显式标注）：`feature` 对应的业务输入值
    #   - `channel_id`（未显式标注）：`channel_id` 对应业务对象的唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_logistics_channel_frame(self, feature, channel_id):
        return self.frame


# 功能：定义 `EmptyAlarmQuery` 类，封装接口访问相关的状态、约束与操作
# 参数：无。
# 返回：EmptyAlarmQuery；返回新建的 `EmptyAlarmQuery` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_api.py` 的 `EmptyAlarmSession::query` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class EmptyAlarmQuery:
    # 功能：实现 `filter` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `*_args`（未显式标注）：`_args` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_delete_expired_records`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_enforce_size_limit`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_referenced_paths`
    #         调用本符号；`AiVision/platform/violation/service.py` 的 `AsyncViolationWriter::update_video_status` 调用本符号；另有 31 处静态调用
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def filter(self, *_args):
        return self

    # 功能：实现 `order_by` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `*_args`（未显式标注）：`_args` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_violation_media_cleanup.py` 的 `test_cleanup_deletes_expired_records_files_and_historical_orphans`
    #         调用本符号；`AiVision/tests/test_violation_media_cleanup.py` 的 `test_cleanup_capacity_removes_oldest_database_backed_image`
    #         调用本符号；`AiVision/tests/test_violation_media_cleanup.py` 的
    #         `test_cleanup_capacity_keeps_fresh_image_during_push_grace_period` 调用本符号；`AiVision/platform/violation/cleanup.py` 的
    #         `ViolationMediaCleaner::_delete_expired_records` 调用本符号；另有 9 处静态调用
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def order_by(self, *_args):
        return self

    # 功能：实现 `limit` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `_limit`（未显式标注）：`_limit` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_delete_expired_records`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_enforce_size_limit`
    #         调用本符号；`AiVision/api/alarms.py` 的 `list_alarms` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def limit(self, _limit):
        return self

    # 功能：实现 `all` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_delete_expired_records`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_enforce_size_limit`
    #         调用本符号；`AiVision/platform/violation/cleanup.py` 的 `ViolationMediaCleaner::_referenced_paths`
    #         调用本符号；`AiVision/tests/test_logistics_channel_runtime.py` 的
    #         `test_inactive_detection_window_still_composes_live_preview_frames` 调用本符号；另有 40 处静态调用
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def all(self):
        return []


# 功能：定义 `EmptyAlarmSession` 类，封装接口访问相关的状态、约束与操作
# 参数：无。
# 返回：EmptyAlarmSession；返回新建的 `EmptyAlarmSession` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class EmptyAlarmSession:
    # 功能：读取或查询 `query` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `_model`（未显式标注）：`_model` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`EmptyAlarmQuery`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def query(self, _model):
        return EmptyAlarmQuery()

    # 功能：停止并释放 `close` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def close(self):
        return None


# 功能：实现 `_seed` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service`（未显式标注）：`service` 对应的业务输入值
#   - `feature`（未显式标注）：`feature` 对应的业务输入值；默认值为 `FEATURES[0]`
#   - `name`（未显式标注）：业务对象名称；默认值为 `'一号通道'`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_api.py` 的 `test_real_asgi_auth_permissions_and_endpoint_contracts`
#         调用本符号；`AiVision/tests/test_logistics_channel_api.py` 的
#         `test_legacy_logistics_config_reads_require_department_and_membership`
#         调用本符号；`AiVision/tests/test_logistics_channel_api.py` 的 `test_member_bind_create_reorder_move_and_remove`
#         调用本符号；`AiVision/tests/test_logistics_channel_api.py` 的 `test_status_response_and_composite_jpeg_semantics` 调用本符号
#   - 内部调用：`service.create_channel`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _seed(service, feature=FEATURES[0], name="一号通道"):
    return service.create_channel(feature, name)


# 功能：验证 `test_router_exposes_full_channel_contract_and_app_registers_it` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`importlib.import_module`、`set`、`getattr`、`registered_paths.add`、`registered_paths.update`、`any`、`path.startswith`、`app_module.app.openapi`、`openapi['paths'].items`、`methods.items`
#          等共 12 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
def test_router_exposes_full_channel_contract_and_app_registers_it():
    paths = {(route.path, method) for route in api.router.routes for method in route.methods}
    expected = {
        ("/api/logistics-channels/inventory", "GET"),
        ("/api/logistics-channels/{feature}", "GET"),
        ("/api/logistics-channels/{feature}", "POST"),
        ("/api/logistics-channels/{feature}/{channel_id}", "GET"),
        ("/api/logistics-channels/{feature}/{channel_id}", "PUT"),
        ("/api/logistics-channels/{feature}/{channel_id}", "DELETE"),
        ("/api/logistics-channels/{feature}/{channel_id}/cameras", "POST"),
        ("/api/logistics-channels/{feature}/{channel_id}/cameras/order", "PUT"),
        ("/api/logistics-channels/{feature}/{channel_id}/cameras/{camera_id}/enabled", "PUT"),
        ("/api/logistics-channels/{feature}/{channel_id}/cameras/{camera_id}/config", "GET"),
        ("/api/logistics-channels/{feature}/{channel_id}/cameras/{camera_id}/config", "PUT"),
        ("/api/logistics-channels/{feature}/{channel_id}/status", "GET"),
        ("/api/logistics-channels/{feature}/{channel_id}/frame.jpg", "GET"),
        ("/api/logistics-channels/{feature}/{channel_id}/alarms", "GET"),
        ("/api/logistics-channels/{feature}/{channel_id}/statistics", "GET"),
    }
    assert expected <= paths
    app_module = importlib.import_module("api.app")
    registered_paths: set[str] = set()
    for route in app_module.app.routes:
        path = getattr(route, "path", None)
        if path:
            registered_paths.add(path)
        included_router = getattr(route, "original_router", None)
        if included_router is not None:
            registered_paths.update(
                child.path
                for child in included_router.routes
                if getattr(child, "path", None)
            )
    assert any(
        path.startswith("/api/logistics-channels")
        for path in registered_paths
    )

    openapi = app_module.app.openapi()
    for path, methods in openapi["paths"].items():
        if not path.startswith("/api/logistics-channels"):
            continue
        for method, operation in methods.items():
            if method == "parameters" or path.endswith("frame.jpg"):
                continue
            success_code = "201" if "201" in operation["responses"] else "200"
            schema = operation["responses"][success_code][
                "content"
            ]["application/json"]["schema"]
            assert schema.get("$ref") or schema.get("type") == "object"


# 功能：验证物流摄像头清单按通道成员关系汇总，并严格裁剪到多事业部用户授权范围。
# 参数：
#   - `monkeypatch`：pytest 补丁夹具，用于让同步 FastAPI 路由在受限测试环境内执行
# 返回：None；通过 HTTP 响应断言验证清单去重、权限、在线状态与敏感字段过滤。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（由 pytest 自动发现执行）
#   - 内部调用：`FakeService`、`FakeCameraService`、`FakeOrchestrator`、`FastAPI`、`httpx.AsyncClient`、`asyncio.run`。
# 副作用/注意事项：只操作内存 ASGI 应用和测试数据，不连接生产数据库或摄像头。
def test_logistics_camera_inventory_uses_membership_permissions_and_deduplicates(monkeypatch):
    service = FakeService()
    orchestrator = FakeOrchestrator()
    orchestrator.status = {
        "camera_states": {
            "7": {"camera_id": 7, "online": True},
        },
    }
    channel_specs = (
        ("detect_logistics_single_person", "通用物流通道", 7),
        (
            "detect_logistics_single_person_electrical_components",
            "电气部件物流通道",
            8,
        ),
        (
            "detect_logistics_single_person_electronics_electrician",
            "电子电工物流通道",
            9,
        ),
    )
    channel_ids = {}
    for feature, name, camera_id in channel_specs:
        channel = _seed(service, feature=feature, name=name)
        channel_ids[feature] = channel["id"]
        service.add_existing_camera(feature, channel["id"], camera_id)
    service.add_existing_camera(
        "detect_logistics_single_person_electrical_components",
        channel_ids["detect_logistics_single_person_electrical_components"],
        7,
    )

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_logistics_channel_service] = lambda: service
    app.dependency_overrides[api.get_current_orchestrator] = lambda: orchestrator
    app.dependency_overrides[api.get_current_user] = lambda: {
        "role": "viewer",
        "department": "general_electric",
        "departments": ["general_electric", "electrical_components"],
    }

    # 功能：在当前线程执行 FastAPI 同步依赖，避免受限测试环境创建 worker thread。
    # 参数：
    #   - `func`：待执行的同步函数
    #   - `*args`：传递给同步函数的位置参数
    #   - `**_kwargs`：AnyIO 附加参数，本测试无需使用
    # 返回：object；返回同步函数的执行结果。
    # 调用关系：
    #   - 调用方：AnyIO 在线程桥接同步路由时调用本函数
    #   - 内部调用：`func`。
    # 副作用/注意事项：仅改变本测试中的执行方式，不修改应用逻辑。
    async def inline_run_sync(func, *args, **_kwargs):
        return func(*args)

    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)

    # 功能：请求物流摄像头清单并校验 viewer 与 admin 的授权结果。
    # 参数：无。
    # 返回：None；所有校验通过后正常结束。
    # 调用关系：
    #   - 调用方：本测试末尾通过 `asyncio.run` 调用
    #   - 内部调用：`httpx.ASGITransport`、`httpx.AsyncClient.get`、`response.json`。
    # 副作用/注意事项：只向内存 ASGI 应用发起请求，不访问外部网络。
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/logistics-channels/inventory")
            assert response.status_code == 200
            items = response.json()["items"]
            assert [item["camera_id"] for item in items] == [7, 8]
            assert all("url" not in item for item in items)
            assert items[0]["online"] is True
            assert items[0]["memberships"][0]["channel_name"] == "通用物流通道"
            assert len(items[0]["memberships"]) == 2
            assert items[1]["department"] == "electrical_components"

            app.dependency_overrides[api.get_current_user] = lambda: ADMIN
            admin_response = await client.get("/api/logistics-channels/inventory")
            assert admin_response.status_code == 200
            assert [
                item["camera_id"] for item in admin_response.json()["items"]
            ] == [7, 8, 9]

    asyncio.run(scenario())


# 功能：验证 `test_fastapi_response_field_filters_and_rejects_invalid_output` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`next`、`asyncio.run`、`serialize_response`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_fastapi_response_field_filters_and_rejects_invalid_output():
    route = next(
        route for route in api.router.routes
        if route.path == "/api/logistics-channels/{feature}" and "GET" in route.methods
    )
    valid = {
        "items": [{
            "id": 1,
            "name": "一号通道",
            "feature_name": FEATURES[0],
            "enabled": True,
            "sort_order": 0,
            "server_only": "must be filtered",
        }],
        "server_only": "must be filtered",
    }
    encoded = asyncio.run(serialize_response(
        field=route.response_field,
        response_content=valid,
        is_coroutine=True,
    ))
    assert "server_only" not in encoded
    assert "server_only" not in encoded["items"][0]

    with pytest.raises(ResponseValidationError):
        asyncio.run(serialize_response(
            field=route.response_field,
            response_content={"items": [{"id": "invalid"}]},
            is_coroutine=True,
        ))


# 功能：验证 `test_real_asgi_auth_permissions_and_endpoint_contracts` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`FakeService`、`FakeOrchestrator`、`_seed`、`service.add_existing_camera`、`FakeFeatureService`、`FastAPI`、`app.include_router`、`monkeypatch.setattr`、`asyncio.run`、`scenario`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_real_asgi_auth_permissions_and_endpoint_contracts(monkeypatch):
    service = FakeService()
    orchestrator = FakeOrchestrator()
    channel = _seed(service)
    feature = "detect_logistics_single_person"
    channel_id = channel["id"]
    service.add_existing_camera(feature, channel_id, 7)
    feature_service = FakeFeatureService()
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_logistics_channel_service] = lambda: service
    app.dependency_overrides[api.get_current_orchestrator] = lambda: orchestrator
    app.dependency_overrides[api.get_feature_config_service] = lambda: feature_service
    monkeypatch.setattr(api, "get_session", EmptyAlarmSession)

    # 功能：启动或执行 `inline_run_sync` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `func`（未显式标注）：`func` 对应的业务输入值
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**_kwargs`（未显式标注）：`_kwargs` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`func`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def inline_run_sync(func, *args, **_kwargs):
        return func(*args)

    # 受限测试环境不允许 worker thread；仍通过完整 ASGI 路由/依赖/序列化栈请求。
    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)

    # 功能：实现 `scenario` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`httpx.ASGITransport`、`httpx.AsyncClient`、`client.get`、`member_config.json`、`client.request`、`client.post`、`created.json`、`client.put`、`np.zeros`、`frame.content.startswith`
    #          等共 12 个调用。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；可能启动、等待或停止线程/进程资源。
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            base = f"/api/logistics-channels/{feature}"
            assert (await client.get(base)).status_code == 401

            viewer = {"role": "viewer", "department": "general_electric"}
            app.dependency_overrides[api.get_current_user] = lambda: viewer
            assert (await client.get(base)).status_code == 200
            assert (await client.get(
                "/api/logistics-channels/"
                "detect_logistics_single_person_electronics_electrician"
            )).status_code == 403
            multi_department_viewer = {
                "role": "viewer",
                "department": "general_electric",
                "departments": ["general_electric", "electrical_components"],
            }
            app.dependency_overrides[api.get_current_user] = lambda: multi_department_viewer
            assert (await client.get(
                "/api/logistics-channels/"
                "detect_logistics_single_person_electrical_components"
            )).status_code == 200
            assert (await client.get(
                "/api/logistics-channels/"
                "detect_logistics_single_person_electronics_electrician"
            )).status_code == 403
            app.dependency_overrides[api.get_current_user] = lambda: viewer
            member_config_url = f"{base}/{channel_id}/cameras/7/config"
            member_config = await client.get(member_config_url)
            assert member_config.status_code == 200
            assert "url" not in member_config.json()["camera"]
            assert (await client.get(f"{base}/{channel_id}/cameras/999/config")).status_code == 404
            cross_config = (
                "/api/logistics-channels/"
                "detect_logistics_single_person_electronics_electrician/1/cameras/7/config"
            )
            assert (await client.get(cross_config)).status_code == 403

            write_requests = (
                ("POST", base, {"name": "禁止新增"}),
                ("PUT", f"{base}/{channel_id}", {"name": "禁止更新"}),
                ("DELETE", f"{base}/{channel_id}", None),
                ("PUT", f"{base}/{channel_id}/config", {"empty_grace_seconds": 3}),
                ("POST", f"{base}/{channel_id}/cameras", {"camera_id": 7}),
                ("PUT", f"{base}/{channel_id}/cameras/order", {"camera_ids": [7]}),
                ("PUT", f"{base}/{channel_id}/cameras/7", None),
                ("PUT", f"{base}/{channel_id}/cameras/7/enabled", {"enabled": False}),
                ("PUT", member_config_url, member_config.json()["config"]),
                ("DELETE", f"{base}/{channel_id}/cameras/7", None),
            )
            for method, url, payload in write_requests:
                response = await client.request(method, url, json=payload)
                assert response.status_code == 403, (method, url, response.text)

            app.dependency_overrides[api.require_admin] = lambda: ADMIN
            created = await client.post(base, json={"name": "管理员新增"})
            assert created.status_code == 201
            assert created.json()["name"] == "管理员新增"
            assert (await client.put(
                f"{base}/{channel_id}",
                json={"name": "管理员更新", "config": {"empty_grace_seconds": 3}},
            )).status_code == 200
            assert (await client.put(
                f"{base}/{channel_id}/config",
                json={"empty_grace_seconds": 4},
            )).status_code == 200
            assert (await client.post(
                f"{base}/{channel_id}/cameras",
                json={"camera_id": 7},
            )).status_code == 200
            assert (await client.put(
                f"{base}/{channel_id}/cameras/7/enabled",
                json={"enabled": False},
            )).status_code == 200
            assert (await client.put(
                member_config_url,
                json=member_config.json()["config"],
            )).status_code == 200
            assert (await client.get(
                "/api/logistics-channels/not-a-feature"
            )).status_code == 404
            assert (await client.post(base, json={})).status_code == 422
            assert (await client.put(
                f"{base}/{channel_id}/config",
                json={"detection_start": "20:00:00", "detection_end": "08:00:00"},
            )).status_code == 422

            assert (await client.get(f"{base}/{channel_id}/status")).status_code == 200
            assert (await client.get(f"{base}/{channel_id}/frame.jpg")).status_code == 503
            orchestrator.frame = np.zeros((60, 120, 3), dtype=np.uint8)
            frame = await client.get(f"{base}/{channel_id}/frame.jpg")
            assert frame.status_code == 200
            assert frame.headers["content-type"] == "image/jpeg"
            assert frame.content.startswith(b"\xff\xd8")
            alarms = await client.get(f"{base}/{channel_id}/alarms")
            assert alarms.status_code == 200
            assert alarms.json() == {"items": []}
            statistics = await client.get(f"{base}/{channel_id}/statistics")
            assert statistics.status_code == 200
            assert statistics.json()["summary"] == {"total": 0, "today": 0}

    asyncio.run(scenario())


# 功能：验证 `test_four_features_are_isolated_and_whitelisted` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`FakeService`、`enumerate`、`api.create_channel`、`api.LogisticsChannelCreate`、`api.list_channels`、`pytest.raises`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_four_features_are_isolated_and_whitelisted():
    service = FakeService()
    for index, feature in enumerate(FEATURES):
        api.create_channel(feature, api.LogisticsChannelCreate(name=f"通道-{index}"), ADMIN, service)
    for index, feature in enumerate(FEATURES):
        assert [item.name for item in api.list_channels(feature, ADMIN, service).items] == [f"通道-{index}"]
    with pytest.raises(HTTPException) as caught:
        api.list_channels("arbitrary", ADMIN, service)
    assert caught.value.status_code == 404


# 功能：验证 `test_viewer_department_access_and_admin_dependency_contract` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`api._require_feature_access`、`next`、`pytest.raises`、`any`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_viewer_department_access_and_admin_dependency_contract():
    general_feature = "detect_logistics_single_person"
    viewer = {"role": "viewer", "department": "general_electric"}
    assert api._require_feature_access(general_feature, viewer) == general_feature
    other = next(feature for feature in FEATURES if feature != general_feature)
    with pytest.raises(HTTPException) as caught:
        api._require_feature_access(other, viewer)
    assert caught.value.status_code == 403
    create_route = next(
        route for route in api.router.routes
        if route.path == "/api/logistics-channels/{feature}" and "POST" in route.methods
    )
    assert any(dependency.call.__name__ == "require_admin" for dependency in create_route.dependant.dependencies)


# 功能：验证 `test_generic_feature_config_http_cannot_bypass_logistics_membership_guard` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`importlib.import_module`、`FakeFeatureService`、`FastAPI`、`app.include_router`、`feature_api.create_features_router`、`monkeypatch.setattr`、`asyncio.run`、`scenario`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_generic_feature_config_http_cannot_bypass_logistics_membership_guard(monkeypatch):
    feature_api = importlib.import_module("api.features")
    feature_service = FakeFeatureService()
    app = FastAPI()
    app.include_router(feature_api.create_features_router(feature_service))

    # 功能：启动或执行 `inline_run_sync` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `func`（未显式标注）：`func` 对应的业务输入值
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**_kwargs`（未显式标注）：`_kwargs` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`func`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def inline_run_sync(func, *args, **_kwargs):
        return func(*args)

    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)

    # 功能：实现 `scenario` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`httpx.ASGITransport`、`httpx.AsyncClient`、`client.get`、`allowed.json`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            path = f"/api/features/{FEATURES[0]}/configs/7"
            app.dependency_overrides[feature_api.get_current_user] = lambda: {
                "role": "viewer",
                "department": "general_electric",
            }
            denied = await client.get(path)
            assert denied.status_code == 403
            assert feature_service.calls == []

            app.dependency_overrides[feature_api.get_current_user] = lambda: ADMIN
            allowed = await client.get(path)
            assert allowed.status_code == 200
            assert "url" not in allowed.json()["camera"]

    asyncio.run(scenario())


# 功能：验证 `test_generic_feature_camera_create_uses_atomic_camera_service` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`importlib.import_module`、`FakeFeatureService`、`FakeCameraService`、`FastAPI`、`app.include_router`、`feature_api.create_features_router`、`monkeypatch.setattr`、`asyncio.run`、`scenario`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_generic_feature_camera_create_uses_atomic_camera_service(monkeypatch):
    feature_api = importlib.import_module("api.features")
    feature_service = FakeFeatureService()

    # 功能：定义 `FakeCameraService` 类，封装接口访问相关的状态、约束与操作
    # 参数：无。
    # 返回：FakeCameraService；返回新建的 `FakeCameraService` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_logistics_channel_api.py` 的 `test_generic_feature_camera_create_uses_atomic_camera_service`
    #         实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeCameraService:
        # 功能：初始化或配置 `__init__` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；初始化当前实例，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：会更新当前实例的运行状态。
        def __init__(self):
            self.calls = []

        # 功能：创建或构建 `create_camera_for_feature` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        #   - `feature`（未显式标注）：`feature` 对应的业务输入值
        #   - `payload`（未显式标注）：接口或事件携带的业务数据
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`self.calls.append`、`payload.get`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def create_camera_for_feature(self, feature, payload):
            self.calls.append((feature, payload))
            return {
                "id": "camera_21",
                "camera_id": 21,
                "name": payload["name"],
                "shm_name": "camera_21",
                "url": payload["url"],
                "enabled": True,
                "department": payload.get("department"),
                "functions": {feature: True},
            }

    camera_service = FakeCameraService()
    app = FastAPI()
    app.include_router(feature_api.create_features_router(
        feature_service,
        camera_service=camera_service,
    ))
    app.dependency_overrides[feature_api.require_admin] = lambda: ADMIN

    # 功能：启动或执行 `inline_run_sync` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `func`（未显式标注）：`func` 对应的业务输入值
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**_kwargs`（未显式标注）：`_kwargs` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`func`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def inline_run_sync(func, *args, **_kwargs):
        return func(*args)

    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)

    # 功能：实现 `scenario` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`httpx.ASGITransport`、`httpx.AsyncClient`、`client.post`、`response.json`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/features/detect_human/cameras",
                json={
                    "name": "后门摄像头",
                    "url": "rtsp://example/human",
                    "department": "general_electric",
                },
            )
            assert response.status_code == 200
            assert response.json()["functions"] == {"detect_human": True}
            assert camera_service.calls == [(
                "detect_human",
                {
                    "name": "后门摄像头",
                    "url": "rtsp://example/human",
                    "fps": 5,
                    "max_restart": 10,
                    "enabled": True,
                    "department": "general_electric",
                },
            )]

    asyncio.run(scenario())


# 功能：验证 `test_legacy_logistics_config_reads_require_department_and_membership` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
#   - `feature`（未显式标注）：`feature` 对应的业务输入值
#   - `legacy_path`（未显式标注）：`legacy_path` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`FakeService`、`_seed`、`service.add_existing_camera`、`FakeFeatureService`、`FastAPI`、`app.include_router`、`monkeypatch.setattr`、`asyncio.run`、`scenario`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    ("feature", "legacy_path"),
    [
        (
            "detect_logistics_single_person",
            "/api/ai/logistics-single-person-config",
        ),
        (
            "detect_logistics_single_person_electronics_electrician",
            "/api/ai/logistics-single-person-electronics-electrician-config",
        ),
        (
            "detect_logistics_single_person_electrical_components",
            "/api/ai/logistics-single-person-electrical-components-config",
        ),
        (
            "detect_logistics_single_person_precious_metal_recycling",
            "/api/ai/logistics-single-person-precious-metal-recycling-config",
        ),
    ],
)
def test_legacy_logistics_config_reads_require_department_and_membership(
    monkeypatch,
    feature,
    legacy_path,
):
    service = FakeService()
    channel = _seed(service, feature=feature)
    service.add_existing_camera(feature, channel["id"], 7)
    feature_service = FakeFeatureService()
    app = FastAPI()
    app.include_router(compat_api.router)
    app.dependency_overrides[compat_api.get_logistics_channel_service] = lambda: service
    app.dependency_overrides[compat_api.get_feature_config_service] = lambda: feature_service

    # 功能：启动或执行 `inline_run_sync` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `func`（未显式标注）：`func` 对应的业务输入值
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**_kwargs`（未显式标注）：`_kwargs` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`func`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    async def inline_run_sync(func, *args, **_kwargs):
        return func(*args)

    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_run_sync)

    # 功能：实现 `scenario` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`httpx.ASGITransport`、`httpx.AsyncClient`、`client.get`、`client.put`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            def unauthenticated():
                raise HTTPException(status_code=401, detail="not authenticated")

            app.dependency_overrides[compat_api.get_current_user] = unauthenticated
            assert (await client.get(f"{legacy_path}/7")).status_code == 401

            viewer = {
                "role": "viewer",
                "department": api.LOGISTICS_FEATURE_DEPARTMENTS[feature],
            }
            app.dependency_overrides[compat_api.get_current_user] = lambda: viewer
            assert (await client.get(f"{legacy_path}/7")).status_code == 200
            assert (await client.get(f"{legacy_path}/8")).status_code == 403
            assert (await client.put(f"{legacy_path}/7", json={})).status_code == 403

            app.dependency_overrides[compat_api.get_current_user] = lambda: {
                "role": "viewer",
                "department": "cross_department",
            }
            assert (await client.get(f"{legacy_path}/7")).status_code == 403

            app.dependency_overrides[compat_api.get_current_user] = lambda: ADMIN
            assert (await client.get(f"{legacy_path}/7")).status_code == 200
            assert (await client.get(f"{legacy_path}/8")).status_code == 200
            assert (await client.get(f"{legacy_path}/missing")).status_code == 404

    asyncio.run(scenario())


# 功能：验证 `test_crud_config_and_validation_models` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`FakeService`、`api.create_channel`、`api.LogisticsChannelCreate`、`api.LogisticsChannelPutRequest`、`api.update_channel`、`api.get_channel`、`api.delete_channel`、`pytest.raises`、`api.LogisticsChannelConfigUpdate`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_crud_config_and_validation_models():
    service = FakeService()
    channel = api.create_channel(FEATURES[0], api.LogisticsChannelCreate(name="初始"), ADMIN, service)
    payload = api.LogisticsChannelPutRequest(
        name="更新",
        config={
            "detection_start": "09:00:00", "detection_end": "18:00:00",
            "confidence_threshold": 0.42,
            "empty_grace_seconds": 3,
        },
    )
    result = api.update_channel(FEATURES[0], channel.id, payload, ADMIN, service)
    assert result.name == "更新"
    assert result.config.confidence_threshold == 0.42
    assert result.config.empty_grace_seconds == 3
    assert api.get_channel(FEATURES[0], channel.id, ADMIN, service).name == "更新"
    assert api.delete_channel(FEATURES[0], channel.id, ADMIN, service).ok is True
    with pytest.raises(HTTPException) as caught:
        api.get_channel(FEATURES[0], channel.id, ADMIN, service)
    assert caught.value.status_code == 404

    with pytest.raises(ValueError):
        api.LogisticsChannelConfigUpdate(
            detection_start="20:00:00", detection_end="08:00:00"
        )
    with pytest.raises(ValueError):
        api.LogisticsChannelConfigUpdate(roi_pos=[[0, 0], [1, 1]])
    with pytest.raises(ValueError):
        api.LogisticsChannelConfigUpdate(confidence_threshold=1.01)
    with pytest.raises(ValueError):
        api.LogisticsChannelConfigUpdate(
            alarm={"wechat": {"enabled": True, "user": "operator", "corp_secret": "secret"}}
        )


# 功能：验证 `test_member_bind_create_reorder_move_and_remove` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`FakeService`、`_seed`、`api.add_camera`、`api.LogisticsChannelMemberCreate`、`api.reorder_cameras`、`api.LogisticsChannelMemberOrder`、`api.move_camera`、`api.remove_camera`、`any`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_member_bind_create_reorder_move_and_remove():
    service = FakeService()
    source = _seed(service, name="来源")
    target = _seed(service, name="目标")
    feature = FEATURES[0]
    api.add_camera(feature, source["id"], api.LogisticsChannelMemberCreate(camera_id=7), ADMIN, service)
    api.add_camera(feature, source["id"], api.LogisticsChannelMemberCreate(camera_id=8), ADMIN, service)
    ordered = api.reorder_cameras(
        feature, source["id"], api.LogisticsChannelMemberOrder(camera_ids=[8, 7]), ADMIN, service
    )
    assert [member.camera_id for member in ordered.members] == [8, 7]
    api.move_camera(feature, target["id"], 8, ADMIN, service)
    assert ("move", feature, 8, target["id"]) in service.calls
    assert api.remove_camera(feature, source["id"], 7, ADMIN, service).ok is True
    api.add_camera(
        feature, source["id"],
        api.LogisticsChannelMemberCreate(name="新增", url="rtsp://camera"),
        ADMIN, service,
    )
    assert any(call[0] == "create_camera" for call in service.calls)


# 功能：验证 `test_service_errors_have_stable_http_mapping` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `message`（未显式标注）：用于展示、记录或发送的文本消息
#   - `expected`（未显式标注）：`expected` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`FakeService`、`pytest.raises`、`api.create_channel`、`api.LogisticsChannelCreate`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("同一功能下通道名称已存在", 409),
        ("通道已达到最多 9 路上限", 409),
        ("摄像头不存在: 42", 404),
        ("department 必须与功能归属一致", 400),
    ],
)
def test_service_errors_have_stable_http_mapping(message, expected):
    service = FakeService()
    service.error = message
    with pytest.raises(HTTPException) as caught:
        api.create_channel(FEATURES[0], api.LogisticsChannelCreate(name="冲突"), ADMIN, service)
    assert caught.value.status_code == expected


# 功能：验证 `test_status_response_and_composite_jpeg_semantics` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`FakeService`、`FakeOrchestrator`、`_seed`、`api.get_channel_status`、`pytest.raises`、`api.get_channel_frame`、`np.zeros`、`response.body.startswith`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_status_response_and_composite_jpeg_semantics():
    service = FakeService()
    orchestrator = FakeOrchestrator()
    channel = _seed(service)
    feature, channel_id = FEATURES[0], channel["id"]
    fallback = api.get_channel_status(feature, channel_id, ADMIN, service, orchestrator)
    assert fallback.reason == "unknown"
    assert fallback.alarm is False

    orchestrator.status = {
        "feature_name": feature,
        "channel_id": channel_id,
        "channel_name": "一号通道",
        "reason": "normal",
        "alarm": False,
        "camera_ids": [7],
        "camera_counts": {"7": 1},
        "camera_states": {},
        "offending_camera_ids": [],
        "updated_at": 1.0,
    }
    status = api.get_channel_status(feature, channel_id, ADMIN, service, orchestrator)
    assert status.reason == "normal"
    assert status.camera_counts == {"7": 1}

    with pytest.raises(HTTPException) as caught:
        api.get_channel_frame(feature, channel_id, 85, None, None, ADMIN, service, orchestrator)
    assert caught.value.status_code == 503
    orchestrator.frame = np.zeros((120, 240, 3), dtype=np.uint8)
    response = api.get_channel_frame(feature, channel_id, 85, None, None, ADMIN, service, orchestrator)
    assert response.media_type == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-width"] == "240"
    assert response.body.startswith(b"\xff\xd8")
    resized = api.get_channel_frame(
        feature, channel_id, 85, 120, None, ADMIN, service, orchestrator
    )
    assert "x-frame-width" not in resized.headers
    assert "x-frame-height" not in resized.headers
    with pytest.raises(HTTPException) as caught:
        api.get_channel_frame(feature, 999, 85, None, None, ADMIN, service, orchestrator)
    assert caught.value.status_code == 404
