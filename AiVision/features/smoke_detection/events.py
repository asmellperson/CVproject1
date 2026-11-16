"""解析设备报警协议；这里只接收设备明确上报的烟雾事件。"""
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message
from hashlib import sha256
from typing import Iterable, Iterator
import xml.etree.ElementTree as ET


MAX_EVENT_BYTES = 2 * 1024 * 1024
MAX_PART_BYTES = 8 * 1024 * 1024
MAX_HEADER_BYTES = 8192


class SmokeProtocolError(ValueError):
    """安全的协议异常，不附带设备响应正文。"""


@dataclass(frozen=True)
class SmokeEvent:
    event_type: str
    channel_id: int
    active: bool
    date_time: str
    event_id: str
    active_post_count: int | None = None
    picture: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True)
class MultipartPart:
    content_type: str
    body: bytes = field(repr=False)


def local_name(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def child(node: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in node if local_name(item) == name), None)


def text(node: ET.Element, name: str) -> str:
    item = child(node, name)
    return (item.text or "").strip() if item is not None else ""


def parse_xml(payload: bytes, *, maximum: int = MAX_EVENT_BYTES) -> ET.Element:
    try:
        source = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SmokeProtocolError("设备 XML 未使用有效的 UTF-8 编码") from None
    if (len(payload) > maximum or "\x00" in source
            or "<!DOCTYPE" in source.upper() or "<!ENTITY" in source.upper()):
        raise SmokeProtocolError("设备 XML 超过限制或包含不支持的声明")
    try:
        return ET.fromstring(source)
    except ET.ParseError:
        raise SmokeProtocolError("设备返回无效的 XML 数据") from None


def parse_smoke_event(payload: bytes) -> SmokeEvent | None:
    """不把火点、烟火合并事件、吸烟、温度或心跳猜成烟雾报警。"""
    root = parse_xml(payload)
    if local_name(root) != "EventNotificationAlert":
        raise SmokeProtocolError("设备报警流返回了非事件消息")
    if text(root, "eventType") != "smokeDetection":
        return None
    state = text(root, "eventState")
    if state not in {"active", "inactive"}:
        raise SmokeProtocolError("烟雾事件缺少有效状态")
    try:
        channel_id = int(text(root, "channelID"))
        date_time = text(root, "dateTime")
        parsed_time = datetime.fromisoformat(date_time.replace("Z", "+00:00"))
        count_text = text(root, "activePostCount")
        count = int(count_text) if count_text else None
        if channel_id <= 0 or parsed_time.tzinfo is None or (count is not None and count < 0):
            raise ValueError
    except (ValueError, OverflowError):
        raise SmokeProtocolError("烟雾事件缺少有效通道或设备时间") from None
    # 同一设备报文重复传输时得到稳定标识；持续事件是否重复报警由运行时管理。
    event_id = text(root, "eventID")
    if not event_id:
        event_id = sha256(f"{channel_id}:{date_time}:{count}".encode()).hexdigest()[:32]
    return SmokeEvent("smokeDetection", channel_id, state == "active", date_time, event_id[:256], count)


def multipart_boundary(content_type: str) -> bytes:
    message = Message()
    message["content-type"] = content_type
    value = message.get_boundary()
    if message.get_content_maintype() != "multipart" or not value:
        raise SmokeProtocolError("设备报警接口未返回 multipart 事件流")
    try:
        boundary = value.encode("ascii")
    except UnicodeEncodeError:
        raise SmokeProtocolError("设备报警流分隔符无效") from None
    if not 1 <= len(boundary) <= 128 or any(item < 32 or item == 127 for item in boundary):
        raise SmokeProtocolError("设备报警流分隔符无效")
    return boundary


def iter_multipart(chunks: Iterable[bytes], content_type: str, *,
                   maximum_part_bytes: int = MAX_PART_BYTES) -> Iterator[MultipartPart]:
    """按实际边界增量解析，兼容边界分片与缺省 Content-Length，限制缓冲区。"""
    marker = b"--" + multipart_boundary(content_type)
    buffer = bytearray()
    state = "boundary"
    length: int | None = None
    part_type = ""
    for chunk in chunks:
        if not chunk:
            continue
        buffer.extend(chunk)
        while True:
            if state == "boundary":
                position = buffer.find(marker)
                if position < 0:
                    if len(buffer) > MAX_HEADER_BYTES:
                        raise SmokeProtocolError("设备报警流未提供有效边界")
                    break
                if len(buffer) < position + len(marker) + 2:
                    break
                suffix = bytes(buffer[position + len(marker):position + len(marker) + 2])
                if suffix == b"--":
                    return
                if suffix != b"\r\n":
                    raise SmokeProtocolError("设备报警流边界格式无效")
                del buffer[:position + len(marker) + 2]
                state = "headers"
            if state == "headers":
                end = buffer.find(b"\r\n\r\n")
                if end < 0:
                    if len(buffer) > MAX_HEADER_BYTES:
                        raise SmokeProtocolError("设备报警流消息头超过限制")
                    break
                if end > MAX_HEADER_BYTES:
                    raise SmokeProtocolError("设备报警流消息头超过限制")
                headers = {}
                try:
                    for line in bytes(buffer[:end]).split(b"\r\n"):
                        key, value = line.split(b":", 1)
                        name = key.decode("ascii").strip().lower()
                        if name in headers:
                            raise ValueError
                        headers[name] = value.decode("ascii").strip()
                    length = int(headers["content-length"]) if "content-length" in headers else None
                    if length is not None and not 0 <= length <= maximum_part_bytes:
                        raise ValueError
                except (ValueError, UnicodeDecodeError):
                    raise SmokeProtocolError("设备报警流消息头无效或消息超过限制") from None
                part_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
                del buffer[:end + 4]
                state = "body"
            if state == "body":
                if length is None:
                    end = buffer.find(b"\r\n" + marker)
                    if end < 0:
                        if len(buffer) > maximum_part_bytes + len(marker) + 2:
                            raise SmokeProtocolError("设备报警流消息超过限制")
                        break
                else:
                    end = length
                    if len(buffer) < end:
                        break
                if end > maximum_part_bytes:
                    raise SmokeProtocolError("设备报警流消息超过限制")
                payload = bytes(buffer[:end])
                del buffer[:end]
                state = "boundary"
                yield MultipartPart(part_type, payload)
    if state != "boundary" or buffer.strip(b"\r\n"):
        raise SmokeProtocolError("设备报警流在完整消息前断开")
