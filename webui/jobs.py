# Runs the whitelisted commands as child processes and keeps enough state
# about each one that a browser polling every second can draw it.
#
# Two things here are worth knowing before editing.
#
# Child processes are started in their own session (start_new_session=True) so
# that cancelling can signal the whole group. A sweep is a parent that spawns
# one process per episode; terminating only the parent would leave up to
# `workers` episodes still talking to the provider, still writing into run
# directories, and invisible to this page. Killing the group is the only stop
# button that actually stops.
#
# Progress is read from disk, not counted from stdout. experiments.pilot
# prints nothing per round -- it prints its summary at the end -- so the only
# honest answer to "how far along is this episode" is how many lines are in
# rounds.jsonl. The run directory is learned by parsing the one line the pilot
# prints when it starts, which keeps this module from having to reimplement
# the timestamp-id rule and then drift from it.

from collections import deque
from dataclasses import dataclass, field
import itertools
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional


# A sweep of 60 episodes prints about 65 lines; a verbose test run prints a few
# hundred. The cap exists so that a command that decides to print a megabyte
# cannot take the desk down with it.
MAX_LOG_LINES = 4000

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"

FINISHED = {SUCCEEDED, FAILED, CANCELLED}

# experiments.sweep prints "[12/60] p0-s1001 ok (254.3s)" as each episode ends.
SWEEP_PROGRESS = re.compile(r"^\[(\d+)/(\d+)\]")
# experiments.pilot announces where it is writing and how long the episode is.
PILOT_HEADER = re.compile(r"^Running \S+: (\d+) rounds")
PILOT_TARGET = re.compile(r"^Writing to (.+)$")
REPLAY_HEADER = re.compile(r"^Replaying (.+?) \((\d+) rounds")


@dataclass
class Job:
    id: str
    command: str
    label: str
    argv: list[str]
    params: dict
    created: float
    status: str = QUEUED
    started: Optional[float] = None
    ended: Optional[float] = None
    returncode: Optional[int] = None
    error: str = ""
    # Filled in from the child's own first lines, then used to read progress
    # off the filesystem rather than guessing it from elapsed time.
    run_directory: Optional[str] = None
    total_units: Optional[int] = None
    done_units: Optional[int] = None
    unit_name: str = ""
    lines: deque = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    # Counts every line ever produced, including the ones the deque dropped,
    # so the client's "give me everything after offset N" stays meaningful
    # after a truncation instead of silently replaying old output.
    lines_produced: int = 0
    process: Optional[subprocess.Popen] = field(default=None, repr=False)

    @property
    def seconds(self) -> float:
        if self.started is None:
            return 0.0
        return (self.ended or time.monotonic()) - self.started

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "command": self.command,
            "label": self.label,
            "argv": self.argv,
            "params": self.params,
            "status": self.status,
            "returncode": self.returncode,
            "error": self.error,
            "seconds": round(self.seconds, 1),
            "created": self.created,
            "run_directory": self.run_directory,
            "done_units": self.done_units,
            "total_units": self.total_units,
            "unit_name": self.unit_name,
            "lines_produced": self.lines_produced,
            "dropped_lines": max(0, self.lines_produced - len(self.lines)),
        }


