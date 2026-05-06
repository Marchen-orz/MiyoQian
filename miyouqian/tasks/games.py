# -*- coding: utf-8 -*-
"""国内游戏每日签到。"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

from .. import constants as c
from ..auth.login import refresh_cookie_token
from ..core import captcha, crypto
from ..core.http import ApiClient


class GameCheckin:
    def __init__(
        self,
        client: ApiClient,
        config: dict[str, Any],
        account: dict[str, Any],
        emit: Callable[[str], None] | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.account = account
        self.device = config["device"]
        self.emit = emit

    def run(self, only_games: list[str] | None = None) -> list[str]:
        enabled = self.config.get("games", {}).get("enabled", [])
        if only_games:
            enabled = [game for game in enabled if game in only_games]
        messages: list[str] = []
        success: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        for game_key in enabled:
            game = c.GAMES.get(game_key)
            if not game:
                self._add(messages, f"[跳过] 未知游戏配置: {game_key}")
                skipped.append(game_key)
                continue
            result = self._run_game(game_key, game)
            messages.extend(result["messages"])
            success.extend(result["success"])
            failed.extend(result["failed"])
            skipped.extend(result["skipped"])
            sleep_by_config(self.config)
        self._add(messages, f"游戏签到汇总：成功 {len(success)}，失败 {len(failed)}，跳过 {len(skipped)}")
        if success:
            self._add(messages, f"游戏成功项：{'; '.join(success)}")
        if failed:
            self._add(messages, f"游戏失败项：{'; '.join(failed)}")
        return messages

    def _run_game(self, game_key: str, game: dict[str, Any]) -> dict[str, list[str]]:
        name = game["name"]
        messages: list[str] = []
        success: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        self._add(messages, f"== {name} ==")
        self._add(messages, f"正在获取{name}绑定角色")
        roles = self._get_roles(game)
        if not roles:
            self._add(messages, "未找到绑定角色")
            skipped.append(f"{name}: 未找到绑定角色")
            return {"messages": messages, "success": success, "failed": failed, "skipped": skipped}
        self._add(messages, f"正在获取{name}签到奖励列表")
        awards = self._get_awards(game)
        blacklist = set(self.config.get("games", {}).get("black_list", {}).get(game_key, []))
        for role in roles:
            uid = str(role.get("game_uid") or "")
            nickname = str(role.get("nickname") or uid)
            label = f"{name} {nickname}({uid})"
            if uid in blacklist:
                self._add(messages, f"{nickname}({uid}) 在黑名单中，跳过")
                skipped.append(label)
                continue
            self._add(messages, f"正在查询{label}签到状态")
            info = self._get_info(game, role)
            if info.get("first_bind"):
                self._add(messages, f"{nickname}({uid}) 首次绑定，请先手动签到一次")
                skipped.append(label)
                continue
            signed = bool(info.get("is_sign"))
            day_index = max(int(info.get("total_sign_day") or 1) - 1, 0)
            if signed:
                reward = describe_award(awards, day_index)
                self._add(messages, f"{nickname}({uid}) 今日已签到，奖励 {reward}")
                success.append(f"{label} 已签到 {reward}")
                continue
            self._add(messages, f"正在为{label}签到")
            result = self._sign(game, role)
            if result.get("retcode") == -5003:
                reward = describe_award(awards, day_index)
                self._add(messages, f"{nickname}({uid}) 今日已签到，奖励 {reward}")
                success.append(f"{label} 已签到 {reward}")
                continue
            if result.get("retcode") != 0:
                reason = f"{result.get('message')}({result.get('retcode')})"
                self._add(messages, f"{nickname}({uid}) 签到失败: {reason}")
                failed.append(f"{label} {reason}")
                continue
            sign_data = result.get("data") or {}
            if sign_data.get("success") == 1:
                result = self._retry_captcha_sign(messages, game, role, result)
                if result.get("retcode") == -5003:
                    reward = describe_award(awards, day_index)
                    self._add(messages, f"{nickname}({uid}) 今日已签到，奖励 {reward}")
                    success.append(f"{label} 已签到 {reward}")
                    continue
                if result.get("retcode") == 0 and (result.get("data") or {}).get("success") != 1:
                    reward = describe_award(awards, day_index + 1)
                    self._add(messages, f"{nickname}({uid}) 签到成功，奖励 {reward}")
                    success.append(f"{label} {reward}")
                    continue
                if not captcha.is_enabled(self.config):
                    self._add(messages, f"{nickname}({uid}) 触发验证码，本次跳过")
                else:
                    reason = f"{result.get('message')}({result.get('retcode')})"
                    self._add(messages, f"{nickname}({uid}) 验证码处理后仍失败: {reason}")
                failed.append(f"{label} 触发验证码")
                continue
            reward = describe_award(awards, day_index + 1)
            self._add(messages, f"{nickname}({uid}) 签到成功，奖励 {reward}")
            success.append(f"{label} {reward}")
        return {"messages": messages, "success": success, "failed": failed, "skipped": skipped}

    def _add(self, messages: list[str], message: str) -> None:
        messages.append(message)
        if self.emit:
            self.emit(message)

    def _headers(self, game: dict[str, Any]) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "DS": crypto.ds(web=True),
            "x-rpc-channel": "miyousheluodi",
            "Origin": "https://act.mihoyo.com",
            "x-rpc-app_version": c.BBS_VERSION,
            "User-Agent": c.DEFAULT_MOBILE_UA,
            "x-rpc-client_type": "5",
            "Referer": "https://act.mihoyo.com/",
            "Accept-Language": "zh-CN,en-US;q=0.8",
            "X-Requested-With": "com.mihoyo.hyperion",
            "Cookie": str(self.account.get("cookie") or ""),
            "x-rpc-device_id": str(self.device["id"]),
        }
        headers.update(game.get("extra_headers") or {})
        return headers

    def _get_roles(self, game: dict[str, Any], retried: bool = False) -> list[dict[str, Any]]:
        data = self.client.get_json(
            c.ACCOUNT_ROLES_URL,
            params={"game_biz": game["game_biz"]},
            headers=self._headers(game),
        )
        if data.get("retcode") == -100 and not retried:
            if refresh_cookie_token(self.client, self.account):
                return self._get_roles(game, retried=True)
        if data.get("retcode") != 0:
            return []
        roles = data.get("data", {}).get("list", [])
        return roles if isinstance(roles, list) else []

    def _get_awards(self, game: dict[str, Any]) -> list[dict[str, Any]]:
        data = self.client.get_json(
            game["home_url"],
            params={"act_id": game["act_id"]},
            headers=self._headers(game),
        )
        if data.get("retcode") != 0:
            return []
        awards = data.get("data", {}).get("awards", [])
        return awards if isinstance(awards, list) else []

    def _get_info(self, game: dict[str, Any], role: dict[str, Any]) -> dict[str, Any]:
        data = self.client.get_json(
            game["info_url"],
            params={
                "act_id": game["act_id"],
                "region": role.get("region"),
                "uid": role.get("game_uid"),
            },
            headers=self._headers(game),
        )
        return data.get("data", {}) if data.get("retcode") == 0 else {}

    def _sign(
        self,
        game: dict[str, Any],
        role: dict[str, Any],
        solution: captcha.CaptchaSolution | None = None,
    ) -> dict[str, Any]:
        headers = self._headers(game)
        if solution:
            headers.update(
                {
                    "x-rpc-challenge": solution.challenge,
                    "x-rpc-validate": solution.validate,
                    "x-rpc-seccode": f"{solution.validate}|jordan",
                }
            )
        return self.client.post_json(
            game["sign_url"],
            json={
                "act_id": game["act_id"],
                "region": role.get("region"),
                "uid": role.get("game_uid"),
            },
            headers=headers,
        )

    def _solve_captcha(
        self,
        messages: list[str],
        sign_data: dict[str, Any],
        attempt: int,
        max_retries: int,
    ) -> captcha.CaptchaSolution | None:
        gt = str(sign_data.get("gt") or "")
        challenge = str(sign_data.get("challenge") or "")
        if not gt or not challenge:
            return None
        if not captcha.is_enabled(self.config):
            return None
        provider = captcha.active_provider_label(self.config)
        self._add(messages, f"游戏签到触发验证码，正在调用{provider}识别({attempt}/{max_retries})")
        solution = captcha.solve_game_captcha(self.client, self.config, gt, challenge, self.emit)
        if not solution:
            self._add(messages, "游戏签到验证码识别失败，准备重新获取验证码")
        return solution

    def _retry_captcha_sign(
        self,
        messages: list[str],
        game: dict[str, Any],
        role: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if not captcha.is_enabled(self.config):
            return result
        max_retries = captcha_max_retries(self.config)
        current = result
        for attempt in range(1, max_retries + 1):
            sign_data = current.get("data") or {}
            solution = self._solve_captcha(messages, sign_data, attempt, max_retries)
            if not solution:
                current = self._sign(game, role)
                continue
            self._add(messages, "游戏签到验证码已处理，正在重试签到")
            current = self._sign(game, role, solution)
            if current.get("retcode") == -5003:
                return current
            if current.get("retcode") == 0 and (current.get("data") or {}).get("success") != 1:
                return current
            if attempt < max_retries:
                self._add(messages, "游戏签到验证码提交失败，准备重新获取验证码")
                current = self._sign(game, role)
        return current


def describe_award(awards: list[dict[str, Any]], index: int) -> str:
    if not awards:
        return "未知"
    index = min(max(index, 0), len(awards) - 1)
    award = awards[index]
    return f"「{award.get('name', '未知')}」x{award.get('cnt', '?')}"


def sleep_by_config(config: dict[str, Any]) -> None:
    span = config.get("bbs", {}).get("delay_seconds", [1, 3])
    try:
        low, high = int(span[0]), int(span[1])
    except (TypeError, ValueError, IndexError):
        low, high = 1, 3
    time.sleep(random.uniform(max(low, 0), max(high, low)))


def captcha_max_retries(config: dict[str, Any]) -> int:
    try:
        return max(int(config.get("captcha", {}).get("max_retries") or 3), 1)
    except (TypeError, ValueError):
        return 3
