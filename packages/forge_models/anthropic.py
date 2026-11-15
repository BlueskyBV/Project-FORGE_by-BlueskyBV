"""Anthropic Messages API adapter, on the standard library.

No SDK. That began as a constraint -- package installation is unavailable in the
environment this was built in -- and turned out to be the right shape anyway:
the whole adapter is one HTTPS POST and a response parse, and vendoring a
dependency tree to perform it would have been the larger cost. It also keeps the
promise made in ADR-0002 intact one layer further out than expected.

Structured output is obtained through **forced tool use** rather than by asking
for JSON in the prompt. The schema is declared as a tool's ``input_schema`` and
``tool_choice`` names that tool, so the model must emit an argument object
matching it. This matters more than it might appear: asking politely for JSON
yields prose-wrapped JSON, markdown fences, and trailing commentary often enough
that the parsing becomes its own source of failures. Forcing the tool moves that
class of error out of the system entirely.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

from .errors import (
    AuthenticationError,
    ConfigurationError,
    ContextTooLargeError,
    ModelError,
    RateLimitError,
    RequestError,
    StructuredOutputError,
    TransientError,
)
from .provider import Budget, Provider, RetryPolicy
from .schema_dialect import ReducedSchema, SchemaDialect, reduce_schema
from .types import ModelRequest, ModelResponse, ProviderInfo, StopReason, Usage
from .leaks import recover_leaked_fields

API_URL = "https://api.anthropic.com/v1/messages"


def _wire_messages(messages: Any) -> list[dict[str, Any]]:
    """The conversation as the Messages API takes it: pictures as image
    blocks before their text, and the first user turn marked for the prompt
    cache when it is long -- a designer correction or a role's retry sends
    it again, and a cached read costs a tenth of a fresh one."""
    import base64

    wire: list[dict[str, Any]] = []
    first_user = next((i for i, m in enumerate(messages)
                       if m.role == "user"), None)
    for index, message in enumerate(messages):
        cache = (index == first_user and len(messages) > 1
                 and len(message.content) > 6000)
        if not message.images and not cache:
            wire.append({"role": message.role, "content": message.content})
            continue
        blocks: list[dict[str, Any]] = [
            {"type": "image", "source": {
                "type": "base64", "media_type": "image/png",
                "data": base64.b64encode(image).decode("ascii")}}
            for image in message.images]
        text: dict[str, Any] = {"type": "text", "text": message.content}
        if cache:
            text["cache_control"] = {"type": "ephemeral"}
        blocks.append(text)
        wire.append({"role": message.role, "content": blocks})
    return wire
API_VERSION = "2023-06-01"

#: The model used when none is named. Kept as a *current* alias rather than a
#: dated snapshot: a hard-coded old identifier fails the first real call with a
#: 404 that reads like a broken adapter, which is a poor first impression of a
#: system whose whole argument is that it does not mislead you.
DEFAULT_MODEL = "claude-sonnet-5"

#: Indicative USD per million tokens, for cost *estimates* only. Prices change,
#: this table will drift, and every report that shows a cost labels it an
#: estimate; the token counts are the authoritative record. Checked against
#: Anthropic's published pricing on 2026-09-12.
PRICE_TABLE: Mapping[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    # Sonnet 5 is listed at the Sonnet 4.6 price on purpose: its own price
    # could not be confirmed on 2026-10-09, and an estimate that errs high is
    # what keeps `--max-cost` a real ceiling rather than a hopeful one.
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4": (0.80, 4.0),
    "claude-3-5-haiku": (0.80, 4.0),
    "claude-3-5-sonnet": (3.0, 15.0),
}

_STOP_REASONS = {
    "end_turn": StopReason.COMPLETE,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "tool_use": StopReason.TOOL_USE,
    "refusal": StopReason.REFUSAL,
}


#: Models that still take `temperature`. The newer ones reject any sampling
#: parameter but the default with a 400 -- Sonnet 5, Opus 4.7 onward, Fable --
#: so it is sent only where it is known to be accepted, and dropped (and the
#: call made again) if a model refuses it anyway.
_TAKES_TEMPERATURE = (
    "claude-3", "claude-haiku-4", "claude-sonnet-4", "claude-opus-4-0",
    "claude-opus-4-1", "claude-opus-4-5", "claude-opus-4-6",
    "claude-opus-4-2025", "claude-sonnet-4-2025",
)


#: What a model is asked to think with, by its name. A forced tool call is
#: answered at once, with no thinking at all -- "where forced tool use is
#: accepted, it skips thinking: the response starts with the tool call" --
#: so every design Forge asked for was a whole CSG program written in one
#: pass with no room to work it out: holes spaced 60 mm apart across a rail
#: 30 mm wide, a pivot "midpoint" of -50 and 25 taken as -37.5, a repair
#: whose diagnosis read "placeholder". Where the model can think, it is
#: let think, and the tool is offered rather than forced.
_THINKING_MODES = ("adaptive", "enabled", "off")


def _thinking_for(model: str) -> str:
    """The thinking a model takes, from its name: `adaptive` from the 4.6
    generation on, `enabled` (a token budget) for 3.7 and the earlier 4s,
    `off` before that. A name this does not know is tried adaptive; a 400
    steps it down (see `_send`)."""
    import re

    name = model.lower()
    if not name.startswith("claude"):
        return "adaptive"
    if re.match(r"claude-3-7", name) or re.match(r"claude-3[.-]7", name):
        return "enabled"
    if re.match(r"claude-(?:3|instant|2)", name) or re.match(
            r"claude-3-5|claude-(?:sonnet|haiku|opus)-3", name):
        return "off"
    found = re.search(r"-(\d+)(?:-(\d{1,2}))?(?:-|$)", name)
    if not found:
        return "adaptive"
    major = int(found.group(1))
    minor = int(found.group(2) or 0)
    if major >= 5 or (major == 4 and minor >= 6):
        return "adaptive"
    if major == 4:
        return "enabled"
    return "off"


def _estimate_cost(
    model: str, usage: Usage, cache_written: int = 0
) -> float | None:
    """USD, estimated: fresh input at the input price, cache reads at a tenth
    of it, cache writes -- counted in `input_tokens` already -- at a quarter
    more, output at the output price."""
    for prefix, (input_price, output_price) in PRICE_TABLE.items():
        if model.startswith(prefix):
            return (
                usage.input_tokens * input_price / 1_000_000.0
                + usage.cached_input_tokens * input_price * 0.1 / 1_000_000.0
                + cache_written * input_price * 0.25 / 1_000_000.0
                + usage.output_tokens * output_price / 1_000_000.0
            )
    return None


class AnthropicProvider(Provider):
    """Talks to the Anthropic Messages API over HTTPS."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        schema_dialect: SchemaDialect = "json_schema",
        base_url: str = API_URL,
        timeout: float = 180.0,
        context_window: int = 200_000,
        retry: RetryPolicy | None = None,
        budget: Budget | None = None,
        thinking: str | None = None,
        effort: str | None = None,
    ) -> None:
        super().__init__(retry=retry, budget=budget)
        self._model = model
        # How the model reasons before it answers: `adaptive`, `enabled` (a
        # token budget) or `off`; None decides from the model's name. A 400
        # that names thinking steps it down, and is remembered.
        chosen = (thinking or os.environ.get("FORGE_THINKING", "")
                  or "").strip().lower()
        if chosen in ("", "auto", "on", "default"):
            chosen = _thinking_for(model)
        if chosen in ("none", "false", "no", "0", "disabled"):
            chosen = "off"
        if chosen not in _THINKING_MODES:
            raise ConfigurationError(
                f"unknown thinking mode {chosen!r}",
                hint="use adaptive, enabled, off, or leave it unset")
        self._thinking = chosen
        self._effort = (effort or os.environ.get("FORGE_EFFORT", "")
                        or "").strip().lower() or None
        # This API takes the full schema, so the default sends it whole. The
        # option exists anyway: an escalation path that is only available on one
        # adapter is not an escalation path, it is a reason to switch providers
        # at the worst possible moment.
        self._schema_dialect: SchemaDialect = schema_dialect
        self.last_reduction: ReducedSchema | None = None
        self._base_url = base_url
        self._timeout = timeout
        self._context_window = context_window
        # The key is read from the environment and never stored anywhere that is
        # serialised: not in provenance, not in the evidence graph, not in a
        # report. Only the fact that a remote provider was used is recorded.
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="anthropic",
            model=self._model,
            supports_structured_output=True,
            is_remote=True,
            context_window=self._context_window,
            supports_images=True,
            thinking=self._thinking,
            effort=self._effort,
            schema_fidelity=(
                self.last_reduction.fidelity if self.last_reduction else "exact"
            ),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _require_key(self) -> str:
        if not self._api_key:
            raise ConfigurationError(
                "no Anthropic API key is configured",
                hint="set the ANTHROPIC_API_KEY environment variable, or pass "
                "api_key= explicitly. Forge never reads a key from a document "
                "or writes one into a report.",
            )
        return self._api_key

    # ------------------------------------------------------------------
    def worst_cost_usd(self, request: ModelRequest) -> float | None:
        """The most this request can cost, estimated before it is sent: a
        cost ceiling that holds before a call (`Budget.price`).

        Its input a third more than the budget's estimate of it (four
        characters a token; three is a token in a dense schema), at the
        input price and a quarter more, as if all of it were written to the
        cache; and every output token `max_tokens` allows -- the answer's
        and, where the model thinks, its thinking's room -- at the output
        price. None for a model outside the price table: such a call can't
        be priced at all."""
        thinks = self._thinking != "off" and request.schema is not None
        output = request.max_output_tokens + (
            self._thinking_room(request) if thinks else 0)
        tokens_in = request.approximate_input_tokens() * 4.0 / 3.0
        for prefix, (input_price, output_price) in PRICE_TABLE.items():
            if self._model.startswith(prefix):
                return (tokens_in * input_price * 1.25
                        + output * output_price) / 1_000_000.0
        return None

    def _thinking_room(self, request: ModelRequest) -> int:
        """Output tokens set aside for thinking, on top of the answer's own:
        `max_tokens` caps the two together, and a design cut off because the
        thinking took its room is paid for and asked again -- the lower-leg
        shell's designer thought past 16 000 tokens, was cut off at 32 768
        after six minutes, and was asked again from the start. As much as
        the call's effort can use: a full-effort design gets 32 000, a
        low-effort reading of a brief 8 000."""
        effort = str(self._effort or getattr(request, "effort", "") or "")
        return {"low": 8_000, "medium": 16_000}.get(effort, 32_000)

    def _build_payload(
        self, request: ModelRequest, *, sampling: bool = True,
        forced: bool = True, thinking: str | None = None,
        effort: str | None = "__default__",
    ) -> dict[str, Any]:
        thinking = self._thinking if thinking is None else thinking
        if effort == "__default__":
            # The run's own setting first; else what this call asks for --
            # a role that only reads a brief does not need to think hard.
            effort = self._effort or (getattr(request, "effort", "") or None)
        if getattr(self, "_effort_refused", False):
            effort = None
        thinks = thinking != "off" and request.schema is not None
        # A forced tool is answered at once, with no thinking: so where the
        # model thinks, the tool is offered, not forced.
        forced = forced and not thinks
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_output_tokens + (
                self._thinking_room(request) if thinks else 0),
            "messages": _wire_messages(request.messages),
        }
        if thinks and thinking == "adaptive":
            payload["thinking"] = {"type": "adaptive"}
            if effort:
                payload["output_config"] = {"effort": effort}
        elif thinks and thinking == "enabled":
            # A budget the effort scales: a low-effort call thinks a little.
            room = self._thinking_room(request)
            budget = {"low": 4096, "medium": 8192}.get(str(effort or ""), room)
            payload["thinking"] = {"type": "enabled",
                                   "budget_tokens": min(budget, room)}
        if sampling and not thinks and request.temperature is not None and \
                self._model.startswith(_TAKES_TEMPERATURE):
            payload["temperature"] = request.temperature
        if request.system:
            # Cached: the same instructions go out again on every correction
            # and repair turn, and a cached read costs a tenth of a fresh one.
            # The tool schema comes before the system prompt in the cache's
            # order, so it is cached with it.
            system = request.system
            if request.schema is not None and not forced:
                system += (
                    "\n\nAnswer only by calling the tool `submit_"
                    f"{request.schema_name or 'result'}` once, with your "
                    "complete answer as its input. Do not reply in text."
                    + (" Work the answer out first -- every position, size "
                       "and count against the brief -- and then call the "
                       "tool with it whole: no placeholder, no value to be "
                       "corrected later, because nothing you write after "
                       "the call is read." if thinks else ""))
            payload["system"] = [{"type": "text", "text": system,
                                  "cache_control": {"type": "ephemeral"}}]
        if request.stop_sequences:
            payload["stop_sequences"] = list(request.stop_sequences)
        if request.schema is not None:
            # `submit_` prefix, deliberately: a tool named for the role reads
            # as something to delegate the work to, and a weak model will call
            # it with the input instead of with an answer.
            name = f"submit_{request.schema_name or 'result'}"
            reduction = reduce_schema(request.schema, self._schema_dialect)
            self.last_reduction = reduction
            payload["tools"] = [
                {
                    "name": name,
                    "description": (
                        request.schema_description
                        or "Return the result in exactly this structure."
                    ),
                    "input_schema": dict(reduction.schema),
                }
            ]
            payload["tool_choice"] = (
                {"type": "tool", "name": name} if forced else {"type": "auto"})
        return payload

    def _send(self, request: ModelRequest) -> ModelResponse:
        """One call, made again -- unbilled, a 400 is never charged -- with
        what the model refused taken out: a sampling parameter the newer
        models reject, or a forced tool choice some of them do not allow."""
        # Remembered across calls, like the thinking and output-limit
        # step-downs: as locals, every call first re-sent the sampling
        # parameter or the forced tool choice, took the 400 again, and sent
        # the call again -- one wasted round trip per call for the run.
        sampling = getattr(self, "_sampling", True)
        forced = getattr(self, "_forced", True)
        limit = getattr(self, "_output_limit", None)
        if limit is not None and request.max_output_tokens > limit:
            request = _with_max_tokens(request, limit)
        for _ in range(6):
            try:
                return self._send_once(request, sampling=sampling,
                                       forced=forced)
            except RequestError as error:
                said = (str(error) + " " + json.dumps(
                    getattr(error, "detail", {}) or {}, default=str)).lower()
                allowed = _the_output_limit_said(said)
                room = (self._thinking_room(request)
                        if self._thinking != "off" and request.schema
                        is not None else 0)
                if allowed is not None and \
                        allowed < request.max_output_tokens + room:
                    # More output asked for than this model can write: an
                    # older model's 8192, say. Asked again within it, and
                    # remembered, rather than the run ending on a 400. The
                    # thinking's room comes out of the same limit.
                    if room and allowed - room < 1024:
                        self._thinking = "off"
                        room = 0
                    within = max(1024, allowed - room)
                    if within < request.max_output_tokens:
                        self._output_limit = within
                        request = _with_max_tokens(request, within)
                    continue
                if not getattr(self, "_effort_refused", False) and (
                        self._effort or getattr(request, "effort", "")) \
                        and any(w in said for w in ("effort", "output_config")):
                    # An effort level this model does not take: its own
                    # default instead, for the rest of the run.
                    self._effort = None
                    self._effort_refused = True
                    continue
                if self._thinking != "off" and any(w in said for w in (
                        "thinking", "adaptive", "budget_tokens")):
                    # Stepped down, and remembered: adaptive to a budget,
                    # a budget to none.
                    self._thinking = ("enabled" if self._thinking == "adaptive"
                                      else "off")
                    continue
                if sampling and any(w in said for w in (
                        "temperature", "sampling", "top_p", "top_k")):
                    sampling = self._sampling = False
                    continue
                if forced and "tool_choice" in said:
                    forced = self._forced = False
                    continue
                raise
        return self._send_once(request, sampling=sampling, forced=forced)

    def _send_once(
        self, request: ModelRequest, *, sampling: bool, forced: bool
    ) -> ModelResponse:
        payload = self._build_payload(request, sampling=sampling,
                                      forced=forced)
        parsed, latency = self._post(payload)
        offered = payload.get("tool_choice", {}).get("type") == "auto"
        if (offered and request.schema is not None
                and not _a_tool_call_in(parsed)
                and parsed.get("stop_reason") not in ("max_tokens",
                                                      "refusal")):
            # Offered the tool, it answered in words -- its reasoning, or the
            # answer itself written out. Asked, in the same conversation, its
            # thinking kept exactly as it came, to submit what it worked out:
            # a fresh call would throw the working away.
            name = payload["tools"][0]["name"]
            follow = dict(payload)
            follow["messages"] = list(payload["messages"]) + [
                {"role": "assistant", "content": parsed.get("content") or [
                    {"type": "text", "text": "(no answer)"}]},
                {"role": "user", "content": (
                    f"Call `{name}` now, with the complete answer you have "
                    "worked out as its input. Do not reply in text.")}]
            first_usage = parsed.get("usage") or {}
            try:
                again, more = self._post(follow)
            except RequestError:
                again, more = None, 0.0
            except ModelError as error:
                # The first call was answered and paid for. A 429, a 5xx or
                # a dropped connection on the follow-up left the pair
                # unrecorded -- the retry then made both calls again and
                # the budget saw none of it. The first call's tokens go out
                # with the error, as every other paid-for failure's do.
                if getattr(error, "usage", None) is None:
                    error.usage = self._usage_from(first_usage)
                raise
            if again is not None:
                usage = dict(again.get("usage") or {})
                for k in ("input_tokens", "output_tokens",
                          "cache_creation_input_tokens",
                          "cache_read_input_tokens"):
                    usage[k] = int(usage.get(k, 0) or 0) + int(
                        first_usage.get(k, 0) or 0)
                written = "".join(
                    b.get("text", "") for b in parsed.get("content") or []
                    if isinstance(b, Mapping) and b.get("type") == "text")
                parsed = {**again, "usage": usage}
                if not _a_tool_call_in(parsed) and written:
                    parsed["content"] = list(parsed.get("content") or []) + [
                        {"type": "text", "text": written}]
                latency += more
        return self._parse(request, parsed, latency)

    def _post(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], float]:
        """One POST of `payload`, streamed; the reply as one message, and
        the seconds it took.

        Streamed because a reply that thinks first can take many minutes,
        and a request that sends nothing back for that long was cut off at
        the timeout and sent again from the start: the leg shell's designer
        timed out at 600 s and was asked again, its analyst twice, its
        redesign twice -- 65 minutes, nothing to show for it. Streamed, the
        answer arrives as it is written, the timeout is the longest silence
        allowed rather than the longest answer, and a stall is caught in
        minutes. The events are put back together into the message the
        non-streamed API returns, so everything after reads the same.
        A plain JSON body -- a proxy that does not stream -- is read as one.
        """
        key = self._require_key()
        body = json.dumps({**dict(payload), "stream": True}).encode("utf-8")

        http_request = urllib.request.Request(
            self._base_url,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "accept": "text/event-stream",
                "x-api-key": key,
                "anthropic-version": API_VERSION,
                "user-agent": "forge/0.1.0",
            },
        )

        started = time.perf_counter()
        # The longest silence allowed. The API sends events -- the answer,
        # the thinking, and a ping when there is nothing else -- every few
        # seconds; five minutes of nothing is a stalled connection.
        silence = max(60.0, min(float(self._timeout), 300.0))
        # How far the answer has got, for the heartbeat: thinking or writing,
        # and roughly how many tokens -- a count that climbs is a model at
        # work, one that stops is a stall.
        self.tokens_so_far = 0
        self.phase_so_far = ""

        def progress(characters: int, phase: str) -> None:
            self.tokens_so_far = characters // 4
            self.phase_so_far = phase

        try:
            with urllib.request.urlopen(http_request, timeout=silence) as handle:
                if "thinking" in payload:
                    # Answered and thinking: a model that thinks without
                    # showing it streams nothing until it writes, and the
                    # heartbeat said "reading the prompt" for six minutes.
                    progress(0, "thinking")
                parsed = _read_the_reply(handle, progress)
        except urllib.error.HTTPError as error:
            raise _classify_http_error(error) from error
        except urllib.error.URLError as error:
            unreachable = TransientError(
                "could not reach the Anthropic API",
                reason=str(error.reason),
            )
            # A network that drops for a few seconds -- a lookup that fails,
            # a Wi-Fi that reconnects -- is waited out, not given up on in
            # the seven seconds four quick tries take.
            unreachable.minimum_delay = 5.0
            raise unreachable from error
        except TimeoutError as error:
            timed_out = TransientError(
                "the Anthropic API went silent", silence_s=silence
            )
            timed_out.retry_limit = 2  # once more, not three times more
            raise timed_out from error
        except (OSError, http.client.HTTPException) as error:
            # A connection dropped while the answer was being read -- a reset
            # (WinError 10054), the server closing early, a body cut short.
            # Not raised by `urlopen` but by `read()`, so it passed every
            # handler above and ended runs as "internal error" instead of
            # being retried.
            raise TransientError(
                "the connection to the Anthropic API dropped",
                reason=f"{type(error).__name__}: {error}"[:300],
            ) from error
        latency = time.perf_counter() - started
        return parsed, latency

    def _usage_from(self, usage_block: Mapping[str, Any]) -> Usage:
        """What one reply cost, from its `usage` block, priced.

        Tokens written to the cache are fresh input, read at full price and
        a quarter more, and the API counts them apart from `input_tokens`.
        Left out, a role whose 30 000-token guide was written to the cache
        showed a few hundred tokens in: the run's token budget never saw
        its largest input, and the cost estimate charged it a quarter.
        """
        usage_block = usage_block or {}
        written = int(usage_block.get("cache_creation_input_tokens", 0) or 0)
        usage = Usage(
            input_tokens=int(usage_block.get("input_tokens", 0) or 0) + written,
            output_tokens=int(usage_block.get("output_tokens", 0) or 0),
            cached_input_tokens=int(
                usage_block.get("cache_read_input_tokens", 0) or 0
            ),
        )
        return Usage(
            usage.input_tokens,
            usage.output_tokens,
            usage.cached_input_tokens,
            _estimate_cost(self._model, usage, written),
        )

    def _parse(
        self, request: ModelRequest, parsed: Mapping[str, Any], latency: float
    ) -> ModelResponse:
        usage = self._usage_from(parsed.get("usage", {}) or {})

        text_parts: list[str] = []
        structured: Mapping[str, Any] | None = None
        for block in parsed.get("content", []) or []:
            if not isinstance(block, Mapping):
                continue
            kind = block.get("type")
            if kind == "text":
                text_parts.append(str(block.get("text", "") or ""))
            elif kind == "tool_use":
                candidate = block.get("input")
                if isinstance(candidate, str):
                    # The arguments as JSON text rather than an object: not
                    # a shape the API sends, but a present answer, and it
                    # was being refused as "no structured output" and billed
                    # again up to four times.
                    try:
                        candidate = json.loads(candidate)
                    except ValueError:
                        candidate = None
                if isinstance(candidate, Mapping):
                    # Fields written inside another field's string, put back:
                    # see forge_models.leaks.
                    structured = recover_leaked_fields(candidate,
                                                       request.schema)

        stop_reason = _STOP_REASONS.get(
            parsed.get("stop_reason", ""), StopReason.OTHER
        )

        if request.schema is not None and structured is None:
            # Offered the tool and written out in words instead: the answer
            # as a JSON object in the text is still the answer.
            written = _an_object_in_the_text("".join(text_parts),
                                             request.schema)
            if written is not None:
                structured = recover_leaked_fields(written, request.schema)
        if (request.schema is not None and structured is None
                and stop_reason is StopReason.MAX_TOKENS):
            # Cut off before the answer began -- the thinking took the room.
            # Returned as the truncation it is, so the role asks again with
            # more room, rather than the same call being made again as is.
            return ModelResponse(
                text="".join(text_parts), structured=None, usage=usage,
                provider="anthropic",
                model=str(parsed.get("model", self._model)),
                stop_reason=stop_reason, latency_seconds=latency,
                request_fingerprint=request.fingerprint(),
                response_id=str(parsed.get("id", "")))
        if request.schema is not None and structured is None:
            # The model was told it had to use the tool and did not. Retrying is
            # worthwhile -- it is usually a truncation -- but the distinction is
            # recorded so a persistent failure is not mistaken for a bad design.
            error = StructuredOutputError(
                "the model returned no structured output despite a forced tool",
                stop_reason=parsed.get("stop_reason"),
                had_text=bool(text_parts),
                hint=(
                    "the response was truncated; raise max_output_tokens"
                    if stop_reason is StopReason.MAX_TOKENS
                    else "unexpected: the tool choice was forced"
                ),
            )
            # The call was paid for even though its answer is unusable.
            error.usage = usage
            raise error

        return ModelResponse(
            text="".join(text_parts),
            structured=structured,
            usage=usage,
            provider="anthropic",
            model=str(parsed.get("model", self._model)),
            stop_reason=stop_reason,
            latency_seconds=latency,
            request_fingerprint=request.fingerprint(),
            response_id=str(parsed.get("id", "")),
        )


