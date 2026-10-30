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
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import qrcode

from ..auth.login import AigisRequired, CaptchaLogin, QRLogin, _QrRefreshed
from ..core import cookies
from ..core import device as devicelib
from ..core.config import (
    PUSH_CHANNEL_DEFAULTS,
    PUSH_CHANNEL_FIELDS,
    bind_shop_plan_accounts,
    find_account_index_by_stuid,
    find_shop_plan,
    load_config,
    log_path,
    normalize_config,
    normalize_push_channels,
    preserve_shop_plan_runtime,
    save_config,
    validate_unique_account_uids,
)
from ..core.http import ApiClient
from ..core.logs import append_log, configure_logger, format_line, print_startup_banner
from ..core.profile import fetch_avatar_url, fetch_os_avatar_url
from ..core.qq_bot import bind_openid as bind_qq_openid
from ..core.qq_bot import generate_verify_code
from ..core.region import REGION_CN, REGION_OS, account_region
from ..overseas.checkin import probe_hoyolab_cookie
from ..overseas.cookie import parse_hoyolab_cookie
from ..tasks.shop_exchange import ShopExchange
from .exchange_scheduler import ExchangeScheduler
from .notifier import send_push, send_task_push, send_exchange_push, push_channels
from .runner import run_tasks
from .scheduler import DailyScheduler

WEB_ROOT = pathlib.Path(__file__).resolve().parents[1] / "webui"

# 标准库的 mimetypes 在部分环境（含 Docker 的 Python 3.11）不认识 .webp，
# 不注册的话头像会被当成 application/octet-stream 发出去
mimetypes.add_type("image/webp", ".webp")

# QQ 官方机器人绑定 OpenID 的等待时间，和页面提示保持一致
QQ_BIND_TIMEOUT = 90

# 账号头像的缓存时间：取到的留一天，没取到的（网络、接口异常）过几分钟再试
AVATAR_CACHE_SECONDS = 24 * 3600
AVATAR_RETRY_SECONDS = 300
AVATAR_MAX_UIDS = 20

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


def summarize_exchange_result(result: dict[str, Any]) -> str:
    """写进计划 last_result 的一句话。执行本身出了异常时没有 retcode，直接用异常说明。"""
    if result.get("error"):
        return str(result.get("message") or "异常")
    return f"{result.get('message', '未知结果')}({result.get('retcode')})，请求 {result.get('attempt', 1)} 次"


