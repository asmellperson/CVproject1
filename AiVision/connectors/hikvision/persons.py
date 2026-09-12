"""iSecure Center 人员查询与照片读取，不涉及本地人员库或身份识别。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from AiVision.core.logger import logger

from .client import HikvisionClient, HikvisionError, HikvisionPicture

PERSON_LIST_PATH = "/api/resource/v1/person/personList"
PERSON_INFO_PATH = "/api/resource/v1/person/personId/personInfo"
# 官方“提取人员图片”，适用于 iSecure Center V1.0 及以上；不是 HikCentral 的 picture_data。
# https://open.hikvision.com/docs/e76113d6-d2b6-4bf1-a71c-4a3126412d8f
PERSON_PICTURE_PATH = "/api/resource/v1/person/picture"


class PersonPhoto(BaseModel):
    model_config = ConfigDict(populate_by_name=True, frozen=True)
    pic_uri: str | None = Field(default=None, alias="picUri", repr=False)
    server_index_code: str | None = Field(default=None, alias="serverIndexCode", repr=False)


class HikvisionPerson(BaseModel):
    model_config = ConfigDict(populate_by_name=True, frozen=True)
    person_id: str = Field(alias="personId", min_length=1, repr=False)
    person_name: str | None = Field(default=None, alias="personName", repr=False)
    person_code: str | None = Field(default=None, alias="personCode", repr=False)
    job_no: str | None = Field(default=None, alias="jobNo", repr=False)
    person_photo: PersonPhoto | None = Field(default=None, alias="personPhoto", repr=False)


class PersonPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, frozen=True)
    total: int = Field(ge=0)
    page_no: int = Field(alias="pageNo", ge=1)
    page_size: int = Field(alias="pageSize", ge=1)
    persons: tuple[HikvisionPerson, ...] = Field(alias="list", repr=False)


class HikvisionPersons:
    """外部人员接口。client 的生命周期由调用方管理，可在同一平台复用连接。"""

    def __init__(self, client: HikvisionClient):
        self.client = client

    def list_persons(self, page_no: int = 1, page_size: int = 10) -> PersonPage:
        if any(type(value) is not int or value < 1 for value in (page_no, page_size)):
            raise ValueError("page_no and page_size must be positive integers")
        result = self.client.post_json(PERSON_LIST_PATH, {"pageNo": page_no, "pageSize": page_size})
        try:
            page = PersonPage.model_validate(result["data"])
        except ValidationError:
            raise HikvisionError("Invalid personList response data") from None
        logger.debug(f"[Hikvision] personList page={page.page_no}, count={len(page.persons)}, total={page.total}")
        return page

    def get_person(self, person_id: str) -> HikvisionPerson:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a nonempty string")
        result = self.client.post_json(PERSON_INFO_PATH, {"personId": person_id})
        try:
            return HikvisionPerson.model_validate(result["data"])
        except ValidationError:
            raise HikvisionError("Invalid personInfo response data") from None

    def get_picture(self, photo: PersonPhoto) -> HikvisionPicture:
        """使用人员列表/详情实际返回的 picUri + serverIndexCode 获取图片字节。"""
        if not photo.pic_uri or not photo.server_index_code:
            raise ValueError("A person picture requires both picUri and serverIndexCode")
        response = self.client.post(PERSON_PICTURE_PATH, {
            "picUri": photo.pic_uri, "serverIndexCode": photo.server_index_code,
        })
        return self.client.download_picture(response, sensitive_values=(photo.pic_uri, photo.server_index_code))
