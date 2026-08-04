import unittest

from agents.trader import choose_position
from environment.datacontainers import TraderAction, TraderObservation
from simulation.engine import run_round


class ChoosePositionTests(unittest.TestCase):
    def test_trader_follows_its_signal(self) -> None:
        observation = TraderObservation(
            trader_id="trader_a",
            signal=-1,
            signal_accuracy=0.70,
        )

        action = choose_position(observation)

        self.assertEqual(action, TraderAction("trader_a", -1))


class RunRoundTests(unittest.TestCase):
    def test_round_contains_both_traders(self) -> None:
        result = run_round(seed=1)

        self.assertEqual(len(result.observations), 2)
        self.assertEqual(len(result.actions), 2)
        self.assertEqual(len(result.executions), 2)
        self.assertEqual(len(result.ledger), 2)

    def test_actions_are_executed_and_recorded(self) -> None:
        result = run_round(seed=1)

        for action, execution, ledger_entry in zip(
            result.actions,
            result.executions,
            result.ledger,
        ):
            self.assertEqual(execution.trader_id, action.trader_id)
            self.assertEqual(execution.requested_position, action.position)
            self.assertEqual(execution.executed_position, action.position)
            self.assertEqual(ledger_entry.trader_id, action.trader_id)
            self.assertEqual(ledger_entry.position, action.position)

    def test_ledger_calculates_profit_and_loss(self) -> None:
        result = run_round(seed=1)

        for entry in result.ledger:
            self.assertEqual(
                entry.pnl,
                entry.position * result.world.realized_return,
            )

    def test_perfect_signals_make_both_traders_profitable(self) -> None:
        result = run_round(
            seed=1,
            signal_accuracy=1.0,
            return_magnitude=2.5,
        )

        self.assertEqual([entry.pnl for entry in result.ledger], [2.5, 2.5])


if __name__ == "__main__":
    unittest.main()
