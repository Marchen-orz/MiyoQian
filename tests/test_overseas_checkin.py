# -*- coding: utf-8 -*-
"""国际服（HoYoLAB）签到、cookie 登录，以及按账号 region 的分发。"""

import copy
import pathlib
import tempfile
import threading
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import yaml

from miyouqian import constants as c
from miyouqian.core.config import (
    bind_shop_plan_accounts,
    find_account_index_by_stuid,
    load_config,
    normalize_config,
    save_config,
    upsert_account,
    validate_unique_account_uids,
)
from miyouqian.core.http import ApiError
from miyouqian.overseas.checkin import HoyolabCheckin, describe_award, geetest_triggered
from miyouqian.overseas.cookie import parse_hoyolab_cookie
from miyouqian.service import notifier, runner, web

COOKIE = "ltoken_v2=v2_abc; ltuid_v2=12345; ltmid_v2=mid"
AWARDS = [{"name": f"奖励{day}", "cnt": day} for day in range(1, 32)]

GENSHIN = c.OS_GAMES["genshin"]
STARRAIL = c.OS_GAMES["starrail"]


def url(game: dict[str, Any], endpoint: str) -> str:
    return f"{game['base_url']}/{endpoint}"


OK = {"retcode": 0, "message": "OK"}


def ok(data: dict[str, Any]) -> dict[str, Any]:
    return {**OK, "data": data}


def signed(total: int, is_sign: bool) -> dict[str, Any]:
    return ok({"total_sign_day": total, "is_sign": is_sign, "first_bind": False})


SIGN_OK = ok({"code": "ok", "gt_result": {"risk_code": 0, "gt": "", "challenge": "", "success": 0, "is_risk": False}})


class FakeClient:
    """按 URL 返回预设响应；预设是列表时依次取，是异常时抛出。"""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _respond(self, method: str, target: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, target, kwargs))
        route = self.routes[target]
        response = route.pop(0) if isinstance(route, list) else route
        if isinstance(response, Exception):
            raise response
        return response

    def get_json(self, target: str, **kwargs: Any) -> dict[str, Any]:
        return self._respond("GET", target, kwargs)

    def post_json(self, target: str, **kwargs: Any) -> dict[str, Any]:
        return self._respond("POST", target, kwargs)

    def urls(self) -> list[str]:
        return [target for _, target, _ in self.calls]


def run_checkin(
    routes: dict[str, Any],
    enabled: list[str],
    account: dict[str, Any] | None = None,
    only_games: list[str] | None = None,
) -> tuple[list[str], FakeClient]:
    client = FakeClient(routes)
    config = {"games": {"enabled": enabled}, "bbs": {"delay_seconds": [0, 0]}}
    account = {"cookie": COOKIE} if account is None else account
    with patch("miyouqian.overseas.checkin.time.sleep"):
        lines = HoyolabCheckin(client, config, account).run(only_games=only_games)  # type: ignore[arg-type]
    return lines, client


def home(game: dict[str, Any] = GENSHIN) -> dict[str, Any]:
    return {url(game, "home"): ok({"awards": AWARDS})}


