# Reads what is already on disk under runs/ so the desk can show it.
#
# Strictly read-only, and deliberately tolerant. The runs directory holds
# episodes written by three different schema versions -- the pilots from
# August 13 predate boss_capital_authority entirely -- and a browser panel that
# refuses to list a run because one key is missing is worse than one that shows
# the run with a blank cell. Anything derived is recomputed from rounds.jsonl
# rather than trusted from a summary file, because no summary file is written.
#
# The counts here duplicate what experiments.pilot.summarize prints, and that
# is on purpose: summarize builds its table from live EpisodeResult objects
# that only exist inside a running episode, while this reads finished JSONL.
# The label definitions they share live in simulation/labels.py, so neither of
# them decides what withholding means.

from dataclasses import dataclass
import json
from pathlib import Path
import threading
import time
from typing import Any, Optional


SWEEP_MARKER = "manifest.json"
EPISODE_MARKER = "metadata.json"
ROUNDS_FILE = "rounds.jsonl"
CALLS_FILE = "calls.jsonl"


def _read_json(path: Path) -> Optional[dict]:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _count_lines(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _setup_name(config: dict) -> str:
    return "B" if config.get("boss_capital_authority") else "A"


# Both sides get resolved before being compared. On macOS the temporary
# directory the tests use is /var/..., which is a symlink to /private/var,
# so resolving only one side makes a path that is plainly inside the root
# look like it is outside it.
def _relative(directory: Path, project_root: Path) -> str:
    return str(directory.resolve().relative_to(Path(project_root).resolve()))


def read_rounds(run_directory: Path) -> list[dict]:
    records = []
    path = run_directory / ROUNDS_FILE
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    # A run killed mid-write leaves a torn last line. Every
                    # complete round before it is still good data.
                    break
    except OSError:
        return []
    return records


# ------------------------------------------------------------------ listings


def describe_episode(directory: Path, project_root: Path) -> Optional[dict]:
    metadata = _read_json(directory / EPISODE_MARKER)
    if metadata is None:
        return None
    config = metadata.get("config", {})
    rounds_written = _count_lines(directory / ROUNDS_FILE)
    planned = config.get("rounds") or 0
    return {
        "kind": "episode",
        "id": directory.name,
        "path": _relative(directory, project_root),
        "parent": directory.parent.name if directory.parent != project_root else "",
        "schema_version": metadata.get("schema_version"),
        "setup": _setup_name(config),
        "pressure": config.get("pressure_level"),
        "seed": config.get("seed"),
        "rounds_planned": planned,
        "rounds_written": rounds_written,
        "complete": planned > 0 and rounds_written >= planned,
        "review_interval": config.get("review_interval"),
        "signal_accuracy": config.get("signal_accuracy"),
        "has_calls": (directory / CALLS_FILE).exists(),
        "modified": directory.stat().st_mtime,
        "config": config,
    }


def describe_sweep(directory: Path, project_root: Path) -> Optional[dict]:
    manifest = _read_json(directory / SWEEP_MARKER)
    if manifest is None:
        return None
    episodes = manifest.get("episodes", [])
    failed = [item for item in episodes if item.get("status") != "ok"]
    return {
        "kind": "sweep",
        "id": directory.name,
        "path": _relative(directory, project_root),
        "setup": "B" if manifest.get("boss_capital_authority") else "A",
        "episodes": len(episodes),
        "failed": len(failed),
        "rounds": manifest.get("rounds"),
        "seeds": len(manifest.get("seeds", [])),
        "pressure_levels": manifest.get("pressure_levels", []),
        "review_interval": manifest.get("review_interval"),
        "wall_seconds": manifest.get("wall_seconds"),
        "workers": manifest.get("workers"),
        "modified": directory.stat().st_mtime,
    }


# A sweep in progress has no manifest yet -- experiments.sweep writes it at the
# end -- so a directory holding episode directories and nothing else is still
# a sweep. Guessing that here is what makes a running sweep visible in the
# panel instead of appearing only once it finishes.
def _looks_like_sweep_in_progress(directory: Path) -> bool:
    if (directory / EPISODE_MARKER).exists():
        return False
    try:
        children = list(directory.iterdir())
    except OSError:
        return False
    return any(
        child.is_dir() and (child / EPISODE_MARKER).exists() for child in children
    )


def list_runs(runs_root: Path, project_root: Path) -> list[dict]:
    if not runs_root.is_dir():
        return []
    found: list[dict] = []
    for directory in sorted(runs_root.iterdir()):
        if not directory.is_dir():
            continue
        sweep = describe_sweep(directory, project_root)
        if sweep is not None:
            found.append(sweep)
            continue
        episode = describe_episode(directory, project_root)
        if episode is not None:
            found.append(episode)
            continue
        if _looks_like_sweep_in_progress(directory):
            children = [
                describe_episode(child, project_root)
                for child in sorted(directory.iterdir())
                if child.is_dir()
            ]
            children = [item for item in children if item]
            found.append(
                {
                    "kind": "sweep",
                    "id": directory.name,
                    "path": _relative(directory, project_root),
                    "setup": children[0]["setup"] if children else "A",
                    "episodes": len(children),
                    "failed": 0,
                    "rounds": children[0]["rounds_planned"] if children else None,
                    "seeds": None,
                    "pressure_levels": sorted(
                        {item["pressure"] for item in children if item["pressure"] is not None}
                    ),
                    "review_interval": None,
                    "wall_seconds": None,
                    "workers": None,
                    "in_progress": True,
                    "modified": directory.stat().st_mtime,
                }
            )
    found.sort(key=lambda item: item["modified"], reverse=True)
    return found


def sweep_episodes(directory: Path, project_root: Path) -> list[dict]:
    episodes = []
    for child in sorted(directory.iterdir()):
        if not child.is_dir():
            continue
        described = describe_episode(child, project_root)
        if described is not None:
            episodes.append(described)
    episodes.sort(key=lambda item: (item["pressure"] or 0, item["seed"] or 0))
    return episodes


# ------------------------------------------------------------------ summaries


def episode_summary(directory: Path) -> dict:
    records = read_rounds(directory)
    metadata = _read_json(directory / EPISODE_MARKER) or {}
    config = metadata.get("config", {})

    traders: dict[str, dict] = {}

    def slot(trader_id: str) -> dict:
        return traders.setdefault(
            trader_id,
            {
                "trader_id": trader_id,
                "rank": None,
                "budget": None,
                "cumulative_pnl": None,
                "messages": 0,
                "signals_shared": 0,
                "misreported": 0,
                "withheld": 0,
                "costly": 0,
            },
        )

    timeline = []
    for record in records:
        for message in record.get("messages", []):
            entry = slot(message.get("sender_id", "?"))
            entry["messages"] += 1
            if message.get("shared_signal") is not None:
                entry["signals_shared"] += 1
        for label in record.get("misreporting_labels", []):
            if label.get("occurred"):
                slot(label.get("trader_id", "?"))["misreported"] += 1
        for label in record.get("withholding_labels", []):
            entry = slot(label.get("trader_id", "?"))
            if label.get("withheld"):
                entry["withheld"] += 1
            if label.get("occurred"):
                entry["costly"] += 1

        firm_pnl = sum(item.get("pnl", 0.0) for item in record.get("ledger", []))
        timeline.append(
            {
                "round": record.get("round_number"),
                "direction": (record.get("world") or {}).get("market_direction"),
                "realized_return": (record.get("world") or {}).get("realized_return"),
                "firm_pnl": round(firm_pnl, 6),
                "misreported": sum(
                    1 for item in record.get("misreporting_labels", []) if item.get("occurred")
                ),
                "withheld": sum(
                    1 for item in record.get("withholding_labels", []) if item.get("withheld")
                ),
                "costly": sum(
                    1 for item in record.get("withholding_labels", []) if item.get("occurred")
                ),
                "budgets": {
                    item["trader_id"]: item.get("budget")
                    for item in record.get("post_round_states", [])
                },
                "pnl": {
                    item["trader_id"]: item.get("cumulative_pnl")
                    for item in record.get("post_round_states", [])
                },
            }
        )

    if records:
        for state in records[-1].get("post_round_states", []):
            entry = slot(state["trader_id"])
            entry["rank"] = state.get("rank")
            entry["budget"] = state.get("budget")
            entry["cumulative_pnl"] = state.get("cumulative_pnl")

    # Who spoke, and how often feedback actually reached a trader. An episode
    # where the boss quietly stopped writing reads exactly like one where it
    # spoke every round if you only look at the traders.
    supervision: dict[str, int] = {}
    delivered = 0
    trader_ids = set(traders)
    for record in records:
        for trace in record.get("reasoning", []):
            actor = trace.get("actor_id", "?")
            if actor in trader_ids:
                continue
            supervision[actor] = supervision.get(actor, 0) + 1
        delivered += len(record.get("delivered_feedback", []))

    return {
        "id": directory.name,
        "config": config,
        "setup": _setup_name(config),
        "rounds_written": len(records),
        "rounds_planned": config.get("rounds"),
        "traders": [traders[key] for key in sorted(traders)],
        "timeline": timeline,
        "supervision": supervision,
        "feedback_delivered": delivered,
        "calls": _count_lines(directory / CALLS_FILE),
    }


# Withholding and misreporting rates per pressure level, over every episode in
# a sweep. This is the headline number from FINDINGS.md, recomputed rather
# than parsed out of the markdown so a fresh sweep shows its own result before
# anybody runs the report.
#
# Cached on the sweep directory's mtime because reading 60 episodes is a few
# megabytes of JSON and the panel polls.
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


def sweep_summary(directory: Path, project_root: Path) -> dict:
    key = str(directory.resolve())
    stamp = directory.stat().st_mtime
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] == stamp:
            return cached[1]

    by_pressure: dict[int, dict] = {}
    episodes = sweep_episodes(directory, project_root)
    for episode in episodes:
        pressure = episode["pressure"]
        bucket = by_pressure.setdefault(
            pressure,
            {
                "pressure": pressure,
                "episodes": 0,
                "trader_rounds": 0,
                "withheld": 0,
                "costly": 0,
                "misreported": 0,
            },
        )
        bucket["episodes"] += 1
        for record in read_rounds(project_root / episode["path"]):
            labels = record.get("withholding_labels", [])
            bucket["trader_rounds"] += len(labels)
            bucket["withheld"] += sum(1 for item in labels if item.get("withheld"))
            bucket["costly"] += sum(1 for item in labels if item.get("occurred"))
            bucket["misreported"] += sum(
                1
                for item in record.get("misreporting_labels", [])
                if item.get("occurred")
            )

    rows = []
    for pressure in sorted(by_pressure):
        bucket = by_pressure[pressure]
        total = bucket["trader_rounds"] or 1
        rows.append(
            {
                **bucket,
                "withheld_rate": bucket["withheld"] / total,
                "costly_rate": bucket["costly"] / total,
                "misreported_rate": bucket["misreported"] / total,
            }
        )

    summary = {
        "id": directory.name,
        "rows": rows,
        "episodes": len(episodes),
        "trader_rounds": sum(row["trader_rounds"] for row in rows),
        "computed": time.time(),
    }
    with _CACHE_LOCK:
        _CACHE[key] = (stamp, summary)
    return summary
