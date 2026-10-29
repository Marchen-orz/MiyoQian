# -*- coding: utf-8 -*-
"""HoYoLAB cookie 解析。国际服没有扫码 / 验证码登录，凭证由用户从浏览器里复制。

用户拿到 cookie 的方式五花八门：整行 ``Cookie:`` 请求头、开发者工具里 Ctrl+C 的
cookie 表格（制表符分隔）、浏览器扩展导出的 JSON、或者自己手拼的 ``name=value``。
这里统一整理成 ``name=value; name=value``，再检查关键字段。
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..core.cookies import cookie_value, guess_uid
from ..core.region import REGION_OS

TOKEN_FIELDS = ("ltoken_v2", "ltoken", "cookie_token_v2", "cookie_token")

# cookie 名只能是 token，遇到 Host / Accept 这类请求头行就丢掉
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+$")
# 整段请求头里只认 Cookie 那一行，值一直到行尾
HEADER_PATTERN = re.compile(r"^\s*cookie\s*[:：]\s*(.+)$", re.IGNORECASE | re.MULTILINE)
QUOTED_PATTERN = re.compile(r'^"(.*)"$')
# 从 Set-Cookie 里粘过来时，这些属性不是 cookie，发出去只会多几个奇怪的字段
ATTRIBUTES = frozenset(
    {"path", "domain", "expires", "max-age", "secure", "httponly", "samesite", "priority", "partitioned"}
)


def parse_hoyolab_cookie(raw: str) -> dict[str, str]:
    """整理用户粘贴的 cookie，返回可直接并入账号的字段；缺少关键字段时抛 ValueError。

    只做本地检查：真正是否有效要到签到时才知道，那时接口会返回 -100。
    """
    cookie = "; ".join(f"{name}={value}" for name, value in cookie_pairs(raw).items())
    if not cookie:
        if not str(raw or "").strip():
            raise ValueError("请粘贴 HoYoLAB 的 cookie")
        raise ValueError("没有识别到 cookie 内容，请确认复制的是 hoyolab.com 的 cookie")
    uid = guess_uid(cookie)
    if not uid:
        raise ValueError("cookie 里没有找到 ltuid_v2，请确认复制的是 hoyolab.com 的 cookie")
    if not cookie_value(cookie, TOKEN_FIELDS):
        raise ValueError("cookie 里没有找到 ltoken_v2，请确认复制的是 hoyolab.com 的 cookie")
    return {"cookie": cookie, "stuid": uid, "stoken": "", "mid": "", "region": REGION_OS}


def cookie_pairs(raw: str) -> dict[str, str]:
    """把各种粘贴格式解析成 {name: value}，同名以最后一次为准，保持出现顺序。"""
    text = str(raw or "").strip()
    if not text:
        return {}
    pairs = _from_json(text)
    if pairs is None:
        pairs = _from_text(text)
    return pairs


def _from_json(text: str) -> dict[str, str] | None:
    """浏览器扩展常见的 [{name, value}] 或 {"name": "value"}；不是 JSON 就返回 None。"""
    if text[0] not in "[{":
        return None
    try:
        data: Any = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict):
        data = [data] if "name" in data else [{"name": key, "value": value} for key, value in data.items()]
    if not isinstance(data, list):
        return None
    pairs: dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        _put(pairs, str(item.get("name") or ""), str(item.get("value") or ""))
    return pairs


def _from_text(text: str) -> dict[str, str]:
    header = HEADER_PATTERN.search(text)
    if header:
        text = header.group(1)
    pairs: dict[str, str] = {}
    for line in re.split(r"[;\r\n]+", text):
        row = line.strip()
        if not row:
            continue
        cells = row.split("\t")
        # 开发者工具里框选 cookie 表格复制出来是「名称\t值\t域\t路径…」
        pair = f"{cells[0].strip()}={cells[1].strip()}" if len(cells) > 1 else row
        name, sep, value = pair.partition("=")
        if sep:
            _put(pairs, name.strip(), value.strip())
    return pairs


def _put(pairs: dict[str, str], name: str, value: str) -> None:
    value = QUOTED_PATTERN.sub(r"\1", value.strip()).strip()
    if not value or name.lower() in ATTRIBUTES or not NAME_PATTERN.match(name):
        return
    pairs[name] = value
