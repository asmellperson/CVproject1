# wechat_sender.py
"""
企业微信消息发送模块。

负责与企业微信服务端 API 直接交互，完成以下步骤：
    1. get_access_token()  —— 获取调用凭证（access_token）；
    2. upload_video_file() —— 将 MP4 上传到素材库，获取 media_id；
    3. send_message()      —— 以视频消息发送给指定用户。

当前发送策略：仅发送视频消息。
以下功能已实现但暂时注释掉，可按需启用：
    - markdown 文字消息（事件摘要）；
    - 图片消息（Base64WeChatUploader）。

IP 白名单说明：
    企业微信要求调用方服务器 IP 在管理后台的可信 IP 列表中；
    IP 被拒绝时（errcode=60020）_describe_wechat_error() 会提取出口 IP
    并给出具体的配置指引，便于运维快速定位问题。
"""
from __future__ import annotations

import base64
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional

import requests


# 企业微信 IP 白名单校验失败的错误码
WECHAT_IP_DENIED_ERRCODE = 60020


def _extract_wechat_from_ip(errmsg: str) -> Optional[str]:
    """从企业微信错误信息中提取"from ip: x.x.x.x"的 IP 地址。

    企业微信在 errcode=60020 时会在 errmsg 中附带出口 IP，
    提取后可直接告知运维人员需要加白名单的地址。
    """
    match = re.search(r"from ip:\s*([^,\s]+)", errmsg or "")
    return match.group(1) if match else None


def _describe_wechat_error(action: str, result: Dict) -> str:
    """将企业微信 API 的错误响应转换为人类可读的诊断信息。

    对 IP 白名单错误（60020）特殊处理：附加出口 IP 和具体操作指引，
    其余错误直接返回原始响应字典的字符串表示。

    Args:
        action: 失败的操作名称，如 "视频上传"、"消息发送"。
        result: 企业微信 API 返回的 JSON 字典。

    Returns:
        可直接打印的错误描述字符串。
    """
    errcode = result.get("errcode")
    errmsg = result.get("errmsg", "")

    if errcode == WECHAT_IP_DENIED_ERRCODE:
        from_ip = _extract_wechat_from_ip(str(errmsg))
        ip_text = f" 当前出口 IP: {from_ip}." if from_ip else ""
        return (
            f"{action}失败: 企业微信拒绝当前服务器 IP 访问接口(errcode=60020)."
            f"{ip_text} 请在企业微信管理后台把该 IP 加入应用可信 IP/白名单，"
            "或把服务部署到固定出口 IP 后再配置白名单。"
        )

    return f"{action}失败: {result}"


# ---------------------------------------------------------------------------
# 图片上传（Base64）—— 当前注释掉，保留供后续启用
# ---------------------------------------------------------------------------

class Base64WeChatUploader:
    """将 Base64 编码的图片上传到企业微信临时素材库。

    上传后返回 media_id，可用于后续的图片消息发送。
    当前发送流程已改为仅发视频，此类暂未被 send_message() 调用。
    """

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = "https://qyapi.weixin.qq.com/cgi-bin/media/upload"

    def extract_base64_data(self, base64_string: str) -> tuple[str, str, str]:
        """解析 Base64 字符串，返回 (纯 Base64 数据, 图片格式, MIME 类型)。

        支持两种输入格式：
          1. 带 Data URL 头部：  "data:image/jpeg;base64,/9j/..."
          2. 裸 Base64 字符串：  "/9j/..."（通过前缀魔数推断格式）

        魔数识别规则：
            /9j/   —— JPEG
            iVBOR  —— PNG
            R0lGOD —— GIF
            其余   —— 默认按 JPEG 处理
        """
        header_pattern = r"data:(image/([^;]+));base64,"
        match = re.match(header_pattern, base64_string)

        if match:
            mime_type = match.group(1)
            image_format = match.group(2)
            pure_base64 = base64_string.split(",", 1)[1]
            return pure_base64, image_format, mime_type

        # 无头部，按魔数推断格式
        pure_base64 = base64_string
        if base64_string.startswith("/9j"):
            return pure_base64, "jpeg", "image/jpeg"
        if base64_string.startswith("iVBOR"):
            return pure_base64, "png", "image/png"
        if base64_string.startswith("R0lGOD"):
            return pure_base64, "gif", "image/gif"
        return pure_base64, "jpeg", "image/jpeg"   # 兜底：默认 JPEG

    def upload_base64_image(self, base64_data: str, filename: Optional[str] = None) -> Dict:
        """上传图片到企业微信临时素材库，返回 API 响应字典。

        上传失败时返回 {"errcode": -1, "errmsg": "..."} 而非抛出异常，
        调用方通过检查 errcode 判断是否成功。
        """
        try:
            pure_base64, image_format, mime_type = self.extract_base64_data(base64_data)
            image_binary = base64.b64decode(pure_base64)

            if filename is None:
                filename = f"alarm_{int(time.time())}.{image_format}"

            params = {"access_token": self.access_token, "type": "image"}
            files = {"media": (filename, BytesIO(image_binary), mime_type)}

            response = requests.post(self.base_url, params=params, files=files, timeout=30)
            return self._handle_response(response)

        except Exception as e:
            return {"errcode": -1, "errmsg": f"upload_base64_image failed: {e}"}

    @staticmethod
    def _handle_response(response: requests.Response) -> Dict:
        """将 HTTP 响应解析为字典；解析失败时返回统一的错误格式。"""
        try:
            return response.json()
        except Exception:
            return {"errcode": -1, "errmsg": f"invalid response: {response.text}"}


