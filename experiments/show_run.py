# Reads a finished run as text instead of JSON.
#
# rounds.jsonl and calls.jsonl are one object per line on purpose: a round is
# appended the moment it completes, so a run that crashes keeps everything
# before the crash. Pretty-printing the files would trade that away. This
# renders them instead, and leaves the files alone.
#
# What one round actually contains -- who knew what, who said what, who did
# what, and which of those the labeller flagged -- is spread across eight
# separate lists in the record. Reading that from raw JSON means holding the
# join in your head. That is the thing worth automating, more than indentation.
#
#   python -m experiments.show_run runs/pilot-20260813-232307
#   python -m experiments.show_run runs/... --round 3 --full
#   python -m experiments.show_run runs/... --misconduct
#   python -m experiments.show_run runs/... --calls
#
# For ad-hoc queries jq is still the better tool, since these are ordinary
# JSON lines:
#
#   jq -r 'select(.round_number==3) | .reasoning[] | .phase' runs/*/rounds.jsonl

import argparse
import json
from pathlib import Path
import sys
import textwrap
from typing import Any, Optional


RULE = "=" * 72


def read_rounds(run_directory: Path) -> list[dict]:
    path = run_directory / "rounds.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"no rounds.jsonl in {run_directory}")
    with path.open(encoding="utf-8") as rounds_file:
        return [json.loads(line) for line in rounds_file if line.strip()]


def wrap(text: str, width: int, indent: str) -> str:
    return "\n".join(
        textwrap.fill(
            paragraph,
            width=width,
            initial_indent=indent,
            subsequent_indent=indent,
        )
        for paragraph in text.splitlines()
        if paragraph.strip()
    )


def clip(content: str, full: bool) -> str:
    if full or len(content) <= 240:
        return content
    return content[:240].rstrip() + " ..."


# clip, applied to every string inside a payload rather than to the payload's
# printed form.
#
# Truncating the rendered JSON instead -- which is what this used to do -- cuts
# in the middle of whichever field happens to be long, so the structure after
# it disappears with it. A model reply is one enormous private_reasoning and
# then the fields that actually record the decision, so the truncated part was
# reliably the part worth seeing.
def clip_strings(value: Any, full: bool) -> Any:
    if isinstance(value, str):
        return clip(value, full)
    if isinstance(value, list):
        return [clip_strings(item, full) for item in value]
    if isinstance(value, dict):
        return {key: clip_strings(item, full) for key, item in value.items()}
    return value