class JobRunner:
    def __init__(self, project_root: Path, max_running: int = 4) -> None:
        self.project_root = Path(project_root)
        self.max_running = max_running
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._counter = itertools.count(1)

    # ------------------------------------------------------------- lifecycle

    def start(self, command: str, label: str, argv: list[str], params: dict) -> Job:
        with self._lock:
            running = [
                job for job in self._jobs.values() if job.status in (QUEUED, RUNNING)
            ]
            if len(running) >= self.max_running:
                raise RuntimeError(
                    f"{len(running)} jobs are already running; stop one first"
                )
            job_id = f"job-{next(self._counter):04d}"
            job = Job(
                id=job_id,
                command=command,
                label=label,
                argv=list(argv),
                params=dict(params),
                created=time.time(),
            )
            self._jobs[job_id] = job
            self._order.append(job_id)

        environment = dict(os.environ)
        # Without this the child buffers 8KB at a time and the console sits
        # empty for minutes, which reads as a hang.
        environment["PYTHONUNBUFFERED"] = "1"

        try:
            process = subprocess.Popen(
                argv,
                cwd=str(self.project_root),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as error:
            with self._lock:
                job.status = FAILED
                job.error = f"could not start: {error}"
                job.started = job.ended = time.monotonic()
            return job

        with self._lock:
            job.process = process
            job.status = RUNNING
            job.started = time.monotonic()

        threading.Thread(
            target=self._pump, args=(job,), name=f"{job_id}-pump", daemon=True
        ).start()
        return job

    def _pump(self, job: Job) -> None:
        assert job.process is not None and job.process.stdout is not None
        try:
            for raw in job.process.stdout:
                line = raw.rstrip("\n")
                with self._lock:
                    job.lines.append(line)
                    job.lines_produced += 1
                    self._read_progress(job, line)
        finally:
            # The pipe has to be closed explicitly. A cancelled job leaves the
            # reader holding an open descriptor otherwise, and a desk that runs
            # for an afternoon of sweeps would leak one per job.
            job.process.stdout.close()
        job.process.wait()
        with self._lock:
            job.ended = time.monotonic()
            job.returncode = job.process.returncode
            if job.status == CANCELLED:
                pass
            elif job.returncode == 0:
                job.status = SUCCEEDED
                # A finished episode is a finished episode, whatever the last
                # line-count probe happened to see.
                if job.total_units is not None:
                    job.done_units = job.total_units
            else:
                job.status = FAILED
                job.error = f"exit code {job.returncode}"

    # Called with the lock held, once per output line.
    def _read_progress(self, job: Job, line: str) -> None:
        match = SWEEP_PROGRESS.match(line)
        if match:
            job.done_units = int(match.group(1))
            job.total_units = int(match.group(2))
            job.unit_name = "episodes"
            return
        match = PILOT_HEADER.match(line)
        if match:
            job.total_units = int(match.group(1))
            job.unit_name = "rounds"
            return
        match = PILOT_TARGET.match(line)
        if match:
            job.run_directory = match.group(1).strip()
            return
        match = REPLAY_HEADER.match(line)
        if match:
            job.run_directory = match.group(1).strip()
            job.total_units = int(match.group(2))
            job.unit_name = "rounds"

    def cancel(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status in FINISHED:
                return job
            job.status = CANCELLED
            job.error = "stopped from the control desk"
            process = job.process

        if process is not None and process.poll() is None:
            # SIGTERM to the whole session, so a sweep's episode subprocesses
            # go down with their parent. A pilot killed mid-episode leaves a
            # partial rounds.jsonl and calls.jsonl behind on purpose: the
            # recording of what the model said up to the kill is the useful
            # part, and the directory can be deleted by hand.
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                process.terminate()
        return job

    # -------------------------------------------------------------- readback

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def snapshot(self) -> list[dict]:
        with self._lock:
            jobs = [self._jobs[job_id] for job_id in self._order]
        return [self._describe(job) for job in jobs]

    def describe(self, job_id: str) -> dict:
        return self._describe(self.get(job_id))

    def _describe(self, job: Job) -> dict:
        payload = job.as_json()
        payload.update(self._probe(job))
        return payload

    # Reads how many rounds have actually been written. Cheap enough to do on
    # every poll -- it is one open and a byte scan of a file a few tens of KB
    # long -- and it is the only per-round progress an episode emits.
    def _probe(self, job: Job) -> dict:
        if job.status != RUNNING or not job.run_directory:
            return {}
        rounds_path = self.project_root / job.run_directory / "rounds.jsonl"
        try:
            with rounds_path.open("rb") as handle:
                written = sum(1 for _ in handle)
        except OSError:
            return {}
        return {"done_units": written}

    def log(self, job_id: str, offset: int = 0) -> dict:
        job = self.get(job_id)
        with self._lock:
            available = list(job.lines)
            produced = job.lines_produced
        first_kept = produced - len(available)
        start = max(0, offset - first_kept)
        return {
            "offset": max(offset, first_kept),
            "next_offset": produced,
            "lines": available[start:],
            "dropped": max(0, first_kept - offset),
        }

    # Jobs are kept for the life of the server so the console history survives
    # a page reload. This drops the finished ones on request.
    def clear_finished(self) -> int:
        with self._lock:
            stale = [
                job_id
                for job_id in self._order
                if self._jobs[job_id].status in FINISHED
            ]
            for job_id in stale:
                del self._jobs[job_id]
            self._order = [item for item in self._order if item not in set(stale)]
        return len(stale)

    def shutdown(self) -> None:
        for job in list(self._jobs.values()):
            if job.status not in FINISHED:
                try:
                    self.cancel(job.id)
                except KeyError:  # pragma: no cover - raced with clear
                    pass
