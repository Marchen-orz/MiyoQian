from typing import Optional, Dict, Any
from ..core.http import ApiClient

class OneBotHTTP:
    def __init__(self, base_url: str = "", access_token: Optional[str] = None):
        """
        :param base_url: OneBot 服务端地址，默认为 http://127.0.0.1:5700
        :param access_token: 如果配置了鉴权 token，请传入
        """
        self.client = ApiClient()
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'Content-Type': 'application/json',
        }
        if access_token:
            self.headers['Authorization'] = f'Bearer {access_token}'

    def _call_api(self, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        调用 OneBot API 的通用方法
        :param action: API 名称，如 'send_private_msg'
        :param params: 参数字典
        :return: 解析后的 JSON 响应
        """
        url = f"{self.base_url}/{action}"
        resp = self.client.post_json(
            url = url,
            headers = self.headers,
            params = params
        )
        if resp.get('status') == 'failed':
            raise Exception(f"API call failed: {resp.get('msg', resp.get('retcode', 'unknown error'))}")
        return resp

    def send_msg(self, message_type: str, user_id: Optional[int] = None, group_id: Optional[int] = None, message: str = '', auto_escape: bool = False) -> Dict[str, Any]:
        """通用发送消息（type='private' 或 'group'）"""
        params = {
            'message_type': message_type,
            'message': message,
            'auto_escape': auto_escape
        }
        if message_type == 'private':
            params['user_id'] = user_id
        elif message_type == 'group':
            params['group_id'] = group_id
        else:
            raise ValueError("message_type must be 'private' or 'group'")
        return self._call_api('send_msg', params)
