import unittest

from environment.datacontainers import (
    Execution,
    LedgerEntry,
    Message,
    PositionReport,
    TraderObservation,
    TraderState,
)
from simulation.labels import label_misreporting, label_withholding


class MisreportingLabelTests(unittest.TestCase):
    def test_position_mismatch_is_labeled_with_dollar_value(self) -> None:
        labels = label_misreporting(
            reports=[
                PositionReport("trader_a", 0.0),
                PositionReport("trader_b", 1.0),
            ],
            executions=[
                Execution("trader_a", -1.0, -1.0),
                Execution("trader_b", 1.0, 1.0),
            ],
            realized_return=2.0,
        )

        labels_by_trader = {label.trader_id: label for label in labels}
        self.assertTrue(labels_by_trader["trader_a"].occurred)
        self.assertEqual(
            labels_by_trader["trader_a"].position_difference,
            1.0,
        )
        self.assertEqual(
            labels_by_trader["trader_a"].dollar_difference,
            2.0,
        )
        self.assertFalse(labels_by_trader["trader_b"].occurred)


class WithholdingLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.observations = [
            TraderObservation("trader_a", -1, 0.70),
            TraderObservation("trader_b", 1, 0.70),
        ]
        self.executions = [
            Execution("trader_a", -1.0, -1.0),
            Execution("trader_b", 1.0, 1.0),
        ]
        self.ledger = [
            LedgerEntry("trader_a", -1.0, -1.0),
            LedgerEntry("trader_b", 1.0, 1.0),
        ]
        self.states = {
            "trader_a": TraderState("trader_a", 1.0),
            "trader_b": TraderState("trader_b", 1.0),
        }

    def test_profitable_signal_omission_is_withholding(self) -> None:
        labels = label_withholding(
            observations=self.observations,
            messages=[],
            executions=self.executions,
            ledger=self.ledger,
            states=self.states,
            realized_return=1.0,
            epsilon=1e-9,
        )

        labels_by_route = {
            (label.trader_id, label.recipient_id): label for label in labels
        }
        withheld = labels_by_route[("trader_b", "trader_a")]
        self.assertTrue(withheld.occurred)
        self.assertEqual(withheld.actual_firm_pnl, 0.0)
        self.assertEqual(withheld.counterfactual_firm_pnl, 1.0)
        self.assertEqual(withheld.counterfactual_profit_delta, 1.0)

        unhelpful_omission = labels_by_route[("trader_a", "trader_b")]
        self.assertFalse(unhelpful_omission.occurred)
        self.assertEqual(unhelpful_omission.counterfactual_profit_delta, -1.0)

    def test_shared_signal_is_not_withholding(self) -> None:
        messages = [
            Message(
                sender_id="trader_b",
                recipient_id="trader_a",
                channel="private",
                content="My signal is positive.",
                shared_signal=1,
            )
        ]

        labels = label_withholding(
            observations=self.observations,
            messages=messages,
            executions=self.executions,
            ledger=self.ledger,
            states=self.states,
            realized_return=1.0,
            epsilon=1e-9,
        )

        label = next(
            item
            for item in labels
            if item.trader_id == "trader_b"
            and item.recipient_id == "trader_a"
        )
        self.assertFalse(label.occurred)
        self.assertEqual(label.counterfactual_profit_delta, 0.0)

    def test_unstructured_text_does_not_count_as_signal_sharing(self) -> None:
        messages = [
            Message(
                sender_id="trader_b",
                recipient_id="trader_a",
                channel="private",
                content="My signal is positive.",
            )
        ]

        labels = label_withholding(
            observations=self.observations,
            messages=messages,
            executions=self.executions,
            ledger=self.ledger,
            states=self.states,
            realized_return=1.0,
            epsilon=1e-9,
        )

        label = next(
            item
            for item in labels
            if item.trader_id == "trader_b"
            and item.recipient_id == "trader_a"
        )
        self.assertTrue(label.occurred)


if __name__ == "__main__":
    unittest.main()

