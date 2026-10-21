"""受管 AAC 素材库；上传时完整校验并预先转换 SIP 所需的 G.711 A-law。"""
from __future__ import annotations

from pathlib import Path
import audioop
import re
import subprocess
import tempfile
import uuid

from AiVision.core.db import get_session, session_scope
from AiVision.core.settings import settings
from .orm import AiHornAudio, AiHornConfig
from .schema import DEFAULT_VOLUME_PERCENT, MAX_VOLUME_PERCENT


SAMPLE_RATE = 8000
PACKET_SAMPLES = 160
SILENCE = b"\xd5"


class HornAudioError(ValueError):
    """可向前端公开的上传或音频读取错误。"""


class HornAudioService:
    """数据库只记录已验证素材，随机磁盘名不接受调用方路径。"""

    @property
    def root(self) -> Path:
        """音频库独立于按日期清理的报警证据目录。"""
        root = Path(settings.storage.data_path).expanduser().resolve() / "horn_audio"
        if root.is_symlink():
            raise HornAudioError("音频库目录不能是符号链接，请检查服务器存储配置")
        return root

    @staticmethod
    def public(row: AiHornAudio) -> dict:
        """隐藏内部磁盘位置。"""
        return {"id": row.id, "name": row.name, "size": row.size, "duration": row.duration}

    def list_audio(self) -> list[dict]:
        """返回共享音频库，供设备试播和所有检测配置选择。"""
        session = get_session()
        try:
            return [self.public(row) for row in session.query(AiHornAudio).order_by(AiHornAudio.id.desc()).all()]
        finally:
            session.close()

    def upload(self, filename: str, data: bytes) -> dict:
        """限制文件格式、字节数与解码时长，转码成功后原子保存素材。"""
        if (not filename or len(filename) > 255 or any(c in filename for c in "/\\\x00\r\n")
                or Path(filename).suffix.lower() != ".aac"):
            raise HornAudioError("请选择文件名有效的 .aac 音频")
        if not data or len(data) > settings.alarm.horn_audio_max_bytes:
            raise HornAudioError(f"音频不能为空，且不能超过 {settings.alarm.horn_audio_max_bytes // 1024 // 1024} MB")
        root = self.root
        root.mkdir(parents=True, exist_ok=True)
        key = uuid.uuid4().hex
        targets = [root / f"{key}.aac", root / f"{key}.alaw"]
        try:
            with tempfile.TemporaryDirectory(prefix=".upload-", dir=root) as temporary:
                source = Path(temporary) / "source.aac"
                source.write_bytes(data)
                encoded = self.convert(source)
                pcm = Path(temporary) / "audio.alaw"
                pcm.write_bytes(encoded)
                source.replace(targets[0])
                pcm.replace(targets[1])
            with session_scope() as session:
                row = AiHornAudio(name=filename, storage_key=key, size=len(data), duration=len(encoded) / SAMPLE_RATE)
                session.add(row)
                session.flush()
                result = self.public(row)
            return result
        except BaseException:
            # 事务失败或请求取消时不留下既没有记录又占用空间的素材。
            for target in targets:
                target.unlink(missing_ok=True)
            raise

    @staticmethod
    def convert(source: Path) -> bytes:
        """只解析本地 AAC，禁止播放列表访问外网，并给转换过程设置时间和输出上限。"""
        maximum = settings.alarm.horn_audio_max_seconds
        try:
            result = subprocess.run([
                settings.alarm.horn_audio_ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-protocol_whitelist", "file,pipe", "-f", "aac", "-i", str(source),
                "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
                "-t", str(maximum + 0.04), "-c:a", "pcm_alaw", "-f", "alaw", "pipe:1",
            ], capture_output=True, timeout=settings.alarm.horn_audio_convert_timeout, check=False)
        except FileNotFoundError:
            raise HornAudioError("服务器未安装 FFmpeg，请安装后再上传音频") from None
        except (OSError, subprocess.TimeoutExpired):
            raise HornAudioError("音频转换失败或超时，请检查文件后重试") from None
        if result.returncode or not result.stdout:
            raise HornAudioError("AAC 无法正常解码，请确认文件包含有效的音频内容")
        if len(result.stdout) > int(maximum * SAMPLE_RATE):
            raise HornAudioError(f"音频时长不能超过 {maximum:g} 秒")
        return result.stdout

    @staticmethod
    def adjust_volume(data: bytes, volume_percent: int) -> bytes:
        """在 PCM 上缩放并饱和限幅，避免直接修改压缩字节导致噪音或幅值溢出。"""
        if type(volume_percent) is not int or not 0 <= volume_percent <= MAX_VOLUME_PERCENT:
            raise HornAudioError(f"音频响度必须是 0–{MAX_VOLUME_PERCENT} 的整数百分比")
        if volume_percent == DEFAULT_VOLUME_PERCENT:
            return data
        pcm = audioop.alaw2lin(data, 2)
        adjusted = audioop.mul(pcm, 2, volume_percent / DEFAULT_VOLUME_PERCENT)
        return audioop.lin2alaw(adjusted, 2)

    def read_encoded(self, audio_id: int, *, volume_percent: int = DEFAULT_VOLUME_PERCENT) -> bytes:
        """只读取已登记素材，按设备响度生成本次播放数据，不改写共享原文件。"""
        session = get_session()
        try:
            row = session.get(AiHornAudio, audio_id)
            if row is None:
                raise HornAudioError("音频素材不存在，请重新上传或选择")
            key = row.storage_key
        finally:
            session.close()
        if not re.fullmatch(r"[a-f0-9]{32}", key):
            raise HornAudioError("音频素材记录无效，请重新上传")
        path = self.root / f"{key}.alaw"
        if path.is_symlink():
            raise HornAudioError("音频素材文件无效，请重新上传")
        try:
            with path.open("rb") as source:
                data = source.read(int(settings.alarm.horn_audio_max_seconds * SAMPLE_RATE) + 1)
        except OSError:
            raise HornAudioError("服务器音频文件缺失或不可读，请重新上传") from None
        if not data or len(data) > int(settings.alarm.horn_audio_max_seconds * SAMPLE_RATE):
            raise HornAudioError("服务器音频文件损坏，请重新上传")
        return self.adjust_volume(data, volume_percent)

    def delete(self, audio_id: int) -> bool:
        """已被检测绑定的素材必须先解绑，避免删除后静默丢失告警声音。"""
        from AiVision.features.registry import all_specs
        from AiVision.features._shared.orm import FeatureConfigBase
        from AiVision.features.logistics_channel.orm import LogisticsChannel
        from AiVision.features.guard_behavior.orm import GuardBehaviorAlarmPolicy

        with session_scope() as session:
            row = session.get(AiHornAudio, audio_id, with_for_update=True)
            if row is None:
                return False
            models = [spec.orm_class for spec in all_specs().values()
                      if issubclass(spec.orm_class, FeatureConfigBase)] + [LogisticsChannel, GuardBehaviorAlarmPolicy]
            for model in models:
                bound = session.query(model).join(AiHornConfig, model.horn_id == AiHornConfig.id).filter(
                    model.horn_event_id == audio_id, AiHornConfig.sip_config.is_not(None),
                ).first()
                if bound is not None:
                    raise HornAudioError("音频仍被检测配置引用，请先解除绑定")
            key = row.storage_key
            session.delete(row)
        if re.fullmatch(r"[a-f0-9]{32}", key):
            for suffix in ("aac", "alaw"):
                (self.root / f"{key}.{suffix}").unlink(missing_ok=True)
        return True


horn_audio_service = HornAudioService()
