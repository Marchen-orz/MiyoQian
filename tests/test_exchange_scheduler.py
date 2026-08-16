# -*- coding: utf-8 -*-

import time
import unittest
from unittest.mock import patch

from miyouqian.service.exchange_scheduler import ExchangeScheduler, PlanWorker


class ExchangeSchedulerWorkerKeyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.exchange_at = int(time.time()) + 3600

    def make_plan(
        self,
        *,
        goods_id: str,
        account_index: int,
        last_attempt_key: str = "",
    ) -> dict:
        return {
            "goods_id": goods_id,
            "goods_name": goods_id,
            "account_index": account_index,
            "exchange_at": self.exchange_at,
            "enable": True,
            "auto": True,
            "last_attempt_key": last_attempt_key,
        }

    def make_scheduler(self, plans: list[dict]) -> ExchangeScheduler:
        return ExchangeScheduler(
            {"shop_exchange": {"enable": True, "plans": plans}},
            lambda _index: None,
            lambda _message: None,
        )

    @patch.object(PlanWorker, "start")
    def test_same_goods_and_time_use_one_worker_per_account(self, start_worker) -> None:
        plans = [
            self.make_plan(goods_id="same-good", account_index=0),
            self.make_plan(goods_id="same-good", account_index=1),
        ]
        scheduler = self.make_scheduler(plans)

        scheduler.start()

        self.assertEqual(scheduler.status()["worker_count"], 2)
        self.assertEqual({worker.index for worker in scheduler._workers.values()}, {0, 1})
        self.assertEqual(
            set(scheduler._workers),
            {
                f"0:same-good:{self.exchange_at}",
                f"1:same-good:{self.exchange_at}",
            },
        )
        self.assertEqual(start_worker.call_count, 2)

    @patch.object(PlanWorker, "start")
    def test_completed_account_does_not_suppress_other_account(self, start_worker) -> None:
        attempt_key = f"same-good:{self.exchange_at}"
        plans = [
            self.make_plan(
                goods_id="same-good",
                account_index=0,
                last_attempt_key=attempt_key,
            ),
            self.make_plan(goods_id="same-good", account_index=1),
        ]
        scheduler = self.make_scheduler(plans)

        scheduler.start()

        self.assertEqual(scheduler.status()["worker_count"], 1)
        worker = next(iter(scheduler._workers.values()))
        self.assertEqual(worker.index, 1)
        start_worker.assert_called_once()

    def test_attempt_key_format_remains_compatible_with_saved_plans(self) -> None:
        plan = self.make_plan(goods_id="same-good", account_index=1)
        scheduler = self.make_scheduler([plan])

        self.assertEqual(
            scheduler._attempt_key(plan, self.exchange_at),
            f"same-good:{self.exchange_at}",
        )


if __name__ == "__main__":
    unittest.main()
