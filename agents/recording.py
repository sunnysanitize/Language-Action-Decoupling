# Records every model call and replays it later.
#
# docs/role_contract.md makes this an experimental invariant: "Every model call
# must be recorded with its complete prompt, raw response, model identifier,
# sampling settings, and call status, and must be replayable." This file is
# that guarantee.
#
# RecordingModelClient wraps any ModelClient and appends one JSON line per call
# to calls.jsonl. It is a decorator, not a new client, so it works for the
# trader today and for boss.py and kengriffin.py when they exist. Point it at
# the same run directory the episode writes to and one folder holds the whole
# episode: metadata.json, rounds.jsonl, calls.jsonl.
#
# Each call is written as it finishes rather than buffered to the end. A pilot
# that dies on round 3 because the model broke the response contract still
# leaves the offending call on disk, which is the situation this file exists
# for.
#
# What "raw response" means here. The ModelClient contract returns a parsed
# mapping, so on a successful call the recorded response is that mapping: it is
# exactly what the policy consumed, which is what replay needs. Verbatim text
# matters when parsing or validation failed, and that is carried by
# ModelResponseError.raw_response and recorded on the error path.
#
# The API key is never recorded. Only model, endpoint, and temperature are read
# off LLMSettings.
#
# Usage:
#   recorder = RecordingModelClient(
#       OpenAIChatModel(settings), "runs/pilot/calls.jsonl", settings, "trader_a"
#   )
#   policy = LLMTraderPolicy(model_client=recorder)
#
# Replaying that episode without touching the network:
#   calls = read_calls("runs/pilot/calls.jsonl")
#   policy = LLMTraderPolicy(model_client=ReplayModelClient(calls, "trader_a"))

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Any, Mapping, Optional, Sequence, Union

from agents.llm_trader import LLMSettings, ModelClient, ModelResponseError


SCHEMA_VERSION = 1


# One model call, start to finish.
#
# status is "ok" when the client returned a payload and "error" when it raised.
# response holds the parsed payload on success; raw_response holds verbatim
# text when a ModelResponseError carried it.
@dataclass(frozen=True)
class ModelCall:
    schema_version: int
    call_index: int
    tag: str
    status: str
    model: str
    endpoint: str
    temperature: Optional[float]
    system_prompt: str
    user_prompt: str
    response: Optional[dict]
    raw_response: Optional[str]
    error: Optional[str]
    started_at: float
    latency_seconds: float


class RecordingModelClient:
    def __init__(
        self,
        inner: ModelClient,
        path: Union[str, Path],
        settings: Optional[LLMSettings] = None,
        tag: str = "",
    ) -> None:
        self._inner = inner
        self._path = Path(path)
        self._tag = tag
        # Deliberately field by field. asdict(settings) would put the API key
        # into every line of the log.
        self._model = settings.model if settings is not None else "unknown"
        self._endpoint = settings.endpoint if settings is not None else "unknown"
        self._temperature = settings.temperature if settings is not None else None
        self._call_index = 0

    @property
    def path(self) -> Path:
        return self._path

    @property
    def call_count(self) -> int:
        return self._call_index

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Mapping[str, Any]:
        started_at = time.time()
        try:
            payload = self._inner.complete(system_prompt, user_prompt)
        except Exception as error:
            # A ModelResponseError carries the model's own text. Anything else
            # is usually a transport or provider failure, where the useful
            # detail is in the HTTP body.
            raw_response = getattr(error, "raw_response", None)
            if raw_response is None:
                raw_response = error_body(error)
            status_code = getattr(error, "status_code", None)
            described = f"{type(error).__name__}: {error}"
            if status_code is not None:
                described = f"{described} (status {status_code})"
            self._write(
                status="error",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=None,
                raw_response=raw_response,
                error=described,
                started_at=started_at,
            )
            raise
        self._write(
            status="ok",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=dict(payload),
            raw_response=None,
            error=None,
            started_at=started_at,
        )
        return payload

    def _write(
        self,
        status: str,
        system_prompt: str,
        user_prompt: str,
        response: Optional[dict],
        raw_response: Optional[str],
        error: Optional[str],
        started_at: float,
    ) -> None:
        call = ModelCall(
            schema_version=SCHEMA_VERSION,
            call_index=self._call_index,
            tag=self._tag,
            status=status,
            model=self._model,
            endpoint=self._endpoint,
            temperature=self._temperature,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response,
            raw_response=raw_response,
            error=error,
            started_at=started_at,
            latency_seconds=time.time() - started_at,
        )
        self._call_index += 1
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Opened and closed per call so the line is on disk before the next one
        # starts. A crashed pilot keeps everything up to the failure.
        with self._path.open("a", encoding="utf-8") as calls_file:
            # Not sort_keys. The order of the fields inside response is part of
            # the response contract -- private_reasoning has to come first, so
            # that the decision was sampled after the reasoning -- and sorting
            # would quietly rewrite it. A replayed call would then be rejected
            # for a field order the model never actually produced.
            calls_file.write(json.dumps(asdict(call)))
            calls_file.write("\n")


# Pulls the useful text out of a provider exception.
#
# An HTTP error from the OpenAI SDK stringifies to "Error code: 404" and stops
# there. The body is where the provider actually says why -- a retired
# endpoint, an unknown model name, an expired key all look identical without
# it. Read by duck typing rather than importing the SDK, so this stays true for
# whatever client is wrapped.
def error_body(error: BaseException) -> Optional[str]:
    body = getattr(error, "body", None)
    if body is not None:
        return body if isinstance(body, str) else json.dumps(body, default=str)
    response = getattr(error, "response", None)
    text = getattr(response, "text", None)
    return text if isinstance(text, str) and text else None


def read_calls(path: Union[str, Path]) -> list[ModelCall]:
    calls = []
    with Path(path).open("r", encoding="utf-8") as calls_file:
        for line in calls_file:
            line = line.strip()
            if line:
                calls.append(ModelCall(**json.loads(line)))
    return calls


# Replays a recorded episode without calling the model.
#
# Calls are matched by position within a tag, and the recorded prompt is checked
# against the prompt being asked for. That check is the point: a replay that
# runs to the end proves the episode is deterministic given the same responses,
# and a replay that raises has found real drift between the code and the run.
#
# Recorded failures are re-raised, so a replay reproduces a broken run as
# faithfully as a clean one.
class ReplayModelClient:
    def __init__(
        self,
        calls: Sequence[ModelCall],
        tag: str = "",
        check_prompts: bool = True,
    ) -> None:
        self._calls = [call for call in calls if call.tag == tag]
        self._tag = tag
        self._check_prompts = check_prompts
        self._index = 0

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Mapping[str, Any]:
        if self._index >= len(self._calls):
            raise ValueError(
                f"no recorded call {self._index} for tag {self._tag!r}: "
                "the replay asked for more calls than were recorded"
            )
        call = self._calls[self._index]
        self._index += 1

        if self._check_prompts and (
            call.system_prompt != system_prompt or call.user_prompt != user_prompt
        ):
            raise ValueError(
                f"replayed prompt does not match recorded call {call.call_index} "
                f"for tag {self._tag!r}: the run has diverged from the recording"
            )
        if call.status == "error":
            raise ModelResponseError(
                call.error or "recorded model call failed", call.raw_response
            )
        if call.response is None:
            raise ValueError(
                f"recorded call {call.call_index} succeeded but has no response"
            )
        return call.response
