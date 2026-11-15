"""Provider-neutral message, request and response types.

No provider SDK type reaches the rest of Forge. A role asks for a completion and
gets back a :class:`ModelResponse`; whether that came from Anthropic, from an
OpenAI-compatible endpoint, from a local model or from a recorded fixture is a
configuration detail and never a code path in the engineering layers.

That boundary is worth the extra types for two reasons beyond portability. It
lets the whole test suite run against a deterministic fixture provider, free and
offline. And it makes the *usage* of a model an explicit, accountable thing: a
run records which provider answered, how many tokens it cost, how long it took,
and whether design data left the machine.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping, Sequence

Role = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of a conversation."""

    role: Role
    content: str
    #: Pictures sent with the text, as PNG bytes: the part as built, so the
    #: model sees what it made. Sent only to a provider that can look at
    #: them (`ProviderInfo.supports_images`); every other drops them.
    images: tuple[bytes, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.images:
            # A digest, not the pixels: what makes a request this request,
            # for fixtures and logs, without megabytes of base64 in them.
            import hashlib

            payload["images"] = [hashlib.blake2b(image, digest_size=8).hexdigest()
                                 for image in self.images]
        return payload


@dataclass(frozen=True, slots=True)
class Usage:
    """What a call consumed.

    ``cost_usd`` is an *estimate* computed from a local price table, and is
    labelled as such wherever it is reported. Prices change and the table will
    drift; the token counts are the authoritative figures.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        if not isinstance(other, Usage):
            return NotImplemented
        costs = [c for c in (self.cost_usd, other.cost_usd) if c is not None]
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=(
                self.cached_input_tokens + other.cached_input_tokens
            ),
            cost_usd=sum(costs) if costs else None,
        )

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }
        if self.cached_input_tokens:
            payload["cached_input_tokens"] = self.cached_input_tokens
        if self.cost_usd is not None:
            payload["estimated_cost_usd"] = round(self.cost_usd, 6)
        return payload


class StopReason(Enum):
    COMPLETE = "complete"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    TOOL_USE = "tool_use"
    REFUSAL = "refusal"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """A completion request, independent of any provider.

    When ``schema`` is set the provider must return JSON conforming to it, by
    whatever mechanism it offers -- tool use, a structured-output parameter, or
    a JSON mode. Roles always set it: free-form prose from a model is not
    something the deterministic layers can consume.
    """

    system: str
    messages: tuple[Message, ...]
    schema: Mapping[str, Any] | None = None
    schema_name: str = "result"
    schema_description: str = ""
    max_output_tokens: int = 8192
    temperature: float = 0.0
    stop_sequences: tuple[str, ...] = ()
    #: Freeform label for logs and fixtures, e.g. "forgeir_designer".
    purpose: str = ""
    #: How much a model that thinks should put into this answer -- "low",
    #: "medium", "high" -- or "" for the provider's default. A hint: a
    #: provider that cannot vary it ignores it.
    effort: str = ""

    def fingerprint(self) -> str:
        """A stable hash of everything that determines the answer.

        This is the fixture provider's lookup key, and it is what makes a
        recorded conversation replayable: the same request produces the same
        key, and a changed prompt produces a different one rather than silently
        replaying a stale response.
        """
        payload = {
            "system": self.system,
            "messages": [m.as_dict() for m in self.messages],
            "schema": self.schema,
            "schema_name": self.schema_name,
            # The tool's description goes on the wire with the schema and
            # changes what the model is told; left out, editing a role's
            # `schema_description()` replayed the fixture recorded against
            # the old words.
            "schema_description": self.schema_description,
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "stop": list(self.stop_sequences),
        }
        if self.effort:
            payload["effort"] = self.effort
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).hexdigest()

    def approximate_prompt_tokens(self) -> int:
        """The prose half of the request: system prompt and messages."""
        characters = len(self.system) + sum(len(m.content) for m in self.messages)
        return characters // 4

    def approximate_schema_tokens(self) -> int:
        """The output schema, which is sent to the model and costs input.

        Every provider here puts the schema on the wire -- as a tool's
        parameters, as ``response_format``, or inlined into the system prompt
        -- so it is part of what has to fit. For the designer it is the *larger*
        half: 10,900 tokens of ForgeIR document schema against a 5,800-token
        prompt.
        """
        if self.schema is None:
            return 0
        return len(json.dumps(self.schema, separators=(",", ":"))) // 4

    def approximate_input_tokens(self) -> int:
        """A rough pre-flight estimate, for budget checks before spending.

        Deliberately crude -- four characters per token -- because its only job
        is to catch a request that is obviously far too large before it is sent.
        The provider's reported counts are what get recorded.

        It used to count the prompt and not the schema, which made it blind to
        65% of a designer request. The fit check built on it therefore passed a
        request of 15,300 tokens as if it were 5,800, Ollama silently dropped
        the overflow, and the model wrote a document against instructions whose
        second half it never saw -- three identical failures, 82 minutes, and
        nothing in the run saying why.
        """
        return self.approximate_prompt_tokens() + self.approximate_schema_tokens()


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """What came back."""

    text: str
    structured: Mapping[str, Any] | None
    usage: Usage
    provider: str
    model: str
    stop_reason: StopReason
    latency_seconds: float
    request_fingerprint: str
    #: What the transport settled on the way in, one line per change.
    #: A provider that repairs an answer has to say so, or the record
    #: of what the model produced is quietly not what it produced.
    notes: tuple[str, ...] = ()
    response_id: str = ""
    attempts: int = 1
    from_fixture: bool = False
    created_at: float = field(default_factory=time.time)

    @property
    def is_truncated(self) -> bool:
        return self.stop_reason is StopReason.MAX_TOKENS

    def require_structured(self) -> Mapping[str, Any]:
        if self.structured is None:
            raise ValueError(
                "the provider returned no structured output for a request that "
                "required it"
            )
        return self.structured

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "stop_reason": self.stop_reason.value,
            "latency_s": round(self.latency_seconds, 3),
            "attempts": self.attempts,
            "from_fixture": self.from_fixture,
            "request_fingerprint": self.request_fingerprint,
            "response_id": self.response_id,
            "usage": self.usage.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """What a provider is and what it can do."""

    name: str
    model: str
    supports_structured_output: bool
    supports_system_prompt: bool = True
    #: Whether using this provider sends design data off the machine. Recorded on
    #: every run, because "did this design leave my workstation?" is a question
    #: a user is entitled to a definite answer to.
    is_remote: bool = True
    context_window: int | None = None
    #: Whether the output schema reached the endpoint intact: "exact",
    #: "reduced" (unsupported keywords dropped) or "collapsed" (unions and deep
    #: nesting replaced by free-form objects). Recorded because it changes how
    #: much of the contract the transport enforced -- never how much is checked.
    schema_fidelity: str = "exact"
    #: Whether the model can be shown pictures of the part.
    supports_images: bool = False
    #: How the model reasons before it answers: "adaptive", "enabled" (a
    #: token budget) or "off" -- recorded, because an answer written with no
    #: room to work it out is a different kind of answer.
    thinking: str = "off"
    #: How hard the model is asked to work (low to max), where the endpoint
    #: takes it; None for its default. Read by what records a measurement.
    effort: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self.model,
            "structured_output": self.supports_structured_output,
            "remote": self.is_remote,
            "context_window": self.context_window,
            "schema_fidelity": self.schema_fidelity,
            "thinking": self.thinking,
        }


def user(content: str, images: tuple[bytes, ...] = ()) -> Message:
    return Message("user", content, tuple(images))


def assistant(content: str) -> Message:
    return Message("assistant", content)


__all__ = [
    "Message",
    "ModelRequest",
    "ModelResponse",
    "ProviderInfo",
    "Role",
    "StopReason",
    "Usage",
    "user",
    "assistant",
]