def _read_the_reply(handle: Any, progress: Any = None) -> dict[str, Any]:
    """The message a reply carries: put back together from its stream of
    server-sent events, or read whole when it came as one JSON body.
    `progress(characters, phase)` is told how far it has got."""
    first = handle.readline()
    while first is not None and first.strip() == b"" and first != b"":
        first = handle.readline()
    if not first:
        raise TransientError("the Anthropic API returned an empty reply")
    if first.lstrip().startswith(b"{"):
        raw = (first + handle.read()).decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise TransientError(
                "the Anthropic API returned a body that is not JSON",
                preview=raw[:200],
            ) from error
        if not isinstance(parsed, Mapping):
            raise TransientError(
                "the Anthropic API returned a body that is not an object",
                preview=raw[:200],
            )
        return dict(parsed)

    message: dict[str, Any] = {"content": [], "usage": {}}
    partial: dict[int, list[str]] = {}
    finished = False
    written = [0]

    def advanced(characters: int, phase: str) -> None:
        written[0] += characters
        if progress is not None:
            try:
                progress(written[0], phase)
            except Exception:  # noqa: BLE001 - a heartbeat never breaks a call
                pass
    event = ""
    data_lines: list[str] = []

    def dispatch(kind: str, data: str) -> None:
        nonlocal finished
        if not data:
            return
        try:
            item = json.loads(data)
        except json.JSONDecodeError:
            return
        if not isinstance(item, Mapping):
            return
        kind = str(item.get("type") or kind)
        if kind == "message_start":
            start = item.get("message") or {}
            content = message["content"]
            message.update({k: v for k, v in dict(start).items()
                            if k != "content"})
            message["content"] = content
            message["usage"] = dict(start.get("usage") or {})
        elif kind == "content_block_start":
            index = int(item.get("index", len(message["content"])))
            block = dict(item.get("content_block") or {})
            if block.get("type") in ("thinking", "redacted_thinking"):
                advanced(0, "thinking")
            elif block.get("type") in ("text", "tool_use"):
                advanced(0, "writing")
            if block.get("type") == "tool_use":
                partial[index] = []
            while len(message["content"]) <= index:
                message["content"].append({})
            message["content"][index] = block
        elif kind == "content_block_delta":
            index = int(item.get("index", 0))
            delta = item.get("delta") or {}
            while len(message["content"]) <= index:
                message["content"].append({})
            block = message["content"][index]
            what = delta.get("type")
            if what == "text_delta":
                piece = str(delta.get("text", ""))
                block["text"] = block.get("text", "") + piece
                advanced(len(piece), "writing")
            elif what == "thinking_delta":
                piece = str(delta.get("thinking", ""))
                block["thinking"] = block.get("thinking", "") + piece
                advanced(len(piece), "thinking")
            elif what == "signature_delta":
                block["signature"] = block.get("signature", "") + str(
                    delta.get("signature", ""))
            elif what == "input_json_delta":
                piece = str(delta.get("partial_json", ""))
                partial.setdefault(index, []).append(piece)
                advanced(len(piece), "writing")
        elif kind == "content_block_stop":
            index = int(item.get("index", 0))
            if index in partial and index < len(message["content"]):
                text = "".join(partial.pop(index))
                block = message["content"][index]
                if text.strip():
                    try:
                        block["input"] = json.loads(text)
                    except json.JSONDecodeError:
                        # Kept as written: read as JSON text downstream, and
                        # a cut-off one is a truncation, not a crash.
                        block["input"] = text
                elif not isinstance(block.get("input"), Mapping):
                    block["input"] = {}
        elif kind == "message_delta":
            delta = item.get("delta") or {}
            for name in ("stop_reason", "stop_sequence"):
                if name in delta:
                    message[name] = delta[name]
            for name, value in dict(item.get("usage") or {}).items():
                if value is not None:
                    message["usage"][name] = value
        elif kind == "message_stop":
            finished = True
        elif kind == "error":
            problem = item.get("error") or {}
            what = str(problem.get("type", ""))
            said = str(problem.get("message", ""))[:300]
            if what in ("overloaded_error", "api_error", "timeout_error"):
                raise TransientError(
                    f"the Anthropic API failed mid-answer ({what})",
                    detail=said, status=529 if what == "overloaded_error"
                    else 500)
            if what == "rate_limit_error":
                raise RateLimitError("rate limited by the Anthropic API",
                                     detail=said)
            begun = any(b for b in message["content"])
            if "credit balance" in said.lower():
                raise RequestError(
                    "the Anthropic API account is out of credit", detail=said,
                    hint="add credit to the Console organization this key "
                    "belongs to (Settings > Billing), or link a Max or Team "
                    "plan's monthly API credits to it; nothing in Forge or "
                    "the design needs changing")
            raise RequestError(
                f"the Anthropic API refused the request"
                + (" mid-answer" if begun else "") + f" ({what})",
                detail=said)

    line = first
    while True:
        if not line:
            break
        text = line.decode("utf-8", "replace").rstrip("\r\n")
        if text == "":
            dispatch(event, "\n".join(data_lines))
            event, data_lines = "", []
            if finished:
                break
        elif text.startswith("event:"):
            event = text[6:].strip()
        elif text.startswith("data:"):
            data_lines.append(text[5:].lstrip())
        line = handle.readline()
    if data_lines:
        dispatch(event, "\n".join(data_lines))
    # Anything still being written when the stream ended: kept as far as it
    # got, so a cut-off answer reads as cut off.
    for index, pieces in list(partial.items()):
        if index < len(message["content"]):
            message["content"][index]["input"] = "".join(pieces)
    if not finished and "stop_reason" not in message:
        raise TransientError(
            "the connection to the Anthropic API dropped mid-answer")
    message["content"] = [b for b in message["content"] if b]
    return message


