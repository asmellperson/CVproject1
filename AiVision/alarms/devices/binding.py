"""普通功能、物流通道及保安室共用的喇叭归属和绑定校验。"""
from sqlalchemy.orm import Session

from .orm import AiHornAudio, AiHornConfig


MAX_HORN_ID = 2_147_483_647  # 现有数据库 Integer 字段的有符号上限。


def validate_horn_binding(session: Session, enabled: bool, horn_id, event_id, *, department: str) -> None:
    """校验设备和任务 ID，并锁定设备核对存在性与启用状态。

    启用通道必须完整绑定且设备可用；停用通道允许保留设备关联。
    调用方负责提交事务，本函数不登录设备或播放语音。
    """
    for field, value in (("horn_id", horn_id), ("horn_event_id", event_id)):
        if value is not None and (type(value) is not int or not 0 < value <= MAX_HORN_ID):
            raise ValueError(f"{field} 必须是 1 到 {MAX_HORN_ID} 之间的整数")
    if enabled and (horn_id is None or event_id is None):
        raise ValueError("启用喇叭告警时必须选择喇叭设备并填写语音任务 ID")
    if horn_id is None:
        return
    # 在写入关系前锁住设备，避免校验成功后被并发删除；停用绑定允许保留原设备。
    with session.no_autoflush:
        horn = session.get(AiHornConfig, horn_id, with_for_update=True)
    if horn is None:
        raise ValueError(f"喇叭设备 #{horn_id} 不存在，请重新选择或清除绑定")
    if horn.department != department:
        raise ValueError("所选喇叭不属于当前事业部，请先分配设备归属或重新选择")
    if enabled and not horn.enable:
        raise ValueError(f"喇叭设备 #{horn_id} 已停用，请选择已启用设备或关闭喇叭告警")
    if enabled and horn.sip_config and session.get(AiHornAudio, event_id, with_for_update=True) is None:
        raise ValueError("所选服务器音频不存在，请重新上传或选择音频")
