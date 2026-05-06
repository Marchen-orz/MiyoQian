# -*- coding: utf-8 -*-
"""配置加载与保存。"""

from __future__ import annotations

import copy
import pathlib
import random
from typing import Any

import yaml

from . import crypto

SENSITIVE_ACCOUNT_FIELDS = ("cookie", "stuid", "stoken", "mid")

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
    "features": {"game_checkin": True, "bbs_tasks": False},
    "captcha": {
        "enable": False,
        "max_retries": 3,
        "channels": [{"provider": "damagou", "enable": False, "userkey": "", "type": "", "timeout": 60}],
    },
    "schedule": {"enable": False, "time": "09:00", "jitter_minutes": 45, "run_on_start": False},
    "games": {
        "enabled": ["genshin", "starrail", "zzz"],
        "black_list": {"genshin": [], "starrail": [], "zzz": []},
    },
    "bbs": {
        "forums": [5, 2],
        "checkin": True,
        "read": True,
        "like": True,
        "share": True,
        "cancel_like": True,
        "post_limit": 5,
        "delay_seconds": [1, 3],
    },
    "push": {
        "enable": False,
        "error_only": False,
        "channels": [],
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
    accounts = config.setdefault("accounts", [])
    if isinstance(accounts, dict):
        config["accounts"] = [accounts]
    for index, account in enumerate(config["accounts"], start=1):
        account["name"] = str(account.get("name") or "")[:10]
        for field in SENSITIVE_ACCOUNT_FIELDS:
            account.setdefault(field, "")
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


PUSH_CHANNEL_FIELDS: dict[str, tuple[str, ...]] = {
    "pushplus": ("token", "topic", "api_url"),
    "telegram": ("token", "chat_id", "api_url"),
    "dingrobot": ("webhook", "secret"),
    "feishubot": ("webhook",),
    "email": ("smtp_host", "smtp_port", "smtp_user", "smtp_password", "mail_from", "mail_to", "smtp_ssl"),
}

def normalize_push_channels(push: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = {"pushplus", "telegram", "dingrobot", "feishubot", "email"}
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
        for field in PUSH_CHANNEL_FIELDS[provider]:
            if field == "smtp_port":
                channel[field] = int(raw.get(field) or 465)
            elif field == "smtp_ssl":
                channel[field] = parse_bool(raw.get(field, True))
            else:
                channel[field] = str(raw.get(field) or "")
        if should_keep_push_channel(channel):
            channels.append(channel)
    return channels


def should_keep_push_channel(channel: dict[str, Any]) -> bool:
    if channel.get("enable"):
        return True
    provider = str(channel.get("provider") or "")
    for field in PUSH_CHANNEL_FIELDS.get(provider, ()):
        if field == "smtp_ssl":
            continue
        if field == "smtp_port":
            if int(channel.get(field) or 465) != 465:
                return True
            continue
        if str(channel.get(field) or "").strip():
            return True
    return False


def normalize_captcha_channels(captcha: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = {"damagou"}
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
        try:
            timeout = max(float(raw.get("timeout") or 60), 1)
            normalized_timeout: int | float = int(timeout) if timeout.is_integer() else timeout
        except (TypeError, ValueError):
            normalized_timeout = 60
        channels.append(
            {
                "provider": provider,
                "enable": parse_bool(raw.get("enable", captcha.get("enable", False))),
                "userkey": str(raw.get("userkey") or ""),
                "type": str(raw.get("type") or ""),
                "timeout": normalized_timeout,
            }
        )
    if not any(channel["provider"] == "damagou" for channel in channels):
        channels.append({"provider": "damagou", "enable": False, "userkey": "", "type": "", "timeout": 60})
    return channels


def parse_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def validate_unique_account_uids(config: dict[str, Any]) -> None:
    seen: dict[str, int] = {}
    for index, account in enumerate(config.get("accounts", []), start=1):
        uid = str(account.get("stuid") or "").strip()
        if not uid:
            continue
        if uid in seen:
            raise ValueError(f"UID {uid} 已存在于账号 {seen[uid]}，不能重复添加同一账号")
        seen[uid] = index


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
    if new_uid:
        for account in accounts:
            if account.get("name") != name and str(account.get("stuid") or "").strip() == new_uid:
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


def strip_credentials(config: dict[str, Any]) -> dict[str, Any]:
    public_config = copy.deepcopy(config)
    for account in public_config.get("accounts", []):
        for field in SENSITIVE_ACCOUNT_FIELDS:
            account.pop(field, None)
    return public_config


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
