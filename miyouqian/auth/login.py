# -*- coding: utf-8 -*-
"""扫码登录与凭证刷新。"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import constants as c
from ..core import cookies, crypto
from ..core.http import ApiClient


class _QrRefreshed(Exception):
    pass


class AigisRequired(RuntimeError):
    def __init__(self, message: str, aigis: str) -> None:
        super().__init__(message)
        self.aigis = aigis


_RSA_MODULUS = int(
    "c3bde91d3cc1cddc06219bfbe4b494fe609afb708e4372c34aa9db31e43657d200"
    "ee585b888f377006eb6b2183cd9912751bcc9b0c817ba035b6784a66e6c31b2fd"
    "cecf44c5709dbeaae7e75a842dbaa3d17c6d3132296821c5488e743df3e94c557"
    "d5edfe19b2570a24a0e5c59401200a7f900a01ace766c5a1832dca2fb111",
    16,
)
_RSA_EXPONENT = 65537
_RSA_KEY_BYTES = 128


def passport_rsa_encrypt(text: str) -> str:
    data = text.encode("utf-8")
    if len(data) > _RSA_KEY_BYTES - 11:
        raise ValueError("待加密内容过长")
    padding_size = _RSA_KEY_BYTES - len(data) - 3
    padding = bytearray()
    while len(padding) < padding_size:
        padding.extend(byte for byte in os.urandom(padding_size - len(padding)) if byte != 0)
    block = b"\x00\x02" + bytes(padding) + b"\x00" + data
    encrypted = pow(int.from_bytes(block, "big"), _RSA_EXPONENT, _RSA_MODULUS)
    return base64.b64encode(encrypted.to_bytes(_RSA_KEY_BYTES, "big")).decode("ascii")


class PassportLogin:
    def __init__(self, client: ApiClient, device_id: str, device_fp: str) -> None:
        self.client = client
        self.device_id = device_id
        self.device_fp = device_fp

    def get_additional_tokens(self, stoken: str, mid: str) -> dict[str, str]:
        ltoken = self._get_ltoken(stoken, mid)
        cookie_token = self._get_cookie_token(stoken, mid)
        return {"ltoken": ltoken, "cookie_token": cookie_token}

    def _passport_headers(self, stoken: str, mid: str) -> dict[str, str]:
        return {
            "user-agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) miHoYoBBS/{c.BBS_VERSION}",
            "x-rpc-app_version": c.BBS_VERSION,
            "x-rpc-client_type": "5",
            "x-requested-with": "com.mihoyo.hyperion",
            "referer": "https://webstatic.mihoyo.com",
            "x-rpc-device_id": self.device_id,
            "x-rpc-device_fp": self.device_fp,
            "cookie": f"mid={mid};stoken={stoken}",
        }

    def _get_ltoken(self, stoken: str, mid: str) -> str:
        headers = self._passport_headers(stoken, mid)
        headers["ds"] = crypto.ds_x4(query=f"stoken={stoken}")
        data = self.client.get_json(
            c.LTOKEN_BY_STOKEN_URL,
            headers=headers,
            params={"stoken": stoken},
        )
        ensure_ok(data, "stoken 换 ltoken 失败")
        return str(data.get("data", {}).get("ltoken") or "")

    def _get_cookie_token(self, stoken: str, mid: str) -> str:
        headers = self._passport_headers(stoken, mid)
        headers["ds"] = crypto.ds_x4(query=f"stoken={stoken}")
        data = self.client.get_json(
            c.COOKIE_TOKEN_BY_STOKEN_URL,
            headers=headers,
            params={"stoken": stoken},
        )
        ensure_ok(data, "stoken 换 cookie_token 失败")
        return str(data.get("data", {}).get("cookie_token") or "")


class QRLogin(PassportLogin):
    def fetch(self) -> tuple[str, str]:
        body = "{}"
        data = self.client.post_json(
            c.QRCODE_FETCH_URL,
            json={},
            headers=self._headers(body),
        )
        ensure_ok(data, "生成二维码失败")
        url = str(data.get("data", {}).get("url", ""))
        ticket = str(data.get("data", {}).get("ticket", ""))
        if not url or not ticket:
            raise RuntimeError("二维码接口未返回 url/ticket")
        return url, ticket

    def wait(self, ticket: str, timeout: int = 120, cancel: threading.Event | None = None, cancel_events: list[threading.Event] | None = None) -> dict[str, str]:
        started = time.time()
        last_status = ""
        while time.time() - started < timeout:
            events = list(cancel_events or [])
            if cancel is not None:
                events.append(cancel)
            for event in events:
                if event.is_set():
                    raise _QrRefreshed()
            body = json.dumps({"ticket": ticket}, separators=(",", ":"))
            data = self.client.post_json(
                c.QRCODE_QUERY_URL,
                json={"ticket": ticket},
                headers=self._headers(body),
            )
            ensure_ok(data, "查询二维码状态失败")
            status_data = data.get("data", {})
            status = str(status_data.get("status", ""))
            if status != last_status:
                if status == "Init":
                    print("等待扫码...")
                elif status == "Scanned":
                    print("已扫码，请在米游社 APP 确认登录。")
                elif status == "Confirmed":
                    print("已确认，正在获取凭证。")
                last_status = status
            if status == "Confirmed":
                user_info = status_data.get("user_info", {})
                mid = str(user_info.get("mid") or "")
                aid = str(user_info.get("aid") or "")
                tokens = status_data.get("tokens", [])
                stoken = str(tokens[0].get("token") or "") if tokens else ""
                if not stoken or not mid or not aid:
                    raise RuntimeError("扫码结果缺少 stoken/mid/aid")
                return {"stoken": stoken, "mid": mid, "stuid": aid}
            time.sleep(2)
        raise TimeoutError("扫码登录超时")

    def _headers(self, body: str) -> dict[str, str]:
        return {
            "User-Agent": c.PASSPORT_APP_UA,
            "Accept": "*/*",
            "Accept-Language": "zh-cn",
            "x-rpc-client_type": "3",
            "x-rpc-app_version": c.PASSPORT_APP_VERSION,
            "x-rpc-device_id": self.device_id,
            "x-rpc-device_fp": self.device_fp,
            "x-rpc-game_biz": "bbs_cn",
            "x-rpc-app_id": c.QRCODE_APP_APP_ID,
            "x-rpc-sdk_version": c.PASSPORT_APP_VERSION,
            "x-rpc-account_version": c.PASSPORT_APP_VERSION,
            "x-rpc-device_model": "Mi 14",
            "x-rpc-device_name": "Mihoyo Capture",
            "DS": crypto.ds_app(body=body),
            "Content-Type": "application/json",
        }

class CaptchaLogin(PassportLogin):
    def create_captcha(self, phone: str, aigis: str = "") -> dict[str, str]:
        body = {"area_code": passport_rsa_encrypt("+86"), "mobile": passport_rsa_encrypt(phone)}
        data, headers = self.client.post_json_with_headers(
            c.LOGIN_CAPTCHA_URL,
            json=body,
            headers=self._captcha_headers(aigis, create=True),
        )
        ensure_ok_or_aigis(data, headers, "发送短信验证码失败")
        payload = data.get("data", {})
        action_type = str(payload.get("action_type") or "")
        if not action_type:
            raise RuntimeError("发送短信验证码失败: 接口未返回 action_type")
        return {
            "action_type": action_type,
            "countdown": str(payload.get("countdown") or ""),
            "sent_new": str(payload.get("sent_new") or ""),
        }

    def login_by_mobile_captcha(
        self, phone: str, captcha: str, action_type: str, aigis: str = ""
    ) -> dict[str, str]:
        body = {
            "area_code": passport_rsa_encrypt("+86"),
            "mobile": passport_rsa_encrypt(phone),
            "action_type": action_type,
            "captcha": captcha,
        }
        data, headers = self.client.post_json_with_headers(
            c.LOGIN_BY_MOBILE_CAPTCHA_URL,
            json=body,
            headers=self._captcha_headers(aigis, create=False),
        )
        ensure_ok_or_aigis(data, headers, "短信验证码登录失败")
        payload = data.get("data", {})
        user_info = payload.get("user_info") or {}
        token = payload.get("token") or {}
        stoken = str(token.get("token") or "")
        mid = str(user_info.get("mid") or "")
        aid = str(user_info.get("aid") or "")
        if not stoken or not mid or not aid:
            raise RuntimeError("短信验证码登录结果缺少 stoken/mid/aid")
        return {"stoken": stoken, "mid": mid, "stuid": aid}

    def _captcha_headers(self, aigis: str, create: bool) -> dict[str, str]:
        headers = {
            "x-rpc-aigis": aigis or "",
            "x-rpc-app_version": c.BBS_VERSION,
            "x-rpc-client_type": "2",
            "x-rpc-app_id": c.PASSPORT_APP_ID,
            "x-rpc-device_fp": self.device_fp,
            "x-rpc-device_name": "Mihoyo Capture",
            "x-rpc-device_id": self.device_id,
            "x-rpc-device_model": "Mi 14",
            "user-agent": f"Mozilla/5.0 (Linux; Android 12) Mobile miHoYoBBS/{c.BBS_VERSION}",
            "content-type": "application/json",
        }
        if create:
            headers.update(
                {
                    "referer": "https://user.miyoushe.com/",
                    "x-rpc-game_biz": "hk4e_cn",
                }
            )
        return headers

def print_qrcode(text: str, image_path: pathlib.Path | None = None) -> None:
    import qrcode

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(text)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    if image_path:
        qrcode.make(text).save(image_path)


def refresh_cookie_token(client: ApiClient, account: dict[str, Any]) -> bool:
    try:
        data = client.get_json(
            c.COOKIE_TOKEN_REFRESH_URL,
            headers={"cookie": cookies.stoken_cookie(account), "user-agent": c.DEFAULT_MOBILE_UA},
        )
        ensure_ok(data, "刷新 cookie_token 失败")
    except Exception:
        return False
    token = str(data.get("data", {}).get("cookie_token") or "")
    if not token:
        return False
    account["cookie"] = cookies.replace_or_append_cookie_value(
        str(account.get("cookie") or ""), "cookie_token", token
    )
    return True


def ensure_ok(data: dict[str, Any], message: str) -> None:
    if data.get("retcode") != 0:
        raise RuntimeError(f"{message}: retcode={data.get('retcode')} message={data.get('message')}")


def ensure_ok_or_aigis(data: dict[str, Any], headers: Any, message: str) -> None:
    if data.get("retcode") == 0:
        return
    aigis = ""
    if headers is not None:
        aigis = str(headers.get("x-rpc-aigis") or "")
    if aigis:
        raise AigisRequired(
            f"{message}: 接口要求完成官方人机验证(AIGIS)；"
            f"retcode={data.get('retcode')} message={data.get('message')}",
            aigis,
        )
    ensure_ok(data, message)
