# -*- coding: utf-8 -*-
"""国际服（HoYoLAB）游戏签到。

和国服的差别：签到按 HoYoLAB 账号计算，没有角色列表，也没有逐角色黑名单；
只需要 cookie，不需要 DS 签名。输出格式与国服保持一致，推送和界面按同样的前缀解析。
接口按 genshin.py 整理，尚未用真实账号验证。
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

from .. import constants as c
from ..core.http import ApiClient

ALREADY_SIGNED_RETCODE = -5003
INVALID_COOKIE_RETCODES = (-100, 10001, 10103)
NO_GAME_ACCOUNT_RETCODES = (-1073, -10002)


class HoyolabCheckin:
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
        self.emit = emit
        self.cookie_invalid = False

    def probe(self, game_key: str = "genshin") -> str:
        """只读地确认 cookie 还能不能用，返回 ok / invalid / unbound / unknown。

        只发一次 info 请求，不签到；网络异常一律算 unknown，不能因为一次超时就拒绝保存。
        """
        game = c.OS_GAMES.get(game_key) or next(iter(c.OS_GAMES.values()))
        try:
            result = self._call(game, "info")
        except Exception:
            return "unknown"
        code = result.get("retcode")
        if code == 0:
            return "ok"
        if code in INVALID_COOKIE_RETCODES:
            return "invalid"
        if code in NO_GAME_ACCOUNT_RETCODES:
            # cookie 是好的，只是这个号没绑该游戏
            return "unbound"
        return "unknown"

    def run(self, only_games: list[str] | None = None) -> list[str]:
        enabled = list(self.config.get("games", {}).get("enabled", []))
        if only_games:
            enabled = [game for game in enabled if game in only_games]
        messages: list[str] = []
        success: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        if not str(self.account.get("cookie") or "").strip():
            self._add(messages, "国际服账号还没有登录")
            failed.append("国际服账号未登录，请先粘贴 HoYoLAB cookie")
            enabled = []
        for game_key in enabled:
            game = c.OS_GAMES.get(game_key)
            if not game:
                name = c.GAMES.get(game_key, {}).get("name", game_key)
                self._add(messages, f"[跳过] {name} 国际服没有签到活动")
                skipped.append(f"{name}: 国际服没有签到活动")
                continue
            label = f"{game['name']}(国际服)"
            self._add(messages, f"== {label} ==")
            try:
                kind, detail = self._check_in(game, label, messages)
            except Exception as exc:
                # 单个游戏的网络异常只记为该游戏失败，不连累后面的游戏
                self._add(messages, f"{label} 签到失败: 请求异常: {exc}")
                kind, detail = "failed", f"请求异常: {exc}"
            {"success": success, "failed": failed, "skipped": skipped}[kind].append(f"{label} {detail}")
            if self.cookie_invalid:
                # cookie 失效对所有游戏都一样，没必要逐个再试
                self._add(messages, "cookie 已失效，其余游戏不再尝试")
                break
            self._pause()
        self._add(messages, f"游戏社区签到汇总：成功 {len(success)}，失败 {len(failed)}，跳过 {len(skipped)}")
        if success:
            self._add(messages, f"游戏社区成功项：{'; '.join(success)}")
        if failed:
            self._add(messages, f"游戏社区失败项：{'; '.join(failed)}")
        return messages

    def _check_in(self, game: dict[str, Any], label: str, messages: list[str]) -> tuple[str, str]:
        """签一个游戏，返回 (success|failed|skipped, 说明)。网络异常交给调用方统一处理。"""
        self._add(messages, f"正在查询{label}签到状态")
        result = self._call(game, "info")
        problem = self._problem(result)
        if problem:
            return self._report(messages, label, *problem)
        info = result.get("data") or {}
        if info.get("first_bind"):
            self._add(messages, f"{label} 首次绑定，请先手动签到一次")
            return "skipped", "首次绑定，请先手动签到一次"
        awards = self._awards(game)
        total = to_int(info.get("total_sign_day"))
        if info.get("is_sign"):
            reward = describe_award(awards, total - 1)
            self._add(messages, f"{label} 今日已签到，奖励 {reward}")
            return "success", f"已签到 {reward}"
        self._add(messages, f"正在为{label}签到")
        result = self._call(game, "sign", post=True)
        # 今天要领的是第 total + 1 天的奖励，列表下标为 total
        reward = describe_award(awards, total)
        if result.get("retcode") == ALREADY_SIGNED_RETCODE:
            self._add(messages, f"{label} 今日已签到，奖励 {reward}")
            return "success", f"已签到 {reward}"
        problem = self._problem(result)
        if problem:
            return self._report(messages, label, *problem)
        if geetest_triggered(result.get("data")):
            # 国际服的验证码识别没有验证过，先不处理，只如实报告
            self._add(messages, f"{label} 触发验证码，本次跳过")
            return "failed", "触发验证码"
        self._add(messages, f"{label} 签到成功，奖励 {reward}")
        return "success", reward

    def _problem(self, result: dict[str, Any]) -> tuple[str, str] | None:
        """非 0 的返回码归类成 (类别, 说明)；正常返回 None。"""
        code = result.get("retcode")
        if code == 0:
            return None
        if code in INVALID_COOKIE_RETCODES:
            return "invalid", f"cookie 已失效，请重新登录({code})"
        if code in NO_GAME_ACCOUNT_RETCODES:
            return "unbound", "未绑定游戏账号"
        return "error", f"{result.get('message')}({code})"

    def _report(self, messages: list[str], label: str, category: str, reason: str) -> tuple[str, str]:
        if category == "unbound":
            self._add(messages, f"{label} {reason}，跳过")
            return "skipped", reason
        if category == "invalid":
            self.cookie_invalid = True
        self._add(messages, f"{label} 签到失败: {reason}")
        return "failed", reason

    def _awards(self, game: dict[str, Any]) -> list[dict[str, Any]]:
        """奖励列表只用来在日志里显示奖励名，取不到不影响签到。"""
        try:
            data = self._call(game, "home")
        except Exception:
            return []
        if data.get("retcode") != 0:
            return []
        awards = (data.get("data") or {}).get("awards", [])
        return awards if isinstance(awards, list) else []

    def _call(self, game: dict[str, Any], endpoint: str, post: bool = False) -> dict[str, Any]:
        url = f"{game['base_url']}/{endpoint}"
        params = {"act_id": game["act_id"], "lang": c.OS_LANG}
        headers = self._headers(game)
        if post:
            # genshin.py 只把 act_id 放在 query 里，也有脚本放在 body 里，两处都给
            return self.client.post_json(url, params=params, json={"act_id": game["act_id"]}, headers=headers)
        return self.client.get_json(url, params=params, headers=headers)

    def _headers(self, game: dict[str, Any]) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": c.OS_ACT_ORIGIN,
            "Referer": f"{c.OS_ACT_ORIGIN}/",
            "User-Agent": c.OS_USER_AGENT,
            "x-rpc-signgame": game["signgame"],
            "Cookie": str(self.account.get("cookie") or ""),
        }

    def _pause(self) -> None:
        span = self.config.get("bbs", {}).get("delay_seconds", [1, 3])
        try:
            low, high = int(span[0]), int(span[1])
        except (TypeError, ValueError, IndexError):
            low, high = 1, 3
        time.sleep(random.uniform(max(low, 0), max(high, low)))

    def _add(self, messages: list[str], message: str) -> None:
        messages.append(message)
        if self.emit:
            self.emit(message)


def probe_hoyolab_cookie(cookie: str) -> str:
    """登录时在线校验一次 cookie，省得无效凭证悄悄存进去、等到签到才报错。"""
    with ApiClient(timeout=15) as client:
        return HoyolabCheckin(client, {}, {"cookie": cookie}).probe()


def geetest_triggered(data: Any) -> bool:
    """签到返回 0 时仍可能要求验证码；风控信息在国际服嵌套在 gt_result 里，国服则平铺。"""
    data = data if isinstance(data, dict) else {}
    risk = data.get("gt_result")
    risk = risk if isinstance(risk, dict) else data
    return to_int(risk.get("risk_code")) != 0 and to_int(risk.get("success")) != 0


def describe_award(awards: list[dict[str, Any]], index: int) -> str:
    if not awards:
        return "未知"
    award = awards[min(max(index, 0), len(awards) - 1)]
    return f"「{award.get('name', '未知')}」x{award.get('cnt', '?')}"


def to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
