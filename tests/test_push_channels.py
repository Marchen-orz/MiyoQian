# -*- coding: utf-8 -*-

import threading
import unittest
from unittest.mock import Mock, patch

import httpx

from miyouqian.core.config import normalize_push_channels
from miyouqian.service import notifier


class ServerChanUrlTest(unittest.TestCase):
    """Server酱³ 的地址拼装：uid 可以留空（从 SendKey 的 sctp{uid}t 前缀解析）。"""

    def test_uid_is_parsed_from_sendkey(self):
        url = notifier.serverchan_url({"sendkey": "sctp1234tAbCdEfGh"})
        self.assertEqual(url, "https://1234.push.ft07.com/send/sctp1234tAbCdEfGh.send")

    def test_explicit_uid_wins(self):
        url = notifier.serverchan_url({"sendkey": "sctp99tXYZ", "uid": "777"})
        self.assertEqual(url, "https://777.push.ft07.com/send/sctp99tXYZ.send")

    def test_blank_input_is_rejected(self):
        with self.assertRaises(ValueError):
            notifier.serverchan_url({})

    def test_unparsable_sendkey_is_rejected(self):
        with self.assertRaises(ValueError):
            notifier.serverchan_url({"sendkey": "no-uid-prefix"})

    def test_surrounding_whitespace_is_trimmed(self):
        url = notifier.serverchan_url({"sendkey": "  sctp5tK  ", "uid": " 5 "})
        self.assertEqual(url, "https://5.push.ft07.com/send/sctp5tK.send")

    def test_non_numeric_uid_cannot_redirect_the_request(self):
        # uid 会被拼进主机名，必须是纯数字，否则请求可能被发往其他域名
        for uid in ("evil.com/#", "1.evil.com", "1@evil.com", "１２３", "-1"):
            with self.subTest(uid=uid):
                with self.assertRaises(ValueError):
                    notifier.serverchan_url({"sendkey": "sctp1tA", "uid": uid})


class ServerChanSendTest(unittest.TestCase):
    def _client(self, payload, status_code=200):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = payload
        client = Mock()
        client.post.return_value = response
        return client, response

    def test_success_sends_title_and_markdown(self):
        client, response = self._client({"code": 0, "message": ""})
        notifier.serverchan_send(client, {"sendkey": "sctp1tA"}, "标题", "# 正文")
        response.raise_for_status.assert_called_once()
        args, kwargs = client.post.call_args
        self.assertEqual(args[0], "https://1.push.ft07.com/send/sctp1tA.send")
        self.assertEqual(kwargs["json"], {"title": "标题", "desp": "# 正文"})

    def test_business_error_is_raised(self):
        # Server酱 把业务错误放在 HTTP 200 的 code 字段里，不能只看状态码
        client, _ = self._client({"code": 40001, "message": "bad sendkey"})
        with self.assertRaises(ValueError) as ctx:
            notifier.serverchan_send(client, {"sendkey": "sctp1tA"}, "标题", "正文")
        self.assertIn("bad sendkey", str(ctx.exception))

    def test_non_json_response_does_not_raise(self):
        client, response = self._client(None)
        response.json.side_effect = ValueError("not json")
        notifier.serverchan_send(client, {"sendkey": "sctp1tA"}, "标题", "正文")

    def test_http_error_does_not_leak_sendkey(self):
        # httpx 的 HTTPStatusError 文本带完整 URL，而 URL 里就是 SendKey
        sendkey = "sctp1tSECRETKEY"
        request = httpx.Request("POST", f"https://1.push.ft07.com/send/{sendkey}.send")
        client = Mock()
        client.post.return_value = httpx.Response(403, request=request)
        with self.assertRaises(Exception) as ctx:
            notifier.serverchan_send(client, {"sendkey": sendkey}, "标题", "正文")
        self.assertNotIn(sendkey, str(ctx.exception))
        self.assertIn("403", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)


class ServerChanRoutingTest(unittest.TestCase):
    def setUp(self):
        self.send = self.enterContext(patch.object(notifier, "serverchan_send"))
        self.client = Mock()
        self.channel = {"sendkey": "sctp1tA"}

    def test_task_push_uses_serverchan(self):
        notifier._send(self.client, "serverchan", self.channel, "标题", "日志", True)
        self.send.assert_called_once_with(
            self.client, self.channel, "标题", notifier.build_push_markdown("标题", "日志", True),
        )

    def test_exchange_push_uses_serverchan(self):
        with patch.object(notifier, "build_exchange_markdown", return_value="**兑换**"):
            notifier._send_exchange(self.client, "serverchan", self.channel, "标题", "商品", {}, {}, True)
        self.send.assert_called_once_with(self.client, self.channel, "标题", "**兑换**")


