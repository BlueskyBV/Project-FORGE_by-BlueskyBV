"""Ollama's own endpoint, where the schema is a decoding grammar.

Forge spoke to local models through the OpenAI-compatible shim at `/v1`, with
the output schema attached as a function-call definition. Measured, that
transport does not constrain generation at all.

The probe put a required single-value enum at three places every valid
document must pass through -- the document, each component, each feature --
and asked both transports for the same simple block::

    native /api/chat  short prompt: ENFORCED      designer prompt: ENFORCED
    openai shim /v1   short prompt: NOT enforced  designer prompt: NOT enforced

Under a five-token prompt the shim answered with this::

    {"document": {"type": "object", "description": "The part you designed.
     Requirements, assumptions, ids, units and the schema version are filled
     in for you -- do not include them.", "properties": {"name": ...

That is our own schema, echoed back wearing a document's clothes. Nothing was
constraining it, so the model reproduced the nearest JSON-shaped thing it had
been shown. `_reject_a_schema` in the designer exists because somebody saw
that once and treated it as a curiosity; it was the transport all along.

On `/api/chat` the `format` field is compiled into a grammar that generation
cannot leave. Two consequences beyond correctness:

* the schema never enters the prompt. Three schemas of 11,215, 4,003 and 68
  tokens all reported the same 7,177 prompt tokens, because only the system
  message and the brief are text. Schema size stops costing context.
* `num_ctx` is set per request, so `--context-window` becomes a real setting
  rather than a planning hint the runtime ignores.

What this does NOT fix, and it matters: a grammar constrains structure, never
meaning. The plate built in the wrong plane was a perfectly valid document.
This removes invented structures and schema echo -- the floor of noise every
real failure has been buried under -- and leaves the semantic work where it
belongs.
"""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

from .errors import (
    ConfigurationError,
    RateLimitError,
    RequestError,
    RequestTimeoutError,
    StructuredOutputError,
    TransientError,
)
from .provider import Provider
from .types import ModelRequest, ModelResponse, ProviderInfo, StopReason, Usage

#: Ollama answers a design request in one JSON object. Anything larger than
#: this is a runaway, not a document, and reading it costs memory we do not
#: have on the machines this exists for.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

#: Characters of nothing but blank space, in a row, after which a reply is
#: given up on. A grammar for JSON allows whitespace between any two tokens,
#: and a local model can fall into writing nothing else -- newline after
#: newline -- until the output cap. On a laptop writing a few tokens a second
#: that is the better part of an hour spent on blank space. A real document
#: never has this much in one place.
BLANK_RUN_LIMIT = 400


def _read_the_stream(lines: Any, on_chunk: Any = None) -> dict[str, Any]:
    """Ollama's streamed reply, read chunk by chunk, as the one object a
    reply that was not streamed would have been.

    Streamed so that waiting has a meaning. Unstreamed, the socket timeout
    covers the whole reply: a document that takes 41 minutes to write and
    a server that stopped answering look the same, and the run that hit
    the timeout threw away everything written so far and asked again. Here
    the timeout is between chunks -- how long Ollama may stay silent -- and
    a reply that is being written is never cut off for taking long.
    """
    content: list[str] = []
    thinking: list[str] = []
    last: dict[str, Any] = {}
    size = 0
    blank = 0
    chunks = 0
    for raw in lines:
        size += len(raw)
        if size > MAX_RESPONSE_BYTES:
            raise StructuredOutputError(
                "the reply exceeded the response limit",
                limit_bytes=MAX_RESPONSE_BYTES,
            )
        raw = raw.strip()
        if not raw:
            continue
        try:
            chunk = json.loads(raw)
        except ValueError as error:
            raise TransientError(
                "Ollama's reply was not JSON",
                detail=raw[:300].decode("utf-8", "replace")
                if isinstance(raw, bytes) else str(raw)[:300],
            ) from error
        if not isinstance(chunk, Mapping):
            continue
        if chunk.get("error"):
            raise TransientError("Ollama stopped with an error",
                                 detail=str(chunk.get("error"))[:400])
        message = chunk.get("message") or {}
        piece = str(message.get("content") or "")
        if message.get("thinking"):
            thinking.append(str(message.get("thinking")))
        if piece:
            content.append(piece)
            chunks += 1
            if piece.strip():
                blank = len(piece) - len(piece.rstrip())
            else:
                blank += len(piece)
            if blank > BLANK_RUN_LIMIT:
                raise StructuredOutputError(
                    "the model was writing nothing but blank space",
                    blank_characters=blank,
                    written=chunks,
                    hint=(
                        "a JSON grammar allows whitespace anywhere, and the "
                        "model fell into writing only that. It was stopped "
                        "rather than left to run to the output cap"
                    ),
                )
        if on_chunk is not None:
            on_chunk(chunks)
        last = dict(chunk)
        if chunk.get("done"):
            break
    reply = dict(last)
    reply["message"] = {"role": "assistant", "content": "".join(content)}
    if thinking:
        reply["message"]["thinking"] = "".join(thinking)
    return reply

