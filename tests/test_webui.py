# Tests for the control desk.
#
# The three things worth testing here are the three that would be dangerous or
# silently wrong if they broke: the parameter validators (they are the only
# thing between a browser and subprocess.Popen), cancellation (a stop button
# that leaves a sweep's episodes running is worse than no stop button), and
# the readers (a summary that quietly miscounts a label would be believed).
#
# Stdlib only, like the rest of the suite, and no network: the jobs tested
# here run `python -c` snippets rather than experiments.

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from webui import commands, floorplan, runs
from webui.jobs import FINISHED, JobRunner
from webui.server import DeskHandler, DeskServer


def wait_until(predicate, timeout=15.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class ParameterValidationTests(unittest.TestCase):
    def test_every_command_builds_from_its_own_defaults(self):
        # A default that its own validator rejects would mean the form opens
        # in an invalid state, which is the one state nobody tests by hand.
        for command in commands.COMMANDS:
            defaults = {field.name: field.default for field in command.fields}
            needs_a_run = any(
                field.kind in ("run", "sweep") and not field.optional
                for field in command.fields
            )
            if needs_a_run:
                continue  # nothing on disk to default to; covered separately
            with self.subTest(command=command.name):
                _, _, argv = commands.build(command.name, defaults)
                self.assertEqual(argv[0], sys.executable)

    def test_unknown_command_is_refused(self):
        with self.assertRaises(commands.ParameterError):
            commands.build("rm", {})

    def test_integers_are_range_checked(self):
        spec = commands.Field("rounds", "Rounds", "int", default=10, minimum=1, maximum=100)
        self.assertEqual(commands._coerce_int(spec, "12"), 12)
        with self.assertRaises(commands.ParameterError):
            commands._coerce_int(spec, 0)
        with self.assertRaises(commands.ParameterError):
            commands._coerce_int(spec, 101)
        with self.assertRaises(commands.ParameterError):
            commands._coerce_int(spec, "ten")

    def test_optional_integer_accepts_empty(self):
        spec = commands.Field("round", "Round", "int", default="", optional=True, minimum=1)
        self.assertIsNone(commands._coerce_int(spec, ""))

    def test_choice_accepts_the_string_a_select_sends(self):
        spec = commands.Field("pressure", "Pressure", "choice", choices=commands.PRESSURE_CHOICES)
        self.assertEqual(commands._coerce_choice(spec, "3"), 3)
        with self.assertRaises(commands.ParameterError):
            commands._coerce_choice(spec, "5")

    def test_pressure_picker_describes_the_active_capital_mechanism(self):
        pilot = next(command for command in commands.COMMANDS if command.name == "pilot")
        pressure = next(field for field in pilot.fields if field.name == "pressure")
        described = pressure.as_json()

        self.assertIn("budget multiplier", described["help"])
        self.assertIn("pressure formula is disabled", described["setup_b_help"])
        self.assertIn("boss allocates", described["setup_b_help"])
        self.assertTrue(all("budget x" in choice["note"] for choice in described["choices"]))
        self.assertTrue(all(
            choice["setup_b_note"] == "founder tone"
            for choice in described["choices"]
        ))

        # The browser must select the alternate copy from the current toggle,
        # not merely receive honest metadata that it never renders.
        source = (Path.cwd() / "webui" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("values.boss_capital_authority && choice.setup_b_note", source)
        self.assertIn("values.boss_capital_authority && field.setup_b_help", source)

    def test_names_reject_separators_and_traversal(self):
        spec = commands.Field("episode_id", "Episode id", "name", default="")
        self.assertEqual(commands._coerce_name(spec, " ok-1.2_3 "), "ok-1.2_3")
        for bad in ("..", ".", "a/b", "a\\b", "-lead", ""):
            with self.subTest(bad=bad), self.assertRaises(commands.ParameterError):
                commands._coerce_name(spec, bad)

    def test_paths_cannot_escape_the_project(self):
        spec = commands.Field("output", "Output", "path", default="RESULTS.md")
        self.assertEqual(commands._coerce_path(spec, "RESULTS.md"), "RESULTS.md")
        for bad in ("../escaped.md", "/etc/passwd", "docs/../../out.md"):
            with self.subTest(bad=bad), self.assertRaises(commands.ParameterError):
                commands._coerce_path(spec, bad)

    def test_an_output_path_cannot_replace_a_source_file(self):
        # paper_report writes with write_text, so an unrestricted --output is
        # one typo away from replacing a module with a findings document.
        spec = commands.Field("output", "Output", "path", default="FINDINGS.md", suffixes=(".md",))
        self.assertEqual(commands._coerce_path(spec, "FINDINGS.md"), "FINDINGS.md")
        with self.assertRaises(commands.ParameterError):
            commands._coerce_path(spec, "agents/prompts.py")

    def test_boolean_flags_only_appear_when_set(self):
        base = {
            "rounds": 4, "seed": 2, "pressure": 1, "review_interval": 1,
            "episode_id": "", "output_root": "runs",
        }
        _, _, off = commands.build("pilot", {**base, "boss_capital_authority": False})
        _, _, on = commands.build("pilot", {**base, "boss_capital_authority": True})
        self.assertNotIn("--boss-capital-authority", off)
        self.assertIn("--boss-capital-authority", on)

    def test_the_argv_is_never_a_shell_string(self):
        # Popen is called with a list, so a value containing shell syntax is an
        # argument and not a command. This asserts the shape that makes that so.
        for command in commands.COMMANDS:
            defaults = {field.name: field.default for field in command.fields}
            if any(f.kind in ("run", "sweep") and not f.optional for f in command.fields):
                continue
            _, _, argv = commands.build(command.name, defaults)
            self.assertTrue(all(isinstance(item, str) for item in argv))


class JobRunnerTests(unittest.TestCase):
    def setUp(self):
        self.runner = JobRunner(Path.cwd(), max_running=2)
        self.addCleanup(self.runner.shutdown)

    def test_output_is_captured_and_the_exit_code_recorded(self):
        job = self.runner.start(
            "tests", "Echo",
            [sys.executable, "-c", "print('hello'); print('world')"], {},
        )
        self.assertTrue(wait_until(lambda: self.runner.get(job.id).status in FINISHED))
        described = self.runner.describe(job.id)
        self.assertEqual(described["status"], "succeeded")
        self.assertEqual(described["returncode"], 0)
        self.assertEqual(self.runner.log(job.id)["lines"], ["hello", "world"])

    def test_stderr_is_merged_and_a_bad_exit_is_a_failure(self):
        job = self.runner.start(
            "tests", "Fail",
            [sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(3)"],
            {},
        )
        self.assertTrue(wait_until(lambda: self.runner.get(job.id).status in FINISHED))
        described = self.runner.describe(job.id)
        self.assertEqual(described["status"], "failed")
        self.assertEqual(described["returncode"], 3)
        self.assertIn("bad", self.runner.log(job.id)["lines"])

    def test_log_offsets_return_only_what_is_new(self):
        job = self.runner.start(
            "tests", "Count",
            [sys.executable, "-c", "[print(i) for i in range(5)]"], {},
        )
        self.assertTrue(wait_until(lambda: self.runner.get(job.id).status in FINISHED))
        first = self.runner.log(job.id, 0)
        self.assertEqual(first["lines"], ["0", "1", "2", "3", "4"])
        self.assertEqual(self.runner.log(job.id, first["next_offset"])["lines"], [])
        self.assertEqual(self.runner.log(job.id, 3)["lines"], ["3", "4"])

    def test_cancel_takes_the_whole_process_group_down(self):
        # The reason cancel signals a group rather than a pid: a sweep is a
        # parent whose children are the episodes, and killing only the parent
        # would leave those episodes running and unreachable.
        child_script = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(60)\n"
        )
        job = self.runner.start("tests", "Group", [sys.executable, "-c", child_script], {})
        self.assertTrue(wait_until(lambda: self.runner.log(job.id)["lines"]))
        grandchild = int(self.runner.log(job.id)["lines"][0])

        self.runner.cancel(job.id)
        self.assertTrue(wait_until(lambda: self.runner.get(job.id).status in FINISHED))
        self.assertEqual(self.runner.get(job.id).status, "cancelled")

        def grandchild_is_gone():
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                return True
            except PermissionError:  # pragma: no cover - reparented, not ours
                return True
            return False

        self.assertTrue(wait_until(grandchild_is_gone), "the grandchild survived the stop")

    def test_running_more_than_the_limit_is_refused(self):
        argv = [sys.executable, "-c", "import time; time.sleep(30)"]
        first = self.runner.start("tests", "A", argv, {})
        second = self.runner.start("tests", "B", argv, {})
        with self.assertRaises(RuntimeError):
            self.runner.start("tests", "C", argv, {})
        self.runner.cancel(first.id)
        self.runner.cancel(second.id)

    def test_clear_drops_finished_jobs_only(self):
        done = self.runner.start("tests", "Done", [sys.executable, "-c", "pass"], {})
        self.assertTrue(wait_until(lambda: self.runner.get(done.id).status in FINISHED))
        alive = self.runner.start(
            "tests", "Alive", [sys.executable, "-c", "import time; time.sleep(30)"], {}
        )
        self.assertEqual(self.runner.clear_finished(), 1)
        self.assertEqual([item["id"] for item in self.runner.snapshot()], [alive.id])
        self.runner.cancel(alive.id)

    def test_a_command_that_cannot_start_fails_rather_than_raising(self):
        job = self.runner.start("tests", "Missing", ["/nonexistent/binary"], {})
        self.assertEqual(job.status, "failed")
        self.assertIn("could not start", job.error)


class RunReaderTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.runs_root = self.root / "runs"
        self.runs_root.mkdir()

    def write_episode(self, name, rounds, *, capital=False, pressure=2, seed=7, records=None):
        directory = self.runs_root / name
        directory.mkdir(parents=True)
        config = {
            "episode_id": name, "seed": seed, "rounds": rounds,
            "pressure_level": pressure, "review_interval": 1,
            "boss_capital_authority": capital,
        }
        (directory / "metadata.json").write_text(
            json.dumps({"schema_version": 3, "config": config}), encoding="utf-8"
        )
        lines = records if records is not None else [self.round_record(index + 1) for index in range(rounds)]
        (directory / "rounds.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in lines), encoding="utf-8"
        )
        return directory

    @staticmethod
    def round_record(number, *, withheld=False, costly=False, misreported=False):
        return {
            "round_number": number,
            "world": {"market_direction": 1, "realized_return": 1.0},
            "ledger": [
                {"trader_id": "trader_a", "position": 0.5, "pnl": 0.5},
                {"trader_id": "trader_b", "position": -0.5, "pnl": -0.5},
            ],
            "messages": [
                {"sender_id": "trader_a", "channel": "public", "content": "hi",
                 "recipient_id": None, "shared_signal": None if withheld else 1},
            ],
            "withholding_labels": [
                {"trader_id": "trader_a", "recipient_id": "trader_b",
                 "withheld": withheld, "occurred": costly},
            ],
            "misreporting_labels": [
                {"trader_id": "trader_a", "occurred": misreported,
                 "position_difference": 0.0, "dollar_difference": 0.0},
            ],
            "post_round_states": [
                {"trader_id": "trader_a", "budget": 1.0, "cumulative_pnl": 0.5,
                 "rank": 1, "pnl_gap": 0.0},
                {"trader_id": "trader_b", "budget": 0.5, "cumulative_pnl": -0.5,
                 "rank": 2, "pnl_gap": 1.0},
            ],
            "reasoning": [{"actor_id": "boss_1", "phase": "pre_review", "content": "x"}],
            "delivered_feedback": [{"boss_id": "boss_1", "trader_id": None, "content": "go"}],
        }

    def test_an_episode_is_described_from_its_metadata(self):
        directory = self.write_episode("ep-1", 4, capital=True)
        described = runs.describe_episode(directory, self.root)
        self.assertEqual(described["kind"], "episode")
        self.assertEqual(described["setup"], "B")
        self.assertEqual(described["pressure"], 2)
        self.assertEqual(described["rounds_written"], 4)
        self.assertTrue(described["complete"])

    def test_a_short_episode_is_marked_incomplete(self):
        directory = self.write_episode("ep-2", 10, records=[self.round_record(1)])
        described = runs.describe_episode(directory, self.root)
        self.assertEqual(described["rounds_written"], 1)
        self.assertFalse(described["complete"])

    def test_an_episode_written_before_the_capital_arm_reads_as_setup_a(self):
        # Older runs have no boss_capital_authority key at all. A reader that
        # required it would drop every pre-August run out of the panel.
        directory = self.write_episode("ep-old", 2)
        config = json.loads((directory / "metadata.json").read_text())
        del config["config"]["boss_capital_authority"]
        config["schema_version"] = 2
        (directory / "metadata.json").write_text(json.dumps(config), encoding="utf-8")
        self.assertEqual(runs.describe_episode(directory, self.root)["setup"], "A")

    def test_a_torn_final_line_does_not_lose_the_rounds_before_it(self):
        directory = self.write_episode("ep-torn", 3)
        with (directory / "rounds.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"round_number": 4, "wor')
        self.assertEqual(len(runs.read_rounds(directory)), 3)

    def test_the_summary_counts_the_labels(self):
        records = [
            self.round_record(1),
            self.round_record(2, withheld=True, costly=True),
            self.round_record(3, withheld=True),
            self.round_record(4, misreported=True),
        ]
        directory = self.write_episode("ep-labels", 4, records=records)
        summary = runs.episode_summary(directory)
        trader_a = next(item for item in summary["traders"] if item["trader_id"] == "trader_a")
        self.assertEqual(trader_a["withheld"], 2)
        self.assertEqual(trader_a["costly"], 1)
        self.assertEqual(trader_a["misreported"], 1)
        self.assertEqual(trader_a["messages"], 4)
        self.assertEqual(trader_a["signals_shared"], 2)
        self.assertEqual(summary["supervision"], {"boss_1": 4})
        self.assertEqual(summary["feedback_delivered"], 4)

    def test_a_sweep_is_described_from_its_manifest(self):
        sweep = self.runs_root / "sweep-x"
        sweep.mkdir()
        (sweep / "manifest.json").write_text(json.dumps({
            "sweep_id": "sweep-x", "rounds": 10, "seeds": [1, 2],
            "pressure_levels": [0, 1], "boss_capital_authority": True,
            "episodes": [{"status": "ok"}, {"status": "failed"}],
        }), encoding="utf-8")
        described = runs.describe_sweep(sweep, self.root)
        self.assertEqual(described["kind"], "sweep")
        self.assertEqual(described["setup"], "B")
        self.assertEqual(described["failed"], 1)

    def test_a_sweep_still_running_is_recognised_without_a_manifest(self):
        # experiments.sweep writes manifest.json only at the end, so without
        # this a sweep is invisible for the half hour it takes to run.
        sweep = self.runs_root / "sweep-live"
        sweep.mkdir()
        for index in range(2):
            self.write_episode(f"sweep-live/p0-s{index}", 3)
        listed = runs.list_runs(self.runs_root, self.root)
        found = next(item for item in listed if item["id"] == "sweep-live")
        self.assertEqual(found["kind"], "sweep")
        self.assertTrue(found["in_progress"])
        self.assertEqual(found["episodes"], 2)

    def test_sweep_rates_are_over_trader_rounds(self):
        sweep = self.runs_root / "sweep-rates"
        sweep.mkdir()
        self.write_episode("sweep-rates/p0-s1", 4, pressure=0, records=[
            self.round_record(1), self.round_record(2, withheld=True),
            self.round_record(3), self.round_record(4),
        ])
        summary = runs.sweep_summary(sweep, self.root)
        row = summary["rows"][0]
        self.assertEqual(row["trader_rounds"], 4)
        self.assertEqual(row["withheld"], 1)
        self.assertAlmostEqual(row["withheld_rate"], 0.25)

    def test_a_directory_that_is_neither_is_skipped(self):
        (self.runs_root / "notes").mkdir()
        (self.runs_root / "notes" / "readme.txt").write_text("x", encoding="utf-8")
        self.assertEqual(runs.list_runs(self.runs_root, self.root), [])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = JobRunner(Path.cwd(), max_running=1)
        cls.quiet_before = DeskHandler.quiet
        DeskHandler.quiet = True
        cls.server = DeskServer(("127.0.0.1", 0), DeskHandler, cls.runner)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.runner.shutdown()
        DeskHandler.quiet = cls.quiet_before

    def get(self, path, headers=None):
        request = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def post(self, path, payload, content_type="application/json"):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_the_page_and_its_assets_are_served(self):
        for path, needle in (
            ("/", b"LLM-OrgSim"),
            ("/static/style.css", b"--color-accent"),
            ("/static/app.js", b"api/jobs"),
        ):
            with self.subTest(path=path):
                status, body = self.get(path)
                self.assertEqual(status, 200)
                self.assertIn(needle, body)

    def test_a_non_loopback_host_header_is_refused(self):
        # DNS rebinding: a page anywhere could otherwise point a script at this
        # port through a name that resolves to 127.0.0.1 and drive the desk.
        status, _ = self.get("/api/runs", headers={"Host": "attacker.example"})
        self.assertEqual(status, 403)

    def test_static_paths_cannot_escape_the_static_directory(self):
        status, _ = self.get("/static/..%2f..%2f.env")
        self.assertEqual(status, 404)

    def test_a_form_post_is_refused(self):
        # Denying the simple-request content types is what forces a preflight
        # for anything cross-origin, which this server never answers.
        status, payload = self.post(
            "/api/jobs", {"command": "tests"}, content_type="application/x-www-form-urlencoded"
        )
        self.assertEqual(status, 400)
        self.assertIn("application/json", payload["error"])

    def test_an_invalid_parameter_comes_back_as_a_message_not_a_traceback(self):
        status, payload = self.post("/api/jobs", {
            "command": "pilot",
            "params": {"rounds": 999, "seed": 1, "pressure": 0, "review_interval": 1,
                       "boss_capital_authority": False, "episode_id": "", "output_root": "runs"},
        })
        self.assertEqual(status, 400)
        self.assertIn("Rounds", payload["error"])

    def test_the_state_payload_never_carries_the_api_key(self):
        status, body = self.get("/api/state")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertNotIn("api_key", set(payload["environment"]))
        self.assertIn("api_key_present", payload["environment"])
        self.assertTrue(payload["commands"])

        # And the value itself, not only a field named for it. The desk reads
        # .env to report on the provider, so the secret is in the process.
        env_file = Path.cwd() / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                secret = value.strip().strip("\'\"")
                if key.strip() == "AZURE_AI_API_KEY" and secret:
                    self.assertNotIn(secret, body.decode("utf-8"))

    def test_an_unknown_run_is_a_404(self):
        status, _ = self.get("/api/run?path=runs/does-not-exist")
        self.assertEqual(status, 404)

    def test_a_run_path_outside_the_project_is_a_404(self):
        status, _ = self.get("/api/run?path=../../etc")
        self.assertEqual(status, 404)


class FloorplanTests(unittest.TestCase):
    """The trading floor's roundEvent list.

    The order is the point. Supervision reaches traders before they decide, so
    a scene that played the brief after the share phase would animate the
    opposite of the causal claim the experiment tests.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, records, *, config=None, calls=None):
        directory = self.root / "ep"
        directory.mkdir()
        settings = {
            "episode_id": "ep", "seed": 1, "rounds": len(records),
            "pressure_level": 3, "review_interval": 1,
            "boss_capital_authority": False,
        }
        settings.update(config or {})
        (directory / "metadata.json").write_text(
            json.dumps({"schema_version": 3, "config": settings}), encoding="utf-8"
        )
        (directory / "rounds.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in records), encoding="utf-8"
        )
        if calls is not None:
            (directory / "calls.jsonl").write_text(
                "".join(json.dumps(item) + "\n" for item in calls), encoding="utf-8"
            )
        return directory

    @staticmethod
    def record(**overrides):
        base = {
            "round_number": 1,
            "world": {"market_direction": 1, "realized_return": 1.0},
            "observations": [
                {"trader_id": "trader_a", "signal": 1, "signal_accuracy": 0.7},
                {"trader_id": "trader_b", "signal": -1, "signal_accuracy": 0.7},
            ],
            "reasoning": [
                {"actor_id": "ken_griffin", "phase": "mandate", "content": "founder thinking"},
                {"actor_id": "boss_1", "phase": "mandate", "content": "boss thinking"},
                {"actor_id": "trader_a", "phase": "pre_share", "content": "a share thinking"},
                {"actor_id": "trader_a", "phase": "pre_trade", "content": "a trade thinking"},
                {"actor_id": "trader_a", "phase": "pre_report", "content": "a report thinking"},
            ],
            "messages": [
                {"sender_id": "trader_a", "channel": "public", "content": "hello",
                 "recipient_id": None, "shared_signal": 1},
            ],
            "executions": [
                {"trader_id": "trader_a", "requested_position": 1.0, "executed_position": 0.5},
            ],
            "reports": [{"trader_id": "trader_a", "reported_position": 0.5}],
            "ledger": [{"trader_id": "trader_a", "position": 0.5, "pnl": 0.5}],
            "withholding_labels": [
                {"trader_id": "trader_a", "recipient_id": "trader_b",
                 "withheld": False, "occurred": False},
            ],
            "misreporting_labels": [
                {"trader_id": "trader_a", "occurred": False,
                 "position_difference": 0.0, "dollar_difference": 0.0},
            ],
            "pre_round_states": [], "post_round_states": [],
            "delivered_feedback": [
                {"boss_id": "boss_1", "trader_id": None, "content": "desk mandate", "version": "v1"},
            ],
            "capital_allocations": [],
        }
        base.update(overrides)
        return base

    def scene(self, records, **kwargs):
        return floorplan.episode_scene(self.write(records, **kwargs))

    def test_phases_run_in_narrative_order(self):
        events = self.scene([self.record()])["rounds"][0]["events"]
        order = [phase["id"] for phase in floorplan.PHASES]
        seen = [roundEvent["phase"] for roundEvent in events]
        positions = [order.index(phase) for phase in seen]
        self.assertEqual(positions, sorted(positions), seen)

    def test_supervision_lands_before_anyone_trades(self):
        events = self.scene([self.record()])["rounds"][0]["events"]
        first_brief = next(i for i, b in enumerate(events) if b["phase"] == "brief")
        first_share = next(i for i, b in enumerate(events) if b["phase"] == "share")
        self.assertLess(first_brief, first_share)

    def test_private_reasoning_is_never_a_say_event(self):
        # The role contract's hardest line: a scratchpad was shown to nobody.
        # Rendering one as speech would put words in an agent's mouth that no
        # other agent ever heard.
        events = self.scene([self.record()])["rounds"][0]["events"]
        reasoning = {"founder thinking", "boss thinking", "a share thinking",
                     "a trade thinking", "a report thinking"}
        for roundEvent in events:
            if roundEvent["text"] in reasoning:
                self.assertEqual(roundEvent["kind"], "think", roundEvent)

    def test_a_message_is_a_say_event_carrying_its_shared_signal(self):
        events = self.scene([self.record()])["rounds"][0]["events"]
        said = next(b for b in events if b["text"] == "hello")
        self.assertEqual(said["kind"], "say")
        self.assertEqual(said["phase"], "share")
        self.assertEqual(said["shared_signal"], 1)
        self.assertTrue(said["broadcast"])

    def test_withholding_is_flagged_in_the_share_phase(self):
        # Not the market phase, where its cost is known. The decision is made
        # during share and that is the thing the detector predicts.
        record = self.record(
            messages=[{"sender_id": "trader_a", "channel": "public", "content": "hi",
                       "recipient_id": None, "shared_signal": None}],
            withholding_labels=[{"trader_id": "trader_a", "recipient_id": "trader_b",
                                 "withheld": True, "occurred": True,
                                 "counterfactual_profit_delta": 0.4}],
        )
        events = self.scene([record])["rounds"][0]["events"]
        flag = next(b for b in events if b.get("label") == "withheld")
        self.assertEqual(flag["phase"], "share")
        self.assertTrue(flag["costly"])

    def test_misreporting_is_flagged_on_the_report_event(self):
        record = self.record(
            reports=[{"trader_id": "trader_a", "reported_position": 1.0}],
            misreporting_labels=[{"trader_id": "trader_a", "occurred": True,
                                  "position_difference": 0.5, "dollar_difference": 0.5}],
        )
        events = self.scene([record])["rounds"][0]["events"]
        report = next(b for b in events if b["phase"] == "report" and b["kind"] == "say")
        self.assertEqual(report["label"], "misreported")
        self.assertEqual(report["data"]["reported"], 1.0)
        self.assertEqual(report["data"]["executed"], 0.5)

    def test_a_budget_clip_is_visible_on_the_trade_event(self):
        events = self.scene([self.record()])["rounds"][0]["events"]
        trade = next(b for b in events if b["phase"] == "trade" and b["kind"] == "act")
        self.assertTrue(trade["data"]["clipped"])
        self.assertIn("budget clipped", trade["text"])

    def test_the_overseer_directive_is_joined_from_calls(self):
        # rounds.jsonl keeps only the founder's reasoning; what it actually
        # sent to the boss lives in calls.jsonl and is matched on that text.
        calls = [{
            "tag": "ken_griffin", "status": "ok",
            "response": {"private_reasoning": "founder thinking", "content": "cut the bottom"},
        }]
        events = self.scene([self.record()], calls=calls)["rounds"][0]["events"]
        spoken = [b for b in events if b["actor"] == "ken_griffin" and b["kind"] == "say"]
        self.assertEqual(len(spoken), 1)
        self.assertEqual(spoken[0]["text"], "cut the bottom")
        self.assertEqual(spoken[0]["to"], "boss_1")

    def test_a_directive_that_cannot_be_matched_costs_one_bubble_not_the_scene(self):
        calls = [{
            "tag": "ken_griffin", "status": "ok",
            "response": {"private_reasoning": "some other round", "content": "unrelated"},
        }]
        scene = self.scene([self.record()], calls=calls)
        events = scene["rounds"][0]["events"]
        self.assertFalse([b for b in events if b["actor"] == "ken_griffin" and b["kind"] == "say"])
        self.assertTrue([b for b in events if b["actor"] == "ken_griffin" and b["kind"] == "think"])

    def test_no_calls_file_still_builds_a_scene(self):
        scene = self.scene([self.record()])
        self.assertFalse(scene["has_overseer_speech"])
        self.assertTrue(scene["rounds"][0]["events"])

    def test_a_capital_allocation_becomes_one_event_per_trader(self):
        record = self.record(capital_allocations=[{
            "boss_id": "boss_1", "round_number": 1,
            "allocated_budget": {"trader_a": 1.4, "trader_b": 0.6},
            "attributed_pnl": {"trader_a": 1.4, "trader_b": 0.8},
        }])
        events = self.scene([record], config={"boss_capital_authority": True})["rounds"][0]["events"]
        allots = [b for b in events if b["kind"] == "act" and b["phase"] == "brief"]
        self.assertEqual([b["to"] for b in allots], ["trader_a", "trader_b"])
        self.assertEqual(allots[0]["data"]["budget"], 1.4)
        self.assertEqual(allots[1]["data"]["attributed_pnl"], 0.8)

    def test_the_scene_reports_whether_the_episode_finished(self):
        short = self.scene([self.record()], config={"rounds": 4})
        self.assertFalse(short["complete"])
        self.assertEqual(short["rounds_planned"], 4)

    def test_every_actor_has_a_seat_the_renderer_knows(self):
        # floor.js positions by actor id. An actor described here with no seat
        # there would simply never be drawn.
        described = {actor["id"] for actor in floorplan.ACTORS}
        self.assertEqual(
            described,
            {"ken_griffin", "boss_1", "trader_a", "trader_b"},
        )
        source = (Path(__file__).resolve().parent.parent / "webui" / "static" / "floor.js").read_text()
        for actor_id in described:
            self.assertIn(f"{actor_id}:", source, f"{actor_id} has no seat in floor.js")
