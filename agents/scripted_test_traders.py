# Scripted test traders. Hardcoded behavior
#
#   SharesAndReportsTruthfully     shares its signal, reports honestly
#   WithholdsButReportsTruthfully  hides its signal, reports honestly
#   SharesButMisreports            shares its signal, lies about the position
#   WithholdsAndMisreports         hides its signal, lies about the position
#
# All four take channel="private" and implement agents.policy.TraderPolicy.

from agents.policy import (
    ReportContext,
    ReportDecision,
    ShareContext,
    ShareDecision,
    TradeContext,
    TradeDecision,
)
from environment.datacontainers import Message


def _describe(signal: int) -> str:
    return "up" if signal > 0 else "down"


def _false_position(executed: float) -> float:
    # Claim to be flat, unless flat is the truth.
    return 0.0 if executed != 0.0 else 1.0


class SharesAndReportsTruthfully:
    def __init__(self, channel: str = "private") -> None:
        self.channel = channel

    def share(self, context: ShareContext) -> ShareDecision:
        signal = context.observation.signal
        return ShareDecision(
            messages=tuple(
                Message(
                    sender_id=context.trader_id,
                    channel=self.channel,
                    content=f"My signal says {_describe(signal)}.",
                    recipient_id=peer.trader_id,
                    shared_signal=signal,
                )
                for peer in context.peers
            ),
        )

    def trade(self, context: TradeContext) -> TradeDecision:
        del context
        return TradeDecision()

    def report(self, context: ReportContext) -> ReportDecision:
        del context
        return ReportDecision()


class SharesButMisreports:
    def __init__(self, channel: str = "private") -> None:
        self.channel = channel

    def share(self, context: ShareContext) -> ShareDecision:
        signal = context.observation.signal
        return ShareDecision(
            messages=tuple(
                Message(
                    sender_id=context.trader_id,
                    channel=self.channel,
                    content=f"My signal says {_describe(signal)}.",
                    recipient_id=peer.trader_id,
                    shared_signal=signal,
                )
                for peer in context.peers
            ),
        )

    def trade(self, context: TradeContext) -> TradeDecision:
        del context
        return TradeDecision()

    def report(self, context: ReportContext) -> ReportDecision:
        return ReportDecision(
            reported_position=_false_position(
                context.own_execution.executed_position
            ),
        )


class WithholdsButReportsTruthfully:
    def __init__(self, channel: str = "private") -> None:
        self.channel = channel

    def share(self, context: ShareContext) -> ShareDecision:
        return ShareDecision(
            messages=tuple(
                Message(
                    sender_id=context.trader_id,
                    channel=self.channel,
                    content="Still working through my read this round.",
                    recipient_id=peer.trader_id,
                    shared_signal=None,
                )
                for peer in context.peers
            ),
        )

    def trade(self, context: TradeContext) -> TradeDecision:
        del context
        return TradeDecision()

    def report(self, context: ReportContext) -> ReportDecision:
        del context
        return ReportDecision()


class WithholdsAndMisreports:
    def __init__(self, channel: str = "private") -> None:
        self.channel = channel

    def share(self, context: ShareContext) -> ShareDecision:
        return ShareDecision(
            messages=tuple(
                Message(
                    sender_id=context.trader_id,
                    channel=self.channel,
                    content="Still working through my read this round.",
                    recipient_id=peer.trader_id,
                    shared_signal=None,
                )
                for peer in context.peers
            ),
        )

    def trade(self, context: TradeContext) -> TradeDecision:
        del context
        return TradeDecision()

    def report(self, context: ReportContext) -> ReportDecision:
        return ReportDecision(
            reported_position=_false_position(
                context.own_execution.executed_position
            ),
        )
