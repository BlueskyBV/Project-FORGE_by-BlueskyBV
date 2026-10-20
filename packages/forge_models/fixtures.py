"""A deterministic provider that replays recorded responses.

This is what lets the AI layer have a test suite at all. Every test of the
orchestrator, the roles, the repair loop and the CLI runs against recorded
responses: free, offline, and identical on every run. A test that calls a real
model is not a test, it is a sample.

Two modes:

**Replay** looks a response up by the request's fingerprint. A miss is an error,
not a fallback -- because the usual cause of a miss is that someone changed a
prompt, and silently answering from a nearby fixture would let a changed prompt
pass tests it was never run against.

**Record** wraps a live provider, passes calls through, and writes each
request/response pair to disk. Re-recording after an intentional prompt change is
one command; that is deliberate, so keeping fixtures honest is cheaper than
working around them.

A fixture stores the full request alongside the response. That costs disk and
buys something worth more: a fixture file is a readable record of exactly what
was asked and what came back, so a reviewer can see whether a prompt is doing
what its author believes.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import FixtureMissingError
from .provider import Budget, Provider, RetryPolicy
from .types import ModelRequest, ModelResponse, ProviderInfo, StopReason, Usage


@dataclass(frozen=True, slots=True)
class Fixture:
    """One recorded exchange."""

    fingerprint: str
    purpose: str
    request: Mapping[str, Any]
    response: Mapping[str, Any]
    recorded_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "purpose": self.purpose,
            "recorded_at": self.recorded_at,
            "request": dict(self.request),
            "response": dict(self.response),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Fixture":
        return cls(
            fingerprint=str(payload["fingerprint"]),
            purpose=str(payload.get("purpose", "")),
            request=payload.get("request", {}),
            response=payload.get("response", {}),
            recorded_at=float(payload.get("recorded_at", 0.0)),
        )


class FixtureLibrary:
    """A directory of fixture files, indexed by request fingerprint."""

    __slots__ = ("_directory", "_by_fingerprint")

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        self._by_fingerprint: dict[str, Fixture] = {}
        self.reload()

    def reload(self) -> None:
        self._by_fingerprint.clear()
        if not self._directory.is_dir():
            return
        for path in sorted(self._directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise ValueError(f"fixture {path} is not valid JSON: {error}") from error
            fixture = Fixture.from_dict(payload)
            self._by_fingerprint[fixture.fingerprint] = fixture

    def __len__(self) -> int:
        return len(self._by_fingerprint)

    def __contains__(self, fingerprint: str) -> bool:
        return fingerprint in self._by_fingerprint

    def get(self, fingerprint: str) -> Fixture | None:
        return self._by_fingerprint.get(fingerprint)

    def purposes(self) -> tuple[str, ...]:
        return tuple(sorted({f.purpose for f in self._by_fingerprint.values()}))

    def add(self, fixture: Fixture) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        stem = f"{fixture.purpose or 'call'}-{fixture.fingerprint[:12]}"
        path = self._directory / f"{stem}.json"
        # Deliberately *not* sort_keys. Sorted files diff more prettily, and the
        # price is that replay stops working past the first call in a chain: the
        # recorded answer feeds the next prompt, so reordering its keys changes
        # that prompt's text and therefore its fingerprint. A fixture has to be
        # a faithful record of what came back, byte for byte, not a tidied one.
        path.write_text(
            json.dumps(fixture.as_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        self._by_fingerprint[fixture.fingerprint] = fixture
        return path


class FixtureProvider(Provider):
    """Replays recorded responses. Deterministic, free and offline."""

    def __init__(
        self,
        library: FixtureLibrary | str | Path,
        *,
        model: str = "fixture",
        budget: Budget | None = None,
    ) -> None:
        super().__init__(retry=RetryPolicy(max_attempts=1), budget=budget)
        self._library = (
            library
            if isinstance(library, FixtureLibrary)
            else FixtureLibrary(library)
        )
        self._model = model

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="fixture",
            model=self._model,
            supports_structured_output=True,
            is_remote=False,
        )

    @property
    def library(self) -> FixtureLibrary:
        return self._library

    def _send(self, request: ModelRequest) -> ModelResponse:
        fingerprint = request.fingerprint()
        fixture = self._library.get(fingerprint)
        if fixture is None:
            raise FixtureMissingError(
                "no recorded response matches this request",
                fingerprint=fingerprint,
                purpose=request.purpose,
                known_purposes=list(self._library.purposes()),
                fixture_count=len(self._library),
                hint="the prompt almost certainly changed. Re-record with "
                "`forge design --record DIR`, rather than loosening how "
                "fixtures are matched.",
            )
        response = fixture.response
        usage_block = response.get("usage", {}) or {}
        return ModelResponse(
            text=str(response.get("text", "")),
            structured=response.get("structured"),
            usage=Usage(
                input_tokens=int(usage_block.get("input_tokens", 0)),
                output_tokens=int(usage_block.get("output_tokens", 0)),
            ),
            provider="fixture",
            model=str(response.get("model", self._model)),
            stop_reason=StopReason(
                str(response.get("stop_reason", StopReason.COMPLETE.value))
            ),
            latency_seconds=0.0,
            request_fingerprint=fingerprint,
            response_id=str(response.get("response_id", "")),
            from_fixture=True,
        )


class RecordingProvider(Provider):
    """Passes calls through to a real provider and records them."""

    def __init__(
        self,
        inner: Provider,
        library: FixtureLibrary | str | Path,
    ) -> None:
        super().__init__(retry=inner.retry, budget=inner.budget)
        self._inner = inner
        self._library = (
            library
            if isinstance(library, FixtureLibrary)
            else FixtureLibrary(library)
        )

    @property
    def info(self) -> ProviderInfo:
        return self._inner.info

    @property
    def library(self) -> FixtureLibrary:
        return self._library

    def _send(self, request: ModelRequest) -> ModelResponse:
        response = self._inner._send(request)  # noqa: SLF001 - deliberate delegation
        self._library.add(
            Fixture(
                fingerprint=request.fingerprint(),
                purpose=request.purpose or "call",
                request={
                    "system": request.system,
                    "messages": [m.as_dict() for m in request.messages],
                    "schema_name": request.schema_name,
                    "temperature": request.temperature,
                    "max_output_tokens": request.max_output_tokens,
                },
                response={
                    "text": response.text,
                    "structured": response.structured,
                    "model": response.model,
                    "stop_reason": response.stop_reason.value,
                    "response_id": response.response_id,
                    "usage": response.usage.as_dict(),
                },
                recorded_at=time.time(),
            )
        )
        return response


class ScriptedProvider(Provider):
    """Returns queued responses in order, for unit tests of control flow.

    Distinct from :class:`FixtureProvider`: this one ignores the request
    entirely, which is exactly what a test of the repair loop wants -- "fail,
    fail, then succeed" -- without having to construct matching fingerprints for
    prompts that the test does not care about.
    """

    def __init__(
        self,
        responses: list[Mapping[str, Any] | Exception],
        *,
        model: str = "scripted",
        budget: Budget | None = None,
    ) -> None:
        super().__init__(retry=RetryPolicy(max_attempts=1), budget=budget)
        self._responses = list(responses)
        self._model = model
        self.requests: list[ModelRequest] = []

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="scripted",
            model=self._model,
            supports_structured_output=True,
            is_remote=False,
        )

    @property
    def exhausted(self) -> bool:
        return not self._responses

    def _send(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self._responses:
            raise FixtureMissingError(
                "the scripted provider ran out of responses",
                calls_made=len(self.requests),
                purpose=request.purpose,
            )
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        # `_stop_reason` scripts how the answer ended -- a truncation, say --
        # and is not part of the answer.
        stop = StopReason(str(item.get("_stop_reason",
                                       StopReason.TOOL_USE.value)))
        if "_stop_reason" in item:
            item = {k: v for k, v in item.items() if k != "_stop_reason"}
        return ModelResponse(
            text=str(item.get("_text", "")),
            structured=item,
            usage=Usage(input_tokens=100, output_tokens=200),
            provider="scripted",
            model=self._model,
            stop_reason=stop,
            latency_seconds=0.0,
            request_fingerprint=request.fingerprint(),
            from_fixture=True,
        )


__all__ = [
    "Fixture",
    "FixtureLibrary",
    "FixtureProvider",
    "RecordingProvider",
    "ScriptedProvider",
]
