# -*- coding: utf-8 -*-
"""配置加载与保存。"""

from __future__ import annotations

import copy
import pathlib
import random
from typing import Any

import yaml

from . import crypto
from .cookies import guess_uid
from .region import REGION_CN, REGION_OS, account_region, normalize_region

SENSITIVE_ACCOUNT_FIELDS = ("cookie", "stuid", "stoken", "mid")
SUPPORTED_CLOUD_GAME_KEYS = ("genshin", "zzz")

DEFAULT_DEVICE_PRESETS: list[dict[str, str]] = [
    {"name": "Xiaomi 14", "model": "23127PN0CC"},
    {"name": "Xiaomi 13", "model": "2211133C"},
    {"name": "Redmi K70", "model": "2311DRK48C"},
    {"name": "Redmi K60", "model": "23013RK75C"},
    {"name": "OnePlus 12", "model": "PJD110"},
    {"name": "OPPO Find X7", "model": "PHZ110"},
    {"name": "vivo X100", "model": "V2309A"},
    {"name": "HONOR 100", "model": "MAA-AN00"},
    {"name": "HUAWEI Mate 60", "model": "BRA-AL00"},
    {"name": "Samsung Galaxy S23", "model": "SM-S9110"},
]

DEFAULT_CONFIG: dict[str, Any] = {
    "enable": True,
    "accounts": [],
    "storage": {
        "data_dir": "data",
        "credentials_file": "credentials.yaml",
        "log_dir": "logs",
        "log_file": "miyouqian.log",
    },
    "device": {"id": "", "fp": "", "name": "", "model": "", "presets": DEFAULT_DEVICE_PRESETS},
    "features": {"game_checkin": True, "cloud_game_checkin": False, "bbs_tasks": False},
    "captcha": {
        "enable": False,
        "max_retries": 3,
        "channels": [
            {"provider": "damagou", "enable": False, "userkey": "", "type": "", "timeout": 60},
            {"provider": "custom", "enable": False, "url": "", "api_key": "", "timeout": 120},
        ],
    },
    "schedule": {"enable": False, "time": "09:00", "jitter_minutes": 45, "run_on_start": False},
    "games": {
        "enabled": ["genshin", "starrail", "zzz"],
        "black_list": {"genshin": [], "starrail": [], "zzz": []},
    },
    "cloud_games": {
        "enabled": ["genshin", "zzz"],
    },
    "bbs": {
        "forums": [5, 2],
        "checkin": True,
        "read": False,
        "like": False,
        "share": False,
        "cancel_like": True,
        "post_limit": 5,
        "delay_seconds": [1, 3],
    },
    "push": {
        "enable": False,
        "error_only": False,
        "channels": [],
    },
    "shop_exchange": {
        "enable": True,
        "retry_seconds": 20,
        "retry_interval": 0.4,
        "plans": [],
    },
    "web": {
        "host": "127.0.0.1",
        "port": 5890,
        "password": "",
    },
}


def load_config(path: str | pathlib.Path) -> dict[str, Any]:
    config_path = pathlib.Path(path)
    if not config_path.exists():
        config = copy.deepcopy(DEFAULT_CONFIG)
        normalize_config(config)
        return config
    with config_path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"配置文件格式错误: {config_path}")
    config = merge_dict(copy.deepcopy(DEFAULT_CONFIG), loaded)
    normalize_config(config)
    merge_credentials(config, load_credentials(config_path, config))
    normalize_config(config)
    bind_shop_plan_accounts(config)
    return config


def save_config(path: str | pathlib.Path, config: dict[str, Any]) -> None:
    normalize_config(config)
    config_path = pathlib.Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    save_credentials(credentials_path(config_path, config), config)
    public_config = strip_credentials(config)
    with config_path.open("w", encoding="utf-8", newline="\n") as file:
        yaml.safe_dump(public_config, file, allow_unicode=True, sort_keys=False)


