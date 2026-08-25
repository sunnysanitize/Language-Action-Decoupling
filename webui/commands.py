# The set of things the control desk is allowed to run, and the rules each
# parameter has to satisfy before it becomes an argv element.
#
# This file is the security boundary. The browser never sends a command line;
# it sends a command *name* out of this table plus a dict of parameters, and
# nothing reaches subprocess.Popen that was not built here from a validated
# value. That is why every field carries its own validator rather than the
# form doing the checking: a form is a suggestion, and the server is the only
# place that can insist.
#
# It is also the single source of truth for the form itself. `describe()`
# serializes this table to JSON and the page renders its inputs from that, so
# a field cannot drift out of sync with the validator that guards it -- the
# same reason simulation/labels.py routes every delivery question through
# message_reaches instead of letting three callers each decide.

from dataclasses import dataclass, field
from pathlib import Path
import re
import sys
from typing import Any, Callable, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Anything that becomes a directory or file name. Deliberately narrower than
# "path-safe": EpisodeJSONLWriter would reject a separator anyway, but it
# rejects it after creating nothing, and a clear message here beats a
# traceback in a job log.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

PRESSURE_BUDGET_MULTIPLIERS = {0: 1.00, 1: 0.90, 2: 0.75, 3: 0.50, 4: 0.25}


