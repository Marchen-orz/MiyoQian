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
import time
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Callable
from urllib.parse import quote_plus

import httpx

PUSH_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parents[1] / "templates" / "push"


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
            request_json(client, "POST", url, json=payload)
        except Exception:
            payload = pushplus_payload(
                token, title, build_exchange_markdown(title, goods_name, result, plan, success), "markdown", topic
            )
            request_json(client, "POST", url, json=payload)
        return

    if provider == "telegram":
        require(token, "token")
        require(chat_id, "chat_id")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
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

    if provider in {"dingrobot", "dingtalk", "钉钉"}:
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

    if provider in {"feishubot", "feishu", "飞书"}:
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
        request_json(client, "POST", webhook, json={"msg_type": "text", "content": {"text": "\n".join(lines)}})
        return

    if provider in {"email", "smtp", "mail", "邮箱"}:
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

    raise ValueError(f"不支持的推送通道: {provider}")


def _send(client: httpx.Client, provider: str, push: dict[str, Any], title: str, message: str, success: bool) -> None:
    token = str(push.get("token") or "").strip()
    webhook = str(push.get("webhook") or "").strip()
    topic = str(push.get("topic") or "").strip()
    chat_id = str(push.get("chat_id") or "").strip()
    secret = str(push.get("secret") or "").strip()
    smtp_host = str(push.get("smtp_host") or "").strip()
    smtp_port = int(push.get("smtp_port") or 465)
    smtp_user = str(push.get("smtp_user") or "").strip()
    smtp_password = str(push.get("smtp_password") or "").strip()
    mail_from = str(push.get("mail_from") or smtp_user).strip()
    mail_to = str(push.get("mail_to") or "").strip()
    smtp_ssl = bool(push.get("smtp_ssl", True))
    markdown_message = build_push_markdown(title, message, success)
    plain_message = build_push_text(title, message, success)

    if provider == "pushplus":
        require(token, "token")
        url = "https://www.pushplus.plus/send"
        payload = pushplus_payload(token, title, build_push_html(title, message, success), "html", topic)
        try:
            request_json(client, "POST", url, json=payload)
        except Exception:
            request_json(client, "POST", url, json=pushplus_payload(token, title, markdown_message, "markdown", topic))
        return

    if provider == "telegram":
        require(token, "token")
        require(chat_id, "chat_id")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        request_json(
            client,
            "POST",
            url,
            json={"chat_id": chat_id, "text": build_telegram_html(title, message, success), "parse_mode": "HTML"},
        )
        return

    if provider in {"dingrobot", "dingtalk", "钉钉"}:
        require(webhook, "webhook")
        url = signed_ding_url(webhook, secret) if secret else webhook
        request_json(client, "POST", url, json={"msgtype": "markdown", "markdown": {"title": title, "text": markdown_message}})
        return

    if provider in {"feishubot", "feishu", "飞书"}:
        require(webhook, "webhook")
        request_json(client, "POST", webhook, json=build_feishu_post(title, message, success))
        return

    if provider in {"email", "smtp", "mail", "邮箱"}:
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

    raise ValueError(f"不支持的推送通道: {provider}")


def build_push_html(title: str, message: str, success: bool) -> str:
    return render_template("html.html", build_template_context(title, message, success))


