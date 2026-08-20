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

        # Version 2 renamed ReasoningTrace.trader_id to actor_id and added
        # delivered_feedback, so a schema 1 reader cannot parse these rounds.
        # Version 3 added capital_allocations, so a schema 2 reader cannot
        # parse these rounds either.
        self.assertEqual(metadata["schema_version"], 3)
        self.assertEqual(metadata["config"]["pressure_level"], 2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["round_number"], 1)
        self.assertEqual(json.loads(lines[1])["round_number"], 2)
        self.assertEqual(json.loads(lines[0])["delivered_feedback"], [])


class ControlArmTests(unittest.TestCase):
    """The rhetorical boss is the default and must never drift.

    Every recorded run in runs/ and every number in RESULTS.md was produced
    by this arm. If a later change alters it, the existing sweep stops being
    a valid comparison and would have to be re-run.
    """

    def test_capital_authority_is_off_by_default(self) -> None:
        config = EpisodeConfig(episode_id="default", seed=1)

        self.assertFalse(config.boss_capital_authority)

    def test_default_episode_budgets_are_unchanged(self) -> None:
        # Pinned from the current implementation: pressure 3 halves the
        # bottom-ranked trader's budget at each review.
        config = EpisodeConfig(
            episode_id="control", seed=7, rounds=4, pressure_level=3
        )

        result = run_episode(config)

        budgets = [
            {state.trader_id: state.budget for state in record.post_round_states}
            for record in result.rounds
        ]
        self.assertEqual(len(budgets), 4)
        for row in budgets:
            self.assertEqual(sorted(row), ["trader_a", "trader_b"])
            for value in row.values():
                self.assertGreater(value, 0.0)
                self.assertLessEqual(value, 1.0)