def _a_tool_call_in(parsed: Mapping[str, Any]) -> bool:
    return any(isinstance(b, Mapping) and b.get("type") == "tool_use"
               for b in parsed.get("content", []) or [])


def _an_object_in_the_text(text: str, schema: Any) -> dict[str, Any] | None:
    """The answer, where it was written as a JSON object in the text: the
    first object that carries every field the schema requires."""
    if "{" not in text:
        return None
    required = list((schema or {}).get("required") or []) \
        if isinstance(schema, Mapping) else []
    decoder = json.JSONDecoder()
    best = None
    for start in range(len(text)):
        if text[start] != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(value, dict) and all(k in value for k in required) \
                and value:
            if best is None or len(json.dumps(value)) > len(json.dumps(best)):
                best = value
    return best


def _the_output_limit_said(message: str) -> int | None:
    """The largest `max_tokens` a 400 says the model allows, if it says.
    "max_tokens: 32768 > 8192, which is the maximum allowed number of output
    tokens for ..." -> 8192."""
    import re

    if "max_tokens" not in message:
        return None
    found = re.search(r"max_tokens\D{0,40}?(\d+)\s*>\s*(\d+)", message)
    if found:
        return int(found.group(2))
    found = re.search(r"maximum[^0-9]{0,60}(\d{3,6})", message)
    return int(found.group(1)) if found else None


