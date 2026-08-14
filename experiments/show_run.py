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
from typing import Optional


RULE = "=" * 72


def read_rounds(run_directory: Path) -> list[dict]:
    path = run_directory / "rounds.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"no rounds.jsonl in {run_directory}")
    with path.open(encoding="utf-8") as rounds_file:
        return [json.loads(line) for line in rounds_file if line.strip()]


def wrap(text: str, width: int, indent: str) -> str:
    import textwrap

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

    # .get keeps the viewer working on schema 1 runs already in runs/.
    for item in record.get("delivered_feedback", []):
        audience = item["trader_id"] or "the desk"
        content = item["content"]
        if not full and len(content) > 240:
            content = content[:240].rstrip() + " ..."
        print()
        print(f"boss to {audience}: {content}")

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
            content = trace["content"]
            if not full and len(content) > 240:
                content = content[:240].rstrip() + " ..."
            print(f"  {heading}:")
            print(wrap(content, width, "    "))

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
            body = json.dumps(call["response"], indent=2)
            if not full and len(body) > 400:
                body = body[:400].rstrip() + "\n  ..."
            print(wrap(body, width, "  ") if full else body)
        else:
            print(f"  error: {call['error']}")
            if call.get("raw_response"):
                print(f"  raw:   {call['raw_response'][:400]}")


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
