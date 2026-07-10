# -*- coding: utf-8 -*-
"""商品兑换计划调度器。"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import httpx

from .. import constants as c

LogFn = Callable[[str], None]
RunPlanFn = Callable[[int], None]

PRECISE_WAIT_SECONDS = 180
CHECK_INTERVAL_SECONDS = 0.1


class ExchangeScheduler:
    def __init__(self, config: dict[str, Any], run_plan_fn: RunPlanFn, log_fn: LogFn) -> None:
        self.config = config
        self.run_plan_fn = run_plan_fn
        self.log = log_fn
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._workers: dict[str, PlanWorker] = {}
        self._running_plans: set[int] = set()
        self._last_error = ""

    def start(self) -> None:
        self._stop.clear()
        self._rebuild_workers()

    def stop(self) -> None:
        self._stop.set()
        self._stop_workers()

    def reload(self, config: dict[str, Any]) -> None:
        self.config = config
        if not self._stop.is_set():
            self._rebuild_workers()

    def status(self) -> dict[str, Any]:
        with self._lock:
            running_plans = sorted(self._running_plans)
            last_error = self._last_error
            worker_count = len(self._workers)
        next_plan = self._next_plan()
        return {
            "enabled": bool(self._shop_config().get("enable", False)),
            "running_plans": running_plans,
            "running_count": len(running_plans),
            "worker_count": worker_count,
            "next_run": format_ts(next_plan[1]) if next_plan else "",
            "next_plan": next_plan[0] if next_plan else None,
            "last_error": last_error,
        }

    def _rebuild_workers(self) -> None:
        if self._stop.is_set():
            return
        shop = self._shop_config()
        desired: dict[str, tuple[int, dict, int]] = {}
        if shop.get("enable", False):
            now = time.time()
            for index, plan in enumerate(shop.get("plans") or []):
                if not isinstance(plan, dict):
                    continue
                exchange_at = parse_ts(plan.get("exchange_at"))
                if not plan.get("enable", True) or not plan.get("auto", True) or exchange_at <= 0:
                    continue
                attempt_key = self._attempt_key(plan, exchange_at)
                if str(plan.get("last_attempt_key") or "") == attempt_key:
                    continue
                if exchange_at <= now:
                    continue
                desired[attempt_key] = (index, plan, exchange_at)

        with self._lock:
            current_keys = set(self._workers.keys())
            desired_keys = set(desired.keys())
            to_remove = current_keys - desired_keys
            to_add = desired_keys - current_keys

            removed_workers = [self._workers.pop(k) for k in to_remove]
            new_workers: dict[str, PlanWorker] = {}
            for key in to_add:
                index, plan, exchange_at = desired[key]
                worker = PlanWorker(index, plan, exchange_at, key, self._run_worker_plan, self.log)
                self._workers[key] = worker
                new_workers[key] = worker


        current_thread = threading.current_thread()
        for worker in removed_workers:
            worker.stop()
        for worker in removed_workers:
            if worker.is_current_thread(current_thread):
                continue
            worker.join(timeout=1)

        for worker in new_workers.values():
            worker.start()
        if new_workers:
            self.log(f"已启动 {len(new_workers)} 个商品兑换计划线程")

    def _stop_workers(self) -> None:
        """方法现仅用于整体 stop()"""
        with self._lock:
            workers = list(self._workers.values())
            self._workers = {}
        current_thread = threading.current_thread()
        for worker in workers:
            worker.stop()
        for worker in workers:
            if worker.is_current_thread(current_thread):
                continue
            worker.join(timeout=1)

    def _run_worker_plan(self, index: int) -> None:
        with self._lock:
            self._running_plans.add(index)
        try:
            self.run_plan_fn(index)
            with self._lock:
                self._last_error = ""
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            self.log(f"商品兑换计划 {index + 1} 执行失败: {exc}")
        finally:
            with self._lock:
                self._running_plans.discard(index)

    def _next_plan(self) -> tuple[int, int] | None:
        shop = self._shop_config()
        if not shop.get("enable", False):
            return None
        now = int(time.time())
        candidates: list[tuple[int, int]] = []
        for index, plan in enumerate(shop.get("plans") or []):
            if not isinstance(plan, dict):
                continue
            exchange_at = parse_ts(plan.get("exchange_at"))
            if not plan.get("enable", True) or not plan.get("auto", True) or exchange_at <= now:
                continue
            attempt_key = self._attempt_key(plan, exchange_at)
            if str(plan.get("last_attempt_key") or "") == attempt_key:
                continue
            candidates.append((index, exchange_at))
        return min(candidates, key=lambda item: item[1]) if candidates else None

    def _shop_config(self) -> dict[str, Any]:
        shop = self.config.get("shop_exchange", {})
        return shop if isinstance(shop, dict) else {}

    def _attempt_key(self, plan: dict[str, Any], exchange_at: int) -> str:
        return f"{plan.get('goods_id', '')}:{exchange_at}"


class PlanWorker:
    def __init__(
        self,
        index: int,
        plan: dict[str, Any],
        exchange_at: int,
        attempt_key: str,
        run_fn: RunPlanFn,
        log_fn: LogFn,
    ) -> None:
        self.index = index
        self.plan = plan
        self.exchange_at = exchange_at
        self.attempt_key = attempt_key
        self.run_fn = run_fn
        self.log = log_fn
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"miyouqian-exchange-plan-{index + 1}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def is_current_thread(self, thread: threading.Thread) -> bool:
        return self._thread is thread

    def _loop(self) -> None:
        goods_name = self.plan.get("goods_name") or self.plan.get("goods_id") or f"计划 {self.index + 1}"
        target_text = format_ts(self.exchange_at)
        time_offset = sync_server_time_offset(self.log)
        now = lambda: time.time() + time_offset
        prewarm_at = max(self.exchange_at - PRECISE_WAIT_SECONDS, 0)
        self.log(f"商品兑换计划线程已创建: {goods_name}，目标时间 {target_text}")
        if not wait_until(prewarm_at, self._stop, now):
            return
        time_offset = sync_server_time_offset(self.log)
        now = lambda: time.time() + time_offset
        self.log(f"商品兑换计划进入精确等待: {goods_name}，校准目标时间 {target_text}")
        while not self._stop.is_set():
            if now() >= self.exchange_at:
                self.log(f"商品兑换计划到点触发: {goods_name}")
                self.run_fn(self.index)
                return
            self._stop.wait(CHECK_INTERVAL_SECONDS)


def wait_until(target_ts: int, stop_event: threading.Event, now_fn: Callable[[], float] = time.time) -> bool:
    while not stop_event.is_set():
        delay = target_ts - now_fn()
        if delay <= 0:
            return True
        stop_event.wait(min(delay, 30))
    return False


def sync_server_time_offset(log: LogFn) -> float:
    try:
        before = time.time()
        response = httpx.get(
            c.MALL_GOODS_LIST_URL,
            params={"app_id": 1, "point_sn": "myb", "page_size": 1, "page": 1},
            headers={
                "User-Agent": c.DEFAULT_MOBILE_UA,
                "x-rpc-client_type": "5",
                "Referer": "https://user.mihoyo.com/",
            },
            timeout=10,
        )
        after = time.time()
        response.raise_for_status()
        date_header = response.headers.get("Date")
        if not date_header:
            log("服务器时间校准失败: 响应缺少 Date 头，使用本地时间")
            return 0.0
        server_time = parsedate_to_datetime(date_header).timestamp()
        local_midpoint = (before + after) / 2
        offset = server_time - local_midpoint
        log(f"服务器时间校准完成: 偏移 {offset:+.3f}s，RTT {after - before:.3f}s")
        return offset
    except Exception as exc:
        log(f"服务器时间校准失败: {exc}，使用本地时间")
        return 0.0


def parse_ts(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def format_ts(value: int) -> str:
    return datetime.fromtimestamp(value).isoformat(timespec="seconds") if value else ""
