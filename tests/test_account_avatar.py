# -*- coding: utf-8 -*-

import threading
import unittest
from unittest.mock import MagicMock, patch

from miyouqian import constants as c
from miyouqian.core.http import ApiError
from miyouqian.core.profile import fetch_avatar_url, fetch_os_avatar_url, safe_avatar_url
from miyouqian.service import web

GOOD = "https://bbs-static.miyoushe.com/avatar/avatar10013.png"
HOYOLAB_GOOD = "https://upload-os-bbs.hoyolab.com/upload/2023/11/22/a.png?x-oss-process=image%2Fformat%2Cwebp"


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.data


class SafeAvatarUrlTest(unittest.TestCase):
    def test_official_https_image_hosts_are_allowed(self):
        self.assertEqual(safe_avatar_url(GOOD), GOOD)
        self.assertEqual(
            safe_avatar_url("https://img-static.mihoyo.com/communityweb/avatar/avatar10013.png"),
            "https://img-static.mihoyo.com/communityweb/avatar/avatar10013.png",
        )
        self.assertEqual(safe_avatar_url(HOYOLAB_GOOD), HOYOLAB_GOOD)

    def test_anything_else_is_dropped(self):
        for url in (
            "",
            None,
            "http://bbs-static.miyoushe.com/a.png",
            "https://evil.example.com/a.png",
            "https://evilmiyoushe.com/a.png",
            "https://miyoushe.com.evil.example.com/a.png",
            "https://hoyolab.com.evil.example.com/a.png",
            "https://example.com/?x=.miyoushe.com",
            "//bbs-static.miyoushe.com/a.png",
            "javascript:alert(1)",
            "data:image/png;base64,AAAA",
        ):
            self.assertEqual(safe_avatar_url(url), "", url)


class FetchAvatarUrlTest(unittest.TestCase):
    def test_asks_the_public_profile_api_by_uid(self):
        client = FakeClient({"retcode": 0, "data": {"user_info": {"avatar_url": GOOD}}})
        self.assertEqual(fetch_avatar_url(client, "75379477"), GOOD)
        url, kwargs = client.calls[0]
        self.assertEqual(url, c.BBS_USER_INFO_URL)
        self.assertEqual(kwargs["params"]["uid"], "75379477")
        # 公开接口，不能把账号的 stoken / cookie 带出去
        self.assertFalse({"cookie", "Cookie", "DS"} & set(kwargs["headers"]))

    def test_api_error_is_raised_instead_of_returning_an_empty_avatar(self):
        client = FakeClient({"retcode": -20001, "message": "用户不存在"})
        with self.assertRaises(ApiError):
            fetch_avatar_url(client, "1")

    def test_a_missing_or_untrusted_avatar_is_an_empty_string(self):
        self.assertEqual(fetch_avatar_url(FakeClient({"retcode": 0, "data": {}}), "1"), "")
        untrusted = {"retcode": 0, "data": {"user_info": {"avatar_url": "https://evil.example.com/a.png"}}}
        self.assertEqual(fetch_avatar_url(FakeClient(untrusted), "1"), "")


class FetchOsAvatarUrlTest(unittest.TestCase):
    def test_asks_the_hoyolab_profile_api_by_uid(self):
        client = FakeClient({"retcode": 0, "data": {"user_info": {"avatar_url": HOYOLAB_GOOD}}})

        self.assertEqual(fetch_os_avatar_url(client, "2002"), HOYOLAB_GOOD)
        url, kwargs = client.calls[0]
        self.assertEqual(url, c.OS_USER_INFO_URL)
        self.assertEqual(kwargs["params"]["uid"], "2002")
        # 公开接口，不能把账号的 cookie 带出去
        self.assertFalse({"cookie", "Cookie", "DS"} & set(kwargs["headers"]))

    def test_api_error_is_raised_like_the_cn_one(self):
        with self.assertRaises(ApiError):
            fetch_os_avatar_url(FakeClient({"retcode": -1, "message": "x"}), "1")


