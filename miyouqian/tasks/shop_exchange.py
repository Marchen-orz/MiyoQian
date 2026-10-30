# -*- coding: utf-8 -*-
"""米游社商品兑换。"""

from __future__ import annotations

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .. import constants as c
from ..core import device as devicelib
from ..core.http import ApiClient

EmitFn = Callable[[str], None]
BJT = timezone(timedelta(hours=8))

# 补查商品详情的并发数
DETAIL_WORKERS = 6

# 重试也不会成功的失败：账号自身的原因，或商品已经没了。只按返回的文字判断；
# 开抢瞬间返回的「未到兑换时间」之类必须继续重试，所以不能把它们列进来。
TERMINAL_FAILURES = (
    ("米游币不足", ("米游币不足", "余额不足", "积分不足")),
    ("已达限购上限", ("兑换上限", "已达上限", "限购")),
    ("商品已售罄", ("已售罄", "已兑完", "库存不足")),
    ("登录已失效", ("未登录", "登录失效", "请先登录")),
)
LOGIN_RETCODES = {-100}
# 同一种不可重试的失败连续出现这么多次才提前结束，防止开抢瞬间的一次误判
TERMINAL_CONFIRM_HITS = 2


def terminal_failure_reason(retcode: Any, message: str) -> str:
    if retcode in LOGIN_RETCODES:
        return "登录已失效"
    for reason, keywords in TERMINAL_FAILURES:
        if any(keyword in message for keyword in keywords):
            return reason
    return ""


