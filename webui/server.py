# The control desk: a local HTTP server that starts the experiment commands
# and shows what is on disk.
#
#   python -m webui.server            # then open http://127.0.0.1:8765
#   python -m webui.server --port 9000 --open
#
# Stdlib only, no build step, no npm. The simulator and the core test suite
# are stdlib-only and the desk had no business being the thing that made this
# repo need a toolchain: `python -m webui.server` has to work in a checkout
# where nothing but the standard library is installed, even though the
# commands it launches may not.
#
# Security, because this endpoint starts processes:
#
#   * It binds 127.0.0.1 by default and warns loudly on any other host.
#   * Every request's Host header must name a loopback address. Without that
#     check, a page on the open internet could point a script at
#     http://127.0.0.1:8765 through a rebound DNS name and drive the desk in
#     the background of the browser that has it open.
#   * POST bodies must be application/json, which denies a cross-origin form
#     the simple-request exemption and forces a preflight this server never
#     answers.
#   * The browser never sends a command line. webui/commands.py owns the
#     whitelist and every parameter validator; this file only routes.
#   * AZURE_AI_API_KEY is reported as present or absent and never sent to the
#     page.

import argparse
import json
import os
import socket
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from webui import commands as command_table
from webui import floorplan
from webui import runs as run_reader
from webui.jobs import JobRunner


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_ROOT = Path(__file__).resolve().parent / "static"
RUNS_ROOT = PROJECT_ROOT / "runs"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"}

MAX_BODY_BYTES = 64 * 1024


def loads_env_report() -> dict:
    # Reads the same .env experiments.pilot reads, without importing the
    # openai client -- the desk must start on a checkout that has no
    # dependencies installed, and importing agents.llm_trader would end that.
    values = dict(os.environ)
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values.setdefault(key.strip(), value.strip().strip("'\""))
        except OSError:
            pass

    def has(module: str) -> bool:
        from importlib.util import find_spec

        try:
            return find_spec(module) is not None
        except (ImportError, ValueError):
            return False

    endpoint = values.get("AZURE_AI_ENDPOINT", "").strip()
    api_key_present = bool(values.get("AZURE_AI_API_KEY", "").strip())

    # The same check experiments.pilot would hit on its first call, run here so
    # the chip in the header is the truth rather than "a key and a URL are
    # both present". agents.llm_trader imports openai lazily, inside the two
    # methods that need it, so this import costs nothing on a bare checkout --
    # and reusing its constant is what stops the retired-host list from
    # existing twice and drifting.
    problem = ""
    if not api_key_present:
        problem = "AZURE_AI_API_KEY is not set"
    elif not endpoint:
        problem = "AZURE_AI_ENDPOINT is not set"
    else:
        try:
            from agents.llm_trader import check_endpoint_is_live

            check_endpoint_is_live(endpoint)
        except ValueError as error:
            problem = str(error)
        except ImportError:  # pragma: no cover - a checkout without agents/
            pass

    return {
        "endpoint": endpoint,
        "model": values.get("AZURE_AI_MODEL", ""),
        "api_version": values.get("AZURE_AI_API_VERSION", ""),
        # The key itself never leaves the process.
        "api_key_present": api_key_present,
        "provider_problem": problem,
        "env_file": env_path.exists(),
        "python": sys.version.split()[0],
        "interpreter": sys.executable,
        "packages": {
            "openai": has("openai"),
            "dotenv": has("dotenv"),
            "numpy": has("numpy"),
            "scipy": has("scipy"),
            "sklearn": has("sklearn"),
        },
        "project_root": str(PROJECT_ROOT),
    }


