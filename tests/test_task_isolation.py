# -*- coding: utf-8 -*-
"""单次网络异常（如读超时）只能让对应的角色/条目失败，不能中断整轮签到。"""

import unittest
from typing import Any
from unittest.mock import Mock, patch

from miyouqian import constants as c
from miyouqian.core.http import ApiError
from miyouqian.service import notifier, runner
from miyouqian.tasks.bbs import BbsTasks
from miyouqian.tasks.games import GameCheckin

TIMEOUT = "网络请求失败: https://example.com/info (The read operation timed out)"


def game_role(uid: str, nickname: str) -> dict[str, str]:
    return {"game_uid": uid, "nickname": nickname, "region": "cn_gf01"}


SIGNED = {"is_sign": True, "total_sign_day": 1}


class GameCheckinIsolationTest(unittest.TestCase):
    def run_checkin(self, enabled: list[str], roles: Any, info: Any) -> list[str]:
        config = {"device": {"id": "dev"}, "games": {"enabled": enabled}, "bbs": {"delay_seconds": [0, 0]}}
        checkin = GameCheckin(Mock(), config, {"cookie": "c"})
        with patch("miyouqian.tasks.games.time.sleep"), \
                patch.object(GameCheckin, "_get_roles", side_effect=roles), \
                patch.object(GameCheckin, "_get_awards", return_value=[]), \
                patch.object(GameCheckin, "_get_info", side_effect=info):
            return checkin.run()

    def test_timeout_on_one_game_does_not_skip_the_next_game(self) -> None:
        lines = self.run_checkin(
            ["genshin", "zzz"],
            roles=[[game_role("1", "甲")], [game_role("2", "乙")]],
            info=[ApiError(TIMEOUT), SIGNED],
        )

        genshin, zzz = c.GAMES["genshin"]["name"], c.GAMES["zzz"]["name"]
        self.assertIn("游戏社区签到汇总：成功 1，失败 1，跳过 0", lines)
        self.assertIn(f"游戏社区成功项：{zzz} 乙(2) 已签到 未知", lines)
        failed = next(line for line in lines if line.startswith("游戏社区失败项："))
        self.assertIn(f"{genshin} 甲(1) 请求异常", failed)
        self.assertIn("read operation timed out", failed)

    def test_timeout_on_one_role_keeps_the_other_roles_of_the_same_game(self) -> None:
        lines = self.run_checkin(
            ["genshin"],
            roles=[[game_role("1", "甲"), game_role("2", "乙")]],
            info=[ApiError(TIMEOUT), SIGNED],
        )

        self.assertIn("游戏社区签到汇总：成功 1，失败 1，跳过 0", lines)
        self.assertTrue(any("乙(2)" in line and line.startswith("游戏社区成功项：") for line in lines))
        self.assertTrue(any("甲(1)" in line and line.startswith("游戏社区失败项：") for line in lines))

    def test_timeout_fetching_roles_fails_that_game_only(self) -> None:
        lines = self.run_checkin(
            ["genshin", "zzz"],
            roles=[ApiError(TIMEOUT), [game_role("2", "乙")]],
            info=[SIGNED],
        )

        self.assertIn("游戏社区签到汇总：成功 1，失败 1，跳过 0", lines)
        failed = next(line for line in lines if line.startswith("游戏社区失败项："))
        self.assertIn(f"{c.GAMES['genshin']['name']} 请求异常", failed)

    def test_summary_reports_the_failure_so_the_push_is_not_a_success(self) -> None:
        lines = self.run_checkin(["genshin"], roles=[[game_role("1", "甲")]], info=[ApiError(TIMEOUT)])

        self.assertFalse(notifier.is_task_success(lines))
        game = notifier.build_structured_summary(lines, False)["sections"][0]["game"]
        self.assertEqual("失败 1", game["label"])


