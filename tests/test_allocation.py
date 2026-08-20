import math
import unittest

from simulation.episode import normalize_allocation


TRADERS = ("trader_a", "trader_b")


class NormalizeAllocationTests(unittest.TestCase):
    def test_an_even_split_stays_even(self) -> None:
        result = normalize_allocation(
            {"trader_a": 1.0, "trader_b": 1.0}, TRADERS, pool=2.0
        )

        self.assertEqual(result, {"trader_a": 1.0, "trader_b": 1.0})

    def test_ratios_are_preserved_whatever_units_the_boss_used(self) -> None:
        # Percentages, dollars and arbitrary units must all mean the same
        # thing, so that a boss answering in one is not read as generous or
        # stingy compared with a boss answering in another.
        as_percentages = normalize_allocation(
            {"trader_a": 75.0, "trader_b": 25.0}, TRADERS, pool=2.0
        )
        as_fractions = normalize_allocation(
            {"trader_a": 0.75, "trader_b": 0.25}, TRADERS, pool=2.0
        )

        self.assertEqual(as_percentages, {"trader_a": 1.5, "trader_b": 0.5})
        self.assertEqual(as_percentages, as_fractions)

    def test_the_pool_is_conserved(self) -> None:
        result = normalize_allocation(
            {"trader_a": 3.0, "trader_b": 1.0}, TRADERS, pool=2.0
        )

        self.assertAlmostEqual(sum(result.values()), 2.0)

    def test_a_trader_may_be_allocated_nothing(self) -> None:
        # Starving a trader is a managerial act worth recording, not a
        # failure mode to design around. There is deliberately no floor.
        result = normalize_allocation(
            {"trader_a": 1.0, "trader_b": 0.0}, TRADERS, pool=2.0
        )

        self.assertEqual(result, {"trader_a": 2.0, "trader_b": 0.0})

    def test_allocating_nothing_to_anyone_freezes_the_whole_desk(self) -> None:
        # Coherent: the boss has stopped the desk. Rescaling is undefined
        # here, so it is defined explicitly rather than dividing by zero.
        result = normalize_allocation(
            {"trader_a": 0.0, "trader_b": 0.0}, TRADERS, pool=2.0
        )

        self.assertEqual(result, {"trader_a": 0.0, "trader_b": 0.0})

    def test_a_missing_trader_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_allocation({"trader_a": 1.0}, TRADERS, pool=2.0)

    def test_a_negative_allocation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_allocation(
                {"trader_a": 2.0, "trader_b": -1.0}, TRADERS, pool=2.0
            )

    def test_a_non_finite_allocation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_allocation(
                {"trader_a": math.inf, "trader_b": 1.0}, TRADERS, pool=2.0
            )

    def test_an_unknown_trader_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_allocation(
                {"trader_a": 1.0, "trader_b": 1.0, "trader_z": 1.0},
                TRADERS,
                pool=2.0,
            )


if __name__ == "__main__":
    unittest.main()