class ShopExchange:
    def __init__(
        self,
        client: ApiClient,
        config: dict[str, Any],
        account: dict[str, Any] | None = None,
        emit: EmitFn | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.account = account or {}
        self.device = config["device"]
        self.emit = emit

    def goods(self, game: str = "", max_pages: int = 5) -> dict[str, Any]:
        raw_goods: list[dict[str, Any]] = []
        games: list[dict[str, str]] = []
        for page in range(1, max_pages + 1):
            data = self.client.get_json(
                c.MALL_GOODS_LIST_URL,
                params={
                    "app_id": 1,
                    "point_sn": "myb",
                    "page_size": 20,
                    "page": page,
                    "game": game,
                },
                headers=self._goods_headers(),
            )
            if data.get("retcode") != 0:
                raise ValueError(str(data.get("message") or "商品列表获取失败"))
            raw = data.get("data") or {}
            if page == 1:
                games = normalize_games(raw.get("games") or [])
            page_goods = raw.get("list") or []
            if not isinstance(page_goods, list) or not page_goods:
                break
            raw_goods.extend(item for item in page_goods if isinstance(item, dict))
        # 未开售的商品要逐个补查详情才有开售时间，串行的话商品一多就要等很久
        if raw_goods:
            with ThreadPoolExecutor(max_workers=min(DETAIL_WORKERS, len(raw_goods))) as pool:
                raw_goods = list(pool.map(self._enrich_good_for_time, raw_goods))
        goods = [normalize_good(item) for item in raw_goods]
        goods.sort(key=goods_sort_key)
        return {"games": games, "goods": goods}

    def good_detail(self, goods_id: str) -> dict[str, Any]:
        return normalize_good(self._good_detail_raw(goods_id))

    def _good_detail_raw(self, goods_id: str) -> dict[str, Any]:
        data = self.client.get_json(
            c.MALL_GOOD_DETAIL_URL,
            params={"app_id": 1, "point_sn": "myb", "goods_id": goods_id},
            headers=self._goods_headers(),
        )
        if data.get("retcode") != 0:
            raise ValueError(str(data.get("message") or "商品详情获取失败"))
        raw = data.get("data") or {}
        if not isinstance(raw, dict):
            raise ValueError("商品详情格式异常")
        return raw

    def _enrich_good_for_time(self, raw: dict[str, Any]) -> dict[str, Any]:
        if not needs_good_detail_time(raw):
            return raw
        goods_id = str(raw.get("goods_id") or "")
        if not goods_id:
            return raw
        try:
            detail = self._good_detail_raw(goods_id)
        except Exception as exc:
            self._add(f"商品 {goods_id} 详情补查失败，使用列表数据: {exc}")
            return raw
        return {**raw, **detail}

    def points(self) -> dict[str, Any]:
        data = self.client.get_json(
            c.MALL_POINT_URL,
            params={"app_id": 1, "point_sn": "myb"},
            headers=self._account_headers(host="api-takumi.mihoyo.com", origin="https://webstatic.mihoyo.com"),
        )
        if data.get("retcode") != 0:
            raise ValueError(str(data.get("message") or "米游币余额获取失败"))
        raw = data.get("data") or {}
        return raw if isinstance(raw, dict) else {}

    def addresses(self) -> list[dict[str, Any]]:
        data = self.client.get_json(
            c.MALL_ADDRESS_URL,
            params={"t": round(time.time() * 1000)},
            headers=self._account_headers(host="api-takumi.mihoyo.com", origin="https://user.mihoyo.com"),
        )
        if data.get("retcode") != 0:
            raise ValueError(str(data.get("message") or "收货地址获取失败"))
        raw_list = (data.get("data") or {}).get("list") or []
        if not isinstance(raw_list, list):
            return []
        return [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("connect_name") or item.get("name") or ""),
                "phone": str(item.get("connect_areacode") or "") + str(item.get("connect_mobile") or ""),
                "address": str(item.get("addr_ext") or item.get("address") or ""),
            }
            for item in raw_list
            if isinstance(item, dict)
        ]

    def roles(self, game_biz: str) -> list[dict[str, str]]:
        if not game_biz:
            return []
        data = self.client.get_json(
            c.ACCOUNT_ROLES_URL,
            params={"game_biz": game_biz},
            headers=self._account_headers(host="api-takumi.mihoyo.com", origin="https://webstatic.mihoyo.com"),
        )
        if data.get("retcode") != 0:
            return []
        raw_roles = (data.get("data") or {}).get("list") or []
        if not isinstance(raw_roles, list):
            return []
        return [
            {
                "uid": str(role.get("game_uid") or ""),
                "region": str(role.get("region") or ""),
                "nickname": str(role.get("nickname") or ""),
                "level": str(role.get("level") or ""),
                "region_name": str(role.get("region_name") or ""),
            }
            for role in raw_roles
            if isinstance(role, dict)
        ]

    def exchange(self, plan: dict[str, Any]) -> dict[str, Any]:
        goods_id = str(plan.get("goods_id") or "").strip()
        if not goods_id:
            raise ValueError("缺少 goods_id")
        body: dict[str, Any] = {
            "app_id": 1,
            "point_sn": "myb",
            "goods_id": goods_id,
            "exchange_num": 1,
        }
        address_id = str(plan.get("address_id") or "").strip()
        if address_id:
            body["address_id"] = address_id
        uid = str(plan.get("uid") or "").strip()
        region = str(plan.get("region") or "").strip()
        game_biz = str(plan.get("game_biz") or "").strip()
        if uid and region and game_biz:
            body.update({"uid": uid, "region": region, "game_biz": game_biz})
        started = time.time()
        data = self.client.post_json(c.MALL_EXCHANGE_URL, json=body, headers=self._exchange_headers(plan))
        retcode = data.get("retcode")
        message = str(data.get("message") or "")
        ok = retcode == 0
        result = {
            "ok": ok,
            "retcode": retcode,
            "message": message or ("兑换成功" if ok else "兑换失败"),
            "sent_at": datetime.fromtimestamp(started).isoformat(timespec="milliseconds"),
            "data": data.get("data") or {},
        }
        self._add(f"商品 {goods_id} 兑换请求返回: {result['message']}({retcode})")
        return result

    def exchange_with_retry(self, plan: dict[str, Any], on_progress: Callable[[int, str], None] | None = None) -> dict[str, Any]:
        from ..core.http import ApiError

        shop = self.config.get("shop_exchange", {})
        duration = max(float(shop.get("retry_seconds") or 0), 0)
        interval = max(float(shop.get("retry_interval") or 0.4), 0.05)
        deadline = time.time() + duration
        last: dict[str, Any] = {}
        attempt = 0
        terminal_hits = 0
        while True:
            attempt += 1
            self._add(f"正在发送第 {attempt} 次商品兑换请求")
            if on_progress:
                on_progress(attempt, "正在发送兑换请求")
            try:
                last = self.exchange(plan)
            except ApiError as exc:
                self._add(f"商品 {plan.get('goods_id', '')} 请求异常: {exc}")
                last = {"ok": False, "retcode": None, "message": f"网络请求异常: {exc}", "data": {}}
            last["attempt"] = attempt
            if on_progress:
                on_progress(attempt, f"{last.get('message', '')}({last.get('retcode')})")
            remaining = deadline - time.time()
            if last.get("ok") or remaining <= 0:
                return last
            reason = terminal_failure_reason(last.get("retcode"), str(last.get("message") or ""))
            terminal_hits = terminal_hits + 1 if reason else 0
            if terminal_hits >= TERMINAL_CONFIRM_HITS:
                self._add(f"商品 {plan.get('goods_id', '')} 连续返回「{reason}」，重试不会成功，提前结束")
                return last
            # 抖动按间隔等比放大缩小，平均间隔才和界面里填的一致
            sleep_seconds = max(interval * random.uniform(0.7, 1.3), 0.05)
            time.sleep(min(sleep_seconds, remaining))

    def _goods_headers(self) -> dict[str, str]:
        return {
            "Host": "api-takumi.mihoyo.com",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://user.mihoyo.com",
            "Connection": "keep-alive",
            "x-rpc-device_id": str(self.device["id"]),
            "x-rpc-client_type": "5",
            "User-Agent": devicelib.mobile_ua(self.device),
            "Referer": "https://user.mihoyo.com/",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        }

    def _account_headers(self, host: str, origin: str) -> dict[str, str]:
        return {
            "Host": host,
            "Accept": "application/json, text/plain, */*",
            "Origin": origin,
            "Connection": "keep-alive",
            "x-rpc-device_id": str(self.device["id"]),
            "x-rpc-client_type": "5",
            "User-Agent": devicelib.mobile_ua(self.device),
            "Referer": f"{origin}/",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Cookie": str(self.account.get("cookie") or ""),
        }

    def _exchange_headers(self, plan: dict[str, Any]) -> dict[str, str]:
        # 设备档案里可信的 fp 优先，这样重置设备、导入真机后旧计划也跟着换；
        # 档案里没有可信的，才退回计划创建时存下的那枚
        device_fp = (
            devicelib.effective_fp(self.device) if devicelib.has_trusted_fp(self.device) else ""
        ) or str(plan.get("device_fp") or "").strip() or devicelib.effective_fp(self.device)
        if not device_fp:
            raise ValueError("兑换计划缺少 device_fp，请先在「设备信息」里申请或导入")
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Connection": "keep-alive",
            "Content-Type": "application/json;charset=utf-8",
            "Host": "api-takumi.miyoushe.com",
            "Origin": "https://webstatic.miyoushe.com",
            "Referer": "https://webstatic.miyoushe.com/",
            "User-Agent": devicelib.mobile_ua(self.device),
            "x-rpc-app_version": c.BBS_VERSION,
            "x-rpc-channel": "appstore",
            "x-rpc-client_type": "1",
            "x-rpc-verify_key": c.PASSPORT_APP_ID,
            "x-rpc-device_fp": device_fp,
            "x-rpc-device_id": str(self.device["id"]),
            "x-rpc-device_model": devicelib.device_model(self.device),
            "x-rpc-device_name": devicelib.device_name(self.device),
            "x-rpc-sys_version": devicelib.sys_version(self.device),
            "Cookie": str(self.account.get("cookie") or ""),
        }
        return headers

    def _add(self, message: str) -> None:
        if self.emit:
            self.emit(message)


