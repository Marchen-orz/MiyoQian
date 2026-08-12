# -*- coding: utf-8 -*-

import time
import unittest
from unittest.mock import patch

from miyouqian.service.exchange_scheduler import ExchangeScheduler, PlanWorker


class ExchangeSchedulerReloadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.exchange_at = int(time.time()) + 3600

    def make_plan(self, goods_id: str = "target") -> dict:
        return {
            "goods_id": goods_id,
            "goods_name": goods_id,
            "account_index": 0,
            "exchange_at": self.exchange_at,
            "enable": True,
            "auto": True,
            "last_attempt_key": "",
        }

    def make_scheduler(self, plans: list[dict], run_plan_fn=lambda _index: None) -> ExchangeScheduler:
        return ExchangeScheduler(
            {"shop_exchange": {"enable": True, "plans": plans}},
            run_plan_fn,
            lambda _message: None,
        )

    @patch.object(PlanWorker, "start")
    def test_reload_updates_retained_worker_after_plan_reorder(self, start_worker) -> None:
        target = self.make_plan()
        scheduler = self.make_scheduler([{}, {}, {}, {}, {}, {}, target])
        scheduler.start()
        worker = next(iter(scheduler._workers.values()))
        updated_target = {**target, "goods_name": "updated-target"}

        scheduler.reload({"shop_exchange": {"enable": True, "plans": [updated_target]}})

        self.assertIs(next(iter(scheduler._workers.values())), worker)
        self.assertEqual(worker.index, 0)
        self.assertIs(worker.plan, updated_target)
        start_worker.assert_called_once()

    @patch.object(PlanWorker, "start")
    def test_reordered_worker_runs_current_plan_index(self, _start_worker) -> None:
        executed: list[int] = []
        target = self.make_plan()
        scheduler = self.make_scheduler([{}, {}, {}, {}, {}, {}, target], executed.append)
        scheduler.start()
        worker = next(iter(scheduler._workers.values()))

        scheduler.reload({"shop_exchange": {"enable": True, "plans": [target]}})
        worker.run_fn(worker.index)

        self.assertEqual(executed, [0])


if __name__ == "__main__":
    unittest.main()
