"""海康摄像头烟雾参数及报警事件接入；不执行图像检测。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Callable, Iterator
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

import requests
from requests.auth import HTTPDigestAuth
from urllib3.exceptions import HTTPError

from .device_schema import (
    SmokeParameter, SmokeParameterChoice, SmokeParametersState, SmokeParametersUpdate,
    SmokeShieldPoint, SmokeShieldRegion, SmokeShieldState, SmokeShieldUpdate,
)
from .events import SmokeEvent, SmokeProtocolError, child, iter_multipart, local_name, parse_smoke_event, parse_xml, text


THERMAL_CAPABILITIES = "/ISAPI/Thermal/capabilities"
ALERT_STREAM = "/ISAPI/Event/notification/alertStream"
XML_RESPONSE_LIMIT = 2 * 1024 * 1024
STREAM_PART_LIMIT = 8 * 1024 * 1024
STREAM_CHUNK_BYTES = 4096
SNAPSHOT_MAX_BYTES = 8 * 1024 * 1024
SNAPSHOT_MAX_PIXELS = 24 * 1024 * 1024
PARAMETERS = {
    "enabled": (("SmokeDetection", "enabled"), "烟雾检测", "boolean"),
    "sensitivity": (("SmokeDetection", "sensitivity"), "烟雾灵敏度", "integer"),
    "patrol_sensitivity": (("SmokeDetection", "patrolSensitivity"), "巡航检测灵敏度", "integer"),
    "double_check_sensitivity": (("SmokeDetection", "doubleCheckSensitivity"), "二次确认灵敏度", "integer"),
    "display_smoke_info": (("SmokeDetection", "displaySmokeInfoOnStreamEnabled"), "画面叠加烟雾信息", "boolean"),
    "alarm_strategy": (("AlarmStrategy", "strategyType"), "设备报警策略（烟雾与火点）", "enum"),
    "device_alarm_interval": (("SmokeDetection", "alarmInterval"), "设备烟雾报警间隔（秒）", "integer"),
    "image_quality": (("SmokeDetection", "imgQuality"), "烟雾报警抓图质量", "enum"),
    "high_sensitivity_enabled": (("SmokeDetection", "highSensitivityEnabled"), "烟雾高灵敏度模式", "boolean"),
}
PARAMETER_CHOICES = {
    "alarm_strategy": {
        "any": "烟雾或火点任一报警", "cooperate": "烟雾与火点协同报警",
        "multiSystem": "多系统确认报警", "multisystem": "多系统确认报警",
        "appointFire": "仅火点报警", "appointSmoke": "仅烟雾报警",
    },
    "image_quality": {"best": "最佳", "good": "良好", "general": "一般"},
}
_LOCKS_GUARD = Lock()
_WRITE_LOCKS: dict[tuple[str, int], Lock] = {}


class SmokeDeviceError(RuntimeError):
    """仅包含可公开的中文错误，设备原始响应和认证信息不对外提供。"""

    def __init__(self, message: str, status_code: int = 502, *, device_status: int | None = None,
                 unsupported: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.device_status = device_status
        self.unsupported = unsupported


@dataclass(frozen=True)
class SmokeDeviceOptions:
    connect_timeout_seconds: float = 3.0
    request_timeout_seconds: float = 10.0
    stream_timeout_seconds: float = 15.0
    max_response_bytes: int = XML_RESPONSE_LIMIT
    max_part_bytes: int = STREAM_PART_LIMIT


@dataclass(frozen=True)
class _Target:
    base_url: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    event_channel_id: int
    thermal_channel_id: int


def _target(camera: dict, value: dict) -> _Target:
    try:
        parsed = urlsplit(str(camera.get("url") or ""))
        if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname or not parsed.username:
            raise ValueError
        host = parsed.hostname
        if any(char in host for char in "/\\?#@\r\n\t%"):
            raise ValueError
        scheme = value.get("device_scheme", "http")
        port = value.get("device_port", 80)
        event_channel = value.get("event_channel_id", 1)
        thermal_channel = value.get("thermal_channel_id", 1)
        if scheme not in {"http", "https"} or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError
        if any(type(item) is not int or not 1 <= item <= 65535 for item in (event_channel, thermal_channel)):
            raise ValueError
        host = f"[{host}]" if ":" in host else host
        return _Target(f"{scheme}://{host}:{port}", unquote(parsed.username), unquote(parsed.password or ""),
                       event_channel, thermal_channel)
    except (ValueError, TypeError):
        raise SmokeDeviceError("视频源未提供可用的设备地址和认证信息，请检查摄像头配置", 409) from None


def _boolean(value: str) -> bool | None:
    return {"true": True, "false": False}.get(value.lower())


def _integer(value: str) -> int | None:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _set_text(parent: ET.Element, name: str, value: str) -> None:
    node = child(parent, name)
    if node is None:
        namespace = parent.tag.rsplit("}", 1)[0] + "}" if "}" in parent.tag else ""
        node = ET.SubElement(parent, namespace + name)
    node.text = value


def _descendant(parent: ET.Element, path: tuple[str, ...]) -> ET.Element | None:
    for name in path:
        parent = child(parent, name)
        if parent is None:
            return None
    return parent


def _xml_bytes(root: ET.Element) -> bytes:
    if "}" in root.tag:
        ET.register_namespace("", root.tag[1:].split("}", 1)[0])
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """解码前读取 JPEG 帧尺寸，避免小体积异常图片造成过量内存分配。"""
    if not data.startswith(b"\xff\xd8"):
        raise SmokeDeviceError("摄像头抓图不是有效的 JPEG 图片")
    position = 2
    while position + 3 < len(data):
        if data[position] != 255:
            break
        while position < len(data) and data[position] == 255:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker in {0x01, *range(0xD0, 0xD9)}:
            continue
        if marker in {0xDA, 0xD9} or position + 2 > len(data):
            break
        length = int.from_bytes(data[position:position + 2], "big")
        if length < 2 or position + length > len(data):
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if length < 8:
                break
            height = int.from_bytes(data[position + 3:position + 5], "big")
            width = int.from_bytes(data[position + 5:position + 7], "big")
            if width <= 0 or height <= 0 or width * height > SNAPSHOT_MAX_PIXELS:
                raise SmokeDeviceError("摄像头抓图尺寸超过允许范围")
            return width, height
        position += length
    raise SmokeDeviceError("摄像头抓图缺少有效的 JPEG 图像信息")


class SmokeDeviceClient:
    """设备直连使用 Digest；事件连接可关闭，管理请求均有超时和大小上限。"""

    def __init__(self, camera: dict, value: dict, options: SmokeDeviceOptions | None = None, *, session_factory=None):
        self._target = _target(camera, value)
        self.options = options or SmokeDeviceOptions()
        self._session_factory = session_factory or requests.Session
        self._active_lock = Lock()
        self._active_response = None
        self._active_session = None
        self._closed = Event()
        self._shield_channel_id = self._target.event_channel_id
        with _LOCKS_GUARD:
            self._write_lock = _WRITE_LOCKS.setdefault(
                (self._target.base_url, self._target.thermal_channel_id), Lock())

    def close(self) -> None:
        self._closed.set()
        with self._active_lock:
            response, session = self._active_response, self._active_session
        if response is not None:
            response.close()
        if session is not None:
            session.close()

    def _session(self):
        if self._closed.is_set():
            raise SmokeDeviceError("设备连接已关闭", 409)
        session = self._session_factory()
        session.trust_env = False
        session.auth = HTTPDigestAuth(self._target.username, self._target.password)
        return session

    def _response_bytes(self, response) -> bytes:
        body = bytearray()
        for chunk in response.iter_content(STREAM_CHUNK_BYTES):
            if len(body) + len(chunk) > self.options.max_response_bytes:
                raise SmokeDeviceError("设备参数响应超过允许大小")
            body.extend(chunk)
        return bytes(body)

    def _check_http(self, response) -> None:
        status = response.status_code
        if status == 403:
            # 设备也用 403 表示通道或接口不支持，不能仅凭 HTTP 状态认定为密码错误。
            body = self._response_bytes(response)
            try:
                root = parse_xml(body, maximum=self.options.max_response_bytes)
            except SmokeProtocolError:
                unsupported = False
            else:
                unsupported = (local_name(root) == "ResponseStatus" and text(root, "statusCode") == "4"
                               and text(root, "subStatusCode") == "notSupport")
            if unsupported:
                raise SmokeDeviceError("设备当前参数通道不支持此接口，请核对设备参数通道",
                                       device_status=status, unsupported=True)
        if status in {401, 403}:
            raise SmokeDeviceError("摄像头拒绝访问，请检查设备账号、密码和接口权限", device_status=status)
        if not 200 <= status < 300:
            raise SmokeDeviceError(f"摄像头接口返回 HTTP {status}", device_status=status)

    def _request(self, method: str, path: str, *, payload: bytes | None = None) -> ET.Element:
        try:
            with self._session() as session:
                with session.request(method, self._target.base_url + path, data=payload,
                        headers={"Content-Type": "application/xml"}, stream=True, allow_redirects=False,
                        timeout=(self.options.connect_timeout_seconds, self.options.request_timeout_seconds)) as response:
                    self._check_http(response)
                    body = self._response_bytes(response)
            root = parse_xml(body, maximum=self.options.max_response_bytes)
        except requests.exceptions.SSLError:
            raise SmokeDeviceError("设备 HTTPS 证书校验失败，请检查摄像头证书") from None
        except requests.Timeout:
            raise SmokeDeviceError("设备管理接口请求超时，请检查网络和端口") from None
        except requests.RequestException:
            raise SmokeDeviceError("无法连接摄像头管理接口") from None
        except SmokeProtocolError as exc:
            raise SmokeDeviceError(str(exc)) from None
        if local_name(root) == "ResponseStatus":
            if text(root, "statusCode") not in {"0", "1"}:
                raise SmokeDeviceError("设备拒绝了参数操作，请检查设备能力及账号权限")
        return root

    def _optional_get(self, path: str) -> ET.Element | None:
        try:
            return self._request("GET", path)
        except SmokeDeviceError as exc:
            if exc.unsupported or exc.device_status in {404, 405}:
                return None
            raise

    def _path(self, suffix: str) -> str:
        return f"/ISAPI/Thermal/channels/{self._target.thermal_channel_id}/{suffix}"

    def _parameter_documents(self):
        thermal = self._request("GET", THERMAL_CAPABILITIES)
        if local_name(thermal) != "ThermalCap":
            raise SmokeDeviceError("设备未返回有效的热成像能力")
        if text(thermal, "isSupportFireDetection") == "false":
            return None, None
        capabilities = self._optional_get(self._path("fireDetection/capabilities"))
        if capabilities is None or (child(capabilities, "SmokeDetection") is None
                                    and child(capabilities, "smokeFireEnabled") is None):
            return None, None
        current = self._request("GET", self._path("fireDetection"))
        if local_name(capabilities) != "FireDetection" or local_name(current) != "FireDetection":
            raise SmokeDeviceError("设备未返回有效的烟雾参数")
        return capabilities, current

    def _parameter_state(self, capabilities, current) -> SmokeParametersState:
        result = SmokeParametersState(supported=False, channel_id=self._target.thermal_channel_id,
                                      message="当前设备参数通道未确认烟雾配置能力，请核对设备参数通道")
        if capabilities is None or current is None:
            return result
        strategy = _descendant(current, ("AlarmStrategy", "strategyType"))
        if strategy is not None and (strategy.text or "").strip() == "appointFire":
            result.warnings.append("当前策略仅上传火点报警，烟雾报警不会上传。")
        result.global_enabled = _boolean(text(current, "smokeFireEnabled"))
        global_cap = child(capabilities, "smokeFireEnabled")
        if global_cap is not None and result.global_enabled is not None:
            choices = {item.strip().lower() for item in (global_cap.get("opt") or "true,false").split(",")}
            if {"true", "false"} <= choices:
                # 部分固件只提供烟火总开关，不提供烟雾独立开关；名称明确其同时影响火点检测。
                result.parameters.append(SmokeParameter(key="global_enabled", label="烟火检测总开关（含火点）",
                    kind="boolean", value=result.global_enabled))
        result.supported = True
        result.message = "已读取摄像头当前参数"
        for key, (path, label, kind) in PARAMETERS.items():
            node = _descendant(capabilities, path)
            current_node = _descendant(current, path)
            if node is None or current_node is None:
                continue
            raw = (current_node.text or "").strip()
            if kind == "boolean":
                value = _boolean(raw)
                choices = {item.strip().lower() for item in (node.get("opt") or "true,false").split(",")}
                if value is not None and {"true", "false"} <= choices:
                    result.parameters.append(SmokeParameter(key=key, label=label, kind=kind, value=value))
            elif kind == "integer":
                minimum, maximum = _integer(node.get("min")), _integer(node.get("max"))
                value = _integer(raw)
                # 不把通用协议示例范围冒充这台设备的实际范围。
                if (minimum is not None and maximum is not None and value is not None
                        and minimum <= value <= maximum):
                    result.parameters.append(SmokeParameter(key=key, label=label, kind=kind, value=value,
                                                            minimum=minimum, maximum=maximum))
            else:
                supported = [item.strip() for item in (node.get("opt") or "").split(",") if item.strip()]
                labels = PARAMETER_CHOICES[key]
                choices = [SmokeParameterChoice(value=item, label=labels[item]) for item in supported if item in labels]
                if raw in {item.value for item in choices}:
                    result.parameters.append(SmokeParameter(key=key, label=label, kind=kind, value=raw, choices=choices))
        return result

    def read_parameters(self) -> SmokeParametersState:
        return self._parameter_state(*self._parameter_documents())

    def write_parameters(self, update: SmokeParametersUpdate) -> SmokeParametersState:
        with self._write_lock:
            capabilities, current = self._parameter_documents()
            state = self._parameter_state(capabilities, current)
            fields = {item.key: item for item in state.parameters}
            if not state.supported or update.values.keys() - fields.keys():
                raise SmokeDeviceError("设备未确认所提交参数的写入能力", 409)
            changed = deepcopy(current)
            for key, value in update.values.items():
                definition = fields[key]
                if definition.kind == "boolean":
                    valid = type(value) is bool
                elif definition.kind == "integer":
                    valid = type(value) is int and definition.minimum <= value <= definition.maximum
                else:
                    valid = type(value) is str and value in {item.value for item in definition.choices}
                if not valid:
                    raise SmokeDeviceError("提交的烟雾参数类型或数值范围不符合设备能力", 422)
                if key == "global_enabled":
                    _set_text(changed, "smokeFireEnabled", str(value).lower())
                else:
                    path = PARAMETERS[key][0]
                    parent = _descendant(changed, path[:-1])
                    _set_text(parent, path[-1], str(value).lower() if type(value) is bool else str(value))
            result = self._request("PUT", self._path("fireDetection"), payload=_xml_bytes(changed))
            if local_name(result) != "ResponseStatus":
                raise SmokeDeviceError("设备未确认参数保存结果")
            actual = self._parameter_state(capabilities, self._request("GET", self._path("fireDetection")))
            readback = {item.key: item.value for item in actual.parameters}
            if any(type(readback.get(key)) is not type(value) or readback.get(key) != value
                   for key, value in update.values.items()):
                raise SmokeDeviceError("设备回读参数与提交值不一致，尚未确认保存成功", 409)
            return actual

    def _shield_documents(self):
        # 双光谱设备的烟雾屏蔽区可能属于可见光通道，不能强行套用热成像参数通道。
        for channel in dict.fromkeys((self._target.event_channel_id, self._target.thermal_channel_id)):
            path = f"/ISAPI/Thermal/channels/{channel}/"
            capabilities = self._optional_get(path + "smokeShieldMask/capabilities")
            if capabilities is None:
                continue
            current = self._optional_get(path + "SmokeShieldMask")
            if current is None:
                continue
            if local_name(capabilities) != "SmokeShieldMask" or local_name(current) != "SmokeShieldMask":
                raise SmokeDeviceError("设备未返回有效的烟雾屏蔽区域")
            self._shield_channel_id = channel
            return capabilities, current
        return None, None

    def _shield_state(self, capabilities, current) -> SmokeShieldState:
        result = SmokeShieldState(supported=False, channel_id=self._shield_channel_id,
                                  message="设备未确认烟雾屏蔽区域能力")
        if capabilities is None or current is None:
            return result
        result.supported = True
        enabled = _boolean(text(current, "enabled"))
        if enabled is None:
            raise SmokeDeviceError("设备屏蔽区域缺少有效的开关状态")
        result.enabled = enabled
        size = child(current, "normalizedScreenSize")
        if size is None:
            size = child(capabilities, "normalizedScreenSize")
        width = _integer(text(size, "normalizedScreenWidth")) if size is not None else None
        height = _integer(text(size, "normalizedScreenHeight")) if size is not None else None
        regions_cap = child(capabilities, "SmokeShieldMaskRegionList")
        template = child(regions_cap, "SmokeShieldMaskRegion") if regions_cap is not None else None
        id_cap = child(template, "id") if template is not None else None
        maximum = _integer(id_cap.get("max")) if id_cap is not None else None
        regions = child(current, "SmokeShieldMaskRegionList")
        count = _integer(regions_cap.get("size")) if regions_cap is not None else None
        if count is None and regions is not None:
            count = _integer(regions.get("size"))
        minimum = _integer(id_cap.get("min")) if id_cap is not None else None
        result.max_regions = min(maximum or 0, count or 0)
        region_type = text(template, "regionType") if template is not None else ""
        type_node = child(template, "regionType") if template is not None else None
        type_choices = (type_node.get("opt") or "").split(",") if type_node is not None else []
        if region_type == "quadrilateral" or "quadrilateral" in type_choices:
            result.min_points = result.max_points = 4
        if not width or not height or width <= 0 or height <= 0:
            result.message = "设备未提供有效坐标尺寸，区域仅可在摄像头端配置"
            return result
        result.coordinate_width, result.coordinate_height = width, height
        result.writable = bool(minimum == 1 and result.max_regions > 0 and template is not None
                               and child(capabilities, "enabled") is not None
                               and child(template, "enabled") is not None
                               and text(template, "showEnabled") != "false"
                               and (region_type == "quadrilateral" or "quadrilateral" in type_choices))
        for region in regions if regions is not None else []:
            if local_name(region) != "SmokeShieldMaskRegion" or text(region, "showEnabled") == "false":
                continue
            if text(region, "regionType") not in {"", "quadrilateral"}:
                result.writable = False
            coordinates = child(region, "RegionCoordinatesList")
            points = []
            for point in coordinates if coordinates is not None else []:
                x, y = _integer(text(point, "positionX")), _integer(text(point, "positionY"))
                if x is None or y is None or not 0 <= x <= width or not 0 <= y <= height:
                    raise SmokeDeviceError("设备屏蔽区域坐标无效")
                points.append(SmokeShieldPoint(x=x / width, y=1 - y / height))
            # 设备可能预留禁用的空区域槽位，不能把占位点展示成有效多边形。
            if not points or len(set((p.x, p.y) for p in points)) < 3:
                if text(region, "enabled") == "true":
                    raise SmokeDeviceError("设备启用的屏蔽区域缺少有效坐标")
                continue
            try:
                region_enabled = _boolean(text(region, "enabled"))
                if region_enabled is None:
                    raise ValueError
                result.regions.append(SmokeShieldRegion(id=int(text(region, "id")),
                    enabled=region_enabled,
                    name=text(region, "maskName"), points=points))
            except (ValueError, TypeError):
                raise SmokeDeviceError("设备屏蔽区域数据无效") from None
        result.message = "已读取摄像头屏蔽区域，框内不进行烟雾检测" if result.writable else "设备能力信息不完整，屏蔽区域只读"
        return result

    def read_shields(self) -> SmokeShieldState:
        return self._shield_state(*self._shield_documents())

    def read_picture(self) -> bytes:
        """屏蔽区底图必须来自能力确认后的区域通道，避免在热图上绘制可见光坐标。"""
        capabilities, current = self._shield_documents()
        if capabilities is None or current is None:
            raise SmokeDeviceError("尚未确认设备屏蔽区画面通道", 409)
        stream_id = self._shield_channel_id * 100 + 1
        try:
            with self._session() as session:
                with session.get(self._target.base_url + f"/ISAPI/Streaming/channels/{stream_id}/picture",
                        stream=True, allow_redirects=False,
                        timeout=(self.options.connect_timeout_seconds, self.options.request_timeout_seconds)) as response:
                    self._check_http(response)
                    mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    if mime not in {"image/jpeg", "image/jpg"}:
                        raise SmokeDeviceError("摄像头抓图接口未返回 JPEG 图片")
                    content = bytearray()
                    for chunk in response.iter_content(STREAM_CHUNK_BYTES):
                        if len(content) + len(chunk) > SNAPSHOT_MAX_BYTES:
                            raise SmokeDeviceError("摄像头抓图超过允许大小")
                        content.extend(chunk)
            image = bytes(content)
            width, height = _jpeg_dimensions(image)
            # 复用项目已有的 OpenCV；格式头与解码结果都确认后才交给浏览器绘制。
            import cv2
            import numpy as np
            decoded = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
            if decoded is None or decoded.shape[:2] != (height, width):
                raise SmokeDeviceError("摄像头抓图无法解码")
            return image
        except requests.RequestException:
            raise SmokeDeviceError("摄像头抓图失败，请检查网络及通道配置") from None

    def write_shields(self, update: SmokeShieldUpdate) -> SmokeShieldState:
        with self._write_lock:
            capabilities, current = self._shield_documents()
            state = self._shield_state(capabilities, current)
            if not state.writable:
                raise SmokeDeviceError("尚未确认设备区域写入能力与坐标范围", 409)
            if len(update.regions) > state.max_regions or any(
                    region.id > state.max_regions or not state.min_points <= len(region.points) <= state.max_points
                    for region in update.regions):
                raise SmokeDeviceError("屏蔽区域数量、编号或顶点数超过设备能力", 422)
            changed = deepcopy(current)
            _set_text(changed, "enabled", str(update.enabled).lower())
            container = child(changed, "SmokeShieldMaskRegionList")
            namespace = changed.tag.rsplit("}", 1)[0] + "}" if "}" in changed.tag else ""
            if container is None:
                container = ET.SubElement(changed, namespace + "SmokeShieldMaskRegionList")
            existing = {text(region, "id"): region for region in container}
            hidden = {int(text(region, "id")) for region in container
                      if text(region, "showEnabled") == "false" and _integer(text(region, "id")) is not None}
            if any(region.id in hidden for region in update.regions):
                raise SmokeDeviceError("提交的区域包含设备未开放配置的区域编号", 409)
            regions_cap = child(capabilities, "SmokeShieldMaskRegionList")
            template = child(regions_cap, "SmokeShieldMaskRegion")
            name_cap = child(template, "maskName")
            for region in list(container):
                if local_name(region) == "SmokeShieldMaskRegion" and text(region, "showEnabled") != "false":
                    container.remove(region)
            for region in update.regions:
                # 量化后的点也必须构成有效区域，不能让窄区域在设备坐标中退化。
                try:
                    quantized = [SmokeShieldPoint(
                        x=round(point.x * state.coordinate_width) / state.coordinate_width,
                        y=1 - round((1 - point.y) * state.coordinate_height) / state.coordinate_height)
                        for point in region.points]
                    SmokeShieldRegion(id=region.id, enabled=region.enabled, name=region.name, points=quantized)
                except ValueError:
                    raise SmokeDeviceError("区域在设备坐标精度下过小或发生退化，请重新绘制", 422) from None
                node = deepcopy(existing.get(str(region.id)))
                if node is None:
                    node = ET.Element(namespace + "SmokeShieldMaskRegion")
                    _set_text(node, "showEnabled", "true")
                    _set_text(node, "regionType", "quadrilateral")
                _set_text(node, "id", str(region.id))
                _set_text(node, "enabled", str(region.enabled).lower())
                if name_cap is None:
                    if region.name != text(node, "maskName"):
                        raise SmokeDeviceError("设备未确认区域名称修改能力", 409)
                else:
                    name_maximum = _integer(name_cap.get("max"))
                    if name_maximum is None or len(region.name) > name_maximum:
                        raise SmokeDeviceError("区域名称超过设备能力或尚未确认名称长度限制", 422)
                    _set_text(node, "maskName", region.name)
                old = child(node, "RegionCoordinatesList")
                if old is not None:
                    node.remove(old)
                coordinates = ET.SubElement(node, namespace + "RegionCoordinatesList")
                for point in region.points:
                    item = ET.SubElement(coordinates, namespace + "RegionCoordinates")
                    _set_text(item, "positionX", str(round(point.x * state.coordinate_width)))
                    _set_text(item, "positionY", str(round((1 - point.y) * state.coordinate_height)))
                container.append(node)
            path = f"/ISAPI/Thermal/channels/{self._shield_channel_id}/SmokeShieldMask"
            result = self._request("PUT", path, payload=_xml_bytes(changed))
            if local_name(result) != "ResponseStatus":
                raise SmokeDeviceError("设备未确认区域保存结果")
            actual = self._shield_state(capabilities, self._request("GET", path))
            expected = {region.id: region for region in update.regions}
            returned = {region.id: region for region in actual.regions}
            if actual.enabled != update.enabled or expected.keys() != returned.keys():
                raise SmokeDeviceError("设备区域回读与提交值不一致，尚未确认保存成功", 409)
            tolerance = 1 / min(state.coordinate_width, state.coordinate_height)
            for region_id, region in expected.items():
                saved = returned[region_id]
                if (region.enabled != saved.enabled or region.name != saved.name
                        or len(region.points) != len(saved.points) or any(
                        abs(a.x - b.x) > tolerance or abs(a.y - b.y) > tolerance
                        for a, b in zip(region.points, saved.points))):
                    raise SmokeDeviceError("设备区域回读与提交值不一致，尚未确认保存成功", 409)
            return actual

    def iter_events(self, stop_event: Event, on_connected: Callable[[], None] | None = None,
                    on_activity: Callable[[], None] | None = None,
                    on_protocol_warning: Callable[[str], None] | None = None) -> Iterator[SmokeEvent]:
        if stop_event.is_set() or self._closed.is_set():
            return
        try:
            with self._session() as session:
                with self._active_lock:
                    self._active_session = session
                if stop_event.is_set() or self._closed.is_set():
                    return
                with session.get(self._target.base_url + ALERT_STREAM, stream=True, allow_redirects=False,
                        timeout=(self.options.connect_timeout_seconds, self.options.stream_timeout_seconds)) as response:
                    self._check_http(response)
                    with self._active_lock:
                        self._active_response = response
                    if stop_event.is_set() or self._closed.is_set():
                        return
                    content_type = response.headers.get("Content-Type", "")
                    from .events import multipart_boundary
                    multipart_boundary(content_type)
                    if on_connected is not None:
                        on_connected()
                    # 非 chunked 长连接的心跳很小；read1及时交付已有数据，避免攒满缓冲后误报断线。
                    def chunks():
                        while not stop_event.is_set() and not self._closed.is_set():
                            data = response.raw.read1(STREAM_CHUNK_BYTES, decode_content=True)
                            if not data:
                                return
                            yield data

                    for part in iter_multipart(chunks(), content_type,
                                               maximum_part_bytes=self.options.max_part_bytes):
                        if stop_event.is_set() or self._closed.is_set():
                            return
                        if part.content_type not in {"application/xml", "text/xml"}:
                            continue
                        root = parse_xml(part.body)
                        if local_name(root) != "EventNotificationAlert":
                            raise SmokeProtocolError("设备报警流返回了非事件消息")
                        event_type = text(root, "eventType")
                        event = parse_smoke_event(part.body) if event_type == "smokeDetection" else None
                        if on_activity is not None:
                            on_activity()
                        if event_type in {"fireDetection", "smokeAndFireDetection"}:
                            channel = _integer(text(root, "channelID"))
                            if channel in {None, self._target.event_channel_id} and on_protocol_warning is not None:
                                # SDK 的烟雾子类型不能未经证实套用到 ISAPI XML，保留可见的联调提示。
                                on_protocol_warning("设备上报烟火相关事件，烟雾子类型尚未核验，请完成设备联调")
                        if event is not None and event.channel_id == self._target.event_channel_id:
                            if on_protocol_warning is not None:
                                on_protocol_warning("")
                            yield event
        except (requests.RequestException, HTTPError, SmokeProtocolError):
            if not stop_event.is_set() and not self._closed.is_set():
                raise SmokeDeviceError("摄像头报警事件连接中断或协议无效，请检查设备网络和事件接口") from None
        finally:
            with self._active_lock:
                self._active_response = None
                self._active_session = None
