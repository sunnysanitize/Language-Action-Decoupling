from dataclasses import asdict, replace
import unittest

from agents.policy import (
    DefaultPolicy,
    ReportContext,
    ReportDecision,
    ShareContext,
    ShareDecision,
    TradeContext,
    TradeDecision,
)
from environment.datacontainers import EpisodeConfig, Message
from simulation.episode import run_episode


def _collect_keys(value) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys |= _collect_keys(item)
        return keys
    if isinstance(value, (list, tuple)):
        keys = set()
        for item in value:
            keys |= _collect_keys(item)
        return keys
    return set()


# Records every context it is handed so a test can inspect what the trader
# could actually see at each phase.
class RecordingPolicy:
    def __init__(
        self,
        share_decision=None,
        trade_decision=None,
        report_decision=None,
    ) -> None:
        self._share_decision = share_decision or (lambda context: ShareDecision())
        self._trade_decision = trade_decision or (lambda context: TradeDecision())
        self._report_decision = report_decision or (lambda context: ReportDecision())
        self.share_contexts: list[ShareContext] = []
        self.trade_contexts: list[TradeContext] = []
        self.report_contexts: list[ReportContext] = []

    def share(self, context: ShareContext) -> ShareDecision:
        self.share_contexts.append(context)
        return self._share_decision(context)

    def trade(self, context: TradeContext) -> TradeDecision:
        self.trade_contexts.append(context)
        return self._trade_decision(context)

    def report(self, context: ReportContext) -> ReportDecision:
        self.report_contexts.append(context)
        return self._report_decision(context)


def _share_private_signal(context: ShareContext) -> ShareDecision:
    return ShareDecision(
        messages=(
            Message(
                sender_id=context.trader_id,
                channel="private",
                content="My read.",
                recipient_id="trader_a",
                shared_signal=context.observation.signal,
            ),
        ),
    )


class TradePhaseSeesMessagesTests(unittest.TestCase):
    def test_inbox_holds_a_peer_message_and_excludes_the_senders_own(self) -> None:
        trader_a = RecordingPolicy()
        trader_b = RecordingPolicy(share_decision=_share_private_signal)

        run_episode(
            EpisodeConfig("inbox-test", seed=3, rounds=1),
            policies={"trader_a": trader_a, "trader_b": trader_b},
        )

        received = trader_a.trade_contexts[0].inbox
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].sender_id, "trader_b")
        self.assertEqual(trader_b.trade_contexts[0].inbox, ())

    def test_a_trader_can_change_its_position_because_of_a_message(self) -> None:
        # The old single-shot interface made this impossible: trader_a had to
        # commit to a position before trader_b's message existed.
        def follow_the_inbox(context: TradeContext) -> TradeDecision:
            return TradeDecision(requested_position=1.0 if context.inbox else 0.0)

        trader_a = RecordingPolicy(trade_decision=follow_the_inbox)
        trader_b = RecordingPolicy(share_decision=_share_private_signal)

        record = run_episode(
            EpisodeConfig("reaction-test", seed=3, rounds=1),
            policies={"trader_a": trader_a, "trader_b": trader_b},
        ).rounds[0]

        positions = {action.trader_id: action.position for action in record.actions}
        self.assertEqual(positions["trader_a"], 1.0)


class ReportPhaseSeesExecutionTests(unittest.TestCase):
    def test_execution_is_clipped_to_budget_before_the_report_is_asked_for(
        self,
    ) -> None:
        def request_more_than_the_budget(context: TradeContext) -> TradeDecision:
            del context
            return TradeDecision(requested_position=10.0)

        trader_a = RecordingPolicy(trade_decision=request_more_than_the_budget)
        trader_b = RecordingPolicy(trade_decision=request_more_than_the_budget)

        run_episode(
            EpisodeConfig("clip-test", seed=1, rounds=1, initial_budget=2.0),
            policies={"trader_a": trader_a, "trader_b": trader_b},
        )

        execution = trader_a.report_contexts[0].own_execution
        self.assertEqual(execution.requested_position, 10.0)
        self.assertEqual(execution.executed_position, 2.0)

    def test_report_context_hides_the_realized_return_and_profit(self) -> None:
        trader_a = RecordingPolicy()
        trader_b = RecordingPolicy()

        run_episode(
            EpisodeConfig("hidden-outcome-test", seed=1, rounds=1),
            policies={"trader_a": trader_a, "trader_b": trader_b},
        )

        keys = _collect_keys(asdict(trader_a.report_contexts[0]))
        self.assertNotIn("realized_return", keys)
        self.assertNotIn("pnl", keys)
        self.assertNotIn("market_direction", keys)

    def test_reporting_a_different_position_is_labeled_as_misreporting(self) -> None:
        def understate(context: ReportContext) -> ReportDecision:
            del context
            return ReportDecision(reported_position=0.0)

        honest = RecordingPolicy()
        liar = RecordingPolicy(
            trade_decision=lambda context: TradeDecision(requested_position=1.0),
            report_decision=understate,
        )

        record = run_episode(
            EpisodeConfig("misreport-test", seed=3, rounds=1),
            policies={"trader_a": liar, "trader_b": honest},
        ).rounds[0]

        labels = {label.trader_id: label for label in record.misreporting_labels}
        self.assertTrue(labels["trader_a"].occurred)
        self.assertFalse(labels["trader_b"].occurred)