#: Ollama's own names for why generation ended.
_STOP_REASONS = {
    "stop": StopReason.COMPLETE,
    "length": StopReason.MAX_TOKENS,
    "load": StopReason.OTHER,
    "unload": StopReason.OTHER,
}


#: How many entries a list may hold in the grammar. Generous enough that no
#: real design meets them: a part with more than 64 features, or a brief
#: yielding more than 24 stated facts, is a runaway rather than a document.
_MAX_OBJECTS = 64
#: Lists of prose are the ones a model pads. Measured on the first run with
#: bounds in place: `implied` and `unstated` both came back at exactly 24,
#: filled with "The spacer block is a printed spacer block" twenty-four times.
#: The bound had turned an endless loop into a 24-long one. Real answers are
#: far shorter -- the bracket fixture's `unstated` holds 7 -- so the ceiling
#: sits above what a genuine answer needs, and padding that reaches it is
#: deduplicated on the way in rather than let through.
#:
#: Raised from 12 once the padding was repaired rather than rejected. At 12 a
#: thorough `unstated` -- the field this project most wants thoroughness in --
#: could reach the ceiling honestly, and the check could not tell that from a
#: truncation. Now that repetition is removed first, the only cost of a higher
#: ceiling is tokens in the pathological case, and the only cost of a lower
#: one is a genuinely thorough answer cut short. On this hardware those are
#: not symmetric: the second is the one that loses the run.
_MAX_STRINGS = 16
#: Characters in one string. A requirement statement or a rationale fits well
#: inside this; a value that reaches it was not a sentence.
_MAX_TEXT = 1000


def bounded_for_grammar(schema: Any) -> Any:
    """Give every list and string a ceiling, so generation can end.

    This is the bill that comes with real enforcement, and it arrives the
    moment the schema stops being decoration. In an unbounded `array` the
    closing bracket is merely *permitted* at each step and another element is
    always legal too; in an unbounded `string` the closing quote is optional
    forever. A grammar therefore never obliges the model to stop, and a small
    model with no strong instinct for finishing will not.

    Observed the first time this transport ran for real: the brief
    interpreter, which had answered the same brief in 274 tokens through the
    unconstrained shim, filled `stated`, `implied`, `unstated` and
    `out_of_scope` for 2,048 tokens and eighteen minutes before hitting the
    output cap. Nothing was wrong with the model or the schema's meaning --
    the schema simply never said "that is enough".

    Applied here rather than in ForgeIR because it is a property of
    grammar-constrained decoding, not a claim about parts. Forge does not
    believe a component may hold at most 64 features; it believes a decoder
    needs a stopping rule. The document is validated afterwards exactly as
    before, and the stored contract is untouched.
    """
    if isinstance(schema, list):
        return [bounded_for_grammar(item) for item in schema]
    if not isinstance(schema, Mapping):
        return schema
    node = {key: bounded_for_grammar(value) for key, value in schema.items()}
    kind = node.get("type")
    if kind == "array" and "maxItems" not in node:
        items = node.get("items")
        of_strings = isinstance(items, Mapping) and items.get("type") == "string"
        node["maxItems"] = _MAX_STRINGS if of_strings else _MAX_OBJECTS
    elif (
        kind == "string"
        and "maxLength" not in node
        # An enum or const already bounds itself, and adding a length to one
        # would be noise in the grammar.
        and "enum" not in node
        and "const" not in node
    ):
        node["maxLength"] = _MAX_TEXT
    return node


