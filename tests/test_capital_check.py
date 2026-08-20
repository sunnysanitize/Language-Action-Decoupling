import unittest

from experiments.capital_check import (
    attribution_follows_reports,
    claims_above_budget,
    starvation_events,
)
from tests.test_dataset import _episode, _round


def _with_allocation(record, attributed, allocated):
    record["capital_allocations"] = [
        {
            "boss_id": "boss_1",
            "round_number": record["round_number"],
            "attributed_pnl": attributed,
            "allocated_budget": allocated,
        }
    ]
    return record


class AttributionTests(unittest.TestCase):
    def test_attribution_matching_reports_is_detected(self) -> None:
        # _round reports 1.0 for both traders and executes nothing, so an
        # attribution proportional to the reports is the signature we want.
        record = _with_allocation(
            _round(1),
            {"trader_a": 1.0, "trader_b": 1.0},
            {"trader_a": 1.0, "trader_b": 1.0},
        )

        result = attribution_follows_reports(_episode([record]))

        self.assertEqual(result["reviews"], 1)

    def test_no_allocations_means_nothing_to_measure(self) -> None:
        result = attribution_follows_reports(_episode([_round(1)]))

        self.assertEqual(result["reviews"], 0)


class StarvationTests(unittest.TestCase):
    def test_a_zero_allocation_is_counted(self) -> None:
        record = _with_allocation(
            _round(1),
            {"trader_a": 1.0, "trader_b": 0.0},
            {"trader_a": 2.0, "trader_b": 0.0},
        )

        result = starvation_events(_episode([record]))

        self.assertEqual(result["events"], 1)
        self.assertEqual(result["traders"], {"trader_b": 1})

    def test_an_even_split_is_not_starvation(self) -> None:
        record = _with_allocation(
            _round(1),
            {"trader_a": 0.0, "trader_b": 0.0},
            {"trader_a": 1.0, "trader_b": 1.0},
        )

        result = starvation_events(_episode([record]))

        self.assertEqual(result["events"], 0)


class BudgetCeilingTests(unittest.TestCase):
    def test_a_claim_above_the_allocated_budget_is_flagged(self) -> None:
        # The budget ceiling is the one channel that catches an individual
        # liar: a trader cannot hold more than it was allocated.
        first = _with_allocation(
            _round(1),
            {"trader_a": 0.0, "trader_b": 0.0},
            {"trader_a": 0.5, "trader_b": 1.5},
        )
        second = _round(2)  # both traders report 1.0
        result = claims_above_budget(_episode([first, second]))

        self.assertEqual(result["claims"], 1)
        self.assertEqual(result["traders"], {"trader_a": 1})


if __name__ == "__main__":
    unittest.main()