class DeskHandler(BaseHTTPRequestHandler):
    server_version = "MarketArenaDesk/1.0"
    protocol_version = "HTTP/1.1"
    quiet = False

    # ------------------------------------------------------------- plumbing

    # One line per request, on stderr, without the default's timestamp prefix.
    # log_request rather than log_message because it is handed the status code
    # as an argument instead of buried in a format string's varargs.
    def log_request(self, code="-", size="-") -> None:
        if self.quiet:
            return
        status = code.value if hasattr(code, "value") else code
        sys.stderr.write(f"  {self.command} {self.path} -> {status}\n")

    def log_message(self, format: str, *args) -> None:
        if not self.quiet:
            sys.stderr.write("  " + (format % args) + "\n")

    def _host_is_loopback(self) -> bool:
        host = (self.headers.get("Host") or "").strip()
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        if name.startswith("[") and "]" in name:
            name = name[: name.index("]") + 1]
        return name in LOOPBACK_HOSTS

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict:
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if content_type != "application/json":
            raise ValueError("Content-Type must be application/json")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"malformed JSON body: {error}") from None
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    # --------------------------------------------------------------- routing

    def do_GET(self) -> None:
        if not self._host_is_loopback():
            self._error(HTTPStatus.FORBIDDEN, "this desk only answers loopback hosts")
            return
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            self._route_get(route, query)
        except BrokenPipeError:  # pragma: no cover - the browser navigated away
            pass
        except Exception as error:  # pragma: no cover - last-resort guard
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(error).__name__}: {error}")

    def _route_get(self, route: str, query: dict) -> None:
        runner: JobRunner = self.server.runner

        if route == "/":
            self._serve_static("index.html")
            return
        if route.startswith("/static/"):
            self._serve_static(route[len("/static/"):])
            return

        if route == "/api/state":
            self._json(
                {
                    "commands": command_table.describe(),
                    "environment": loads_env_report(),
                    "runs": run_reader.list_runs(RUNS_ROOT, PROJECT_ROOT),
                    "jobs": runner.snapshot(),
                }
            )
            return
        if route == "/api/commands":
            self._json(command_table.describe())
            return
        if route == "/api/environment":
            self._json(loads_env_report())
            return
        if route == "/api/runs":
            self._json(run_reader.list_runs(RUNS_ROOT, PROJECT_ROOT))
            return
        if route == "/api/run":
            self._serve_run(query)
            return
        if route == "/api/scene":
            self._serve_scene(query)
            return
        if route == "/api/jobs":
            self._json(runner.snapshot())
            return
        if route.startswith("/api/jobs/") and route.endswith("/log"):
            job_id = route[len("/api/jobs/"): -len("/log")]
            offset = int((query.get("offset") or ["0"])[0])
            try:
                payload = runner.log(job_id, offset)
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, f"no such job: {job_id}")
                return
            payload["job"] = runner.describe(job_id)
            self._json(payload)
            return

        self._error(HTTPStatus.NOT_FOUND, f"no route for {route}")

    def do_POST(self) -> None:
        if not self._host_is_loopback():
            self._error(HTTPStatus.FORBIDDEN, "this desk only answers loopback hosts")
            return
        route = urlparse(self.path).path.rstrip("/") or "/"
        runner: JobRunner = self.server.runner
        try:
            body = self._body()
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))
            return

        try:
            if route == "/api/jobs":
                self._launch(runner, body)
                return
            if route.startswith("/api/jobs/") and route.endswith("/stop"):
                job_id = route[len("/api/jobs/"): -len("/stop")]
                try:
                    runner.cancel(job_id)
                except KeyError:
                    self._error(HTTPStatus.NOT_FOUND, f"no such job: {job_id}")
                    return
                self._json(runner.describe(job_id))
                return
            if route == "/api/jobs/clear":
                self._json({"cleared": runner.clear_finished()})
                return
        except BrokenPipeError:  # pragma: no cover
            return
        except Exception as error:  # pragma: no cover - last-resort guard
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(error).__name__}: {error}")
            return

        self._error(HTTPStatus.NOT_FOUND, f"no route for {route}")

    # --------------------------------------------------------------- actions

    def _launch(self, runner: JobRunner, body: dict) -> None:
        name = body.get("command", "")
        params = body.get("params", {})
        if not isinstance(params, dict):
            self._error(HTTPStatus.BAD_REQUEST, "params must be an object")
            return
        try:
            command, values, argv = command_table.build(name, params)
        except command_table.ParameterError as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))
            return

        # A pilot or sweep whose target directory already exists fails inside
        # EpisodeJSONLWriter after the process has started, which shows up as a
        # traceback in the console. Saying so here, before anything is spawned,
        # is the difference between a typo and a stack trace.
        conflict = self._existing_target(name, values)
        if conflict:
            self._error(
                HTTPStatus.CONFLICT,
                f"{conflict} already exists; pick another id or move it aside",
            )
            return

        try:
            job = runner.start(name, command.label, argv, values)
        except RuntimeError as error:
            self._error(HTTPStatus.TOO_MANY_REQUESTS, str(error))
            return
        self._json(runner.describe(job.id), HTTPStatus.ACCEPTED)

    def _existing_target(self, name: str, values: dict) -> Optional[str]:
        if name == "pilot" and values.get("episode_id"):
            target = PROJECT_ROOT / values["output_root"] / values["episode_id"]
        elif name == "sweep" and values.get("sweep_id"):
            target = PROJECT_ROOT / values["output_root"] / values["sweep_id"]
        else:
            return None
        return str(target.relative_to(PROJECT_ROOT)) if target.exists() else None

    def _serve_run(self, query: dict) -> None:
        raw = (query.get("path") or [""])[0]
        if not raw:
            self._error(HTTPStatus.BAD_REQUEST, "path is required")
            return
        directory = (PROJECT_ROOT / raw).resolve()
        if not directory.is_relative_to(PROJECT_ROOT) or not directory.is_dir():
            self._error(HTTPStatus.NOT_FOUND, f"no such run: {raw}")
            return
        if (directory / run_reader.EPISODE_MARKER).exists():
            self._json({"kind": "episode", **run_reader.episode_summary(directory)})
            return
        episodes = run_reader.sweep_episodes(directory, PROJECT_ROOT)
        if not episodes:
            self._error(HTTPStatus.NOT_FOUND, f"{raw} holds no episodes")
            return
        self._json(
            {
                "kind": "sweep",
                "id": directory.name,
                "episodes": episodes,
                "summary": run_reader.sweep_summary(directory, PROJECT_ROOT),
            }
        )

    # One episode, rebuilt as the ordered beats the trading floor acts out.
    # Episodes only: a sweep is sixty of these and there is nothing sensible to
    # animate for the collection.
    def _serve_scene(self, query: dict) -> None:
        raw = (query.get("path") or [""])[0]
        if not raw:
            self._error(HTTPStatus.BAD_REQUEST, "path is required")
            return
        directory = (PROJECT_ROOT / raw).resolve()
        if not directory.is_relative_to(PROJECT_ROOT) or not directory.is_dir():
            self._error(HTTPStatus.NOT_FOUND, f"no such run: {raw}")
            return
        if not (directory / run_reader.EPISODE_MARKER).exists():
            self._error(
                HTTPStatus.BAD_REQUEST,
                f"{raw} is a sweep, not an episode; open one of its episodes",
            )
            return
        self._json(floorplan.episode_scene(directory))

    def _serve_static(self, relative: str) -> None:
        # Resolve and then confirm containment, rather than scanning for "..".
        # The scan is the version that gets a clever encoding past it.
        candidate = (STATIC_ROOT / relative).resolve()
        if not candidate.is_relative_to(STATIC_ROOT) or not candidate.is_file():
            self._error(HTTPStatus.NOT_FOUND, f"no such file: {relative}")
            return
        content_type = CONTENT_TYPES.get(candidate.suffix, "application/octet-stream")
        self._send(HTTPStatus.OK, candidate.read_bytes(), content_type)


class DeskServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, runner: JobRunner) -> None:
        self.runner = runner
        super().__init__(address, handler)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve the MarketArena control desk on localhost."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--max-running",
        type=int,
        default=4,
        help="how many jobs may run at once from this desk",
    )
    parser.add_argument(
        "--open", action="store_true", help="open the desk in a browser"
    )
    arguments = parser.parse_args(argv)

    if arguments.host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            f"WARNING: binding {arguments.host} exposes a process launcher to "
            "anything that can reach this machine. Use 127.0.0.1 unless you "
            "have a reason not to.",
            file=sys.stderr,
        )

    runner = JobRunner(PROJECT_ROOT, max_running=arguments.max_running)
    try:
        server = DeskServer((arguments.host, arguments.port), DeskHandler, runner)
    except OSError as error:
        print(f"Cannot listen on {arguments.host}:{arguments.port}: {error}", file=sys.stderr)
        return 1

    host, port = server.server_address[0], server.server_address[1]
    url = f"http://{host}:{port}/"
    report = loads_env_report()
    print(f"MarketArena control desk on {url}")
    print(f"  project     {PROJECT_ROOT}")
    print(f"  interpreter {sys.executable}")
    print(f"  model       {report['model'] or '(unset)'}")
    if report["provider_problem"]:
        print(f"  provider    UNUSABLE -- live runs will fail:\n              {report['provider_problem']}")
    else:
        print(f"  provider    {report['endpoint']}")
    missing = [name for name, ok in report["packages"].items() if not ok]
    if missing:
        print(f"  missing     {', '.join(missing)} (some commands will fail)")
    print("Ctrl-C to stop.")

    if arguments.open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping. Cancelling any running jobs...")
    finally:
        runner.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