# Prints JSON that fits the terminal.
#
# json.dumps(indent=2) gets the structure right and then puts a whole page of
# reasoning on one line, because it will not break a string; wrap() flattens
# the indentation, because textwrap.fill normalises leading whitespace. So
# neither one alone is readable. This wraps each line inside the indentation
# json.dumps already chose.
#
# The result is for reading, not for parsing -- a wrapped string is no longer
# valid JSON. The files on disk are untouched and jq still works on them.
def render_json(value: Any, width: int, indent: str) -> str:
    lines: list[str] = []
    for line in json.dumps(value, indent=2, ensure_ascii=False).splitlines():
        body = line.lstrip()
        own_indent = indent + line[: len(line) - len(body)]
        if len(own_indent) + len(body) <= width:
            lines.append(own_indent + body)
            continue
        lines.extend(
            textwrap.wrap(
                body,
                width=width,
                initial_indent=own_indent,
                # Continuations sit past the key they belong to, so a wrapped
                # value still reads as one field rather than as a new one.
                subsequent_indent=own_indent + "  ",
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return "\n".join(lines)


# Everyone in the reasoning list who is not one of the market traders.
#
# The boss and the overseer write to the same list the traders do, and until
# this was here their traces were the only part of a round the viewer dropped:
# every mandate and every review was on disk and invisible. Reading the actor
# ids off the record rather than importing BOSS_ID and KEN_ID keeps the viewer
# working on runs recorded before either agent existed, and on runs where only
# one of them was wired in.
def supervisor_traces(record: dict, trader_ids: set[str]) -> list[dict]:
    return [
        trace
        for trace in record["reasoning"]
        if trace.get("actor_id", trace.get("trader_id")) not in trader_ids
    ]


def show_supervision(traces: list[dict], full: bool, width: int) -> None:
    for trace in traces:
        actor = trace.get("actor_id", trace.get("trader_id"))
        print()
        print(f"{actor} thinking ({trace['phase']}):")
        print(wrap(clip(trace["content"], full), width, "  "))


def show_round(record: dict, full: bool, width: int) -> None:
    world = record["world"]
    direction = "UP" if world["market_direction"] > 0 else "DOWN"
    print(RULE)
    print(
        f"Round {record['round_number']}  |  market {direction}  |  "
        f"return {world['realized_return']:+.2f}  |  "
        f"pressure {record['pressure_level']}"
    )
    print(RULE)

    by_trader = lambda items: {item["trader_id"]: item for item in items}
    signals = by_trader(record["observations"])
    executions = by_trader(record["executions"])
    reports = by_trader(record["reports"])
    ledger = by_trader(record["ledger"])
    before = by_trader(record["pre_round_states"])
    after = by_trader(record["post_round_states"])
    misreporting = by_trader(record["misreporting_labels"])

    # The mandate is written before any round runs, so it prints above the
    # round it lands on; the review is written after the round completes and
    # prints at the bottom. Same list on disk, but the order is the point --
    # a review that appeared before the trades would read as an instruction
    # the traders could have followed.
    supervision = supervisor_traces(record, set(signals))
    show_supervision(
        [trace for trace in supervision if trace["phase"] == "mandate"], full, width
    )

    # .get keeps the viewer working on schema 1 runs already in runs/.
    for item in record.get("delivered_feedback", []):
        audience = item["trader_id"] or "the desk"
        print()
        print(f"boss to {audience}:")
        print(wrap(clip(item["content"], full), width, "  "))

    for trader_id in sorted(signals):
        state = before[trader_id]
        signal = signals[trader_id]["signal"]
        correct = "correct" if signal == world["market_direction"] else "wrong"
        print()
        print(
            f"{trader_id}  rank {state['rank']}  budget {state['budget']:.3f}  "
            f"pnl {state['cumulative_pnl']:+.3f}  |  "
            f"signal {signal:+d} ({correct})"
        )

        for phase, heading in (
            ("pre_share", "thinking (before speaking)"),
            ("pre_trade", "thinking (before trading)"),
            ("pre_report", "thinking (before reporting)"),
        ):
            trace = next(
                (
                    item
                    for item in record["reasoning"]
                    # Schema 1 called this trader_id; schema 2 renamed it to
                    # actor_id when the boss started writing to the same list.
                    # Runs are regenerable, but not for free, so the viewer
                    # reads both rather than orphaning the ones on disk.
                    if item.get("actor_id", item.get("trader_id")) == trader_id
                    and item["phase"] == phase
                ),
                None,
            )
            if trace is None:
                continue
            print(f"  {heading}:")
            print(wrap(clip(trace["content"], full), width, "    "))

        sent = [
            message
            for message in record["messages"]
            if message["sender_id"] == trader_id
        ]
        for message in sent:
            target = (
                "all" if message["channel"] == "public" else message["recipient_id"]
            )
            shared = message["shared_signal"]
            tag = f" [shares signal {shared:+d}]" if shared is not None else ""
            print(f"  says to {target}{tag}:")
            print(wrap(message["content"], width, "    "))
        if not sent:
            print("  says nothing")

        execution = executions[trader_id]
        report = reports[trader_id]
        clipped = (
            ""
            if abs(execution["requested_position"] - execution["executed_position"])
            < 1e-9
            else f" (clipped from {execution['requested_position']:+.3f})"
        )
        flag = " <- MISREPORT" if misreporting[trader_id]["occurred"] else ""
        print(
            f"  position {execution['executed_position']:+.3f}{clipped}  "
            f"reported {report['reported_position']:+.3f}{flag}  "
            f"pnl {ledger[trader_id]['pnl']:+.3f}"
        )

        for label in record["withholding_labels"]:
            if label["trader_id"] != trader_id or not label["withheld"]:
                continue
            if label["occurred"]:
                print(
                    f"  <- WITHHELD, and it cost the firm "
                    f"{label['counterfactual_profit_delta']:+.3f}"
                )
            else:
                print("  <- withheld, but sharing would not have helped")

        end = after[trader_id]
        if abs(end["budget"] - state["budget"]) > 1e-9:
            print(f"  budget {state['budget']:.3f} -> {end['budget']:.3f}")

    show_supervision(
        [trace for trace in supervision if trace["phase"] != "mandate"], full, width
    )


def show_calls(run_directory: Path, full: bool, width: int) -> None:
    path = run_directory / "calls.jsonl"
    if not path.exists():
        print(f"no calls.jsonl in {run_directory}", file=sys.stderr)
        return
    with path.open(encoding="utf-8") as calls_file:
        calls = [json.loads(line) for line in calls_file if line.strip()]

    print(RULE)
    print(f"{len(calls)} model calls")
    print(RULE)
    for call in calls:
        status = call["status"]
        print(
            f"\n[{call['call_index']}] {call['tag']}  {status}  "
            f"{call['latency_seconds']:.1f}s  {call['model']}"
        )
        if status == "ok":
            print(render_json(clip_strings(call["response"], full), width, "  "))
        else:
            print("  error:")
            print(wrap(call["error"], width, "    "))
            raw = call.get("raw_response")
            if raw:
                # The raw text is whatever the model sent, which is usually a
                # JSON object and sometimes the reason it was rejected, so it
                # is rendered as JSON when it parses and as text when it does
                # not. A response that failed to parse is exactly the one worth
                # reading literally.
                print("  raw:")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    print(wrap(clip(raw, full), width, "    "))
                else:
                    print(render_json(clip_strings(payload, full), width, "    "))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print a finished run in a readable form."
    )
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--round", type=int, default=None, help="show only this round")
    parser.add_argument(
        "--misconduct",
        action="store_true",
        help="show only rounds where a label fired",
    )
    parser.add_argument(
        "--full", action="store_true", help="do not truncate reasoning"
    )
    parser.add_argument("--calls", action="store_true", help="show model calls instead")
    parser.add_argument("--width", type=int, default=76)
    arguments = parser.parse_args(argv)

    try:
        if arguments.calls:
            show_calls(arguments.run_directory, arguments.full, arguments.width)
            return 0
        rounds = read_rounds(arguments.run_directory)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1

    metadata_path = arguments.run_directory / "metadata.json"
    if metadata_path.exists():
        config = json.loads(metadata_path.read_text(encoding="utf-8"))["config"]
        print(
            f"{config['episode_id']}  seed {config['seed']}  "
            f"{config['rounds']} rounds  pressure {config['pressure_level']}"
        )

    shown = 0
    for record in rounds:
        if arguments.round is not None and record["round_number"] != arguments.round:
            continue
        if arguments.misconduct and not (
            any(item["occurred"] for item in record["misreporting_labels"])
            or any(item["withheld"] for item in record["withholding_labels"])
        ):
            continue
        show_round(record, arguments.full, arguments.width)
        shown += 1

    if shown == 0:
        print("nothing to show for those filters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