def _lists_at_their_ceiling(payload: Any, schema: Any, path: str = "") -> list[str]:
    """Every list in the answer that is exactly as long as the schema allows.

    Walked against the bounded schema rather than the original, because the
    bound is what the grammar enforced. Only `maxItems` is consulted: a string
    at its `maxLength` is far likelier to be a long sentence than a cut one,
    and flagging those would cry wolf.
    """
    if not isinstance(schema, Mapping):
        return []
    found: list[str] = []
    if isinstance(payload, list):
        limit = schema.get("maxItems")
        floor = schema.get("minItems")
        # A list whose minimum equals its maximum has a mandated length, not
        # a ceiling: a three-component vector is exactly three because space
        # has three axes. Reporting those would fire on every coordinate in
        # every document -- caught by the clevis, which is all vectors.
        exact = isinstance(floor, int) and floor == limit
        if isinstance(limit, int) and not exact and len(payload) >= limit:
            found.append(f"{path or '/'} holds {len(payload)}, the limit is {limit}")
        items = schema.get("items")
        for index, entry in enumerate(payload):
            found += _lists_at_their_ceiling(entry, items, f"{path}/{index}")
    elif isinstance(payload, Mapping):
        properties = schema.get("properties")
        if isinstance(properties, Mapping):
            for key, value in payload.items():
                if key in properties:
                    found += _lists_at_their_ceiling(value, properties[key], f"{path}/{key}")
        # A union branch is satisfied by whichever branch validates; checking
        # them all would report a ceiling from a branch the answer never took.
        for branch in schema.get("oneOf") or []:
            found += _lists_at_their_ceiling(payload, branch, path)
    return sorted(set(found))


def _drop_the_padding(
    payload: Any, schema: Any, path: str = ""
) -> tuple[Any, list[str], list[str]]:
    """Remove repeated entries from a list that ran to its ceiling.

    The first version of this refused the whole answer, and that was wrong.
    Measured on the run that tripped it::

        stated     7 items ->  7 distinct   <- the brief, extracted correctly
        implied   24 items ->  4 distinct
        unstated  24 items ->  1 distinct

    The model produces the real content and then repeats itself to fill the
    list, because a bounded array still permits another element at every step
    and it has no instinct for stopping. Everything it knew was in the first
    few entries. Ending a four-minute run over a duplicated tail throws away a
    good answer for a cosmetic fault -- the same mistake as making validation
    stricter until a ninety-percent-correct document gets rejected.

    So a padded list is repaired here and noted, and only a list that stays at
    its ceiling after deduplication is refused: distinct entries filling the
    bound is the signature of a genuine truncation, where the answer looks
    complete and is not.

    Returns the repaired payload, a note per repair, and the lists that are
    still full of distinct entries.
    """
    notes: list[str] = []
    still_full: list[str] = []
    if not isinstance(schema, Mapping):
        return payload, notes, still_full

    if isinstance(payload, list):
        limit = schema.get("maxItems")
        floor = schema.get("minItems")
        # A vector is three long because space has three axes: mandated, not
        # a ceiling. Reporting those would fire on every coordinate.
        exact = isinstance(floor, int) and floor == limit
        items = schema.get("items")
        repaired = []
        for index, entry in enumerate(payload):
            fixed, sub_notes, sub_full = _drop_the_padding(
                entry, items, f"{path}/{index}"
            )
            repaired.append(fixed)
            notes += sub_notes
            still_full += sub_full
        if isinstance(limit, int) and not exact and len(repaired) >= limit:
            seen: dict[str, None] = {}
            unique = []
            for entry in repaired:
                key = json.dumps(entry, sort_keys=True, default=str)
                if key not in seen:
                    seen[key] = None
                    unique.append(entry)
            if len(unique) < len(repaired):
                notes.append(
                    f"{path or '/'} came back at its ceiling of {limit} with "
                    f"only {len(unique)} distinct entries; the repeats were "
                    "dropped."
                )
                repaired = unique
            if len(repaired) >= limit:
                still_full.append(
                    f"{path or '/'} holds {len(repaired)} distinct entries, "
                    f"the limit is {limit}"
                )
        return repaired, notes, still_full

    if isinstance(payload, Mapping):
        properties = schema.get("properties")
        repaired_map = dict(payload)
        if isinstance(properties, Mapping):
            for key, value in payload.items():
                if key in properties:
                    fixed, sub_notes, sub_full = _drop_the_padding(
                        value, properties[key], f"{path}/{key}"
                    )
                    repaired_map[key] = fixed
                    notes += sub_notes
                    still_full += sub_full
        for branch in schema.get("oneOf") or []:
            fixed, sub_notes, sub_full = _drop_the_padding(
                repaired_map, branch, path)
            if sub_notes and isinstance(fixed, Mapping):
                # The branch's repair was computed and then thrown away:
                # every feature is a `oneOf` of its kinds, so a padded list
                # inside a feature was reported dropped and never was.
                repaired_map = dict(fixed)
            notes += sub_notes
            still_full += sub_full
        return repaired_map, notes, still_full

    return payload, notes, still_full


