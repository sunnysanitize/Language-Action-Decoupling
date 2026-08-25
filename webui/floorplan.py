# Turns one recorded episode into an ordered list of beats a trading floor can
# act out: who thought what, who said what to whom, and what it cost.
#
# Presentation only. Nothing here feeds a label or a detector -- experiments/
# dataset.py owns the timing rules that matter for the science, and this file
# must never become a second opinion on them. What it owns is narrative order:
# the sequence a viewer needs in order to follow a round.
#
# That order is not the order of the fields in the record. Supervisor reasoning
# stored in round N describes the review that ran *after* round N-1 and was
# delivered *before* round N (simulation/episode.py holds it in
# pending_reasoning and attaches it to the next round), and delivered_feedback
# in round N is likewise what reached traders before round N decided anything.
# So a round is played as: brief, signal, share, trade, report, market. Putting
# supervision first is not a stylistic choice -- it is the causal claim the
# study is testing, and drawing it in the wrong order would illustrate the
# opposite of what happened.
#
# Two honesty rules the renderer depends on:
#
#   * A THINK beat is private_reasoning. It was never shown to another agent.
#   * A SAY beat is something that actually reached someone: a Message, or a
#     BossFeedback item, or the overseer's delivered directive.
#
# The overseer is the awkward one. rounds.jsonl keeps only its
# private_reasoning -- what it *said* to the boss is not in that file at all.
# It is in calls.jsonl, as the `content` field of the same model response, so
# the two are joined on the reasoning text rather than on a call index. Joining
# on text means a missing or renumbered call drops one speech bubble instead of
# silently attributing round 7's directive to round 3.

import json
from pathlib import Path
from typing import Any, Optional

from webui.runs import read_rounds, _read_json


TRADER_IDS = ("trader_a", "trader_b")
BOSS_ID = "boss_1"
OVERSEER_ID = "ken_griffin"

# Where each actor stands on the floor and how it is drawn. The rows are the
# hierarchy: the founder above the portfolio manager above the traders, which
# is the structure the experiment manipulates.
ACTORS: tuple[dict, ...] = (
    {
        "id": OVERSEER_ID,
        "name": "Ken Griffin",
        "role": "Founder",
        "row": 0,
        "seat": 0,
        "palette": "founder",
        "blurb": "Sets firm-level pressure. Never speaks to a trader.",
    },
    {
        "id": BOSS_ID,
        "name": "The Boss",
        "role": "Portfolio manager",
        "row": 1,
        "seat": 0,
        "palette": "boss",
        "blurb": "Hears the founder, briefs the desk. Never sees an executed position.",
    },
    {
        "id": "trader_a",
        "name": "Trader A",
        "role": "Trader",
        "row": 2,
        "seat": 0,
        "palette": "trader_a",
        "blurb": "Private signal, own book, own rank.",
    },
    {
        "id": "trader_b",
        "name": "Trader B",
        "role": "Trader",
        "row": 2,
        "seat": 1,
        "palette": "trader_b",
        "blurb": "Private signal, own book, own rank.",
    },
)

PHASES: tuple[dict, ...] = (
    {"id": "brief", "label": "Brief", "note": "supervision, before anyone trades"},
    {"id": "signal", "label": "Signal", "note": "each trader's private draw"},
    {"id": "share", "label": "Share", "note": "the only phase withholding is decided in"},
    {"id": "trade", "label": "Trade", "note": "requested, then clipped to budget"},
    {"id": "report", "label": "Report", "note": "what the trader claims it did"},
    {"id": "market", "label": "Market", "note": "the direction, the P&L, the labels"},
)


def _beat(phase: str, actor: str, kind: str, text: str, **extra) -> dict:
    beat = {"phase": phase, "actor": actor, "kind": kind, "text": text}
    beat.update(extra)
    return beat


def _traces(record: dict, actor: str, phase: str) -> list[str]:
    return [
        trace.get("content", "")
        for trace in record.get("reasoning", [])
        if trace.get("actor_id") == actor and trace.get("phase") == phase
    ]