class HoyolabCheckinTest(unittest.TestCase):
    def test_signs_in_and_reports_the_reward_for_today(self) -> None:
        routes = {**home(), url(GENSHIN, "info"): signed(3, False), url(GENSHIN, "sign"): SIGN_OK}
        lines, client = run_checkin(routes, ["genshin"])

        # 已签 3 天，今天领的是第 4 天（列表下标 3）
        self.assertIn("游戏社区成功项：原神(国际服) 「奖励4」x4", lines)
        self.assertIn("游戏社区签到汇总：成功 1，失败 0，跳过 0", lines)
        self.assertEqual([url(GENSHIN, "info"), url(GENSHIN, "home"), url(GENSHIN, "sign")], client.urls())

    def test_requests_use_the_hoyolab_shape_and_never_leak_cn_headers(self) -> None:
        routes = {**home(), url(GENSHIN, "info"): signed(0, False), url(GENSHIN, "sign"): SIGN_OK}
        _, client = run_checkin(routes, ["genshin"])

        by_url = {target: (method, kwargs) for method, target, kwargs in client.calls}
        method, kwargs = by_url[url(GENSHIN, "sign")]
        self.assertEqual("POST", method)
        self.assertEqual({"act_id": GENSHIN["act_id"], "lang": c.OS_LANG}, kwargs["params"])
        self.assertEqual({"act_id": GENSHIN["act_id"]}, kwargs["json"])
        headers = kwargs["headers"]
        self.assertEqual(COOKIE, headers["Cookie"])
        self.assertEqual("https://act.hoyolab.com/", headers["Referer"])
        self.assertEqual("hk4e", headers["x-rpc-signgame"])
        # 国际服不需要 DS 和设备头，也不能带国服 APP 的标识
        self.assertFalse({"DS", "x-rpc-device_id", "x-rpc-app_version", "x-rpc-client_type"} & set(headers))
        self.assertNotIn("miHoYoBBS", headers["User-Agent"])

    def test_first_day_of_a_month_reports_the_first_reward(self) -> None:
        routes = {**home(), url(GENSHIN, "info"): signed(0, False), url(GENSHIN, "sign"): SIGN_OK}
        lines, _ = run_checkin(routes, ["genshin"])

        self.assertIn("游戏社区成功项：原神(国际服) 「奖励1」x1", lines)

    def test_already_signed_does_not_post(self) -> None:
        routes = {**home(), url(GENSHIN, "info"): signed(5, True)}
        lines, client = run_checkin(routes, ["genshin"])

        self.assertNotIn(url(GENSHIN, "sign"), client.urls())
        self.assertIn("游戏社区成功项：原神(国际服) 已签到 「奖励5」x5", lines)

    def test_already_claimed_retcode_counts_as_success(self) -> None:
        sign = {"retcode": -5003, "message": "Traveler, you've already checked in today"}
        routes = {**home(), url(GENSHIN, "info"): signed(2, False), url(GENSHIN, "sign"): sign}
        lines, _ = run_checkin(routes, ["genshin"])

        self.assertIn("游戏社区签到汇总：成功 1，失败 0，跳过 0", lines)

    def test_invalid_cookie_fails_once_and_stops_the_remaining_games(self) -> None:
        routes = {**home(), url(GENSHIN, "info"): {"retcode": -100, "message": "login"}}
        lines, client = run_checkin(routes, ["genshin", "starrail", "zzz"])

        self.assertEqual(0, sum("hkrpg" in target for target in client.urls()))
        self.assertIn("游戏社区签到汇总：成功 0，失败 1，跳过 0", lines)
        failed = next(line for line in lines if line.startswith("游戏社区失败项："))
        self.assertIn("cookie 已失效", failed)
        self.assertFalse(notifier.is_task_success(lines))

    def test_game_without_a_bound_account_is_skipped_not_failed(self) -> None:
        routes = {
            **home(),
            **home(STARRAIL),
            url(GENSHIN, "info"): {"retcode": -10002, "message": "no role"},
            url(STARRAIL, "info"): signed(1, True),
        }
        lines, _ = run_checkin(routes, ["genshin", "starrail"])

        self.assertIn("游戏社区签到汇总：成功 1，失败 0，跳过 1", lines)
        self.assertTrue(notifier.is_task_success(lines))

    def test_geetest_is_reported_as_a_failure(self) -> None:
        risk = ok({"gt_result": {"risk_code": 5001, "gt": "g", "challenge": "c", "success": 1, "is_risk": True}})
        routes = {**home(), url(GENSHIN, "info"): signed(1, False), url(GENSHIN, "sign"): risk}
        lines, _ = run_checkin(routes, ["genshin"])

        self.assertIn("游戏社区失败项：原神(国际服) 触发验证码", lines)
        self.assertFalse(notifier.is_task_success(lines))

    def test_geetest_detection_handles_both_response_shapes(self) -> None:
        self.assertTrue(geetest_triggered({"gt_result": {"risk_code": 5001, "success": 1}}))
        self.assertTrue(geetest_triggered({"risk_code": 375, "success": 1}))
        self.assertFalse(geetest_triggered({"gt_result": {"risk_code": 0, "success": 0}}))
        self.assertFalse(geetest_triggered({"code": "ok"}))
        self.assertFalse(geetest_triggered(None))

    def test_a_game_the_overseas_server_does_not_have_is_skipped(self) -> None:
        routes = {**home(), url(GENSHIN, "info"): signed(1, True)}
        lines, client = run_checkin(routes, ["honkai2", "genshin"])

        self.assertIn("游戏社区签到汇总：成功 1，失败 0，跳过 1", lines)
        self.assertTrue(any("崩坏学园2" in line and "跳过" in line for line in lines))
        self.assertEqual(2, len(client.calls))

    def test_network_error_on_one_game_keeps_the_next_game(self) -> None:
        timeout = ApiError("网络请求失败: x (The read operation timed out)")
        routes = {
            **home(),
            **home(STARRAIL),
            url(GENSHIN, "info"): timeout,
            url(STARRAIL, "info"): signed(1, True),
        }
        lines, _ = run_checkin(routes, ["genshin", "starrail"])

        self.assertIn("游戏社区签到汇总：成功 1，失败 1，跳过 0", lines)
        failed = next(line for line in lines if line.startswith("游戏社区失败项："))
        self.assertIn("原神(国际服) 请求异常", failed)
        self.assertFalse(notifier.is_task_success(lines))

    def test_reward_list_failure_does_not_block_the_sign_in(self) -> None:
        routes = {
            url(GENSHIN, "home"): ApiError("boom"),
            url(GENSHIN, "info"): signed(2, False),
            url(GENSHIN, "sign"): SIGN_OK,
        }
        lines, _ = run_checkin(routes, ["genshin"])

        self.assertIn("游戏社区成功项：原神(国际服) 未知", lines)

    def test_only_games_limits_the_run(self) -> None:
        routes = {**home(), url(GENSHIN, "info"): signed(1, True)}
        _, client = run_checkin(routes, ["genshin", "starrail"], only_games=["genshin"])

        self.assertFalse(any("hkrpg" in target for target in client.urls()))

    def test_account_without_a_cookie_fails_without_any_request(self) -> None:
        lines, client = run_checkin({}, ["genshin"], account={"cookie": ""})

        self.assertEqual([], client.calls)
        self.assertFalse(notifier.is_task_success(lines))

    def test_describe_award_clamps_the_index(self) -> None:
        self.assertEqual("「奖励1」x1", describe_award(AWARDS, -1))
        self.assertEqual("「奖励31」x31", describe_award(AWARDS, 99))
        self.assertEqual("未知", describe_award([], 0))

    def test_every_supported_game_is_a_known_game_with_a_complete_entry(self) -> None:
        for key, game in c.OS_GAMES.items():
            self.assertIn(key, c.GAMES)
            self.assertTrue(game["base_url"].startswith("https://") and "?" not in game["base_url"], key)
            self.assertTrue(game["act_id"] and game["signgame"], key)


