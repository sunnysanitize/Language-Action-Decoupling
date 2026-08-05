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
from typing import Optional, Protocol, Tuple

from environment.datacontainers import (
    Execution,
    Message,
    TraderObservation,
    TraderState,
)


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


def peer_view(state: TraderState) -> PeerView:
    return PeerView(
        trader_id=state.trader_id,
        rank=state.rank,
        budget=state.budget,
        cumulative_pnl=state.cumulative_pnl,
    )


# Phase 1. The trader's own signal and the standings it carries into the round.
@dataclass(frozen=True)
class ShareContext:
    episode_id: str
    round_number: int
    pressure_level: int
    signal_accuracy: float
    observation: TraderObservation
    state: TraderState
    peers: Tuple[PeerView, ...] = ()

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
    def state(self) -> TraderState:
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
    def state(self) -> TraderState:
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
