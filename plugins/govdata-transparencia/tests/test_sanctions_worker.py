from __future__ import annotations

import unittest
from datetime import date

from govdata_transparencia.sanctions_worker import build_sync_plan


class SanctionSyncPlanTests(unittest.TestCase):
    def test_uses_rolling_ceis_and_cnep_window_on_weekdays(self) -> None:
        plan = build_sync_plan(date(2026, 7, 27), lookback_days=30)

        self.assertEqual([task.dataset for task in plan], ["ceis", "cnep"])
        self.assertEqual(
            dict(plan[0].parameters),
            {
                "dataInicialSancao": "27/06/2026",
                "dataFinalSancao": "27/07/2026",
            },
        )

    def test_runs_complete_reconciliation_on_sundays(self) -> None:
        plan = build_sync_plan(date(2026, 8, 2))

        self.assertEqual(
            [task.dataset for task in plan],
            ["ceis", "cnep", "cepim"],
        )
        self.assertTrue(all(not task.parameters for task in plan))

    def test_full_flag_runs_every_dataset_on_a_weekday(self) -> None:
        plan = build_sync_plan(date(2026, 7, 27), full=True)

        self.assertEqual(
            [task.dataset for task in plan],
            ["ceis", "cnep", "cepim"],
        )
        self.assertTrue(all(not task.parameters for task in plan))

    def test_rejects_invalid_lookback(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            build_sync_plan(date(2026, 7, 27), lookback_days=0)


if __name__ == "__main__":
    unittest.main()