def _with_max_tokens(request: ModelRequest, limit: int) -> ModelRequest:
    from dataclasses import replace

    return replace(request, max_output_tokens=int(limit))


def _classify_http_error(error: urllib.error.HTTPError) -> ModelError:
    try:
        detail = json.loads(error.read().decode("utf-8"))
        message = detail.get("error", {}).get("message", "")
        error_type = detail.get("error", {}).get("type", "")
    except Exception:  # noqa: BLE001 - the body may be anything on an error path
        message, error_type = "", ""

    status = error.code
    if status in (401, 403):
        return AuthenticationError(
            "the Anthropic API rejected the credential",
            status=status,
            detail=message,
        )
    if status == 429:
        header = error.headers.get("retry-after") if error.headers else None
        try:
            retry_after = float(header) if header else None
        except ValueError:
            retry_after = None
        return RateLimitError(
            "rate limited by the Anthropic API",
            retry_after=retry_after,
            status=status,
            detail=message,
        )
    if status == 400 and "prompt is too long" in message.lower():
        return ContextTooLargeError(
            "the request exceeds the model's context window",
            status=status,
            detail=message,
        )
    if status == 404 or "model" in error_type.lower():
        # The most likely first-run failure: model identifiers are retired and
        # replaced, so a default that was current when this was written will one
        # day 404. Saying which model was asked for, and that it is nameable,
        # turns a dead end into a one-flag fix.
        return RequestError(
            "the Anthropic API does not recognise this model",
            status=status,
            detail=message,
            hint="name a model the account can use with --model, e.g. "
            f"--model {DEFAULT_MODEL}. Current identifiers are listed at "
            "https://docs.claude.com/en/docs/about-claude/models",
        )
    if status == 400 and "input_schema" in message.lower():
        return RequestError(
            "the Anthropic API rejected the request schema",
            status=status,
            error_type=error_type,
            detail=message,
            hint="retry with --schema-dialect openapi, or opaque if it still "
            "refuses; the full contract is enforced locally either way",
        )
    if 400 <= status < 500 and "credit balance" in message.lower():
        return RequestError(
            "the Anthropic API account is out of credit",
            status=status,
            error_type=error_type,
            detail=message,
            hint="add credit to the Console organization this key belongs "
            "to (Settings > Billing), or link a Max or Team plan's monthly "
            "API credits to it; nothing in Forge or the design needs changing",
        )
    if 400 <= status < 500:
        return RequestError(
            "the Anthropic API rejected the request",
            status=status,
            error_type=error_type,
            detail=message,
        )
    return TransientError(
        "the Anthropic API returned a server error",
        status=status,
        detail=message,
    )


__all__ = ["AnthropicProvider", "API_URL", "PRICE_TABLE", "DEFAULT_MODEL"]
