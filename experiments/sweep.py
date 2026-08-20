# Runs the full experiment grid: every pressure level crossed with a shared
# seed list, each episode a separate process.
#
# One episode is one process on purpose. An episode that dies -- a provider
# timeout, a model that breaks the response contract on round 7 -- takes down
# only itself, and the manifest records that it failed instead of the sweep
# ending wherever the first bad call landed. Retrying then means re-running one
# process, not the grid.
#
# Seeds are shared across pressure levels rather than drawn per episode, so
# pressure 0 seed 1001 and pressure 4 seed 1001 see the same market. That is
# the pairing docs/role_contract.md asks for, and it is what lets a difference
# between two pressure levels be read as the treatment rather than as one
# condition drawing kinder markets.
#
#   python -m experiments.sweep --seeds 12 --rounds 10 --workers 8
#
# Every episode lands in its own directory under the sweep root, in exactly the
# layout experiments.pilot already writes, so a sweep episode replays with the
# same command as a pilot episode.

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Optional


PRESSURE_LEVELS = (0, 1, 2, 3, 4)
MANIFEST_FILENAME = "manifest.json"


@dataclass
class EpisodeJob:
    episode_id: str
    pressure: int
    seed: int
    rounds: int
    review_interval: int
    boss_capital_authority: bool = False


@dataclass
class EpisodeOutcome:
    episode_id: str
    pressure: int
    seed: int
    rounds: int
    status: str
    attempts: int
    seconds: float
    error: str = ""


def build_jobs(arguments: argparse.Namespace) -> list[EpisodeJob]:
    seeds = [arguments.seed_start + offset for offset in range(arguments.seeds)]
    jobs = []
    for pressure in PRESSURE_LEVELS:
        for seed in seeds:
            jobs.append(
                EpisodeJob(
                    episode_id=f"p{pressure}-s{seed}",
                    pressure=pressure,
                    seed=seed,
                    rounds=arguments.rounds,
                    review_interval=arguments.review_interval,
                    boss_capital_authority=arguments.boss_capital_authority,
                )
            )
    return jobs


def run_one(job: EpisodeJob, sweep_root: Path, attempts: int) -> EpisodeOutcome:
    # A retry has to clear the run directory first. EpisodeJSONLWriter creates
    # it with exist_ok=False so that two runs can never interleave rounds into
    # one rounds.jsonl, which means a half-written directory from a failed
    # attempt would make every retry fail instantly on the mkdir rather than on
    # whatever actually went wrong.
    run_directory = sweep_root / job.episode_id
    command = [
        sys.executable,
        "-m",
        "experiments.pilot",
        "--rounds",
        str(job.rounds),
        "--seed",
        str(job.seed),
        "--pressure",
        str(job.pressure),
        "--review-interval",
        str(job.review_interval),
        "--episode-id",
        job.episode_id,
        "--output-root",
        str(sweep_root),
    ]
    if job.boss_capital_authority:
        command.append("--boss-capital-authority")

    started = time.monotonic()
    last_error = ""
    for attempt in range(1, attempts + 1):
        if run_directory.exists():
            shutil.rmtree(run_directory)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        if completed.returncode == 0:
            return EpisodeOutcome(
                episode_id=job.episode_id,
                pressure=job.pressure,
                seed=job.seed,
                rounds=job.rounds,
                status="ok",
                attempts=attempt,
                seconds=round(time.monotonic() - started, 1),
            )
        last_error = (completed.stderr or completed.stdout).strip()[-600:]
        # The full stderr goes to a file rather than only into the manifest.
        # The manifest is written at the end of the sweep, so a sweep killed
        # partway through -- which is exactly when the failures matter -- would
        # otherwise leave no record of why anything failed.
        failures_directory = sweep_root / "failures"
        failures_directory.mkdir(parents=True, exist_ok=True)
        log_path = failures_directory / f"{job.episode_id}-attempt{attempt}.log"
        log_path.write_text(
            f"$ {' '.join(command)}\n\n--- stdout ---\n{completed.stdout}\n"
            f"--- stderr ---\n{completed.stderr}\n",
            encoding="utf-8",
        )
        print(
            f"  {job.episode_id} attempt {attempt}/{attempts} failed "
            f"(log: {log_path})",
            file=sys.stderr,
        )

    return EpisodeOutcome(
        episode_id=job.episode_id,
        pressure=job.pressure,
        seed=job.seed,
        rounds=job.rounds,
        status="failed",
        attempts=attempts,
        seconds=round(time.monotonic() - started, 1),
        error=last_error,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the full pressure x seed episode grid."
    )
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--seeds", type=int, default=12)
    parser.add_argument("--seed-start", type=int, default=1001)
    parser.add_argument("--review-interval", type=int, default=1)
    parser.add_argument(
        "--boss-capital-authority",
        action="store_true",
        help="run the capital-authority arm instead of the rhetorical boss",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--output-root", default="runs")
    parser.add_argument(
        "--sweep-id",
        default=None,
        help="sweep directory name; defaults to a timestamp",
    )
    arguments = parser.parse_args(argv)

    sweep_id = arguments.sweep_id or time.strftime("sweep-%Y%m%d-%H%M%S")
    sweep_root = Path(arguments.output_root) / sweep_id
    sweep_root.mkdir(parents=True, exist_ok=True)

    jobs = build_jobs(arguments)
    print(
        f"Sweep {sweep_id}: {len(jobs)} episodes "
        f"({len(PRESSURE_LEVELS)} pressure levels x {arguments.seeds} seeds x "
        f"{arguments.rounds} rounds), {arguments.workers} at a time"
    )
    print(f"Writing to {sweep_root}")

    started = time.monotonic()
    outcomes: list[EpisodeOutcome] = []
    with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
        futures = {
            pool.submit(run_one, job, sweep_root, arguments.attempts): job
            for job in jobs
        }
        for future in as_completed(futures):
            outcome = future.result()
            outcomes.append(outcome)
            done = len(outcomes)
            print(
                f"[{done}/{len(jobs)}] {outcome.episode_id} {outcome.status} "
                f"({outcome.seconds}s)"
            )

    outcomes.sort(key=lambda item: (item.pressure, item.seed))
    failed = [item for item in outcomes if item.status != "ok"]
    manifest = {
        "sweep_id": sweep_id,
        "rounds": arguments.rounds,
        "seeds": [arguments.seed_start + offset for offset in range(arguments.seeds)],
        "pressure_levels": list(PRESSURE_LEVELS),
        "review_interval": arguments.review_interval,
        "boss_capital_authority": arguments.boss_capital_authority,
        "workers": arguments.workers,
        "wall_seconds": round(time.monotonic() - started, 1),
        "episodes": [asdict(item) for item in outcomes],
    }
    with (sweep_root / MANIFEST_FILENAME).open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print()
    print(
        f"Completed {len(outcomes) - len(failed)}/{len(outcomes)} episodes in "
        f"{manifest['wall_seconds']}s"
    )
    if failed:
        print("Failed episodes:")
        for item in failed:
            print(f"  {item.episode_id}: {item.error.splitlines()[-1:] or ['']}")
    print(f"Manifest: {sweep_root / MANIFEST_FILENAME}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
