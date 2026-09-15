"""手动完整同步 one、two：python -m AiVision.features.face_recognition.library.sync。"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.exc import SQLAlchemyError

from AiVision.connectors.hikvision import HikvisionClient, HikvisionConfig, HikvisionError, HikvisionPerson, HikvisionPersons
from AiVision.connectors.hikvision.client import DEFAULT_TIMEOUT
from AiVision.core.logger import logger

from . import HIKVISION_SOURCES, PersonSyncError

if TYPE_CHECKING:
    from .service import FaceLibraryService, SyncCounts

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class HikvisionSyncSettings(BaseSettings):
    """按 HIKVISION_ONE_ / HIKVISION_TWO_ 前缀从环境读取，不在应用启动时强制要求凭据。"""

    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)
    base_url: str
    app_key: SecretStr
    app_secret: SecretStr
    artemis_path: str = "/artemis"
    verify_tls: bool = True
    page_size: int = Field(default=100, ge=1)
    connect_timeout: float = Field(default=DEFAULT_TIMEOUT[0], gt=0, allow_inf_nan=False)
    read_timeout: float = Field(default=DEFAULT_TIMEOUT[1], gt=0, allow_inf_nan=False)

    def client_config(self) -> HikvisionConfig:
        return HikvisionConfig(
            base_url=self.base_url, app_key=self.app_key.get_secret_value(),
            app_secret=self.app_secret.get_secret_value(), artemis_path=self.artemis_path,
            verify_tls=self.verify_tls, timeout=(self.connect_timeout, self.read_timeout),
        )


def fetch_persons(persons: HikvisionPersons, *, page_size: int) -> tuple[HikvisionPerson, ...]:
    """完整获取并核对分页；总数变化、缺页或重复人员均视为本次失败。"""
    if type(page_size) is not int or page_size < 1:
        raise ValueError("page_size must be a positive integer")
    collected: list[HikvisionPerson] = []
    person_ids: set[str] = set()
    total = None
    page_no = 1
    while True:
        try:
            page = persons.list_persons(page_no=page_no, page_size=page_size)
        except HikvisionError as exc:
            raise PersonSyncError(f"personList 第 {page_no} 页失败：{exc}") from None
        if page.page_no != page_no or page.page_size != page_size:
            raise PersonSyncError(f"personList 第 {page_no} 页的页码或分页大小不一致")
        if total is None:
            total = page.total
        if page.total != total:
            raise PersonSyncError(f"personList 第 {page_no} 页总数发生变化，需重新完整同步")
        if len(page.persons) != min(page_size, total - len(collected)):
            raise PersonSyncError(f"personList 第 {page_no} 页人员数量不完整")
        for person in page.persons:
            if person.person_id in person_ids:
                raise PersonSyncError(f"personList 第 {page_no} 页出现重复 personId")
            person_ids.add(person.person_id)
            collected.append(person)
        if len(collected) == total:
            return tuple(collected)
        page_no += 1


def sync_source(source: str, persons: HikvisionPersons, service: FaceLibraryService, *, page_size: int) -> SyncCounts:
    snapshot = fetch_persons(persons, page_size=page_size)
    return service.apply_snapshot(source, snapshot)


def _error_summary(exc: Exception) -> str:
    # 数据库异常原文可能带 SQL 参数，配置异常原文可能带密钥；仅输出安全的错误类别/代码。
    if isinstance(exc, ValidationError):
        fields = ", ".join(".".join(map(str, item["loc"])) for item in exc.errors(include_input=False))
        return f"环境配置缺失或不合法：{fields}"
    if isinstance(exc, SQLAlchemyError):
        args = getattr(getattr(exc, "orig", None), "args", ())
        code = f"，数据库错误码 {args[0]}" if args and isinstance(args[0], int) else ""
        return f"{type(exc).__name__}{code}"
    if isinstance(exc, PersonSyncError):
        return str(exc)
    return type(exc).__name__


def main() -> int:
    # 与 AiVision 主入口使用同一个 .env 位置；已有系统环境变量优先。
    load_dotenv(dotenv_path=_ENV_FILE, override=False)
    try:
        from AiVision.core.db import get_engine
        from AiVision.core.settings import settings
        from .orm import FacePerson
        from .service import FaceLibraryService

        if not settings.db.enable:
            logger.error("[FaceLibrary] SQL_ENABLE=false，未执行同步")
            return 1
        # ORM 导入即注册到现有 Base；只创建本任务的新表，不检查或修改其他表。
        FacePerson.__table__.create(bind=get_engine(), checkfirst=True)
    except Exception as exc:
        logger.error(f"[FaceLibrary] 数据库初始化失败：{_error_summary(exc)}")
        return 1

    service = FaceLibraryService()
    failed = False
    for source in HIKVISION_SOURCES:
        logger.info(f"[FaceLibrary] 开始同步 {source}")
        try:
            config = HikvisionSyncSettings(_env_prefix=f"HIKVISION_{source.upper()}_")
            with HikvisionClient(config.client_config()) as client:
                counts = sync_source(source, HikvisionPersons(client), service, page_size=config.page_size)
        except Exception as exc:
            failed = True
            print(f"{source}:\n总数 未完成完整获取或提交\n新增 0\n更新 0\n未变化 0\n停用 0\n失败 1（来源同步失败）")
            logger.error(f"[FaceLibrary] {source} 同步失败，人员事务未提交：{_error_summary(exc)}")
        else:
            print(
                f"{source}:\n总数 {counts.total}\n新增 {counts.inserted}\n更新 {counts.updated}"
                f"\n未变化 {counts.unchanged}\n停用 {counts.deactivated}\n失败 0",
                flush=True,
            )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
