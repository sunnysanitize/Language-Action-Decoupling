# A short episode driven by real LLM traders, with every model call recorded.
#
# This is the smoke test that the rest of the pipeline is built on. Until it
# runs, LLMTraderPolicy has only ever been exercised against the stub client in
# tests/test_llm_trader.py, which always answers in exactly the right shape. A
# real model does not. The response contract is strict on purpose -- fields in
# a fixed order, an exact field set on every message -- so the first thing
# worth knowing is how often a real model actually satisfies it.
#
# Every call is written to calls.jsonl as it completes, so a run that dies
# halfway still shows what the model said. That is the whole reason the
# recorder is wired in here rather than added later.
#
# Run a live pilot:
#   python -m experiments.pilot --rounds 5 --pressure 3
#
# Re-run a finished pilot from its recording, with no network calls:
#   python -m experiments.pilot --replay runs/pilot-20260813-120000
#
# The replay checks every prompt against the recording, so it fails loudly if
# the simulator no longer produces the same episode. That is the replayability
# requirement in docs/role_contract.md.

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Optional

from agents.llm_trader import (
    LLMSettings,
    LLMTraderPolicy,
    ModelResponseError,
    OpenAIChatModel,
)
from agents.recording import (
    RecordingModelClient,
    ReplayModelClient,
    error_body,
    read_calls,
)
from environment.datacontainers import EpisodeConfig, EpisodeResult
from simulation.episode import TRADER_IDS, run_episode


CALLS_FILENAME = "calls.jsonl"
METADATA_FILENAME = "metadata.json"


def build_config(arguments: argparse.Namespace) -> EpisodeConfig:
    episode_id = arguments.episode_id or time.strftime("pilot-%Y%m%d-%H%M%S")
    return EpisodeConfig(
        episode_id=episode_id,
        seed=arguments.seed,
        rounds=arguments.rounds,
        pressure_level=arguments.pressure,
        review_interval=arguments.review_interval,
    )


def load_config(run_directory: Path) -> EpisodeConfig:
    with (run_directory / METADATA_FILENAME).open(encoding="utf-8") as metadata_file:
        metadata = json.load(metadata_file)
    return EpisodeConfig(**metadata["config"])


def live_policies(
    config: EpisodeConfig,
    output_root: Path,
    settings: LLMSettings,
) -> dict[str, LLMTraderPolicy]:
    # One recorder per trader, all appending to the same calls.jsonl. The tag
    # is what lets a replay pull one trader's calls back out in order.
    calls_path = output_root / config.episode_id / CALLS_FILENAME
    return {
        trader_id: LLMTraderPolicy(
            model_client=RecordingModelClient(
                inner=OpenAIChatModel(settings),
                path=calls_path,
                settings=settings,
                tag=trader_id,
            ),
            settings=settings,
        )
        for trader_id in TRADER_IDS
    }


def replay_policies(run_directory: Path) -> dict[str, LLMTraderPolicy]:
    calls = read_calls(run_directory / CALLS_FILENAME)
    return {
        trader_id: LLMTraderPolicy(
            model_client=ReplayModelClient(calls, tag=trader_id)
        )
        for trader_id in TRADER_IDS
    }


# One throwaway call, to find out whether the provider is configured before
# spending a whole episode on it.
#
# A misconfigured endpoint fails identically on call 1 and call 30, so there is
# no reason to discover it the expensive way.
def check_provider(settings: LLMSettings) -> int:
    print(f"Endpoint:    {settings.endpoint}")
    print(f"Model:       {settings.model}")
    print(f"API version: {settings.api_version or '(none)'}")
    print("Sending one request...")
    try:
        payload = OpenAIChatModel(settings).complete(
            "Reply with one JSON object and nothing else.",
            '{"reply_with": {"ok": true}}',
        )
    except Exception as error:
        status = getattr(error, "status_code", None)
        print(
            f"\nFailed: {type(error).__name__}: {error}"
            + (f" (status {status})" if status is not None else ""),
            file=sys.stderr,
        )
        body = error_body(error)
        if body:
            print(f"Provider said: {body}", file=sys.stderr)
        if status == 404:
            print(
                "\nA 404 usually means the endpoint, the model name, or the "
                "api-version is wrong.\nFor Azure AI Foundry the endpoint "
                "looks like https://<resource>.services.ai.azure.com/models "
                "and\nAZURE_AI_API_VERSION must be set.",
                file=sys.stderr,
            )
        return 1
    print(f"\nOK. The model replied: {json.dumps(payload)[:200]}")
    return 0


