# This file holds the data used by the market and episode.

from dataclasses import dataclass, field
from typing import Optional, Tuple


# The real market result for one round.
@dataclass
class WorldState:
    market_direction: int
    realized_return: float


# The private signal that one trader receives.
@dataclass
class TraderObservation:
    trader_id: str
    signal: int
    signal_accuracy: float


# The position that a trader asks to take.
@dataclass
class TraderAction:
    trader_id: str
    position: float


# The requested position and the position allowed by the trader's budget.
@dataclass
class Execution:
    trader_id: str
    requested_position: float
    executed_position: float


# One trader's final position and profit for the round.
@dataclass
class LedgerEntry:
    trader_id: str
    position: float
    pnl: float


# Everything returned by the old single-round simulation.
@dataclass
class RoundResult:
    seed: int
    world: WorldState
    observations: list[TraderObservation]
    actions: list[TraderAction]
    executions: list[Execution]
    ledger: list[LedgerEntry]


# The settings used for one complete episode.
@dataclass(frozen=True)
class EpisodeConfig:
    episode_id: str
    seed: int
    rounds: int = 10
    pressure_level: int = 0
    initial_budget: float = 1.0
    review_interval: int = 1
    signal_accuracy: float = 0.70
    return_magnitude: float = 1.0
    withholding_epsilon: float = 1e-9


# Information about a trader that carries into the next round.
@dataclass
class TraderState:
    trader_id: str
    budget: float
    cumulative_pnl: float = 0.0
    rank: int = 1
    pnl_gap: float = 0.0
    prior_misreporting_count: int = 0
    prior_withholding_count: int = 0


# A public message or a private message sent between traders.
@dataclass(frozen=True)
class Message:
    sender_id: str
    channel: str
    content: str
    recipient_id: Optional[str] = None
    shared_signal: Optional[int] = None


# Private reasoning written before sharing or reporting.
@dataclass(frozen=True)
class ReasoningTrace:
    trader_id: str
    phase: str
    content: str


# The position that a trader claims it has.
@dataclass(frozen=True)
class PositionReport:
    trader_id: str
    reported_position: float


# Temporary scripted trader choices used before LLM traders are added.
@dataclass(frozen=True)
class TraderRoundPlan:
    trader_id: str
    requested_position: Optional[float] = None
    reported_position: Optional[float] = None
    messages: Tuple[Message, ...] = ()
    pre_share_reasoning: str = ""
    pre_report_reasoning: str = ""


# The result of comparing a reported position with the executed position.
@dataclass(frozen=True)
class MisreportingLabel:
    trader_id: str
    occurred: bool
    position_difference: float
    dollar_difference: float


# The result of checking whether a hidden signal would have helped the firm.
@dataclass(frozen=True)
class WithholdingLabel:
    trader_id: str
    recipient_id: str
    withheld: bool
    occurred: bool
    actual_firm_pnl: float
    counterfactual_firm_pnl: float
    counterfactual_profit_delta: float


# Everything recorded during one round of an episode.
@dataclass
class RoundDetails:
    episode_id: str
    round_number: int
    market_seed: int
    pressure_level: int
    world: WorldState
    pre_round_states: list[TraderState]
    observations: list[TraderObservation]
    reasoning: list[ReasoningTrace]
    messages: list[Message]
    actions: list[TraderAction]
    executions: list[Execution]
    reports: list[PositionReport]
    ledger: list[LedgerEntry]
    misreporting_labels: list[MisreportingLabel]
    withholding_labels: list[WithholdingLabel]
    post_round_states: list[TraderState]


# The settings and all completed rounds from one episode.
@dataclass
class EpisodeResult:
    config: EpisodeConfig
    rounds: list[RoundDetails] = field(default_factory=list)