def normalize_games(raw_games: list[Any]) -> list[dict[str, str]]:
    games: list[dict[str, str]] = [{"key": "", "name": "全部分区"}]
    for item in raw_games:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        name = str(item.get("name") or key)
        # 接口自带的「全部商品」key 是 all，按它查不到任何商品；不带分区查询才是全部，上面已经有了
        if key and key != "all":
            games.append({"key": key, "name": name})
    return games


def needs_good_detail_time(raw: dict[str, Any]) -> bool:
    if parse_int(raw.get("next_time"), 0) <= 0:
        return False
    if is_sold_out(raw):
        return False
    if raw.get("sale_start_time") not in (None, "", 0, "0"):
        return False
    return str(raw.get("status") or "") == "not_in_sell"


def normalize_good(raw: dict[str, Any]) -> dict[str, Any]:
    exchange_ts = good_exchange_timestamp(raw)
    display_status = good_display_status(raw, exchange_ts)
    stock = good_stock_text(raw, display_status)
    next_stock = good_next_stock_text(raw)
    return {
        "goods_id": str(raw.get("goods_id") or ""),
        "goods_name": str(raw.get("goods_name") or raw.get("name") or "未命名商品"),
        "price": parse_int(raw.get("price"), 0),
        "icon": str(raw.get("icon") or ""),
        "game_biz": str(raw.get("game_biz") or ""),
        "status": str(raw.get("status") or ""),
        "type": parse_int(raw.get("type"), 0),
        "unlimit": bool(raw.get("unlimit", False)),
        "total": raw.get("total"),
        "next_num": raw.get("next_num"),
        "stock": stock,
        "next_stock": next_stock,
        "sold_out": is_sold_out(raw),
        "exchange_timestamp": exchange_ts,
        "exchange_time": format_exchange_time(exchange_ts, raw, display_status),
        "display_status": display_status,
        "limit": format_limit(raw),
        "raw": {
            "start": raw.get("start"),
            "end": raw.get("end"),
            "sale_start_time": raw.get("sale_start_time"),
            "next_time": raw.get("next_time"),
            "now_time": raw.get("now_time"),
            "total": raw.get("total"),
            "next_num": raw.get("next_num"),
            "account_exchange_num": raw.get("account_exchange_num"),
            "account_cycle_limit": raw.get("account_cycle_limit"),
            "account_cycle_type": raw.get("account_cycle_type"),
        },
    }