# ---------------------------------------------------------------------------
# 核心 API 调用
# ---------------------------------------------------------------------------

def get_access_token(corpid: str, corpsecret: str) -> str:
    """向企业微信获取 access_token（调用凭证）。

    access_token 有效期约 2 小时，当前每次推送前都重新获取，
    无本地缓存——推送频率低时可接受，高频场景可加 TTL 缓存优化。

    Args:
        corpid:     企业微信企业 ID。
        corpsecret: 自建应用 Secret。

    Returns:
        有效的 access_token 字符串。

    Raises:
        RuntimeError: 获取失败（网络错误或凭证无效）时抛出，含完整响应信息。
    """
    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    resp = requests.get(url, params={"corpid": corpid, "corpsecret": corpsecret}, timeout=20)
    result = resp.json()
    access_token = result.get("access_token")
    if not access_token:
        raise RuntimeError(f"获取企业微信 access_token 失败: {result}")
    return access_token


def upload_video_file(access_token: str, video_path: str) -> Dict:
    """将本地 MP4 文件上传到企业微信临时素材库。

    企业微信对视频消息的限制：
        - 格式必须为 MP4；
        - 文件大小上限为 10 MB（视频消息）；
        - 临时素材 media_id 有效期 3 天。

    Args:
        access_token: 有效的企业微信调用凭证。
        video_path:   本地 MP4 文件路径。

    Returns:
        API 响应字典；成功时含 media_id，失败时含 errcode / errmsg。
        文件不存在时返回 {"errcode": -1, "errmsg": "..."} 而非抛出异常。
    """
    url = "https://qyapi.weixin.qq.com/cgi-bin/media/upload"
    path = Path(video_path)

    if not path.exists():
        return {"errcode": -1, "errmsg": f"video file not found: {video_path}"}

    with open(path, "rb") as f:
        resp = requests.post(
            url,
            params={"access_token": access_token, "type": "video"},
            files={"media": (path.name, f, "video/mp4")},
            timeout=60,     # 视频文件较大，超时设为 60s
        )

    try:
        return resp.json()
    except Exception:
        return {"errcode": -1, "errmsg": f"invalid response: {resp.text}"}


def send_message(
    data: dict,
    alarm_user: str,
    *,
    corpid: str,
    corpsecret: str,
    agentid: int,
) -> bool:
    """发送报警视频消息到企业微信。

    data 格式：
        {
            "eventType":  "phone_use",          # 报警类型
            "cameraName": "值班室双摄",          # 摄像头名称
            "video_path": "/path/to/clip.mp4",  # 本地视频路径（必填）
        }

    发送流程：
        1. 检查 video_path 是否存在；
        2. 获取 access_token；
        3. 上传视频到临时素材库，获取 media_id；
        4. 发送视频消息给 alarm_user。

    任意步骤失败均返回 False 并打印错误信息，不抛出异常，
    确保调用方（WeChatNotifier._worker）的 finally 块始终能执行回调。

    Args:
        data:       报警数据字典，格式见上。
        alarm_user: 接收人账号，多人用 '|' 分隔，"@all" 表示全体。
        corpid:     企业微信企业 ID。
        corpsecret: 自建应用 Secret。
        agentid:    自建应用 AgentID。

    Returns:
        True 表示消息发送成功；False 表示任意步骤失败。
    """
    video_path = data.get("video_path")
    if not video_path:
        print("[wechat_sender] 没有视频路径，跳过本次推送")
        return False

    # ── 1. 获取 access_token ────────────────────────────────────────────
    try:
        access_token = get_access_token(corpid, corpsecret)
    except Exception as e:
        print(f"[wechat_sender] 获取 access_token 失败: {e}")
        return False

    # ── 2. 事件类型中文映射（用于消息标题和描述）────────────────────────
    event_dict = {
        "absent":      "离岗",
        "phone_use":   "玩手机",
        "prone_sleep": "趴睡",
    }
    event_name = event_dict.get(data["eventType"], "未知事件")
    camera_name = data["cameraName"]

    # ── 3. 上传视频到临时素材库 ─────────────────────────────────────────
    video_result = upload_video_file(access_token, video_path)
    if video_result.get("errcode") != 0:
        print(f"[wechat_sender] {_describe_wechat_error('视频上传', video_result)}")
        return False

    # ── 4. 发送视频消息 ─────────────────────────────────────────────────
    video_data = {
        "touser":  alarm_user,
        "msgtype": "video",
        "agentid": agentid,
        "video": {
            "media_id":    video_result["media_id"],
            "title":       f"保安{event_name}告警",
            "description": f"{event_name} - {camera_name}",
        },
        "safe": 0,  # 0：普通消息，1：保密消息（不可转发）
    }

    try:
        resp = requests.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}",
            json=video_data,
            timeout=20,
        )
        result = resp.json()
        if result.get("errcode") != 0:
            print(f"[wechat_sender] {_describe_wechat_error('消息发送', result)}")
            return False
        return True
    except Exception as e:
        print(f"[wechat_sender] 消息发送异常: {e}")
        return False