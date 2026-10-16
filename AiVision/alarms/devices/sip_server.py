"""平台常驻 SIP 注册服务，按设备 IP 和账户隔离呼叫与 RTP 音频。"""
from __future__ import annotations

from dataclasses import dataclass, field
import hmac
import queue
import re
import secrets
import socket
import struct
import threading
import time
from urllib.parse import urlsplit

from AiVision.core.logger import logger
from AiVision.core.settings import settings
from .audio import SAMPLE_RATE, PACKET_SAMPLES, SILENCE
from .schema import SipServerConfig
from .sip_protocol import (
    MAX_SIP_MESSAGE, SIP_REALM, SipAudioError, SipMessage, audio_destination,
    authorization, digest_fields, digest_value, parse_message, response,
)


@dataclass(frozen=True)
class SipDevice:
    """内部设备地址和身份，凭据不会进入默认调试表示。"""
    id: int
    host: str
    username: str
    auth_id: str
    password: str = field(repr=False)
    port: int = 5060


class SipAudioServer:
    """一个 UDP 监听器服务多台喇叭，每次播放拥有独立事务队列与 RTP socket。"""

    def __init__(self):
        """初始化不绑定端口，便于 API 先启动以及隔离测试。"""
        self._lock = threading.RLock()
        self._config = SipServerConfig()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._devices: dict[int, SipDevice] = {}
        self._calls: dict[str, SipCall] = {}
        self._nonces: dict[str, dict] = {}
        self._registered: dict[int, float] = {}
        self._error: str | None = None
        self.generation = 0

    def status(self) -> dict:
        """区分已保存参数和实际运行状态。"""
        with self._lock:
            return {**self._config.model_dump(), "running": self._socket is not None,
                    "last_error": self._error}

    def configure(self, config: SipServerConfig) -> None:
        """先尝试绑定新端口再替换旧服务，配置错误不破坏现有监听。"""
        if config.enabled and not config.address:
            raise SipAudioError("启用 SIP 服务前请填写本机局域网 IPv4 地址")
        with self._lock:
            if self._config == config and (self._socket is not None or not config.enabled):
                return
            if self._calls:
                raise SipAudioError("喇叭正在播放，请结束试播或等待播放完成后修改 SIP 服务")
            candidate = None
            if config.enabled:
                try:
                    candidate = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    candidate.bind((config.address, config.port))
                    candidate.settimeout(0.2)
                except OSError:
                    if candidate is not None:
                        candidate.close()
                    raise SipAudioError("SIP 监听失败：请确认服务器地址属于本机，且 UDP 端口未被占用") from None
            old_socket = self._socket
            self._stop.set()
            self._stop = threading.Event()
            self._socket = candidate
            self._config = config.model_copy()
            self._registered.clear()
            self._nonces.clear()
            self._error = None
            self.generation += 1
            if old_socket is not None:
                old_socket.close()
            if candidate is not None:
                self._thread = threading.Thread(target=self._listen, args=(candidate, self._stop),
                                                daemon=True, name="horn-sip")
                self._thread.start()

    def set_device(self, config: dict) -> None:
        """提交后的设备配置进入注册白名单；同一 IP 和账户不允许指向两条设备记录。"""
        sip = config.get("sip")
        if not config.get("enable") or not sip:
            self.remove_device(config["id"])
            return
        try:
            host = socket.gethostbyname(urlsplit(config["url"]).hostname or "")
        except OSError:
            raise SipAudioError("喇叭 IPv4 地址解析失败，请检查设备地址") from None
        device = SipDevice(config["id"], host, sip["username"], sip["auth_id"], sip["password"], sip["port"])
        with self._lock:
            for other in self._devices.values():
                if other.id != device.id and (other.host, other.username) == (device.host, device.username):
                    raise SipAudioError("已有设备使用相同的喇叭地址和 SIP 账户，请检查设备配置")
            if self._devices.get(device.id) != device:
                self._registered.pop(device.id, None)
            self._devices[device.id] = device

    def remove_device(self, horn_id: int) -> None:
        """停用或删除设备后立即撤销注册许可。"""
        with self._lock:
            self._devices.pop(horn_id, None)
            self._registered.pop(horn_id, None)

    def registered(self, horn_id: int) -> bool:
        """只在实际完成密码校验的 REGISTER 有效期内返回真。"""
        with self._lock:
            return self._registered.get(horn_id, 0) > time.monotonic()

    def send(self, data: bytes, peer: tuple[str, int]) -> None:
        """只发送控制报文；底层异常转换为不含凭据的提示。"""
        with self._lock:
            if self._socket is None:
                raise SipAudioError("SIP 服务尚未启动，请在喇叭配置中启用 SIP 服务")
            try:
                self._socket.sendto(data, peer)
            except OSError:
                raise SipAudioError("SIP 控制报文发送失败，请检查网络") from None

    def _listen(self, sock: socket.socket, stop: threading.Event) -> None:
        """接收循环不等待播放，不让某台喇叭阻塞其他设备注册或接听。"""
        while not stop.is_set():
            try:
                data, peer = sock.recvfrom(MAX_SIP_MESSAGE + 1)
                message = parse_message(data)
                with self._lock:
                    if sock is not self._socket:
                        return
                    call = self._calls.get(message.headers["call-id"])
                    known = any(device.host == peer[0] for device in self._devices.values())
                if call is not None and peer == call.peer:
                    call.receive(message)
                elif not known:
                    continue
                elif message.start.startswith("REGISTER "):
                    self._register(message, peer)
                elif message.start.startswith(("OPTIONS ", "MESSAGE ")):
                    self.send(response(message, 200), peer)
            except socket.timeout:
                continue
            except SipAudioError:
                logger.debug("[HornSIP] 已忽略无效或无法处理的控制报文")
            except OSError:
                if not stop.is_set():
                    with self._lock:
                        if sock is self._socket:
                            self._error = "SIP 接收失败，请检查网络或重新保存 SIP 服务配置"
                            sock.close()
                            self._socket = None
                    logger.warning("[HornSIP] 控制报文接收失败")
                return

    def _register(self, message: SipMessage, peer: tuple[str, int]) -> None:
        """注册只允许已配置设备的账户，摘要匹配才登记成功。"""
        identity = re.search(r"sip:([^@;>]+)@", message.headers["to"])
        with self._lock:
            device = next((item for item in self._devices.values()
                           if identity and item.host == peer[0] and item.username == identity[1]), None)
            if device is None:
                return
            now = time.monotonic()
            self._nonces = {key: value for key, value in self._nonces.items() if value["until"] > now}
            fields = digest_fields(message.headers.get("authorization", ""))
            nonce = self._nonces.get(fields.get("nonce", ""))
            request_uri = message.start.split(" ")[1]
            nc = fields.get("nc", "")
            fingerprint = (message.headers["call-id"], message.headers["cseq"], message.headers.get("authorization"))
            # 部分海康固件使用 SIP 账户做摘要用户名，其他设备使用独立认证 ID。
            valid = bool(nonce and nonce["device"] == device.id
                         and fields.get("username") in {device.auth_id, device.username}
                         and fields.get("realm") == SIP_REALM and fields.get("uri") == request_uri
                         and fields.get("qop") == "auth" and fields.get("cnonce")
                         and re.fullmatch(r"[a-fA-F0-9]{8}", nc)
                         and re.fullmatch(r"[a-fA-F0-9]{32}", fields.get("response", ""))
                         and fields.get("algorithm", "MD5").upper() == "MD5")
            if valid:
                expected = digest_value(fields["username"], device.password, SIP_REALM, fields["nonce"],
                                        "REGISTER", request_uri, qop="auth", nc=nc, cnonce=fields["cnonce"])
                valid = hmac.compare_digest(fields.get("response", ""), expected)
                valid = valid and (int(nc, 16) > nonce["nc"] or fingerprint == nonce.get("fingerprint"))
            if not valid:
                if len(self._nonces) >= 512:
                    self._nonces.pop(next(iter(self._nonces)))
                token = secrets.token_hex(24)
                self._nonces[token] = {"device": device.id, "until": now + 300, "nc": 0}
                challenge = f'Digest realm="{SIP_REALM}", nonce="{token}", algorithm=MD5, qop="auth"'
                self.send(response(message, 401, extra={"WWW-Authenticate": challenge}), peer)
                return
            nonce.update(nc=int(nc, 16), fingerprint=fingerprint)
            try:
                expires = min(max(int(message.headers.get("expires", "3600")), 0), 3600)
            except ValueError:
                self.send(response(message, 400), peer)
                return
            self._registered[device.id] = now + expires if expires else 0
            extra = {"Expires": str(expires)}
            if "contact" in message.headers:
                extra["Contact"] = message.headers["contact"]
            self.send(response(message, 200, extra=extra), peer)

    def play(self, horn_id: int, audio: bytes, cancel: threading.Event, *, expires_at: float | None = None) -> None:
        """播放只读取当前设备身份，同台设备禁止同时开启多个呼叫。"""
        with self._lock:
            if self._socket is None:
                raise SipAudioError("SIP 服务尚未启动，请先在喇叭配置中启用")
            device = self._devices.get(horn_id)
            if device is None:
                raise SipAudioError("喇叭的 SIP 参数尚未同步，请保存设备配置后重试")
            if any(call.device.id == horn_id for call in self._calls.values()):
                raise SipAudioError("这台喇叭正在播放，请等待播放完成")
            call = SipCall(self, device, self._config, cancel)
            self._calls[call.id] = call
        try:
            call.play(audio, expires_at)
        finally:
            with self._lock:
                self._calls.pop(call.id, None)

    def stop(self) -> None:
        """先关闭播放入口并唤醒会话，资源归属保持在当前服务实例。"""
        with self._lock:
            for call in self._calls.values():
                call.cancel.set()
            self._stop.set()
            if self._socket is not None:
                self._socket.close()
                self._socket = None
            self._registered.clear()
        if self._thread is not None:
            self._thread.join(timeout=1)