class ProbeTest(unittest.TestCase):
    """登录时的在线校验只读一次 info，不签到。"""

    def probe(self, route: Any) -> tuple[str, FakeClient]:
        client = FakeClient({url(GENSHIN, "info"): route})
        return HoyolabCheckin(client, {}, {"cookie": COOKIE}).probe(), client

    def test_a_working_cookie_reports_ok(self) -> None:
        status, client = self.probe(ok({"total_sign_day": 1, "is_sign": True}))

        self.assertEqual("ok", status)
        self.assertEqual([url(GENSHIN, "info")], client.urls())

    def test_the_return_codes_are_classified(self) -> None:
        cases = ((-100, "invalid"), (10103, "invalid"), (-1073, "unbound"), (-5003, "unknown"), (-9999, "unknown"))
        for retcode, expected in cases:
            with self.subTest(retcode=retcode):
                status, _ = self.probe({"retcode": retcode, "message": "x"})
                self.assertEqual(expected, status)

    def test_a_network_error_is_unknown_rather_than_invalid(self) -> None:
        status, _ = self.probe(ApiError("boom"))

        self.assertEqual("unknown", status)


class ParseHoyolabCookieTest(unittest.TestCase):
    def test_extracts_the_uid_and_marks_the_account_overseas(self) -> None:
        data = parse_hoyolab_cookie(COOKIE)

        self.assertEqual({"cookie": COOKIE, "stuid": "12345", "stoken": "", "mid": "", "region": "os"}, data)

    def test_tidies_multi_line_and_loose_input(self) -> None:
        data = parse_hoyolab_cookie("  ltoken_v2=v2_abc;\r\nltuid_v2=12345 ;\n\n")

        self.assertEqual("ltoken_v2=v2_abc; ltuid_v2=12345", data["cookie"])
        self.assertEqual("12345", data["stuid"])

    def test_rejects_input_that_is_not_a_hoyolab_cookie(self) -> None:
        for raw, message in (
            ("", "请粘贴"),
            ("   \n ", "请粘贴"),
            ("ltoken_v2=v2_abc", "ltuid_v2"),
            ("ltuid_v2=12345", "ltoken_v2"),
            ("just some text", "没有识别到"),
            ("Host: www.hoyolab.com\nAccept: */*", "没有识别到"),
        ):
            with self.assertRaises(ValueError, msg=raw) as caught:
                parse_hoyolab_cookie(raw)
            self.assertIn(message, str(caught.exception), raw)

    def test_accepts_a_whole_cookie_header(self) -> None:
        data = parse_hoyolab_cookie(
            "Host: www.hoyolab.com\nCookie: ltuid_v2=12345; ltoken_v2=v2_abc; ltmid_v2=99\r\nAccept: */*"
        )

        self.assertEqual("ltuid_v2=12345; ltoken_v2=v2_abc; ltmid_v2=99", data["cookie"])
        self.assertEqual("12345", data["stuid"])

    def test_accepts_devtools_cookie_table_rows(self) -> None:
        raw = (
            "ltuid_v2\t12345\t.hoyolab.com\t/\t2027-01-01T00:00:00.000Z\t12\t✓\t✓\tLax\tMedium\n"
            "ltoken_v2\tv2_abc\t.hoyolab.com\t/\t2027-01-01T00:00:00.000Z\t60\t✓\t✓\tLax\tMedium"
        )

        data = parse_hoyolab_cookie(raw)

        self.assertEqual("ltuid_v2=12345; ltoken_v2=v2_abc", data["cookie"])

    def test_accepts_json_exports(self) -> None:
        listing = '[{"name": "ltuid_v2", "value": "12345"}, {"name": "ltoken_v2", "value": "v2_abc"}]'
        mapping = '{"ltuid_v2": "12345", "ltoken_v2": "v2_abc"}'

        for raw in (listing, mapping):
            with self.subTest(raw=raw):
                self.assertEqual("ltuid_v2=12345; ltoken_v2=v2_abc", parse_hoyolab_cookie(raw)["cookie"])

    def test_drops_quotes_and_keeps_unknown_cookies(self) -> None:
        data = parse_hoyolab_cookie('ltuid_v2="12345"; ltoken_v2=v2_abc; _ga=GA1.1.1')

        self.assertEqual('ltuid_v2=12345; ltoken_v2=v2_abc; _ga=GA1.1.1', data["cookie"])

    def test_a_repeated_name_keeps_the_last_value(self) -> None:
        data = parse_hoyolab_cookie("ltuid_v2=1; ltoken_v2=v2_old; ltoken_v2=v2_new")

        self.assertEqual("ltuid_v2=1; ltoken_v2=v2_new", data["cookie"])

    def test_set_cookie_attributes_are_not_kept_as_cookies(self) -> None:
        data = parse_hoyolab_cookie(
            "ltuid_v2=12345; Path=/; Domain=.hoyolab.com; Expires=Wed, 01 Jan 2027 00:00:00 GMT; "
            "Secure; HttpOnly; SameSite=Lax; ltoken_v2=v2_abc"
        )

        self.assertEqual("ltuid_v2=12345; ltoken_v2=v2_abc", data["cookie"])