class PushPlusTest(unittest.TestCase):
    """pushplus 内容过大等业务错误仍是 HTTP 200，必须看 code 字段才能判断成败。"""

    def _client(self, payload, status_code=200):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = payload
        response.raise_for_status = Mock()
        client = Mock()
        client.request.return_value = response
        return client, response

    def test_success_does_not_raise(self):
        client, _ = self._client({"code": 200, "msg": "success", "data": "请求成功"})
        notifier.request_pushplus(client, "https://www.pushplus.plus/send", {"token": "t"})

    def test_business_error_is_raised_even_though_http_status_is_200(self):
        client, _ = self._client({"code": 999, "msg": "服务端验证错误", "data": "发送内容过大，不能超过2万字"})
        with self.assertRaises(ValueError) as ctx:
            notifier.request_pushplus(client, "https://www.pushplus.plus/send", {"token": "t"})
        self.assertIn("发送内容过大", str(ctx.exception))

    def test_non_json_response_does_not_raise(self):
        client, response = self._client(None)
        response.json.side_effect = ValueError("not json")
        notifier.request_pushplus(client, "https://www.pushplus.plus/send", {"token": "t"})

    def test_html_too_large_falls_back_to_markdown(self):
        # html 版本因为过大被拒绝后，_send 应该改用更紧凑的 markdown 重试，而不是直接报失败
        oversized = self._client({"code": 999, "msg": "服务端验证错误", "data": "发送内容过大，不能超过2万字"})[1]
        ok = self._client({"code": 200, "msg": "success", "data": "请求成功"})[1]
        client = Mock()
        client.request.side_effect = [oversized, ok]
        notifier._send(client, "pushplus", {"token": "t"}, "标题", "日志", True)
        self.assertEqual(client.request.call_count, 2)
        self.assertEqual(client.request.call_args_list[1].kwargs["json"]["template"], "markdown")


class NormalizeMessageLinesTest(unittest.TestCase):
    """推送内容里的「正在...」只是进度提示，紧跟的结果行已经说明成败，应该在推送里省掉。"""

    def test_progress_only_lines_are_dropped(self):
        message = "\n".join(
            [
                "# 账号 1/1: 账号1",
                "正在浏览: 帖子A",
                "阅读成功: 帖子A",
                "正在点赞: 帖子A",
                "点赞成功: 帖子A",
            ]
        )
        self.assertEqual(
            notifier.normalize_message_lines(message),
            ["# 账号 1/1: 账号1", "阅读成功: 帖子A", "点赞成功: 帖子A"],
        )

    def test_result_lines_and_blank_lines_are_kept(self):
        message = "正在签到\n\n签到成功，奖励 60原石\n"
        self.assertEqual(notifier.normalize_message_lines(message), ["签到成功，奖励 60原石"])