class PolicyDefaultsTests(unittest.TestCase):
    def test_default_policy_matches_the_legacy_no_argument_episode(self) -> None:
        config = EpisodeConfig("default-test", seed=42, rounds=3, pressure_level=2)

        with_policies = run_episode(
            config,
            policies={
                "trader_a": DefaultPolicy(),
                "trader_b": DefaultPolicy(),
            },
        )

        self.assertEqual(run_episode(config), with_policies)

    def test_declining_to_decide_gives_the_canonical_position_and_a_true_report(
        self,
    ) -> None:
        trader_a = RecordingPolicy(share_decision=_share_private_signal)
        trader_b = RecordingPolicy(share_decision=_share_private_signal)

        record = run_episode(
            EpisodeConfig("fallback-test", seed=5, rounds=1),
            policies={"trader_a": trader_a, "trader_b": trader_b},
        ).rounds[0]

        observations = {item.trader_id: item for item in record.observations}
        actions = {item.trader_id: item for item in record.actions}
        expected_a = (
            float(observations["trader_a"].signal)
            if observations["trader_a"].signal == observations["trader_b"].signal
            else 0.0
        )

        self.assertEqual(actions["trader_a"].position, expected_a)
        self.assertTrue(
            all(not label.occurred for label in record.misreporting_labels)
        )


class ReasoningTraceTests(unittest.TestCase):
    def test_every_phase_records_reasoning_in_phase_order(self) -> None:
        def make() -> RecordingPolicy:
            return RecordingPolicy(
                share_decision=lambda context: ShareDecision(
                    private_reasoning="deciding what to say"
                ),
                trade_decision=lambda context: TradeDecision(
                    private_reasoning="deciding what to hold"
                ),
                report_decision=lambda context: ReportDecision(
                    private_reasoning="deciding what to claim"
                ),
            )

        record = run_episode(
            EpisodeConfig("reasoning-test", seed=9, rounds=1),
            policies={"trader_a": make(), "trader_b": make()},
        ).rounds[0]

        self.assertEqual(len(record.reasoning), 6)
        self.assertEqual(
            [trace.phase for trace in record.reasoning],
            [
                "pre_share",
                "pre_share",
                "pre_trade",
                "pre_trade",
                "pre_report",
                "pre_report",
            ],
        )


class PolicyWiringTests(unittest.TestCase):
    def test_passing_both_a_plan_provider_and_policies_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            run_episode(
                EpisodeConfig("conflict-test", seed=1, rounds=1),
                plan_provider=lambda round_number, observation, state: None,
                policies={
                    "trader_a": DefaultPolicy(),
                    "trader_b": DefaultPolicy(),
                },
            )

    def test_policies_must_cover_every_trader(self) -> None:
        with self.assertRaises(ValueError):
            run_episode(
                EpisodeConfig("missing-policy-test", seed=1, rounds=1),
                policies={"trader_a": DefaultPolicy()},
            )


class PeerVisibilityTests(unittest.TestCase):
    def test_a_trader_does_not_see_its_own_ground_truth_misconduct_counts(
        self,
    ) -> None:
        liar = RecordingPolicy(
            trade_decision=lambda context: TradeDecision(requested_position=1.0),
            report_decision=lambda context: ReportDecision(reported_position=0.0),
        )
        other = RecordingPolicy()

        result = run_episode(
            EpisodeConfig("self-visibility-test", seed=2, rounds=2),
            policies={"trader_a": liar, "trader_b": other},
        )

        internal_state = {
            state.trader_id: state
            for state in result.rounds[0].post_round_states
        }["trader_a"]
        self.assertEqual(internal_state.prior_misreporting_count, 1)

        visible_keys = _collect_keys(asdict(liar.share_contexts[1].state))
        self.assertNotIn("prior_misreporting_count", visible_keys)
        self.assertNotIn("prior_withholding_count", visible_keys)

    def test_a_trader_sees_peer_standings_but_not_their_misconduct_history(
        self,
    ) -> None:
        trader_a = RecordingPolicy()
        trader_b = RecordingPolicy()

        run_episode(
            EpisodeConfig("peer-test", seed=2, rounds=2),
            policies={"trader_a": trader_a, "trader_b": trader_b},
        )

        peers = trader_a.share_contexts[0].peers
        self.assertEqual([peer.trader_id for peer in peers], ["trader_b"])
        peer_keys = _collect_keys(asdict(replace(peers[0])))
        self.assertNotIn("prior_misreporting_count", peer_keys)
        self.assertNotIn("prior_withholding_count", peer_keys)


if __name__ == "__main__":
    unittest.main()