def pushplus_payload(token: str, title: str, content: str, template: str, topic: str = "") -> dict[str, str]:
    payload = {"token": token, "title": title, "content": content, "template": template}
    if topic:
        payload["topic"] = topic
    return payload


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
    message = result.get("message", "未知结果")
    attempt = result.get("attempt", 1)

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
        "message": html.escape(message),
        "message_text": message,
        "attempt": str(attempt),
        "exchange_time": exchange_time,
        "icon_html": icon_html,
        "detail_html": html.escape(f"结果：{message}({retcode})，尝试 {attempt} 次"),
        "detail_text": f"结果：{message}({retcode})，尝试 {attempt} 次",
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
            <details{open_attr} style="border:1px solid #d8e4ef;border-radius:8px;background:#ffffff;margin-bottom:12px;overflow:hidden;">
              <summary style="cursor:pointer;list-style:none;padding:13px 14px;background:#f1f7fc;color:#102033;font-size:15px;font-weight:800;">
                {html.escape(section["label"])}
                <span style="float:right;color:#627389;font-size:12px;font-weight:600;">点击切换</span>
              </summary>
              <div style="padding:12px;">
                <div style="margin-bottom:10px;">{build_game_section_html(section)}</div>
                <div style="margin-bottom:10px;">{build_cloud_game_section_html(section)}</div>
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
    <div style="border:1px solid #d8e4ef;border-radius:8px;padding:14px;background:#ffffff;">
      <div style="font-size:16px;font-weight:800;color:#102033;margin-bottom:8px;">游戏社区签到</div>
      {progress_html(game["percent"], game["label"], "#168df5")}
      <div style="margin-top:8px;color:#627389;font-size:13px;line-height:1.5;">{html.escape(game["summary"] or "无汇总信息")}</div>
      {item_rows}
    </div>
    """.strip()


def build_cloud_game_section_html(summary: dict[str, Any]) -> str:
    cloud = summary["cloud_game"]
    if not cloud["present"]:
        return section_empty_html("云游戏签到", "本次未执行云游戏签到")
    item_rows = build_result_items_html(cloud)
    return f"""
    <div style="border:1px solid #d8e4ef;border-radius:8px;padding:14px;background:#ffffff;">
      <div style="font-size:16px;font-weight:800;color:#102033;margin-bottom:8px;">云游戏签到</div>
      {progress_html(cloud["percent"], cloud["label"], "#168df5")}
      <div style="margin-top:8px;color:#627389;font-size:13px;line-height:1.5;">{html.escape(cloud["summary"] or "无汇总信息")}</div>
      {item_rows}
    </div>
    """.strip()


def build_result_items_html(result: dict[str, Any]) -> str:
    rows: list[str] = []
    for item in result["failed_items"][:6]:
        rows.append(result_item_html("失败", item, "#b83b4b", "#fdecef"))
    for item in result["items"][:6]:
        rows.append(result_item_html("成功", item, "#1c7c61", "#edf8f3"))
    if not rows:
        return ""
    return '<div style="margin-top:10px;border-top:1px solid #edf3f8;">' + "".join(rows) + "</div>"


def result_item_html(label: str, item: str, color: str, bg: str) -> str:
    return f"""
    <div style="padding:8px 0;border-bottom:1px solid #edf3f8;font-size:13px;line-height:1.5;">
      <span style="display:inline-block;min-width:34px;text-align:center;border-radius:999px;background:{html.escape(bg)};color:{html.escape(color)};font-weight:700;margin-right:8px;">{html.escape(label)}</span>
      <span style="color:#102033;">{html.escape(shorten_text(item, 120))}</span>
    </div>
    """.strip()


def build_bbs_section_html(summary: dict[str, Any]) -> str:
    bbs = summary["bbs"]
    if not bbs["present"]:
        return section_empty_html("米游币获取", "本次未执行米游币任务")
    task_rows = "".join(
        f"""
        <div style="padding:10px 0;border-top:1px solid #edf3f8;">
          <div style="font-size:13px;margin-bottom:6px;">
            <span style="font-weight:700;color:#102033;">{html.escape(task["name"])}</span>
            <span style="float:right;color:{html.escape(task["color"])};">{html.escape(task["label"])} · {task["done"]}/{task["total"]}</span>
          </div>
          {progress_html(task["percent"], "", task["color"], compact=True)}
        </div>
        """.strip()
        for task in bbs["tasks"]
    )
    return f"""
    <div style="border:1px solid #d8e4ef;border-radius:8px;padding:14px;background:#ffffff;">
      <div style="font-size:16px;font-weight:800;color:#102033;margin-bottom:8px;">米游币获取</div>
      <div style="font-size:13px;color:#627389;margin-bottom:10px;line-height:1.6;">
        今日 <strong style="color:#102033;font-size:18px;">{bbs["today_done_points"]}/{bbs["possible_points"]}</strong>
        <span style="margin-left:8px;">实际 {bbs["actual_points"]}</span>
        <span style="margin-left:8px;">新增 {bbs["gained_points"]}</span>
        <span style="margin-left:8px;">总计 {bbs["total_points"] or "-"}</span>
      </div>
      {progress_html(bbs["point_percent"], f'今日进度 {bbs["point_percent"]}%', "#168df5")}
      {task_rows}
    </div>
    """.strip()


def section_empty_html(title: str, message: str) -> str:
    return f"""
    <div style="border:1px solid #d8e4ef;border-radius:8px;padding:16px;background:#ffffff;">
      <div style="font-size:16px;font-weight:800;color:#102033;margin-bottom:8px;">{html.escape(title)}</div>
      <div style="color:#627389;font-size:13px;">{html.escape(message)}</div>
    </div>
    """.strip()


def progress_html(percent: int, label: str, color: str, compact: bool = False) -> str:
    percent = clamp_percent(percent)
    height = 6 if compact else 8
    label_html = f'<div style="margin-top:5px;color:#627389;font-size:12px;">{html.escape(label)}</div>' if label else ""
    return f"""
    <div>
      <div style="height:{height}px;border-radius:999px;background:#d8e4ef;overflow:hidden;">
        <div style="width:{percent}%;height:{height}px;background:{html.escape(color)};"></div>
      </div>
      {label_html}
    </div>
    """.strip()


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
        f"- 进度 {text_bar(result['percent'])} {result['label']}",
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
        lines.append(f"- {task['name']} {text_bar(task['percent'])} {task['label']} ({task['done']}/{task['total']})")
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


def build_result_summary(summary: str, success_items: list[str], failed_items: list[str], success: bool) -> dict[str, Any]:
    counts = parse_counts(summary)
    total = sum(counts)
    percent = round(counts[0] / total * 100) if total else (100 if success and summary else 0)
    return {
        "present": bool(summary or success_items or failed_items),
        "summary": summary,
        "success": counts[0],
        "failed": counts[1],
        "skipped": counts[2],
        "percent": percent,
        "label": f"{counts[0]}/{total or counts[0]} 成功",
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
) -> dict[str, Any]:
    completed_by_skip = any(any(keyword in line for keyword in skip_keywords) for line in lines)
    started = sum(1 for line in lines if start_matcher(line))
    done = count_task_items(success_items, item_keywords)
    failed = count_task_items(failed_items, item_keywords)
    if not success_items and not failed_items:
        done = count_keyword_hits(lines, done_keywords)
        failed = count_keyword_hits(lines, fail_keywords)
    if completed_by_skip:
        total = max(target, started, done, failed, 1)
        done = max(done, total)
    elif started:
        total = max(started, done + failed, 1)
    elif done or failed:
        total = max(done + failed, 1)
    else:
        total = max(target, 1)
    percent = round(done / total * 100)
    if failed:
        label = f"失败 {failed}"
        color = "#b83b4b"
    elif done >= total:
        label = "完成"
        color = "#168df5"
    elif done > 0:
        label = "部分完成"
        color = "#a86d12"
    else:
        label = "未执行"
        color = "#627389"
    return {
        "name": name,
        "done": min(done, total),
        "total": total,
        "failed": failed,
        "percent": percent,
        "label": label,
        "color": color,
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


def is_task_success(lines: list[str]) -> bool:
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
    return [line.rstrip() for line in normalized.split("\n") if line.strip()]


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


def request_json(client: httpx.Client, method: str, url: str, **kwargs: Any) -> None:
    response = client.request(method, url, **kwargs)
    response.raise_for_status()


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
