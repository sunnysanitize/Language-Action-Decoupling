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

    def test_a_field_echoed_back_from_the_prompt_is_ignored(self) -> None:
        # A 70B model repeats prompt keys it reads as instructions. Rejecting
        # the whole response for that throws away a decision the model plainly
        # made, and the echo carries no information the boss acts on.
        model = FakeModel(
            [
                {
                    "private_reasoning": "the desk needs pushing",
                    "phase": "mandate",
                    "content": "work harder",
                }
            ]
        )

        decision = LLMBossPolicy(model_client=model).mandate(self.mandate_context())

        self.assertEqual(decision.content, "work harder")

    def test_a_missing_decision_field_is_still_rejected(self) -> None:
        model = FakeModel([{"private_reasoning": "thinking", "phase": "mandate"}])

        with self.assertRaises(ModelResponseError):
            LLMBossPolicy(model_client=model).mandate(self.mandate_context())

    def test_reasoning_after_the_decision_is_still_rejected(self) -> None:
        # Tolerating extra keys must not tolerate a reasoning field written
        # after the decision it claims to explain.
        model = FakeModel(
            [{"content": "work harder", "extra": 1, "private_reasoning": "late"}]
        )

        with self.assertRaises(ModelResponseError):
            LLMBossPolicy(model_client=model).mandate(self.mandate_context())

    def test_a_review_returns_feedback_per_trader(self) -> None:
        model = FakeModel(
            [{"private_reasoning": "a is behind", "feedback": {"trader_a": "step up"}}]
        )

        decision = LLMBossPolicy(model_client=model).review(self.review_context())

        self.assertEqual(decision.feedback, {"trader_a": "step up"})

    def test_the_review_schema_names_the_real_traders(self) -> None:
        # A placeholder key called "trader_id" is ambiguous, and a real run
        # resolved it the wrong way: the model returned
        # {"trader_id": "trader_b"}, putting the id in the value. Naming the
        # desk's actual ids leaves nothing to interpret.
        model = FakeModel(
            [{"private_reasoning": "ok", "feedback": {"trader_a": "fine"}}]
        )

        LLMBossPolicy(model_client=model).review(self.review_context())

        schema = model.calls[0][1]["response_fields_in_order"]["feedback"]
        self.assertEqual(list(schema), ["trader_a"])

    def test_feedback_for_a_trader_outside_the_desk_is_rejected(self) -> None:
        model = FakeModel(
            [{"private_reasoning": "ok", "feedback": {"trader_z": "hello"}}]
        )

        with self.assertRaises(ModelResponseError):
            LLMBossPolicy(model_client=model).review(self.review_context())

    def test_the_boss_is_never_shown_a_bare_pressure_code(self) -> None:
        # Same rule as the traders. The directive's words carry the condition;
        # the integer is an experiment-side label and reads as a dial.
        model = FakeModel(
            [{"private_reasoning": "ok", "content": "work harder"}]
        )

        LLMBossPolicy(model_client=model).mandate(self.mandate_context())

        self.assertNotIn("pressure_level", json.dumps(model.calls[0][1]))

    def test_the_boss_prompt_never_carries_ground_truth(self) -> None:
        model = FakeModel(
            [{"private_reasoning": "ok", "feedback": {"trader_a": "fine"}}]
        )

        LLMBossPolicy(model_client=model).review(self.review_context())

        prompt = json.dumps(model.calls[0][1])
        self.assertNotIn("executed", prompt)
        self.assertNotIn("realized_return", prompt)
        self.assertNotIn("rank", prompt)


class CapitalAuthorityTests(unittest.TestCase):
    @staticmethod
    def _context():
        return ReviewContext(
            directive=firm_directive(3),
            round_number=1,
            desk=desk_view(DESK_ID, [build_round()], [build_round()]),
            traders=(
                trader_card("trader_a", [build_round()]),
                trader_card("trader_b", [build_round()]),
            ),
        )

    def test_the_rhetorical_boss_returns_no_allocation(self) -> None:
        review = ScriptedBossPolicy().review(self._context())

        self.assertEqual(review.allocation, {})
        self.assertEqual(review.attributed_pnl, {})

    def test_the_capital_boss_returns_an_allocation(self) -> None:
        model = FakeModel(
            [
                {
                    "private_reasoning": "trader_a carried the desk.",
                    "attributed_pnl": {"trader_a": 1.0, "trader_b": -0.5},
                    "allocation": {"trader_a": 1.5, "trader_b": 0.5},
                    "feedback": {"trader_a": "Good.", "trader_b": "Improve."},
                }
            ]
        )

        review = LLMBossPolicy(model, capital_authority=True).review(
            self._context()
        )

        self.assertEqual(review.allocation, {"trader_a": 1.5, "trader_b": 0.5})
        self.assertEqual(
            review.attributed_pnl, {"trader_a": 1.0, "trader_b": -0.5}
        )
        self.assertEqual(review.feedback["trader_a"], "Good.")

    def test_the_capital_boss_uses_its_own_system_prompt(self) -> None:
        from agents.prompts import BOSS_CAPITAL_SYSTEM_PROMPT, BOSS_SYSTEM_PROMPT

        model = FakeModel(
            [
                {
                    "private_reasoning": "Even split.",
                    "attributed_pnl": {"trader_a": 0.0, "trader_b": 0.0},
                    "allocation": {"trader_a": 1.0, "trader_b": 1.0},
                    "feedback": {},
                }
            ]
        )

        LLMBossPolicy(model, capital_authority=True).review(self._context())

        system_prompt = model.calls[0][0]
        self.assertEqual(system_prompt, BOSS_CAPITAL_SYSTEM_PROMPT)
        self.assertNotEqual(system_prompt, BOSS_SYSTEM_PROMPT)

    def test_an_allocation_omitting_a_trader_is_rejected(self) -> None:
        # Unlike feedback, where an absent trader legitimately means "told
        # nothing this cycle", an absent allocation is indistinguishable from
        # a formatting failure and would silently read as zero capital.
        model = FakeModel(
            [
                {
                    "private_reasoning": "Only one matters.",
                    "attributed_pnl": {"trader_a": 1.0, "trader_b": 0.0},
                    "allocation": {"trader_a": 2.0},
                    "feedback": {},
                }
            ]
        )

        with self.assertRaises(ModelResponseError):
            LLMBossPolicy(model, capital_authority=True).review(self._context())

    def test_reasoning_must_still_come_first(self) -> None:
        model = FakeModel(
            [
                {
                    "allocation": {"trader_a": 1.0, "trader_b": 1.0},
                    "private_reasoning": "Written afterwards.",
                    "attributed_pnl": {"trader_a": 0.0, "trader_b": 0.0},
                    "feedback": {},
                }
            ]
        )

        with self.assertRaises(ModelResponseError):
            LLMBossPolicy(model, capital_authority=True).review(self._context())

    def test_attribution_must_precede_allocation(self) -> None:
        # Attribution sampled after the split would be a rationalisation of a
        # decision already made, which is the same reason private_reasoning
        # comes first.
        model = FakeModel(
            [
                {
                    "private_reasoning": "Deciding.",
                    "allocation": {"trader_a": 1.0, "trader_b": 1.0},
                    "attributed_pnl": {"trader_a": 0.0, "trader_b": 0.0},
                    "feedback": {},
                }
            ]
        )

        with self.assertRaises(ModelResponseError):
            LLMBossPolicy(model, capital_authority=True).review(self._context())


if __name__ == "__main__":
    unittest.main()
