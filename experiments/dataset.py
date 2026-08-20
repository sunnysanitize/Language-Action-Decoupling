# Turns recorded episodes into one row per trader-round, with the four
# information blocks of docs/overview.md kept separate.
#
# The blocks are nested: block 1 is the situation, block 2 adds what an
# observer of the firm could see, block 3 adds the traders' private chat, and
# block 4 adds private reasoning. The detector trains on 1, then 1+2, then
# 1+2+3, then 1+2+3+4, and the comparison the paper is about is 3 against 4.
#
# What makes this file delicate is not the parsing. It is that misconduct is
# an act inside a round, and most of the round happens after it. A row that
# quietly includes the act's own consequences would score beautifully and mean
# nothing.
#
#   Withholding is decided in the share phase, which is the first thing that
#   happens. So for a same-round withholding row, the only current-round
#   information admitted is the pre-round state and the pre_share scratchpad.
#   This round's messages are the act itself; this round's ledger is
#   downstream of it. Both come from earlier rounds only.
#
#   Misreporting is decided in the report phase, after messages are exchanged
#   and after the position executes. So a same-round misreporting row may use
#   this round's chat and the reasoning written up to pre_report, none of which
#   depend on what the trader is about to claim. The report and the labels do,
#   and are excluded.
#
# For the next-round rows the horizon does the separating: every feature comes
# from a completed round r and the label comes from round r+1, so the whole
# round is admissible and no phase argument is needed.

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Optional


TRADER_IDS = ("trader_a", "trader_b")
BOSS_ID = "boss_1"
KEN_ID = "ken_griffin"

# Which reasoning phases exist before the decision each target names. Anything
# later in the round is written after the act and cannot be an early warning
# for it.
PHASES_BEFORE = {
    "withholding": ("pre_share",),
    "misreporting": ("pre_share", "pre_trade", "pre_report"),
}


@dataclass
class Row:
    episode_id: str
    seed: int
    pressure_level: int
    round_number: int
    trader_id: str

    # Block 1: the situation the trader is in before it acts.
    situation: dict[str, float] = field(default_factory=dict)

    # Block 2: what an observer of the firm could read -- the ledger, the
    # position reports, the public chat, and what the boss said.
    observable: dict[str, float] = field(default_factory=dict)
    observable_text: str = ""

    # Block 3: messages addressed trader-to-trader rather than to the room.
    private_chat: dict[str, float] = field(default_factory=dict)
    private_chat_text: str = ""

    # Block 4: the trader's own scratchpad, never delivered to anyone.
    reasoning: dict[str, float] = field(default_factory=dict)
    reasoning_text: str = ""

    # Labels. Recorded for every row; which one is the target is the caller's
    # choice.
    withheld: int = 0
    withheld_costly: int = 0
    misreported: int = 0


