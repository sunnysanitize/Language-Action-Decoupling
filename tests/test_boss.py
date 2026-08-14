import json
import unittest
from dataclasses import asdict

from agents.boss import (
    DESK_ID,
    BossMandate,
    BossReview,
    LLMBossPolicy,
    MandateContext,
    ReviewContext,
    ScriptedBossPolicy,
    desk_view,
    firm_directive,
    trader_card,
)
from agents.llm_trader import ModelResponseError
from environment.datacontainers import EpisodeConfig
from simulation.episode import run_episode
from tests.test_llm_trader import FakeModel
from tests.test_memory import SECRET_B_REASONING, SECRET_BC_MESSAGE, build_round


class BossVisionTests(unittest.TestCase):
    """What the boss cannot see is the design.

    P&L, rank and budget are all derived from executed positions, so any
    per-trader view of them could be inverted to recover what a trader really
    held, and a report would hide nothing.
    """

    def test_a_card_shows_what_the_trader_claimed_not_what_it_did(self) -> None:
        # build_round has trader_a executing 1.0 and reporting 0.0.
        card = trader_card("trader_a", [build_round()])

        self.assertEqual(card.rounds[0].reported_position, 0.0)
        self.assertNotIn("executed", json.dumps(asdict(card)))
        self.assertNotIn(1.0, [item.reported_position for item in card.rounds])

    def test_a_card_carries_only_the_traders_public_messages(self) -> None:
        card = trader_card("trader_b", [build_round()])

        # trader_b's only message in build_round is a private one to trader_c.
        self.assertEqual(card.rounds[0].public_messages, ())
        self.assertNotIn(SECRET_BC_MESSAGE, json.dumps(asdict(card)))

    def test_a_card_never_carries_reasoning_or_labels(self) -> None:
        dumped = json.dumps(asdict(trader_card("trader_b", [build_round()])))

        self.assertNotIn(SECRET_B_REASONING, dumped)
        self.assertNotIn("occurred", dumped)

    def test_desk_pnl_is_an_aggregate_that_cannot_be_split_per_trader(self) -> None:
        # build_round: 2.0 + -2.0 + 1.0 = 1.0 across three traders.
        desk = desk_view(DESK_ID, [build_round()], [build_round()])

        self.assertEqual(desk.cumulative_pnl, 1.0)
        self.assertEqual(desk.period_pnl, 1.0)
        self.assertEqual(
            sorted(asdict(desk)), ["cumulative_pnl", "desk_id", "period_pnl"]
        )

    def test_a_missing_report_is_an_error_not_a_silent_gap(self) -> None:
        with self.assertRaises(KeyError):
            trader_card("trader_z", [build_round()])

    def test_the_scripted_boss_speaks_for_the_pressure_condition(self) -> None:
        # A fixture and a control, never evidence of emergent behavior.
        low = firm_directive(0)
        high = firm_directive(4)

        self.assertEqual(low.pressure_level, 0)
        self.assertNotEqual(low.content, high.content)
        self.assertEqual(low.version, high.version)


class RecordingBoss:
    """A boss that answers with traceable text and keeps what it was shown."""

    def __init__(self) -> None:
        self.mandate_contexts = []
        self.review_contexts = []

    def mandate(self, context):
        self.mandate_contexts.append(context)
        return BossMandate(
            private_reasoning="setting expectations",
            content="MANDATE-TEXT",
        )

    def review(self, context):
        self.review_contexts.append(context)
        return BossReview(
            private_reasoning="judging the desk",
            feedback={
                trader_id: f"REVIEW-{context.round_number}-{trader_id}"
                for trader_id in ("trader_a", "trader_b")
            },
        )


