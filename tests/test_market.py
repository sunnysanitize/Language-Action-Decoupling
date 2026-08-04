import random
import unittest
from unittest.mock import Mock

from environment.market import (
    MarketRound,
    VALID_DIRECTIONS,
    generate_market_round,
    signal_generation,
)


class SignalGenerationTests(unittest.TestCase):
    def test_returns_true_direction_when_draw_is_below_accuracy(self) -> None:
        rng = Mock(spec=random.Random)
        rng.random.return_value = 0.69

        signal = signal_generation(rng, true_direction=1, accuracy=0.70)

        self.assertEqual(signal, 1)

    def test_returns_opposite_direction_when_draw_equals_accuracy(self) -> None:
        rng = Mock(spec=random.Random)
        rng.random.return_value = 0.70

        signal = signal_generation(rng, true_direction=-1, accuracy=0.70)

        self.assertEqual(signal, 1)

    def test_accuracy_boundaries(self) -> None:
        rng = Mock(spec=random.Random)

        rng.random.return_value = 0.0
        self.assertEqual(
            signal_generation(rng, true_direction=1, accuracy=0.0),
            -1,
        )

        rng.random.return_value = 0.999999
        self.assertEqual(
            signal_generation(rng, true_direction=-1, accuracy=1.0),
            -1,
        )

    def test_rejects_invalid_true_direction(self) -> None:
        rng = random.Random(1)

        for direction in (-2, 0, 2):
            with self.subTest(direction=direction):
                with self.assertRaisesRegex(
                    ValueError,
                    "true_direction must be",
                ):
                    signal_generation(rng, direction, accuracy=0.70)

    def test_rejects_accuracy_outside_probability_range(self) -> None:
        rng = random.Random(1)

        for accuracy in (-0.01, 1.01):
            with self.subTest(accuracy=accuracy):
                with self.assertRaisesRegex(
                    ValueError,
                    "accuracy must be between 0.0 and 1.0",
                ):
                    signal_generation(rng, true_direction=1, accuracy=accuracy)


class GenerateMarketRoundTests(unittest.TestCase):
    def test_same_seed_produces_same_round(self) -> None:
        first = generate_market_round(seed=42)
        second = generate_market_round(seed=42)

        self.assertEqual(first, second)
        self.assertIsInstance(first, MarketRound)
        self.assertEqual(first.seed, 42)

    def test_generated_rounds_obey_market_invariants(self) -> None:
        return_magnitude = 2.5

        for seed in range(25):
            with self.subTest(seed=seed):
                market_round = generate_market_round(
                    seed=seed,
                    return_magnitude=return_magnitude,
                )

                self.assertIn(market_round.market_direction, VALID_DIRECTIONS)
                self.assertIn(market_round.trader_a_signal, VALID_DIRECTIONS)
                self.assertIn(market_round.trader_b_signal, VALID_DIRECTIONS)
                self.assertEqual(
                    market_round.realized_return,
                    market_round.market_direction * return_magnitude,
                )

    def test_perfect_accuracy_makes_both_signals_correct(self) -> None:
        market_round = generate_market_round(seed=7, signal_accuracy=1.0)

        self.assertEqual(
            market_round.trader_a_signal,
            market_round.market_direction,
        )
        self.assertEqual(
            market_round.trader_b_signal,
            market_round.market_direction,
        )

    def test_zero_accuracy_makes_both_signals_incorrect(self) -> None:
        market_round = generate_market_round(seed=7, signal_accuracy=0.0)

        self.assertEqual(
            market_round.trader_a_signal,
            -market_round.market_direction,
        )
        self.assertEqual(
            market_round.trader_b_signal,
            -market_round.market_direction,
        )

    def test_rejects_non_positive_return_magnitude(self) -> None:
        for return_magnitude in (0.0, -0.01):
            with self.subTest(return_magnitude=return_magnitude):
                with self.assertRaisesRegex(
                    ValueError,
                    "return_magnitude must be positive",
                ):
                    generate_market_round(
                        seed=1,
                        return_magnitude=return_magnitude,
                    )

    def test_rejects_invalid_signal_accuracy(self) -> None:
        for accuracy in (-0.01, 1.01):
            with self.subTest(accuracy=accuracy):
                with self.assertRaisesRegex(
                    ValueError,
                    "accuracy must be between 0.0 and 1.0",
                ):
                    generate_market_round(seed=1, signal_accuracy=accuracy)


if __name__ == "__main__":
    unittest.main()
