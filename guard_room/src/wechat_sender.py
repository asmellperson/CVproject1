# wechat_sender.py
from __future__ import annotations

import base64
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional

import requests


WECHAT_IP_DENIED_ERRCODE = 60020


def _extract_wechat_from_ip(errmsg: str) -> Optional[str]:
    match = re.search(r"from ip:\s*([^,\s]+)", errmsg or "")
    return match.group(1) if match else None


def _describe_wechat_error(action: str, result: Dict) -> str:
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


class Base64WeChatUploader:
    """Base64 图片上传到企业微信素材库"""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = "https://qyapi.weixin.qq.com/cgi-bin/media/upload"

    def extract_base64_data(self, base64_string: str) -> tuple[str, str, str]:
        """
        返回:
            pure_base64, image_format, mime_type
        """
        header_pattern = r"data:(image/([^;]+));base64,"
        match = re.match(header_pattern, base64_string)

        if match:
            mime_type = match.group(1)
            image_format = match.group(2)
            pure_base64 = base64_string.split(",", 1)[1]
            return pure_base64, image_format, mime_type

        pure_base64 = base64_string
        if base64_string.startswith("/9j"):
            return pure_base64, "jpeg", "image/jpeg"
        if base64_string.startswith("iVBOR"):
            return pure_base64, "png", "image/png"
        if base64_string.startswith("R0lGOD"):
            return pure_base64, "gif", "image/gif"
        return pure_base64, "jpeg", "image/jpeg"

    def upload_base64_image(self, base64_data: str, filename: Optional[str] = None) -> Dict:
        try:
            pure_base64, image_format, mime_type = self.extract_base64_data(base64_data)
            image_binary = base64.b64decode(pure_base64)

            if filename is None:
                filename = f"alarm_{int(time.time())}.{image_format}"

            params = {
                "access_token": self.access_token,
                "type": "image",
            }
            files = {
                "media": (filename, BytesIO(image_binary), mime_type)
            }

            response = requests.post(
                self.base_url,
                params=params,
                files=files,
                timeout=30,
            )
            return self._handle_response(response)

        except Exception as e:
            return {"errcode": -1, "errmsg": f"upload_base64_image failed: {e}"}

    @staticmethod
    def _handle_response(response: requests.Response) -> Dict:
        try:
            return response.json()
        except Exception:
            return {"errcode": -1, "errmsg": f"invalid response: {response.text}"}


def get_access_token(corpid: str, corpsecret: str) -> str:
    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    resp = requests.get(
        url,
        params={"corpid": corpid, "corpsecret": corpsecret},
        timeout=20,
    )
    result = resp.json()
    access_token = result.get("access_token")
    if not access_token:
        raise RuntimeError(f"获取企业微信 access_token 失败: {result}")
    return access_token


def upload_video_file(access_token: str, video_path: str) -> Dict:
    """
    上传 mp4 视频到企业微信素材库
    注意企业微信视频消息通常要求 mp4，且大小受限
    """
    url = "https://qyapi.weixin.qq.com/cgi-bin/media/upload"
    path = Path(video_path)

    if not path.exists():
        return {"errcode": -1, "errmsg": f"video file not found: {video_path}"}

    with open(path, "rb") as f:
        files = {
            "media": (path.name, f, "video/mp4")
        }
        params = {
            "access_token": access_token,
            "type": "video",
        }
        resp = requests.post(url, params=params, files=files, timeout=60)

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
) -> None:
    """
    data 约定格式：
    {
        "eventType": "phone_use",
        "img_base64": "...",
        "cameraName": "值班室双摄",
        "video_path": "/xx/xx.mp4"   
    }
    """
    video_path = data.get("video_path")
    if not video_path:
        print("[wechat_sender] 没有视频路径,跳过本次推送")
        return False
    try:
        access_token = get_access_token(corpid, corpsecret)
    except Exception as e:
        print(f"[wechat_sender] 获取 access_token 失败: {e}")
        return False

    # uploader = Base64WeChatUploader(access_token)
    # image_result = uploader.upload_base64_image(data["img_base64"])
    # if image_result.get("errcode") != 0:
    #     raise RuntimeError(f"图片上传失败: {image_result}")

    # image_media_id = image_result["media_id"]

    event_dict = {
        "absent": "离岗",
        "phone_use": "玩手机",
        "prone_sleep": "趴睡",
        # "blocks": "越界检测",
        # "detect_face": "逗留检测",
        # "detect_phone": "手机检测",
        # "detect_door": "大门未关",
        # "detect_human": "人体逗留检测",
    }

    event_name = event_dict.get(data["eventType"], "未知事件")
    camera_name = data["cameraName"]

#    =================发送 markdown 文字 =============
#     markdown_data = {
#         "touser": alarm_user,
#         "msgtype": "markdown",
#         "agentid": agentid,
#         "markdown": {
#             "content": f"""检测到异常行为，请注意查看！

# **事件名称**：{event_name}
# **摄像头名称**：{camera_name}
# """
#         },
#         "safe": 0,
#     }

#     requests.post(
#         f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}",
#         json=markdown_data,
#         timeout=20,
#     )
 

    #  =============发送图片==============
    # image_data = {
    #     "touser": alarm_user,
    #     "msgtype": "image",
    #     "agentid": agentid,
    #     "image": {
    #         "media_id": image_media_id
    #     },
    #     "safe": 0,
    # }

    # requests.post(
    #     f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}",
    #     json=image_data,
    #     timeout=20,
    # )
    video_result = upload_video_file(access_token, video_path)
    if video_result.get("errcode") != 0:
        print(f"[wechat_sender] {_describe_wechat_error('视频上传', video_result)}")
        return False  # ← 返回 False
    video_data = {
        "touser": alarm_user,
        "msgtype": "video",
        "agentid": agentid,
        "video": {
            "media_id": video_result["media_id"],
            "title": f"保安{event_name}告警",
            "description": f"{event_name} - {camera_name}",
        },
        "safe": 0,
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
