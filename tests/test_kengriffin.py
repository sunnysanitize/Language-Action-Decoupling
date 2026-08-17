import json
import unittest
from dataclasses import asdict

from agents.boss import BossMandate, BossReview
from agents.kengriffin import (
    KEN_ID,
    LLMOverseerPolicy,
    OverseerContext,
    OverseerDecision,
    PortfolioView,
    ScriptedOverseerPolicy,
    firm_directive,
)
from agents.llm_trader import ModelResponseError
from environment.datacontainers import EpisodeConfig
from simulation.episode import run_episode
from tests.test_llm_trader import FakeModel


class RecordingOverseer:
    def __init__(self):
        self.mandates = []
        self.reviews = []

    def mandate(self, context):
        self.mandates.append(context)
        return OverseerDecision("setting policy", "INITIAL")

    def review(self, context):
        self.reviews.append(context)
        return OverseerDecision("reviewing desk", "UPDATED")


class RecordingBoss:
    def __init__(self):
        self.mandates = []
        self.reviews = []

    def mandate(self, context):
        self.mandates.append(context)
        return BossMandate(content=context.directive.content)

    def review(self, context):
        self.reviews.append(context)
        return BossReview(
            feedback={
                trader_id: context.directive.content
                for trader_id in ("trader_a", "trader_b")
            }
        )


class OverseerScheduleTests(unittest.TestCase):
    def test_directives_flow_through_the_boss(self):
        overseer = RecordingOverseer()
        boss = RecordingBoss()

        result = run_episode(
            EpisodeConfig("overseer", seed=3, rounds=2),
            boss=boss,
            overseer=overseer,
        )

        self.assertEqual(boss.mandates[0].directive.content, "INITIAL")
        self.assertEqual(boss.reviews[0].directive.content, "UPDATED")
        self.assertEqual(
            {item.content for item in result.rounds[1].delivered_feedback},
            {"UPDATED"},
        )

    def test_review_sees_only_portfolio_level_results(self):
        overseer = RecordingOverseer()
        run_episode(
            EpisodeConfig("overseer-view", seed=3, rounds=2),
            boss=RecordingBoss(),
            overseer=overseer,
        )

        dumped = json.dumps(asdict(overseer.reviews[0]))
        self.assertIn("period_pnl", dumped)
        self.assertNotIn("trader_a", dumped)
        self.assertNotIn("executed", dumped)

    def test_reasoning_is_recorded(self):
        result = run_episode(
            EpisodeConfig("overseer-reasoning", seed=3, rounds=2),
            boss=RecordingBoss(),
            overseer=RecordingOverseer(),
        )

        phases = {
            (trace.actor_id, trace.phase)
            for record in result.rounds
            for trace in record.reasoning
        }
        self.assertIn((KEN_ID, "mandate"), phases)
        self.assertIn((KEN_ID, "pre_review"), phases)

    def test_scripted_policy_keeps_the_treatment(self):
        policy = ScriptedOverseerPolicy()
        context = OverseerContext(
            treatment=firm_directive(4).content,
            round_number=1,
            total_rounds=2,
            portfolios=(PortfolioView("desk_1", -1.0, -1.0),),
        )

        self.assertIn(context.treatment, policy.review(context).content)


class LLMOverseerTests(unittest.TestCase):
    def context(self):
        return OverseerContext("Push for stronger performance.", 0, 5)

    def test_returns_reasoning_and_direction(self):
        model = FakeModel(
            [{"private_reasoning": "set expectations", "content": "Improve returns."}]
        )

        decision = LLMOverseerPolicy(model_client=model).mandate(self.context())

        self.assertEqual(decision.content, "Improve returns.")
        self.assertEqual(decision.private_reasoning, "set expectations")

    def test_reasoning_must_come_first(self):
        model = FakeModel(
            [{"content": "Improve returns.", "private_reasoning": "late"}]
        )

        with self.assertRaises(ModelResponseError):
            LLMOverseerPolicy(model_client=model).mandate(self.context())

    def test_prompt_does_not_expose_the_pressure_code(self):
        model = FakeModel(
            [{"private_reasoning": "ok", "content": "Improve returns."}]
        )

        LLMOverseerPolicy(model_client=model).mandate(self.context())

        self.assertNotIn("pressure_level", json.dumps(model.calls[0][1]))


if __name__ == "__main__":
    unittest.main()
