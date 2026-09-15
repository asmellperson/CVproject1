"""人脸识别的人员资料、注册照片特征、特征索引及人员同步。

本入口仅定义来源标识和同步异常；模型实现留在 inference/，海康协议
留在 connectors/hikvision/。导入不执行同步、特征生成或后台任务。
"""

HIKVISION_SOURCES = ("one", "two")


class PersonSyncError(RuntimeError):
    """不含人员字段的完整性检查错误。"""
