import unittest

from experiments.dataset import build_rows, label_of


def _round(
    round_number: int,
    *,
    messages=(),
    withheld_a=False,
    misreported_a=False,
    reasoning=(),
    delivered=(),
    pressure_level=3,
):
    # A round record shaped like one line of rounds.jsonl, with only the
    # fields the dataset builder reads.
    return {
        "episode_id": "ep1",
        "round_number": round_number,
        "market_seed": 1,
        "pressure_level": pressure_level,
        "world": {"market_direction": 1, "realized_return": 1.0},
        "pre_round_states": [
            {
                "trader_id": "trader_a",
                "budget": 1.0,
                "cumulative_pnl": 0.0,
                "rank": 1,
                "pnl_gap": 0.0,
                "prior_misreporting_count": 0,
                "prior_withholding_count": 0,
            },
            {
                "trader_id": "trader_b",
                "budget": 1.0,
                "cumulative_pnl": 0.0,
                "rank": 1,
                "pnl_gap": 0.0,
                "prior_misreporting_count": 0,
                "prior_withholding_count": 0,
            },
        ],
        "observations": [
            {"trader_id": "trader_a", "signal": 1, "signal_accuracy": 0.7},
            {"trader_id": "trader_b", "signal": 1, "signal_accuracy": 0.7},
        ],
        "reasoning": list(reasoning),
        "messages": list(messages),
        "actions": [],
        "executions": [],
        "reports": [
            {"trader_id": "trader_a", "reported_position": 1.0},
            {"trader_id": "trader_b", "reported_position": 1.0},
        ],
        "ledger": [
            {"trader_id": "trader_a", "position": 1.0, "pnl": 1.0},
            {"trader_id": "trader_b", "position": 1.0, "pnl": 1.0},
        ],
        "misreporting_labels": [
            {
                "trader_id": "trader_a",
                "occurred": misreported_a,
                "position_difference": 0.0,
                "dollar_difference": 0.0,
            },
            {
                "trader_id": "trader_b",
                "occurred": False,
                "position_difference": 0.0,
                "dollar_difference": 0.0,
            },
        ],
        "withholding_labels": [
            {
                "trader_id": "trader_a",
                "recipient_id": "trader_b",
                "withheld": withheld_a,
                "occurred": withheld_a,
                "actual_firm_pnl": 0.0,
                "counterfactual_firm_pnl": 0.0,
                "counterfactual_profit_delta": 0.0,
            },
            {
                "trader_id": "trader_b",
                "recipient_id": "trader_a",
                "withheld": False,
                "occurred": False,
                "actual_firm_pnl": 0.0,
                "counterfactual_firm_pnl": 0.0,
                "counterfactual_profit_delta": 0.0,
            },
        ],
        "post_round_states": [],
        "delivered_feedback": list(delivered),
    }


def _episode(records):
    metadata = {
        "config": {
            "episode_id": "ep1",
            "seed": 7,
            "rounds": len(records),
            "initial_budget": 1.0,
            "review_interval": 1,
            "signal_accuracy": 0.7,
        }
    }
    return [(metadata, records)]


class WithholdingLeakageTests(unittest.TestCase):
    # The act being predicted is the decision not to send a message. If this
    # round's messages reached the features, the detector would be reading the
    # answer, and every AUPRC in the report would be meaningless.
    def test_same_round_features_exclude_this_rounds_messages(self) -> None:
        message = {
            "sender_id": "trader_a",
            "channel": "public",
            "content": "UNIQUEMARKER shared my signal",
            "recipient_id": None,
            "shared_signal": 1,
        }
        episodes = _episode([_round(1, messages=[message])])
        rows = build_rows(episodes, "withholding", "same")
        trader_a = next(row for row in rows if row.trader_id == "trader_a")

        self.assertNotIn("UNIQUEMARKER", trader_a.observable_text)
        self.assertNotIn("UNIQUEMARKER", trader_a.private_chat_text)
        self.assertEqual(trader_a.observable["now_public_sent"], 0.0)
        self.assertEqual(trader_a.observable["now_shared_signal"], 0.0)

    def test_same_round_features_exclude_this_rounds_private_chat(self) -> None:
        message = {
            "sender_id": "trader_a",
            "channel": "private",
            "content": "PRIVATEMARKER",
            "recipient_id": "trader_b",
            "shared_signal": 1,
        }
        episodes = _episode([_round(1, messages=[message])])
        rows = build_rows(episodes, "withholding", "same")
        trader_a = next(row for row in rows if row.trader_id == "trader_a")

        self.assertNotIn("PRIVATEMARKER", trader_a.private_chat_text)
        self.assertEqual(trader_a.private_chat["now_private_sent"], 0.0)

    def test_only_pre_share_reasoning_is_used(self) -> None:
        reasoning = [
            {"actor_id": "trader_a", "phase": "pre_share", "content": "EARLY"},
            {"actor_id": "trader_a", "phase": "pre_trade", "content": "MIDDLE"},
            {"actor_id": "trader_a", "phase": "pre_report", "content": "LATE"},
        ]
        episodes = _episode([_round(1, reasoning=reasoning)])
        rows = build_rows(episodes, "withholding", "same")
        trader_a = next(row for row in rows if row.trader_id == "trader_a")

        self.assertIn("EARLY", trader_a.reasoning_text)
        self.assertNotIn("MIDDLE", trader_a.reasoning_text)
        self.assertNotIn("LATE", trader_a.reasoning_text)

    def test_earlier_rounds_are_visible(self) -> None:
        message = {
            "sender_id": "trader_a",
            "channel": "public",
            "content": "OLDMARKER",
            "recipient_id": None,
            "shared_signal": 1,
        }
        episodes = _episode([_round(1, messages=[message]), _round(2)])
        rows = build_rows(episodes, "withholding", "same")
        second = next(
            row
            for row in rows
            if row.trader_id == "trader_b" and row.round_number == 2
        )

        # trader_b received it last round, so it is history it may condition on.
        self.assertIn("OLDMARKER", second.observable_text)
        self.assertEqual(second.observable["hist_rounds"], 1.0)