class OllamaNativeProvider(Provider):
    """Talk to Ollama directly, so the schema actually constrains generation.

    Deliberately not a subclass of the OpenAI-compatible provider. That one
    carries schema dialects, reduction, fit planning and tool-call extraction,
    all of which exist to work around a transport that sends the schema as
    text. None of it applies here, and inheriting it would keep the workarounds
    alive in a place they cannot help.
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 900.0,
        context_window: int = 32768,
        keep_alive: str = "10m",
        temperature: float = 0.0,
        seed: int | None = 42,
        think: bool = False,
        retry: Any = None,
        budget: Any = None,
    ) -> None:
        super().__init__(retry=retry, budget=budget)
        self._model = model
        self._base_url = base_url.rstrip("/")
        if self._base_url.endswith("/v1"):
            raise ConfigurationError(
                "the native provider speaks Ollama's own API, not the "
                "OpenAI-compatible one",
                base_url=base_url,
                hint="drop the trailing /v1: use http://localhost:11434",
            )
        self._timeout = timeout
        self._context_window = context_window
        self._keep_alive = keep_alive
        self._temperature = temperature
        #: A fixed seed with temperature zero makes a run reproducible, which
        #: is what lets two answers to the same brief be compared at all. A
        #: caller who wants variety passes seed=None.
        self._seed = seed
        #: Thinking tokens are generated at the same speed as answer tokens
        #: and then discarded. On a machine producing three tokens a second
        #: that is minutes per call spent on text nobody reads.
        self._think = think
        self._last_prompt_tokens = 0
        #: Tokens of the reply written so far, while one is being written:
        #: what the progress line reports, so a wait shows what it is.
        self.tokens_so_far = 0

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="ollama-native",
            model=self._model,
            supports_structured_output=True,
            supports_system_prompt=True,
            is_remote=False,
            # Only the models that take pictures: a text model sent one
            # errors or ignores it.
            supports_images=bool(re.search(
                r"llava|vision|-vl|vl:|qwen2\.5vl|qwen3-vl|minicpm-v|bakllava|"
                r"gemma3:(?!1b)|moondream|granite3\.2-vision|mistral-small3",
                self._model.lower())),
            context_window=self._context_window,
            # The schema is sent whole and compiled to a grammar; nothing is
            # dropped to make it fit, because it costs no prompt space.
            schema_fidelity="exact",
        )

    # -- the wire ------------------------------------------------------

    def _post(self, route: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self._base_url + route,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        self.tokens_so_far = 0

        def written(count: int) -> None:
            self.tokens_so_far = count

        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                if payload.get("stream"):
                    return _read_the_stream(response, written)
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            body = error.read()[:400].decode("utf-8", "replace")
            hint = ("a 404 usually means the model name is not pulled; "
                    "`ollama list` shows what is")
            if error.code == 429:
                raise RateLimitError(
                    "Ollama is busy (429)", status=error.code, detail=body,
                ) from error
            if 400 <= error.code < 500:
                # A model that is not pulled, or a request Ollama will not
                # take, fails the same way four times over; it was retried
                # with backoff as if the server might recover.
                raise RequestError(
                    f"Ollama refused the request ({error.code})",
                    status=error.code, detail=body, hint=hint,
                ) from error
            raise TransientError(
                f"Ollama returned a server error ({error.code})",
                status=error.code,
                detail=body,
                hint=hint,
            ) from error
        except TimeoutError as error:
            raise RequestTimeoutError(
                "Ollama did not answer in time" if not self.tokens_so_far else
                f"Ollama went silent after {self.tokens_so_far} tokens",
                seconds=self._timeout,
                hint=(
                    "a local model on CPU can take many minutes for a "
                    "document; raise --timeout rather than retrying"
                ),
            ) from error
        except (OSError, http.client.HTTPException) as error:
            raise TransientError(
                "could not reach the Ollama endpoint",
                url=self._base_url + route,
                reason=str(error),
                hint="check `ollama serve` is running and the base URL is right",
            ) from error
        if len(raw) > MAX_RESPONSE_BYTES:
            raise StructuredOutputError(
                "the reply exceeded the response limit",
                limit_bytes=MAX_RESPONSE_BYTES,
            )
        try:
            return json.loads(raw)
        except ValueError as error:
            raise TransientError(
                "Ollama's reply was not JSON",
                detail=raw[:300].decode("utf-8", "replace"),
            ) from error

    def _send(self, request: ModelRequest) -> ModelResponse:
        if not request.schema:
            raise ConfigurationError(
                "the native provider requires a schema",
                hint=(
                    "the whole point of this transport is that the schema "
                    "becomes the decoding grammar; without one there is "
                    "nothing to enforce"
                ),
            )
        messages: list[dict[str, Any]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for message in request.messages:
            entry: dict[str, Any] = {"role": message.role,
                                     "content": message.content}
            if message.images and self.info.supports_images:
                import base64

                entry["images"] = [base64.b64encode(image).decode("ascii")
                                   for image in message.images]
            messages.append(entry)

        options: dict[str, Any] = {
            "num_ctx": self._context_window,
            "temperature": request.temperature
            if request.temperature is not None
            else self._temperature,
        }
        if request.max_output_tokens:
            options["num_predict"] = request.max_output_tokens
        if self._seed is not None:
            options["seed"] = self._seed
        if request.stop_sequences:
            options["stop"] = list(request.stop_sequences)

        bounded = bounded_for_grammar(dict(request.schema))
        started = time.time()
        data = self._post(
            "/api/chat",
            {
                "model": self._model,
                # Streamed: see `_read_the_stream`.
                "stream": True,
                "think": self._think,
                "keep_alive": self._keep_alive,
                # Bounded so the grammar permits an ending. See
                # `bounded_for_grammar`: without this the interpreter ran to
                # the output cap filling a list nothing told it to close.
                "format": bounded,
                "options": options,
                "messages": messages,
            },
        )
        latency = time.time() - started

        text = str((data.get("message") or {}).get("content", ""))
        reason = str(data.get("done_reason", ""))
        stop = _STOP_REASONS.get(reason, StopReason.OTHER)
        usage = Usage(
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
        )
        self._last_prompt_tokens = usage.input_tokens

        # The server says outright when it ran out of room, so this is
        # reported rather than inferred from a character count -- the estimate
        # Forge used to make, and got wrong in both directions.
        if stop is StopReason.MAX_TOKENS:
            # Returned as the truncation it is, not raised: raised as a
            # retryable error, the identical call was made four times under
            # the pinned seed -- four times the same cut-off bytes, 16 000
            # output tokens for nothing -- and the role never heard that it
            # had run out of room. Returned, the role asks again with more
            # room, exactly as it does for the Anthropic adapter.
            return ModelResponse(
                text=text,
                structured=None,
                usage=usage,
                provider=self.info.name,
                model=self._model,
                stop_reason=stop,
                latency_seconds=latency,
                request_fingerprint=request.fingerprint(),
                notes=(
                    f"the reply was cut off at the output limit of "
                    f"{request.max_output_tokens} tokens after "
                    f"{usage.output_tokens}. If the answer should have been "
                    "short, the schema is probably letting an array run "
                    "away: a grammar will fill an unbounded array forever "
                    "because nothing permits the closing bracket",),
                response_id=str(data.get("created_at", "")),
            )

        try:
            structured = json.loads(text)
        except ValueError as error:
            # Under a grammar this should be unreachable. If it happens the
            # grammar was not applied, which is the exact defect this provider
            # exists to remove -- so it is reported as itself, loudly, rather
            # than as a parse failure the repair loop would blame on the model.
            error = StructuredOutputError(
                "the reply was not JSON, which means the schema was not "
                "enforced as a grammar",
                # Retrying cannot fix a transport that ignores `format`: the
                # second attempt is answered by the same endpoint the same
                # way, and under a pinned seed it is the same bytes. Fail once
                # and say what to change.
                retryable=False,
                reply=text[:400],
                hint=(
                    "this endpoint accepted `format` but did not constrain "
                    "generation with it; check the Ollama version"
                ),
            )
            error.usage = usage
            raise error from None
        if not isinstance(structured, Mapping):
            error = StructuredOutputError(
                "the reply was JSON but not an object",
                # Deterministic settings make every retry bit-identical, so a
                # retry is only worth its minutes when the sampler can move.
                retryable=self._seed is None,
                reply=text[:200],
            )
            error.usage = usage
            raise error

        structured, notes, still_full = _drop_the_padding(structured, bounded)
        for full in still_full:
            # Deduplicating did not shorten it, so every entry is distinct and
            # the list may really have been cut off at the bound rather than
            # padded. That is a limitation of this transport, not a defect in
            # the answer, and it is reported rather than raised.
            #
            # Raising here was the wrong call and cost a good run. Three
            # reasons, each sufficient. The content is intact: every entry is
            # distinct and usable, so discarding the whole answer throws away
            # work to punish a ceiling Forge itself imposed. The retry cannot
            # help: `seed` and `temperature` are pinned, so all four attempts
            # are bit-identical by construction -- four times four to
            # twenty-five minutes of guaranteed-identical generation before
            # dying. And the downstream gates already catch the real harm: a
            # document whose feature list was truncated fails measurement and
            # routes to BLOCKED with a full report, which tells the reader
            # more than a transport-level crash ever could.
            #
            # The note is what keeps the answer from *looking* complete, which
            # was the legitimate worry. It lands in the run log next to the
            # role that produced it.
            notes.append(
                f"{full} -- every entry is distinct, so this list may have "
                f"been cut short at its ceiling rather than finished. Treat "
                f"it as possibly incomplete; raising the bound in "
                f"forge_models.ollama_native is the fix if it recurs."
            )

        return ModelResponse(
            text=text,
            structured=structured,
            usage=usage,
            provider=self.info.name,
            model=self._model,
            stop_reason=stop,
            latency_seconds=latency,
            request_fingerprint=request.fingerprint(),
            notes=tuple(notes),
            response_id=str(data.get("created_at", "")),
        )


__all__ = ["OllamaNativeProvider", "MAX_RESPONSE_BYTES"]