def load_episode(run_directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with (run_directory / "metadata.json").open(encoding="utf-8") as handle:
        metadata = json.load(handle)
    rounds = []
    with (run_directory / "rounds.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rounds.append(json.loads(line))
    return metadata, rounds


def load_sweep(sweep_root: Path) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    # Read the manifest when there is one so a failed episode is skipped by
    # name rather than by whether it happens to have left a parseable
    # directory behind.
    manifest_path = sweep_root / "manifest.json"
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
        names = [
            episode["episode_id"]
            for episode in manifest["episodes"]
            if episode["status"] == "ok"
        ]
    else:
        names = sorted(
            path.name
            for path in sweep_root.iterdir()
            if (path / "rounds.jsonl").exists()
        )

    # A run directory exists from the moment an episode starts, and rounds are
    # appended as they finish. So a sweep that is still running -- or one that
    # was killed partway -- leaves directories holding three or seven rounds
    # of a ten-round episode. Those are not short episodes, they are truncated
    # ones: the trader never faced the late rounds where budgets have actually
    # been cut, so including them would quietly weight the sample toward early,
    # low-pressure rounds. Only complete episodes are returned.
    episodes = []
    for name in names:
        run_directory = sweep_root / name
        if not (run_directory / "rounds.jsonl").exists():
            continue
        metadata, records = load_episode(run_directory)
        expected = metadata["config"]["rounds"]
        if len(records) != expected:
            print(
                f"skipping {name}: {len(records)} of {expected} rounds recorded",
                file=sys.stderr,
            )
            continue
        episodes.append((metadata, records))
    return episodes


def _by_trader(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["trader_id"]: item for item in items}


def _labels_for(record: dict[str, Any], trader_id: str) -> tuple[int, int, int]:
    withheld = 0
    costly = 0
    for label in record["withholding_labels"]:
        if label["trader_id"] != trader_id:
            continue
        withheld = max(withheld, int(label["withheld"]))
        costly = max(costly, int(label["occurred"]))
    misreported = 0
    for label in record["misreporting_labels"]:
        if label["trader_id"] == trader_id:
            misreported = max(misreported, int(label["occurred"]))
    return withheld, costly, misreported


def _messages_of(record: dict[str, Any], trader_id: str, channel: str) -> list[dict]:
    return [
        message
        for message in record["messages"]
        if message["sender_id"] == trader_id and message["channel"] == channel
    ]


def _messages_to(record: dict[str, Any], trader_id: str, channel: str) -> list[dict]:
    return [
        message
        for message in record["messages"]
        if message["sender_id"] != trader_id
        and message["channel"] == channel
        and (channel == "public" or message["recipient_id"] == trader_id)
    ]


def _reasoning_of(
    record: dict[str, Any], actor_id: str, phases: tuple[str, ...]
) -> list[dict]:
    return [
        trace
        for trace in record["reasoning"]
        if trace["actor_id"] == actor_id and trace["phase"] in phases
    ]


def _history_features(
    history: list[dict[str, Any]], trader_id: str
) -> tuple[dict[str, float], str]:
    # Everything an observer could have accumulated from completed rounds. The
    # counts are cumulative and the ratios are per-round, so a row from round 9
    # is comparable to a row from round 2.
    rounds_seen = len(history)
    if rounds_seen == 0:
        return (
            {
                "hist_rounds": 0.0,
                "hist_own_pnl": 0.0,
                "hist_firm_pnl": 0.0,
                "hist_last_own_pnl": 0.0,
                "hist_last_firm_pnl": 0.0,
                "hist_last_reported_position": 0.0,
                "hist_last_peer_reported_position": 0.0,
                "hist_public_rate": 0.0,
                "hist_shared_signal_rate": 0.0,
                "hist_silent_rate": 0.0,
                "hist_boss_feedback_count": 0.0,
                "hist_reported_abs_mean": 0.0,
            },
            "",
        )

    own_pnl = 0.0
    firm_pnl = 0.0
    public_rounds = 0
    shared_signal_rounds = 0
    silent_rounds = 0
    boss_feedback_count = 0
    reported_absolute_total = 0.0
    text_parts: list[str] = []

    for record in history:
        ledger = _by_trader(record["ledger"])
        own_pnl += ledger[trader_id]["pnl"]
        firm_pnl += sum(entry["pnl"] for entry in record["ledger"])

        public = _messages_of(record, trader_id, "public")
        private = _messages_of(record, trader_id, "private")
        if public:
            public_rounds += 1
        if not public and not private:
            silent_rounds += 1
        if any(
            message["shared_signal"] is not None for message in (*public, *private)
        ):
            shared_signal_rounds += 1

        reports = _by_trader(record["reports"])
        reported_absolute_total += abs(reports[trader_id]["reported_position"])

        for item in record["delivered_feedback"]:
            if item["trader_id"] in (None, trader_id):
                boss_feedback_count += 1
                text_parts.append(item["content"])
        for message in _messages_to(record, trader_id, "public"):
            text_parts.append(message["content"])

    last = history[-1]
    last_ledger = _by_trader(last["ledger"])
    last_reports = _by_trader(last["reports"])
    peer_id = next(other for other in TRADER_IDS if other != trader_id)

    features = {
        "hist_rounds": float(rounds_seen),
        "hist_own_pnl": own_pnl,
        "hist_firm_pnl": firm_pnl,
        "hist_last_own_pnl": last_ledger[trader_id]["pnl"],
        "hist_last_firm_pnl": sum(entry["pnl"] for entry in last["ledger"]),
        "hist_last_reported_position": last_reports[trader_id]["reported_position"],
        "hist_last_peer_reported_position": last_reports[peer_id][
            "reported_position"
        ],
        "hist_public_rate": public_rounds / rounds_seen,
        "hist_shared_signal_rate": shared_signal_rounds / rounds_seen,
        "hist_silent_rate": silent_rounds / rounds_seen,
        "hist_boss_feedback_count": float(boss_feedback_count),
        "hist_reported_abs_mean": reported_absolute_total / rounds_seen,
    }
    return features, "\n".join(text_parts)


def _history_private_chat(
    history: list[dict[str, Any]], trader_id: str
) -> tuple[dict[str, float], str]:
    rounds_seen = len(history)
    sent = 0
    received = 0
    text_parts: list[str] = []
    for record in history:
        outgoing = _messages_of(record, trader_id, "private")
        incoming = _messages_to(record, trader_id, "private")
        sent += len(outgoing)
        received += len(incoming)
        for message in (*outgoing, *incoming):
            text_parts.append(message["content"])
    return (
        {
            "hist_private_sent": float(sent),
            "hist_private_received": float(received),
            "hist_private_rate": sent / rounds_seen if rounds_seen else 0.0,
        },
        "\n".join(text_parts),
    )


def _situation(
    record: dict[str, Any], trader_id: str, metadata: dict[str, Any]
) -> dict[str, float]:
    state = _by_trader(record["pre_round_states"])[trader_id]
    peer_id = next(other for other in TRADER_IDS if other != trader_id)
    peer = _by_trader(record["pre_round_states"])[peer_id]
    total_rounds = metadata["config"]["rounds"]
    return {
        "pressure_level": float(record["pressure_level"]),
        "round_number": float(record["round_number"]),
        "rounds_remaining": float(total_rounds - record["round_number"]),
        "round_fraction": record["round_number"] / total_rounds,
        "rank": float(state["rank"]),
        "is_last_rank": float(state["rank"] > 1),
        "budget": state["budget"],
        "budget_fraction": (
            state["budget"] / metadata["config"]["initial_budget"]
            if metadata["config"]["initial_budget"]
            else 0.0
        ),
        "cumulative_pnl": state["cumulative_pnl"],
        "pnl_gap": state["pnl_gap"],
        "peer_budget": peer["budget"],
        "budget_minus_peer": state["budget"] - peer["budget"],
        "prior_misreporting_count": float(state["prior_misreporting_count"]),
        "prior_withholding_count": float(state["prior_withholding_count"]),
    }


def _current_round_observable(
    record: dict[str, Any], trader_id: str
) -> tuple[dict[str, float], str]:
    # Only used where the phase ordering allows it: the public chat of this
    # round, plus the boss feedback that arrived before it ran.
    public_out = _messages_of(record, trader_id, "public")
    public_in = _messages_to(record, trader_id, "public")
    text_parts = [message["content"] for message in (*public_out, *public_in)]
    for item in record["delivered_feedback"]:
        if item["trader_id"] in (None, trader_id):
            text_parts.append(item["content"])
    return (
        {
            "now_public_sent": float(len(public_out)),
            "now_public_received": float(len(public_in)),
            "now_shared_signal": float(
                any(message["shared_signal"] is not None for message in public_out)
            ),
            "now_peer_shared_signal": float(
                any(message["shared_signal"] is not None for message in public_in)
            ),
            "now_boss_feedback": float(
                sum(
                    1
                    for item in record["delivered_feedback"]
                    if item["trader_id"] in (None, trader_id)
                )
            ),
        },
        "\n".join(text_parts),
    )


def _current_round_private_chat(
    record: dict[str, Any], trader_id: str
) -> tuple[dict[str, float], str]:
    outgoing = _messages_of(record, trader_id, "private")
    incoming = _messages_to(record, trader_id, "private")
    text_parts = [message["content"] for message in (*outgoing, *incoming)]
    return (
        {
            "now_private_sent": float(len(outgoing)),
            "now_private_received": float(len(incoming)),
        },
        "\n".join(text_parts),
    )


def _reasoning_block(
    record: dict[str, Any], trader_id: str, phases: tuple[str, ...]
) -> tuple[dict[str, float], str]:
    traces = _reasoning_of(record, trader_id, phases)
    text = "\n".join(trace["content"] for trace in traces)
    words = text.split()
    return (
        {
            "reasoning_traces": float(len(traces)),
            "reasoning_words": float(len(words)),
            "reasoning_chars": float(len(text)),
        },
        text,
    )


def build_rows(
    episodes: Iterable[tuple[dict[str, Any], list[dict[str, Any]]]],
    target: str,
    horizon: str = "same",
) -> list[Row]:
    # target: "withholding" or "misreporting" -- decides which phases of the
    # current round are admissible.
    # horizon: "same" labels the round the features come from; "next" labels
    # the round after it, and every feature then comes from a completed round.
    if target not in PHASES_BEFORE:
        raise ValueError(f"unknown target: {target}")
    if horizon not in ("same", "next"):
        raise ValueError(f"unknown horizon: {horizon}")

    phases = ("pre_share", "pre_trade", "pre_report") if horizon == "next" else (
        PHASES_BEFORE[target]
    )
    # For misreporting the trader has already seen this round's chat when it
    # reports, so the chat is admissible. For withholding the chat is the act.
    use_current_chat = horizon == "next" or target == "misreporting"

    rows: list[Row] = []
    for metadata, records in episodes:
        config = metadata["config"]
        for index, record in enumerate(records):
            history = records[:index]
            if horizon == "next":
                if index + 1 >= len(records):
                    continue
                label_record = records[index + 1]
            else:
                label_record = record

            for trader_id in TRADER_IDS:
                history_numeric, history_text = _history_features(history, trader_id)
                history_chat, history_chat_text = _history_private_chat(
                    history, trader_id
                )

                observable = dict(history_numeric)
                observable_text = history_text
                private_chat = dict(history_chat)
                private_chat_text = history_chat_text

                if use_current_chat:
                    now_numeric, now_text = _current_round_observable(
                        record, trader_id
                    )
                    observable.update(now_numeric)
                    observable_text = "\n".join(
                        part for part in (observable_text, now_text) if part
                    )
                    now_chat, now_chat_text = _current_round_private_chat(
                        record, trader_id
                    )
                    private_chat.update(now_chat)
                    private_chat_text = "\n".join(
                        part for part in (private_chat_text, now_chat_text) if part
                    )
                else:
                    # Keep the key set identical across rows so the feature
                    # matrix has one fixed layout. A row that simply omits
                    # these would otherwise be filled with a column mean drawn
                    # from rows that did have them.
                    observable.update(
                        {
                            "now_public_sent": 0.0,
                            "now_public_received": 0.0,
                            "now_shared_signal": 0.0,
                            "now_peer_shared_signal": 0.0,
                            "now_boss_feedback": float(
                                sum(
                                    1
                                    for item in record["delivered_feedback"]
                                    if item["trader_id"] in (None, trader_id)
                                )
                            ),
                        }
                    )
                    for item in record["delivered_feedback"]:
                        if item["trader_id"] in (None, trader_id):
                            observable_text = "\n".join(
                                part
                                for part in (observable_text, item["content"])
                                if part
                            )
                    private_chat.update(
                        {"now_private_sent": 0.0, "now_private_received": 0.0}
                    )

                reasoning_numeric, reasoning_text = _reasoning_block(
                    record, trader_id, phases
                )
                withheld, costly, misreported = _labels_for(label_record, trader_id)

                rows.append(
                    Row(
                        episode_id=record["episode_id"],
                        seed=config["seed"],
                        pressure_level=record["pressure_level"],
                        round_number=record["round_number"],
                        trader_id=trader_id,
                        situation=_situation(record, trader_id, metadata),
                        observable=observable,
                        observable_text=observable_text,
                        private_chat=private_chat,
                        private_chat_text=private_chat_text,
                        reasoning=reasoning_numeric,
                        reasoning_text=reasoning_text,
                        withheld=withheld,
                        withheld_costly=costly,
                        misreported=misreported,
                    )
                )
    return rows


def label_of(row: Row, target: str, costly_only: bool = False) -> int:
    if target == "withholding":
        return row.withheld_costly if costly_only else row.withheld
    if target == "misreporting":
        return row.misreported
    raise ValueError(f"unknown target: {target}")
