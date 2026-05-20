# -*- coding: utf-8 -*-
"""米游社商品兑换。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .. import constants as c
from ..core import crypto
from ..core.http import ApiClient

EmitFn = Callable[[str], None]
BJT = timezone(timedelta(hours=8))


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
        goods: list[dict[str, Any]] = []
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
            for item in page_goods:
                if not isinstance(item, dict):
                    continue
                goods.append(normalize_good(self._enrich_good_for_time(item)))
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

    def fetch_device_fp(self) -> str:
        device_id = str(self.device.get("id") or crypto.device_id()).lower()
        body = {
            "seed_id": crypto.device_fp()[:8],
            "device_id": device_id,
            "platform": "5",
            "seed_time": str(int(time.time() * 1000)),
            "ext_fields": (
                "{\"userAgent\":\""
                + c.DEFAULT_MOBILE_UA.replace('"', '\\"')
                + "\",\"browserScreenSize\":243750,\"maxTouchPoints\":5,"
                "\"isTouchSupported\":true,\"browserLanguage\":\"zh-CN\",\"browserPlat\":\"iPhone\","
                "\"browserTimeZone\":\"Asia/Shanghai\",\"webGlRender\":\"Apple GPU\","
                "\"webGlVendor\":\"Apple Inc.\",\"numOfPlugins\":0,\"listOfPlugins\":\"unknown\","
                "\"screenRatio\":3,\"deviceMemory\":\"unknown\",\"hardwareConcurrency\":\"4\","
                "\"cpuClass\":\"unknown\",\"ifNotTrack\":\"unknown\",\"ifAdBlock\":0,"
                "\"hasLiedResolution\":1,\"hasLiedOs\":0,\"hasLiedBrowser\":0}"
            ),
            "app_name": "account_cn",
            "device_fp": crypto.device_fp(),
        }
        data = self.client.post_json(c.DEVICE_FP_URL, json=body)
        raw = data.get("data") or {}
        device_fp = str(raw.get("device_fp") or "")
        if data.get("retcode") != 0 or not device_fp:
            raise ValueError(str(raw.get("msg") or data.get("message") or "device_fp 获取失败"))
        return device_fp

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
        data = self.client.post_json(c.MALL_EXCHANGE_URL, json=body, headers=self._exchange_headers())
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

    def exchange_with_retry(self, plan: dict[str, Any]) -> dict[str, Any]:
        shop = self.config.get("shop_exchange", {})
        duration = max(float(shop.get("retry_seconds") or 0), 0)
        interval = max(float(shop.get("retry_interval") or 0.4), 0.05)
        deadline = time.time() + duration
        last: dict[str, Any] = {}
        attempt = 0
        while True:
            attempt += 1
            self._add(f"正在发送第 {attempt} 次商品兑换请求")
            last = self.exchange(plan)
            last["attempt"] = attempt
            if last.get("ok") or time.time() >= deadline:
                return last
            time.sleep(interval)

    def _goods_headers(self) -> dict[str, str]:
        return {
            "Host": "api-takumi.mihoyo.com",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://user.mihoyo.com",
            "Connection": "keep-alive",
            "x-rpc-device_id": str(self.device["id"]),
            "x-rpc-client_type": "5",
            "User-Agent": c.DEFAULT_MOBILE_UA,
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
            "User-Agent": c.DEFAULT_MOBILE_UA,
            "Referer": f"{origin}/",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Cookie": str(self.account.get("cookie") or ""),
        }

    def _exchange_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Connection": "keep-alive",
            "Content-Type": "application/json;charset=utf-8",
            "Host": "api-takumi.miyoushe.com",
            "Origin": "https://webstatic.miyoushe.com",
            "Referer": "https://webstatic.miyoushe.com/",
            "User-Agent": c.DEFAULT_MOBILE_UA,
            "x-rpc-app_version": c.BBS_VERSION,
            "x-rpc-channel": "appstore",
            "x-rpc-client_type": "1",
            "x-rpc-verify_key": c.PASSPORT_APP_ID,
            "x-rpc-device_fp": str(self.device.get("fp") or crypto.device_fp()),
            "x-rpc-device_id": str(self.device["id"]),
            "x-rpc-device_model": str(self.device.get("model") or "Mi 6"),
            "x-rpc-device_name": str(self.device.get("name") or "Xiaomi MI 6"),
            "x-rpc-sys_version": "12",
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
        if key:
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