class RegionConfigTest(unittest.TestCase):
    def make(self, accounts: list[dict[str, Any]]) -> dict[str, Any]:
        config: dict[str, Any] = {"accounts": copy.deepcopy(accounts)}
        normalize_config(config)
        return config

    def test_existing_accounts_default_to_cn(self) -> None:
        config = self.make([{"name": "旧账号", "stuid": "1"}, {"name": "怪值", "region": "EU"}])

        self.assertEqual(["cn", "cn"], [account["region"] for account in config["accounts"]])

    def test_overseas_uid_is_derived_from_the_cookie_only_when_missing(self) -> None:
        config = self.make(
            [
                {"name": "a", "region": "os", "cookie": COOKIE},
                {"name": "b", "region": "os", "cookie": COOKIE, "stuid": "999"},
                {"name": "c", "region": "cn", "cookie": COOKIE},
            ]
        )

        self.assertEqual(["12345", "999", ""], [account["stuid"] for account in config["accounts"]])

    def test_same_uid_is_allowed_across_regions_but_not_within_one(self) -> None:
        validate_unique_account_uids(self.make([{"stuid": "1"}, {"stuid": "1", "region": "os"}]))

        with self.assertRaises(ValueError):
            validate_unique_account_uids(self.make([{"stuid": "1", "region": "os"}, {"stuid": "1", "region": "os"}]))
        with self.assertRaises(ValueError):
            validate_unique_account_uids(self.make([{"stuid": "1"}, {"stuid": "1"}]))

    def test_upsert_checks_duplicates_within_the_same_region_only(self) -> None:
        config = self.make([{"name": "os", "stuid": "1", "region": "os"}])

        upsert_account(config, "cn", {"stuid": "1"})
        with self.assertRaises(ValueError):
            upsert_account(config, "os2", {"stuid": "1", "region": "os"})

    def test_shop_plans_never_bind_to_an_overseas_account(self) -> None:
        config = self.make([{"name": "os", "stuid": "7", "region": "os"}, {"name": "cn", "stuid": "7"}])

        self.assertEqual(1, find_account_index_by_stuid(config["accounts"], "7"))
        config["shop_exchange"]["plans"] = [
            {"goods_id": "g", "account_index": 0, "account_stuid": "", "exchange_at": 1, "device_fp": "fp"}
        ]
        bind_shop_plan_accounts(config)
        self.assertEqual("", config["shop_exchange"]["plans"][0]["account_stuid"])

    def test_region_is_public_while_the_cookie_stays_in_the_credentials_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "config.yaml"
            config = self.make([{"name": "os", "region": "os", "cookie": COOKIE}])
            save_config(path, config)

            public = yaml.safe_load(path.read_text(encoding="utf-8"))
            account = public["accounts"][0]
            self.assertEqual("os", account["region"])
            self.assertNotIn("cookie", account)
            self.assertNotIn("ltoken_v2", path.read_text(encoding="utf-8"))

            loaded = load_config(path)
            self.assertEqual(("os", COOKIE, "12345"), tuple(loaded["accounts"][0][k] for k in ("region", "cookie", "stuid")))


