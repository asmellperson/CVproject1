"""SIP 报文、摘要认证和 PCMA 媒体描述；不包含网络或持久化状态。"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
import secrets

from requests.utils import parse_dict_header


SIP_REALM = "AiVision-SIP"
MAX_SIP_MESSAGE = 16384


class SipAudioError(RuntimeError):
    """经过约束的公开 SIP 错误，不携带设备原始报文或密码。"""


@dataclass
class SipMessage:
    """解析后的控制报文，默认 repr 隐藏认证头和正文。"""
    start: str
    headers: dict[str, str] = field(repr=False)
    body: str = field(default="", repr=False)

    @property
    def status(self) -> int:
        """请求返回零，响应只解析三位状态码。"""
        match = re.match(r"^SIP/2\.0 ([1-6][0-9]{2})\b", self.start)
        return int(match[1]) if match else 0


def parse_message(data: bytes) -> SipMessage:
    """严格限制单个 UDP 控制报文，不接受重复的身份或认证字段。"""
    if len(data) > MAX_SIP_MESSAGE:
        raise SipAudioError("SIP 控制报文过大")
    raw, separator, body = data.partition(b"\r\n\r\n")
    if not separator:
        raise SipAudioError("SIP 控制报文不完整")
    try:
        lines = raw.decode("utf-8").split("\r\n")
        if not re.fullmatch(r"(?:SIP/2\.0 [1-6][0-9]{2}(?: [^\r\n\x00]*)?|[A-Z]+ sip:[^\s\x00]+ SIP/2\.0)", lines[0]):
            raise ValueError("起始行无效")
        headers = {}
        for line in lines[1:]:
            name, value = line.split(":", 1)
            name = name.strip().lower()
            if name in headers or any(c in value for c in "\r\n\x00"):
                raise ValueError("重复字段")
            headers[name] = value.strip()
        length = int(headers.get("content-length", "0"))
        if length < 0 or length != len(body):
            raise ValueError("正文长度不符")
        for name in ("via", "from", "to", "call-id", "cseq"):
            if not headers.get(name):
                raise ValueError("缺少身份字段")
        return SipMessage(lines[0], headers, body.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise SipAudioError("SIP 控制报文格式无效") from None


def response(message: SipMessage, code: int, *, extra: dict[str, str] | None = None) -> bytes:
    """保留事务身份回应注册、保活和设备主动挂断。"""
    reason = {200: "OK", 401: "Unauthorized", 400: "Bad Request", 481: "Call Does Not Exist"}[code]
    headers = {key: message.headers[key] for key in ("via", "from", "to", "call-id", "cseq")}
    if ";tag=" not in headers["to"]:
        headers["to"] += ";tag=aivision-server"
    headers.update(extra or {})
    text = f"SIP/2.0 {code} {reason}\r\n" + "".join(f"{key}: {value}\r\n" for key, value in headers.items())
    return (text + "Content-Length: 0\r\n\r\n").encode()


def digest_fields(value: str) -> dict[str, str]:
    """仅接受 Digest，解析转义和引号由现有 requests 实现负责。"""
    if not value.startswith("Digest "):
        return {}
    return {key: item for key, item in parse_dict_header(value[7:]).items() if isinstance(item, str)}


def digest_value(username: str, password: str, realm: str, nonce: str, method: str, uri: str,
                 *, qop: str = "", nc: str = "", cnonce: str = "") -> str:
    """按 SIP Digest 计算摘要，不把密码拼入传输报文。"""
    def md5(value: str) -> str:
        return hashlib.md5(value.encode()).hexdigest()

    first = md5(f"{username}:{realm}:{password}")
    second = md5(f"{method}:{uri}")
    return md5(f"{first}:{nonce}:{nc}:{cnonce}:{qop}:{second}" if qop else f"{first}:{nonce}:{second}")


def authorization(challenge: str, username: str, password: str, method: str, uri: str) -> str:
    """设备要求呼叫鉴权时使用对应喇叭的 SIP 凭据，仅允许一次挑战重试。"""
    fields = digest_fields(challenge)
    if not fields.get("realm") or not fields.get("nonce") or fields.get("algorithm", "MD5").upper() != "MD5":
        raise SipAudioError("喇叭要求的 SIP 呼叫认证方式不受支持")
    qop = "auth" if "auth" in [v.strip() for v in fields.get("qop", "").split(",")] else ""
    if fields.get("qop") and not qop:
        raise SipAudioError("喇叭要求的 SIP 呼叫认证方式不受支持")
    cnonce, nc = secrets.token_hex(12), "00000001"
    value = digest_value(username, password, fields["realm"], fields["nonce"], method, uri,
                         qop=qop, nc=nc, cnonce=cnonce)
    def quoted(text: str) -> str:
        # 设备挑战中的引号须按协议转义，避免认证头被截断。
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    result = (f'Digest username={quoted(username)}, realm={quoted(fields["realm"])}, nonce={quoted(fields["nonce"])}, '
              f'uri={quoted(uri)}, response="{value}", algorithm=MD5')
    if qop:
        result += f', qop=auth, nc={nc}, cnonce="{cnonce}"'
    if fields.get("opaque"):
        result += f', opaque={quoted(fields["opaque"])}'
    return result


def audio_destination(body: str, expected_host: str) -> tuple[str, int]:
    """兼容海康 30000/2 端口格式，只向当前喇叭发送约定的 PCMA 音频。"""
    sections = re.split(r"(?m)^m=", body)
    for section in sections[1:]:
        match = re.match(r"audio (\d+)(?:/\d+)? RTP/AVP ([^\r\n]+)", section)
        if not match or not 0 < int(match[1]) <= 65535 or "8" not in match[2].split():
            continue
        if re.search(r"(?m)^a=(?:sendonly|inactive)\r?$", section):
            continue
        address = re.search(r"(?m)^c=IN IP4 ([^\r\n]+)", section)
        if address is None:
            address = re.search(r"(?m)^c=IN IP4 ([^\r\n]+)", sections[0])
        if not address or address[1] != expected_host:
            raise SipAudioError("喇叭返回的音频接收地址与所选设备不一致")
        mapping = re.search(r"(?mi)^a=rtpmap:8 ([^\r\n]+)", section)
        if mapping and mapping[1].upper() not in {"PCMA/8000", "PCMA/8000/1"}:
            continue
        return expected_host, int(match[1])
    raise SipAudioError("喇叭没有接受 G.711 A-law 音频，请检查 SIP 音频编码配置")
