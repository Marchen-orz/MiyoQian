# -*- coding: utf-8 -*-
"""米游社用户资料，目前只取头像。"""

from __future__ import annotations

from urllib.parse import urlparse

from .. import constants as c
from .http import ApiClient, ApiError

# 头像地址来自远程接口，只放行米哈游自家的 https 图片域名，别让页面去加载任意地址
AVATAR_HOST_SUFFIXES = (".miyoushe.com", ".mihoyo.com", ".hoyolab.com")


def safe_avatar_url(url: object) -> str:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host.endswith(AVATAR_HOST_SUFFIXES):
        return ""
    return parsed.geturl()


def fetch_avatar_url(client: ApiClient, uid: str) -> str:
    """按米游社 UID 取头像地址。这是公开资料接口，不需要账号凭证。"""
    data = client.get_json(
        c.BBS_USER_INFO_URL,
        params={"uid": uid, "gids": 2},
        headers={"User-Agent": c.DEFAULT_MOBILE_UA, "Referer": "https://www.miyoushe.com/"},
    )
    if data.get("retcode") != 0:
        raise ApiError(f"米游社用户资料获取失败: {data.get('message') or data.get('retcode')}")
    user_info = (data.get("data") or {}).get("user_info") or {}
    return safe_avatar_url(user_info.get("avatar_url"))


def fetch_os_avatar_url(client: ApiClient, uid: str) -> str:
    """按 HoYoLAB UID 取头像地址。同样是公开资料接口，不需要账号凭证。"""
    data = client.get_json(
        c.OS_USER_INFO_URL,
        params={"uid": uid},
        headers={"User-Agent": c.OS_USER_AGENT, "Referer": "https://www.hoyolab.com/"},
    )
    if data.get("retcode") != 0:
        raise ApiError(f"HoYoLAB 用户资料获取失败: {data.get('message') or data.get('retcode')}")
    user_info = (data.get("data") or {}).get("user_info") or {}
    return safe_avatar_url(user_info.get("avatar_url"))