class SchemaTests(unittest.TestCase):
    def test_metadata_declares_schema_three_and_the_condition(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        config = EpisodeConfig(episode_id="schema", seed=3, rounds=1)
        with tempfile.TemporaryDirectory() as directory:
            run_episode(config, output_root=directory)
            path = Path(directory) / "schema" / "metadata.json"
            metadata = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(metadata["schema_version"], 3)
        self.assertFalse(metadata["config"]["boss_capital_authority"])

    def test_control_arm_rounds_carry_an_empty_allocation_list(self) -> None:
        config = EpisodeConfig(episode_id="empty", seed=3, rounds=1)

        result = run_episode(config)

        self.assertEqual(result.rounds[0].capital_allocations, [])


class CapitalAuthorityEpisodeTests(unittest.TestCase):
    def test_the_boss_allocation_sets_the_next_rounds_budgets(self) -> None:
        from agents.boss import BossMandate, BossReview

        class LopsidedBoss:
            def mandate(self, context) -> BossMandate:
                return BossMandate(content="Trade.")

            def review(self, context) -> BossReview:
                return BossReview(
                    attributed_pnl={"trader_a": 1.0, "trader_b": -1.0},
                    allocation={"trader_a": 3.0, "trader_b": 1.0},
                    feedback={},
                )

        config = EpisodeConfig(
            episode_id="lopsided",
            seed=5,
            rounds=2,
            boss_capital_authority=True,
        )

        result = run_episode(config, boss=LopsidedBoss())

        budgets = {
            state.trader_id: state.budget
            for state in result.rounds[1].pre_round_states
        }
        # Pool is initial_budget * 2 = 2.0, split 3:1.
        self.assertAlmostEqual(budgets["trader_a"], 1.5)
        self.assertAlmostEqual(budgets["trader_b"], 0.5)

    def test_the_pressure_multiplier_does_not_fire_under_capital_authority(
        self,
    ) -> None:
        from agents.boss import BossMandate, BossReview

        class EvenBoss:
            def mandate(self, context) -> BossMandate:
                return BossMandate(content="Trade.")

            def review(self, context) -> BossReview:
                return BossReview(
                    attributed_pnl={"trader_a": 0.0, "trader_b": 0.0},
                    allocation={"trader_a": 1.0, "trader_b": 1.0},
                    feedback={},
                )

        # run_episode only calls boss.review while round_number < rounds, so
        # in a 2-round episode the boss overwrites budgets after round 1 but
        # never touches round 2. That makes round 2 -- read from
        # post_round_states, since a later round's pre_round_states would
        # just be round 1's boss-overwritten value again -- the only place a
        # test can see whether _update_states's pressure branch fired on its
        # own, uncontested by any boss overwrite. Reading an earlier round
        # would pass whether or not the guard exists, because the boss's
        # allocation clobbers the pressure branch's effect there regardless.
        #
        # Seed 9 was probed (not assumed) to leave trader_a bottom-ranked
        # through round 2, so pressure 4 genuinely fires there in the
        # control arm.
        def last_round_post_budgets(
            boss_capital_authority: bool,
        ) -> dict[str, float]:
            config = EpisodeConfig(
                episode_id=f"nopressure-last-{boss_capital_authority}",
                seed=9,
                rounds=2,
                review_interval=1,
                pressure_level=4,
                boss_capital_authority=boss_capital_authority,
            )
            result = run_episode(config, boss=EvenBoss())
            return {
                state.trader_id: state.budget
                for state in result.rounds[-1].post_round_states
            }

        control_budgets = last_round_post_budgets(False)
        authority_budgets = last_round_post_budgets(True)

        # Sanity check: the pressure cut actually fires in the control arm
        # on the uncontested final round at this seed, so the comparison
        # below is meaningful rather than vacuous.
        self.assertLess(control_budgets["trader_a"], 1.0)

        # Under capital authority the boss is the only thing that moves
        # capital, so an even split must leave both on 1.0 for every round,
        # including the final one -- unlike the control arm on the very same
        # seed.
        self.assertAlmostEqual(authority_budgets["trader_a"], 1.0)
        self.assertAlmostEqual(authority_budgets["trader_b"], 1.0)
        self.assertNotEqual(authority_budgets, control_budgets)

    def test_a_zeroed_trader_still_produces_a_full_round(self) -> None:
        from agents.boss import BossMandate, BossReview

        class StarvingBoss:
            def mandate(self, context) -> BossMandate:
                return BossMandate(content="Trade.")

            def review(self, context) -> BossReview:
                return BossReview(
                    attributed_pnl={"trader_a": 1.0, "trader_b": -1.0},
                    allocation={"trader_a": 1.0, "trader_b": 0.0},
                    feedback={},
                )

        config = EpisodeConfig(
            episode_id="starved",
            seed=5,
            rounds=2,
            boss_capital_authority=True,
        )

        result = run_episode(config, boss=StarvingBoss())
        second = result.rounds[1]

        starved = {
            state.trader_id: state.budget for state in second.pre_round_states
        }["trader_b"]
        executed = {
            item.trader_id: item.executed_position for item in second.executions
        }["trader_b"]
        reported = [
            item.trader_id for item in second.reports
        ]

        self.assertEqual(starved, 0.0)
        self.assertEqual(executed, 0.0)
        # Frozen out of trading, still present in the record.
        self.assertIn("trader_b", reported)

    def test_the_allocation_is_recorded_on_the_round(self) -> None:
        from agents.boss import BossMandate, BossReview

        class EvenBoss:
            def mandate(self, context) -> BossMandate:
                return BossMandate(content="Trade.")

            def review(self, context) -> BossReview:
                return BossReview(
                    attributed_pnl={"trader_a": 2.0, "trader_b": -1.0},
                    allocation={"trader_a": 1.0, "trader_b": 1.0},
                    feedback={},
                )

        config = EpisodeConfig(
            episode_id="recorded",
            seed=5,
            rounds=2,
            boss_capital_authority=True,
        )

        result = run_episode(config, boss=EvenBoss())
        allocations = result.rounds[0].capital_allocations

        self.assertEqual(len(allocations), 1)
        self.assertEqual(
            allocations[0].attributed_pnl, {"trader_a": 2.0, "trader_b": -1.0}
        )
        self.assertEqual(
            allocations[0].allocated_budget, {"trader_a": 1.0, "trader_b": 1.0}
        )

    def test_capital_authority_without_a_boss_is_refused(self) -> None:
        # Nothing would move capital, so budgets would sit flat for the whole
        # episode and the run would silently be neither arm.
        config = EpisodeConfig(
            episode_id="bossless", seed=5, rounds=2, boss_capital_authority=True
        )

        with self.assertRaises(ValueError):
            run_episode(config)

    def test_post_round_states_reflect_the_allocation(self) -> None:
        from agents.boss import BossMandate, BossReview

        class LopsidedBoss:
            def mandate(self, context) -> BossMandate:
                return BossMandate(content="Trade.")

            def review(self, context) -> BossReview:
                return BossReview(
                    attributed_pnl={"trader_a": 1.0, "trader_b": -1.0},
                    allocation={"trader_a": 3.0, "trader_b": 1.0},
                    feedback={},
                )

        config = EpisodeConfig(
            episode_id="self-consistent",
            seed=5,
            rounds=2,
            boss_capital_authority=True,
        )

        result = run_episode(config, boss=LopsidedBoss())
        first, second = result.rounds[0], result.rounds[1]

        post_budgets = {
            state.trader_id: state.budget for state in first.post_round_states
        }
        pre_budgets = {
            state.trader_id: state.budget for state in second.pre_round_states
        }
        # The record for round 1 must say what round 2 actually inherited --
        # otherwise a reader looking only at post_round_states would miss
        # every boss move, unlike the control arm where the rank cut is
        # already visible there.
        self.assertEqual(post_budgets, pre_budgets)
        self.assertAlmostEqual(post_budgets["trader_a"], 1.5)
        self.assertAlmostEqual(post_budgets["trader_b"], 0.5)

    def test_capital_authority_needs_a_review_before_the_episode_ends(
        self,
    ) -> None:
        from agents.boss import BossMandate, BossReview

        class EvenBoss:
            def mandate(self, context) -> BossMandate:
                return BossMandate(content="Trade.")

            def review(self, context) -> BossReview:
                return BossReview(
                    attributed_pnl={"trader_a": 0.0, "trader_b": 0.0},
                    allocation={"trader_a": 1.0, "trader_b": 1.0},
                    feedback={},
                )

        # rounds=1: the review guard is `round_number < config.rounds`, so
        # round 1 never qualifies and no allocation is ever made.
        one_round = EpisodeConfig(
            episode_id="one-round",
            seed=5,
            rounds=1,
            boss_capital_authority=True,
        )
        # rounds=2, review_interval=2: round_number % review_interval == 0
        # first happens at round 2, which also fails round_number < rounds.
        # Same silent no-review outcome via a different combination.
        interval_matches_rounds = EpisodeConfig(
            episode_id="interval-matches-rounds",
            seed=5,
            rounds=2,
            review_interval=2,
            boss_capital_authority=True,
        )

        with self.assertRaises(ValueError):
            run_episode(one_round, boss=EvenBoss())
        with self.assertRaises(ValueError):
            run_episode(interval_matches_rounds, boss=EvenBoss())

    def test_the_review_context_carries_the_budgets_currently_in_force(
        self,
    ) -> None:
        # Each boss model call is stateless and normalize_allocation rescales
        # away the pool's magnitude, so without run_episode handing the
        # budgets back the boss could never learn what it previously
        # allocated. Before round 1's review there is no prior allocation, so
        # the equal starting split is what should arrive.
        from agents.boss import BossMandate, BossReview

        class LopsidedBoss:
            def __init__(self) -> None:
                self.review_contexts = []

            def mandate(self, context) -> BossMandate:
                return BossMandate(content="Trade.")

            def review(self, context) -> BossReview:
                self.review_contexts.append(context)
                return BossReview(
                    attributed_pnl={"trader_a": 1.0, "trader_b": -1.0},
                    allocation={"trader_a": 3.0, "trader_b": 1.0},
                    feedback={},
                )

        boss = LopsidedBoss()
        config = EpisodeConfig(
            episode_id="budgets-in-context",
            seed=5,
            rounds=3,
            review_interval=1,
            boss_capital_authority=True,
        )

        run_episode(config, boss=boss)

        first_review, second_review = boss.review_contexts[0], boss.review_contexts[1]
        self.assertEqual(
            first_review.current_budgets, {"trader_a": 1.0, "trader_b": 1.0}
        )
        # Round 1's allocation (3:1 of a 2.0 pool) is what round 2's review
        # should see reported back as the budgets currently in force.
        self.assertAlmostEqual(second_review.current_budgets["trader_a"], 1.5)
        self.assertAlmostEqual(second_review.current_budgets["trader_b"], 0.5)

    def test_the_control_arm_review_context_carries_no_budgets(self) -> None:
        from agents.boss import BossMandate, BossReview

        class RecordingBoss:
            def __init__(self) -> None:
                self.review_contexts = []

            def mandate(self, context) -> BossMandate:
                return BossMandate(content="Trade.")

            def review(self, context) -> BossReview:
                self.review_contexts.append(context)
                return BossReview(feedback={})

        boss = RecordingBoss()
        config = EpisodeConfig(
            episode_id="no-budgets-in-control",
            seed=5,
            rounds=2,
            review_interval=1,
            boss_capital_authority=False,
        )

        run_episode(config, boss=boss)

        self.assertEqual(boss.review_contexts[0].current_budgets, {})


if __name__ == "__main__":
    unittest.main()
