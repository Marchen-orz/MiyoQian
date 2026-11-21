# -*- coding: utf-8 -*-
"""Cookie 与账号凭证处理。"""

from __future__ import annotations

import re
from typing import Any


def cookie_value(cookie: str, names: tuple[str, ...]) -> str:
    for name in names:
        match = re.search(rf"(?:^|;\s*){re.escape(name)}=([^;]+)", cookie)
        if match:
            return match.group(1)
    return ""


def guess_uid(cookie: str) -> str:
    return cookie_value(
        cookie,
        ("account_id", "account_id_v2", "ltuid", "ltuid_v2", "login_uid", "stuid"),
    )


def guess_mid(cookie: str) -> str:
    return cookie_value(cookie, ("mid", "account_mid_v2", "ltmid_v2"))


def stoken_cookie(account: dict[str, Any]) -> str:
    uid = str(account.get("stuid") or guess_uid(account.get("cookie", "")))
    stoken = str(account.get("stoken") or "")
    mid = str(account.get("mid") or guess_mid(account.get("cookie", "")))
    if not uid or not stoken:
        raise ValueError("缺少 stuid/stoken，无法执行米游币社区任务")
    if stoken.startswith("v2_") and not mid:
        raise ValueError("v2 stoken 需要 mid，请重新扫码登录")
    items = [f"stuid={uid}", f"stoken={stoken}"]
    if mid:
        items.append(f"mid={mid}")
    return ";".join(items)


def build_cookie(uid: str, mid: str, ltoken: str, cookie_token: str) -> str:
    """国服网页 cookie，只放 V2 凭证：ltoken / cookie_token 是 stoken 换出来的 ltoken_v2 / cookie_token_v2。"""
    parts = [
        f"account_id_v2={uid}",
        f"account_mid_v2={mid}",
        f"cookie_token_v2={cookie_token}",
        f"ltmid_v2={mid}",
        f"ltoken_v2={ltoken}",
        f"ltuid_v2={uid}",
    ]
    return "; ".join(parts)
