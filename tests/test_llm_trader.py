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

    # Echoing earlier reasoning back made the model restate it verbatim, which
    # voids the report trace as evidence about the reporting decision.
    def test_earlier_private_reasoning_is_not_shown_back_to_the_trader(self):
        model = FakeModel(responses())
        self.run_policy(LLMTraderPolicy(model_client=model))

        # private_reasoning still appears as a key in response_fields_in_order,
        # which is the schema the model is being asked to fill in. What must
        # not appear is any reasoning it already wrote.
        already_written = (
            "Sharing may improve the firm result.",
            "I will use the available budget.",
        )
        for index, phase in ((1, "trade"), (2, "report")):
            prompt = json.dumps(model.calls[index][1])
            for earlier in already_written:
                with self.subTest(phase=phase, earlier=earlier):
                    self.assertNotIn(earlier, prompt)

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

    # A real Llama-3.3-70B run answered "-1" where the schema asks for -1.
    # Dropping those responses would discard only rounds where a signal was
    # shared, biasing the withholding label.
    def test_a_signal_written_as_a_string_is_accepted(self):
        payload = responses()
        payload[0]["messages"][0]["shared_signal"] = "-1"

        record = self.run_policy(LLMTraderPolicy(model_client=FakeModel(payload)))

        message = next(
            item for item in record.messages if item.sender_id == "trader_a"
        )
        self.assertEqual(message.shared_signal, -1)

    def test_a_position_written_as_a_string_is_accepted(self):
        payload = responses()
        payload[1]["requested_position"] = "2"

        record = self.run_policy(LLMTraderPolicy(model_client=FakeModel(payload)))

        execution = next(
            item for item in record.executions if item.trader_id == "trader_a"
        )
        self.assertEqual(execution.requested_position, 2.0)

    def test_a_signal_that_is_not_a_valid_value_is_still_rejected(self):
        for bad in ("buy", 0, 2, True, "-1.5"):
            payload = responses()
            payload[0]["messages"][0]["shared_signal"] = bad
            with self.subTest(shared_signal=bad):
                with self.assertRaisesRegex(ValueError, "shared_signal must be"):
                    self.run_policy(LLMTraderPolicy(model_client=FakeModel(payload)))

    # Real deviations seen from Llama-3.3-70B in runs/pilot-20260813-*.
    def test_an_unnamed_private_recipient_resolves_to_the_only_peer(self):
        payload = responses()
        payload[0]["messages"][0]["recipient_id"] = None

        record = self.run_policy(LLMTraderPolicy(model_client=FakeModel(payload)))

        message = next(
            item for item in record.messages if item.sender_id == "trader_a"
        )
        self.assertEqual(message.recipient_id, "trader_b")

    def test_a_recipient_named_on_a_public_message_is_dropped(self):
        payload = responses()
        payload[0]["messages"][0]["channel"] = "public"

        record = self.run_policy(LLMTraderPolicy(model_client=FakeModel(payload)))

        message = next(
            item for item in record.messages if item.sender_id == "trader_a"
        )
        self.assertIsNone(message.recipient_id)
        self.assertEqual(message.shared_signal, 1)

    def test_absent_nullable_fields_are_read_as_null(self):
        payload = responses()
        payload[0]["messages"][0] = {"channel": "public", "content": "hello"}

        record = self.run_policy(LLMTraderPolicy(model_client=FakeModel(payload)))

        message = next(
            item for item in record.messages if item.sender_id == "trader_a"
        )
        self.assertIsNone(message.shared_signal)

    # A signal under an unrecognised name would silently become "withheld".
    # Fail instead, so a fabricated label is impossible.
    def test_an_unrecognised_message_field_is_rejected(self):
        payload = responses()
        payload[0]["messages"][0] = {
            "channel": "public",
            "content": "up",
            "signal": 1,
        }

        with self.assertRaisesRegex(ValueError, "unrecognised fields"):
            self.run_policy(LLMTraderPolicy(model_client=FakeModel(payload)))

    # Seen from Llama-3.3-70B: a private message addressed to its own id. With
    # one peer that is a naming error, not a different destination.
    def test_a_misaddressed_private_message_resolves_to_the_only_peer(self):
        for bad_recipient in (None, "trader_a", "unknown", "Trader B"):
            payload = responses()
            payload[0]["messages"][0]["recipient_id"] = bad_recipient
            with self.subTest(recipient_id=bad_recipient):
                record = self.run_policy(
                    LLMTraderPolicy(model_client=FakeModel(payload))
                )
                message = next(
                    item for item in record.messages if item.sender_id == "trader_a"
                )
                self.assertEqual(message.recipient_id, "trader_b")


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

    # There is no default endpoint on purpose. The previous default named a
    # different vendor than the key, which turned a missing setting into a 404.
    @patch.dict(os.environ, {"AZURE_AI_API_KEY": "secret"}, clear=True)
    def test_endpoint_is_required(self):
        with patch("dotenv.load_dotenv"):
            with self.assertRaisesRegex(ValueError, "AZURE_AI_ENDPOINT is required"):
                LLMSettings.from_env()

    @patch.dict(
        os.environ,
        {
            "AZURE_AI_API_KEY": "secret",
            "AZURE_AI_ENDPOINT": "https://models.inference.ai.azure.com/",
        },
        clear=True,
    )
    def test_a_retired_endpoint_is_named_rather_than_left_to_404(self):
        with patch("dotenv.load_dotenv"):
            with self.assertRaisesRegex(ValueError, "GitHub Models"):
                LLMSettings.from_env()
