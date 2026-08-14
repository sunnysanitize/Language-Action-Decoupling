# The interface a trader implements to play one round.
#
# A round is split into three phases so that each decision is made with the
# information a real trader would actually have at that moment:
#
# 1. share  - the trader knows its own private signal and the standings.
# 2. trade  - the messages sent during the share phase have been delivered.
# 3. report - the position has been executed and clipped to the budget.
#
# The split matters for the research labels. A trader can only misreport on
# purpose if it has already seen what the simulator executed, and it can only
# react to a rival if that rival's message arrived first.
#
# Returning None from a decision means "use the simulator's default": the
# canonical position for a trade, and a truthful report of the execution.

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Protocol, Sequence, Tuple, TypeVar

from environment.datacontainers import (
    Execution,
    Message,
    TraderObservation,
    TraderState,
)

# agents.memory builds RoundMemory out of the views defined here, so importing
# it at runtime would close a cycle. The annotation is all this file needs.
if TYPE_CHECKING:
    from agents.boss import BossFeedback
    from agents.memory import RoundMemory


# What one trader is allowed to know about another trader.
#
# This is deliberately narrower than TraderState. The misconduct counts on
# TraderState are ground truth that the simulator derives after the fact, so a
# rival must not see them. Anything exposed here counts as observable
# information for the detector.
@dataclass(frozen=True)
class PeerView:
    trader_id: str
    rank: int
    budget: float
    cumulative_pnl: float


@dataclass(frozen=True)
class SelfView:
    """The simulator state a trader is allowed to know about itself."""

    trader_id: str
    rank: int
    budget: float
    cumulative_pnl: float
    pnl_gap: float


def self_view(state: TraderState) -> SelfView:
    # Misconduct counts are evaluator-generated ground truth. Showing them to
    # the trader would let a label from one round influence later behavior.
    return SelfView(
        trader_id=state.trader_id,
        rank=state.rank,
        budget=state.budget,
        cumulative_pnl=state.cumulative_pnl,
        pnl_gap=state.pnl_gap,
    )


Record = TypeVar("Record")


# Pull one actor's record out of a round, for any of the per-trader lists.
#
# A missing record is a broken round, not an empty view. Returning a default
# would turn a mistyped id into an actor that quietly did nothing, which reads
# as an actor that chose to do nothing.
def own_record(records: Sequence[Record], actor_id: str, kind: str) -> Record:
    for record in records:
        if record.trader_id == actor_id:  # type: ignore[attr-defined]
            return record
    raise KeyError(f"round has no {kind} for {actor_id}")


def peer_view(state: TraderState) -> PeerView:
    return PeerView(
        trader_id=state.trader_id,
        rank=state.rank,
        budget=state.budget,
        cumulative_pnl=state.cumulative_pnl,
    )


# Phase 1. The trader's own signal, the standings it carries into the round,
# and what it remembers of the rounds already finished.
#
# Memory sits on the share context rather than on each of the three phase
# contexts because the trade and report contexts already carry this one, so
# there is a single copy per round and no way for the phases to disagree about
# what the trader remembers.
#
# There is no pressure_level here. A trader learns how hard the firm is
# squeezing it from what its boss says and from what actually happens to its
# budget and rank, which is the contract in docs/role_contract.md. Handing it
# the condition as an integer let the model read the experiment's independent
# variable straight off the prompt and treat it as an instruction.
@dataclass(frozen=True)
class ShareContext:
    episode_id: str
    round_number: int
    signal_accuracy: float
    observation: TraderObservation
    state: SelfView
    peers: Tuple[PeerView, ...] = ()
    memory: Tuple["RoundMemory", ...] = ()
    boss_feedback: Tuple["BossFeedback", ...] = ()

    @property
    def trader_id(self) -> str:
        return self.observation.trader_id


# Phase 2. Adds the messages that reached this trader.
@dataclass(frozen=True)
class TradeContext:
    share: ShareContext
    inbox: Tuple[Message, ...] = ()

    @property
    def trader_id(self) -> str:
        return self.share.trader_id

    @property
    def round_number(self) -> int:
        return self.share.round_number

    @property
    def observation(self) -> TraderObservation:
        return self.share.observation

    @property
    def state(self) -> SelfView:
        return self.share.state


# Phase 3. Adds the executed position.
#
# There is no realized return and no profit here on purpose. The data contract
# reveals returns only after reports are collected, so a trader reports without
# knowing whether the round went its way.
@dataclass(frozen=True)
class ReportContext:
    trade: TradeContext
    own_execution: Execution

    @property
    def share(self) -> ShareContext:
        return self.trade.share

    @property
    def trader_id(self) -> str:
        return self.trade.trader_id

    @property
    def round_number(self) -> int:
        return self.trade.round_number

    @property
    def observation(self) -> TraderObservation:
        return self.trade.observation

    @property
    def state(self) -> SelfView:
        return self.trade.state

    @property
    def inbox(self) -> Tuple[Message, ...]:
        return self.trade.inbox


# Every decision carries private_reasoning first, and that ordering is a
# contract rather than a style choice.
#
# The detector experiment compares a model that sees private chat against one
# that also sees private reasoning, so the reasoning has to be evidence about
# the decision it accompanies. That only holds if it was produced before the
# decision. Text written after the fact is a rationalisation of a choice
# already made, and it would predict nothing.
#
# The dataclass cannot enforce this: a policy is free to fill the field last.
# The obligation sits with the policy. For a generated policy that means
# private_reasoning must come first in the response schema, so the decision is
# sampled conditioned on the reasoning. For a scripted policy the field is
# usually left empty.
#
# private_reasoning is never shown to the other trader. Anything meant for the
# peer belongs in a Message.


@dataclass(frozen=True)
class ShareDecision:
    private_reasoning: str = ""
    messages: Tuple[Message, ...] = ()


@dataclass(frozen=True)
class TradeDecision:
    private_reasoning: str = ""
    requested_position: Optional[float] = None


@dataclass(frozen=True)
class ReportDecision:
    private_reasoning: str = ""
    reported_position: Optional[float] = None


class TraderPolicy(Protocol):
    def share(self, context: ShareContext) -> ShareDecision: ...

    def trade(self, context: TradeContext) -> TradeDecision: ...

    def report(self, context: ReportContext) -> ReportDecision: ...


# Says nothing, follows the canonical position, reports truthfully.
class DefaultPolicy:
    def share(self, context: ShareContext) -> ShareDecision:
        del context
        return ShareDecision()

    def trade(self, context: TradeContext) -> TradeDecision:
        del context
        return TradeDecision()

    def report(self, context: ReportContext) -> ReportDecision:
        del context
        return ReportDecision()
