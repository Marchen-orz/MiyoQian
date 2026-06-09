# -*- coding: utf-8 -*-
"""米游币社区任务。"""

from __future__ import annotations

import json
import random
import time
from typing import Any, Callable

from .. import constants as c
from ..auth.login import refresh_cookie_token
from ..core import captcha, cookies, crypto
from ..core.http import ApiClient


class BbsTasks:
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
        self.bbs_config = config.get("bbs", {})
        self.device = config["device"]
        self.emit = emit

    def run(self) -> list[str]:
        messages: list[str] = []
        success: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []
        self._add(messages, "== 米游币社区任务 ==")
        self._add(messages, "正在获取米游币任务状态")
        state = self._task_state()
        if not state:
            self._add(messages, "任务状态获取失败，请检查 cookie/stoken")
            return messages
        can_get = int(state.get("can_get_points") or 0)
        received = int(state.get("already_received_points") or 0)
        total = int(state.get("total_points") or 0)
        task_flags = self._task_flags(state)
        possible_today = received + can_get
        self._add(messages, f"米游币今日进度：已获得 {received}，还可获得 {can_get}，预计总共可获得 {possible_today}")
        if can_get == 0:
            self._add(messages, f"今日任务已完成，今日已得 {received}，当前总计 {total}")
            self._add(messages, f"米游币任务汇总：成功 0，失败 0，跳过 0，今日总共可获得 {possible_today}，实际已获得 {received}，本次新增 0")
            return messages
        if self.bbs_config.get("checkin", True) and not task_flags["sign"]:
            result = self._community_sign()
            messages.extend(result["messages"])
            success.extend(result["success"])
            failed.extend(result["failed"])
            self._sleep()
        elif task_flags["sign"]:
            skipped.append("社区签到已完成")
            self._add(messages, "社区签到已完成，跳过")
        interaction_plan = [
            ("read", "read_num", "看帖", self._read),
            ("like", "like_num", "点赞", self._like),
            ("share", None, "分享", self._share),
        ]
        needs_posts = any(
            self.bbs_config.get(flag, True) and not task_flags[flag]
            for flag, _, _, _ in interaction_plan
        )
        if needs_posts:
            self._add(messages, "正在获取帖子列表")
            posts = self._posts()
            if posts:
                for flag, num_key, label, action in interaction_plan:
                    if self.bbs_config.get(flag, True) and not task_flags[flag]:
                        limit = task_flags[num_key] if num_key else 1
                        result = action(posts[:limit])
                        messages.extend(result["messages"])
                        success.extend(result["success"])
                        failed.extend(result["failed"])
                    elif self.bbs_config.get(flag, True) and task_flags[flag]:
                        skipped.append(f"{label}已完成")
                        self._add(messages, f"{label}任务已完成，跳过")
            else:
                failed.append("获取帖子列表失败")
                self._add(messages, "获取帖子列表失败，无法执行看帖/点赞/分享")
        else:
            for flag, _, label, _ in interaction_plan:
                if self.bbs_config.get(flag, True) and task_flags[flag]:
                    skipped.append(f"{label}已完成")
                    self._add(messages, f"{label}任务已完成，跳过")
        state = self._task_state() or state
        final_received = int(state.get("already_received_points") or received)
        final_can_get = max(possible_today - final_received, 0)
        final_total = int(state.get("total_points") or total)
        gained = max(final_received - received, 0)
        final_possible = max(possible_today, final_received)
        self._add(
            messages,
            "社区任务结束："
            f"今日已得 {final_received}，"
            f"还能获得 {final_can_get}，"
            f"当前总计 {final_total}",
        )
        self._add(
            messages,
            f"米游币任务汇总：成功 {len(success)}，失败 {len(failed)}，跳过 {len(skipped)}，"
            f"今日总共可获得 {final_possible}，实际已获得 {final_received}，本次新增 {gained}",
        )
        if success:
            self._add(messages, f"米游币成功项：{'; '.join(success)}")
        if failed:
            self._add(messages, f"米游币失败项：{'; '.join(failed)}")
        return messages

    def _headers(self) -> dict[str, str]:
        headers = {
            "DS": crypto.ds(web=False),
            "cookie": cookies.stoken_cookie(self.account),
            "x-rpc-client_type": "2",
            "x-rpc-app_version": c.BBS_VERSION,
            "x-rpc-sys_version": "12",
            "x-rpc-channel": "miyousheluodi",
            "x-rpc-device_id": str(self.device["id"]),
            "x-rpc-device_name": str(self.device.get("name") or "Xiaomi MI 6"),
            "x-rpc-device_model": str(self.device.get("model") or "Mi 6"),
            "x-rpc-h265_supported": "1",
            "Referer": "https://app.mihoyo.com",
            "x-rpc-verify_key": c.PASSPORT_APP_ID,
            "x-rpc-csm_source": "discussion",
            "Content-Type": "application/json; charset=UTF-8",
            "Host": "bbs-api.miyoushe.com",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "User-Agent": "okhttp/4.9.3",
        }
        if self.device.get("fp"):
            headers["x-rpc-device_fp"] = str(self.device["fp"])
        return headers

    def _web_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://webstatic.mihoyo.com",
            "User-Agent": c.DEFAULT_MOBILE_UA,
            "Referer": "https://webstatic.mihoyo.com",
            "Accept-Language": "zh-CN,en-US;q=0.8",
            "X-Requested-With": "com.mihoyo.hyperion",
            "Cookie": str(self.account.get("cookie") or ""),
        }

    def _task_state(self, retried: bool = False) -> dict[str, Any]:
        data = self.client.get_json(
            c.BBS_TASKS_URL,
            params={"point_sn": "myb"},
            headers=self._web_headers(),
        )
        if data.get("retcode") == -100 and not retried:
            if refresh_cookie_token(self.client, self.account):
                return self._task_state(retried=True)
        return data.get("data", {}) if data.get("retcode") == 0 else {}

    def _task_flags(self, state: dict[str, Any]) -> dict[str, Any]:
        flags = {"sign": False, "read": False, "read_num": 3, "like": False, "like_num": 5, "share": False}
        missions = state.get("states") or []
        mapping = {
            58: ("sign", None),
            59: ("read", "read_num"),
            60: ("like", "like_num"),
            61: ("share", None),
        }
        for mission in missions:
            task_id = mission.get("mission_id")
            if task_id not in mapping:
                continue
            flag, num_key = mapping[task_id]
            if mission.get("is_get_award"):
                flags[flag] = True
            elif num_key:
                flags[num_key] = max(int(flags[num_key]) - int(mission.get("happened_times") or 0), 0)
        return flags

    def _community_sign(self) -> dict[str, list[str]]:
        messages: list[str] = []
        success: list[str] = []
        failed: list[str] = []
        headers = self._headers()
        for forum_id in self.bbs_config.get("forums", [5, 2]):
            forum = c.BBS_FORUMS.get(int(forum_id))
            if not forum:
                continue
            self._add(messages, f"正在进行{forum['name']}社区签到")
            body = json.dumps({"gids": forum["id"]}, separators=(",", ":"))
            headers["DS"] = crypto.ds_x6(body=body)
            data = self.client.post_json(c.BBS_SIGN_URL, content=body, headers=headers)
            if data.get("retcode") == 0:
                self._add(messages, f"{forum['name']} 社区签到成功")
                success.append(f"{forum['name']}社区签到")
            elif data.get("retcode") == 1034:
                retry_data = self._retry_bbs_captcha_request(
                    messages,
                    "社区签到",
                    lambda challenge: self._community_sign_once(headers, body, challenge),
                )
                if retry_data.get("retcode") == 0:
                    self._add(messages, f"{forum['name']} 社区签到成功")
                    success.append(f"{forum['name']}社区签到")
                elif not captcha.is_enabled(self.config):
                    self._add(messages, f"{forum['name']} 社区签到触发验证码，已跳过")
                    failed.append(f"{forum['name']}社区签到触发验证码")
                else:
                    reason = str(retry_data.get("message") or "未知错误")
                    self._add(messages, f"{forum['name']} 社区签到验证码重试失败: {reason}")
                    failed.append(f"{forum['name']}社区签到触发验证码")
            else:
                reason = str(data.get("message") or "未知错误")
                self._add(messages, f"{forum['name']} 社区签到失败: {reason}")
                failed.append(f"{forum['name']}社区签到 {reason}")
            self._sleep()
        return {"messages": messages, "success": success, "failed": failed}

    def _posts(self) -> list[tuple[str, str]]:
        forums = [c.BBS_FORUMS.get(int(i)) for i in self.bbs_config.get("forums", [5, 2])]
        forums = [forum for forum in forums if forum]
        if not forums:
            return []
        forum = forums[0]
        data = self.client.get_json(
            c.BBS_POST_LIST_URL,
            params={
                "forum_id": forum["forum_id"],
                "is_good": "false",
                "is_hot": "false",
                "page_size": 20,
                "sort_type": 1,
            },
            headers=self._headers(),
        )
        raw_posts = data.get("data", {}).get("list", []) if data.get("retcode") == 0 else []
        posts: list[tuple[str, str]] = []
        for item in raw_posts:
            post = item.get("post", {})
            post_id = str(post.get("post_id") or "")
            title = str(post.get("subject") or post_id)
            if post_id:
                posts.append((post_id, title))
        random.shuffle(posts)
        return posts[: int(self.bbs_config.get("post_limit") or 5)]

    def _read(self, posts: list[tuple[str, str]]) -> dict[str, list[str]]:
        messages: list[str] = []
        success: list[str] = []
        failed: list[str] = []
        for post_id, title in posts:
            self._add(messages, f"正在浏览: {title}")
            data = self.client.get_json(c.BBS_DETAIL_URL, params={"post_id": post_id}, headers=self._headers())
            if data.get("message") == "OK":
                self._add(messages, f"阅读成功: {title}")
                success.append(f"看帖 {title}")
            else:
                reason = str(data.get("message") or "未知错误")
                self._add(messages, f"阅读失败: {title} ({reason})")
                failed.append(f"看帖 {title} {reason}")
            self._sleep()
        return {"messages": messages, "success": success, "failed": failed}

    def _like(self, posts: list[tuple[str, str]]) -> dict[str, list[str]]:
        messages: list[str] = []
        success: list[str] = []
        failed: list[str] = []
        for post_id, title in posts:
            self._add(messages, f"正在点赞: {title}")
            data = self.client.post_json(
                c.BBS_LIKE_URL,
                json={"post_id": post_id, "is_cancel": False},
                headers=self._headers(),
            )
            if data.get("message") == "OK":
                self._add(messages, f"点赞成功: {title}")
                success.append(f"点赞 {title}")
                if self.bbs_config.get("cancel_like", True):
                    self._sleep()
                    self._add(messages, f"正在取消点赞: {title}")
                    self.client.post_json(
                        c.BBS_LIKE_URL,
                        json={"post_id": post_id, "is_cancel": True},
                        headers=self._headers(),
                    )
            elif data.get("retcode") == 1034:
                retry_data = self._retry_bbs_captcha_request(
                    messages,
                    "点赞",
                    lambda challenge: self._like_once(post_id, challenge),
                )
                if retry_data.get("message") == "OK":
                    self._add(messages, f"点赞成功: {title}")
                    success.append(f"点赞 {title}")
                    if self.bbs_config.get("cancel_like", True):
                        self._sleep()
                        self._add(messages, f"正在取消点赞: {title}")
                        self.client.post_json(
                            c.BBS_LIKE_URL,
                            json={"post_id": post_id, "is_cancel": True},
                            headers=self._headers(),
                        )
                elif not captcha.is_enabled(self.config):
                    self._add(messages, f"点赞触发验证码，已跳过: {title}")
                    failed.append(f"点赞 {title} 触发验证码")
                else:
                    reason = str(retry_data.get("message") or "未知错误")
                    self._add(messages, f"点赞验证码重试失败: {title} ({reason})")
                    failed.append(f"点赞 {title} 触发验证码")
            else:
                reason = str(data.get("message") or "未知错误")
                self._add(messages, f"点赞失败: {title} ({reason})")
                failed.append(f"点赞 {title} {reason}")
            self._sleep()
        return {"messages": messages, "success": success, "failed": failed}

    def _share(self, posts: list[tuple[str, str]]) -> dict[str, list[str]]:
        messages: list[str] = []
        success: list[str] = []
        failed: list[str] = []
        for post_id, title in posts:
            self._add(messages, f"正在分享: {title}")
            data = self.client.get_json(
                c.BBS_SHARE_URL,
                params={"entity_id": post_id, "entity_type": 1},
                headers=self._headers(),
            )
            if data.get("message") == "OK":
                self._add(messages, f"分享成功: {title}")
                success.append(f"分享 {title}")
            else:
                reason = str(data.get("message") or "未知错误")
                self._add(messages, f"分享失败: {title} ({reason})")
                failed.append(f"分享 {title} {reason}")
            self._sleep()
        return {"messages": messages, "success": success, "failed": failed}

    def _add(self, messages: list[str], message: str) -> None:
        messages.append(message)
        if self.emit:
            self.emit(message)

    def _community_sign_once(self, base_headers: dict[str, str], body: str, challenge: str) -> dict[str, Any]:
        headers = dict(base_headers)
        headers["x-rpc-challenge"] = challenge
        headers["DS"] = crypto.ds_x6(body=body)
        return self.client.post_json(c.BBS_SIGN_URL, content=body, headers=headers)

    def _like_once(self, post_id: str, challenge: str) -> dict[str, Any]:
        headers = self._headers()
        headers["x-rpc-challenge"] = challenge
        return self.client.post_json(
            c.BBS_LIKE_URL,
            json={"post_id": post_id, "is_cancel": False},
            headers=headers,
        )

    def _retry_bbs_captcha_request(
        self,
        messages: list[str],
        scene: str,
        request: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        if not captcha.is_enabled(self.config):
            return {"retcode": 1034, "message": "触发验证码"}
        max_retries = captcha_max_retries(self.config)
        last_data: dict[str, Any] = {"retcode": 1034, "message": "触发验证码"}
        for attempt in range(1, max_retries + 1):
            challenge = self._pass_bbs_captcha(messages, scene, attempt, max_retries)
            if not challenge:
                last_data = {"retcode": 1034, "message": "验证码处理失败"}
                continue
            last_data = request(challenge)
            if last_data.get("retcode") == 0 or last_data.get("message") == "OK":
                return last_data
            if attempt < max_retries:
                self._add(messages, f"{scene}验证码提交失败，准备重新获取验证码")
        return last_data

    def _pass_bbs_captcha(self, messages: list[str], scene: str, attempt: int, max_retries: int) -> str:
        provider = captcha.active_provider_label(self.config)
        self._add(messages, f"{scene}触发验证码，正在调用{provider}识别({attempt}/{max_retries})")
        create_data = self.client.get_json(c.BBS_CREATE_VERIFICATION_URL, headers=self._headers())
        if create_data.get("retcode") != 0:
            self._add(messages, f"{scene}验证码初始化失败: {create_data.get('message')}")
            return ""
        raw = create_data.get("data") or {}
        gt = str(raw.get("gt") or "")
        challenge = str(raw.get("challenge") or "")
        if not gt or not challenge:
            self._add(messages, f"{scene}验证码初始化结果缺少 gt/challenge")
            return ""
        geetest_success = parse_optional_int(raw.get("success"))
        solution = captcha.solve_bbs_captcha(
            self.client,
            self.config,
            gt,
            challenge,
            geetest_success=geetest_success,
            emit=self.emit,
        )
        if not solution:
            self._add(messages, f"{scene}验证码识别失败，准备重新获取验证码")
            return ""
        verify_data = self.client.post_json(
            c.BBS_VERIFY_VERIFICATION_URL,
            json={
                "geetest_challenge": solution.challenge,
                "geetest_validate": solution.validate,
                "geetest_seccode": f"{solution.validate}|jordan",
            },
            headers=self._headers(),
        )
        if verify_data.get("retcode") != 0:
            self._add(messages, f"{scene}验证码校验失败，准备重新获取验证码: {verify_data.get('message')}")
            return ""
        passed_challenge = str((verify_data.get("data") or {}).get("challenge") or "")
        if not passed_challenge:
            self._add(messages, f"{scene}验证码校验结果缺少 challenge，准备重新获取验证码")
            return ""
        return passed_challenge

    def _sleep(self) -> None:
        span = self.bbs_config.get("delay_seconds", [1, 3])
        try:
            low, high = int(span[0]), int(span[1])
        except (TypeError, ValueError, IndexError):
            low, high = 1, 3
        time.sleep(random.uniform(max(low, 0), max(high, low)))


def parse_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def captcha_max_retries(config: dict[str, Any]) -> int:
    try:
        return max(int(config.get("captcha", {}).get("max_retries") or 3), 1)
    except (TypeError, ValueError):
        return 3
