# -*- coding: utf-8 -*-
"""任务结果推送。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import pathlib
import re
import smtplib
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Callable, Optional
from urllib.parse import quote_plus
from ..core.config import normalize_gotify_priority
from ..core.onebot import OneBotHTTP
from ..core.qq_bot import QQBot
from ..core.captcha import DAMAGOU_BALANCE_INSUFFICIENT_MESSAGE

import httpx

PUSH_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parents[1] / "templates" / "push"
# 卡片外层（account_sections_html 的容器）已经是白底，这里不用再重复 background，省字符
_CARD_STYLE = "border:1px solid #d8e4ef;border-radius:8px;padding:14px"
WECOM_MARKDOWN_MAX_BYTES = 4096
WECOM_TEXT_MAX_BYTES = 2048
WECOM_SEND_INTERVAL = 3.1  # 每个机器人最多 20 条/分钟，留出边界余量。
_WECOM_REGISTRY_LOCK = threading.Lock()
_WECOM_SEND_LOCKS: dict[str, threading.Lock] = {}
_WECOM_NEXT_SEND: dict[str, float] = {}


def send_task_push(config: dict[str, Any], lines: list[str]) -> str:
    """发送签到结果推送，标题要如实反映成败，不能不管有没有失败都说「任务完成」。"""
    balance_insufficient = has_damagou_balance_insufficient(lines)
    success = False if balance_insufficient else is_task_success(lines)
    if balance_insufficient:
        title = "打码狗余额不足"
    else:
        title = "米游签任务完成" if success else "米游签任务失败"
    return send_push(config, title, "\n".join(lines), success=success)


def send_push(config: dict[str, Any], title: str, message: str, success: bool = True) -> str:
    push = config.get("push") or {}
    if not push.get("enable"):
        return ""
    if push.get("error_only") and success:
        return ""
    channels = push_channels(push)
    if not channels:
        return "推送失败: 未配置推送通道"
    results: list[str] = []
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            for channel in channels:
                provider = str(channel.get("provider") or "").strip().lower()
                try:
                    _send(client, provider, channel, title, message, success)
                    results.append(f"{provider}: 成功")
                except Exception as exc:
                    results.append(f"{provider}: 失败 ({exc})")
        return "推送结果: " + "；".join(results)
    except Exception as exc:
        return f"推送失败: {exc}"


def send_exchange_push(
    config: dict[str, Any],
    title: str,
    goods_name: str,
    result: dict[str, Any],
    plan: dict[str, Any],
    success: bool = True,
) -> str:
    """发送商品兑换推送"""
    push = config.get("push") or {}
    if not push.get("enable"):
        return ""
    if push.get("error_only") and success:
        return ""
    channels = push_channels(push)
    if not channels:
        return "推送失败: 未配置推送通道"
    results: list[str] = []
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            for channel in channels:
                provider = str(channel.get("provider") or "").strip().lower()
                try:
                    _send_exchange(client, provider, channel, title, goods_name, result, plan, success)
                    results.append(f"{provider}: 成功")
                except Exception as exc:
                    results.append(f"{provider}: 失败 ({exc})")
        return "推送结果: " + "；".join(results)
    except Exception as exc:
        return f"推送失败: {exc}"


def push_channels(push: dict[str, Any]) -> list[dict[str, Any]]:
    raw_channels = push.get("channels")
    if isinstance(raw_channels, list):
        return [
            channel
            for channel in raw_channels
            if isinstance(channel, dict) and channel.get("enable")
        ]
    if push.get("provider") and push.get("enable"):
        return [push]
    return []


def _send_exchange(
    client: httpx.Client,
    provider: str,
    push: dict[str, Any],
    title: str,
    goods_name: str,
    result: dict[str, Any],
    plan: dict[str, Any],
    success: bool,
) -> None:
    """发送商品兑换推送"""
    token = str(push.get("token") or "").strip()
    webhook = str(push.get("webhook") or "").strip()
    topic = str(push.get("topic") or "").strip()
    chat_id = str(push.get("chat_id") or "").strip()
    secret = str(push.get("secret") or "").strip()
    # 自定义 API 地址
    api_url = str(push.get("api_url") or "").strip()
    # QQ推送
    push_url = str(push.get("push_url") or "").strip()
    access_token = str(push.get("access_token") or "").strip()
    send_id = str(push.get("send_id") or "").strip()
    msg_type = str(push.get("msg_type") or "").strip()

    smtp_host = str(push.get("smtp_host") or "").strip()
    smtp_port = int(push.get("smtp_port") or 465)
    smtp_user = str(push.get("smtp_user") or "").strip()
    smtp_password = str(push.get("smtp_password") or "").strip()
    mail_from = str(push.get("mail_from") or smtp_user).strip()
    mail_to = str(push.get("mail_to") or "").strip()
    smtp_ssl = bool(push.get("smtp_ssl", True))

    if provider == "pushplus":
        require(token, "token")
        url = "https://www.pushplus.plus/send"
        payload = pushplus_payload(
            token, title, build_exchange_html(title, goods_name, result, plan, success), "html", topic
        )
        try:
            request_pushplus(client, url, payload)
        except Exception:
            payload = pushplus_payload(
                token, title, build_exchange_markdown(title, goods_name, result, plan, success), "markdown", topic
            )
            request_pushplus(client, url, payload)
        return

    if provider == "serverchan":
        serverchan_send(client, push, title, build_exchange_markdown(title, goods_name, result, plan, success))
        return

    if provider == "telegram":
        require(token, "token")
        require(chat_id, "chat_id")
        request_url = api_url or "https://api.telegram.org"
        url = f"{request_url}/bot{token}/sendMessage"
        request_json(
            client,
            "POST",
            url,
            json={
                "chat_id": chat_id,
                "text": build_exchange_telegram(title, goods_name, result, plan, success),
                "parse_mode": "HTML",
            },
        )
        return

    if provider == "qq":
        require(push_url, "push_url")
        require(access_token, "access_token")
        require(send_id, "send_id")
        require(msg_type, "msg_type")
        if msg_type == "group":
            message_type = 'group'
            user_id = None
            group_id = send_id
        elif msg_type == "private":
            message_type = 'private'
            user_id = send_id
            group_id = None

        text = build_exchange_text(title, goods_name, result, plan, success)
        bot = OneBotHTTP(base_url=push_url, access_token=access_token)
        try:
            bot.send_msg(user_id=user_id, group_id=group_id, message=text, message_type=message_type)
        except Exception as ex:
            raise ValueError(f"QQ推送通道暂不可用，{ex}")
        return

    if provider == "qqbot":
        send_qq_bot_message(push, build_exchange_text(title, goods_name, result, plan, success))
        return

    if provider == "dingrobot":
        require(webhook, "webhook")
        url = signed_ding_url(webhook, secret) if secret else webhook
        request_json(
            client,
            "POST",
            url,
            json={
                "msgtype": "markdown",
                "markdown": {"title": title, "text": build_exchange_markdown(title, goods_name, result, plan, success)},
            },
        )
        return

    if provider == "feishubot":
        require(webhook, "webhook")
        lines = [
            f"**{title}**",
            "",
            "**商品兑换通知**",
            f"商品：{goods_name}",
            f"账号：{plan.get('account', '未知')}",
            f"结果：{result.get('message', '未知')}",
            f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        payload = {"msg_type": "text", "content": {"text": "\n".join(lines)}}
        if secret:
            # 飞书签名：HMAC-SHA256(key="timestamp\nsecret", msg="") 后 base64
            now = int(time.time())
            payload["timestamp"] = str(now)
            payload["sign"] = base64.b64encode(
                hmac.new(
                    f"{now}\n{secret}".encode("utf-8"),
                    digestmod=hashlib.sha256,
                ).digest()
            ).decode("utf-8")
        request_json(client, "POST", webhook, json=payload)
        return

    if provider == "wecombot":
        require(webhook, "webhook")
        plain_text = push.get("plain_text", False)
        content = (build_exchange_text if plain_text else build_exchange_markdown)(
            title, goods_name, result, plan, success,
        )
        send_wecom(client, webhook, "text" if plain_text else "markdown", content)
        return

    if provider == "email":
        send_mail(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            mail_from=mail_from,
            mail_to=mail_to,
            title=title,
            message=build_exchange_text(title, goods_name, result, plan, success),
            html_message=build_exchange_html(title, goods_name, result, plan, success),
            smtp_ssl=smtp_ssl,
        )
        return

    if provider == "gotify":
        send_gotify(client, push, title, build_exchange_markdown(title, goods_name, result, plan, success))
        return

    raise ValueError(f"不支持的推送通道: {provider}")


def _send(client: httpx.Client, provider: str, push: dict[str, Any], title: str, message: str, success: bool) -> None:
    token = str(push.get("token") or "").strip()
    webhook = str(push.get("webhook") or "").strip()
    topic = str(push.get("topic") or "").strip()
    chat_id = str(push.get("chat_id") or "").strip()
    secret = str(push.get("secret") or "").strip()
    # 自定义 API 地址
    api_url = str(push.get("api_url") or "").strip()
    # QQ推送
    push_url = str(push.get("push_url") or "").strip()
    access_token = str(push.get("access_token") or "").strip()
    send_id = str(push.get("send_id") or "").strip()
    msg_type = str(push.get("msg_type") or "").strip()

    smtp_host = str(push.get("smtp_host") or "").strip()
    smtp_port = int(push.get("smtp_port") or 465)
    smtp_user = str(push.get("smtp_user") or "").strip()
    smtp_password = str(push.get("smtp_password") or "").strip()
    mail_from = str(push.get("mail_from") or smtp_user).strip()
    mail_to = str(push.get("mail_to") or "").strip()
    smtp_ssl = bool(push.get("smtp_ssl", True))
    markdown_message = build_push_markdown(title, message, success)
    plain_message = build_push_text(title, message, success)

    if provider == "qq":
        require(push_url, "push_url")
        require(access_token, "access_token")
        require(send_id, "send_id")
        require(msg_type, "msg_type")
        # 消息类型
        if msg_type == "group":
            message_type = 'group'
            user_id = None
            group_id = send_id
        elif msg_type == "private":
            message_type = 'private'
            user_id = send_id
            group_id = None

        lines = message.splitlines()

        prefix_skip = (
            "正在",
            "游戏社区签到汇总",
            "游戏社区成功项",
            "米游币任务汇总",
            "米游币成功项",
        )
        filtered = []
        for line in lines:
            if line.endswith("社区签到成功"):
                continue
            if any(line.startswith(p) for p in prefix_skip):
                continue
            filtered.append(line)

        bot = OneBotHTTP(base_url = push_url, access_token = access_token)
        try:
            bot.send_msg(user_id = user_id, group_id = group_id, message = '\n'.join(filtered), message_type = message_type)
        except Exception as ex:
            raise ValueError(f"QQ推送通道暂不可用，{ex}")
        return



    if provider == "pushplus":
        require(token, "token")
        url = "https://www.pushplus.plus/send"
        payload = pushplus_payload(token, title, build_push_html(title, message, success), "html", topic)
        try:
            request_pushplus(client, url, payload)
        except Exception:
            request_pushplus(client, url, pushplus_payload(token, title, markdown_message, "markdown", topic))
        return

    if provider == "serverchan":
        serverchan_send(client, push, title, markdown_message)
        return

    if provider == "telegram":
        require(token, "token")
        require(chat_id, "chat_id")
        request_url = api_url or "https://api.telegram.org"
        url = f"{request_url}/bot{token}/sendMessage"
        request_json(
            client,
            "POST",
            url,
            json={"chat_id": chat_id, "text": build_telegram_html(title, message, success), "parse_mode": "HTML"},
        )
        return

    if provider == "qqbot":
        send_qq_bot_message(push, plain_message)
        return

    if provider == "dingrobot":
        require(webhook, "webhook")
        url = signed_ding_url(webhook, secret) if secret else webhook
        request_json(client, "POST", url, json={"msgtype": "markdown", "markdown": {"title": title, "text": markdown_message}})
        return

    if provider == "feishubot":
        require(webhook, "webhook")
        payload = build_feishu_post(title, message, success)
        if secret:
            now = int(time.time())
            payload["timestamp"] = str(now)
            payload["sign"] = base64.b64encode(
                hmac.new(
                    f"{now}\n{secret}".encode("utf-8"),
                    digestmod=hashlib.sha256,
                ).digest()
            ).decode("utf-8")
        request_json(client, "POST", webhook, json=payload)
        return

    if provider == "wecombot":
        require(webhook, "webhook")
        plain_text = push.get("plain_text", False)
        send_wecom(
            client, webhook, "text" if plain_text else "markdown",
            plain_message if plain_text else markdown_message,
        )
        return

    if provider == "email":
        send_mail(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            mail_from=mail_from,
            mail_to=mail_to,
            title=title,
            message=plain_message,
            html_message=build_push_html(title, message, success),
            smtp_ssl=smtp_ssl,
        )
        return

    if provider == "gotify":
        send_gotify(client, push, title, markdown_message)
        return

    raise ValueError(f"不支持的推送通道: {provider}")


def send_gotify(client: httpx.Client, push: dict[str, Any], title: str, message: str) -> None:
    """发送 Gotify 通知。"""
    server = str(push.get("server") or "").strip().rstrip("/")
    token = str(push.get("token") or "").strip()
    require(server, "server")
    require(token, "token")
    # token 放请求头而不是 ?token=：HTTPStatusError 的文本带完整 URL，会连同 token 一起进推送结果和日志
    response = client.post(
        f"{server}/message",
        headers={"X-Gotify-Key": token},
        json={
            "title": title,
            "message": message,
            "priority": normalize_gotify_priority(push.get("priority")),
            # Gotify 默认按纯文本展示，要让它渲染 Markdown 得显式声明 content type
            "extras": {"client::display": {"contentType": "text/markdown"}},
        },
        # 公共 client 会跟随重定向，而 301/302 会把 POST 改成不带正文的 GET，还会把 token 带给跳转的目标主机
        follow_redirects=False,
    )
    if response.is_redirect:
        raise ValueError(
            f"Gotify 服务器返回了重定向（HTTP {response.status_code}），请检查服务器地址的 http/https 是否写对"
        )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"Gotify 请求失败：HTTP {exc.response.status_code}") from None


def build_push_html(title: str, message: str, success: bool) -> str:
    return render_template("html.html", build_template_context(title, message, success))


def send_qq_bot_message(push: dict[str, Any], message: str) -> None:
    """通过 QQ 开放平台官方机器人（AppID + AppSecret）发送消息。

    和 onebot 版 `qq` 通道不是一回事：那条通道走的是第三方框架的 HTTP API，
    这条走官方 OpenAPI，需要用户先绑定 user_openid / group_openid。
    """
    with QQBot(push) as bot:
        results = bot.send(message)
    failures = [item for item in results if "失败" in item]
    if failures:
        # 有目标成功时不算失败，但要把问题带出去，避免「推送成功」掩盖掉一半没发出去
        raise ValueError("；".join(failures))


def pushplus_payload(token: str, title: str, content: str, template: str, topic: str = "") -> dict[str, str]:
    payload = {"token": token, "title": title, "content": content, "template": template}
    if topic:
        payload["topic"] = topic
    return payload


SERVERCHAN_SENDKEY_RE = re.compile(r"^sctp([0-9]+)t")
SERVERCHAN_UID_RE = re.compile(r"[0-9]+")


def serverchan_url(push: dict[str, Any]) -> str:
    """拼 Server酱³ 的推送地址：``https://<uid>.push.ft07.com/send/<sendkey>.send``。

    `uid` 可以留空——官方文档写明它就在 SendKey 的 ``sctp{uid}t...`` 前缀里，
    这里自动解析，省得用户还要去 SendKey 页面抄一遍。
    """
    sendkey = str(push.get("sendkey") or "").strip()
    if not sendkey:
        raise ValueError("请先填写 Server酱 SendKey")
    uid = str(push.get("uid") or "").strip()
    if not uid:
        match = SERVERCHAN_SENDKEY_RE.match(sendkey)
        if not match:
            raise ValueError("SendKey 形如 sctp1234tXXXX，未能解析出 uid，请在配置里手动填写 uid")
        uid = match.group(1)
    # uid 会拼进主机名，只接受 ASCII 数字，避免被填成其他域名后把推送内容发出去
    if not SERVERCHAN_UID_RE.fullmatch(uid):
        raise ValueError("uid 只能是数字，请检查 Server酱 配置")
    return f"https://{uid}.push.ft07.com/send/{sendkey}.send"


def serverchan_send(client: httpx.Client, push: dict[str, Any], title: str, markdown: str) -> None:
    """POST 到 Server酱³。用 JSON 提交，中文与换行不用手工 urlencode。

    这里不走公共的 `request_json`：那个 helper 只负责 raise_for_status 且不返回响应体，
    而 Server酱的业务错误是放在 200 响应的 `code` 字段里的，必须自己看一眼。
    """
    url = serverchan_url(push)
    response = client.post(url, json={"title": title, "desp": markdown})
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # HTTPStatusError 的文本带完整 URL，而 URL 里就是 SendKey，会被推送结果/日志/页面提示原样显示
        raise ValueError(f"Server酱请求失败：HTTP {exc.response.status_code}") from None
    try:
        data = response.json()
    except ValueError:
        # 200 但不是 JSON（比如网关返回的 HTML）也按成功处理，和其他渠道只看状态码的行为保持一致
        return
    if not isinstance(data, dict):
        return
    code = data.get("code")
    if code is not None and str(code) != "0":
        raise ValueError(f"Server酱返回错误：{data.get('message') or code}")


def build_telegram_html(title: str, message: str, success: bool) -> str:
    context = build_template_context(title, message, success, detail_limit=2600)
    for key in ("account_sections_text",):
        context[key] = html.escape(context[key])
    return render_template("telegram.html", context)


def build_push_markdown(title: str, message: str, success: bool) -> str:
    return render_template("markdown.md", build_template_context(title, message, success))


def build_push_text(title: str, message: str, success: bool) -> str:
    return render_template("text.txt", build_template_context(title, message, success))


def build_template_context(title: str, message: str, success: bool, detail_limit: int | None = None) -> dict[str, str]:
    lines = normalize_message_lines(message)
    summary = build_structured_summary(lines, success)
    detail = "\n".join(lines) or "无详细日志"
    if detail_limit is not None:
        detail = truncate_text(detail, detail_limit)
    status = format_status(success)
    return {
        "title": html.escape(title),
        "title_text": title,
        "status": html.escape(status),
        "status_text": status,
        "status_color": "#1c9a68" if success else "#b83b4b",
        "status_bg": "#edf8f3" if success else "#fdecef",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account_sections_html": build_account_sections_html(summary),
        "account_sections_markdown": build_account_sections_text(summary, markdown=True),
        "account_sections_text": build_account_sections_text(summary),
        "detail_html": html.escape(detail),
        "detail_markdown": escape_markdown_code(detail),
        "detail_text": detail,
    }


def build_exchange_template_context(
    title: str,
    goods_name: str,
    result: dict[str, Any],
    plan: dict[str, Any],
    success: bool,
) -> dict[str, str]:
    """为商品兑换构建推送模板上下文"""
    status = "兑换成功" if success else "兑换失败"
    retcode = result.get("retcode", -1)
    # 执行本身出了异常时没有返回码
    retcode_text = "-" if retcode is None else str(retcode)
    message = result.get("message", "未知结果")
    attempt = result.get("attempt", 1)
    # 虚拟商品才有游戏角色，实体商品没有这一行
    role = " / ".join(part for part in (plan.get("role_name"), plan.get("uid")) if part)

    # 商品信息
    price = plan.get("price", 0)
    icon = plan.get("icon", "")
    account_name = plan.get("account", "未知账号")
    exchange_time = result.get("sent_at", datetime.now().isoformat())

    # 构建商品图标HTML
    icon_html = ""
    if icon:
        icon_html = f'<img src="{html.escape(icon)}" style="width:60px;height:60px;border-radius:8px;object-fit:cover;margin-right:12px;" alt="商品图标">'
    else:
        icon_html = f'<div style="width:60px;height:60px;border-radius:8px;background:#d8e4ef;display:flex;align-items:center;justify-content:center;margin-right:12px;"><svg width="30" height="30" viewBox="0 0 24 24" fill="#168df5"><path d="M20.38 3.4a1.6 1.6 0 0 0-1.52-.07L13 5.6V4.1a1.6 1.6 0 0 0-2.5-1.3l-8 6.4a1.6 1.6 0 0 0-.2 2.3l8 9.6a1.6 1.6 0 0 0 2.7-.7V13l5.9 3.5a1.6 1.6 0 0 0 2.4-1.4V5a1.6 1.6 0 0 0-1.46-1.6z"/></svg></div>'

    return {
        "title": html.escape(title),
        "title_text": title,
        "status": html.escape(status),
        "status_text": status,
        "status_color": "#1c9a68" if success else "#b83b4b",
        "status_bg": "#edf8f3" if success else "#fdecef",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "goods_name": html.escape(goods_name),
        "goods_name_text": goods_name,
        "price": str(price),
        "account_name": html.escape(account_name),
        "account_name_text": account_name,
        "retcode": str(retcode),
        "retcode_text": retcode_text,
        "message": html.escape(message),
        "message_text": message,
        "attempt": str(attempt),
        "exchange_time": exchange_time,
        "icon_html": icon_html,
        "detail_html": html.escape(f"结果：{message}({retcode_text})，尝试 {attempt} 次"),
        "detail_text": f"结果：{message}({retcode_text})，尝试 {attempt} 次",
        "role_line_text": f"角色：{role}\n" if role else "",
        "role_line_markdown": f"> 🎮 **角色：**{role}\n" if role else "",
        "role_line_html": f"🎮 <b>角色：</b>{html.escape(role)}\n" if role else "",
    }


def build_account_sections_html(summary: dict[str, Any]) -> str:
    sections = summary["sections"]
    if not sections:
        return section_empty_html("账号摘要", "无账号信息")
    parts: list[str] = []
    for index, section in enumerate(sections):
        open_attr = " open" if index == 0 else ""
        parts.append(
            f"""
            <details{open_attr} style="border:1px solid #d8e4ef;border-radius:8px;background:#fff;margin-bottom:10px;overflow:hidden;">
              <summary style="cursor:pointer;list-style:none;padding:12px 14px;background:#f1f7fc;color:#102033;font-size:15px;font-weight:800;">{html.escape(section["label"])}</summary>
              <div style="padding:10px;">
                <div style="margin-bottom:8px;">{build_game_section_html(section)}</div>
                <div style="margin-bottom:8px;">{build_cloud_game_section_html(section)}</div>
                {build_bbs_section_html(section)}
              </div>
            </details>
            """.strip()
        )
    return "\n".join(parts)


def build_account_sections_text(summary: dict[str, Any], markdown: bool = False) -> str:
    sections = summary["sections"]
    if not sections:
        return "- 无账号信息"
    blocks: list[str] = []
    for section in sections:
        heading = f"#### {section['label']}" if markdown else f"[{section['label']}]"
        blocks.append(
            "\n".join(
                [
                    heading,
                    "游戏社区签到：",
                    build_game_section_text(section, markdown=markdown),
                    "云游戏签到：",
                    build_cloud_game_section_text(section, markdown=markdown),
                    "米游币获取：",
                    build_bbs_section_text(section, markdown=markdown),
                ]
            )
        )
    return "\n\n".join(blocks)


def build_game_section_html(summary: dict[str, Any]) -> str:
    game = summary["game"]
    if not game["present"]:
        return section_empty_html("游戏社区签到", "本次未执行游戏社区签到")
    item_rows = build_result_items_html(game)
    return f"""
    <div style="{_CARD_STYLE}">
      <div style="font-size:15px;font-weight:800;color:#102033;margin-bottom:6px;">游戏社区签到</div>
      {segmented_progress_html(game["done_percent"], game["failed_percent"], game["label"], game["color"])}
      <div style="margin-top:6px;color:#627389;font-size:13px;">{html.escape(game["summary"] or "无汇总信息")}</div>
      {item_rows}
    </div>
    """.strip()


def build_cloud_game_section_html(summary: dict[str, Any]) -> str:
    cloud = summary["cloud_game"]
    if not cloud["present"]:
        return section_empty_html("云游戏签到", "本次未执行云游戏签到")
    item_rows = build_result_items_html(cloud)
    return f"""
    <div style="{_CARD_STYLE}">
      <div style="font-size:15px;font-weight:800;color:#102033;margin-bottom:6px;">云游戏签到</div>
      {segmented_progress_html(cloud["done_percent"], cloud["failed_percent"], cloud["label"], cloud["color"])}
      <div style="margin-top:6px;color:#627389;font-size:13px;">{html.escape(cloud["summary"] or "无汇总信息")}</div>
      {item_rows}
    </div>
    """.strip()


def build_result_items_html(result: dict[str, Any]) -> str:
    rows: list[str] = []
    for item in result["failed_items"][:6]:
        rows.append(result_item_html("失败", item, "#b83b4b"))
    for item in result["items"][:6]:
        rows.append(result_item_html("成功", item, "#1c7c61"))
    if not rows:
        return ""
    return '<div style="margin-top:8px;border-top:1px solid #edf3f8;">' + "".join(rows) + "</div>"


def result_item_html(label: str, item: str, color: str) -> str:
    return (
        f'<div style="padding:6px 0;border-bottom:1px solid #edf3f8;font-size:13px;">'
        f'<b style="color:{color};">{html.escape(label)}</b> {html.escape(shorten_text(item, 120))}</div>'
    )


def build_bbs_section_html(summary: dict[str, Any]) -> str:
    bbs = summary["bbs"]
    if not bbs["present"]:
        return section_empty_html("米游币获取", "本次未执行米游币任务")
    task_rows = "".join(
        f"""
        <div style="padding:8px 0;border-top:1px solid #edf3f8;">
          <div style="font-size:13px;margin-bottom:4px;">
            <b style="color:#102033;">{html.escape(task["name"])}</b>
            <span style="float:right;color:{html.escape(task["color"])};">{html.escape(task["label"])} · {task["done"]}/{task["total"]}</span>
          </div>
          {segmented_progress_html(task["done_percent"], task["failed_percent"], "", compact=True)}
        </div>
        """.strip()
        for task in bbs["tasks"]
    )
    return f"""
    <div style="{_CARD_STYLE}">
      <div style="font-size:15px;font-weight:800;color:#102033;margin-bottom:6px;">米游币获取</div>
      <div style="font-size:13px;color:#627389;margin-bottom:8px;">
        今日 <b style="color:#102033;font-size:17px;">{bbs["today_done_points"]}/{bbs["possible_points"]}</b>
        实际 {bbs["actual_points"]} · 新增 {bbs["gained_points"]} · 总计 {bbs["total_points"] or "-"}
      </div>
      {progress_html(bbs["point_percent"], f'今日进度 {bbs["point_percent"]}%', "#168df5")}
      {task_rows}
    </div>
    """.strip()


def section_empty_html(title: str, message: str) -> str:
    return f"""
    <div style="{_CARD_STYLE}">
      <div style="font-size:15px;font-weight:800;color:#102033;margin-bottom:6px;">{html.escape(title)}</div>
      <div style="color:#627389;font-size:13px;">{html.escape(message)}</div>
    </div>
    """.strip()


def progress_html(percent: int, label: str, color: str, compact: bool = False) -> str:
    percent = clamp_percent(percent)
    height = 6 if compact else 8
    label_html = f'<div style="color:#627389;font-size:12px;">{html.escape(label)}</div>' if label else ""
    return (
        f'<div style="height:{height}px;border-radius:999px;background:'
        f"linear-gradient(to right,{color} 0 {percent}%,#d8e4ef {percent}% 100%);\">"
        f"</div>{label_html}"
    )


def segmented_progress_html(
    done_percent: int,
    failed_percent: int,
    label: str,
    label_color: str = "#627389",
    compact: bool = False,
) -> str:
    """红蓝分段进度条，从左到右依次是红（失败的尝试）、蓝（成功）、灰（未执行）。

    先失败后成功的任务就是前红后蓝，两段宽度之和才是整体完成度。用一个 div 的
    linear-gradient 分段代替两个嵌套 div，视觉效果一样，省下一半标签。
    """
    failed_percent = clamp_percent(failed_percent)
    done_percent = min(clamp_percent(done_percent), 100 - failed_percent)
    failed_end = failed_percent
    done_end = failed_percent + done_percent
    height = 6 if compact else 8
    label_html = (
        f'<div style="color:{label_color};font-size:12px;font-weight:700;">{html.escape(label)}</div>'
        if label
        else ""
    )
    return (
        f'<div style="height:{height}px;border-radius:999px;background:'
        f"linear-gradient(to right,#b83b4b 0 {failed_end}%,#168df5 {failed_end}% {done_end}%,"
        f'#d8e4ef {done_end}% 100%);"></div>{label_html}'
    )


def build_game_section_text(summary: dict[str, Any], markdown: bool = False) -> str:
    game = summary["game"]
    if not game["present"]:
        return "- 本次未执行游戏社区签到"
    return build_result_section_text(game, "游戏社区签到汇总")


def build_cloud_game_section_text(summary: dict[str, Any], markdown: bool = False) -> str:
    cloud = summary["cloud_game"]
    if not cloud["present"]:
        return "- 本次未执行云游戏签到"
    return build_result_section_text(cloud, "云游戏签到汇总")


def build_result_section_text(result: dict[str, Any], fallback_summary: str) -> str:
    lines = [
        f"- {result['summary'] or fallback_summary}",
        f"- 进度 {segmented_text_bar(result['done_percent'], result['failed_percent'])} {result['label']}",
    ]
    for item in result["failed_items"][:6]:
        lines.append(f"- 失败：{item}")
    for item in result["items"][:6]:
        lines.append(f"- 成功：{item}")
    return "\n".join(lines)


def build_bbs_section_text(summary: dict[str, Any], markdown: bool = False) -> str:
    bbs = summary["bbs"]
    if not bbs["present"]:
        return "- 本次未执行米游币任务"
    lines = [
        f"- 今日米游币获取进度 {text_bar(bbs['point_percent'])} {bbs['today_done_points']}/{bbs['possible_points']}",
        f"- 米游币数量：实际已获得 {bbs['actual_points']}，本次新增 {bbs['gained_points']}，当前总计 {bbs['total_points'] or '-'}",
    ]
    for task in bbs["tasks"]:
        bar = segmented_text_bar(task["done_percent"], task["failed_percent"])
        lines.append(f"- {task['name']} {bar} {task['label']} ({task['done']}/{task['total']})")
    if bbs["summary"]:
        lines.append(f"- {bbs['summary']}")
    return "\n".join(lines)


def build_structured_summary(lines: list[str], success: bool) -> dict[str, Any]:
    sections = [
        build_account_summary(section["label"], section["lines"], success)
        for section in split_account_sections(lines)
    ]
    return {
        "accounts": [section["label"] for section in sections],
        "sections": sections,
    }


def split_account_sections(lines: list[str]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current_label = ""
    current_lines: list[str] = []
    for line in lines:
        if line.startswith("# "):
            if current_label or current_lines:
                sections.append({"label": current_label or "任务摘要", "lines": current_lines})
            current_label = line.removeprefix("# ").strip()
            current_lines = []
            continue
        current_lines.append(line)
    if current_label or current_lines:
        sections.append({"label": current_label or "任务摘要", "lines": current_lines})
    return sections


def build_account_summary(label: str, lines: list[str], success: bool) -> dict[str, Any]:
    game = build_result_summary(
        first_line(lines, "游戏社区签到汇总：") or first_line(lines, "游戏签到汇总："),
        task_items(lines, "游戏社区成功项：") + task_items(lines, "游戏成功项："),
        task_items(lines, "游戏社区失败项：") + task_items(lines, "游戏失败项："),
        success,
        lines,
        "游戏社区签到",
    )
    cloud_game = build_result_summary(
        first_line(lines, "云游戏签到汇总："),
        task_items(lines, "云游戏成功项："),
        task_items(lines, "云游戏失败项："),
        success,
    )

    bbs_summary = first_line(lines, "米游币任务汇总：")
    bbs_progress = first_line(lines, "米游币今日进度：")
    bbs_completed = first_line(lines, "今日任务已完成")
    bbs_end = first_line(lines, "社区任务结束：")
    points = parse_point_summary(bbs_summary, bbs_progress, bbs_end, bbs_completed)
    bbs_tasks = build_bbs_tasks(lines)
    bbs_present = bool(bbs_summary or bbs_progress or any("米游币" in line or "社区签到" in line for line in lines))

    return {
        "label": label,
        "game": game,
        "cloud_game": cloud_game,
        "bbs": {
            "present": bbs_present,
            "summary": bbs_summary,
            "tasks": bbs_tasks,
            "possible_points": points["possible"],
            "actual_points": points["actual"],
            "gained_points": points["gained"],
            "total_points": points["total"],
            "point_percent": round(points["today_done"] / points["possible"] * 100) if points["possible"] else 0,
            "today_done_points": points["today_done"],
        },
    }


CAPTCHA_ATTEMPT_MARK = "触发验证码，正在调用"


def count_captcha_attempts(lines: list[str], scene: str) -> tuple[int, int]:
    """统计某类任务的验证码识别尝试，返回 (尝试总次数, 触发验证码的项目数)。

    每个项目触发验证码后会连续尝试 (1/N)、(2/N)…，所以序号为 1 的行就是一个新项目的开始。
    scene 必须是日志行的开头（如「点赞」「游戏社区签到」），避免「社区签到」误匹配「游戏社区签到」。
    """
    pattern = re.compile(rf"^{re.escape(scene)}{CAPTCHA_ATTEMPT_MARK}.+识别\((\d+)/\d+\)$")
    attempts = episodes = 0
    for line in lines:
        match = pattern.match(line)
        if match:
            attempts += 1
            episodes += match.group(1) == "1"
    return attempts, episodes


def count_failed_marks(failed: int, captcha_failed: int, attempts: int, episodes: int) -> int:
    """进度条里红色段的数量：最终失败的项目 + 重试时失败、但项目最终成功的验证码尝试。

    触发验证码的项目最多尝试 N 次：N 次都失败才是真正的失败（N 段红）；
    前几次失败、最后一次成功的，前几次画成红色，最后一次是蓝色，整体仍算成功。
    """
    if not attempts:
        return failed
    captcha_failed = min(captcha_failed, episodes, failed)
    recovered = episodes - captcha_failed
    return (failed - captcha_failed) + (attempts - recovered)


def summarize_attempts(done: int, failed: int, total: int, failed_marks: int | None = None) -> dict[str, Any]:
    """根据成功/最终失败的项目数算出状态标签，并给出进度条的红蓝比例。

    done / failed 是项目的最终结果：重试后成功的项目算 done，只有重试用完仍失败的才算 failed。
    failed_marks 是进度条红色段数量（包含重试时失败的尝试），缺省等于 failed。
    进度条从左到右依次是 红（失败的尝试）、蓝（成功）、灰（还没执行），所以先失败后成功是前红后蓝。
    """
    total = max(total, 0)
    marks = failed if failed_marks is None else max(failed_marks, 0)
    pending = max(total - done - failed, 0)
    bar_total = done + marks + pending
    failed_percent = round(marks / bar_total * 100) if bar_total else 0
    done_percent = round(done / bar_total * 100) if bar_total else 0
    done_percent = min(done_percent, 100 - failed_percent)
    attempted = done + failed
    if attempted == 0:
        label, color = "未执行", "#627389"
    elif failed:
        label, color = f"失败 {failed}", "#b83b4b"
    elif attempted < total:
        label, color = "部分完成", "#a86d12"
    else:
        label, color = "完成", "#168df5"
    return {"done_percent": done_percent, "failed_percent": failed_percent, "label": label, "color": color}


def build_result_summary(
    summary: str,
    success_items: list[str],
    failed_items: list[str],
    success: bool,
    lines: list[str] | None = None,
    captcha_scene: str = "",
) -> dict[str, Any]:
    counts = parse_counts(summary)
    done, failed = counts[0], counts[1]
    if not (done or failed):
        done, failed = len(success_items), len(failed_items)
    attempts, episodes = count_captcha_attempts(lines or [], captcha_scene) if captcha_scene else (0, 0)
    captcha_failed = sum(1 for item in failed_items if "触发验证码" in item)
    status = summarize_attempts(done, failed, done + failed, count_failed_marks(failed, captcha_failed, attempts, episodes))
    return {
        "present": bool(summary or success_items or failed_items),
        "summary": summary,
        "success": done,
        "failed": failed,
        "skipped": counts[2],
        "done_percent": status["done_percent"],
        "failed_percent": status["failed_percent"],
        "label": status["label"],
        "color": status["color"],
        "items": success_items,
        "failed_items": failed_items,
    }


def build_bbs_tasks(lines: list[str]) -> list[dict[str, Any]]:
    success_items = task_items(lines, "米游币成功项：")
    failed_items = task_items(lines, "米游币失败项：")
    specs = [
        (
            "社区签到",
            1,
            ("社区签到",),
            ("社区签到已完成",),
            lambda line: line.startswith("正在进行") and line.endswith("社区签到"),
            ("社区签到成功", "社区签到已完成"),
            ("社区签到失败", "社区签到验证码重试失败", "社区签到触发验证码，已跳过"),
            "社区签到",
        ),
        (
            "看帖任务",
            3,
            ("看帖 ",),
            ("看帖任务已完成",),
            lambda line: line.startswith("正在浏览:"),
            ("阅读成功", "看帖任务已完成"),
            ("阅读失败",),
        ),
        (
            "点赞任务",
            5,
            ("点赞 ",),
            ("点赞任务已完成",),
            lambda line: line.startswith("正在点赞:"),
            ("点赞成功", "点赞任务已完成"),
            ("点赞失败", "点赞验证码重试失败", "点赞触发验证码，已跳过"),
            "点赞",
        ),
        (
            "分享任务",
            1,
            ("分享 ",),
            ("分享任务已完成",),
            lambda line: line.startswith("正在分享:"),
            ("分享成功", "分享任务已完成"),
            ("分享失败",),
        ),
    ]
    return [task_progress(lines, success_items, failed_items, *spec) for spec in specs]


def task_progress(
    lines: list[str],
    success_items: list[str],
    failed_items: list[str],
    name: str,
    target: int,
    item_keywords: tuple[str, ...],
    skip_keywords: tuple[str, ...],
    start_matcher: Callable[[str], bool],
    done_keywords: tuple[str, ...],
    fail_keywords: tuple[str, ...],
    captcha_scene: str = "",
) -> dict[str, Any]:
    completed_by_skip = any(any(keyword in line for keyword in skip_keywords) for line in lines)
    started = sum(1 for line in lines if start_matcher(line))
    done = count_task_items(success_items, item_keywords)
    failed = count_task_items(failed_items, item_keywords)
    captcha_failed = sum(1 for item in failed_items if "触发验证码" in item and any(k in item for k in item_keywords))
    if not success_items and not failed_items:
        done = count_keyword_hits(lines, done_keywords)
        failed = count_keyword_hits(lines, fail_keywords)
        captcha_failed = count_keyword_hits(lines, tuple(k for k in fail_keywords if "验证码" in k))
    if completed_by_skip:
        total = max(target, started, done, failed, 1)
        done = max(done, total)
    elif started:
        total = max(started, done + failed, 1)
    elif done or failed:
        total = max(done + failed, 1)
    else:
        total = max(target, 1)
    attempts, episodes = count_captcha_attempts(lines, captcha_scene) if captcha_scene else (0, 0)
    status = summarize_attempts(done, failed, total, count_failed_marks(failed, captcha_failed, attempts, episodes))
    return {
        "name": name,
        "done": min(done, total),
        "total": total,
        "failed": failed,
        "done_percent": status["done_percent"],
        "failed_percent": status["failed_percent"],
        "label": status["label"],
        "color": status["color"],
    }


def task_items(lines: list[str], prefix: str) -> list[str]:
    items: list[str] = []
    for line in prefixed_lines(lines, prefix):
        items.extend(item.strip() for item in line.removeprefix(prefix).split(";") if item.strip())
    return items


def count_task_items(items: list[str], keywords: tuple[str, ...]) -> int:
    return sum(1 for item in items if any(keyword in item for keyword in keywords))


def first_line(lines: list[str], prefix: str) -> str:
    return next((line for line in lines if line.startswith(prefix)), "")


def prefixed_lines(lines: list[str], prefix: str) -> list[str]:
    return [line for line in lines if line.startswith(prefix)]


def parse_counts(line: str) -> tuple[int, int, int]:
    if not line:
        return (0, 0, 0)
    return (
        number_after(line, "成功"),
        number_after(line, "失败"),
        number_after(line, "跳过"),
    )


def has_damagou_balance_insufficient(lines: list[str]) -> bool:
    """判断任务日志中是否出现打码狗余额不足。"""
    return any(DAMAGOU_BALANCE_INSUFFICIENT_MESSAGE in line for line in lines)


def is_task_success(lines: list[str]) -> bool:
    if has_damagou_balance_insufficient(lines):
        return False
    for line in lines:
        if line.startswith(("游戏社区失败项：", "游戏失败项：", "云游戏失败项：", "米游币失败项：")):
            return False
        if line.startswith(("游戏社区签到汇总：", "游戏签到汇总：", "云游戏签到汇总：", "米游币任务汇总：")):
            if number_after(line, "失败") > 0:
                return False
        elif line in {"任务状态获取失败，请检查 cookie/stoken", "获取帖子列表失败，无法执行看帖/点赞/分享"}:
            return False
        elif line.startswith(("配置 enable=false", "没有配置账号")):
            return False
    return True


def parse_point_summary(
    summary_line: str,
    progress_line: str = "",
    end_line: str = "",
    completed_line: str = "",
) -> dict[str, int]:
    initial_received = number_after(progress_line, "已获得")
    actual = number_after(summary_line, "实际已获得")
    if not actual:
        actual = number_after(end_line, "今日已得")
    if not actual:
        actual = initial_received
    possible = number_after(progress_line, "预计总共可获得")
    if not possible:
        possible = number_after(summary_line, "今日总共可获得")
    if not possible:
        possible = initial_received + number_after(progress_line, "还可获得")
    if not possible:
        possible = actual + number_after(end_line, "还能获得")
    today_done = actual or initial_received
    return {
        "actual": actual,
        "possible": possible,
        "today_done": today_done,
        "gained": number_after(summary_line, "本次新增"),
        "total": (
            number_after(end_line, "当前总计")
            or number_after(completed_line, "当前总计")
            or number_after(summary_line, "当前总计")
        ),
    }


def number_after(text: str, keyword: str) -> int:
    if not text:
        return 0
    match = re.search(rf"{re.escape(keyword)}\s*(\d+)", text)
    return int(match.group(1)) if match else 0


def count_keyword_hits(lines: list[str], keywords: tuple[str, ...]) -> int:
    return sum(1 for line in lines if any(keyword in line for keyword in keywords))


def text_bar(percent: int) -> str:
    percent = clamp_percent(percent)
    filled = round(percent / 10)
    return "[" + "#" * filled + "-" * (10 - filled) + f"] {percent}%"


def segmented_text_bar(done_percent: int, failed_percent: int) -> str:
    """纯文本版红蓝分段进度条，顺序同 HTML：`x` 是失败的尝试，`#` 是成功，`-` 是未执行。

    不足一格的非零比例也至少画一格，免得 1 次失败夹在十几次成功里被四舍五入吞掉。
    """
    failed_percent = clamp_percent(failed_percent)
    done_percent = min(clamp_percent(done_percent), 100 - failed_percent)
    failed_filled = text_bar_cells(failed_percent)
    done_filled = min(text_bar_cells(done_percent), 10 - failed_filled)
    empty = 10 - failed_filled - done_filled
    return "[" + "x" * failed_filled + "#" * done_filled + "-" * empty + f"] {done_percent}%"


def text_bar_cells(percent: int) -> int:
    return min(max(round(percent / 10), 1), 10) if percent else 0


def shorten_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(limit - 1, 0)] + "…"


def clamp_percent(percent: int) -> int:
    return max(0, min(int(percent or 0), 100))


def render_template(name: str, values: dict[str, str]) -> str:
    template = (PUSH_TEMPLATE_DIR / name).read_text(encoding="utf-8")
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template.strip()


def build_exchange_html(title: str, goods_name: str, result: dict[str, Any], plan: dict[str, Any], success: bool) -> str:
    """构建商品兑换HTML推送"""
    context = build_exchange_template_context(title, goods_name, result, plan, success)
    return render_template("exchange.html", context)


def build_exchange_telegram(title: str, goods_name: str, result: dict[str, Any], plan: dict[str, Any], success: bool) -> str:
    """构建商品兑换Telegram推送"""
    context = build_exchange_template_context(title, goods_name, result, plan, success)
    return render_template("exchange_telegram.html", context)


def build_exchange_markdown(title: str, goods_name: str, result: dict[str, Any], plan: dict[str, Any], success: bool) -> str:
    """构建商品兑换Markdown推送"""
    context = build_exchange_template_context(title, goods_name, result, plan, success)
    return render_template("exchange_markdown.md", context)


def build_exchange_text(title: str, goods_name: str, result: dict[str, Any], plan: dict[str, Any], success: bool) -> str:
    """构建商品兑换文本推送"""
    context = build_exchange_template_context(title, goods_name, result, plan, success)
    return render_template("exchange_text.txt", context)


def build_feishu_post(title: str, message: str, success: bool) -> dict[str, Any]:
    lines = normalize_message_lines(message)
    summary = build_structured_summary(lines, success)
    content: list[list[dict[str, str]]] = [
        [{"tag": "text", "text": f"状态：{format_status(success)}"}],
        [{"tag": "text", "text": f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}],
    ]
    for section in summary["sections"]:
        content.extend(
            [
                [{"tag": "text", "text": ""}],
                [{"tag": "text", "text": section["label"]}],
                [{"tag": "text", "text": "游戏社区签到"}],
                [{"tag": "text", "text": build_game_section_text(section)}],
                [{"tag": "text", "text": "云游戏签到"}],
                [{"tag": "text", "text": build_cloud_game_section_text(section)}],
                [{"tag": "text", "text": "米游币获取"}],
                [{"tag": "text", "text": build_bbs_section_text(section)}],
            ]
        )
    content.extend(
        [
            [{"tag": "text", "text": ""}],
            [{"tag": "text", "text": "详细日志"}],
            [{"tag": "text", "text": truncate_text("\n".join(lines) or "无详细日志", 12000)}],
        ]
    )
    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def normalize_message_lines(message: str) -> list[str]:
    normalized = message.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n") if line.strip()]
    # "正在..." 只是进度提示，紧跟着的结果行已经说明了成败，推送里留着只会让内容变长
    return [line for line in lines if not line.lstrip().startswith("正在")]


def extract_summary(lines: list[str], success: bool) -> list[str]:
    if not lines:
        return ["无任务日志"]
    summary: list[str] = []
    for line in lines:
        clean = line.removeprefix("# ").strip()
        if is_summary_line(clean):
            summary.append(clean)
    if not success and not summary:
        summary.extend(lines[:5])
    if not summary:
        summary.append("未找到汇总行，查看详细日志确认执行情况")
    return dedupe(summary)[:12]


def extract_stats(summary: list[str]) -> list[tuple[str, str]]:
    text = "\n".join(summary)
    failed = first_number_after(text, "失败")
    gained = first_number_after(text, "本次新增")
    actual = first_number_after(text, "实际已获得")
    return [
        ("结果", "有失败" if failed and failed != "0" else "正常"),
        ("实际获得", actual or "-"),
        ("本次新增", gained or "-"),
    ]


def first_number_after(text: str, keyword: str) -> str:
    index = text.find(keyword)
    if index < 0:
        return ""
    tail = text[index + len(keyword) :]
    number = ""
    for char in tail:
        if char.isdigit():
            number += char
        elif number:
            break
    return number


def is_summary_line(line: str) -> bool:
    keywords = (
        "账号 ",
        "汇总：",
        "成功项：",
        "失败项：",
        "云游戏",
        "社区任务结束：",
        "米游币今日进度：",
        "今日任务已完成",
        DAMAGOU_BALANCE_INSUFFICIENT_MESSAGE,
        "配置 enable=false",
        "没有配置账号",
    )
    return any(keyword in line for keyword in keywords)


def dedupe(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
    return result


def format_status(success: bool) -> str:
    return "成功" if success else "失败"


def escape_markdown_code(text: str) -> str:
    return text.replace("```", "'''")


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 20, 0)] + "\n... 已截断"


def _split_wecom_message(text: str, limit: int) -> list[str]:
    """优先保留完整行，超长单行按 UTF-8 字符边界切分，不丢弃空白。"""
    encoded = text.encode("utf-8")
    parts: list[str] = []
    offset = 0
    while offset < len(encoded):
        part = encoded[offset:offset + limit].decode("utf-8", errors="ignore")
        if offset + limit < len(encoded):
            newline = part.rfind("\n")
            if newline >= 0:
                part = part[:newline + 1]
        parts.append(part)
        offset += len(part.encode("utf-8"))
    return parts or [text]


def send_wecom(client: httpx.Client, webhook: str, msgtype: str, content: str) -> None:
    limit = WECOM_TEXT_MAX_BYTES if msgtype == "text" else WECOM_MARKDOWN_MAX_BYTES
    parts = _split_wecom_message(content, limit)
    with _WECOM_REGISTRY_LOCK:
        lock = _WECOM_SEND_LOCKS.setdefault(webhook, threading.Lock())
    # 同机器人整批串行，避免定时任务、网页测试、兑换推送交错或并发超限。
    with lock:
        for index, part in enumerate(parts, 1):
            delay = _WECOM_NEXT_SEND.get(webhook, 0) - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            try:
                try:
                    response = client.post(webhook, json={"msgtype": msgtype, msgtype: {"content": part}})
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise ValueError(f"HTTP {exc.response.status_code}") from None
                except httpx.RequestError as exc:
                    # 不暴露带密钥的 Webhook，也不盲目重试可能已经送达的消息。
                    raise ValueError(type(exc).__name__) from None
                finally:
                    _WECOM_NEXT_SEND[webhook] = time.monotonic() + WECOM_SEND_INTERVAL
                try:
                    data = response.json()
                except ValueError:
                    raise ValueError("企业微信返回了无效 JSON") from None
                if not isinstance(data, dict) or type(data.get("errcode")) is not int:
                    raise ValueError("企业微信响应缺少有效 errcode")
                if data["errcode"] != 0:
                    raise ValueError(f"企业微信错误码 {data['errcode']}")
            except ValueError as exc:
                raise ValueError(
                    f"第 {index}/{len(parts)} 条发送失败，已成功发送 {index - 1} 条 ({exc})"
                ) from None


def request_json(client: httpx.Client, method: str, url: str, **kwargs: Any) -> None:
    response = client.request(method, url, **kwargs)
    response.raise_for_status()


def request_pushplus(client: httpx.Client, url: str, payload: dict[str, str]) -> None:
    """pushplus 内容过大等业务错误仍返回 HTTP 200，必须看 code 才能判断成败。"""
    response = client.request("POST", url, json=payload)
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        return
    if isinstance(data, dict) and data.get("code") not in (200, None):
        raise ValueError(f"{data.get('msg') or '请求失败'}: {data.get('data') or ''}".strip(": "))


def require(value: str, name: str) -> None:
    if not value:
        raise ValueError(f"缺少 {name}")


def signed_ding_url(webhook: str, secret: str) -> str:
    timestamp = str(round(time.time() * 1000))
    sign_data = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), sign_data, hashlib.sha256).digest()
    sign = quote_plus(base64.b64encode(digest).decode("utf-8"))
    separator = "&" if "?" in webhook else "?"
    return f"{webhook}{separator}timestamp={timestamp}&sign={sign}"


def send_mail(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    mail_from: str,
    mail_to: str,
    title: str,
    message: str,
    html_message: str,
    smtp_ssl: bool,
) -> None:
    require(smtp_host, "smtp_host")
    require(smtp_user, "smtp_user")
    require(smtp_password, "smtp_password")
    require(mail_from, "mail_from")
    require(mail_to, "mail_to")
    email = EmailMessage()
    email["Subject"] = title
    email["From"] = mail_from
    email["To"] = mail_to
    email.set_content(message)
    email.add_alternative(html_message, subtype="html")
    recipients = [item.strip() for item in mail_to.split(",") if item.strip()]
    if smtp_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(email, to_addrs=recipients)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            smtp.starttls()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(email, to_addrs=recipients)
