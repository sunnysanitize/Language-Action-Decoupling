"""Data produced during a market round."""

from dataclasses import dataclass


@dataclass
class WorldState:
    market_direction: int
    realized_return: float


@dataclass
class TraderObservation:
    trader_id: str
    signal: int
    signal_accuracy: float


@dataclass
class TraderAction:
    trader_id: str
    position: int


@dataclass
class Execution:
    trader_id: str
    requested_position: int
    executed_position: int


@dataclass
class LedgerEntry:
    trader_id: str
    position: int
    pnl: float


@dataclass
class RoundResult:
    seed: int
    world: WorldState
    observations: list[TraderObservation]
    actions: list[TraderAction]
    executions: list[Execution]
    ledger: list[LedgerEntry]
