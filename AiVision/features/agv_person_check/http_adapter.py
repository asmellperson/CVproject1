"""将内部布尔判定映射成配置协议，并执行单次 HTTP 回调。"""
import requests

from .schema import HttpConfigSchema, PersonCheckResult


class CallbackError(RuntimeError):
    """对外隐藏回调地址和请求凭据的通信错误。"""


def render_body(config: HttpConfigSchema, result: PersonCheckResult, *, camera_key: str, request_id: str):
    """递归替换模板中的完整占位符值，保留结果原本的 JSON 数据类型。"""
    variables = {
        "${result}": config.present_value if result.person_present else config.absent_value,
        "${camera_key}": camera_key,
        "${request_id}": request_id,
    }

    def render(value):
        """遍历对象和数组，仅替换与受支持占位符完全相等的字符串。"""
        if isinstance(value, dict):
            return {key: render(child) for key, child in value.items()}
        if isinstance(value, list):
            return [render(child) for child in value]
        if isinstance(value, str) and value in variables:
            return variables[value]
        return value

    return render(config.body_template)


def send_callback(config: HttpConfigSchema, body):
    """GET 和 POST 均使用配置的 JSON Body，不改写为查询参数，不自动重试。"""
    try:
        with requests.request(
            config.method, config.callback_url, headers=config.headers, json=body,
            timeout=config.timeout_seconds, allow_redirects=False, stream=True,
        ) as response:
            if not 200 <= response.status_code < 300:
                raise CallbackError(f"AGV 回调返回非成功状态 HTTP {response.status_code}")
    except requests.RequestException as exc:
        # 不携带目标 URL、Headers 或响应正文。
        raise CallbackError(f"AGV 回调通信失败：{type(exc).__name__}") from exc
