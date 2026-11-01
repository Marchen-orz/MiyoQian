from typing import Any, Dict, Optional

from ..core.http import ApiClient

# 未配置协议时沿用原来的 OneBot v11 行为（Napcat 也是这一套）
DEFAULT_PROTOCOL = "nap"


class OneBotHTTP:
    def __init__(
        self,
        base_url: str = "",
        access_token: Optional[str] = None,
        protocol: str = DEFAULT_PROTOCOL,
    ):
        """
        :param base_url: OneBot 服务端地址，默认为 http://127.0.0.1:5700
        :param access_token: 如果配置了鉴权 token，请传入
        :param protocol: 对接的 OneBot 实现，nap = Napcat，sl = SnowLuma
        """
        self.client = ApiClient()
        self.base_url = base_url.rstrip("/")
        self.protocol = (protocol or DEFAULT_PROTOCOL).strip().lower()
        self.headers = {"Content-Type": "application/json"}
        if access_token:
            self.headers["Authorization"] = f"Bearer {access_token}"

    def _call_api(
        self, action: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        调用 OneBot API 的通用方法
        :param action: API 名称，如 'send_private_msg'
        :param params: 参数字典，作为 JSON 请求体发送
        :return: 解析后的 JSON 响应
        """
        url = f"{self.base_url}/{action}"
        resp = self.client.post_json(
            url=url,
            headers=self.headers,
            json=params or {},
        )
        if resp.get("status") == "failed":
            detail = (
                resp.get("wording")
                or resp.get("message")
                or resp.get("msg")
                or resp.get("retcode")
                or "unknown error"
            )
            raise Exception(f"API call failed: {detail} (retcode={resp.get('retcode')})")
        return resp

    def send_msg(
        self,
        message_type: str,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None,
        message: str = "",
        auto_escape: bool = True,
    ) -> Dict[str, Any]:
        """通用发送消息（message_type='private' 或 'group'）"""
        if message_type not in ("private", "group"):
            raise ValueError("message_type must be 'private' or 'group'")

        if self.protocol == "sl":
            # SnowLuma：私聊/群聊分别调用不同 action，参数仍是 OneBot v11 标准
            action = "send_private_msg" if message_type == "private" else "send_group_msg"

            params: Dict[str, Any] = {
                "message": message,
                "auto_escape": auto_escape,
            }
        else:
            # Napcat 以及未配置协议时：走标准 send_msg
            action = "send_msg"
            params = {
                "message_type": message_type,
                "message": message,
                "auto_escape": auto_escape,
            }

        if message_type == "private":
            params["user_id"] = user_id
        else:
            params["group_id"] = group_id

        return self._call_api(action, params)
