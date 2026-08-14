from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from agents.llm_trader import LLMSettings, LLMTraderPolicy, ModelResponseError
from agents.recording import (
    RecordingModelClient,
    ReplayModelClient,
    read_calls,
)
from environment.datacontainers import EpisodeConfig
from simulation.episode import run_episode


SETTINGS = LLMSettings(
    api_key="super-secret-key",
    model="test-model",
    endpoint="https://example.test",
    temperature=0.2,
)


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def responses(recipient_id):
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


class RecordingModelClientTests(TestCase):
    def record_one_call(self, path, response):
        client = RecordingModelClient(
            inner=FakeModel([response]),
            path=path,
            settings=SETTINGS,
            tag="trader_a",
        )
        return client

    def test_a_successful_call_is_written_with_its_prompt_and_settings(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calls.jsonl"
            client = self.record_one_call(path, {"private_reasoning": "fine"})

            payload = client.complete("system text", '{"phase": "share"}')

            self.assertEqual(payload, {"private_reasoning": "fine"})
            calls = read_calls(path)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].status, "ok")
            self.assertEqual(calls[0].tag, "trader_a")
            self.assertEqual(calls[0].call_index, 0)
            self.assertEqual(calls[0].system_prompt, "system text")
            self.assertEqual(calls[0].user_prompt, '{"phase": "share"}')
            self.assertEqual(calls[0].response, {"private_reasoning": "fine"})
            self.assertEqual(calls[0].model, "test-model")
            self.assertEqual(calls[0].endpoint, "https://example.test")
            self.assertEqual(calls[0].temperature, 0.2)
            self.assertIsNone(calls[0].error)

    def test_the_api_key_is_never_written(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calls.jsonl"
            client = self.record_one_call(path, {"private_reasoning": "fine"})
            client.complete("system text", "user text")

            self.assertNotIn("super-secret-key", path.read_text(encoding="utf-8"))

    def test_a_failed_call_keeps_the_offending_text_and_re_raises(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calls.jsonl"
            client = self.record_one_call(
                path, ModelResponseError("not valid JSON", "I think you should buy!")
            )

            with self.assertRaises(ModelResponseError):
                client.complete("system text", "user text")

            calls = read_calls(path)
            self.assertEqual(calls[0].status, "error")
            self.assertEqual(calls[0].raw_response, "I think you should buy!")
            self.assertIn("not valid JSON", calls[0].error)
            self.assertIsNone(calls[0].response)

    def test_a_provider_error_keeps_its_status_and_body(self):
        # An SDK HTTP error stringifies to "Error code: 404" and nothing else.
        # Without the body there is no way to tell a retired endpoint from a
        # bad model name after the fact.
        class NotFoundError(Exception):
            status_code = 404
            body = {"error": {"code": "retired", "message": "endpoint is gone"}}

            def __str__(self):
                return "Error code: 404"

        with TemporaryDirectory() as directory:
            path = Path(directory) / "calls.jsonl"
            client = self.record_one_call(path, NotFoundError())

            with self.assertRaises(NotFoundError):
                client.complete("system", "user")

            call = read_calls(path)[0]
            self.assertIn("status 404", call.error)
            self.assertIn("endpoint is gone", call.raw_response)

    def test_calls_are_numbered_and_appended(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calls.jsonl"
            client = RecordingModelClient(
                inner=FakeModel([{"a": 1}, {"b": 2}, {"c": 3}]),
                path=path,
                settings=SETTINGS,
            )
            for _ in range(3):
                client.complete("system", "user")

            self.assertEqual(client.call_count, 3)
            self.assertEqual([call.call_index for call in read_calls(path)], [0, 1, 2])

    def test_the_directory_is_created_when_it_is_missing(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs" / "pilot" / "calls.jsonl"
            client = self.record_one_call(path, {"ok": True})
            client.complete("system", "user")

            self.assertTrue(path.exists())


class ReplayTests(TestCase):
    def run_recorded_episode(self, directory):
        path = Path(directory) / "calls.jsonl"
        policies = {
            "trader_a": LLMTraderPolicy(
                model_client=RecordingModelClient(
                    inner=FakeModel(responses("trader_b")),
                    path=path,
                    settings=SETTINGS,
                    tag="trader_a",
                )
            ),
            "trader_b": LLMTraderPolicy(
                model_client=RecordingModelClient(
                    inner=FakeModel(responses("trader_a")),
                    path=path,
                    settings=SETTINGS,
                    tag="trader_b",
                )
            ),
        }
        result = run_episode(
            EpisodeConfig("replay-test", seed=1, rounds=1), policies=policies
        )
        return path, result

    def test_a_recorded_episode_replays_to_the_same_rounds(self):
        with TemporaryDirectory() as directory:
            path, recorded = self.run_recorded_episode(directory)
            calls = read_calls(path)

            replayed = run_episode(
                EpisodeConfig("replay-test", seed=1, rounds=1),
                policies={
                    trader_id: LLMTraderPolicy(
                        model_client=ReplayModelClient(calls, tag=trader_id)
                    )
                    for trader_id in ("trader_a", "trader_b")
                },
            )

            self.assertEqual(
                [asdict(record) for record in replayed.rounds],
                [asdict(record) for record in recorded.rounds],
            )

    def test_each_trader_replays_only_its_own_calls(self):
        with TemporaryDirectory() as directory:
            path, _ = self.run_recorded_episode(directory)
            calls = read_calls(path)

            self.assertEqual(len(calls), 6)
            self.assertEqual(
                len([call for call in calls if call.tag == "trader_a"]), 3
            )

    def test_a_diverged_prompt_is_rejected(self):
        with TemporaryDirectory() as directory:
            path, _ = self.run_recorded_episode(directory)
            calls = read_calls(path)

            client = ReplayModelClient(calls, tag="trader_a")
            with self.assertRaisesRegex(ValueError, "diverged"):
                client.complete("system text", '{"phase": "not what was recorded"}')

    def test_running_past_the_recording_is_rejected(self):
        with TemporaryDirectory() as directory:
            path, _ = self.run_recorded_episode(directory)
            calls = [call for call in read_calls(path) if call.tag == "trader_a"]

            client = ReplayModelClient(calls, tag="trader_a", check_prompts=False)
            for _ in range(3):
                client.complete("system", "user")

            with self.assertRaisesRegex(ValueError, "more calls than were recorded"):
                client.complete("system", "user")

    def test_a_recorded_failure_is_replayed_as_a_failure(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calls.jsonl"
            recorder = RecordingModelClient(
                inner=FakeModel([ModelResponseError("bad shape", "nonsense")]),
                path=path,
                settings=SETTINGS,
                tag="trader_a",
            )
            with self.assertRaises(ModelResponseError):
                recorder.complete("system", "user")

            client = ReplayModelClient(read_calls(path), tag="trader_a")
            with self.assertRaises(ModelResponseError) as caught:
                client.complete("system", "user")

            self.assertEqual(caught.exception.raw_response, "nonsense")