class BossScheduleTests(unittest.TestCase):
    def run_with_boss(self, boss, rounds=4, review_interval=1):
        return run_episode(
            EpisodeConfig(
                episode_id="boss-schedule",
                seed=3,
                rounds=rounds,
                review_interval=review_interval,
            ),
            boss=boss,
        )

    def test_the_mandate_reaches_both_traders_before_round_one(self) -> None:
        result = self.run_with_boss(RecordingBoss())

        delivered = result.rounds[0].delivered_feedback
        self.assertEqual([item.content for item in delivered], ["MANDATE-TEXT"])
        self.assertIsNone(delivered[0].trader_id)

    def test_reviews_run_on_the_interval_and_not_after_the_last_round(self) -> None:
        boss = RecordingBoss()
        self.run_with_boss(boss, rounds=4, review_interval=2)

        # Rounds 2 and 4 are review points, but round 4's review could never
        # be delivered, so it is not requested.
        self.assertEqual(
            [context.round_number for context in boss.review_contexts], [2]
        )

    def test_feedback_from_a_review_is_delivered_before_the_next_round(self) -> None:
        result = self.run_with_boss(RecordingBoss(), rounds=2)

        delivered = result.rounds[1].delivered_feedback
        self.assertEqual(
            sorted(item.content for item in delivered),
            ["REVIEW-1-trader_a", "REVIEW-1-trader_b"],
        )

    def test_boss_reasoning_is_recorded_on_the_round_it_belongs_to(self) -> None:
        result = self.run_with_boss(RecordingBoss(), rounds=2)

        phases = {
            (trace.actor_id, trace.phase)
            for record in result.rounds
            for trace in record.reasoning
        }
        self.assertIn(("boss_1", "mandate"), phases)
        self.assertIn(("boss_1", "pre_review"), phases)

    def test_the_boss_only_sees_rounds_since_its_last_review(self) -> None:
        boss = RecordingBoss()
        self.run_with_boss(boss, rounds=3, review_interval=1)

        first, second = boss.review_contexts[0], boss.review_contexts[1]
        self.assertEqual(
            [card.rounds[0].round_number for card in first.traders], [1, 1]
        )
        self.assertEqual(
            [card.rounds[0].round_number for card in second.traders], [2, 2]
        )

    def test_feedback_for_an_unknown_trader_is_rejected(self) -> None:
        class MisaddressingBoss(RecordingBoss):
            def review(self, context):
                return BossReview(feedback={"trader_z": "who are you"})

        with self.assertRaises(ValueError):
            self.run_with_boss(MisaddressingBoss(), rounds=2)

    def test_an_episode_still_runs_with_no_boss(self) -> None:
        result = run_episode(EpisodeConfig("no-boss", seed=3, rounds=2))

        for record in result.rounds:
            self.assertEqual(record.delivered_feedback, [])

    def test_the_trader_is_told_what_the_boss_said(self) -> None:
        result = run_episode(
            EpisodeConfig("scripted-boss", seed=3, rounds=2),
            boss=ScriptedBossPolicy(),
        )

        memory_feedback = [
            item.content
            for item in result.rounds[1].delivered_feedback
        ]
        self.assertTrue(any("Desk P&L" in content for content in memory_feedback))


class LLMBossTests(unittest.TestCase):
    def mandate_context(self):
        return MandateContext(firm_directive(3), DESK_ID, ("trader_a",), 5)

    def review_context(self):
        return ReviewContext(
            directive=firm_directive(3),
            round_number=1,
            desk=desk_view(DESK_ID, [build_round()], [build_round()]),
            traders=(trader_card("trader_a", [build_round()]),),
        )

    def test_the_mandate_call_returns_reasoning_and_text(self) -> None:
        model = FakeModel(
            [{"private_reasoning": "the desk needs pushing", "content": "work harder"}]
        )

        decision = LLMBossPolicy(model_client=model).mandate(self.mandate_context())

        self.assertEqual(decision.content, "work harder")
        self.assertEqual(decision.private_reasoning, "the desk needs pushing")

    def test_reasoning_must_come_before_the_decision(self) -> None:
        # Reasoning sampled after the decision is a rationalisation of a choice
        # already made, and would predict nothing.
        model = FakeModel([{"content": "work harder", "private_reasoning": "late"}])

        with self.assertRaises(ModelResponseError):
            LLMBossPolicy(model_client=model).mandate(self.mandate_context())

    def test_a_review_returns_feedback_per_trader(self) -> None:
        model = FakeModel(
            [{"private_reasoning": "a is behind", "feedback": {"trader_a": "step up"}}]
        )

        decision = LLMBossPolicy(model_client=model).review(self.review_context())

        self.assertEqual(decision.feedback, {"trader_a": "step up"})

    def test_feedback_for_a_trader_outside_the_desk_is_rejected(self) -> None:
        model = FakeModel(
            [{"private_reasoning": "ok", "feedback": {"trader_z": "hello"}}]
        )

        with self.assertRaises(ModelResponseError):
            LLMBossPolicy(model_client=model).review(self.review_context())

    def test_the_boss_prompt_never_carries_ground_truth(self) -> None:
        model = FakeModel(
            [{"private_reasoning": "ok", "feedback": {"trader_a": "fine"}}]
        )

        LLMBossPolicy(model_client=model).review(self.review_context())

        prompt = json.dumps(model.calls[0][1])
        self.assertNotIn("executed", prompt)
        self.assertNotIn("realized_return", prompt)
        self.assertNotIn("rank", prompt)


if __name__ == "__main__":
    unittest.main()
