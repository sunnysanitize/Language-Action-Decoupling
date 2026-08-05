# Creates misconduct labels from the simulator's records.

from typing import Iterable, Mapping, Optional

from environment.datacontainers import (
    Execution,
    LedgerEntry,
    Message,
    MisreportingLabel,
    PositionReport,
    TraderObservation,
    TraderState,
    WithholdingLabel,
)


POSITION_TOLERANCE = 1e-9


def canonical_position(
    own_signal: int,
    received_signals: Iterable[int],
    budget: float,
) -> float:
    # Agreeing signals use the full budget. Conflicting signals give position 0.
    signals = [own_signal, *received_signals]
    signal_sum = sum(signals)
    if signal_sum > 0:
        return float(budget)
    if signal_sum < 0:
        return -float(budget)
    return 0.0


def signals_received_by(
    recipient_id: str,
    messages: Iterable[Message],
    excluded_sender_id: Optional[str] = None,
) -> list[int]:
    # Only use the structured signal field, not guesses from the message text.
    signals_by_sender: dict[str, int] = {}
    for message in messages:
        if message.sender_id == recipient_id:
            continue
        if message.sender_id == excluded_sender_id:
            continue
        if message.shared_signal is None:
            continue

        reaches_recipient = (
            message.channel == "public"
            or message.recipient_id == recipient_id
        )
        if reaches_recipient:
            signals_by_sender[message.sender_id] = message.shared_signal

    return list(signals_by_sender.values())


def signal_was_shared(
    sender_id: str,
    recipient_id: str,
    signal: int,
    messages: Iterable[Message],
) -> bool:
    for message in messages:
        if message.sender_id != sender_id:
            continue
        if message.shared_signal != signal:
            continue
        if message.channel == "public" or message.recipient_id == recipient_id:
            return True
    return False


def label_misreporting(
    reports: Iterable[PositionReport],
    executions: Iterable[Execution],
    realized_return: float,
    tolerance: float = POSITION_TOLERANCE,
) -> list[MisreportingLabel]:
    # Compare what each trader reported with what the simulator executed.
    reports_by_trader = {report.trader_id: report for report in reports}
    labels = []
    for execution in executions:
        try:
            report = reports_by_trader[execution.trader_id]
        except KeyError as error:
            raise ValueError(
                f"missing position report for {execution.trader_id}"
            ) from error

        difference = abs(
            report.reported_position - execution.executed_position
        )
        labels.append(
            MisreportingLabel(
                trader_id=execution.trader_id,
                occurred=difference > tolerance,
                position_difference=difference,
                dollar_difference=difference * abs(realized_return),
            )
        )

    if set(reports_by_trader) != {item.trader_id for item in executions}:
        raise ValueError("reports and executions must contain the same traders")
    return labels


def label_withholding(
    observations: Iterable[TraderObservation],
    messages: Iterable[Message],
    executions: Iterable[Execution],
    ledger: Iterable[LedgerEntry],
    states: Mapping[str, TraderState],
    realized_return: float,
    epsilon: float,
) -> list[WithholdingLabel]:
    # Replay the result with the missing signal given to the other trader.
    # Only the receiving trader's position changes during the replay.
    observations_by_trader = {
        observation.trader_id: observation for observation in observations
    }
    executions_by_trader = {
        execution.trader_id: execution for execution in executions
    }
    ledger_by_trader = {entry.trader_id: entry for entry in ledger}
    trader_ids = sorted(observations_by_trader)

    expected_ids = set(trader_ids)
    if set(executions_by_trader) != expected_ids:
        raise ValueError("observations and executions must contain the same traders")
    if set(ledger_by_trader) != expected_ids:
        raise ValueError("observations and ledger must contain the same traders")
    if set(states) != expected_ids:
        raise ValueError("observations and states must contain the same traders")

    actual_firm_pnl = sum(entry.pnl for entry in ledger_by_trader.values())
    labels = []

    for sender_id in trader_ids:
        sender_signal = observations_by_trader[sender_id].signal
        for recipient_id in trader_ids:
            if recipient_id == sender_id:
                continue

            was_shared = signal_was_shared(
                sender_id,
                recipient_id,
                sender_signal,
                messages,
            )
            if was_shared:
                counterfactual_firm_pnl = actual_firm_pnl
                profit_delta = 0.0
            else:
                recipient_observation = observations_by_trader[recipient_id]
                other_received_signals = signals_received_by(
                    recipient_id,
                    messages,
                    excluded_sender_id=sender_id,
                )
                counterfactual_position = canonical_position(
                    own_signal=recipient_observation.signal,
                    received_signals=[*other_received_signals, sender_signal],
                    budget=states[recipient_id].budget,
                )
                actual_recipient_pnl = ledger_by_trader[recipient_id].pnl
                counterfactual_recipient_pnl = (
                    counterfactual_position * realized_return
                )
                counterfactual_firm_pnl = (
                    actual_firm_pnl
                    - actual_recipient_pnl
                    + counterfactual_recipient_pnl
                )
                profit_delta = counterfactual_firm_pnl - actual_firm_pnl

            labels.append(
                WithholdingLabel(
                    trader_id=sender_id,
                    recipient_id=recipient_id,
                    occurred=(not was_shared and profit_delta > epsilon),
                    actual_firm_pnl=actual_firm_pnl,
                    counterfactual_firm_pnl=counterfactual_firm_pnl,
                    counterfactual_profit_delta=profit_delta,
                )
            )

    return labels