class TaskProgressStatusTest(unittest.TestCase):
    """推送里游戏签到/米游币任务的进度条：重试后成功不算失败，只有真失败才变红。"""

    GAME_RETRY_THEN_SUCCESS = [
        "# 账号 1/1: 沐晨",
        "游戏社区签到触发验证码，正在调用自定义接口识别(1/3)",
        "游戏社区签到验证码识别失败，准备重新获取验证码",
        "游戏社区签到触发验证码，正在调用自定义接口识别(2/3)",
        "游戏社区签到验证码提交失败，准备重新获取验证码",
        "游戏社区签到触发验证码，正在调用自定义接口识别(3/3)",
        "游戏社区签到验证码已处理，正在重试签到",
        "沐晨(100) 签到成功，奖励 「原石」x60",
        "游戏社区签到汇总：成功 1，失败 0，跳过 0",
        "游戏社区成功项：原神 「原石」x60",
    ]

    def test_real_failure_is_labeled_failed_even_if_others_succeeded(self) -> None:
        status = notifier.summarize_attempts(done=1, failed=2, total=3)
        self.assertEqual("失败 2", status["label"])
        self.assertEqual("#b83b4b", status["color"])
        self.assertEqual(33, status["done_percent"])
        self.assertEqual(67, status["failed_percent"])

    def test_total_failure_is_labeled_failed(self) -> None:
        status = notifier.summarize_attempts(done=0, failed=3, total=3)
        self.assertEqual("失败 3", status["label"])
        self.assertEqual("#b83b4b", status["color"])
        self.assertEqual(100, status["failed_percent"])

    def test_failed_retries_before_success_still_count_as_done(self) -> None:
        # 3 次尝试 2 次失败 1 次成功：整体是「完成」（蓝），进度条前 2/3 红、后 1/3 蓝。
        status = notifier.summarize_attempts(done=1, failed=0, total=1, failed_marks=2)
        self.assertEqual("完成", status["label"])
        self.assertEqual("#168df5", status["color"])
        self.assertEqual(67, status["failed_percent"])
        self.assertEqual(33, status["done_percent"])

    def test_not_all_attempts_made_is_partial_and_nothing_made_is_not_executed(self) -> None:
        self.assertEqual("部分完成", notifier.summarize_attempts(done=1, failed=0, total=3)["label"])
        self.assertEqual("未执行", notifier.summarize_attempts(done=0, failed=0, total=3)["label"])

    def test_skipped_items_do_not_make_the_result_partial(self) -> None:
        result = notifier.build_result_summary("游戏签到汇总：成功 2，失败 0，跳过 1", [], [], True)
        self.assertEqual("完成", result["label"])
        self.assertEqual(100, result["done_percent"])
        self.assertEqual(0, result["failed_percent"])

    def test_failed_marks_cover_retries_but_not_first_try_success(self) -> None:
        # 参数依次是：最终失败项数、其中触发验证码的项数、验证码尝试次数、触发验证码的项目数
        self.assertEqual(2, notifier.count_failed_marks(0, 0, 3, 1))  # 失败 2 次后成功
        self.assertEqual(3, notifier.count_failed_marks(1, 1, 3, 1))  # 3 次都失败
        self.assertEqual(0, notifier.count_failed_marks(0, 0, 1, 1))  # 一次就过
        self.assertEqual(1, notifier.count_failed_marks(1, 0, 0, 0))  # 没有验证码，普通失败
        self.assertEqual(2, notifier.count_failed_marks(1, 0, 2, 1))  # 1 个普通失败 + 另一项失败 1 次后成功

    def test_captcha_attempts_are_scoped_to_their_own_scene(self) -> None:
        lines = [
            "游戏社区签到触发验证码，正在调用打码狗识别(1/3)",
            "社区签到触发验证码，正在调用打码狗识别(1/3)",
            "社区签到触发验证码，正在调用打码狗识别(2/3)",
            "点赞触发验证码，正在调用打码狗识别(1/3)",
        ]
        self.assertEqual((1, 1), notifier.count_captcha_attempts(lines, "游戏社区签到"))
        self.assertEqual((2, 1), notifier.count_captcha_attempts(lines, "社区签到"))
        self.assertEqual((1, 1), notifier.count_captcha_attempts(lines, "点赞"))

    def test_game_retry_then_success_is_done_with_red_before_blue(self) -> None:
        game = notifier.build_structured_summary(self.GAME_RETRY_THEN_SUCCESS, True)["sections"][0]["game"]
        self.assertEqual(0, game["failed"])
        self.assertEqual("完成", game["label"])
        self.assertEqual("#168df5", game["color"])
        self.assertEqual(67, game["failed_percent"])
        self.assertEqual(33, game["done_percent"])
        self.assertTrue(notifier.is_task_success(self.GAME_RETRY_THEN_SUCCESS))

    def test_game_captcha_failing_every_attempt_is_all_red(self) -> None:
        lines = [
            "# 账号 1/1: 沐晨",
            "游戏社区签到触发验证码，正在调用自定义接口识别(1/3)",
            "游戏社区签到验证码识别失败，准备重新获取验证码",
            "游戏社区签到触发验证码，正在调用自定义接口识别(2/3)",
            "游戏社区签到验证码识别失败，准备重新获取验证码",
            "游戏社区签到触发验证码，正在调用自定义接口识别(3/3)",
            "游戏社区签到验证码识别失败，准备重新获取验证码",
            "沐晨(100) 验证码处理后仍失败: 出错了(1034)",
            "游戏社区签到汇总：成功 0，失败 1，跳过 0",
            "游戏社区失败项：原神 触发验证码",
        ]
        game = notifier.build_structured_summary(lines, False)["sections"][0]["game"]
        self.assertEqual("失败 1", game["label"])
        self.assertEqual("#b83b4b", game["color"])
        self.assertEqual(100, game["failed_percent"])
        self.assertEqual(0, game["done_percent"])
        self.assertFalse(notifier.is_task_success(lines))

    def test_bbs_like_retry_then_success_is_done_with_half_red(self) -> None:
        lines = [
            "# 账号 1/1: 沐晨",
            "点赞触发验证码，正在调用打码狗识别(1/3)",
            "点赞验证码提交失败，准备重新获取验证码",
            "点赞触发验证码，正在调用打码狗识别(2/3)",
            "点赞成功: 帖子 A",
            "米游币成功项：点赞 帖子 A",
            "米游币任务汇总：成功 1，失败 0，跳过 0，今日总共可获得 10，实际已获得 10，本次新增 10",
        ]
        like = notifier.build_structured_summary(lines, True)["sections"][0]["bbs"]["tasks"][2]
        self.assertEqual("完成", like["label"])
        self.assertEqual((1, 1, 0), (like["done"], like["total"], like["failed"]))
        self.assertEqual(50, like["failed_percent"])
        self.assertEqual(50, like["done_percent"])

    def test_html_progress_bar_puts_red_before_blue(self) -> None:
        bar = notifier.segmented_progress_html(33, 67, "完成", "#168df5")
        self.assertIn("#b83b4b 0 67%", bar)
        self.assertIn("#168df5 67% 100%", bar)
        self.assertLess(bar.index("#b83b4b"), bar.index("#168df5 67%"))

    def test_html_progress_bar_caps_overflow_from_rounding(self) -> None:
        bar = notifier.segmented_progress_html(70, 40, "失败 1", "#b83b4b")
        self.assertIn("#b83b4b 0 40%", bar)
        self.assertIn("#168df5 40% 100%", bar)

    def test_text_progress_bar_puts_x_before_hash(self) -> None:
        self.assertEqual("[xxxxxxx###] 33%", notifier.segmented_text_bar(33, 67))

    def test_text_progress_bar_keeps_a_tiny_segment_visible(self) -> None:
        self.assertEqual("[x#########] 96%", notifier.segmented_text_bar(96, 4))
        self.assertEqual("[#---------] 4%", notifier.segmented_text_bar(4, 0))
        self.assertEqual("[----------] 0%", notifier.segmented_text_bar(0, 0))

    def test_rendered_push_shows_retry_then_success_as_completed(self) -> None:
        message = "\n".join(self.GAME_RETRY_THEN_SUCCESS)
        html_body = notifier.build_push_html("米游签任务完成", message, True)
        self.assertLess(html_body.index("#b83b4b 0 67%"), html_body.index("#168df5 67% 100%"))
        markdown = notifier.build_push_markdown("米游签任务完成", message, True)
        self.assertIn("[xxxxxxx###] 33% 完成", markdown)
        self.assertNotIn("失败 1", markdown)

    def test_push_title_reflects_failure_instead_of_always_saying_completed(self) -> None:
        lines = [
            "# 账号 1/1: 沐晨",
            "游戏签到汇总：成功 2，失败 1，跳过 0",
            "游戏失败项：原神 触发验证码",
        ]
        with patch.object(notifier, "send_push", return_value="sent") as send_push:
            notifier.send_task_push({"push": {"enable": True}}, lines)
        self.assertEqual("米游签任务失败", send_push.call_args.args[1])
        self.assertFalse(send_push.call_args.kwargs["success"])

    def test_push_title_stays_completed_when_failed_attempts_ended_in_success(self) -> None:
        with patch.object(notifier, "send_push", return_value="sent") as send_push:
            notifier.send_task_push({"push": {"enable": True}}, self.GAME_RETRY_THEN_SUCCESS)
        self.assertEqual("米游签任务完成", send_push.call_args.args[1])
        self.assertTrue(send_push.call_args.kwargs["success"])


