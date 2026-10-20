"""OpenAI-compatible adapter, for local models and third-party endpoints.

Covers anything speaking the ``/v1/chat/completions`` shape: Ollama, vLLM,
llama.cpp's server, LM Studio, OpenAI itself. Also on the standard library.

The interesting part is structured output, because support for it varies more
than the endpoints do. Three mechanisms are tried in descending order of
reliability:

1. ``response_format: {"type": "json_schema", ...}`` -- genuine constrained
   decoding, where available.
2. Function calling with a forced tool choice.
3. ``response_format: {"type": "json_object"}`` plus the schema in the prompt.

Level 3 is a real step down and is labelled as such on the response, because a
model merely *asked* to follow a schema will sometimes not, and the caller should
know which guarantee it got. A local endpoint that reports level 3 will lean far
harder on the bounded repair loop, and that is a fact about the deployment worth
surfacing rather than smoothing over.
"""

from __future__ import annotations

import http.client
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Literal, Mapping, get_args

from .errors import (
    AuthenticationError,
    ConfigurationError,
    ContextTooLargeError,
    ModelError,
    RateLimitError,
    RequestError,
    RequestTimeoutError,
    StructuredOutputError,
    TransientError,
)
from .provider import Budget, Provider, RetryPolicy
from .schema_dialect import ReducedSchema, SchemaDialect, reduce_schema
from .types import ModelRequest, ModelResponse, ProviderInfo, StopReason, Usage

StructuredMode = Literal["json_schema", "tools", "json_object"]

_STOP_REASONS = {
    "stop": StopReason.COMPLETE,
    "length": StopReason.MAX_TOKENS,
    "tool_calls": StopReason.TOOL_USE,
    "function_call": StopReason.TOOL_USE,
    "content_filter": StopReason.REFUSAL,
}


def _rounded_up_minutes(seconds: float) -> int:
    """Round a duration up to a whole minute, for advice a human will retype."""
    return int(math.ceil(seconds / 60.0) * 60)


#: Schema dialects to fall back through, narrowest last, from each starting
#: point. `openapi` keeps widely-supported keywords; `opaque` also collapses
#: unions and deep nesting, which takes the designer's schema from 10,900
#: tokens to 600. Nothing is checked less strictly for it -- the document is
#: validated against the real schema when it comes back, whatever was sent.
_NARROWER_FROM: dict[str, tuple[str, ...]] = {
    "json_schema": ("json_schema", "openapi", "opaque"),
    "openapi": ("openapi", "opaque"),
    "opaque": ("opaque",),
}

#: Slack left for the estimate being wrong. Four characters per token is
#: generous on prose and mean on dense JSON, and being 5% optimistic at the
#: edge of the window costs a silent truncation.
_FIT_MARGIN = 512

#: Below this there is no point sending the request: a document the model
#: cannot finish is a truncation either way.
_OUTPUT_FLOOR = 1024

#: Room a refusal assumes the answer wants, when working out the context length
#: to recommend. The floor is what makes a request possible; this is what makes
#: it comfortable, and advice that lands you back at the floor is bad advice.
_COMFORTABLE_ANSWER = 4096


