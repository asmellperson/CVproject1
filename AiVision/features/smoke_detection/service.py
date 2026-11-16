"""连接平台配置与设备接口；设备参数不写入平台算法配置。"""
from __future__ import annotations

from contextlib import closing

from .device import SmokeDeviceClient
from .device_schema import SmokeParametersUpdate, SmokeShieldUpdate


class SmokeDeviceService:
    """每次读取当前摄像头配置，避免修改连接后仍访问旧设备。"""

    def __init__(self, client_factory=SmokeDeviceClient):
        self.client_factory = client_factory

    def _client(self, camera: dict, config: dict):
        return self.client_factory(camera, config["value"])

    def parameters(self, camera: dict, config: dict):
        with closing(self._client(camera, config)) as client:
            return client.read_parameters()

    def save_parameters(self, camera: dict, config: dict, payload: SmokeParametersUpdate):
        with closing(self._client(camera, config)) as client:
            return client.write_parameters(payload)

    def shields(self, camera: dict, config: dict):
        with closing(self._client(camera, config)) as client:
            return client.read_shields()

    def save_shields(self, camera: dict, config: dict, payload: SmokeShieldUpdate):
        with closing(self._client(camera, config)) as client:
            return client.write_shields(payload)

    def picture(self, camera: dict, config: dict) -> bytes:
        with closing(self._client(camera, config)) as client:
            return client.read_picture()


smoke_device_service = SmokeDeviceService()
