"""复用系统 JSON 配置表管理 SIP 服务，并维护进程内监听器生命周期。"""
from __future__ import annotations

import threading

from AiVision.core.system_config import SystemConfigService
from AiVision.core.logger import logger
from .schema import SipServerConfig
from .sip_protocol import SipAudioError
from .sip_server import SipAudioServer


class HornSipService(SystemConfigService):
    """服务器参数集中配置，每台喇叭的身份仍由设备配置表管理。"""
    CONFIG_KEY = "horn_sip_server"

    def __init__(self, server=None):
        """构造时不读数据库或打开端口。"""
        self.server = server or SipAudioServer()
        self._lock = threading.RLock()
        self._error = None

    def config(self) -> SipServerConfig:
        """缺少配置时默认关闭 SIP，不绑定猜测的服务器地址。"""
        return SipServerConfig.model_validate(self._get_value(self.CONFIG_KEY) or {})

    def public(self) -> dict:
        """读取保存值及监听状态，不通过查询接口隐式启动服务。"""
        config = self.config()
        status = self.server.status()
        return {**config.model_dump(), "running": status["running"],
                "last_error": self._error or status["last_error"]}

    def ensure_started(self) -> dict:
        """启动入口或显式试播可以恢复已保存的服务配置。"""
        with self._lock:
            try:
                self.server.configure(self.config())
                self._error = None
            except SipAudioError as exc:
                self._error = str(exc)
                raise
            return self.server.status()

    def start(self) -> None:
        """监听失败保留错误供前端修正，不阻止视觉检测主进程启动。"""
        try:
            self.ensure_started()
        except Exception as exc:
            self._error = str(exc) if isinstance(exc, SipAudioError) else "SIP 服务配置暂时无法读取"
            logger.warning(f"[HornSIP] {self._error}")

    def save(self, config: SipServerConfig) -> dict:
        """先验证端口可监听，再提交数据库；提交失败恢复原监听参数。"""
        with self._lock:
            old = self.config()
            self.server.configure(config)
            try:
                self._set_value(self.CONFIG_KEY, config.model_dump())
            except BaseException:
                self.server.configure(old)
                raise
            self._error = None
            return self.public()


horn_sip_service = HornSipService()
