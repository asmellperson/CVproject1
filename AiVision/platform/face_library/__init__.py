"""本地人员资料库；不包含图片下载、身份识别或接口路由。"""

HIKVISION_SOURCES = ("one", "two")


class PersonSyncError(RuntimeError):
    """不含人员字段的完整性检查错误。"""