class RunnerDispatchTest(unittest.TestCase):
    def run_all(self, features: dict[str, bool], **kwargs: Any) -> tuple[list[str], list[tuple[str, str]]]:
        ran: list[tuple[str, str]] = []

        def fake(stage: str):
            class Stage:
                def __init__(self, client: Any, config: Any, account: Any, emit: Any = None) -> None:
                    self.account = account

                def run(self, **_: Any) -> list[str]:
                    ran.append((stage, self.account["name"]))
                    return [f"{stage}:{self.account['name']}"]

            return Stage

        config = {
            "enable": True,
            "accounts": [{"name": "国服号"}, {"name": "国际服号", "region": "os"}],
            "features": features,
        }
        with patch.object(runner, "GameCheckin", fake("cn-game")), \
                patch.object(runner, "CloudGameCheckin", fake("cn-cloud")), \
                patch.object(runner, "BbsTasks", fake("cn-bbs")), \
                patch.object(runner, "HoyolabCheckin", fake("os-game")), \
                patch.object(runner, "save_config"):
            output = runner.run_tasks(config, "cfg.json", **kwargs)
        return output, ran

    def test_each_account_runs_the_implementation_of_its_own_region(self) -> None:
        output, ran = self.run_all({"game_checkin": True, "cloud_game_checkin": True, "bbs_tasks": True})

        self.assertEqual(
            [("cn-game", "国服号"), ("cn-cloud", "国服号"), ("cn-bbs", "国服号"), ("os-game", "国际服号")],
            ran,
        )
        self.assertIn("# 账号 1/2: 国服号", output)
        self.assertIn("# 账号 2/2: 国际服号（国际服）", output)

    def test_unsupported_stages_are_reported_once_instead_of_silently_dropped(self) -> None:
        output, _ = self.run_all({"game_checkin": True, "cloud_game_checkin": True, "bbs_tasks": True})

        self.assertEqual(["国际服账号暂不支持云游戏签到、米游币任务，已跳过"], [line for line in output if "暂不支持" in line])

    def test_no_notice_when_the_unsupported_features_are_off(self) -> None:
        output, ran = self.run_all({"game_checkin": True, "cloud_game_checkin": False, "bbs_tasks": False})

        self.assertFalse(any("暂不支持" in line for line in output))
        self.assertIn(("os-game", "国际服号"), ran)

    def test_bbs_only_does_nothing_for_an_overseas_account(self) -> None:
        output, ran = self.run_all({"game_checkin": True, "bbs_tasks": True}, bbs_only=True)

        self.assertEqual([("cn-bbs", "国服号")], ran)
        self.assertTrue(any("暂不支持米游币任务" in line for line in output))

    def test_games_only_skips_the_bbs_notice(self) -> None:
        output, _ = self.run_all({"game_checkin": True, "bbs_tasks": True}, games_only=True)

        self.assertFalse(any("暂不支持" in line for line in output))


class WebCookieLoginTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.logged: list[str] = []
        app = web.WebApp.__new__(web.WebApp)
        app.lock = threading.RLock()
        app.config_path = pathlib.Path(self.directory.name) / "config.yaml"
        app.config = {"accounts": [{"name": "国服号", "stuid": "12345", "cookie": "cn-cookie"}]}
        normalize_config(app.config)
        app.log_file = None
        app.login_state = {}
        app.scheduler = MagicMock()
        app.exchange_scheduler = MagicMock()
        app.log = lambda message, component="web": self.logged.append(message)
        self.app = app
        patcher = patch.object(web, "configure_logger")
        patcher.start()
        self.addCleanup(patcher.stop)
        probe = patch.object(web, "probe_hoyolab_cookie", return_value="ok")
        self.probe = probe.start()
        self.addCleanup(probe.stop)

    def test_draft_login_returns_the_account_data_without_saving(self) -> None:
        result = self.app.complete_login_cookie(1, COOKIE, {"name": "海外", "region": "os"}, draft=True)

        self.assertTrue(result["draft"])
        self.assertEqual("12345", result["account_data"]["stuid"])
        self.assertEqual("os", result["account_data"]["region"])
        self.assertEqual(1, len(self.app.config["accounts"]))
        self.assertFalse(self.app.config_path.exists())

    def test_login_for_a_saved_account_persists_it(self) -> None:
        self.app.config["accounts"].append({"name": "海外", "region": "os", "stuid": "", "cookie": ""})

        result = self.app.complete_login_cookie(1, COOKIE)

        self.assertFalse(result["draft"])
        saved = self.app.config["accounts"][1]
        self.assertEqual(("os", "12345", COOKIE), (saved["region"], saved["stuid"], saved["cookie"]))
        self.assertEqual("海外", saved["name"])
        self.assertTrue(self.app.config_path.exists())
        self.app.scheduler.reload.assert_called_once()

    def test_same_uid_as_a_cn_account_is_not_a_duplicate(self) -> None:
        # 国服号的 stuid 也是 12345，两边是不同的账号体系
        result = self.app.complete_login_cookie(1, COOKIE, {"region": "os"}, draft=True)

        self.assertEqual("12345", result["account_data"]["stuid"])

    def test_same_uid_twice_within_overseas_is_rejected(self) -> None:
        self.app.config["accounts"].append({"name": "海外", "region": "os", "stuid": "12345", "cookie": COOKIE})

        with self.assertRaises(ValueError):
            self.app.complete_login_cookie(2, COOKIE, {"region": "os"}, draft=True)

    def test_cn_account_cannot_take_a_hoyolab_cookie(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self.app.complete_login_cookie(0, COOKIE)

        self.assertIn("国服", str(caught.exception))
        self.assertEqual("cn-cookie", self.app.config["accounts"][0]["cookie"])

    def test_overseas_account_cannot_use_the_cn_login_flows(self) -> None:
        self.app.config["accounts"].append({"name": "海外", "region": "os"})

        with self.assertRaises(ValueError):
            self.app.start_login(1, 60)
        with self.assertRaises(ValueError):
            self.app.send_login_captcha(1, "13800138000")
        with self.assertRaises(ValueError):
            self.app.complete_login_captcha(1, "13800138000", "1234", "login")

    def test_malformed_cookie_is_rejected_before_touching_the_account(self) -> None:
        with self.assertRaises(ValueError):
            self.app.complete_login_cookie(1, "ltuid_v2=1", {"region": "os"}, draft=True)

    def test_an_invalid_cookie_is_rejected_before_the_account_is_touched(self) -> None:
        self.probe.return_value = "invalid"
        self.app.config["accounts"].append({"name": "海外", "region": "os", "stuid": "", "cookie": ""})

        with self.assertRaises(ValueError) as caught:
            self.app.complete_login_cookie(1, COOKIE)

        self.assertIn("无效", str(caught.exception))
        self.assertEqual("", self.app.config["accounts"][1]["cookie"])
        self.assertFalse(self.app.config_path.exists())
        self.probe.assert_called_once()

    def test_the_probe_sees_the_normalized_cookie(self) -> None:
        self.app.config["accounts"].append({"name": "海外", "region": "os", "stuid": "", "cookie": ""})

        self.app.complete_login_cookie(1, f"Cookie: {COOKIE}")

        self.assertEqual(COOKIE, self.probe.call_args.args[0])

    def test_a_cookie_that_cannot_be_checked_is_still_saved_with_a_note(self) -> None:
        self.probe.return_value = "unknown"
        self.app.config["accounts"].append({"name": "海外", "region": "os", "stuid": "", "cookie": ""})

        result = self.app.complete_login_cookie(1, COOKIE)

        self.assertIn("暂时无法在线校验", result["message"])
        self.assertEqual(COOKIE, self.app.config["accounts"][1]["cookie"])

    def test_shop_exchange_refuses_overseas_accounts(self) -> None:
        self.app.config["accounts"].append({"name": "海外", "region": "os", "stuid": "9", "cookie": COOKIE})

        with self.assertRaises(ValueError) as caught:
            self.app._account_by_index(1)
        self.assertIn("国服", str(caught.exception))
        self.assertEqual("国服号", self.app._account_by_index(0)["name"])


if __name__ == "__main__":
    unittest.main()
