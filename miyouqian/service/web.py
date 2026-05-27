# -*- coding: utf-8 -*-
"""本地 Web 控制台。"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import mimetypes
import pathlib
import secrets
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import qrcode

from ..auth.login import QRLogin
from ..core.config import load_config, log_path, normalize_config, save_config, validate_unique_account_uids
from ..core.http import ApiClient
from ..core.logs import append_log, configure_logger, format_line, print_startup_banner
from ..tasks.shop_exchange import ShopExchange
from .exchange_scheduler import ExchangeScheduler
from .notifier import is_task_success, send_push, send_exchange_push, push_channels
from .runner import run_tasks
from .scheduler import DailyScheduler

WEB_ROOT = pathlib.Path(__file__).resolve().parents[1] / "webui"

# ---------------------------------------------------------------------------
# 密码认证工具
# ---------------------------------------------------------------------------
AUTH_COOKIE = "myq_token"


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def is_hashed_password(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def check_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    return secrets.compare_digest(hash_password(password), stored_hash)


def is_external_host(host: str) -> bool:
    return host not in ("127.0.0.1", "localhost", "::1")


class WebApp:
    def __init__(self, config_path: pathlib.Path) -> None:
        self.config_path = config_path
        self.config = load_config(config_path)
        self._ensure_password_hashed()
        self.log_file = log_path(config_path, self.config)
        configure_logger(self.log_file)
        self.lock = threading.RLock()
        self.logs: list[str] = []
        self.login_state: dict[str, Any] = {"running": False, "status": "idle"}
        self.scheduler = DailyScheduler(self.config, self.run_all, lambda message: self.log(message, "scheduler"))
        self.exchange_scheduler = ExchangeScheduler(
            self.config,
            self.run_shop_exchange_plan,
            lambda message: self.log(message, "exchange"),
        )
        self._sessions: dict[str, float] = {}

    def _ensure_password_hashed(self) -> None:
        web = self.config.get("web", {})
        password = str(web.get("password", ""))
        if password and not is_hashed_password(password):
            web["password"] = hash_password(password)
            save_config(self.config_path, self.config)

    @property
    def need_auth(self) -> bool:
        web = self.config.get("web", {})
        return is_external_host(str(web.get("host", "127.0.0.1")))

    @property
    def password_is_set(self) -> bool:
        return bool(self.config.get("web", {}).get("password", ""))

    def _create_session(self) -> str:
        token = secrets.token_hex(32)
        with self.lock:
            self._sessions[token] = True
        return token

    def _check_session(self, token: str) -> bool:
        if not token:
            return False
        with self.lock:
            return token in self._sessions

    def _revoke_session(self, token: str) -> None:
        with self.lock:
            self._sessions.pop(token, None)

    def auth_setup(self, password: str) -> str:
        if not self.need_auth:
            raise ValueError("当前为内网模式，无需设置密码")
        if self.password_is_set:
            raise ValueError("密码已设置，不能重复设置")
        if len(password) < 4:
            raise ValueError("密码长度至少 4 位")
        with self.lock:
            self.config.setdefault("web", {})["password"] = hash_password(password)
            save_config(self.config_path, self.config)
        self.log("已设置外网访问密码", "auth")
        return self._create_session()

    def auth_login(self, password: str) -> str:
        if not self.need_auth:
            raise ValueError("当前为内网模式，无需登录")
        stored_hash = self.config.get("web", {}).get("password", "")
        if not stored_hash:
            raise ValueError("密码未设置，请先设置密码")
        if not check_password(password, stored_hash):
            raise ValueError("密码错误")
        return self._create_session()

    def auth_status(self) -> dict[str, Any]:
        return {
            "need_auth": self.need_auth,
            "password_set": self.password_is_set,
        }

    def start(self) -> None:
        self.scheduler.start()
        self.exchange_scheduler.start()

    def stop(self) -> None:
        self.scheduler.stop()
        self.exchange_scheduler.stop()

    def log(self, message: str, component: str = "web") -> None:
        line = format_line(message, component)
        with self.lock:
            self.logs.append(line)
            self.logs = self.logs[-500:]
            log_file = self.log_file
        append_log(log_file, line, component=component)

    def run_all(self) -> list[str]:
        with self.lock:
            config = self.config
        try:
            self.log("任务编排开始", "task")
            lines = run_tasks(
                config,
                str(self.config_path),
                emit_component=lambda message, component: self.log(message, component),
            )
        except Exception as exc:
            push_result = send_push(config, "米游签任务失败", str(exc), success=False)
            if push_result:
                self.log(push_result, "push")
            raise
        self.log("任务编排完成，准备发送推送", "task")
        push_result = send_push(config, "米游签任务完成", "\n".join(lines), success=is_task_success(lines))
        if push_result:
            self.log(push_result, "push")
        return []

    def test_push_channels(self) -> str:
        with self.lock:
            config = copy.deepcopy(self.config)
        channels = push_channels(config.get("push") or {})
        if not channels:
            raise ValueError("请先启用至少一个推送通道")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"这是一条推送测试消息\n发送时间: {now}\n如收到消息，说明该通道可用"
        result = send_push(config, "米游签推送测试", message, success=False)
        if result:
            self.log(result, "push")
        return result or "推送测试已完成"

    def status(self) -> dict[str, Any]:
        with self.lock:
            logs = list(self.logs[-300:])
            login_state = dict(self.login_state)
            shop_exchange = copy.deepcopy(self.config.get("shop_exchange", {}))
        return {
            "scheduler": self.scheduler.status(),
            "exchange_scheduler": self.exchange_scheduler.status(),
            "shop_exchange": shop_exchange,
            "login": login_state,
            "logs": logs,
        }

    def get_config(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.config, ensure_ascii=False))

    def set_config(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise ValueError("配置必须是 JSON 对象")
        normalize_config(payload)
        validate_unique_account_uids(payload)
        with self.lock:
            old_config = copy.deepcopy(self.config)
            preserve_push_channel_secrets(old_config, payload)
            normalize_config(payload)
            changes = diff_config(old_config, payload)
            self.config = payload
            save_config(self.config_path, self.config)
            self.log_file = log_path(self.config_path, self.config)
            configure_logger(self.log_file)
            self.scheduler.reload(self.config)
            self.exchange_scheduler.reload(self.config)
        visible_changes = [change for change in changes if should_log_config_change(*change)]
        if visible_changes:
            self.log(f"配置已保存，共 {len(visible_changes)} 项变更", "config")
            for path, old_value, new_value in visible_changes[:50]:
                self.log(
                    f"配置项变更 {path}: {format_config_value(path, old_value)} -> {format_config_value(path, new_value)}",
                    "config",
                )
            if len(visible_changes) > 50:
                self.log(f"配置项变更过多，已省略 {len(visible_changes) - 50} 项", "config")
        else:
            self.log("配置已保存，未检测到配置项变化", "config")

    def shop_goods(self, game: str = "") -> dict[str, Any]:
        game_label = game or "全部分区"
        self.log(f"开始获取商品列表: {game_label}", "exchange")
        with self.lock:
            config = copy.deepcopy(self.config)
        try:
            with ApiClient(timeout=20.0) as client:
                result = ShopExchange(client, config, emit=lambda message: self.log(message, "exchange")).goods(game=game)
        except Exception as exc:
            self.log(f"商品列表获取失败: {game_label}，{exc}", "exchange")
            raise
        goods_count = len(result.get("goods") or [])
        self.log(f"商品列表获取完成: {game_label}，共 {goods_count} 个商品", "exchange")
        return result

    def shop_good_detail(self, goods_id: str) -> dict[str, Any]:
        self.log(f"开始获取商品详情: {goods_id}", "exchange")
        with self.lock:
            config = copy.deepcopy(self.config)
        try:
            with ApiClient(timeout=20.0) as client:
                result = ShopExchange(client, config).good_detail(goods_id)
        except Exception as exc:
            self.log(f"商品详情获取失败: {goods_id}，{exc}", "exchange")
            raise
        self.log(f"商品详情获取完成: {result.get('goods_name') or goods_id}", "exchange")
        return result

    def ensure_shop_device_fp(self) -> dict[str, Any]:
        self.log("开始预获取商品兑换 device_fp", "exchange")
        with self.lock:
            config = copy.deepcopy(self.config)
        try:
            with ApiClient(timeout=20.0) as client:
                device_fp = ShopExchange(client, config).fetch_device_fp()
        except Exception as exc:
            self.log(f"商品兑换 device_fp 获取失败: {exc}", "exchange")
            raise
        with self.lock:
            self.config.setdefault("device", {})["fp"] = device_fp
            save_config(self.config_path, self.config)
        self.log("已预获取商品兑换 device_fp", "exchange")
        return {"device_fp": device_fp}

    def shop_account_meta(self, account_index: int, game_biz: str = "") -> dict[str, Any]:
        account = self._account_by_index(account_index)
        account_name = display_account_name(account)
        self.log(f"开始获取兑换账号信息: {account_name}，game_biz={game_biz or '无'}", "exchange")
        with self.lock:
            config = copy.deepcopy(self.config)
        with ApiClient(timeout=20.0) as client:
            shop = ShopExchange(client, config, account)
            result: dict[str, Any] = {"points": {}, "addresses": [], "roles": []}
            try:
                result["points"] = shop.points()
            except Exception as exc:
                result["points_error"] = str(exc)
                self.log(f"米游币余额获取失败: {account_name}，{exc}", "exchange")
            try:
                result["addresses"] = shop.addresses()
            except Exception as exc:
                result["addresses_error"] = str(exc)
                self.log(f"收货地址获取失败: {account_name}，{exc}", "exchange")
            if game_biz:
                try:
                    result["roles"] = shop.roles(game_biz)
                except Exception as exc:
                    result["roles_error"] = str(exc)
                    self.log(f"游戏角色获取失败: {account_name}，{game_biz}，{exc}", "exchange")
                    raise
            self.log(
                f"兑换账号信息获取完成: {account_name}，地址 {len(result.get('addresses') or [])} 个，角色 {len(result.get('roles') or [])} 个",
                "exchange",
            )
            return result

    def shop_exchange_once(self, plan: dict[str, Any]) -> dict[str, Any]:
        account = self._account_by_index(int(plan.get("account_index") or 0))
        account_name = display_account_name(account)
        goods_name = str(plan.get("goods_name") or plan.get("goods_id") or "未知商品")
        self.log(f"开始商品兑换: {goods_name}，账号 {account_name}", "exchange")
        if not str(plan.get("device_fp") or "").strip():
            raise ValueError("兑换计划缺少 device_fp，请重新添加计划")
        with self.lock:
            config = copy.deepcopy(self.config)
        try:
            with ApiClient(timeout=15.0) as client:
                result = ShopExchange(
                    client,
                    config,
                    account,
                    emit=lambda message: self.log(message, "exchange"),
                ).exchange_with_retry(plan)
        except Exception as exc:
            self.log(f"商品兑换请求异常: {goods_name}，账号 {account_name}，{exc}", "exchange")
            raise
        summary = f"{result.get('message', '未知结果')}({result.get('retcode')})，请求 {result.get('attempt', 1)} 次"
        self.log(f"商品兑换结束: {goods_name}，账号 {account_name}，{summary}", "exchange")
        return result

    def shop_exchange_plan_once(self, plan_index: int) -> dict[str, Any]:
        with self.lock:
            plans = self.config.get("shop_exchange", {}).get("plans") or []
            shop_config = self.config.get("shop_exchange", {})
            if plan_index < 0 or plan_index >= len(plans):
                raise ValueError("兑换计划不存在")
            plan = copy.deepcopy(plans[plan_index])
            goods_name = plan.get("goods_name") or plan.get("goods_id")
        self.log(f"开始手动执行商品兑换计划 {plan_index + 1}: {goods_name}", "exchange")
        result = self.shop_exchange_once(plan)
        summary = f"{result.get('message', '未知结果')}({result.get('retcode')})，请求 {result.get('attempt', 1)} 次"
        with self.lock:
            plans = self.config.get("shop_exchange", {}).get("plans") or []
            if plan_index < len(plans):
                plans[plan_index]["last_result"] = summary
                plans[plan_index]["last_run"] = datetime.now().isoformat(timespec="seconds")
                plans[plan_index]["last_attempt_key"] = f"manual:{datetime.now().isoformat(timespec='seconds')}"
                if result.get("ok"):
                    plans[plan_index]["enable"] = False
                save_config(self.config_path, self.config)
                self.exchange_scheduler.reload(self.config)
        self.log(f"手动商品兑换计划完成 {plan_index + 1}: {goods_name}，{summary}", "exchange")

        # 发送兑换结果推送
        if shop_config.get("push", False):
            self._send_exchange_push(goods_name, result, plan)

        return result

    def run_shop_exchange_plan(self, plan_index: int) -> None:
        with self.lock:
            plans = self.config.get("shop_exchange", {}).get("plans") or []
            shop_config = self.config.get("shop_exchange", {})
            if plan_index < 0 or plan_index >= len(plans):
                raise ValueError("兑换计划不存在")
            plan = copy.deepcopy(plans[plan_index])
            goods_name = plan.get("goods_name") or plan.get("goods_id")
            exchange_at = int(plan.get("exchange_at") or 0)
            plans[plan_index]["last_attempt_key"] = f"{plan.get('goods_id', '')}:{exchange_at}"
            plans[plan_index]["last_run"] = datetime.now().isoformat(timespec="seconds")
            save_config(self.config_path, self.config)
        self.log(f"开始执行商品兑换计划: {goods_name}", "exchange")
        result = self.shop_exchange_once(plan)
        summary = f"{result.get('message', '未知结果')}({result.get('retcode')})，请求 {result.get('attempt', 1)} 次"
        with self.lock:
            plans = self.config.get("shop_exchange", {}).get("plans") or []
            if plan_index < len(plans):
                plans[plan_index]["last_result"] = summary
                plans[plan_index]["last_run"] = datetime.now().isoformat(timespec="seconds")
                if result.get("ok"):
                    plans[plan_index]["enable"] = False
                save_config(self.config_path, self.config)
                self.exchange_scheduler.reload(self.config)
        self.log(f"商品兑换计划完成: {goods_name}，{summary}", "exchange")

        # 发送兑换结果推送
        if shop_config.get("push", False):
            self._send_exchange_push(goods_name, result, plan)

    def _send_exchange_push(self, goods_name: str, result: dict[str, Any], plan: dict[str, Any]) -> None:
        """发送商品兑换结果推送"""
        with self.lock:
            config = self.config
        try:
            is_success = result.get("ok", False)

            # 构建推送标题
            if is_success:
                title = "🎉 商品兑换成功"
            else:
                title = "❌ 商品兑换失败"

            # 从 account_index 获取账号信息，添加到 plan 中
            plan_with_account = dict(plan)
            account_index = plan.get("account_index")
            if account_index is not None:
                try:
                    account = self._account_by_index(int(account_index))
                    plan_with_account["account"] = display_account_name(account)
                except Exception:
                    plan_with_account["account"] = "未知账号"

            push_result = send_exchange_push(config, title, goods_name, result, plan_with_account, success=is_success)
            if push_result:
                self.log(f"商品兑换推送已发送: {push_result}", "exchange")
        except Exception as exc:
            self.log(f"商品兑换推送发送失败: {exc}", "exchange")

    def _account_by_index(self, account_index: int) -> dict[str, Any]:
        with self.lock:
            accounts = self.config.get("accounts") or []
            if account_index < 0 or account_index >= len(accounts):
                raise ValueError("请选择已登录账号")
            account = copy.deepcopy(accounts[account_index])
        if not str(account.get("cookie") or "").strip():
            raise ValueError("账号未登录或缺少 cookie")
        return account

    def start_login(
        self,
        account_index: int,
        timeout: int,
        account_payload: dict[str, Any] | None = None,
        draft: bool = False,
    ) -> None:
        with self.lock:
            if self.login_state.get("running"):
                raise RuntimeError("扫码登录正在进行")
            accounts = self.config.get("accounts") or []
            if not draft and (account_index < 0 or account_index >= len(accounts)):
                raise ValueError("请先添加账号")
            account_snapshot = dict(account_payload or {})
            if not draft:
                account_snapshot = dict(accounts[account_index])
            account_name = display_account_name(account_snapshot)
            self.login_state = {
                "running": True,
                "status": "starting",
                "account_index": account_index,
                "account": account_name,
                "draft": draft,
                "message": "正在生成二维码",
                "qr": "",
            }
        thread = threading.Thread(
            target=self._login_worker,
            args=(account_index, timeout, account_snapshot, draft),
            name="miyouqian-web-login",
            daemon=True,
        )
        thread.start()
        self.log(f"账号 {account_name} 开始扫码登录", "auth")

    def _login_worker(
        self,
        account_index: int,
        timeout: int,
        account_snapshot: dict[str, Any],
        draft: bool,
    ) -> None:
        try:
            with self.lock:
                device = dict(self.config["device"])
                account_name = display_account_name(account_snapshot)
            with ApiClient() as client:
                login = QRLogin(client, str(device["id"]), str(device["fp"]))
                url, ticket = login.fetch()
                qr = make_qr_data_uri(url)
                with self.lock:
                    self.login_state.update(
                        {
                            "status": "waiting",
                            "message": "等待扫码确认",
                            "qr": qr,
                            "qr_url": url,
                        }
                    )
                self.log(f"账号 {account_name} 等待扫码登录", "auth")
                scan = login.wait(ticket, timeout=timeout)
                with self.lock:
                    self.login_state.update({"status": "exchanging", "message": "正在换取凭证"})
                account_data = login.exchange_tokens(scan["uid"], scan["game_token"])
            with self.lock:
                new_uid = str(account_data.get("stuid") or "").strip()
                duplicate = find_duplicate_uid(self.config.get("accounts") or [], new_uid, None if draft else account_index)
                if duplicate is not None:
                    raise ValueError(f"UID {new_uid} 已存在，不能重复添加同一账号")
                account = {**account_snapshot, **account_data}
                if not str(account.get("name") or "").strip():
                    account["name"] = account_data["stuid"]
                if not draft:
                    self.config["accounts"][account_index] = account
                    save_config(self.config_path, self.config)
                    self.log_file = log_path(self.config_path, self.config)
                    configure_logger(self.log_file)
                    self.scheduler.reload(self.config)
                account_name = display_account_name(account)
                self.login_state.update(
                    {
                        "running": False,
                        "status": "success",
                        "message": f"账号 {account_name} 登录成功" + ("，请保存账号" if draft else ""),
                        "qr": "",
                        "account_data": account_data,
                    }
                )
            if draft:
                self.log(f"账号 {account_name} 登录成功，等待保存", "auth")
            else:
                self.log(f"账号 {account_name} 登录成功，凭证已保存", "auth")
        except Exception as exc:
            with self.lock:
                self.login_state.update(
                    {
                        "running": False,
                        "status": "error",
                        "message": str(exc),
                        "qr": "",
                    }
                )
            self.log(f"扫码登录失败: {exc}", "auth")


def make_qr_data_uri(text: str) -> str:
    image = qrcode.make(text)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    encoded = base64.b64encode(stream.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def display_account_name(account: dict[str, Any]) -> str:
    return str(account.get("name") or account.get("stuid") or "未命名账号")


def find_duplicate_uid(accounts: list[dict[str, Any]], uid: str, exclude_index: int | None = None) -> int | None:
    if not uid:
        return None
    for index, account in enumerate(accounts):
        if exclude_index is not None and index == exclude_index:
            continue
        if str(account.get("stuid") or "").strip() == uid:
            return index
    return None


def preserve_push_channel_secrets(old_config: dict[str, Any], new_config: dict[str, Any]) -> None:
    old_channels = {
        str(channel.get("provider") or ""): channel
        for channel in old_config.get("push", {}).get("channels", [])
        if isinstance(channel, dict)
    }
    new_push = new_config.setdefault("push", {})
    new_channels = new_push.setdefault("channels", [])
    if not isinstance(new_channels, list):
        new_push["channels"] = []
        return
    for channel in new_channels:
        if not isinstance(channel, dict):
            continue
        provider = str(channel.get("provider") or "")
        old_channel = old_channels.get(provider)
        if not old_channel:
            continue
        for key, value in old_channel.items():
            if key not in channel or channel.get(key) in (None, ""):
                channel[key] = value


def diff_config(old: Any, new: Any, path: str = "") -> list[tuple[str, Any, Any]]:
    if type(old) is not type(new):
        return [(path or "<root>", old, new)]
    if isinstance(old, dict):
        changes: list[tuple[str, Any, Any]] = []
        keys = sorted(set(old) | set(new), key=str)
        for key in keys:
            child_path = f"{path}.{key}" if path else str(key)
            if key not in old:
                changes.extend(diff_added_config(new[key], child_path))
            elif key not in new:
                changes.extend(diff_removed_config(old[key], child_path))
            else:
                changes.extend(diff_config(old[key], new[key], child_path))
        return changes
    if isinstance(old, list):
        changes = []
        common = min(len(old), len(new))
        for index in range(common):
            changes.extend(diff_config(old[index], new[index], f"{path}[{index}]"))
        for index in range(common, len(old)):
            changes.extend(diff_removed_config(old[index], f"{path}[{index}]"))
        for index in range(common, len(new)):
            changes.extend(diff_added_config(new[index], f"{path}[{index}]"))
        return changes
    if old != new:
        return [(path or "<root>", old, new)]
    return []


def diff_added_config(value: Any, path: str) -> list[tuple[str, Any, Any]]:
    if isinstance(value, dict):
        changes: list[tuple[str, Any, Any]] = []
        for key in sorted(value, key=str):
            changes.extend(diff_added_config(value[key], f"{path}.{key}"))
        return changes
    if isinstance(value, list):
        changes = []
        for index, item in enumerate(value):
            changes.extend(diff_added_config(item, f"{path}[{index}]"))
        return changes
    return [(path, None, value)]


def diff_removed_config(value: Any, path: str) -> list[tuple[str, Any, Any]]:
    if isinstance(value, dict):
        changes: list[tuple[str, Any, Any]] = []
        for key in sorted(value, key=str):
            changes.extend(diff_removed_config(value[key], f"{path}.{key}"))
        return changes
    if isinstance(value, list):
        changes = []
        for index, item in enumerate(value):
            changes.extend(diff_removed_config(item, f"{path}[{index}]"))
        return changes
    return [(path, value, None)]


def format_config_value(path: str, value: Any) -> str:
    if is_sensitive_config_path(path):
        return mask_sensitive_value(value)
    text = json.dumps(redact_config_value(value), ensure_ascii=False, sort_keys=True)
    if len(text) > 120:
        return text[:117] + "..."
    return text


def redact_config_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: mask_sensitive_value(child) if is_sensitive_config_path(str(key)) else redact_config_value(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_config_value(item) for item in value]
    return value


def mask_sensitive_value(value: Any) -> str:
    return "<空>" if value in (None, "") else "<已设置>"


def should_log_config_change(path: str, old_value: Any, new_value: Any) -> bool:
    if format_config_value(path, old_value) == format_config_value(path, new_value):
        return False
    if old_value is None and new_value in ("", [], {}, None):
        return False
    if old_value is None and path.startswith("push.channels[") and path.rsplit(".", 1)[-1] in {"smtp_port", "smtp_ssl"}:
        return False
    return True


def is_sensitive_config_path(path: str) -> bool:
    sensitive_names = {
        "cookie",
        "stoken",
        "mid",
        "token",
        "tokens",
        "webhook",
        "userkey",
        "secret",
        "password",
        "smtp_password",
        "fp",
    }
    parts = [part.split("[", 1)[0].lower() for part in path.replace("]", "").split(".")]
    return any(part in sensitive_names or part.endswith("_token") for part in parts)


def first_query(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    if not values:
        return default
    return values[0]


class Handler(BaseHTTPRequestHandler):
    app: WebApp

    def log_message(self, format: str, *args: object) -> None:
        return

    def _get_cookie(self, name: str) -> str:
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith(f"{name}="):
                return part[len(name) + 1:]
        return ""

    def _is_authenticated(self) -> bool:
        if not self.app.need_auth:
            return True
        token = self._get_cookie(AUTH_COOKIE)
        return self.app._check_session(token)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/auth/status":
                self.send_json(self.app.auth_status())
                return
            if not self._is_authenticated() and path.startswith("/api/"):
                self.send_error_json("未登录", HTTPStatus.UNAUTHORIZED)
                return
            if path == "/api/config":
                self.send_json(self.app.get_config())
                return
            if path == "/api/status":
                self.send_json(self.app.status())
                return
            if path == "/api/shop/goods":
                self.send_json(self.app.shop_goods(str(first_query(query, "game"))))
                return
            if path == "/api/shop/good-detail":
                self.send_json(self.app.shop_good_detail(str(first_query(query, "goods_id"))))
                return
            if path == "/api/shop/account-meta":
                account_index = int(first_query(query, "account_index", "0") or 0)
                game_biz = str(first_query(query, "game_biz", ""))
                self.send_json(self.app.shop_account_meta(account_index, game_biz))
                return
            if path == "/api/shop/device-fp":
                self.send_json(self.app.ensure_shop_device_fp())
                return
            self.serve_static(path)
        except Exception as exc:
            self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/auth/setup":
                token = self.app.auth_setup(str(payload.get("password", "")))
                self.send_json({"ok": True}, set_cookie=token)
                return
            if path == "/api/auth/login":
                token = self.app.auth_login(str(payload.get("password", "")))
                self.send_json({"ok": True}, set_cookie=token)
                return
            if not self._is_authenticated():
                self.send_error_json("未登录", HTTPStatus.UNAUTHORIZED)
                return
            if path == "/api/config":
                self.app.set_config(payload)
                self.send_json({"ok": True})
                return
            if path == "/api/push/test":
                result = self.app.test_push_channels()
                self.send_json({"ok": True, "result": result})
                return
            if path == "/api/run":
                self.app.log("收到手动执行请求", "web")
                started = self.app.scheduler.run_now()
                if not started:
                    self.app.log("手动执行请求被拒绝：任务正在运行", "scheduler")
                    self.send_error_json("任务正在运行", HTTPStatus.CONFLICT)
                    return
                self.send_json({"ok": True})
                return
            if path == "/api/login/start":
                account_index = int(payload.get("account_index", -1))
                timeout = int(payload.get("timeout") or 120)
                account_payload = payload.get("account")
                if account_payload is not None and not isinstance(account_payload, dict):
                    raise ValueError("账号数据必须是 JSON 对象")
                self.app.start_login(account_index, timeout, account_payload, bool(payload.get("draft")))
                self.send_json({"ok": True})
                return
            if path == "/api/shop/exchange":
                if "plan_index" in payload:
                    result = self.app.shop_exchange_plan_once(int(payload.get("plan_index")))
                    self.send_json({"ok": True, "result": result, "config": self.app.get_config()})
                    return
                plan = payload.get("plan")
                if not isinstance(plan, dict):
                    raise ValueError("兑换计划必须是 JSON 对象")
                result = self.app.shop_exchange_once(plan)
                # 处理直接传递plan的情况，也需要推送支持
                shop_config = self.app.config.get("shop_exchange", {})
                if shop_config.get("push", False):
                    goods_name = plan.get("goods_name") or plan.get("goods_id") or "未知商品"
                    self.app._send_exchange_push(goods_name, result, plan)
                self.send_json({"ok": True, "result": result})
                return
            self.send_error_json("接口不存在", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_error_json(str(exc), HTTPStatus.BAD_REQUEST)

    def serve_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        relative = pathlib.Path(unquote(path).lstrip("/"))
        target = (WEB_ROOT / relative).resolve()
        root = WEB_ROOT.resolve()
        if root not in target.parents and target != root:
            self.send_error_json("路径非法", HTTPStatus.FORBIDDEN)
            return
        if not target.exists() or not target.is_file():
            self.send_error_json("文件不存在", HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        try:
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            return

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK, set_cookie: str = "") -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            if set_cookie:
                # 7 天过期 (7 * 24 * 60 * 60 = 604800 秒)
                self.send_header("Set-Cookie", f"{AUTH_COOKIE}={set_cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age=604800")
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            return

    def send_error_json(self, message: str, status: HTTPStatus) -> None:
        self.send_json({"ok": False, "error": message}, status=status)


def serve(config_path: pathlib.Path, host: str, port: int) -> None:
    app = WebApp(config_path)
    Handler.app = app
    print_startup_banner("MYQ")
    app.log(f"正在启动 Web 控制台，配置文件: {config_path.resolve()}", "startup")
    if app.need_auth and not app.password_is_set:
        app.log("外网模式已启用，首次访问时请设置访问密码", "auth")
    server, actual_port = create_server(host, port)
    if actual_port != port:
        app.log(f"端口 {port} 被占用，已切换到 {actual_port}", "startup")
    app.start()

    # 显示可访问的地址
    if host == "0.0.0.0":
        # 外网模式，显示本地访问地址
        local_url = f"http://127.0.0.1:{actual_port}"
        app.log(f"Web 控制台已启动: {local_url}", "web")
        app.log("外网访问请替换为实际 IP 地址", "web")
    else:
        url = f"http://{host}:{actual_port}"
        app.log(f"Web 控制台已启动: {url}", "web")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        app.log("收到退出信号，正在停止 Web 控制台", "startup")
    finally:
        app.stop()
        server.server_close()
        app.log("Web 控制台已停止", "startup")


def create_server(host: str, port: int) -> tuple[ThreadingHTTPServer, int]:
    last_error: OSError | None = None
    for candidate in range(port, port + 30):
        try:
            return ThreadingHTTPServer((host, candidate), Handler), candidate
        except OSError as exc:
            last_error = exc
            if getattr(exc, "winerror", None) not in (10013, 10048):
                raise
    raise OSError(f"端口 {port}-{port + 29} 都无法监听: {last_error}")