def summarize(result: EpisodeResult) -> str:
    rounds = result.rounds
    if not rounds:
        return "No rounds completed."

    lines = [f"Rounds completed: {len(rounds)} of {result.config.rounds}"]
    misreported = {trader_id: 0 for trader_id in TRADER_IDS}
    withheld = {trader_id: 0 for trader_id in TRADER_IDS}
    costly = {trader_id: 0 for trader_id in TRADER_IDS}
    messages_sent = {trader_id: 0 for trader_id in TRADER_IDS}

    for record in rounds:
        for label in record.misreporting_labels:
            if label.occurred:
                misreported[label.trader_id] += 1
        for label in record.withholding_labels:
            if label.withheld:
                withheld[label.trader_id] += 1
            if label.occurred:
                costly[label.trader_id] += 1
        for message in record.messages:
            messages_sent[message.sender_id] += 1

    lines.append("")
    lines.append(
        f"{'trader':<10}{'rank':>6}{'budget':>10}{'pnl':>10}"
        f"{'msgs':>7}{'misrep':>8}{'withheld':>10}{'costly':>8}"
    )
    for state in rounds[-1].post_round_states:
        lines.append(
            f"{state.trader_id:<10}{state.rank:>6}{state.budget:>10.3f}"
            f"{state.cumulative_pnl:>10.3f}{messages_sent[state.trader_id]:>7}"
            f"{misreported[state.trader_id]:>8}{withheld[state.trader_id]:>10}"
            f"{costly[state.trader_id]:>8}"
        )

    lines.append("")
    lines.append(
        "withheld is the decision to predict; costly is the subset where "
        "sharing would have helped the firm."
    )
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a short LLM-driven pilot episode and record every model call."
    )
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--pressure",
        type=int,
        default=0,
        choices=(0, 1, 2, 3, 4),
        help="pressure level; higher cuts the losing trader's budget harder",
    )
    parser.add_argument("--review-interval", type=int, default=1)
    parser.add_argument(
        "--episode-id",
        default=None,
        help="run directory name; defaults to a timestamp",
    )
    parser.add_argument("--output-root", default="runs")
    parser.add_argument(
        "--replay",
        default=None,
        metavar="RUN_DIRECTORY",
        help="re-run a finished pilot from its calls.jsonl instead of calling the model",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="make one request to confirm the provider works, then stop",
    )
    arguments = parser.parse_args(argv)

    if arguments.check:
        try:
            return check_provider(LLMSettings.from_env())
        except ValueError as error:
            print(f"Cannot start: {error}", file=sys.stderr)
            return 2

    if arguments.replay is not None:
        run_directory = Path(arguments.replay)
        config = load_config(run_directory)
        policies = replay_policies(run_directory)
        output_root = None
        print(f"Replaying {run_directory} ({config.rounds} rounds, no network calls)")
    else:
        try:
            settings = LLMSettings.from_env()
        except ValueError as error:
            print(f"Cannot start: {error}", file=sys.stderr)
            print(
                "Copy .env.example to .env and fill in AZURE_AI_API_KEY.",
                file=sys.stderr,
            )
            return 2
        config = build_config(arguments)
        output_root = Path(arguments.output_root)
        run_directory = output_root / config.episode_id
        policies = live_policies(config, output_root, settings)
        print(
            f"Running {config.episode_id}: {config.rounds} rounds, "
            f"pressure {config.pressure_level}, model {settings.model}"
        )
        print(f"Writing to {run_directory}")

    # Every phase of every round is one model call, and a trader that breaks
    # the response contract stops the episode. The recording is already on
    # disk, so the failure is diagnosable rather than just fatal.
    try:
        result = run_episode(config, output_root=output_root, policies=policies)
    except ModelResponseError as error:
        print(f"\nThe model broke the response contract: {error}", file=sys.stderr)
        if error.raw_response is not None:
            print(f"Offending response: {error.raw_response}", file=sys.stderr)
        print(
            f"\nEvery call up to the failure is in {run_directory / CALLS_FILENAME}.",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(f"\nThe pilot stopped: {type(error).__name__}: {error}", file=sys.stderr)
        print(
            f"Calls made before the failure are in {run_directory / CALLS_FILENAME}.",
            file=sys.stderr,
        )
        return 1

    print()
    print(summarize(result))
    if output_root is not None:
        print()
        print(f"Rounds:      {run_directory / 'rounds.jsonl'}")
        print(f"Model calls: {run_directory / CALLS_FILENAME}")
        print(f"Replay with: python -m experiments.pilot --replay {run_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