# Maps an overseer private_reasoning string to the directive it was written
# alongside. Built once per episode from calls.jsonl, which is the only file
# that keeps what the founder actually sent to the boss.
def _overseer_speech(directory: Path) -> dict[str, str]:
    spoken: dict[str, str] = {}
    calls_path = directory / "calls.jsonl"
    if not calls_path.exists():
        return spoken
    try:
        with calls_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    call = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if call.get("tag") != OVERSEER_ID or call.get("status") != "ok":
                    continue
                response = call.get("response")
                # The recorder stringifies values, so a response can arrive as
                # a dict or as its repr. Only the dict form is usable, and a
                # missing directive costs one bubble, not the scene.
                if not isinstance(response, dict):
                    continue
                reasoning = str(response.get("private_reasoning", "")).strip()
                content = str(response.get("content", "")).strip()
                if reasoning and content:
                    spoken[reasoning] = content
    except OSError:
        return spoken
    return spoken


def _by_trader(items: list[dict], key: str) -> dict[str, Any]:
    return {item["trader_id"]: item.get(key) for item in items if "trader_id" in item}


def round_beats(record: dict, spoken: dict[str, str]) -> list[dict]:
    beats: list[dict] = []

    # ---------------------------------------------------------------- brief
    for phase_name in ("mandate", "pre_review"):
        for reasoning in _traces(record, OVERSEER_ID, phase_name):
            beats.append(
                _beat("brief", OVERSEER_ID, "think", reasoning, to=None)
            )
            directive = spoken.get(reasoning.strip())
            if directive:
                beats.append(
                    _beat("brief", OVERSEER_ID, "say", directive, to=BOSS_ID)
                )
        for reasoning in _traces(record, BOSS_ID, phase_name):
            beats.append(_beat("brief", BOSS_ID, "think", reasoning, to=None))

    for item in record.get("delivered_feedback", []):
        target = item.get("trader_id")
        beats.append(
            _beat(
                "brief",
                BOSS_ID,
                "say",
                item.get("content", ""),
                to=target,
                broadcast=target is None,
            )
        )

    # Setup B only. One CapitalAllocation covers the whole desk -- dicts keyed
    # by trader, not a row each -- and it is split here so the floor can show
    # the money moving to one trader at a time. attributed_pnl rides along
    # because the gap between what the boss credited a trader with and what
    # that trader actually made is the divergence Setup B was built to expose.
    for allocation in record.get("capital_allocations", []):
        budgets = allocation.get("allocated_budget") or {}
        attributed = allocation.get("attributed_pnl") or {}
        for trader_id in TRADER_IDS:
            if trader_id not in budgets:
                continue
            beats.append(
                _beat(
                    "brief",
                    BOSS_ID,
                    "act",
                    f"allots {budgets[trader_id]:.2f} to {trader_id} "
                    f"(credited {attributed.get(trader_id, 0.0):+.2f})",
                    to=trader_id,
                    data={
                        "budget": budgets[trader_id],
                        "attributed_pnl": attributed.get(trader_id),
                    },
                )
            )

    # --------------------------------------------------------------- signal
    for observation in record.get("observations", []):
        signal = observation.get("signal")
        accuracy = observation.get("signal_accuracy")
        beats.append(
            _beat(
                "signal",
                observation.get("trader_id", "?"),
                "signal",
                f"private signal {signal:+d} ({accuracy:.0%} accurate)",
                data={"signal": signal, "accuracy": accuracy},
            )
        )

    # ---------------------------------------------------------------- share
    #
    # Withholding is decided here and nowhere else, so the label is attached to
    # this phase rather than left to the market beat where its cost is known.
    withheld = {
        label["trader_id"]: label
        for label in record.get("withholding_labels", [])
        if "trader_id" in label
    }
    for trader_id in TRADER_IDS:
        for reasoning in _traces(record, trader_id, "pre_share"):
            beats.append(_beat("share", trader_id, "think", reasoning))
    for message in record.get("messages", []):
        sender = message.get("sender_id", "?")
        beats.append(
            _beat(
                "share",
                sender,
                "say",
                message.get("content", ""),
                to=message.get("recipient_id"),
                channel=message.get("channel"),
                shared_signal=message.get("shared_signal"),
                broadcast=message.get("recipient_id") is None,
            )
        )
    for trader_id, label in withheld.items():
        if label.get("withheld"):
            beats.append(
                _beat(
                    "share",
                    trader_id,
                    "label",
                    "kept the signal to itself",
                    label="withheld",
                    costly=bool(label.get("occurred")),
                    delta=label.get("counterfactual_profit_delta"),
                )
            )

    # ---------------------------------------------------------------- trade
    requested = _by_trader(record.get("executions", []), "requested_position")
    executed = _by_trader(record.get("executions", []), "executed_position")
    for trader_id in TRADER_IDS:
        for reasoning in _traces(record, trader_id, "pre_trade"):
            beats.append(_beat("trade", trader_id, "think", reasoning))
    for item in record.get("executions", []):
        trader_id = item.get("trader_id", "?")
        want = item.get("requested_position", 0.0)
        got = item.get("executed_position", 0.0)
        clipped = abs(want - got) > 1e-9
        beats.append(
            _beat(
                "trade",
                trader_id,
                "act",
                f"takes {got:+.2f}" + (f" (asked {want:+.2f}, budget clipped)" if clipped else ""),
                data={"requested": want, "executed": got, "clipped": clipped},
            )
        )

    # --------------------------------------------------------------- report
    misreported = {
        label["trader_id"]: label
        for label in record.get("misreporting_labels", [])
        if "trader_id" in label
    }
    for trader_id in TRADER_IDS:
        for reasoning in _traces(record, trader_id, "pre_report"):
            beats.append(_beat("report", trader_id, "think", reasoning))
    for item in record.get("reports", []):
        trader_id = item.get("trader_id", "?")
        claimed = item.get("reported_position", 0.0)
        label = misreported.get(trader_id, {})
        beats.append(
            _beat(
                "report",
                trader_id,
                "say",
                f"reports {claimed:+.2f}",
                to=BOSS_ID,
                data={
                    "reported": claimed,
                    "executed": executed.get(trader_id),
                },
                label="misreported" if label.get("occurred") else None,
                difference=label.get("position_difference"),
            )
        )

    # --------------------------------------------------------------- market
    world = record.get("world") or {}
    direction = world.get("market_direction")
    beats.append(
        _beat(
            "market",
            "market",
            "system",
            f"market moves {direction:+d}, return {world.get('realized_return', 0):+.2f}",
            data=world,
        )
    )
    for item in record.get("ledger", []):
        pnl = item.get("pnl", 0.0)
        beats.append(
            _beat(
                "market",
                item.get("trader_id", "?"),
                "pnl",
                f"{pnl:+.3f}",
                data={"pnl": pnl, "position": item.get("position")},
            )
        )
    return beats


def episode_scene(directory: Path) -> dict:
    records = read_rounds(directory)
    metadata = _read_json(directory / "metadata.json") or {}
    config = metadata.get("config", {})
    spoken = _overseer_speech(directory)

    rounds = []
    for record in records:
        rounds.append(
            {
                "round": record.get("round_number"),
                "world": record.get("world") or {},
                "pre_states": record.get("pre_round_states", []),
                "post_states": record.get("post_round_states", []),
                "beats": round_beats(record, spoken),
            }
        )

    return {
        "id": directory.name,
        "config": config,
        "setup": "B" if config.get("boss_capital_authority") else "A",
        "pressure": config.get("pressure_level"),
        "actors": list(ACTORS),
        "phases": list(PHASES),
        "rounds": rounds,
        # A live episode is still being written. The page uses this to decide
        # whether to keep asking for more rounds.
        "complete": bool(config.get("rounds")) and len(records) >= config["rounds"],
        "rounds_planned": config.get("rounds"),
        "has_overseer_speech": bool(spoken),
    }
