# -*- coding: utf-8 -*-
"""商品兑换计划调度器。"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Callable

LogFn = Callable[[str], None]
RunPlanFn = Callable[[int], None]


class ExchangeScheduler:
    def __init__(self, config: dict[str, Any], run_plan_fn: RunPlanFn, log_fn: LogFn) -> None:
        self.config = config
        self.run_plan_fn = run_plan_fn
        self.log = log_fn
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._running_plan: int | None = None
        self._last_error = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="miyouqian-exchange-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def reload(self, config: dict[str, Any]) -> None:
        self.config = config
        self._wake.set()

    def status(self) -> dict[str, Any]:
        with self._lock:
            running_plan = self._running_plan
            last_error = self._last_error
        next_plan = self._next_plan()
        return {
            "enabled": bool(self._shop_config().get("enable", False)),
            "running": running_plan is not None,
            "running_plan": running_plan,
            "next_run": format_ts(next_plan[1]) if next_plan else "",
            "next_plan": next_plan[0] if next_plan else None,
            "last_error": last_error,
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            due = self._due_plan_indices()
            if not due:
                self._wake.wait(timeout=1)
                self._wake.clear()
                continue
            for index in due:
                if self._stop.is_set():
                    return
                with self._lock:
                    if self._running_plan is not None:
                        break
                    self._running_plan = index
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
                        self._running_plan = None

    def _due_plan_indices(self) -> list[int]:
        shop = self._shop_config()
        if not shop.get("enable", False):
            return []
        now = int(time.time())
        indices: list[int] = []
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
                indices.append(index)
        return indices

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


def parse_ts(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def format_ts(value: int) -> str:
    return datetime.fromtimestamp(value).isoformat(timespec="seconds") if value else ""