class PushChannelConfigTest(unittest.TestCase):
    def test_serverchan_fields_are_normalized(self):
        channels = normalize_push_channels(
            {"channels": [{"provider": "serverchan", "enable": True, "sendkey": "sctp1tA", "uid": "1"}]}
        )
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]["provider"], "serverchan")
        self.assertEqual(channels[0]["sendkey"], "sctp1tA")
        self.assertEqual(channels[0]["uid"], "1")

    def test_disabled_channel_with_sendkey_is_kept(self):
        channels = normalize_push_channels(
            {"channels": [{"provider": "serverchan", "enable": False, "sendkey": "sctp1tA"}]}
        )
        self.assertEqual(len(channels), 1)
        self.assertIs(channels[0]["enable"], False)

    def test_disabled_empty_channel_is_dropped(self):
        channels = normalize_push_channels({"channels": [{"provider": "serverchan", "enable": False}]})
        self.assertEqual(channels, [])


class WebPushTestEndpointTest(unittest.TestCase):
    """弹窗里的「测试推送」：只测提交的那条通道，不要求先保存或启用。"""

    def _app(self, push):
        from types import SimpleNamespace

        return SimpleNamespace(lock=threading.Lock(), config={"push": push}, log=Mock())

    @patch("miyouqian.service.web.send_push", return_value="推送结果: wecombot: 成功")
    def test_submitted_channel_is_tested_even_when_nothing_is_enabled(self, send_push):
        from miyouqian.service.web import WebApp

        app = self._app({"enable": False, "channels": []})
        result = WebApp.test_push_channels(
            app,
            {"provider": "wecombot", "enable": False, "webhook": "https://example.invalid/bot"},
        )
        scoped = send_push.call_args.args[0]
        self.assertIs(scoped["push"]["enable"], True)
        self.assertIs(scoped["push"]["error_only"], False)
        channels = scoped["push"]["channels"]
        self.assertEqual([channel["provider"] for channel in channels], ["wecombot"])
        self.assertEqual(channels[0]["webhook"], "https://example.invalid/bot")
        self.assertTrue(channels[0]["enable"])
        self.assertIn("成功", result)

    @patch("miyouqian.service.web.send_push")
    def test_empty_channel_payload_is_rejected(self, send_push):
        from miyouqian.service.web import WebApp

        app = self._app({"enable": True, "channels": []})
        with self.assertRaises(ValueError):
            WebApp.test_push_channels(app, {"provider": "wecombot"})
        send_push.assert_not_called()

    @patch("miyouqian.service.web.send_push", return_value="推送结果: qq: 成功")
    def test_only_the_submitted_channel_is_tested(self, send_push):
        from miyouqian.service.web import WebApp

        app = self._app(
            {
                "enable": True,
                "channels": [
                    {"provider": "dingrobot", "enable": True, "webhook": "https://example.invalid/ding"},
                    {
                        "provider": "qq",
                        "enable": True,
                        "push_url": "http://127.0.0.1:3000",
                        "access_token": "token",
                        "send_id": "1134741727",
                    },
                ],
            }
        )
        WebApp.test_push_channels(
            app,
            {
                "provider": "qq",
                "enable": True,
                "push_url": "http://127.0.0.1:3000",
                "access_token": "token",
                "send_id": "1134741727",
                "msg_type": "private",
            },
        )
        config = send_push.call_args.args[0]
        self.assertEqual(
            [channel["provider"] for channel in config["push"]["channels"]], ["qq"]
        )


