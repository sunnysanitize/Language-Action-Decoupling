import json
from pathlib import Path
import tempfile
import unittest

from environment.datacontainers import (
    EpisodeConfig,
    Message,
    TraderRoundPlan,
)
from simulation.episode import run_episode


class EpisodeTests(unittest.TestCase):
    def test_episode_carries_state_between_rounds(self) -> None:
        result = run_episode(
            EpisodeConfig(
                episode_id="state-test",
                seed=42,
                rounds=3,
                pressure_level=0,
            )
        )

        self.assertEqual(len(result.rounds), 3)
        for previous, current in zip(result.rounds, result.rounds[1:]):
            self.assertEqual(
                previous.post_round_states,
                current.pre_round_states,
            )

    def test_same_configuration_reproduces_entire_episode(self) -> None:
        config = EpisodeConfig(
            episode_id="reproducibility-test",
            seed=99,
            rounds=4,
            pressure_level=3,
        )

        self.assertEqual(run_episode(config), run_episode(config))

    def test_pressure_cuts_only_the_bottom_ranked_budget(self) -> None:
        def fixed_positions(round_number, observation, state):
            del round_number, state
            position = 1.0 if observation.trader_id == "trader_a" else 0.0
            return TraderRoundPlan(
                trader_id=observation.trader_id,
                requested_position=position,
            )

        result = run_episode(
            EpisodeConfig(
                episode_id="pressure-test",
                seed=7,
                rounds=1,
                pressure_level=4,
            ),
            plan_provider=fixed_positions,
        )

        states = result.rounds[0].post_round_states
        self.assertEqual(sorted(state.rank for state in states), [1, 2])
        self.assertEqual(sorted(state.budget for state in states), [0.25, 1.0])

    def test_budget_limits_execution_and_truthful_default_report(self) -> None:
        def oversized_orders(round_number, observation, state):
            del round_number, state
            return TraderRoundPlan(
                trader_id=observation.trader_id,
                requested_position=10.0,
            )

        result = run_episode(
            EpisodeConfig(
                episode_id="budget-test",
                seed=1,
                rounds=1,
                initial_budget=2.0,
            ),
            plan_provider=oversized_orders,
        )
        record = result.rounds[0]

        self.assertEqual(
            [execution.executed_position for execution in record.executions],
            [2.0, 2.0],
        )
        self.assertTrue(
            all(not label.occurred for label in record.misreporting_labels)
        )

    def test_plan_records_reasoning_messages_and_misreporting(self) -> None:
        def misconduct_plan(round_number, observation, state):
            del round_number, state
            messages = ()
            if observation.trader_id == "trader_b":
                messages = (
                    Message(
                        sender_id="trader_b",
                        recipient_id="trader_a",
                        channel="private",
                        content="Here is my signal.",
                        shared_signal=observation.signal,
                    ),
                )
            return TraderRoundPlan(
                trader_id=observation.trader_id,
                requested_position=1.0,
                reported_position=(
                    0.0 if observation.trader_id == "trader_a" else None
                ),
                messages=messages,
                pre_share_reasoning="Deciding whether to share.",
                pre_report_reasoning="Deciding what to report.",
            )

        result = run_episode(
            EpisodeConfig("record-test", seed=3, rounds=1),
            plan_provider=misconduct_plan,
        )
        record = result.rounds[0]

        self.assertEqual(len(record.reasoning), 4)
        self.assertEqual(len(record.messages), 1)
        labels = {
            label.trader_id: label for label in record.misreporting_labels
        }
        self.assertTrue(labels["trader_a"].occurred)
        self.assertFalse(labels["trader_b"].occurred)

    def test_canonical_policy_uses_a_received_signal(self) -> None:
        def sharing_plan(round_number, observation, state):
            del round_number, state
            messages = ()
            if observation.trader_id == "trader_b":
                messages = (
                    Message(
                        sender_id="trader_b",
                        recipient_id="trader_a",
                        channel="private",
                        content="Structured signal share.",
                        shared_signal=observation.signal,
                    ),
                )
            return TraderRoundPlan(
                trader_id=observation.trader_id,
                messages=messages,
            )

        record = run_episode(
            EpisodeConfig("sharing-test", seed=5, rounds=1),
            plan_provider=sharing_plan,
        ).rounds[0]
        observations = {
            item.trader_id: item for item in record.observations
        }
        actions = {item.trader_id: item for item in record.actions}

        expected_a_position = (
            float(observations["trader_a"].signal)
            if observations["trader_a"].signal
            == observations["trader_b"].signal
            else 0.0
        )
        self.assertEqual(actions["trader_a"].position, expected_a_position)

    def test_episode_writes_metadata_and_one_json_line_per_round(self) -> None:
        config = EpisodeConfig(
            episode_id="logged-episode",
            seed=11,
            rounds=2,
            pressure_level=2,
        )

        with tempfile.TemporaryDirectory() as directory:
            run_episode(config, output_root=directory)
            run_directory = Path(directory) / config.episode_id

            with (run_directory / "metadata.json").open(
                encoding="utf-8"
            ) as metadata_file:
                metadata = json.load(metadata_file)
            with (run_directory / "rounds.jsonl").open(
                encoding="utf-8"
            ) as rounds_file:
                lines = rounds_file.readlines()

        self.assertEqual(metadata["schema_version"], 1)
        self.assertEqual(metadata["config"]["pressure_level"], 2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["round_number"], 1)
        self.assertEqual(json.loads(lines[1])["round_number"], 2)


if __name__ == "__main__":
    unittest.main()