class FakeBbsClient:
    """按 URL 返回预设响应；预设为异常时抛出，用来模拟读超时。"""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def _respond(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        route = self.routes[url]
        response = route.pop(0) if isinstance(route, list) else route
        if isinstance(response, Exception):
            raise response
        return response

    def get_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self._respond(url)

    def post_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self._respond(url)


def bbs_state(received: int = 0) -> dict[str, Any]:
    return {
        "retcode": 0,
        "data": {"can_get_points": 40 - received, "already_received_points": received, "total_points": 100, "states": []},
    }


POSTS = {
    "retcode": 0,
    "data": {"list": [{"post": {"post_id": "1", "subject": "帖子A"}}, {"post": {"post_id": "2", "subject": "帖子B"}}]},
}
OK = {"message": "OK", "retcode": 0}


class BbsTasksIsolationTest(unittest.TestCase):
    def run_bbs(self, **overrides: Any) -> tuple[list[str], FakeBbsClient]:
        routes: dict[str, Any] = {
            c.BBS_TASKS_URL: [bbs_state(), bbs_state(40)],
            c.BBS_SIGN_URL: OK,
            c.BBS_POST_LIST_URL: POSTS,
            c.BBS_DETAIL_URL: OK,
            c.BBS_LIKE_URL: OK,
            c.BBS_SHARE_URL: OK,
        }
        routes.update(overrides)
        client = FakeBbsClient(routes)
        config = {
            "device": {"id": "dev"},
            "bbs": {"delay_seconds": [0, 0], "forums": [5, 2], "post_limit": 2, "cancel_like": False},
        }
        account = {"stuid": "1", "stoken": "tok", "mid": "m", "cookie": "c"}
        with patch("miyouqian.tasks.bbs.time.sleep"):
            return BbsTasks(client, config, account).run(), client  # type: ignore[arg-type]

    def line(self, lines: list[str], prefix: str) -> str:
        return next(line for line in lines if line.startswith(prefix))

    def test_forum_sign_timeout_does_not_stop_the_other_forums_or_tasks(self) -> None:
        lines, _ = self.run_bbs(**{c.BBS_SIGN_URL: [ApiError(TIMEOUT), OK]})

        failed = self.line(lines, "米游币失败项：")
        self.assertIn("社区签到 请求异常", failed)
        success = self.line(lines, "米游币成功项：")
        self.assertIn("社区签到", success)
        self.assertIn("看帖 帖子A", success + failed)
        self.assertIn("分享 帖子", success + failed)
        self.assertTrue(any(line.startswith("米游币任务汇总：") for line in lines))

    def test_read_timeout_on_one_post_keeps_reading_the_rest(self) -> None:
        lines, client = self.run_bbs(**{c.BBS_DETAIL_URL: [ApiError(TIMEOUT), OK]})

        self.assertEqual(2, client.calls.count(c.BBS_DETAIL_URL))
        self.assertIn("看帖", self.line(lines, "米游币失败项："))
        self.assertIn("看帖", self.line(lines, "米游币成功项："))

    def test_like_timeout_is_a_failed_item_not_a_crash(self) -> None:
        lines, client = self.run_bbs(**{c.BBS_LIKE_URL: [ApiError(TIMEOUT), OK]})

        self.assertEqual(2, client.calls.count(c.BBS_LIKE_URL))
        self.assertIn("点赞", self.line(lines, "米游币失败项："))
        self.assertIn("分享 帖子", self.line(lines, "米游币成功项："))

    def test_post_list_timeout_is_reported_as_the_existing_post_list_failure(self) -> None:
        lines, _ = self.run_bbs(**{c.BBS_POST_LIST_URL: ApiError(TIMEOUT)})

        self.assertIn("获取帖子列表失败，无法执行看帖/点赞/分享", lines)
        self.assertFalse(notifier.is_task_success(lines))
        self.assertTrue(any(line.startswith("米游币任务汇总：") for line in lines))

    def test_state_timeout_is_reported_as_the_existing_state_failure(self) -> None:
        lines, _ = self.run_bbs(**{c.BBS_TASKS_URL: ApiError(TIMEOUT)})

        self.assertIn("任务状态获取失败，请检查 cookie/stoken", lines)
        self.assertFalse(notifier.is_task_success(lines))

    def test_final_progress_timeout_keeps_the_summary(self) -> None:
        lines, _ = self.run_bbs(**{c.BBS_TASKS_URL: [bbs_state(), ApiError(TIMEOUT)]})

        self.assertTrue(any(line.startswith("米游币任务汇总：") for line in lines))
        self.assertIn("米游币成功项：", "\n".join(lines))


class RunTasksIsolationTest(unittest.TestCase):
    CONFIG = {
        "enable": True,
        "device": {"id": "dev"},
        "accounts": [{"name": "甲"}, {"name": "乙"}],
        "features": {"game_checkin": True, "cloud_game_checkin": False, "bbs_tasks": True},
    }

    def run_all(self, **kwargs: Any) -> list[str]:
        ran: list[str] = []

        class ExplodingGames:
            def __init__(self, *args: Any, **kw: Any) -> None:
                pass

            def run(self, only_games: Any = None) -> list[str]:
                raise ApiError(TIMEOUT)

        class FakeBbs:
            def __init__(self, client: Any, config: Any, account: Any, emit: Any = None) -> None:
                self.account = account

            def run(self) -> list[str]:
                ran.append(self.account["name"])
                return [f"米游币任务汇总：成功 1，失败 0，跳过 0 ({self.account['name']})"]

        with patch.object(runner, "GameCheckin", ExplodingGames), \
                patch.object(runner, "BbsTasks", FakeBbs), \
                patch.object(runner.devicelib, "ensure_device_fp", return_value=(True, "")), \
                patch.object(runner, "save_config"):
            output = runner.run_tasks(self.CONFIG, "cfg.json", **kwargs)
        self.assertEqual(["甲", "乙"], ran)
        return output

    def test_a_stage_that_blows_up_is_recorded_and_the_rest_still_runs(self) -> None:
        output = self.run_all()

        self.assertEqual(2, sum(line.startswith("游戏社区失败项：游戏社区签到执行异常") for line in output))
        self.assertTrue(any("米游币任务汇总" in line for line in output))
        self.assertFalse(notifier.is_task_success(output))

    def test_streaming_mode_records_the_failure_with_its_component(self) -> None:
        streamed: list[tuple[str, str]] = []

        output = self.run_all(emit_component=lambda message, component: streamed.append((component, message)))

        self.assertEqual(output, [message for _, message in streamed])
        self.assertIn(("game", f"游戏社区失败项：游戏社区签到执行异常: {TIMEOUT}"), streamed)


if __name__ == "__main__":
    unittest.main()