class ParameterError(ValueError):
    """A parameter the browser sent does not satisfy its field's rules."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str  # int | bool | choice | name | path | run | sweep
    default: Any = None
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    choices: tuple[dict, ...] = ()
    optional: bool = False
    help: str = ""
    # Some controls change meaning under the capital-authority condition. The
    # server owns both descriptions so the browser never has to invent an
    # explanation for an experimental treatment.
    setup_b_help: str = ""
    # Which file extensions a "path" field will accept. Both commands that
    # take an --output write a markdown document, and paper_report writes with
    # write_text rather than appending -- so an unrestricted path field is one
    # typo away from replacing a source file with a findings report.
    suffixes: tuple[str, ...] = ()

    def as_json(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "default": self.default,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "choices": list(self.choices),
            "optional": self.optional,
            "help": self.help,
            "setup_b_help": self.setup_b_help,
            "suffixes": list(self.suffixes),
        }


@dataclass(frozen=True)
class Command:
    name: str
    label: str
    blurb: str
    # Live means it spends provider tokens. The page marks these so nobody
    # starts a 60-episode sweep thinking it is a local computation.
    live: bool
    fields: tuple[Field, ...]
    build: Callable[[dict], list[str]] = field(repr=False, default=None)

    def as_json(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "blurb": self.blurb,
            "live": self.live,
            "fields": [item.as_json() for item in self.fields],
        }


# ---------------------------------------------------------------- validation


def _coerce_int(spec: Field, raw: Any) -> Optional[int]:
    if raw is None or raw == "":
        if spec.optional:
            return None
        raise ParameterError(f"{spec.label} is required")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ParameterError(f"{spec.label} must be a whole number") from None
    if spec.minimum is not None and value < spec.minimum:
        raise ParameterError(f"{spec.label} must be at least {spec.minimum}")
    if spec.maximum is not None and value > spec.maximum:
        raise ParameterError(f"{spec.label} must be at most {spec.maximum}")
    return value


def _coerce_name(spec: Field, raw: Any) -> Optional[str]:
    if raw is None or str(raw).strip() == "":
        if spec.optional:
            return None
        raise ParameterError(f"{spec.label} is required")
    value = str(raw).strip()
    if not SAFE_NAME.match(value):
        raise ParameterError(
            f"{spec.label} may only contain letters, digits, dot, dash and "
            "underscore, and must start with a letter or digit"
        )
    return value


# Output files (RESULTS.md, FINDINGS.md) are written wherever the caller says,
# so the caller has to stay inside the project. resolve() before comparing
# collapses "..", and is_relative_to catches a symlink that points out.
def _coerce_path(spec: Field, raw: Any) -> Optional[str]:
    if raw is None or str(raw).strip() == "":
        if spec.optional:
            return None
        raise ParameterError(f"{spec.label} is required")
    value = str(raw).strip()
    resolved = (PROJECT_ROOT / value).resolve()
    if not resolved.is_relative_to(PROJECT_ROOT):
        raise ParameterError(f"{spec.label} must stay inside the project")
    if resolved.is_dir():
        raise ParameterError(f"{spec.label} is a directory")
    if spec.suffixes and resolved.suffix.lower() not in spec.suffixes:
        raise ParameterError(
            f"{spec.label} must end in {' or '.join(spec.suffixes)}"
        )
    return str(resolved.relative_to(PROJECT_ROOT))


# A run or a sweep is picked from what is on disk, so the check is existence
# rather than shape: a directory the page offered but that has since been
# renamed should fail here and not three seconds later inside the analysis.
def _coerce_run(spec: Field, raw: Any, want_manifest: bool) -> Optional[str]:
    if raw is None or str(raw).strip() == "":
        if spec.optional:
            return None
        raise ParameterError(f"{spec.label} is required")
    value = str(raw).strip()
    resolved = (PROJECT_ROOT / value).resolve()
    if not resolved.is_relative_to(PROJECT_ROOT):
        raise ParameterError(f"{spec.label} must stay inside the project")
    if not resolved.is_dir():
        raise ParameterError(f"{spec.label}: no such directory ({value})")
    marker = "manifest.json" if want_manifest else "metadata.json"
    if not (resolved / marker).exists():
        kind = "sweep" if want_manifest else "episode"
        raise ParameterError(f"{value} is not a {kind} directory (no {marker})")
    return str(resolved.relative_to(PROJECT_ROOT))


def _coerce_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_choice(spec: Field, raw: Any) -> Any:
    allowed = [item["value"] for item in spec.choices]
    if raw in allowed:
        return raw
    # A <select> hands back strings even for integer choices.
    for candidate in allowed:
        if str(candidate) == str(raw):
            return candidate
    raise ParameterError(f"{spec.label} must be one of {allowed}")


def clean(command: Command, params: dict) -> dict:
    values: dict[str, Any] = {}
    for spec in command.fields:
        raw = params.get(spec.name, spec.default)
        if spec.kind == "int":
            values[spec.name] = _coerce_int(spec, raw)
        elif spec.kind == "bool":
            values[spec.name] = _coerce_bool(raw)
        elif spec.kind == "choice":
            values[spec.name] = _coerce_choice(spec, raw)
        elif spec.kind == "name":
            values[spec.name] = _coerce_name(spec, raw)
        elif spec.kind == "path":
            values[spec.name] = _coerce_path(spec, raw)
        elif spec.kind == "run":
            values[spec.name] = _coerce_run(spec, raw, want_manifest=False)
        elif spec.kind == "sweep":
            values[spec.name] = _coerce_run(spec, raw, want_manifest=True)
        else:  # pragma: no cover - a field kind that never shipped
            raise ParameterError(f"unknown field kind: {spec.kind}")
    return values


# ------------------------------------------------------------------ builders

# sys.executable, never the string "python". The desk is started from the
# project venv and the subprocess has to land in that same interpreter, or the
# analysis commands import a numpy that is not there.
def _python() -> list[str]:
    return [sys.executable]


def _build_pilot(values: dict) -> list[str]:
    argv = _python() + [
        "-m", "experiments.pilot",
        "--rounds", str(values["rounds"]),
        "--seed", str(values["seed"]),
        "--pressure", str(values["pressure"]),
        "--review-interval", str(values["review_interval"]),
        "--output-root", values["output_root"],
    ]
    if values["episode_id"]:
        argv += ["--episode-id", values["episode_id"]]
    if values["boss_capital_authority"]:
        argv.append("--boss-capital-authority")
    return argv


def _build_replay(values: dict) -> list[str]:
    return _python() + ["-m", "experiments.pilot", "--replay", values["run"]]


def _build_check(values: dict) -> list[str]:
    del values
    return _python() + ["-m", "experiments.pilot", "--check"]


def _build_sweep(values: dict) -> list[str]:
    argv = _python() + [
        "-m", "experiments.sweep",
        "--rounds", str(values["rounds"]),
        "--seeds", str(values["seeds"]),
        "--seed-start", str(values["seed_start"]),
        "--review-interval", str(values["review_interval"]),
        "--workers", str(values["workers"]),
        "--attempts", str(values["attempts"]),
        "--output-root", values["output_root"],
    ]
    if values["sweep_id"]:
        argv += ["--sweep-id", values["sweep_id"]]
    if values["boss_capital_authority"]:
        argv.append("--boss-capital-authority")
    return argv


def _build_report(values: dict) -> list[str]:
    argv = _python() + [
        "-m", "experiments.report",
        "--sweep", values["sweep"],
        "--output", values["output"],
    ]
    if values["stdout"]:
        argv.append("--stdout")
    return argv


def _build_findings(values: dict) -> list[str]:
    argv = _python() + [
        "-m", "experiments.paper_report",
        "--control", values["control"],
        "--output", values["output"],
    ]
    if values["capital"]:
        argv += ["--capital", values["capital"]]
    if values["stdout"]:
        argv.append("--stdout")
    return argv


def _build_capital_check(values: dict) -> list[str]:
    return _python() + ["-m", "experiments.capital_check", "--sweep", values["sweep"]]


def _build_show_run(values: dict) -> list[str]:
    argv = _python() + [
        "-m", "experiments.show_run",
        values["run"],
        "--width", str(values["width"]),
    ]
    if values["round"] is not None:
        argv += ["--round", str(values["round"])]
    if values["misconduct"]:
        argv.append("--misconduct")
    if values["full"]:
        argv.append("--full")
    if values["calls"]:
        argv.append("--calls")
    return argv


def _build_tests(values: dict) -> list[str]:
    del values
    return _python() + ["-m", "unittest", "discover", "-v"]


# -------------------------------------------------------------- the whitelist

PRESSURE_CHOICES = tuple(
    {
        "value": level,
        "label": f"{level}",
        "note": f"budget x{multiplier:.2f}",
        "setup_b_note": "founder tone",
    }
    for level, multiplier in sorted(PRESSURE_BUDGET_MULTIPLIERS.items())
)

_OUTPUT_ROOT = Field(
    "output_root", "Output root", "name", default="runs",
    help="directory the run lands in, relative to the project",
)
_SETUP = Field(
    "boss_capital_authority", "Setup B - boss holds the purse", "bool",
    default=False,
    help="off: the pressure formula moves budgets and the boss only talks. "
         "on: the boss splits a fixed pool on what traders report, so lying pays.",
)

COMMANDS: tuple[Command, ...] = (
    Command(
        name="pilot",
        label="Run episode",
        blurb="One live episode with LLM traders, boss and overseer. "
              "Every model call is recorded to calls.jsonl as it lands.",
        live=True,
        fields=(
            Field("rounds", "Rounds", "int", default=10, minimum=1, maximum=100),
            Field("seed", "Seed", "int", default=1, minimum=0, maximum=2**31 - 1,
                  help="same seed, same market"),
            Field("pressure", "Pressure", "choice", default=0,
                  choices=PRESSURE_CHOICES,
                  help="Setup A: worst-ranked budget multiplier applied after review",
                  setup_b_help="Setup B: founder rhetoric only; the pressure formula is "
                               "disabled and the boss allocates the fixed pool from reports"),
            Field("review_interval", "Review every", "int", default=1,
                  minimum=1, maximum=20, help="rounds between boss reviews"),
            _SETUP,
            Field("episode_id", "Episode id", "name", default="", optional=True,
                  help="leave empty for a timestamp; the directory must not exist"),
            _OUTPUT_ROOT,
        ),
        build=_build_pilot,
    ),
    Command(
        name="sweep",
        label="Run sweep",
        blurb="The full grid: 5 pressure levels x N shared seeds, one episode "
              "per process so a single failure does not take down the grid.",
        live=True,
        fields=(
            Field("rounds", "Rounds", "int", default=10, minimum=1, maximum=100),
            Field("seeds", "Seeds", "int", default=12, minimum=1, maximum=200,
                  help="episodes per pressure level; total is 5x this"),
            Field("seed_start", "First seed", "int", default=1001, minimum=0,
                  maximum=2**31 - 1),
            Field("review_interval", "Review every", "int", default=1,
                  minimum=1, maximum=20),
            _SETUP,
            Field("workers", "Workers", "int", default=8, minimum=1, maximum=32,
                  help="past ~10 the provider's tokens-per-minute ceiling binds, not the CPU"),
            Field("attempts", "Attempts", "int", default=3, minimum=1, maximum=10,
                  help="retries per episode before the manifest records it failed"),
            Field("sweep_id", "Sweep id", "name", default="", optional=True,
                  help="leave empty for a timestamp"),
            _OUTPUT_ROOT,
        ),
        build=_build_sweep,
    ),
    Command(
        name="replay",
        label="Replay episode",
        blurb="Re-run a finished episode from its recording with no network "
              "calls. Fails loudly if the simulator no longer builds the same prompts.",
        live=False,
        fields=(
            Field("run", "Episode", "run", default="", help="a directory holding metadata.json"),
        ),
        build=_build_replay,
    ),
    Command(
        name="check",
        label="Check provider",
        blurb="One throwaway request, to find out whether the endpoint, model "
              "and api-version are right before spending an episode on them.",
        live=True,
        fields=(),
        build=_build_check,
    ),
    Command(
        name="report",
        label="Append to RESULTS",
        blurb="Analyze a finished sweep and append one technical section to "
              "the audit trail.",
        live=False,
        fields=(
            Field("sweep", "Sweep", "sweep", default=""),
            Field("output", "Output file", "path", default="RESULTS.md", suffixes=(".md",)),
            Field("stdout", "Print instead of appending", "bool", default=False),
        ),
        build=_build_report,
    ),
    Command(
        name="findings",
        label="Write FINDINGS",
        blurb="Rewrite the plain-language write-up from one or both sweeps. "
              "Overwrites the output file rather than appending.",
        live=False,
        fields=(
            Field("control", "Setup A sweep", "sweep", default=""),
            Field("capital", "Setup B sweep", "sweep", default="", optional=True),
            Field("output", "Output file", "path", default="FINDINGS.md", suffixes=(".md",)),
            Field("stdout", "Print instead of writing", "bool", default=False),
        ),
        build=_build_findings,
    ),
    Command(
        name="capital_check",
        label="Capital go/no-go",
        blurb="Cheap check on a Setup B sweep: is the capital condition really "
              "creating the incentive, or silently failing?",
        live=False,
        fields=(
            Field("sweep", "Sweep", "sweep", default=""),
        ),
        build=_build_capital_check,
    ),
    Command(
        name="show_run",
        label="Read a run",
        blurb="Render rounds.jsonl or calls.jsonl as readable text.",
        live=False,
        fields=(
            Field("run", "Episode", "run", default=""),
            Field("round", "Round", "int", default="", optional=True,
                  minimum=1, maximum=1000, help="empty shows every round"),
            Field("misconduct", "Only rounds where a label fired", "bool", default=False),
            Field("full", "Do not truncate reasoning", "bool", default=False),
            Field("calls", "Show model calls instead", "bool", default=False),
            Field("width", "Width", "int", default=76, minimum=40, maximum=200),
        ),
        build=_build_show_run,
    ),
    Command(
        name="tests",
        label="Run tests",
        blurb="python -m unittest discover -v, from the project root.",
        live=False,
        fields=(),
        build=_build_tests,
    ),
)

BY_NAME = {command.name: command for command in COMMANDS}


def describe() -> list[dict]:
    return [command.as_json() for command in COMMANDS]


# Turns a command name plus browser-supplied parameters into an argv, or
# raises ParameterError. Callers hand the argv straight to the job runner;
# nothing else is allowed to assemble one.
def build(name: str, params: dict) -> tuple[Command, dict, list[str]]:
    command = BY_NAME.get(name)
    if command is None:
        raise ParameterError(f"unknown command: {name}")
    values = clean(command, params or {})
    return command, values, command.build(values)