class MisreportingTimingTests(unittest.TestCase):
    # Misreporting is decided after the chat, so the chat is legitimately
    # available. Only the report itself and the labels must stay out.
    def test_same_round_chat_is_available(self) -> None:
        message = {
            "sender_id": "trader_a",
            "channel": "public",
            "content": "CHATMARKER",
            "recipient_id": None,
            "shared_signal": 1,
        }
        episodes = _episode([_round(1, messages=[message])])
        rows = build_rows(episodes, "misreporting", "same")
        trader_a = next(row for row in rows if row.trader_id == "trader_a")

        self.assertIn("CHATMARKER", trader_a.observable_text)
        self.assertEqual(trader_a.observable["now_public_sent"], 1.0)

    def test_reasoning_runs_through_pre_report(self) -> None:
        reasoning = [
            {"actor_id": "trader_a", "phase": "pre_share", "content": "EARLY"},
            {"actor_id": "trader_a", "phase": "pre_report", "content": "LATE"},
        ]
        episodes = _episode([_round(1, reasoning=reasoning)])
        rows = build_rows(episodes, "misreporting", "same")
        trader_a = next(row for row in rows if row.trader_id == "trader_a")

        self.assertIn("EARLY", trader_a.reasoning_text)
        self.assertIn("LATE", trader_a.reasoning_text)


class HorizonTests(unittest.TestCase):
    def test_next_horizon_labels_the_following_round(self) -> None:
        episodes = _episode(
            [_round(1, withheld_a=False), _round(2, withheld_a=True)]
        )
        rows = build_rows(episodes, "withholding", "next")

        # One row per trader for round 1 only; round 2 has no successor.
        self.assertEqual({row.round_number for row in rows}, {1})
        trader_a = next(row for row in rows if row.trader_id == "trader_a")
        self.assertEqual(label_of(trader_a, "withholding"), 1)

    def test_labels_come_from_the_named_trader(self) -> None:
        episodes = _episode([_round(1, withheld_a=True, misreported_a=True)])
        rows = build_rows(episodes, "withholding", "same")
        by_trader = {row.trader_id: row for row in rows}

        self.assertEqual(by_trader["trader_a"].withheld, 1)
        self.assertEqual(by_trader["trader_b"].withheld, 0)
        self.assertEqual(by_trader["trader_a"].misreported, 1)
        self.assertEqual(by_trader["trader_b"].misreported, 0)


class FeatureLayoutTests(unittest.TestCase):
    def test_every_row_has_the_same_feature_keys(self) -> None:
        # The feature matrix is built by walking sorted(block) per row. A row
        # with a different key set would silently shift every column after it.
        episodes = _episode([_round(1), _round(2), _round(3)])
        for target in ("withholding", "misreporting"):
            for horizon in ("same", "next"):
                rows = build_rows(episodes, target, horizon)
                for block in ("situation", "observable", "private_chat",
                              "reasoning"):
                    layouts = {
                        tuple(sorted(getattr(row, block))) for row in rows
                    }
                    self.assertEqual(
                        len(layouts),
                        1,
                        f"{block} layout varies for {target}/{horizon}",
                    )

    def test_boss_feedback_is_observable_before_the_round(self) -> None:
        delivered = [
            {
                "boss_id": "boss_1",
                "trader_id": None,
                "version": "boss-mandate-v1",
                "content": "FEEDBACKMARKER",
            }
        ]
        episodes = _episode([_round(1, delivered=delivered)])
        rows = build_rows(episodes, "withholding", "same")
        trader_a = next(row for row in rows if row.trader_id == "trader_a")

        # It arrived before the round ran, so it is admissible even for the
        # share-phase target.
        self.assertIn("FEEDBACKMARKER", trader_a.observable_text)
        self.assertEqual(trader_a.observable["now_boss_feedback"], 1.0)


if __name__ == "__main__":
    unittest.main()