class WebPushTestAllProvidersTest(unittest.TestCase):
    """9 个推送方式都能单独测试：每个只触发自己那一次发送。"""

    SAMPLES = {
        "pushplus": {"token": "token"},
        "serverchan": {"sendkey": "sctp1234tABC"},
        "telegram": {"token": "123:abc", "chat_id": "42"},
        "dingrobot": {"webhook": "https://example.invalid/ding"},
        "feishubot": {"webhook": "https://example.invalid/feishu"},
        "wecombot": {"webhook": "https://example.invalid/wecom"},
        "email": {
            "smtp_host": "smtp.example.com",
            "smtp_user": "a@example.com",
            "smtp_password": "secret",
            "mail_to": "b@example.com",
        },
        "qq": {
            "push_url": "http://127.0.0.1:3000",
            "access_token": "token",
            "send_id": "",
            "msg_type": "private",
        },
        "qqbot": {"app_id": "102000000", "client_secret": "secret", "user_openid": "openid"},
    }

    def test_every_provider_is_sent_alone(self):
        from types import SimpleNamespace

        from miyouqian.service.web import WebApp

        for provider, fields in self.SAMPLES.items():
            with self.subTest(provider=provider):
                app = SimpleNamespace(
                    lock=threading.Lock(),
                    config={"push": {"enable": True, "channels": []}},
                    log=Mock(),
                )
                payload = dict(fields, provider=provider, enable=False)
                with patch(
                    "miyouqian.service.web.send_push",
                    return_value=f"推送结果: {provider}: 成功",
                ) as send_push:
                    result = WebApp.test_push_channels(app, payload)

                scoped = send_push.call_args.args[0]
                channels = scoped["push"]["channels"]
                self.assertEqual([channel["provider"] for channel in channels], [provider])
                self.assertTrue(channels[0]["enable"])
                self.assertIs(scoped["push"]["error_only"], False)
                self.assertIn(f"{provider}: 成功", result)

    def test_all_providers_survive_normalization_with_frontend_fields(self):
        for provider, fields in self.SAMPLES.items():
            with self.subTest(provider=provider):
                channels = normalize_push_channels(
                    {"channels": [dict(fields, provider=provider, enable=True)]}
                )
                self.assertEqual(len(channels), 1)
                self.assertEqual(channels[0]["provider"], provider)
                for key, value in fields.items():
                    self.assertEqual(str(channels[0].get(key, "")), str(value))