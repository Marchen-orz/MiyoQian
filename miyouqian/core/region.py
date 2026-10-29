# -*- coding: utf-8 -*-
"""账号所属服务器（国服 / 国际服）。

账号列表和大部分配置是共用的，只有这个字段决定执行时走哪一套实现。
"""

from __future__ import annotations

from typing import Any

REGION_CN = "cn"
REGION_OS = "os"
REGIONS = (REGION_CN, REGION_OS)


def normalize_region(value: Any) -> str:
    """未知或缺失的取值一律按国服处理，旧配置不需要迁移。"""
    return REGION_OS if str(value or "").strip().lower() == REGION_OS else REGION_CN


def account_region(account: dict[str, Any]) -> str:
    return normalize_region(account.get("region"))