class WebApp:
    def __init__(self, config_path: pathlib.Path, host: str = "127.0.0.1", port: int = 5890) -> None:
        self.config_path = config_path
        self.config = load_config(config_path)
        self.host = host
        self.port = port
        self._ensure_password_hashed()
        self.log_file = log_path(config_path, self.config)
        configure_logger(self.log_file)
        self.lock = threading.RLock()
        self.logs: list[str] = []
        self.login_state: dict[str, Any] = {"running": False, "status": "idle"}
        self._qr_refresh = threading.Event()
        self._login_cancel = threading.Event()
        self._login_generation = 0
        self.qq_bind_state: dict[str, Any] = {"running": False, "status": "idle"}
        self._qq_bind_cancel = threading.Event()
        self.scheduler = DailyScheduler(self.config, self.run_all, lambda message: self.log(message, "scheduler"))
        self.exchange_scheduler = ExchangeScheduler(
            self.config,
            self.run_shop_exchange_plan,
            lambda message: self.log(message, "exchange"),
        )
        self._sessions: dict[str, float] = {}
        # uid -> (过期时间, 头像地址)，空地址表示这次没取到
        self._avatar_cache: dict[str, tuple[float, str]] = {}

    def _ensure_password_hashed(self) -> None:
        web = self.config.get("web", {})
        password = str(web.get("password", ""))
        if password and not is_hashed_password(password):
            web["password"] = hash_password(password)
            save_config(self.config_path, self.config)

    @property
    def need_auth(self) -> bool:
        # 为了保证不会因为命令行参数、配置文件在无意间被调整导致 Web 控制台泄露到本机之外，要求首次访问 Web 控制台时必须设置一个外网访问密码
        stored_hash = self.config.get("web", {}).get("password", "")
        if not stored_hash:
            return True
        return is_external_host(str(self.host))

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
        if self.password_is_set:
            raise ValueError("密码已设置，不能重复设置")
        if len(password) < 8:
            raise ValueError("密码长度至少 8 位")
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
        push_result = send_task_push(config, lines)
        if push_result:
            self.log(push_result, "push")
        return []

    def test_push_channels(self, channel: dict[str, Any] | None = None) -> str:
        with self.lock:
            config = copy.deepcopy(self.config)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"这是一条推送测试消息\n发送时间: {now}\n如收到消息，说明该通道可用"
        if isinstance(channel, dict) and channel.get("provider"):
            # 弹窗里的参数可能还没保存，测试直接用它算出来的通道。
            # 这里拼一份只含该通道、总开关打开的临时配置，复用普通的 send_push，
            # 不依赖 notifier 额外参数，旧版 notifier 也能正常工作。
            targets = normalize_push_channels({"channels": [channel]})
            if not targets:
                raise ValueError("请先填写该通道的参数")
            # send_push 只会发 enable 的通道，这里强制标记一下
            for target in targets:
                target["enable"] = True
            scoped = {"push": {"enable": True, "error_only": False, "channels": targets}}
            result = send_push(scoped, "米游签推送测试", message, success=False)
        else:
            if not push_channels(config.get("push") or {}):
                raise ValueError("请先启用至少一个推送通道")
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
            preserve_shop_plan_runtime(old_config, payload)
            # 设备档案只通过「设备信息」的专用接口改；页面里那份可能是旧的，
            # 照单全收会把刚申请到的 device_fp 覆盖掉
            payload["device"] = copy.deepcopy(old_config["device"])
            normalize_config(payload)
            bind_shop_plan_accounts(payload)
            self._guard_running_plans(old_config, payload)
            changes = diff_config(old_config, payload)
            self.config = payload
            save_config(self.config_path, self.config)
            self.log_file = log_path(self.config_path, self.config)
            configure_logger(self.log_file)
            self.scheduler.reload(self.config)
            self.exchange_scheduler.reload(self.config)
            # AppID/AppSecret 可能刚被改过，正在跑的绑定用的还是旧凭证，结果不可信
            if self.qq_bind_state.get("running"):
                self._qq_bind_cancel.set()
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

    def _guard_running_plans(self, old_config: dict[str, Any], payload: dict[str, Any]) -> None:
        """正在兑换的计划不能删，也不能改会影响这次请求的字段（页面也会拦，这里兜底旧页面）。"""
        guarded = ("goods_id", "exchange_at", "account_stuid", "address_id", "uid", "region", "game_biz")
        new_plans = {plan.get("id"): plan for plan in (payload.get("shop_exchange") or {}).get("plans") or []}
        for plan_id in self.exchange_scheduler.status().get("running_plans", []):
            old = find_shop_plan(old_config, plan_id)
            if old is None:
                continue
            new = new_plans.get(plan_id)
            if new is None:
                raise ValueError("该兑换计划正在执行，暂不能删除")
            if any(old.get(key) != new.get(key) for key in guarded):
                raise ValueError("该兑换计划正在执行，暂不能修改")

    def account_avatars(self, keys: list[str]) -> dict[str, Any]:
        """账号头像地址。键写成 uid（国服）或 os:uid（国际服），两边的 UID 可能撞号。

        纯展示用，取不到的账号不出现在结果里，页面继续用默认头像。
        """
        keys = list(dict.fromkeys(key for key in map(parse_avatar_key, keys) if key))
        keys = keys[:AVATAR_MAX_UIDS]
        now = time.monotonic()
        with self.lock:
            cached = {key: self._avatar_cache[key] for key in keys if key in self._avatar_cache}
        pending = [key for key in keys if key not in cached or cached[key][0] <= now]
        fresh: dict[str, tuple[float, str]] = {}
        if pending:
            def lookup(key: str) -> tuple[str, tuple[float, str]]:
                region, sep, uid = key.partition(":")
                if not sep:
                    region, uid = REGION_CN, key
                fetch = fetch_os_avatar_url if region == REGION_OS else fetch_avatar_url
                try:
                    return key, (now + AVATAR_CACHE_SECONDS, fetch(client, uid))
                except Exception as exc:
                    self.log(f"账号头像获取失败: {key}，{exc}", "web")
                    return key, (now + AVATAR_RETRY_SECONDS, "")

            # 网络差时单个请求可能要等很久（比如 IPv6 不通要先等超时），并发取免得账号越多越慢
            with ApiClient(timeout=8.0) as client, ThreadPoolExecutor(max_workers=min(len(pending), 5)) as pool:
                fresh = dict(pool.map(lookup, pending))
            with self.lock:
                self._avatar_cache.update(fresh)
        known = {**cached, **fresh}
        return {"avatars": {key: known[key][1] for key in keys if known[key][1]}}

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

    def ensure_device_fp(
        self, client: ApiClient, force: bool = False, component: str = "device"
    ) -> tuple[bool, str]:
        """保证设备档案里有可信的 device_fp，新申请到的立刻落盘。返回 (是否可信, 失败原因)。"""
        with self.lock:
            device = self.config["device"]
        before = (devicelib.effective_fp(device), device.get("fp_source"))
        ok, reason = devicelib.ensure_device_fp(
            client, device, force=force, emit=lambda message: self.log(message, component)
        )
        if (devicelib.effective_fp(device), device.get("fp_source")) != before:
            with self.lock:
                live = self.config["device"]
                # 申请期间页面刚好保存过配置时 self.config 已经换了一份，把结果同步过去
                if live is not device and live.get("id") == device.get("id"):
                    live.update({key: device[key] for key in ("fp", "fp_source", "fp_time")})
                save_config(self.config_path, self.config)
        return ok, reason

    def ensure_shop_device_fp(self) -> dict[str, Any]:
        """兑换计划用的 device_fp：和其它请求共用设备档案里那一枚，不再单独申请、覆盖。"""
        self.log("开始预获取商品兑换 device_fp", "exchange")
        with ApiClient(timeout=20.0) as client:
            ok, reason = self.ensure_device_fp(client, component="exchange")
        with self.lock:
            device_fp = devicelib.effective_fp(self.config["device"])
        if not device_fp:
            self.log(f"商品兑换 device_fp 获取失败: {reason}", "exchange")
            raise RuntimeError(f"device_fp 获取失败: {reason}。可以在「设备信息」里导入真机的 device_fp")
        if not ok:
            self.log(f"向服务器申请 device_fp 失败（{reason}），先沿用已有的", "exchange")
        self.log("已预获取商品兑换 device_fp", "exchange")
        return {"device_fp": device_fp}

    def device_info(self) -> dict[str, Any]:
        with self.lock:
            return devicelib.device_view(self.config["device"])

    def import_device(self, text: str) -> dict[str, Any]:
        parsed = devicelib.parse_device_import(text)
        with self.lock:
            changed = devicelib.apply_device_import(self.config["device"], parsed)
            if changed:
                save_config(self.config_path, self.config)
            view = devicelib.device_view(self.config["device"])
        if changed:
            self.log(f"已导入设备信息: {'、'.join(changed)}", "device")
        return {"changed": changed, "device": view}

    def issue_device_fp(self) -> dict[str, Any]:
        """手动向服务器重新申请 device_fp。"""
        self.log("开始向服务器申请 device_fp", "device")
        with ApiClient(timeout=20.0) as client:
            ok, reason = self.ensure_device_fp(client, force=True)
        if not ok:
            raise RuntimeError(f"申请失败: {reason}")
        return {"device": self.device_info()}

    def reset_device(self, model: str = "") -> dict[str, Any]:
        """换一台全新的虚拟设备（新 device_id，旧 fp 作废）。"""
        with self.lock:
            devicelib.reset_device(self.config["device"], model)
            save_config(self.config_path, self.config)
            view = devicelib.device_view(self.config["device"])
        self.log(f"已重新生成虚拟设备: {view['name']}", "device")
        return {"device": view}

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

    def shop_exchange_once(self, plan: dict[str, Any], on_progress: Callable[[int, str], None] | None = None) -> dict[str, Any]:
        account = self._account_by_index(self._plan_account_index(plan))
        account_name = display_account_name(account)
        goods_name = str(plan.get("goods_name") or plan.get("goods_id") or "未知商品")
        log_prefix = f"【账号 {account_name}｜商品 {goods_name}】"
        self.log(f"{log_prefix}开始商品兑换", "exchange")
        with self.lock:
            config = copy.deepcopy(self.config)
        if not str(plan.get("device_fp") or "").strip() and not devicelib.effective_fp(config["device"]):
            raise ValueError("兑换计划缺少 device_fp，请先在「设备信息」里申请或导入")
        try:
            with ApiClient(timeout=15.0) as client:
                result = ShopExchange(
                    client,
                    config,
                    account,
                    emit=lambda message: self.log(f"{log_prefix}{message}", "exchange"),
                ).exchange_with_retry(plan, on_progress=on_progress)
        except Exception as exc:
            self.log(f"{log_prefix}商品兑换请求异常: {exc}", "exchange")
            raise
        summary = f"{result.get('message', '未知结果')}({result.get('retcode')})，请求 {result.get('attempt', 1)} 次"
        self.log(f"{log_prefix}商品兑换结束: {summary}", "exchange")
        return result

    def shop_exchange_plan_once(self, plan_id: str) -> dict[str, Any]:
        """手动执行一个已保存的计划。"""
        return self._execute_plan(plan_id, manual=True)

    def run_shop_exchange_plan(self, plan_id: str) -> None:
        """调度器到点触发的入口。"""
        self._execute_plan(plan_id, manual=False)

    def shop_exchange_adhoc(self, plan: dict[str, Any]) -> dict[str, Any]:
        """不保存计划的一次性兑换（商品列表里的「兑换」）。
        进度挂在临时 key 上，界面同样能看到第几次尝试。"""
        goods_name = str(plan.get("goods_name") or plan.get("goods_id") or "未知商品")
        key = f"adhoc:{plan.get('goods_id', '')}:{plan.get('account_stuid') or plan.get('account_index', 0)}"
        if not self.exchange_scheduler.begin(key, goods_name):
            raise ValueError("该商品正在兑换中，请稍候")
        try:
            result = self.shop_exchange_once(
                plan,
                on_progress=lambda attempt, msg: self.exchange_scheduler.update_progress(
                    key, attempt=attempt, message=msg
                ),
            )
        finally:
            self.exchange_scheduler.end(key)
        with self.lock:
            push = bool(self.config.get("shop_exchange", {}).get("push", False))
        if push:
            self._send_exchange_push(goods_name, result, plan)
        return result

    def _scheduled_run_allowed(self, plan: dict[str, Any]) -> bool:
        shop = self.config.get("shop_exchange") or {}
        if not shop.get("enable") or plan.get("enable") is False or plan.get("auto") is False:
            return False
        # 调度器按服务器时间校准后触发，本机时钟可能快慢几秒；差得远说明时间已被改到之后，
        # 这次旧触发不该去消耗新的一轮
        return int(plan.get("exchange_at") or 0) - time.time() <= 300

    def _execute_plan(self, plan_id: str, *, manual: bool) -> dict[str, Any]:
        """定时触发和手动执行共用：登记进度 → 兑换 → 按 id 写回结果 → 推送。

        结果一律按 id 写回：兑换要等好几秒，期间页面可能删了、排序了别的计划，
        按下标写回会把结果记到别的计划头上。"""
        with self.lock:
            live = find_shop_plan(self.config, plan_id)
            if live is None:
                raise ValueError("兑换计划不存在")
            plan = copy.deepcopy(live)
            goods_name = str(plan.get("goods_name") or plan.get("goods_id") or "未知商品")
            push = bool(self.config.get("shop_exchange", {}).get("push", False))
            if not manual and not self._scheduled_run_allowed(live):
                self.log(f"计划已暂停或改期，跳过本次定时兑换: {goods_name}", "exchange")
                return {"ok": False, "skipped": True, "message": "计划已暂停或改期"}
            # 定时触发和手动执行（或连点两次）不能同时下单
            if not self.exchange_scheduler.begin(plan_id, goods_name):
                raise ValueError("该计划正在兑换中，请稍候")
        error: Exception | None = None
        try:
            if not manual:
                # 先打上「已尝试」标记，调度器重载时才不会把同一个时间点再排一次
                with self.lock:
                    live = find_shop_plan(self.config, plan_id)
                    if live is not None:
                        exchange_at = int(live.get("exchange_at") or 0)
                        live["last_attempt_key"] = f"{live.get('goods_id', '')}:{exchange_at}"
                        live["last_run"] = datetime.now().isoformat(timespec="seconds")
                        save_config(self.config_path, self.config)
            self.log(f"开始{'手动' if manual else ''}执行商品兑换计划: {goods_name}", "exchange")
            try:
                result = self.shop_exchange_once(
                    plan,
                    on_progress=lambda attempt, msg: self.exchange_scheduler.update_progress(
                        plan_id, attempt=attempt, message=msg
                    ),
                )
            except Exception as exc:
                error = exc
                result = {"ok": False, "retcode": None, "message": f"异常: {exc}", "attempt": 0, "error": True}
            summary = summarize_exchange_result(result)
            with self.lock:
                live = find_shop_plan(self.config, plan_id)
                if live is not None:
                    live["last_result"] = summary
                    live["last_ok"] = bool(result.get("ok"))
                    live["last_run"] = datetime.now().isoformat(timespec="seconds")
                    if result.get("ok"):
                        live["enable"] = False
                    save_config(self.config_path, self.config)
        finally:
            self.exchange_scheduler.end(plan_id)
        # 移出锁外：重载会等被移除的线程退出，持锁等待可能互相卡住
        self.exchange_scheduler.reload(self.config)
        self.log(f"商品兑换计划完成: {goods_name}，{summary}", "exchange")
        if push:
            self._send_exchange_push(goods_name, result, plan)
        if error is not None:
            raise error
        return result

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

            # 获取计划所属账号信息，添加到 plan 中
            plan_with_account = dict(plan)
            try:
                account = self._account_by_index(self._plan_account_index(plan))
                plan_with_account["account"] = display_account_name(account)
            except Exception:
                plan_with_account["account"] = "未知账号"

            push_result = send_exchange_push(config, title, goods_name, result, plan_with_account, success=is_success)
            if push_result:
                self.log(f"商品兑换推送已发送: {push_result}", "exchange")
        except Exception as exc:
            self.log(f"商品兑换推送发送失败: {exc}", "exchange")

    def _plan_account_index(self, plan: dict[str, Any]) -> int:
        """兑换计划所属账号在当前列表里的下标：优先按 stuid 找，避免账号列表变动后指向别的账号。"""
        stuid = str(plan.get("account_stuid") or "").strip()
        if not stuid:
            return int(plan.get("account_index") or 0)
        with self.lock:
            index = find_account_index_by_stuid(self.config.get("accounts") or [], stuid)
        if index is None:
            raise ValueError("兑换计划所属账号已不存在，请重新选择执行账号")
        return index

    def _account_by_index(self, account_index: int) -> dict[str, Any]:
        with self.lock:
            accounts = self.config.get("accounts") or []
            if account_index < 0 or account_index >= len(accounts):
                raise ValueError("请选择已登录账号")
            account = copy.deepcopy(accounts[account_index])
        if account_region(account) != REGION_CN:
            raise ValueError("商店兑换只支持国服账号")
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
            ensure_login_region(account_snapshot, REGION_CN)
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
            self._qr_refresh.clear()
            self._login_cancel.clear()
            self._login_generation += 1
            generation = self._login_generation
        thread = threading.Thread(
            target=self._login_worker,
            args=(account_index, timeout, account_snapshot, draft, generation),
            name="miyouqian-web-login",
            daemon=True,
        )
        thread.start()
        self.log(f"账号 {account_name} 开始扫码登录", "auth")

    def send_login_captcha(
        self,
        account_index: int,
        phone: str,
        account_payload: dict[str, Any] | None = None,
        draft: bool = False,
        aigis: str = "",
    ) -> dict[str, str]:
        phone = normalize_cn_phone(phone)
        account_snapshot, account_name = self._login_account_snapshot(account_index, account_payload, draft)
        with self.lock:
            if self.login_state.get("running"):
                raise RuntimeError("扫码登录正在进行")
        with ApiClient() as client:
            login = CaptchaLogin(client, self._login_device(client))
            result = login.create_captcha(phone, aigis)
        self.log(f"账号 {account_name} 已发送验证码", "auth")
        return result

    def complete_login_captcha(
        self,
        account_index: int,
        phone: str,
        captcha: str,
        action_type: str,
        account_payload: dict[str, Any] | None = None,
        draft: bool = False,
        aigis: str = "",
    ) -> dict[str, Any]:
        phone = normalize_cn_phone(phone)
        captcha = str(captcha or "").strip()
        action_type = str(action_type or "").strip()
        if not captcha:
            raise ValueError("请输入短信验证码")
        if not action_type:
            raise ValueError("请先发送短信验证码")
        account_snapshot, account_name = self._login_account_snapshot(account_index, account_payload, draft)
        with self.lock:
            if self.login_state.get("running"):
                raise RuntimeError("扫码登录正在进行")
        with ApiClient() as client:
            login = CaptchaLogin(client, self._login_device(client))
            token_data = login.login_by_mobile_captcha(phone, captcha, action_type, aigis)
            account_data = self._complete_login_data(login, token_data)
        account = self._save_login_account(account_index, account_snapshot, account_data, draft)
        account_name = display_account_name(account)
        if draft:
            self.log(f"账号 {account_name} 验证码登录成功，等待保存", "auth")
        else:
            self.log(f"账号 {account_name} 验证码登录成功，凭证已保存", "auth")
        return {
            "account_index": account_index,
            "draft": draft,
            "message": f"账号 {account_name} 登录成功" + ("，请保存账号" if draft else ""),
            "account_data": account_data,
        }

    def _login_account_snapshot(
        self,
        account_index: int,
        account_payload: dict[str, Any] | None,
        draft: bool,
        region: str = REGION_CN,
    ) -> tuple[dict[str, Any], str]:
        with self.lock:
            accounts = self.config.get("accounts") or []
            if not draft and (account_index < 0 or account_index >= len(accounts)):
                raise ValueError("请先添加账号")
            account_snapshot = dict(account_payload or {})
            if not draft:
                account_snapshot = dict(accounts[account_index])
            account_name = display_account_name(account_snapshot)
        ensure_login_region(account_snapshot, region)
        return account_snapshot, account_name

    def complete_login_cookie(
        self,
        account_index: int,
        cookie: str,
        account_payload: dict[str, Any] | None = None,
        draft: bool = False,
    ) -> dict[str, Any]:
        """国际服登录：没有扫码 / 验证码，直接收下用户粘贴的 HoYoLAB cookie。"""
        account_data = parse_hoyolab_cookie(cookie)
        # 格式对了不代表 cookie 还有效，先拿一次只读的 info 请求试一下
        status = probe_hoyolab_cookie(account_data["cookie"])
        if status == "invalid":
            raise ValueError("HoYoLAB 提示 cookie 无效或已过期，请重新复制一次")
        account_snapshot, account_name = self._login_account_snapshot(
            account_index, account_payload, draft, REGION_OS
        )
        account = self._save_login_account(account_index, account_snapshot, account_data, draft, REGION_OS)
        account_name = display_account_name(account)
        if draft:
            self.log(f"账号 {account_name} 国际服 cookie 已录入，等待保存", "auth")
        else:
            self.log(f"账号 {account_name} 国际服 cookie 已保存", "auth")
        message = f"账号 {account_name} 登录成功" + ("，请保存账号" if draft else "")
        if status == "unknown":
            # 网络抖动不该挡住保存，但要让用户知道这次没验成
            message += "（暂时无法在线校验，签到时会再确认）"
        return {
            "account_index": account_index,
            "draft": draft,
            "message": message,
            "account_data": account_data,
        }

    def _login_device(self, client: ApiClient) -> dict[str, Any]:
        """登录用的设备档案快照。fp 先尽量申请好；申请不到就不带这个头，不拿随机串顶替。"""
        self.ensure_device_fp(client, component="auth")
        with self.lock:
            return dict(self.config["device"])

    def _complete_login_data(self, login: QRLogin | CaptchaLogin, token_data: dict[str, str]) -> dict[str, str]:
        account_data = {**token_data, **login.get_additional_tokens(token_data["stoken"], token_data["mid"])}
        account_data["cookie"] = cookies.build_cookie(
            account_data["stuid"],
            account_data["mid"],
            account_data["ltoken"],
            account_data["cookie_token"],
        )
        return account_data

    def _save_login_account(
        self,
        account_index: int,
        account_snapshot: dict[str, Any],
        account_data: dict[str, str],
        draft: bool,
        region: str = REGION_CN,
    ) -> dict[str, Any]:
        with self.lock:
            new_uid = str(account_data.get("stuid") or "").strip()
            duplicate = find_duplicate_uid(
                self.config.get("accounts") or [], new_uid, None if draft else account_index, region
            )
            if duplicate is not None:
                raise ValueError(f"UID {new_uid} 已存在，不能重复添加同一账号")
            account = {**account_snapshot, **account_data}
            if not str(account.get("name") or "").strip():
                account["name"] = account_data["stuid"]
            if not draft:
                self.config["accounts"][account_index] = account
                # 这个位置换成了另一个米游社账号时，绑定旧账号的兑换计划要停用，不能改用新账号的 cookie
                bind_shop_plan_accounts(self.config)
                save_config(self.config_path, self.config)
                self.log_file = log_path(self.config_path, self.config)
                configure_logger(self.log_file)
                self.scheduler.reload(self.config)
                self.exchange_scheduler.reload(self.config)
        return account

    def _login_worker(
        self,
        account_index: int,
        timeout: int,
        account_snapshot: dict[str, Any],
        draft: bool,
        generation: int,
    ) -> None:
        try:
            if self._login_cancel.is_set():
                return
            with self.lock:
                account_name = display_account_name(account_snapshot)
            with ApiClient() as client:
                login = QRLogin(client, self._login_device(client))
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
                scan = self._wait_with_refresh(login, ticket, timeout, account_name)
                if self._login_cancel.is_set():
                    return
                with self.lock:
                    self.login_state.update({"status": "exchanging", "message": "正在获取完整凭证"})
                account_data = self._complete_login_data(login, scan)
            account = self._save_login_account(account_index, account_snapshot, account_data, draft)
            with self.lock:
                account_name = display_account_name(account)
                if self._login_generation == generation:
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
                if self._login_generation == generation:
                    self.login_state.update(
                        {
                            "running": False,
                            "status": "error",
                            "message": str(exc),
                            "qr": "",
                        }
                    )
            self.log(f"扫码登录失败: {exc}", "auth")

    def _wait_with_refresh(self, login: QRLogin, ticket: str, timeout: int, account_name: str) -> dict[str, str]:
        while True:
            if self._login_cancel.is_set():
                raise RuntimeError("登录已取消")
            try:
                return login.wait(ticket, timeout=timeout, cancel=self._qr_refresh, cancel_events=[self._login_cancel])
            except _QrRefreshed:
                if self._login_cancel.is_set():
                    raise RuntimeError("登录已取消")
                self._qr_refresh.clear()
                self.log(f"账号 {account_name} 刷新二维码", "auth")
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

    def refresh_login_qr(self) -> None:
        with self.lock:
            if not self.login_state.get("running"):
                raise RuntimeError("当前没有进行中的登录")
            if self.login_state.get("status") != "waiting":
                raise RuntimeError("当前不在等待扫码状态")
        self._qr_refresh.set()

    def cancel_login(self) -> None:
        with self.lock:
            if not self.login_state.get("running"):
                raise RuntimeError("当前没有进行中的登录")
            self.login_state.update(
                {
                    "running": False,
                    "status": "error",
                    "message": "登录流程已取消",
                    "qr": "",
                }
            )
        self._login_cancel.set()
        self.log("登录流程已取消", "auth")

    # ------------------------------------------------------------------
    # QQ 官方机器人 OpenID 绑定
    #
    # QQ 开放平台不提供查询 user_openid / group_openid 的接口，只能在机器人收到
    # 消息或入群事件时被动获取，所以这里起一个线程连网关等用户发验证码。
    # ------------------------------------------------------------------
    def start_qq_bind(self, payload: dict[str, Any]) -> None:
        target = str(payload.get("target") or "user").strip().lower()
        if target not in ("user", "group"):
            raise ValueError("绑定目标只能是 user 或 group")
        app_id = str(payload.get("app_id") or "").strip()
        client_secret = str(payload.get("client_secret") or "").strip()
        api_base = str(payload.get("api_base") or "").strip()
        if not app_id:
            raise ValueError("请先填写 AppID")
        if not client_secret:
            raise ValueError("请先填写 AppSecret")

        with self.lock:
            if self.qq_bind_state.get("running"):
                raise RuntimeError("已有 QQ 绑定正在进行，请等待或取消")
            self._qq_bind_cancel.clear()
            # 验证码在这里生成并立刻返回给页面，用户看到后才有东西可发
            self.qq_bind_state = {
                "running": True,
                "status": "starting",
                "target": target,
                "message": "正在连接 QQ 网关",
                "verify_code": generate_verify_code(),
                "openid": "",
            }
            verify_code = str(self.qq_bind_state["verify_code"])
        thread = threading.Thread(
            target=self._qq_bind_worker,
            args=(target, app_id, client_secret, api_base, verify_code),
            name="miyouqian-web-qq-bind",
            daemon=True,
        )
        thread.start()
        self.log(f"开始绑定 QQ {'群聊' if target == 'group' else '私聊'} OpenID", "push")

    def _qq_bind_worker(
        self,
        target: str,
        app_id: str,
        client_secret: str,
        api_base: str,
        verify_code: str,
    ) -> None:
        def on_event(message: str) -> None:
            with self.lock:
                self.qq_bind_state.update({"message": message})

        try:
            openid = bind_qq_openid(
                app_id=app_id,
                client_secret=client_secret,
                verify_code=verify_code,
                target=target,
                api_base=api_base,
                timeout=QQ_BIND_TIMEOUT,
                on_event=on_event,
                cancel=self._qq_bind_cancel.is_set,
            )
            field = "group_openid" if target == "group" else "user_openid"
            # 绑定过程中配置可能已经被改过（改 AppID/AppSecret 会让结果作废），此时不再落盘
            if self._qq_bind_cancel.is_set():
                raise RuntimeError("绑定已取消")
            # 把绑定到的 OpenID 写回配置，省得用户再从日志里手抄一遍
            with self.lock:
                channel = ensure_push_channel(self.config, "qqbot")
                channel[field] = openid
                channel["app_id"] = app_id
                channel["client_secret"] = client_secret
                if api_base:
                    channel["api_base"] = api_base
                normalize_config(self.config)
                save_config(self.config_path, self.config)
                self.qq_bind_state = {
                    "running": False,
                    "status": "success",
                    "target": target,
                    "message": "绑定成功，已保存到配置",
                    "verify_code": verify_code,
                    "openid": openid,
                    "field": field,
                }
        except Exception as exc:
            with self.lock:
                self.qq_bind_state = {
                    "running": False,
                    "status": "error",
                    "target": target,
                    "message": str(exc),
                    "verify_code": verify_code,
                    "openid": "",
                }
            self.log(f"绑定 QQ OpenID 失败: {exc}", "push")
            return
        self.log(f"绑定 QQ OpenID 成功: {openid}", "push")

    def qq_bind_status(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.qq_bind_state)

    def cancel_qq_bind(self) -> None:
        with self.lock:
            if not self.qq_bind_state.get("running"):
                raise RuntimeError("当前没有进行中的 QQ 绑定")
            # 只置取消标志，最终状态交给 worker 收尾，避免两边同时改状态互相覆盖
            self.qq_bind_state["message"] = "正在取消绑定"
        self._qq_bind_cancel.set()
        self.log("已请求取消 QQ OpenID 绑定", "push")