def create_config(path: str | pathlib.Path, force: bool = False) -> pathlib.Path:
    config_path = pathlib.Path(path)
    if config_path.exists() and not force:
        raise FileExistsError(f"配置已存在: {config_path}")
    config = copy.deepcopy(DEFAULT_CONFIG)
    save_config(config_path, config)
    return config_path


def merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_dict(base[key], value)
        else:
            base[key] = value
    return base


def normalize_config(config: dict[str, Any]) -> None:
    storage = config.setdefault("storage", {})
    storage.setdefault("data_dir", "data")
    storage.setdefault("credentials_file", "credentials.yaml")
    storage.setdefault("log_dir", "logs")
    storage.setdefault("log_file", "miyouqian.log")
    cloud_games = config.setdefault("cloud_games", {})
    if not isinstance(cloud_games, dict):
        cloud_games = {}
        config["cloud_games"] = cloud_games
    cloud_games["enabled"] = normalize_cloud_game_enabled(cloud_games.get("enabled", SUPPORTED_CLOUD_GAME_KEYS))
    accounts = config.setdefault("accounts", [])
    if isinstance(accounts, dict):
        config["accounts"] = [accounts]
    for index, account in enumerate(config["accounts"], start=1):
        account["name"] = str(account.get("name") or "")[:10]
        account["region"] = normalize_region(account.get("region"))
        for field in SENSITIVE_ACCOUNT_FIELDS:
            account.setdefault(field, "")
        if account["region"] == REGION_OS and not account["stuid"] and account.get("cookie"):
            # 国际服只有 cookie 一项凭证，UID 直接从里面取，手改凭证文件时也不用另填
            account["stuid"] = guess_uid(str(account["cookie"]))
    device = config.setdefault("device", {})
    first_cookie = str(config["accounts"][0].get("cookie", "")) if config["accounts"] else ""
    presets = device.setdefault("presets", copy.deepcopy(DEFAULT_DEVICE_PRESETS))
    if not isinstance(presets, list) or not presets:
        presets = copy.deepcopy(DEFAULT_DEVICE_PRESETS)
        device["presets"] = presets
    if not device.get("name") or not device.get("model"):
        preset = random.choice([item for item in presets if isinstance(item, dict)] or DEFAULT_DEVICE_PRESETS)
        device["name"] = str(preset.get("name") or DEFAULT_DEVICE_PRESETS[0]["name"])
        device["model"] = str(preset.get("model") or DEFAULT_DEVICE_PRESETS[0]["model"])
    if not device.get("id"):
        device["id"] = crypto.device_id(first_cookie or None)
    if not device.get("fp"):
        device["fp"] = crypto.device_fp()
    captcha = config.setdefault("captcha", {})
    captcha["channels"] = normalize_captcha_channels(captcha)
    captcha["enable"] = any(channel.get("enable") for channel in captcha["channels"])
    try:
        captcha["max_retries"] = max(int(captcha.get("max_retries") or 3), 1)
    except (TypeError, ValueError):
        captcha["max_retries"] = 3
    push = config.setdefault("push", {})
    push["channels"] = normalize_push_channels(push)
    push["enable"] = any(channel.get("enable") for channel in push["channels"])
    push["error_only"] = bool(push.get("error_only", False))
    web = config.setdefault("web", {})
    web.setdefault("host", "127.0.0.1")
    web.setdefault("port", 5890)
    web.setdefault("password", "")
    features = config.setdefault("features", {})
    features.setdefault("game_checkin", True)
    features.setdefault("cloud_game_checkin", False)
    features.setdefault("bbs_tasks", False)
    bbs = config.setdefault("bbs", {})
    if not isinstance(bbs, dict):
        bbs = {}
        config["bbs"] = bbs
    bbs["checkin"] = parse_bool(bbs.get("checkin", True))
    raw_forums = bbs.get("forums")
    if isinstance(raw_forums, list):
        forums: list[int] = []
        for item in raw_forums:
            try:
                forums.append(int(item))
            except (TypeError, ValueError):
                continue
    else:
        forums = list(DEFAULT_CONFIG["bbs"]["forums"])
    bbs["forums"] = forums
    bbs["read"] = False
    bbs["like"] = False
    bbs["share"] = False
    normalize_shop_exchange(config)


