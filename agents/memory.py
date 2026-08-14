# What one trader is allowed to remember from earlier rounds.
#
# An experiment runs many rounds with the same traders, so an LLM trader has to
# act like one trader across the whole episode rather than starting fresh every
# round. The simulator already carries rank, budget, cumulative profit and the
# profit gap forward; this file carries the rest of what the trader itself saw.
#
# The filtering is the point of the module. A RoundDetails record holds every
# trader's private signal, every private message, every scratchpad, and the
# evaluator's misconduct labels. A trader may remember only its own side of a
# completed round, so each rule below drops something the record contains.

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence, Tuple

from agents.policy import PeerView, SelfView, own_record, peer_view, self_view
from environment.datacontainers import Message, RoundDetails
from simulation.labels import message_reaches

if TYPE_CHECKING:
    from agents.boss import BossFeedback


# One completed round as the trader itself experienced it.
#
# There is no private reasoning here, not even the trader's own. Replaying an
# earlier scratchpad invites the model to restate it instead of reasoning
# afresh, and a trace that merely repeats an older one is no longer evidence
# about the decision it accompanies. The same argument already keeps the report
# phase from seeing the trade phase's reasoning in agents/llm_trader.py.
#
# The market outcome is here, and only because the round is finished. Hiding it
# would leave a trader unable to tell a round that went its way from one that
# did not, which is the main thing anyone remembers about a trade.
@dataclass(frozen=True)
class RoundMemory:
    round_number: int
    own_signal: int
    signal_accuracy: float
    messages_sent: Tuple[Message, ...]
    messages_received: Tuple[Message, ...]
    requested_position: float
    executed_position: float
    reported_position: float
    market_direction: int
    realized_return: float
    own_pnl: float
    state_after: SelfView
    peers_after: Tuple[PeerView, ...]
    boss_feedback: Tuple["BossFeedback", ...] = ()


def _round_memory(trader_id: str, record: RoundDetails) -> RoundMemory:
    observation = own_record(record.observations, trader_id, "observation")
    execution = own_record(record.executions, trader_id, "execution")
    report = own_record(record.reports, trader_id, "report")
    entry = own_record(record.ledger, trader_id, "ledger entry")
    state = own_record(record.post_round_states, trader_id, "post-round state")

    return RoundMemory(
        round_number=record.round_number,
        own_signal=observation.signal,
        signal_accuracy=observation.signal_accuracy,
        messages_sent=tuple(
            message
            for message in record.messages
            if message.sender_id == trader_id
        ),
        # The delivery rule lives in simulation.labels and is called here
        # rather than repeated. If memory and the labeller disagreed about
        # what reached a trader, a trader could remember a message the
        # labeller thinks was never sent.
        messages_received=tuple(
            message
            for message in record.messages
            if message_reaches(message, trader_id)
        ),
        requested_position=execution.requested_position,
        executed_position=execution.executed_position,
        reported_position=report.reported_position,
        market_direction=record.world.market_direction,
        realized_return=record.world.realized_return,
        own_pnl=entry.pnl,
        # self_view and peer_view are reused rather than reimplemented, so the
        # misconduct counts on TraderState are dropped by construction. A
        # hand-copied state here would silently regain them the next time
        # TraderState grows a field.
        state_after=self_view(state),
        peers_after=tuple(
            peer_view(other)
            for other in record.post_round_states
            if other.trader_id != trader_id
        ),
        # A desk-wide mandate (trader_id None) reached everyone; per-trader
        # feedback reached only its addressee.
        boss_feedback=tuple(
            item
            for item in record.delivered_feedback
            if item.trader_id in (None, trader_id)
        ),
    )


# Every completed round from this trader's point of view, oldest first.
def trader_memory(
    trader_id: str,
    rounds: Sequence[RoundDetails],
) -> Tuple[RoundMemory, ...]:
    return tuple(_round_memory(trader_id, record) for record in rounds)