def make_qr_data_uri(text: str) -> str:
    image = qrcode.make(text)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    encoded = base64.b64encode(stream.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def display_account_name(account: dict[str, Any]) -> str:
    return str(account.get("name") or account.get("stuid") or "未命名账号")


def parse_avatar_key(value: str) -> str:
    """把页面传来的头像键规整成 uid（国服）或 os:uid（国际服），不合法返回空串。"""
    text = str(value or "").strip()
    region, sep, uid = text.partition(":")
    if not sep:
        region, uid = REGION_CN, text
    if region not in (REGION_CN, REGION_OS):
        return ""
    uid = uid.strip()
    if not (uid.isascii() and uid.isdigit() and len(uid) <= 20):
        return ""
    return f"{REGION_OS}:{uid}" if region == REGION_OS else uid


def ensure_login_region(account: dict[str, Any], region: str) -> None:
    """服务器类型一旦确定就不能换：国服的登录凭证写不进国际服账号，反过来也一样。"""
    if account_region(account) == region:
        return
    if region == REGION_CN:
        raise ValueError("该账号是国际服账号，请用 HoYoLAB cookie 登录")
    raise ValueError("该账号是国服账号，请用扫码或验证码登录")


def normalize_cn_phone(phone: str) -> str:
    digits = "".join(char for char in str(phone or "") if char.isdigit())
    if len(digits) != 11:
        raise ValueError("请输入 11 位手机号")
    return digits


def find_duplicate_uid(
    accounts: list[dict[str, Any]], uid: str, exclude_index: int | None = None, region: str = REGION_CN
) -> int | None:
    if not uid:
        return None
    for index, account in enumerate(accounts):
        if exclude_index is not None and index == exclude_index:
            continue
        if account_region(account) == region and str(account.get("stuid") or "").strip() == uid:
            return index
    return None


def ensure_push_channel(config: dict[str, Any], provider: str) -> dict[str, Any]:
    """取出推送通道，不存在就按默认字段建一个并写回配置。"""
    push = config.setdefault("push", {})
    channels = push.setdefault("channels", [])
    for channel in channels:
        if isinstance(channel, dict) and str(channel.get("provider") or "") == provider:
            return channel
    fields = PUSH_CHANNEL_FIELDS.get(provider, ())
    channel: dict[str, Any] = {"provider": provider, "enable": True}
    for field in fields:
        channel[field] = PUSH_CHANNEL_DEFAULTS.get(provider, {}).get(field, "")
    channels.append(channel)
    return channel


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
        "api_key",
        "secret",
        "client_secret",
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
            if path == "/api/account/avatars":
                uids = [uid.strip() for uid in first_query(query, "uids").split(",")]
                self.send_json(self.app.account_avatars(uids))
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
            if path == "/api/device":
                self.send_json(self.app.device_info())
                return
            if path == "/api/qqbot/bind/status":
                self.send_json(self.app.qq_bind_status())
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
            if path == "/api/device/import":
                self.send_json({"ok": True, **self.app.import_device(str(payload.get("text") or ""))})
                return
            if path == "/api/device/fp":
                self.send_json({"ok": True, **self.app.issue_device_fp()})
                return
            if path == "/api/device/reset":
                self.send_json({"ok": True, **self.app.reset_device(str(payload.get("model") or ""))})
                return
            if path == "/api/push/test":
                channel = payload.get("channel") if isinstance(payload, dict) else None
                result = self.app.test_push_channels(channel)
                # single 让页面能判断服务端是否已支持「只测单条通道」
                self.send_json(
                    {"ok": True, "result": result, "single": isinstance(channel, dict)}
                )
                return
            if path == "/api/qqbot/bind":
                self.app.start_qq_bind(payload)
                self.send_json({"ok": True, **self.app.qq_bind_status()})
                return
            if path == "/api/qqbot/bind/cancel":
                self.app.cancel_qq_bind()
                self.send_json({"ok": True})
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
            if path == "/api/login/captcha/send":
                account_index = int(payload.get("account_index", -1))
                account_payload = payload.get("account")
                if account_payload is not None and not isinstance(account_payload, dict):
                    raise ValueError("账号数据必须是 JSON 对象")
                result = self.app.send_login_captcha(
                    account_index,
                    str(payload.get("phone") or ""),
                    account_payload,
                    bool(payload.get("draft")),
                    str(payload.get("aigis") or ""),
                )
                self.send_json({"ok": True, **result})
                return
            if path == "/api/login/captcha/verify":
                account_index = int(payload.get("account_index", -1))
                account_payload = payload.get("account")
                if account_payload is not None and not isinstance(account_payload, dict):
                    raise ValueError("账号数据必须是 JSON 对象")
                result = self.app.complete_login_captcha(
                    account_index,
                    str(payload.get("phone") or ""),
                    str(payload.get("captcha") or ""),
                    str(payload.get("action_type") or ""),
                    account_payload,
                    bool(payload.get("draft")),
                    str(payload.get("aigis") or ""),
                )
                self.send_json({"ok": True, **result})
                return
            if path == "/api/login/cookie":
                account_index = int(payload.get("account_index", -1))
                account_payload = payload.get("account")
                if account_payload is not None and not isinstance(account_payload, dict):
                    raise ValueError("账号数据必须是 JSON 对象")
                result = self.app.complete_login_cookie(
                    account_index,
                    str(payload.get("cookie") or ""),
                    account_payload,
                    bool(payload.get("draft")),
                )
                self.send_json({"ok": True, **result})
                return
            if path == "/api/login/refresh":
                self.app.refresh_login_qr()
                self.send_json({"ok": True})
                return
            if path == "/api/login/cancel":
                self.app.cancel_login()
                self.send_json({"ok": True})
                return
            if path == "/api/shop/exchange":
                plan_id = str(payload.get("plan_id") or "")
                if not plan_id and "plan_index" in payload:
                    # 旧页面缓存还在发下标，翻译成 id
                    plans = self.app.config.get("shop_exchange", {}).get("plans") or []
                    index = int(payload.get("plan_index"))
                    if 0 <= index < len(plans):
                        plan_id = str(plans[index].get("id") or "")
                if plan_id:
                    result = self.app.shop_exchange_plan_once(plan_id)
                    self.send_json({"ok": True, "result": result, "config": self.app.get_config()})
                    return
                plan = payload.get("plan")
                if not isinstance(plan, dict):
                    raise ValueError("兑换计划必须是 JSON 对象")
                self.send_json({"ok": True, "result": self.app.shop_exchange_adhoc(plan)})
                return
            self.send_error_json("接口不存在", HTTPStatus.NOT_FOUND)
        except AigisRequired as exc:
            self.send_json(
                {
                    "ok": False,
                    "error": str(exc),
                    "code": "aigis_required",
                    "aigis": exc.aigis,
                },
                HTTPStatus.PRECONDITION_REQUIRED,
            )
        except Exception as exc:
            self.send_error_json(str(exc), HTTPStatus.BAD_REQUEST)

    def serve_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        relative = pathlib.Path(unquote(path).lstrip("/"))
        # 移除版本参数（如 /app.js?v=123 -> /app.js）
        if len(relative.parts) > 0:
            file_part = relative.parts[-1]
            if "?" in file_part:
                file_part = file_part.split("?")[0]
                relative = pathlib.Path(*relative.parts[:-1], file_part)

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

        # 如果是 HTML 文件，给静态资源添加版本号
        if content_type == "text/html":
            html_content = data.decode("utf-8")
            for script in ("shop.js", "app.js"):
                script_path = WEB_ROOT / script
                if script_path.exists():
                    mtime = int(script_path.stat().st_mtime)
                    html_content = html_content.replace(f'src="/{script}"', f'src="/{script}?v={mtime}"')
            data = html_content.encode("utf-8")

        # ETag 取最终发出的内容：HTML 里注入了脚本版本号，只看 HTML 文件本身会让旧页面一直 304
        etag = f'"{hashlib.sha1(data).hexdigest()[:16]}"'

        # 检查 If-None-Match 头
        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.end_headers()
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etag)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        if set_cookie:
            # 7 天过期 (7 * 24 * 60 * 60 = 604800 秒)
            self.send_header("Set-Cookie", f"{AUTH_COOKIE}={set_cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age=604800")
        self.end_headers()
        self.wfile.write(raw)

    def send_error_json(self, message: str, status: HTTPStatus) -> None:
        self.send_json({"ok": False, "error": message}, status=status)


def serve(config_path: pathlib.Path, host: str, port: int) -> None:
    app = WebApp(config_path, host, port)
    Handler.app = app
    print_startup_banner("MYQ")
    app.log(f"正在启动 Web 控制台，配置文件: {config_path.resolve()}", "startup")
    if not app.password_is_set:
        app.log("您尚未设置外网访问密码！首次访问 Web 控制台时请您妥善设置并保管外网访问密码！", "auth")
    if host in ("127.0.0.1", "localhost", "::1"):
        app.log("您设置了仅监听本机，访问 Web 控制台时将不校验外网访问密码，请您知悉。", "auth")
    else:
        app.log("您设置了监听外网，访问 Web 控制台时将校验外网访问密码，请您妥善设置并保管外网访问密码！", "auth")
    server, actual_port = create_server(host, port)
    app.port = actual_port
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