def normalize_shop_exchange(config: dict[str, Any]) -> None:
    shop = config.setdefault("shop_exchange", {})
    if not isinstance(shop, dict):
        shop = {}
        config["shop_exchange"] = shop
    shop["enable"] = parse_bool(shop.get("enable", True))
    try:
        shop["retry_seconds"] = max(float(shop.get("retry_seconds", 20)), 0)
    except (TypeError, ValueError):
        shop["retry_seconds"] = 20
    try:
        shop["retry_interval"] = max(float(shop.get("retry_interval", 0.4)), 0.05)
    except (TypeError, ValueError):
        shop["retry_interval"] = 0.4
    raw_plans = shop.get("plans")
    if not isinstance(raw_plans, list):
        raw_plans = []
    plans: list[dict[str, Any]] = []
    for raw in raw_plans:
        if not isinstance(raw, dict):
            continue
        try:
            account_index = max(int(raw.get("account_index", 0)), 0)
        except (TypeError, ValueError):
            account_index = 0
        try:
            exchange_at = int(float(raw.get("exchange_at") or 0))
        except (TypeError, ValueError):
            exchange_at = 0
        plan = {
            "enable": parse_bool(raw.get("enable", True)),
            "auto": parse_bool(raw.get("auto", True)),
            "account_index": account_index,
            "account_stuid": str(raw.get("account_stuid") or "").strip(),
            "goods_id": str(raw.get("goods_id") or "").strip(),
            "goods_name": str(raw.get("goods_name") or raw.get("name") or "").strip(),
            "icon": str(raw.get("icon") or ""),
            "price": parse_int(raw.get("price"), 0),
            "stock": str(raw.get("stock") or ""),
            "type": parse_int(raw.get("type"), 0),
            "exchange_at": exchange_at,
            "game": str(raw.get("game") or ""),
            "game_biz": str(raw.get("game_biz") or ""),
            "device_fp": str(raw.get("device_fp") or ""),
            "uid": str(raw.get("uid") or "").strip(),
            "region": str(raw.get("region") or "").strip(),
            "role_name": str(raw.get("role_name") or "").strip(),
            "region_name": str(raw.get("region_name") or "").strip(),
            "address_id": str(raw.get("address_id") or "").strip(),
            "last_result": str(raw.get("last_result") or ""),
            "last_attempt_key": str(raw.get("last_attempt_key") or ""),
            "last_run": str(raw.get("last_run") or ""),
        }
        if plan["goods_id"]:
            plans.append(plan)
    shop["plans"] = plans


def normalize_cloud_game_tokens(value: Any) -> dict[str, str]:
    tokens = value if isinstance(value, dict) else {}
    return {key: str(tokens.get(key) or "") for key in SUPPORTED_CLOUD_GAME_KEYS}


