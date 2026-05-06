# -*- coding: utf-8 -*-
"""验证码识别渠道。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .http import ApiClient

DAMAGOU_URL = "http://api.damagou.top/apiv1/jiyanRecognize.html"
PROVIDER_LABELS = {
    "damagou": "打码狗",
}


@dataclass(frozen=True)
class CaptchaSolution:
    validate: str
    challenge: str


def is_enabled(config: dict[str, Any]) -> bool:
    return _active_channel(config) is not None


def active_provider_label(config: dict[str, Any]) -> str:
    channel = _active_channel(config)
    if not channel:
        return "验证码渠道"
    provider = str(channel.get("provider") or "")
    return PROVIDER_LABELS.get(provider, provider or "验证码渠道")


def solve_game_captcha(
    client: ApiClient,
    config: dict[str, Any],
    gt: str,
    challenge: str,
    emit: Callable[[str], None] | None = None,
) -> CaptchaSolution | None:
    return _solve(client, config, gt, challenge, None, emit)


def solve_bbs_captcha(
    client: ApiClient,
    config: dict[str, Any],
    gt: str,
    challenge: str,
    geetest_success: int | None = None,
    emit: Callable[[str], None] | None = None,
) -> CaptchaSolution | None:
    return _solve(client, config, gt, challenge, geetest_success, emit)


def _solve(
    client: ApiClient,
    config: dict[str, Any],
    gt: str,
    challenge: str,
    geetest_success: int | None,
    emit: Callable[[str], None] | None,
) -> CaptchaSolution | None:
    channel = _active_channel(config)
    if not channel:
        return None
    try:
        params: dict[str, Any] = {
            "userkey": str(channel.get("userkey") or "").strip(),
            "gt": gt,
            "challenge": challenge,
            "isJson": "2",
        }
        captcha_type = str(channel.get("type") or "").strip()
        if captcha_type:
            params["type"] = captcha_type
        if geetest_success == 0:
            params["success"] = 0
        data = client.get_json(DAMAGOU_URL, params=params, timeout=float(channel.get("timeout") or 60))
        solution = _parse_damagou_response(data)
        if not solution and emit:
            emit(f"{active_provider_label(config)}验证码识别失败: {data.get('msg') or '未知错误'}")
        return solution
    except Exception as exc:
        if emit:
            emit(f"{active_provider_label(config)}验证码识别失败: {exc}")
        return None


def _active_channel(config: dict[str, Any]) -> dict[str, Any] | None:
    captcha_config = config.get("captcha", {})
    if not captcha_config.get("enable"):
        return None
    channels = captcha_config.get("channels") or []
    if not isinstance(channels, list):
        return None
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        if (
            str(channel.get("provider") or "") == "damagou"
            and channel.get("enable")
            and str(channel.get("userkey") or "").strip()
        ):
            return channel
    return None


def _parse_damagou_response(data: dict[str, Any]) -> CaptchaSolution | None:
    if str(data.get("status")) != "0":
        return None
    raw = str(data.get("data") or "")
    if "|" not in raw:
        return None
    challenge, validate = raw.split("|", 1)
    challenge = challenge.strip()
    validate = validate.strip()
    if not challenge or not validate:
        return None
    return CaptchaSolution(validate=validate, challenge=challenge)