class WebAppAccountAvatarsTest(unittest.TestCase):
    def setUp(self):
        self.logged = []
        app = web.WebApp.__new__(web.WebApp)
        app.lock = threading.RLock()
        app._avatar_cache = {}
        app.log = lambda message, component="web": self.logged.append(message)
        self.app = app

        patches = [
            patch.object(web, "ApiClient", MagicMock()),
            patch.object(web, "fetch_avatar_url"),
            patch.object(web, "fetch_os_avatar_url"),
            patch.object(web, "time"),
        ]
        self.fetch = patches[1].start()
        self.fetch_os = patches[2].start()
        self.time = patches[3].start()
        patches[0].start()
        for item in patches:
            self.addCleanup(item.stop)
        self.time.monotonic.return_value = 1000.0
        self.fetch.side_effect = lambda client, uid: f"https://bbs-static.miyoushe.com/avatar/{uid}.png"
        self.fetch_os.side_effect = lambda client, uid: f"https://upload-os-bbs.hoyolab.com/avatar/{uid}.png"

    def fetched(self):
        # 并发查询，调用顺序不固定
        return sorted(call.args[1] for call in self.fetch.call_args_list)

    def test_only_valid_uids_are_looked_up_once_each(self):
        result = self.app.account_avatars(["12", "12", "abc", "", "１２", "9" * 30, "34"])
        self.assertEqual(self.fetched(), ["12", "34"])
        self.assertEqual(set(result["avatars"]), {"12", "34"})

    def test_at_most_twenty_accounts_are_looked_up(self):
        self.app.account_avatars([str(i) for i in range(1, 40)])
        self.assertEqual(len(self.fetched()), web.AVATAR_MAX_UIDS)

    def test_a_cached_avatar_is_not_requested_again_until_it_expires(self):
        self.app.account_avatars(["12"])
        self.time.monotonic.return_value = 1000.0 + web.AVATAR_CACHE_SECONDS - 1
        self.assertEqual(self.app.account_avatars(["12"])["avatars"], {"12": "https://bbs-static.miyoushe.com/avatar/12.png"})
        self.assertEqual(self.fetched(), ["12"])
        self.time.monotonic.return_value = 1000.0 + web.AVATAR_CACHE_SECONDS + 1
        self.app.account_avatars(["12"])
        self.assertEqual(self.fetched(), ["12", "12"])

    def test_a_failed_lookup_is_left_out_and_retried_only_after_a_short_wait(self):
        self.fetch.side_effect = ApiError("网络请求失败")
        result = self.app.account_avatars(["12"])
        self.assertEqual(result, {"avatars": {}})
        self.assertEqual(len(self.logged), 1)

        self.time.monotonic.return_value = 1000.0 + web.AVATAR_RETRY_SECONDS - 1
        self.app.account_avatars(["12"])
        self.assertEqual(self.fetched(), ["12"])

        self.fetch.side_effect = lambda client, uid: GOOD
        self.time.monotonic.return_value = 1000.0 + web.AVATAR_RETRY_SECONDS + 1
        self.assertEqual(self.app.account_avatars(["12"]), {"avatars": {"12": GOOD}})

    def test_one_failing_account_does_not_hide_the_others(self):
        def flaky(client, uid):
            if uid == "12":
                raise ApiError("boom")
            return GOOD

        self.fetch.side_effect = flaky
        self.assertEqual(self.app.account_avatars(["12", "34"]), {"avatars": {"34": GOOD}})

    def test_lookups_run_side_by_side_so_a_slow_network_does_not_add_up(self):
        barrier = threading.Barrier(2, timeout=5)

        def meet(client, uid):
            barrier.wait()  # 两个请求必须同时在途，串行的话这里会超时
            return GOOD

        self.fetch.side_effect = meet
        self.assertEqual(set(self.app.account_avatars(["12", "34"])["avatars"]), {"12", "34"})

    def test_an_account_without_an_avatar_is_left_out(self):
        self.fetch.side_effect = lambda client, uid: ""
        self.assertEqual(self.app.account_avatars(["12"]), {"avatars": {}})

    def test_overseas_keys_use_the_hoyolab_profile_api(self):
        result = self.app.account_avatars(["os:12", "34"])

        self.assertEqual(["12"], [call.args[1] for call in self.fetch_os.call_args_list])
        self.assertEqual(["34"], self.fetched())
        self.assertEqual(
            {
                "os:12": "https://upload-os-bbs.hoyolab.com/avatar/12.png",
                "34": "https://bbs-static.miyoushe.com/avatar/34.png",
            },
            result["avatars"],
        )

    def test_the_same_uid_on_both_servers_gets_two_avatars(self):
        result = self.app.account_avatars(["12", "os:12"])

        self.assertEqual(
            {
                "12": "https://bbs-static.miyoushe.com/avatar/12.png",
                "os:12": "https://upload-os-bbs.hoyolab.com/avatar/12.png",
            },
            result["avatars"],
        )

    def test_a_failing_overseas_lookup_does_not_disturb_the_cn_one(self):
        self.fetch_os.side_effect = ApiError("boom")
        self.assertEqual(self.app.account_avatars(["12", "os:12"]), {"avatars": {"12": "https://bbs-static.miyoushe.com/avatar/12.png"}})

    def test_avatar_keys_are_normalized(self):
        self.assertEqual("12", web.parse_avatar_key(" 12 "))
        self.assertEqual("os:12", web.parse_avatar_key("os:12"))
        for key in ("os:", "os:abc", "xx:12", ":12", "os:" + "9" * 30, ""):
            self.assertEqual("", web.parse_avatar_key(key), key)


if __name__ == "__main__":
    unittest.main()
