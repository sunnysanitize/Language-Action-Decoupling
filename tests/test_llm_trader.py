import json
import os
from unittest import TestCase
from unittest.mock import patch

from agents.llm_trader import LLMSettings, LLMTraderPolicy
from environment.datacontainers import EpisodeConfig
from simulation.episode import run_episode


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, json.loads(user_prompt)))
        return self.responses.pop(0)


def responses(recipient_id="trader_b"):
    return [
        {
            "private_reasoning": "Sharing may improve the firm result.",
            "messages": [
                {
                    "channel": "private",
                    "content": "My signal is positive.",
                    "recipient_id": recipient_id,
                    "shared_signal": 1,
                }
            ],
        },
        {
            "private_reasoning": "I will use the available budget.",
            "requested_position": 2,
        },
        {
            "private_reasoning": "I will report the clipped execution.",
            "reported_position": 1,
        },
    ]


class LLMTraderPolicyTests(TestCase):
    def run_policy(self, policy):
        return run_episode(
            EpisodeConfig("llm-test", seed=1, rounds=1),
            policies={
                "trader_a": policy,
                "trader_b": LLMTraderPolicy(
                    model_client=FakeModel(responses("trader_a"))
                ),
            },
        ).rounds[0]

    def test_one_model_call_is_made_for_each_phase(self):
        model = FakeModel(responses())
        record = self.run_policy(LLMTraderPolicy(model_client=model))

        self.assertEqual(
            [call[1]["phase"] for call in model.calls],
            ["share", "trade", "report"],
        )
        self.assertEqual(
            [
                trace.content
                for trace in record.reasoning
                if trace.trader_id == "trader_a"
            ],
            [
                "Sharing may improve the firm result.",
                "I will use the available budget.",
                "I will report the clipped execution.",
            ],
        )

    def test_phase_context_and_prior_decisions_are_available(self):
        model = FakeModel(responses())
        self.run_policy(LLMTraderPolicy(model_client=model))

        trade_prompt = model.calls[1][1]
        report_prompt = model.calls[2][1]
        self.assertEqual(
            trade_prompt["messages_you_sent"][0]["sender_id"],
            "trader_a",
        )
        self.assertEqual(
            report_prompt["trade_decision"]["requested_position"],
            2.0,
        )
        self.assertNotIn("realized_return", json.dumps(report_prompt))

    def test_model_message_sender_is_set_by_the_policy(self):
        record = self.run_policy(
            LLMTraderPolicy(model_client=FakeModel(responses()))
        )

        message = next(
            item for item in record.messages if item.sender_id == "trader_a"
        )
        self.assertEqual(message.recipient_id, "trader_b")

    def test_private_reasoning_must_be_the_first_field(self):
        model = FakeModel([
            {"messages": [], "private_reasoning": "Too late."},
        ])

        with self.assertRaisesRegex(ValueError, "fields must be in this order"):
            self.run_policy(LLMTraderPolicy(model_client=model))

    def test_invalid_private_recipient_is_rejected(self):
        bad = responses()
        bad[0]["messages"][0]["recipient_id"] = "unknown"

        with self.assertRaisesRegex(ValueError, "must name a peer"):
            self.run_policy(LLMTraderPolicy(model_client=FakeModel(bad)))


class LLMSettingsTests(TestCase):
    @patch.dict(
        os.environ,
        {
            "AZURE_AI_API_KEY": "secret",
            "AZURE_AI_MODEL": "test-model",
            "AZURE_AI_ENDPOINT": "https://example.test/v1",
            "AZURE_AI_TEMPERATURE": "0.2",
        },
        clear=True,
    )
    def test_settings_load_from_environment(self):
        settings = LLMSettings.from_env()

        self.assertEqual(settings.api_key, "secret")
        self.assertEqual(settings.model, "test-model")
        self.assertEqual(settings.endpoint, "https://example.test/v1")
        self.assertEqual(settings.temperature, 0.2)

    @patch.dict(os.environ, {}, clear=True)
    def test_api_key_is_required(self):
        with patch("dotenv.load_dotenv"):
            with self.assertRaisesRegex(ValueError, "AZURE_AI_API_KEY"):
                LLMSettings.from_env()