def _rounded_up_to_a_power_of_two(tokens: int) -> int:
    """The next 4096-aligned size, because that is how num_ctx is written."""
    block = 4096
    return max(block, ((tokens + block - 1) // block) * block)


class OpenAICompatibleProvider(Provider):
    """Talks to any endpoint implementing the OpenAI chat-completions shape."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://localhost:11434/v1",
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        structured_mode: StructuredMode = "json_schema",
        schema_dialect: SchemaDialect = "json_schema",
        timeout: float = 300.0,
        context_window: int | None = None,
        is_remote: bool = False,
        allow_schema_reduction: bool = True,
        retry: RetryPolicy | None = None,
        budget: Budget | None = None,
    ) -> None:
        super().__init__(retry=retry, budget=budget)
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or os.environ.get(api_key_env, "")
        self._structured_mode: StructuredMode = structured_mode
        self._schema_dialect: SchemaDialect = schema_dialect
        #: The most recent reduction, so a caller can report what was sent.
        self.last_reduction: ReducedSchema | None = None
        self._timeout = timeout
        self._context_window = context_window
        self._is_remote = is_remote
        #: When false, the dialect asked for is the dialect sent: a request
        #: that does not fit is refused, naming the context length that would
        #: hold it, rather than quietly costing fidelity to make room.
        self._allow_schema_reduction = allow_schema_reduction
        #: Output tokens and seconds accumulated over completed calls, so a
        #: timeout can be judged against the rate this endpoint actually runs
        #: at rather than against a guess.
        self._tokens_generated = 0
        self._seconds_generating = 0.0
        #: Reduced-schema sizes, per (schema, dialect). Reducing a 43 KB schema
        #: three times per request to measure it would cost more than it saves.
        self._schema_sizes: dict[tuple[int, str], int] = {}

    @property
    def observed_rate(self) -> float | None:
        """Output tokens per second, over the calls that have completed."""
        if self._tokens_generated <= 0 or self._seconds_generating <= 0.0:
            return None
        return self._tokens_generated / self._seconds_generating

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=f"openai-compatible ({self._structured_mode})",
            model=self._model,
            supports_structured_output=self._structured_mode != "json_object",
            is_remote=self._is_remote,
            context_window=self._context_window,
            schema_fidelity=(
                self.last_reduction.fidelity if self.last_reduction else "exact"
            ),
        )

    # ------------------------------------------------------------------
    def _build_payload(
        self,
        request: ModelRequest,
        *,
        dialect: SchemaDialect | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        system = request.system
        if request.schema is not None and self._structured_mode == "json_object":
            # Level 3: the schema has to travel in the prompt, because the
            # endpoint will only promise "some JSON".
            system = (
                f"{system}\n\n## Required output shape\n\n"
                "Reply with a single JSON object and nothing else. It must "
                "conform to this JSON Schema:\n\n"
                f"{json.dumps(dict(request.schema), indent=2)}"
            )
        if system:
            messages.append({"role": "system", "content": system})
        messages.extend({"role": m.role, "content": m.content}
                        for m in request.messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": (
                request.max_output_tokens
                if max_output_tokens is None
                else max_output_tokens
            ),
            "temperature": request.temperature,
        }
        if request.stop_sequences:
            payload["stop"] = list(request.stop_sequences)

        if request.schema is not None:
            # `submit_` prefix, deliberately: a tool named for the role reads
            # as something to delegate the work to, and a weak model will call
            # it with the input instead of with an answer.
            name = f"submit_{request.schema_name or 'result'}"
            reduction = reduce_schema(
                request.schema, dialect or self._schema_dialect
            )
            self.last_reduction = reduction
            schema = dict(reduction.schema)
            if self._structured_mode == "json_schema":
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": name,
                        "schema": schema,
                        "strict": False,
                    },
                }
            elif self._structured_mode == "tools":
                payload["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": (
                                request.schema_description
                                or "Return the result in exactly this structure."
                            ),
                            "parameters": schema,
                        },
                    }
                ]
                payload["tool_choice"] = {
                    "type": "function",
                    "function": {"name": name},
                }
            elif self._structured_mode == "json_object":
                payload["response_format"] = {"type": "json_object"}
            else:
                # Not a default. A misspelled mode silently falling through to
                # the weakest one is how a run ends up with prose-wrapped JSON
                # and a parse failure that looks like the model's fault.
                raise ConfigurationError(
                    f"unknown structured output mode '{self._structured_mode}'",
                    supported=list(get_args(StructuredMode)),
                )
        return payload

    def _plan_the_request(self, request: ModelRequest) -> tuple[SchemaDialect, int]:
        """Choose a schema dialect and an output reservation that both fit.

        A hosted API answers an over-long prompt with an error. A local runtime
        usually does not: it quietly drops the overflow and answers whatever is
        left. For Forge that is the worst possible behaviour -- the designer
        loses the back half of its authoring guide and produces a confident
        document written against instructions it never saw, and nothing in the
        run says so.

        Refusing was the first answer and it is not enough. The designer's
        schema is 10,900 tokens at full fidelity and 600 collapsed, so on a 16k
        local model the difference between "impossible" and "comfortable" is a
        flag nobody knew to pass. Given a known window, this narrows the schema
        as far as it must -- recording the fidelity it settled on, which the run
        reports -- and reserves for the answer what is actually left rather than
        a fixed figure larger than the whole window.

        Only planned when ``context_window`` is known, because guessing one
        would refuse or degrade requests that would have worked.
        """
        if self._context_window is None:
            return self._schema_dialect, request.max_output_tokens

        prompt = request.approximate_prompt_tokens()
        ladder = (
            _NARROWER_FROM.get(self._schema_dialect, (self._schema_dialect,))
            if self._allow_schema_reduction
            else (self._schema_dialect,)
        )
        attempts: list[tuple[str, int, int]] = []
        for dialect in ladder:
            schema_tokens = self._schema_tokens(request, dialect)
            room = self._context_window - prompt - schema_tokens - _FIT_MARGIN
            attempts.append((dialect, schema_tokens, room))
            if room >= _OUTPUT_FLOOR:
                return dialect, min(request.max_output_tokens, room)

        best = max(attempts, key=lambda a: a[2])
        answer = min(request.max_output_tokens, _COMFORTABLE_ANSWER)
        needed = _rounded_up_to_a_power_of_two(
            prompt + best[1] + _FIT_MARGIN + answer
        )
        held_back = (
            "the schema is pinned to "
            f"`{self._schema_dialect}` (--exact-schema), so it was not narrowed"
            if not self._allow_schema_reduction
            else f"even with the schema narrowed to {best[1]} tokens"
        )
        raise ContextTooLargeError(
            "this request cannot fit in the model's context window",
            estimated_prompt_tokens=prompt,
            estimated_schema_tokens=best[1],
            narrowest_schema_tried=best[0],
            room_left_for_the_answer=best[2],
            context_window=self._context_window,
            required_context_window=needed,
            purpose=request.purpose,
            hint=(
                f"{held_back}, the prompt for "
                f"{request.purpose or 'this role'} leaves {max(0, best[2])} "
                f"tokens for the answer, and it needs at least {_OUTPUT_FLOOR}."
                f" Set the runtime's context length to {needed} (in Ollama, "
                f"`PARAMETER num_ctx {needed}` in a Modelfile, then rebuild the "
                f"model) and pass --context-window {needed}. A local runtime "
                "would otherwise truncate the prompt silently and answer from "
                "the part it kept."
            ),
        )

    def _schema_tokens(self, request: ModelRequest, dialect: str) -> int:
        if request.schema is None:
            return 0
        # Keyed by content, not by `id()`: a role builds a fresh schema dict
        # per run, and once freed the next role's could land at the same
        # address and inherit a size measured on a different schema.
        import hashlib

        digest = hashlib.blake2b(
            json.dumps(request.schema, sort_keys=True,
                       separators=(",", ":")).encode("utf-8"),
            digest_size=12).hexdigest()
        key = (digest, dialect)
        cached = self._schema_sizes.get(key)
        if cached is None:
            reduced = reduce_schema(request.schema, dialect)  # type: ignore[arg-type]
            cached = len(json.dumps(reduced.schema, separators=(",", ":"))) // 4
            self._schema_sizes[key] = cached
        return cached

    def _send(self, request: ModelRequest) -> ModelResponse:
        dialect, output_tokens = self._plan_the_request(request)
        payload = self._build_payload(
            request, dialect=dialect, max_output_tokens=output_tokens
        )
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "user-agent": "forge/0.1.0",
        }
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"

        http_request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            method="POST",
            headers=headers,
        )

        started = time.perf_counter()
        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout) as handle:
                raw = handle.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise _classify_http_error(error) from error
        except TimeoutError as error:
            raise self._classify_timeout(request) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise self._classify_timeout(request) from error
            raise TransientError(
                "could not reach the endpoint",
                url=self._base_url,
                reason=str(error.reason),
                hint="for a local model, check the server is running and the "
                "base_url is right",
            ) from error
        except (OSError, http.client.HTTPException) as error:
            # Dropped while the answer was being read: retried, not a crash.
            raise TransientError(
                "the connection to the endpoint dropped",
                url=self._base_url,
                reason=f"{type(error).__name__}: {error}"[:300],
            ) from error
        latency = time.perf_counter() - started

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise TransientError(
                "the endpoint returned a body that is not JSON", preview=raw[:200]
            ) from error

        return self._parse(request, parsed, latency)

    def _no_structured_output(
        self,
        request: ModelRequest,
        finish: str,
        text: str,
        spent: Usage,
        raw_finish: Any,
    ) -> StructuredOutputError:
        """Three different faults wear "no structured output" as a face.

        The endpoint could not express the schema; the model answered in prose;
        or the answer was simply cut off at the token ceiling. The third was
        being reported as the second, with a hint recommending a different
        structured mode and a different model -- advice that cannot help,
        because nothing was wrong with the mode or the model. Observed live: a
        72-minute run spent three full generations being truncated at 4096
        tokens and told to try `--structured-mode json_schema`.
        """
        lowered = finish.lower()
        if "malformed_function_call" in lowered:
            return StructuredOutputError(
                "the endpoint could not build a call from this schema",
                # Retrying an identical request against an endpoint that cannot
                # express this schema fails identically, four times, slowly.
                retryable=False,
                mode=self._structured_mode,
                finish_reason=raw_finish,
                preview=text[:200],
                hint="this endpoint accepts only a subset of JSON Schema and "
                "could not build a function call from ours. Retry with "
                "--schema-dialect opaque, which collapses unions and deep "
                "nesting; the full contract is still enforced locally.",
            )

        if lowered in ("length", "max_tokens"):
            ceiling = request.max_output_tokens
            suggested = max(ceiling * 2, 8192)
            hint = (
                f"the answer was cut off at the {ceiling}-token ceiling, so "
                "the JSON is incomplete and there is nothing to parse. This "
                "is not a schema or tool-support problem, and retrying "
                "unchanged truncates at exactly the same place. Raise "
                f"--max-output-tokens to about {suggested}"
            )
            rate = self.observed_rate
            if rate:
                hint += (
                    f", and --timeout with it: at the {rate:.1f} tokens/second "
                    f"this endpoint is running, {suggested} tokens is about "
                    f"{suggested / rate / 60:.0f} minutes per attempt"
                )
            hint += "."
            return StructuredOutputError(
                "the reply was cut off at the output limit",
                # Identical request, identical ceiling, identical truncation.
                retryable=False,
                mode=self._structured_mode,
                finish_reason=raw_finish,
                max_output_tokens=ceiling,
                output_tokens=spent.output_tokens,
                characters_produced=len(text),
                preview=text[:200],
                hint=hint,
            )

        return StructuredOutputError(
            "the endpoint returned no parseable structured output",
            retryable=True,
            mode=self._structured_mode,
            finish_reason=raw_finish,
            preview=text[:200],
            hint="the reply contained no JSON object this could read. A model "
            "that narrates a tool call instead of making one is handled; a "
            "model that answers in prose alone is not. Try --structured-mode "
            "json_schema, or a model with tool support",
        )

    def _classify_timeout(self, request: ModelRequest) -> ModelError:
        """Say whether the endpoint stalled or is simply slower than the clock.

        Observed live: a local 3B model generating at 2.1 tokens a second was
        given a 4096-token ceiling and a 900-second timeout. Those numbers
        cannot both be met -- the ceiling alone needs 32 minutes -- so the call
        was killed at 15 minutes having done nothing wrong, and the user was
        left with a bare ``TimeoutError: timed out`` and no way to tell a slow
        model from a hung one. The arithmetic is right here; the error does it.
        """
        rate = self.observed_rate
        ceiling = request.max_output_tokens
        detail: dict[str, Any] = {"timeout_seconds": self._timeout}
        if rate is not None:
            detail["observed_tokens_per_second"] = round(rate, 2)
        if not (rate and ceiling):
            return RequestTimeoutError(
                "the endpoint did not answer in time",
                hint="if the model is local and simply slow, raise --timeout; "
                "if it is remote, this is usually a stall and a retry lands",
                **detail,
            )

        needed = ceiling / rate
        detail["max_output_tokens"] = ceiling
        detail["seconds_needed_at_that_rate"] = round(needed, 0)
        if needed <= self._timeout:
            # Fast enough on paper, so something actually went wrong. Retrying
            # is the right move.
            return RequestTimeoutError(
                "the endpoint stopped responding mid-generation",
                hint="the timeout is long enough for this token ceiling at the "
                "rate the earlier calls ran at, so this looks like a stall "
                "rather than a slow model",
                **detail,
            )
        return RequestTimeoutError(
            "the timeout is shorter than this model needs, not a stall",
            retryable=False,
            hint=(
                f"earlier calls ran at {rate:.1f} output tokens/second. At that "
                f"rate the {ceiling}-token ceiling needs about "
                f"{needed / 60:.0f} minutes, and --timeout is "
                f"{self._timeout / 60:.0f}. Raise --timeout to at least "
                f"{_rounded_up_minutes(needed * 1.25)} seconds, or lower "
                "--max-output-tokens. Retrying unchanged would fail the same "
                "way and cost another full timeout."
            ),
            **detail,
        )

    def _parse(
        self, request: ModelRequest, parsed: Mapping[str, Any], latency: float
    ) -> ModelResponse:
        choices = parsed.get("choices") or []
        if not choices:
            raise TransientError("the endpoint returned no choices")
        choice = choices[0]
        message = choice.get("message", {}) or {}

        text = message.get("content") or ""
        if isinstance(text, list):
            # Content as a list of parts, as some endpoints send it: the
            # text of each part, joined, rather than an AttributeError.
            text = "".join(
                str(part.get("text", "") or "") if isinstance(part, Mapping)
                else str(part or "") for part in text)
        text = str(text)
        structured: Mapping[str, Any] | None = None

        name = request.schema_name or "result"
        tool_calls = message.get("tool_calls") or []
        if tool_calls and isinstance(tool_calls[0], Mapping):
            function = tool_calls[0].get("function") or {}
            arguments = (function.get("arguments", "")
                         if isinstance(function, Mapping) else "")
            structured = _loads_or_none(arguments)
        if structured is None and request.schema is not None and text:
            # No usable tool call, but the reply may still contain the answer.
            # Local models routinely narrate a tool call instead of making one:
            # "Here is the JSON for the function call:" followed by a fenced
            # envelope. That is the right content in the wrong container, and
            # throwing it away costs four retries at five minutes each.
            found = _extract_json_object(text)
            if found is not None:
                structured = _unwrap_tool_envelope(found, name)
        if structured is not None:
            structured = _unwrap_tool_envelope(structured, name)

        usage_block = parsed.get("usage", {}) or {}
        spent = Usage(
            # `or 0`: a key present with a null value is not a missing key,
            # and `int(None)` ended a run as an internal error.
            input_tokens=int(usage_block.get("prompt_tokens") or 0),
            output_tokens=int(usage_block.get("completion_tokens") or 0),
        )
        # Recorded even when the answer turns out to be unusable: the call still
        # generated at whatever rate the endpoint runs at, and that rate is what
        # a later timeout has to be judged against.
        if spent.output_tokens > 0 and latency > 0.0:
            self._tokens_generated += spent.output_tokens
            self._seconds_generating += latency

        if request.schema is not None and structured is None:
            finish = str(choice.get("finish_reason") or "")
            error = self._no_structured_output(
                request, finish, text, spent, choice.get("finish_reason")
            )
            error.usage = spent
            raise error

        usage = spent

        return ModelResponse(
            text=text,
            structured=structured,
            usage=usage,
            provider="openai-compatible",
            model=str(parsed.get("model", self._model)),
            stop_reason=_STOP_REASONS.get(
                str(choice.get("finish_reason", "")), StopReason.OTHER
            ),
            latency_seconds=latency,
            request_fingerprint=request.fingerprint(),
            response_id=str(parsed.get("id", "")),
        )


def _loads_or_none(value: Any) -> Mapping[str, Any] | None:
    """Parse a JSON object, accepting one that has already been parsed.

    The OpenAI wire format says a tool call's ``arguments`` is a *string* of
    JSON. Several compatible endpoints send the object itself instead. Both mean
    the same thing, so both are accepted.
    """
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


#: A fenced block anywhere in a reply, not only at the start of it.
_FENCED = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _strip_json_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments, leaving strings untouched.

    Models annotate JSON. A real answer arrived with

        "10" // Arbitrary thickness

    inside an otherwise complete document, which made the whole thing
    unparseable. The comment is not the answer and never was; removing it costs
    nothing and saves a document that is otherwise entirely correct.

    String-aware, because ``"https://example.com"`` is not a comment and a naive
    strip would quietly corrupt every URL and path in the document.
    """
    out: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        character = text[index]
        if in_string:
            out.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            out.append(character)
            index += 1
            continue
        if text.startswith("//", index):
            end = text.find("\n", index)
            index = len(text) if end == -1 else end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end == -1 else end + 2
            continue
        out.append(character)
        index += 1
    return "".join(out)


def _balanced_spans(text: str) -> list[str]:
    """Every balanced ``{...}`` span in the text, outermost first."""
    spans: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}":
            if depth:
                depth -= 1
                if depth == 0 and start != -1:
                    spans.append(text[start : index + 1])
    return spans


def _extract_json_object(text: str) -> Mapping[str, Any] | None:
    """Find the JSON object in a reply that may also contain prose.

    Whole text, then fenced blocks, then balanced spans -- each attempted twice,
    once as written and once with comments stripped.

    The *largest* parseable candidate wins, not the first. An earlier version
    took the first, and when a 7 kB document failed to parse over a single
    trailing comment it returned the four-line ``units`` block nested inside it
    -- a fragment that parsed perfectly and was not the answer. Reporting a
    confident fragment is worse than reporting nothing.
    """
    candidates: list[str] = [text.strip()]
    candidates.extend(block.strip() for block in _FENCED.findall(text))
    candidates.extend(_balanced_spans(text))

    best: Mapping[str, Any] | None = None
    best_size = -1
    for candidate in candidates:
        for attempt in (candidate, _strip_json_comments(candidate)):
            found = _loads_or_none(attempt)
            if found is not None and len(attempt) > best_size:
                best, best_size = found, len(attempt)
                break
    return best


#: Keys of the envelope a model writes when it imitates a tool call in prose.
_ENVELOPE_ARGUMENTS = ("parameters", "arguments", "input")


def _unwrap_tool_envelope(
    payload: Mapping[str, Any], name: str
) -> Mapping[str, Any]:
    """Unwrap ``{"name": ..., "parameters": {...}}`` to the arguments inside.

    A model told to call a tool, which then writes the call out as text, tends
    to write the whole envelope. The answer we want is the inner object. Only
    unwrapped when the payload looks like nothing else -- it names the tool we
    asked for, or carries no other keys -- so a document that legitimately has a
    ``name`` field is never mistaken for an envelope.
    """
    keys = set(payload)
    inner_key = next((k for k in _ENVELOPE_ARGUMENTS if k in payload), None)
    if inner_key is None:
        return payload
    inner = payload[inner_key]
    if not isinstance(inner, Mapping):
        return payload
    # Shape decides, not the name: a model writing the call out by hand often
    # gets the tool name slightly wrong, and an envelope carrying nothing but
    # a name and its arguments is unambiguous whatever it is called.
    del name
    looks_like_envelope = keys <= {"name", "type", "id", *_ENVELOPE_ARGUMENTS}
    return inner if looks_like_envelope else payload


def _error_body(error: urllib.error.HTTPError) -> tuple[str, str]:
    """The endpoint's own words, and a fallback that is never empty.

    An HTTP body can only be read once, and every branch below wants it, so it
    is read here. Two shapes are accepted because two are seen in the wild: a
    bare ``{"error": {...}}`` object, and that object wrapped in a single-element
    array, which is what Google's OpenAI-compatible endpoint returns. Failing to
    unwrap the array cost a real diagnosis: the message was lost, and a missing
    Authorization header was reported as a schema problem.

    The raw preview is kept whatever happens. A diagnostic that says "rejected"
    and stops is not a diagnostic.
    """
    try:
        raw = error.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - an error path must not raise
        return ("", "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ("", raw[:600])

    if isinstance(parsed, list) and parsed:
        parsed = parsed[0]
    message = ""
    if isinstance(parsed, Mapping):
        block = parsed.get("error", parsed)
        if isinstance(block, Mapping):
            message = str(block.get("message", "") or block.get("detail", ""))
        elif isinstance(block, str):
            message = block
    return (message, raw[:600])


#: "Please retry in 59.549108345s", "retryDelay": "60s" -- the delay an endpoint
#: states in its message rather than in a Retry-After header. Reading only the
#: header threw away a precise instruction and fell back to guessing.
_RETRY_HINT = re.compile(
    r"retry(?:\s+in|Delay\"?\s*:\s*\"?)\s*([0-9]+(?:\.[0-9]+)?)\s*s", re.IGNORECASE
)


def _retry_after(error: urllib.error.HTTPError, message: str) -> float | None:
    """When to come back: the header if there is one, else the endpoint's words."""
    header = error.headers.get("retry-after") if error.headers else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    found = _RETRY_HINT.search(message)
    return float(found.group(1)) if found else None



def _classify_http_error(error: urllib.error.HTTPError) -> ModelError:
    message, preview = _error_body(error)
    status = error.code
    detail: dict[str, Any] = {"status": status, "detail": message}
    if not message and preview:
        detail["body"] = preview

    if status in (401, 403) or _looks_like_a_credential_problem(message):
        # Some endpoints answer a missing key with 400 rather than 401. The
        # remedy is the same and it is not the one a 400 usually implies, so it
        # is classified by what the endpoint said, not by the status alone.
        return AuthenticationError(
            "the endpoint rejected the credential",
            **detail,
            hint="set the key in the environment variable this provider reads "
            "(--api-key-env names it; OPENAI_API_KEY by default), in the same "
            "shell you run forge from",
        )
    if status == 429:
        return RateLimitError(
            "rate limited by the endpoint",
            retry_after=_retry_after(error, message),
            **detail,
        )
    if status == 400 and "context" in message.lower():
        return ContextTooLargeError(
            "the request exceeds the model's context window", **detail
        )
    if status == 400 and _looks_like_a_schema_complaint(message):
        return RequestError(
            "the endpoint rejected the request schema",
            **detail,
            hint="this endpoint accepts only a subset of JSON Schema. Retry "
            "with --schema-dialect openapi, or --schema-dialect opaque if it "
            "still refuses; the full contract is enforced locally either way.",
        )
    if 400 <= status < 500:
        return RequestError("the endpoint rejected the request", **detail)
    return TransientError("the endpoint returned a server error", **detail)


#: Words that mean the key, not the request, is the problem.
_CREDENTIAL_COMPLAINTS = (
    "authorization header",
    "api key",
    "api_key",
    "unauthenticated",
    "permission denied",
    "invalid credential",
)


def _looks_like_a_credential_problem(message: str) -> bool:
    lowered = message.lower()
    return any(word in lowered for word in _CREDENTIAL_COMPLAINTS)


#: Words endpoints use when the schema, rather than the prompt, is the problem.
#: Phrases specific enough to mean the *schema* was the problem. Deliberately
#: not "invalid_argument": that is the generic status for every bad request, and
#: matching it turned a missing API key into a confident, wrong recommendation
#: to change the schema dialect. A heuristic that fires on a generic word is
#: worse than no heuristic, because it is believed.
_SCHEMA_COMPLAINTS = (
    "schema",
    "function_declarations",
    "additionalproperties",
    "oneof",
    "anyof",
    "$ref",
    "too deep",
    "nesting",
    "at 'tools",
    "function.parameters",
)


def _looks_like_a_schema_complaint(message: str) -> bool:
    lowered = message.lower()
    return any(word in lowered for word in _SCHEMA_COMPLAINTS)


__all__ = ["OpenAICompatibleProvider", "StructuredMode"]