def normalize_cloud_game_enabled(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = list(SUPPORTED_CLOUD_GAME_KEYS)
    enabled: list[str] = []
    for item in raw_items:
        key = str(item or "").strip()
        if key in SUPPORTED_CLOUD_GAME_KEYS and key not in enabled:
            enabled.append(key)
    return enabled


PUSH_CHANNEL_FIELDS: dict[str, tuple[str, ...]] = {
    "pushplus": ("token", "topic"),
    # Server酱³（sc3.ft07.com）：SendKey 形如 sctp1234tXXXX，uid 可留空（会从 SendKey 前缀解析）
    "serverchan": ("sendkey", "uid"),
    "qq": ("push_url", "access_token", "send_id", "msg_type"),
    # QQ 开放平台官方机器人：与上面的 onebot 版 qq 通道无关，
    # user_openid / group_openid 只能通过 Web 控制台的「绑定」按钮获取
    "qqbot": ("app_id", "client_secret", "user_openid", "group_openid", "message_format", "api_base"),
    "telegram": ("token", "chat_id", "api_url"),
    "dingrobot": ("webhook", "secret"),
    "feishubot": ("webhook", "secret"),
    "wecombot": ("webhook", "plain_text"),
    "email": ("smtp_host", "smtp_port", "smtp_user", "smtp_password", "mail_from", "mail_to", "smtp_ssl"),
    "gotify": ("server", "token", "priority"),
}

# 通道字段的默认值：取值等于默认值不算「已配置」。
# Web 控制台的 app.js 里有一份对应的 pushChannelDefaults，测试会校验两边一致。
PUSH_CHANNEL_DEFAULTS: dict[str, dict[str, Any]] = {
    "qqbot": {"message_format": "text"},
    "gotify": {"priority": 5},
}


def normalize_gotify_priority(value: Any) -> int:
    """Gotify 优先级取 0-10 的整数；空值和非数字用默认值，越界按边界算。

    不能用 `value or 默认值`：0 是合法的最低优先级，会被当成空值吞掉。
    """
    try:
        priority = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return PUSH_CHANNEL_DEFAULTS["gotify"]["priority"]
    return max(0, min(10, priority))


def normalize_push_channels(push: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = {
        "pushplus",
        "serverchan",
        "telegram",
        "dingrobot",
        "feishubot",
        "wecombot",
        "email",
        "qq",
        "qqbot",
        "gotify",
    }
    raw_channels = push.get("channels")
    if not isinstance(raw_channels, list):
        raw_channels = []

    channels: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_channels:
        if not isinstance(raw, dict):
            continue
        provider = str(raw.get("provider") or "").strip()
        if provider not in allowed or provider in seen:
            continue
        seen.add(provider)
        channel: dict[str, Any] = {
            "provider": provider,
            "enable": parse_bool(raw.get("enable", push.get("enable", False))),
        }
        defaults = PUSH_CHANNEL_DEFAULTS.get(provider, {})
        for field in PUSH_CHANNEL_FIELDS[provider]:
            if field == "smtp_port":
                channel[field] = int(raw.get(field) or 465)
            elif field == "smtp_ssl":
                channel[field] = parse_bool(raw.get(field, True))
            elif field == "plain_text":
                channel[field] = parse_bool(raw.get(field, False))
            elif field == "message_format":
                channel[field] = "markdown" if str(raw.get(field) or "").strip().lower() == "markdown" else "text"
            elif field == "priority":
                channel[field] = normalize_gotify_priority(raw.get(field))
            else:
                channel[field] = str(raw.get(field) or defaults.get(field, ""))
        if should_keep_push_channel(channel):
            channels.append(channel)
    return channels


def should_keep_push_channel(channel: dict[str, Any]) -> bool:
    if channel.get("enable"):
        return True
    provider = str(channel.get("provider") or "")
    defaults = PUSH_CHANNEL_DEFAULTS.get(provider, {})
    for field in PUSH_CHANNEL_FIELDS.get(provider, ()):
        if field == "smtp_ssl":
            continue
        if field == "plain_text":
            if channel.get(field):
                return True
            continue
        if field == "smtp_port":
            if int(channel.get(field) or 465) != 465:
                return True
            continue
        # 只有非默认取值才算「已配置」，避免默认的 message_format=text、priority=5 让空通道一直被保留
        if field in defaults:
            value = channel.get(field)
            if value not in (None, "") and str(value) != str(defaults[field]):
                return True
            continue
        if str(channel.get(field) or "").strip():
            return True
    return False


def default_captcha_channel(provider: str) -> dict[str, Any]:
    if provider == "custom":
        return {"provider": "custom", "enable": False, "url": "", "api_key": "", "timeout": 120}
    return {"provider": "damagou", "enable": False, "userkey": "", "type": "", "timeout": 60}


def normalize_captcha_channels(captcha: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = ("damagou", "custom")
    raw_channels = captcha.get("channels")
    if not isinstance(raw_channels, list):
        raw_channels = []
    if not raw_channels:
        raw_channels = [{"provider": "damagou", "enable": False}]

    channels: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_channels:
        if not isinstance(raw, dict):
            continue
        provider = str(raw.get("provider") or "").strip() or "damagou"
        if provider not in allowed or provider in seen:
            continue
        seen.add(provider)
        default_timeout = default_captcha_channel(provider)["timeout"]
        try:
            timeout = max(float(raw.get("timeout") or default_timeout), 1)
            normalized_timeout: int | float = int(timeout) if timeout.is_integer() else timeout
        except (TypeError, ValueError):
            normalized_timeout = default_timeout
        channel: dict[str, Any] = {
            "provider": provider,
            "enable": parse_bool(raw.get("enable", captcha.get("enable", False))),
        }
        if provider == "custom":
            channel["url"] = str(raw.get("url") or "").strip()
            channel["api_key"] = str(raw.get("api_key") or "").strip()
        else:
            channel["userkey"] = str(raw.get("userkey") or "")
            channel["type"] = str(raw.get("type") or "")
        channel["timeout"] = normalized_timeout
        channels.append(channel)
    for provider in allowed:
        if provider not in seen:
            channels.append(default_captcha_channel(provider))
    return channels


def parse_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def validate_unique_account_uids(config: dict[str, Any]) -> None:
    # 国服和国际服是两套账号体系，UID 只在同一服务器内要求唯一
    seen: dict[tuple[str, str], int] = {}
    for index, account in enumerate(config.get("accounts", []), start=1):
        uid = str(account.get("stuid") or "").strip()
        if not uid:
            continue
        key = (account_region(account), uid)
        if key in seen:
            raise ValueError(f"UID {uid} 已存在于账号 {seen[key]}，不能重复添加同一账号")
        seen[key] = index


def find_account_index_by_stuid(accounts: list[dict[str, Any]], stuid: str) -> int | None:
    """按 stuid 找国服账号的下标。商店兑换是国服功能，国际服账号不参与。"""
    stuid = str(stuid or "").strip()
    if not stuid:
        return None
    for index, account in enumerate(accounts):
        if account_region(account) == REGION_CN and str(account.get("stuid") or "").strip() == stuid:
            return index
    return None


def bind_shop_plan_accounts(config: dict[str, Any]) -> None:
    """让兑换计划跟着账号走，而不是跟着账号在列表里的下标走。

    计划里的 account_index 只是账号列表下标，删除或重排账号后会悄悄指向另一个账号，
    而 uid/region 仍是原账号的角色。这里按 account_stuid 重新算下标；
    还没有 account_stuid 的旧计划按当前下标补上；找不到对应账号的计划直接停用。
    stuid 存在凭证文件里，所以必须在凭证合并之后调用，否则会把所有计划都当成账号已删除。
    """
    accounts = config.get("accounts") or []
    # 没有任何账号带 stuid（凭证文件缺失或都未登录）时没有可比对的标识，保持原样
    if not any(str(account.get("stuid") or "").strip() for account in accounts):
        return
    plans = (config.get("shop_exchange") or {}).get("plans") or []
    for plan in plans:
        stuid = str(plan.get("account_stuid") or "").strip()
        if not stuid:
            index = plan.get("account_index", 0)
            if isinstance(index, int) and 0 <= index < len(accounts) and account_region(accounts[index]) == REGION_CN:
                plan["account_stuid"] = str(accounts[index].get("stuid") or "").strip()
            continue
        index = find_account_index_by_stuid(accounts, stuid)
        if index is not None:
            plan["account_index"] = index
        elif plan.get("enable", True):
            plan["enable"] = False
            plan["last_result"] = "所属账号已删除或更换，计划已停用"


def find_account(config: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    accounts = config.get("accounts") or []
    if not accounts:
        raise ValueError("配置中没有账号")
    if name is None:
        return accounts[0]
    for account in accounts:
        if account.get("name") == name:
            return account
    raise ValueError(f"未找到账号: {name}")


def upsert_account(config: dict[str, Any], name: str, data: dict[str, Any]) -> dict[str, Any]:
    accounts = config.setdefault("accounts", [])
    new_uid = str(data.get("stuid") or "").strip()
    new_region = normalize_region(data.get("region"))
    if new_uid:
        for account in accounts:
            if (
                account.get("name") != name
                and account_region(account) == new_region
                and str(account.get("stuid") or "").strip() == new_uid
            ):
                raise ValueError(f"UID {new_uid} 已存在，不能重复添加同一账号")
    for account in accounts:
        if account.get("name") == name:
            account.update(data)
            return account
    account = {"name": name, **data}
    accounts.append(account)
    return account


def load_credentials(config_path: pathlib.Path, config: dict[str, Any]) -> dict[str, Any]:
    path = credentials_path(config_path, config)
    if not path.exists():
        return {"accounts": []}
    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"凭证文件格式错误: {path}")
    loaded.setdefault("accounts", [])
    return loaded


def save_credentials(path: pathlib.Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    credentials = {
        "accounts": [
            {
                "name": str(account.get("name") or ""),
                **{field: str(account.get(field) or "") for field in SENSITIVE_ACCOUNT_FIELDS},
                "cloud_games": {
                    "tokens": normalize_cloud_game_tokens(
                        (account.get("cloud_games") or {}).get("tokens", {})
                        if isinstance(account.get("cloud_games"), dict)
                        else {}
                    )
                },
            }
            for index, account in enumerate(config.get("accounts", []), start=1)
        ]
    }
    with path.open("w", encoding="utf-8", newline="\n") as file:
        yaml.safe_dump(credentials, file, allow_unicode=True, sort_keys=False)


def merge_credentials(config: dict[str, Any], credentials: dict[str, Any]) -> None:
    if not config.get("accounts") and credentials.get("accounts"):
        config["accounts"] = [
            {"name": str(account.get("name") or "")}
            for account in credentials.get("accounts", [])
            if isinstance(account, dict)
        ]
    credential_list = [
        account
        for account in credentials.get("accounts", [])
        if isinstance(account, dict)
    ]
    credential_accounts = {
        str(account.get("name")): account
        for account in credential_list
        if account.get("name")
    }
    for index, account in enumerate(config.get("accounts", [])):
        saved = credential_accounts.get(str(account.get("name")))
        if saved is None and index < len(credential_list):
            saved = credential_list[index]
        for field in SENSITIVE_ACCOUNT_FIELDS:
            if saved and not account.get(field):
                account[field] = str(saved.get(field) or "")
            else:
                account.setdefault(field, "")
        merge_account_cloud_game_credentials(account, saved)


def strip_credentials(config: dict[str, Any]) -> dict[str, Any]:
    public_config = copy.deepcopy(config)
    for account in public_config.get("accounts", []):
        for field in SENSITIVE_ACCOUNT_FIELDS:
            account.pop(field, None)
        account.pop("cloud_games", None)
    return public_config


def merge_account_cloud_game_credentials(account: dict[str, Any], saved: dict[str, Any] | None) -> None:
    if saved and isinstance(saved.get("cloud_games"), dict):
        saved_tokens = normalize_cloud_game_tokens((saved.get("cloud_games") or {}).get("tokens", {}))
    else:
        saved_tokens = {}
    cloud_games = account.setdefault("cloud_games", {})
    if not isinstance(cloud_games, dict):
        cloud_games = {}
        account["cloud_games"] = cloud_games
    cloud_games["tokens"] = saved_tokens


def credentials_path(config_path: str | pathlib.Path, config: dict[str, Any]) -> pathlib.Path:
    storage = config.get("storage", {})
    data_dir = resolve_storage_path(config_path, str(storage.get("data_dir") or "data"))
    return data_dir / str(storage.get("credentials_file") or "credentials.yaml")


def log_path(config_path: str | pathlib.Path, config: dict[str, Any]) -> pathlib.Path:
    storage = config.get("storage", {})
    log_dir = resolve_storage_path(config_path, str(storage.get("log_dir") or "logs"))
    return log_dir / str(storage.get("log_file") or "miyouqian.log")


def resolve_storage_path(config_path: str | pathlib.Path, value: str) -> pathlib.Path:
    path = pathlib.Path(value)
    if path.is_absolute():
        return path
    return pathlib.Path(config_path).parent / path