def good_exchange_timestamp(raw: dict[str, Any]) -> int:
    next_time = parse_int(raw.get("next_time"), 0)
    if is_sold_out(raw):
        return next_time if next_time > 0 else 0
    if str(raw.get("status") or "") == "online":
        return 0
    sale_start_time = parse_int(raw.get("sale_start_time"), 0)
    now_time = parse_int(raw.get("now_time"), int(time.time()))
    if sale_start_time > 0 and now_time < sale_start_time and (next_time <= 0 or sale_start_time <= next_time):
        return sale_start_time
    if next_time > 0:
        return next_time
    return 0


def format_exchange_time(timestamp: int, raw: dict[str, Any], display_status: str = "") -> str:
    if display_status == "sold_out_with_next" and timestamp > 0:
        return datetime.fromtimestamp(timestamp, BJT).strftime("%Y-%m-%d %H:%M:%S")
    if display_status == "always":
        return "任何时间"
    if display_status == "online":
        return "正在兑换"
    if display_status == "ended":
        return "已结束"
    if timestamp > 0:
        return datetime.fromtimestamp(timestamp, BJT).strftime("%Y-%m-%d %H:%M:%S")
    if str(raw.get("status") or "") == "online":
        return "正在兑换"
    if raw.get("unlimit"):
        return "任何时间"
    return "未公布或已结束"


def good_stock_text(raw: dict[str, Any], display_status: str = "") -> str:
    if raw.get("unlimit"):
        return "不限"
    total = raw.get("total")
    if total in (None, ""):
        return good_next_stock_text(raw)
    try:
        return str(int(total))
    except (TypeError, ValueError):
        return str(total)


def good_next_stock_text(raw: dict[str, Any]) -> str:
    next_num = raw.get("next_num")
    if next_num in (None, ""):
        return "未知"
    try:
        return str(int(next_num))
    except (TypeError, ValueError):
        return str(next_num)


def is_sold_out(raw: dict[str, Any]) -> bool:
    if raw.get("unlimit"):
        return False
    total = raw.get("total")
    if total not in (None, ""):
        return parse_int(total, -1) <= 0
    return parse_int(raw.get("next_num"), -1) <= 0


def good_display_status(raw: dict[str, Any], exchange_ts: int) -> str:
    status = str(raw.get("status") or "")
    sold_out = is_sold_out(raw)
    if exchange_ts > 0 and sold_out:
        return "sold_out_with_next"
    if sold_out:
        return "ended"
    if raw.get("unlimit"):
        return "always"
    if status == "online":
        return "online"
    if exchange_ts > 0:
        return "scheduled"
    return status


def goods_sort_key(good: dict[str, Any]) -> tuple[int, int, int, str]:
    sold_out_rank = 1 if good.get("sold_out") else 0
    online_rank = 0 if good.get("display_status") == "online" else 1
    exchange_ts = parse_int(good.get("exchange_timestamp"), 0)
    return (sold_out_rank, online_rank, exchange_ts or 2_147_483_647, str(good.get("goods_id") or ""))


def format_limit(raw: dict[str, Any]) -> str:
    current = parse_int(raw.get("account_exchange_num"), 0)
    limit = parse_int(raw.get("account_cycle_limit"), 0)
    cycle = str(raw.get("account_cycle_type") or "")
    if cycle == "not_limit" or limit <= 0:
        return "不限购"
    cycle_text = {"forever": "永久", "month": "每月"}.get(cycle, cycle or "周期")
    return f"{cycle_text} {current}/{limit}"


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default
