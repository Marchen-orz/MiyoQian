# -*- coding: utf-8 -*-
"""米游社请求签名工具。"""

from __future__ import annotations

import hashlib
import json
import random
import string
import time
from typing import Any

from .. import constants as c


def md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def random_text(length: int) -> str:
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))


def ds(web: bool = False) -> str:
    salt = c.BBS_WEB_SALT if web else c.BBS_SALT
    t = str(int(time.time()))
    r = random_text(6)
    sign = md5(f"salt={salt}&t={t}&r={r}")
    return f"{t},{r},{sign}"


def ds_x6(query: str = "", body: str = "") -> str:
    t = str(int(time.time()))
    r = str(random.randint(100001, 200000))
    sign = md5(f"salt={c.BBS_X6_SALT}&t={t}&r={r}&b={body}&q={query}")
    return f"{t},{r},{sign}"


def ds_x4(query: str = "", body: str = "") -> str:
    t = str(int(time.time()))
    r = str(random.randint(100000, 200000))
    sign = md5(f"salt={c.PASSPORT_X4_SALT}&t={t}&r={r}&b={body}&q={query}")
    return f"{t},{r},{sign}"


def ds_app(body: str = "", query: str = "") -> str:
    t = str(int(time.time()))
    r = str(random.randint(100001, 200000))
    b = body if body else ""
    q = query if query else ""
    sign = md5(f"salt={c.PASSPORT_APP_SALT}&t={t}&r={r}&b={b}&q={q}")
    return f"{t},{r},{sign}"