class SipCall:
    """单次有界 SIP 会话；拨号、发送、取消、挂断始终共用同一设备身份。"""

    def __init__(self, server: SipAudioServer, device: SipDevice, config: SipServerConfig, cancel: threading.Event):
        """只保存本次参数，socket 在播放作用域内创建和关闭。"""
        self.server, self.device, self.config, self.cancel = server, device, config, cancel
        self.id = secrets.token_hex(16) + "@" + config.address
        self.tag = secrets.token_hex(12)
        self.branch = "z9hG4bK" + secrets.token_hex(12)
        self.target = f"sip:{device.username}@{device.host}:{device.port}"
        self.to = f"<{self.target}>"
        self.from_header = f"<sip:aivision@{config.address}:{config.port}>;tag={self.tag}"
        self.peer = (device.host, device.port)
        self.messages: queue.Queue[SipMessage] = queue.Queue(maxsize=32)
        self.cseq = 1
        self.established = False
        self.pending = False
        self.remote_hangup = threading.Event()

    def receive(self, message: SipMessage) -> None:
        """接收线程只投递匹配会话的控制消息，不处理音频。"""
        if message.status and f"tag={self.tag}" not in message.headers["from"]:
            return
        if message.start.startswith("BYE "):
            if f"tag={self.tag}" in message.headers["to"]:
                self.server.send(response(message, 200), self.peer)
                self.remote_hangup.set()
            return
        try:
            self.messages.put_nowait(message)
        except queue.Full:
            logger.debug("[HornSIP] 会话重复控制报文过多，已丢弃")

    def request(self, method: str, *, body: str = "", branch: str | None = None,
                authentication: tuple[str, str] | None = None) -> bytes:
        """报文由受校验的配置构建，不采用设备返回的 Contact 重定向发送地址。"""
        branch = branch or "z9hG4bK" + secrets.token_hex(12)
        headers = (f"{method} {self.target} SIP/2.0\r\n"
                   f"Via: SIP/2.0/UDP {self.config.address}:{self.config.port};branch={branch};rport\r\n"
                   f"Max-Forwards: 70\r\nFrom: {self.from_header}\r\nTo: {self.to}\r\n"
                   f"Call-ID: {self.id}\r\nCSeq: {self.cseq} {method}\r\n"
                   f"Contact: <sip:aivision@{self.config.address}:{self.config.port}>\r\nUser-Agent: AiVision\r\n")
        if method == "INVITE":
            headers += f"Call-Info: <sip:aivision@{self.config.address}>;answer-after=0\r\n"
        if authentication:
            headers += f"{authentication[0]}: {authentication[1]}\r\n"
        if body:
            headers += "Content-Type: application/sdp\r\n"
        raw = body.encode()
        return (headers + f"Content-Length: {len(raw)}\r\n\r\n").encode() + raw

    def stopped(self) -> bool:
        """停止设备、关闭服务或设备主动挂断都立即终止发声。"""
        return self.cancel.is_set() or self.remote_hangup.is_set() or not self.server.status()["running"]

    def _invite(self, port: int, expires_at: float | None) -> tuple[str, int]:
        """重传同一事务不会重复播放，接听后才允许发送 RTP。"""
        body = (f"v=0\r\no=aivision {int(time.time())} 1 IN IP4 {self.config.address}\r\n"
                f"s=AiVision alarm\r\nc=IN IP4 {self.config.address}\r\nt=0 0\r\n"
                f"m=audio {port} RTP/AVP 8\r\na=rtpmap:8 PCMA/8000\r\na=sendonly\r\na=ptime:20\r\n")
        packet = self.request("INVITE", body=body, branch=self.branch)
        self.pending = True
        self.server.send(packet, self.peer)
        deadline = time.monotonic() + settings.alarm.horn_sip_call_timeout
        retry, interval, provisional, challenged = time.monotonic() + 0.5, 0.5, False, False
        while not self.stopped() and time.monotonic() < deadline:
            if expires_at is not None and time.monotonic() >= expires_at:
                raise SipAudioError("告警等待播放已过期，已取消本次呼叫")
            try:
                message = self.messages.get(timeout=0.1)
            except queue.Empty:
                if not provisional and time.monotonic() >= retry:
                    self.server.send(packet, self.peer)
                    interval = min(interval * 2, 2)
                    retry = time.monotonic() + interval
                continue
            if message.headers["cseq"] != f"{self.cseq} INVITE":
                continue
            if 100 <= message.status < 200:
                provisional = True
                continue
            if message.status == 200:
                self.to = message.headers["to"]
                self.server.send(self.request("ACK"), self.peer)
                self.established, self.pending = True, False
                return audio_destination(message.body, self.device.host)
            if message.status >= 300:
                self.to = message.headers["to"]
                self.server.send(self.request("ACK", branch=self.branch), self.peer)
                if message.status in {401, 407} and not challenged:
                    key = "www-authenticate" if message.status == 401 else "proxy-authenticate"
                    value = authorization(message.headers.get(key, ""), self.device.auth_id,
                                          self.device.password, "INVITE", self.target)
                    self.cseq += 1
                    self.branch = "z9hG4bK" + secrets.token_hex(12)
                    self.to = f"<{self.target}>"
                    header = "Authorization" if message.status == 401 else "Proxy-Authorization"
                    packet = self.request("INVITE", body=body, branch=self.branch, authentication=(header, value))
                    self.server.send(packet, self.peer)
                    provisional, challenged = False, True
                    continue
                self.pending = False
                raise SipAudioError(f"喇叭拒绝 SIP 播放（状态 {message.status}），请检查账户、设备启用状态和编码")
        raise SipAudioError("SIP 呼叫已取消" if self.stopped() else "喇叭 SIP 接听超时，请检查设备端口和网络")

    def _release(self) -> None:
        """所有退出路径都终止事务，防止设备继续占用广播通道。"""
        if self.remote_hangup.is_set():
            return
        method = "BYE" if self.established else "CANCEL"
        if not self.established and not self.pending:
            return
        if self.established:
            self.cseq += 1
        packet = self.request(method, branch=self.branch if method == "CANCEL" else None)
        try:
            self.server.send(packet, self.peer)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                try:
                    message = self.messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                if message.headers["cseq"].endswith(method) and message.status >= 200:
                    return
                if method == "CANCEL" and message.headers["cseq"].endswith("INVITE") and message.status == 200:
                    # CANCEL 与接听交叉时仍须 ACK 后 BYE，不能留下已建立但无人释放的会话。
                    self.to = message.headers["to"]
                    self.server.send(self.request("ACK"), self.peer)
                    self.cseq += 1
                    self.server.send(self.request("BYE"), self.peer)
                    return
            logger.debug("[HornSIP] 设备未确认挂断，本地音频已停止")
        except SipAudioError:
            logger.debug("[HornSIP] 服务关闭期间已终止本地音频")

    def play(self, audio: bytes, expires_at: float | None) -> None:
        """按 20ms 发送 PCMA；同一呼叫只播一次，尾部静音让解码器自然排空。"""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rtp:
            try:
                rtp.bind((self.config.address, 0))
                destination = self._invite(rtp.getsockname()[1], expires_at)
                sequence, stamp, ssrc = secrets.randbits(16), secrets.randbits(32), secrets.randbits(32)
                started = time.monotonic()
                data = audio + SILENCE * (SAMPLE_RATE // 5)
                for offset in range(0, len(data), PACKET_SAMPLES):
                    if self.stopped():
                        raise SipAudioError("SIP 播放已停止")
                    delay = started + offset / SAMPLE_RATE - time.monotonic()
                    if delay > 0 and self.cancel.wait(delay):
                        raise SipAudioError("SIP 播放已停止")
                    payload = data[offset:offset + PACKET_SAMPLES].ljust(PACKET_SAMPLES, SILENCE)
                    packet = struct.pack("!BBHII", 128, 136 if offset == 0 else 8, sequence, stamp, ssrc) + payload
                    rtp.sendto(packet, destination)
                    sequence, stamp = (sequence + 1) & 65535, (stamp + PACKET_SAMPLES) & 0xffffffff
            except OSError:
                raise SipAudioError("SIP 音频发送失败，请检查服务器地址和到喇叭的网络") from None
            finally:
                self._release()
