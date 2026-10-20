"""The transport layer: retries, budgets, fixtures and provider adapters.

None of this touches the network. The HTTP boundary is exercised by feeding the
adapters the shapes a real API returns -- a forced tool call, a truncated
answer, a 429 with a ``retry-after`` -- and checking what the adapter makes of
them, which is where the interesting decisions live anyway.

The recurring theme is that a failure must arrive as the *right* failure. An
authentication error and a rate limit are both "the call did not work", and
treating them alike means either retrying something that will never succeed or
giving up on something that would have.
"""

from __future__ import annotations

import io
import json
import pathlib
import unittest
import urllib.error
import urllib.request
from typing import Any, Mapping

from forge_models import (
    AnthropicProvider,
    AuthenticationError,
    Budget,
    BudgetExceededError,
    CancellationToken,
    CancelledError,
    ConfigurationError,
    ContextTooLargeError,
    Fixture,
    FixtureLibrary,
    FixtureMissingError,
    FixtureProvider,
    Message,
    ModelError,
    ModelRequest,
    ModelResponse,
    OpenAICompatibleProvider,
    Provider,
    RateLimitError,
    RequestError,
    RequestTimeoutError,
    RetryPolicy,
    StopReason,
    StructuredOutputError,
    TransientError,
    Usage,
    user,
)
from forge_models.anthropic import _classify_http_error
from forge_models.openai_compatible import (
    _classify_http_error as _classify_openai_error,
)
from forge_models.schema_dialect import reduce_schema

SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _request(**kwargs: Any) -> ModelRequest:
    fields: dict[str, Any] = {
        "messages": (user("hello"),),
        "system": "be useful",
        "schema": SCHEMA,
        "schema_name": "result",
        "purpose": "test",
    }
    fields.update(kwargs)
    return ModelRequest(**fields)


def _response(**kwargs: Any) -> ModelResponse:
    fields: dict[str, Any] = {
        "text": "",
        "structured": {"answer": "42"},
        "usage": Usage(input_tokens=10, output_tokens=5),
        "provider": "stub",
        "model": "stub-1",
        "stop_reason": StopReason.COMPLETE,
        "latency_seconds": 0.01,
        "request_fingerprint": "f" * 32,
    }
    fields.update(kwargs)
    return ModelResponse(**fields)


class _Stub(Provider):
    """A provider that raises a scripted sequence, then answers."""

    def __init__(self, failures: list[Exception], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._failures = list(failures)
        self.attempts = 0

    @property
    def info(self):  # type: ignore[override]
        from forge_models import ProviderInfo

        return ProviderInfo(name="stub", model="stub-1")

    def _send(self, request: ModelRequest) -> ModelResponse:
        self.attempts += 1
        if self._failures:
            raise self._failures.pop(0)
        return _response()


class Fingerprints(unittest.TestCase):
    def test_the_same_request_fingerprints_the_same(self) -> None:
        self.assertEqual(_request().fingerprint(), _request().fingerprint())

    def test_a_changed_prompt_fingerprints_differently(self) -> None:
        """The property that stops a stale fixture answering a new prompt."""
        self.assertNotEqual(
            _request().fingerprint(),
            _request(system="be useful, briefly").fingerprint(),
        )

    def test_the_schema_is_part_of_the_identity(self) -> None:
        other = dict(SCHEMA) | {"required": []}
        self.assertNotEqual(
            _request().fingerprint(), _request(schema=other).fingerprint()
        )


class Retries(unittest.TestCase):
    def test_a_retryable_failure_is_retried(self) -> None:
        provider = _Stub(
            [TransientError("network hiccup")],
            retry=RetryPolicy(max_attempts=3, initial_delay=0.0, jitter=False),
        )
        response = provider.complete(_request())
        self.assertEqual(provider.attempts, 2)
        self.assertEqual(response.attempts, 2, "the retry was not recorded")

    def test_a_non_retryable_failure_is_not_retried(self) -> None:
        """Retrying a rejected key just spends time arriving at the same answer."""
        provider = _Stub(
            [AuthenticationError("bad key")],
            retry=RetryPolicy(max_attempts=4, initial_delay=0.0, jitter=False),
        )
        with self.assertRaises(AuthenticationError):
            provider.complete(_request())
        self.assertEqual(provider.attempts, 1)

    def test_attempts_are_bounded(self) -> None:
        provider = _Stub(
            [TransientError("x") for _ in range(10)],
            retry=RetryPolicy(max_attempts=3, initial_delay=0.0, jitter=False),
        )
        with self.assertRaises(TransientError):
            provider.complete(_request())
        self.assertEqual(provider.attempts, 3)

    def test_a_server_supplied_delay_is_honoured_but_capped(self) -> None:
        """Two ceilings, because they answer different questions: how long we
        are willing to guess, and how long we are willing to be told."""
        policy = RetryPolicy(maximum_delay=30.0, maximum_retry_after=120.0)
        self.assertEqual(policy.delay_for(1, retry_after=5.0), 5.0)
        self.assertEqual(policy.delay_for(1, retry_after=59.5), 59.5)
        self.assertEqual(policy.delay_for(1, retry_after=3600.0), 120.0)

    def test_backoff_grows_and_stays_under_the_ceiling(self) -> None:
        policy = RetryPolicy(initial_delay=1.0, multiplier=2.0, maximum_delay=8.0,
                             jitter=False)
        self.assertEqual(
            [policy.delay_for(n) for n in range(1, 6)], [1.0, 2.0, 4.0, 8.0, 8.0]
        )

    def test_jitter_spreads_retries(self) -> None:
        """Synchronised retries after a shared rate limit arrive together."""
        policy = RetryPolicy(initial_delay=4.0, jitter=True)
        delays = {policy.delay_for(2) for _ in range(40)}
        self.assertGreater(len(delays), 30)
        self.assertTrue(all(0.0 <= d <= 4.0 * 2.4 for d in delays))

    def test_cancellation_stops_between_attempts(self) -> None:
        token = CancellationToken()
        token.cancel()
        provider = _Stub([], retry=RetryPolicy(max_attempts=2))
        with self.assertRaises(CancelledError):
            provider.complete(_request(), cancellation=token)
        self.assertEqual(provider.attempts, 0)


class Budgets(unittest.TestCase):
    def test_a_call_that_would_exceed_the_token_budget_never_leaves(self) -> None:
        provider = _Stub([], budget=Budget(max_total_tokens=10))
        with self.assertRaises(BudgetExceededError):
            provider.complete(_request(max_output_tokens=4096))
        self.assertEqual(provider.attempts, 0, "the budget was checked too late")

    def test_the_call_budget_stops_the_run(self) -> None:
        provider = _Stub([], budget=Budget(max_calls=2, max_total_tokens=None))
        provider.complete(_request())
        provider.complete(_request())
        with self.assertRaises(BudgetExceededError) as caught:
            provider.complete(_request())
        self.assertEqual(caught.exception.detail["limit"], 2)

    def test_usage_accumulates_across_calls(self) -> None:
        provider = _Stub([], budget=Budget(max_total_tokens=None, max_calls=None))
        provider.complete(_request())
        provider.complete(_request())
        self.assertEqual(provider.budget.usage.total_tokens, 30)

    def test_budget_exhaustion_is_not_retryable(self) -> None:
        self.assertFalse(BudgetExceededError("spent").retryable)


class Fixtures(unittest.TestCase):
    def _library(self, directory: str) -> FixtureLibrary:
        library = FixtureLibrary(directory)
        library.add(
            Fixture(
                fingerprint=_request().fingerprint(),
                purpose="test",
                request={},
                response={
                    "text": "",
                    "structured": {"answer": "42"},
                    "model": "recorded",
                    "stop_reason": "complete",
                    "usage": {"input_tokens": 7, "output_tokens": 3},
                },
                recorded_at=0.0,
            )
        )
        return library

    def test_a_recorded_response_replays(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            provider = FixtureProvider(self._library(directory))
            response = provider.complete(_request())
        self.assertEqual(response.structured, {"answer": "42"})
        self.assertTrue(response.from_fixture)
        self.assertEqual(response.usage.input_tokens, 7)

    def test_a_miss_is_an_error_rather_than_a_near_match(self) -> None:
        """Answering a changed prompt from a nearby fixture is how a prompt
        change passes tests it was never run against."""
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            provider = FixtureProvider(self._library(directory))
            with self.assertRaises(FixtureMissingError) as caught:
                provider.complete(_request(system="different"))
        self.assertIn("known_purposes", caught.exception.detail)

    def test_a_library_survives_a_round_trip_through_disk(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            self._library(directory)
            reloaded = FixtureLibrary(directory)
            self.assertEqual(len(reloaded), 1)
            self.assertIn(_request().fingerprint(), reloaded)

    def test_recording_does_not_reorder_what_it_records(self) -> None:
        """A tidied fixture breaks replay of every call after the first.

        The recorded answer feeds the next prompt, so reordering its keys
        changes that prompt's text and therefore its fingerprint.
        """
        import tempfile

        ordered = {"zebra": 1, "alpha": 2, "middle": 3}
        with tempfile.TemporaryDirectory() as directory:
            library = FixtureLibrary(directory)
            path = library.add(
                Fixture(
                    fingerprint="f" * 32,
                    purpose="test",
                    request={},
                    response={"structured": ordered},
                    recorded_at=0.0,
                )
            )
            written = path.read_text(encoding="utf-8")
        self.assertLess(
            written.index("zebra"), written.index("alpha"), "keys were sorted"
        )


class AnthropicAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = AnthropicProvider(api_key="test-key-not-real")

    def test_a_schema_becomes_a_forced_tool_call(self) -> None:
        """Structured output by forced tool use, not by asking nicely for JSON.

        The tool is named `submit_...`, not for the role: a tool named for the
        role reads as a worker to delegate to, and a small model will call it
        with the input instead of with an answer. Observed live.
        """
        provider = AnthropicProvider(api_key="test-key-not-real",
                                     thinking="off")
        payload = provider._build_payload(_request())
        self.assertEqual(
            payload["tool_choice"], {"type": "tool", "name": "submit_result"}
        )
        self.assertEqual(payload["tools"][0]["input_schema"], SCHEMA)

    def test_no_tools_are_sent_when_no_schema_is_wanted(self) -> None:
        payload = self.provider._build_payload(_request(schema=None))
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)

    def test_the_key_is_not_in_the_request_body(self) -> None:
        self.assertNotIn("test-key-not-real", json.dumps(
            self.provider._build_payload(_request())
        ))

    def test_the_key_is_not_in_the_provider_description(self) -> None:
        """Provenance records that a remote provider was used, never which key."""
        self.assertNotIn(
            "test-key-not-real", json.dumps(self.provider.info.as_dict())
        )

    def test_a_missing_key_is_a_configuration_error_not_a_failed_call(self) -> None:
        with self.assertRaises(ConfigurationError) as caught:
            AnthropicProvider(api_key="")._require_key()
        self.assertIn("ANTHROPIC_API_KEY", str(caught.exception))

    def test_a_tool_use_block_becomes_structured_output(self) -> None:
        response = self.provider._parse(
            _request(),
            {
                "id": "msg_1",
                "model": "claude-x",
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 11, "output_tokens": 4},
                "content": [
                    {"type": "text", "text": "thinking"},
                    {"type": "tool_use", "input": {"answer": "42"}},
                ],
            },
            0.5,
        )
        self.assertEqual(response.structured, {"answer": "42"})
        self.assertEqual(response.text, "thinking")
        self.assertEqual(response.usage.input_tokens, 11)
        self.assertIsNotNone(response.usage.cost_usd)

    def test_a_truncated_answer_says_so_rather_than_returning_nothing(self) -> None:
        """Cut off before the tool call: returned as the truncation it is,
        so the role asks again with more room. Raised as a transport error,
        it was sent again unchanged -- and a model that thinks first is cut
        off at the same place every time."""
        response = self.provider._parse(
            _request(),
            {
                "stop_reason": "max_tokens",
                "usage": {"input_tokens": 1, "output_tokens": 4096},
                "content": [{"type": "text", "text": "{\"answ"}],
            },
            0.5,
        )
        self.assertTrue(response.is_truncated)
        self.assertIsNone(response.structured)
        self.assertEqual(response.usage.output_tokens, 4096)

    def test_cached_input_tokens_are_counted_separately(self) -> None:
        response = self.provider._parse(
            _request(schema=None),
            {
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "cache_read_input_tokens": 900,
                },
                "content": [{"type": "text", "text": "ok"}],
            },
            0.1,
        )
        self.assertEqual(response.usage.cached_input_tokens, 900)

    def test_tokens_written_to_the_cache_are_input_too(self) -> None:
        # The API counts a cache write apart from `input_tokens`; it is
        # fresh input all the same, and the budget and the cost must see it.
        response = self.provider._parse(
            _request(schema=None),
            {
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "cache_creation_input_tokens": 30_000,
                },
                "content": [{"type": "text", "text": "ok"}],
            },
            0.1,
        )
        self.assertEqual(response.usage.input_tokens, 30_003)
        self.assertGreater(response.usage.total_tokens, 30_000)


class OpenAICompatibleAdapter(unittest.TestCase):
    """Three levels of structured-output support, and no silent demotion."""

    def _payload(self, mode: str) -> dict[str, Any]:
        provider = OpenAICompatibleProvider(
            model="local", structured_mode=mode, api_key="x"  # type: ignore[arg-type]
        )
        return provider._build_payload(_request())  # noqa: SLF001

    def test_json_schema_mode_asks_for_constrained_decoding(self) -> None:
        payload = self._payload("json_schema")
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(payload["response_format"]["json_schema"]["schema"], SCHEMA)

    def test_tools_mode_forces_the_function(self) -> None:
        payload = self._payload("tools")
        self.assertEqual(
            payload["tool_choice"],
            {"type": "function", "function": {"name": "submit_result"}},
        )
        self.assertEqual(payload["tools"][0]["function"]["parameters"], SCHEMA)

    def test_json_object_mode_carries_the_schema_in_the_prompt(self) -> None:
        """The weakest level: the endpoint promises only 'some JSON'."""
        payload = self._payload("json_object")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertIn("Required output shape", payload["messages"][0]["content"])

    def test_only_the_weakest_mode_is_reported_as_unguaranteed(self) -> None:
        for mode, guaranteed in (
            ("json_schema", True),
            ("tools", True),
            ("json_object", False),
        ):
            provider = OpenAICompatibleProvider(
                model="local", structured_mode=mode  # type: ignore[arg-type]
            )
            self.assertEqual(provider.info.supports_structured_output, guaranteed)

    def test_a_misspelled_mode_raises_rather_than_quietly_degrading(self) -> None:
        """`tool` is the obvious typo for `tools`, and it used to fall through
        to the weakest mode — producing prose-wrapped JSON and a parse failure
        that reads like the model's fault."""
        with self.assertRaises(ConfigurationError) as caught:
            self._payload("tool")
        self.assertIn("tools", caught.exception.detail["supported"])

    def test_a_local_endpoint_is_not_recorded_as_remote(self) -> None:
        """`is_remote` is what tells a report whether design data left the box."""
        provider = OpenAICompatibleProvider(model="local", is_remote=False)
        self.assertFalse(provider.info.is_remote)


class HttpErrorClassification(unittest.TestCase):
    def _error(
        self, status: int, message: str = "", headers: dict[str, str] | None = None
    ) -> urllib.error.HTTPError:
        body = json.dumps({"error": {"message": message, "type": "some_type"}})
        return urllib.error.HTTPError(
            url="https://example.invalid",
            code=status,
            msg="error",
            hdrs=headers or {},  # type: ignore[arg-type]
            fp=io.BytesIO(body.encode("utf-8")),
        )

    def test_a_rejected_credential_is_not_retried(self) -> None:
        for status in (401, 403):
            error = _classify_http_error(self._error(status))
            self.assertIsInstance(error, AuthenticationError)
            self.assertFalse(error.retryable)

    def test_a_rate_limit_carries_its_retry_after(self) -> None:
        error = _classify_http_error(
            self._error(429, headers={"retry-after": "12"})
        )
        self.assertIsInstance(error, RateLimitError)
        self.assertTrue(error.retryable)
        self.assertEqual(error.retry_after, 12.0)

    def test_an_oversized_prompt_is_its_own_failure(self) -> None:
        """Distinct from a generic 400, because the remedy is different."""
        error = _classify_http_error(self._error(400, "prompt is too long: 1M tokens"))
        self.assertIsInstance(error, ContextTooLargeError)
        self.assertFalse(error.retryable)

    def test_a_retired_model_identifier_says_how_to_fix_it(self) -> None:
        """The most likely first-run failure, and the least self-explanatory."""
        error = _classify_http_error(self._error(404, "model not found"))
        self.assertIsInstance(error, RequestError)
        self.assertIn("--model", error.detail["hint"])

    def test_other_client_errors_are_request_errors(self) -> None:
        error = _classify_http_error(self._error(422, "unprocessable"))
        self.assertIsInstance(error, RequestError)
        self.assertFalse(error.retryable)

    def test_server_errors_are_retryable(self) -> None:
        for status in (500, 502, 529):
            error = _classify_http_error(self._error(status))
            self.assertIsInstance(error, TransientError)
            self.assertTrue(error.retryable)

    def test_an_unparseable_error_body_still_classifies(self) -> None:
        broken = urllib.error.HTTPError(
            url="https://example.invalid",
            code=500,
            msg="error",
            hdrs={},  # type: ignore[arg-type]
            fp=io.BytesIO(b"<html>gateway</html>"),
        )
        self.assertIsInstance(_classify_http_error(broken), TransientError)


class Messages(unittest.TestCase):
    def test_a_message_round_trips(self) -> None:
        self.assertEqual(
            Message("user", "hi").as_dict(), {"role": "user", "content": "hi"}
        )

    def test_input_estimation_is_crude_and_conservative(self) -> None:
        """Its only job is catching a request that is obviously far too large."""
        request = _request(messages=(user("x" * 4000),))
        self.assertGreater(request.approximate_input_tokens(), 500)



class AClaudeThatCanThinkIsLetThink(unittest.TestCase):
    """A forced tool call is answered at once: "where forced tool use is
    accepted, it skips thinking". Every design Forge asked Claude Sonnet 5
    for was written in one pass, with no room to work it out -- and the
    run read like a model that could not draw: holes spaced across a rail
    narrower than their spacing, a midpoint worked out wrong, a repair whose
    diagnosis read "placeholder". Where the model can think, it thinks, and
    the tool is offered rather than forced."""

    def _call(self, *args, **kwargs):
        return TheAnthropicCallTheNewerModelsAccept._provider(
            self, *args, **kwargs)

    def test_each_model_thinks_the_way_it_can(self) -> None:
        from forge_models.anthropic import _thinking_for

        for model, mode in (
                ("claude-sonnet-5", "adaptive"), ("claude-opus-5-5", "adaptive"),
                ("claude-sonnet-4-6", "adaptive"), ("claude-opus-4-7", "adaptive"),
                ("claude-fable-5", "adaptive"), ("claude-haiku-4-5", "enabled"),
                ("claude-sonnet-4-20250514", "enabled"),
                ("claude-opus-4-1", "enabled"), ("claude-3-7-sonnet-latest",
                                                 "enabled"),
                ("claude-3-5-sonnet-20241022", "off"),
                ("claude-3-haiku-20240307", "off")):
            self.assertEqual(_thinking_for(model), mode, model)

    def test_sonnet_5_thinks_and_is_offered_the_tool(self) -> None:
        provider = AnthropicProvider(api_key="k", model="claude-sonnet-5")
        payload = provider._build_payload(_request(max_output_tokens=16384))
        self.assertEqual(payload["thinking"], {"type": "adaptive"})
        self.assertEqual(payload["tool_choice"], {"type": "auto"})
        self.assertGreaterEqual(payload["max_tokens"], 16384 + 16000)
        self.assertNotIn("temperature", payload)
        self.assertIn("no placeholder", payload["system"][0]["text"])
        self.assertEqual(provider.info.thinking, "adaptive")

    def test_an_effort_is_sent_where_it_is_asked_for(self) -> None:
        payload = AnthropicProvider(
            api_key="k", model="claude-sonnet-5", effort="high",
        )._build_payload(_request())
        self.assertEqual(payload["output_config"], {"effort": "high"})

    def test_an_older_model_thinks_to_a_budget(self) -> None:
        payload = AnthropicProvider(
            api_key="k", model="claude-sonnet-4-20250514",
        )._build_payload(_request(max_output_tokens=4096))
        self.assertEqual(payload["thinking"]["type"], "enabled")
        self.assertLess(payload["thinking"]["budget_tokens"],
                        payload["max_tokens"])
        self.assertNotIn("temperature", payload)

    def test_a_call_with_no_schema_is_not_made_to_think(self) -> None:
        payload = AnthropicProvider(
            api_key="k", model="claude-sonnet-5",
        )._build_payload(_request(schema=None))
        self.assertNotIn("thinking", payload)

    def test_off_is_the_old_forced_call(self) -> None:
        payload = AnthropicProvider(
            api_key="k", model="claude-sonnet-5", thinking="off",
        )._build_payload(_request())
        self.assertNotIn("thinking", payload)
        self.assertEqual(payload["tool_choice"]["type"], "tool")

    def test_a_refused_thinking_steps_down_and_is_remembered(self) -> None:
        provider, sent, patch = self._call(
            "claude-new-9",
            [("thinking.type: adaptive is not supported",
              lambda b: b.get("thinking", {}).get("type") == "adaptive"),
             ("thinking is not supported on this model",
              lambda b: b.get("thinking", {}).get("type") == "enabled")],
            thinking=None)
        with patch:
            response = provider._send(_request())
        self.assertEqual(response.structured, {"answer": 1})
        self.assertEqual([b.get("thinking", {}).get("type") for b in sent],
                         ["adaptive", "enabled", None])
        self.assertEqual(sent[-1]["tool_choice"]["type"], "tool")
        self.assertEqual(provider.info.thinking, "off")

    def test_a_refused_effort_is_dropped(self) -> None:
        provider, sent, patch = self._call(
            "claude-sonnet-5",
            [("output_config.effort: xhigh is not supported",
              lambda b: "output_config" in b)], thinking="adaptive")
        provider._effort = "xhigh"
        with patch:
            provider._send(_request())
        self.assertEqual(["output_config" in b for b in sent], [True, False])
        self.assertIn("thinking", sent[-1])

    def test_an_answer_in_words_is_asked_for_in_the_tool(self) -> None:
        thought = {"type": "thinking", "thinking": "the hole is 15 mm in",
                   "signature": "sig"}
        provider, sent, patch = self._call(
            "claude-sonnet-5", [], thinking="adaptive", replies=[
                {"content": [thought, {"type": "text",
                                       "text": "I will now submit."}],
                 "stop_reason": "end_turn",
                 "usage": {"input_tokens": 100, "output_tokens": 50}},
                {"content": [{"type": "tool_use", "name": "submit_result",
                              "input": {"answer": "15"}}],
                 "stop_reason": "tool_use",
                 "usage": {"input_tokens": 160, "output_tokens": 9}}])
        with patch:
            response = provider._send(_request())
        self.assertEqual(response.structured, {"answer": "15"})
        self.assertEqual(len(sent), 2)
        # its thinking handed back exactly as it came
        self.assertEqual(sent[1]["messages"][-2]["content"][0], thought)
        self.assertIn("submit_result", sent[1]["messages"][-1]["content"])
        self.assertEqual(response.usage.input_tokens, 260)
        self.assertEqual(response.usage.output_tokens, 59)

    def test_an_answer_written_as_json_in_the_text_is_the_answer(self) -> None:
        provider = AnthropicProvider(api_key="k", model="claude-sonnet-5")
        response = provider._parse(_request(), {
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "thinking", "thinking": "..."},
                        {"type": "text", "text":
                         'Here it is: {"answer": "a plate"} -- done.'}]}, 0.1)
        self.assertEqual(response.structured, {"answer": "a plate"})

    def _stream(self, events, ending=True):
        lines = []
        for kind, data in events:
            lines.append(f"event: {kind}\n")
            lines.append(f"data: {json.dumps(data)}\n\n")
        if ending:
            lines.append("event: message_stop\n")
            lines.append('data: {"type": "message_stop"}\n\n')
        return "".join(lines).encode()

    def _served(self, body):
        from unittest import mock

        seen = {}

        def fake(request, timeout=None):
            seen["timeout"] = timeout
            seen["body"] = json.loads(request.data)
            return mock.MagicMock(__enter__=lambda s: io.BytesIO(body),
                                  __exit__=lambda s, *a: False)

        provider = AnthropicProvider(api_key="k", model="claude-sonnet-5",
                                     timeout=600.0)
        return provider, seen, mock.patch(
            "forge_models.anthropic.urllib.request.urlopen", fake)

    def test_a_reply_is_streamed_and_put_back_together(self) -> None:
        """The leg shell's designer was cut off at 600 s and asked again
        from the start, its analyst twice, its redesign twice: 65 minutes.
        Streamed, the timeout is the longest silence, not the longest
        answer."""
        events = [
            ("message_start", {"type": "message_start", "message": {
                "id": "m1", "model": "claude-sonnet-5", "content": [],
                "usage": {"input_tokens": 120, "output_tokens": 1}}}),
            ("content_block_start", {"type": "content_block_start",
                                     "index": 0, "content_block": {
                                         "type": "thinking", "thinking": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "thinking_delta",
                                               "thinking": "the hole is "}}),
            ("ping", {"type": "ping"}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "thinking_delta",
                                               "thinking": "15 mm in"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "signature_delta",
                                               "signature": "abc"}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("content_block_start", {"type": "content_block_start",
                                     "index": 1, "content_block": {
                                         "type": "tool_use", "id": "t1",
                                         "name": "submit_result",
                                         "input": {}}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 1,
                                     "delta": {"type": "input_json_delta",
                                               "partial_json": '{"ans'}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 1,
                                     "delta": {"type": "input_json_delta",
                                               "partial_json": 'wer": "15"}'}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 1}),
            ("message_delta", {"type": "message_delta",
                               "delta": {"stop_reason": "tool_use"},
                               "usage": {"output_tokens": 77}})]
        provider, seen, patch = self._served(self._stream(events))
        with patch:
            response = provider._send(_request())
        self.assertTrue(seen["body"]["stream"])
        self.assertLessEqual(seen["timeout"], 300.0)
        self.assertEqual(response.structured, {"answer": "15"})
        self.assertEqual(response.usage.input_tokens, 120)
        self.assertEqual(response.usage.output_tokens, 77)

    def test_a_stream_cut_short_is_a_dropped_connection(self) -> None:
        from forge_models.errors import TransientError

        events = [("message_start", {"type": "message_start", "message": {
            "id": "m", "content": [], "usage": {"input_tokens": 3}}})]
        provider, _, patch = self._served(self._stream(events, ending=False))
        with patch, self.assertRaises(TransientError) as caught:
            provider._send(_request())
        self.assertTrue(caught.exception.retryable)

    def test_an_overload_mid_answer_is_retried(self) -> None:
        from forge_models.errors import TransientError

        events = [("message_start", {"type": "message_start", "message": {
                      "id": "m", "content": [], "usage": {}}}),
                  ("error", {"type": "error", "error": {
                      "type": "overloaded_error", "message": "Overloaded"}})]
        provider, _, patch = self._served(self._stream(events, ending=False))
        with patch, self.assertRaises(TransientError) as caught:
            provider._send(_request())
        self.assertTrue(caught.exception.retryable)

    def test_a_cut_off_answer_reads_as_a_truncation(self) -> None:
        events = [
            ("message_start", {"type": "message_start", "message": {
                "id": "m", "content": [], "usage": {"input_tokens": 5}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "tool_use",
                                                       "id": "t",
                                                       "name": "submit_result",
                                                       "input": {}}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "input_json_delta",
                                               "partial_json": '{"answer": "a'}}),
            ("message_delta", {"type": "message_delta",
                               "delta": {"stop_reason": "max_tokens"},
                               "usage": {"output_tokens": 4096}})]
        provider, _, patch = self._served(self._stream(events))
        with patch:
            response = provider._send(_request())
        self.assertTrue(response.is_truncated)
        self.assertIsNone(response.structured)

    def test_an_unreachable_network_is_waited_out(self) -> None:
        from unittest import mock
        import urllib.error

        from forge_models.provider import RetryPolicy

        sleeps = []
        calls = {"n": 0}

        def fake(request, timeout=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError("[Errno 11001] getaddrinfo failed")
            reply = json.dumps({
                "content": [{"type": "tool_use", "name": "submit_result",
                             "input": {"answer": 1}}],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
            return mock.MagicMock(__enter__=lambda s: io.BytesIO(reply),
                                  __exit__=lambda s, *a: False)

        provider = AnthropicProvider(api_key="k", model="claude-sonnet-5",
                                     retry=RetryPolicy(jitter=False))
        with mock.patch("forge_models.anthropic.urllib.request.urlopen", fake), \
                mock.patch("forge_models.provider.time.sleep", sleeps.append):
            response = provider.complete(_request())
        self.assertEqual(response.structured, {"answer": 1})
        self.assertGreaterEqual(sum(sleeps), 15.0)

    def test_the_cli_takes_it(self) -> None:
        from forge_cli.design import build_provider
        import argparse
        import os

        args = argparse.Namespace(
            provider="anthropic", model="claude-sonnet-5",
            schema_dialect="json_schema", timeout=300.0, max_tokens=1000,
            max_calls=5, max_cost=None, record=None, thinking="off",
            effort="low")
        old = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "not-a-real-key"
        try:
            provider = build_provider(args)
        finally:
            if old is None:
                del os.environ["ANTHROPIC_API_KEY"]
            else:
                os.environ["ANTHROPIC_API_KEY"] = old
        self.assertEqual(provider.info.thinking, "off")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class SchemaDialects(unittest.TestCase):
    """Sending less schema when an endpoint cannot take it all -- and saying so.

    Found by the first live run against a third-party endpoint: it answered the
    small prompts and rejected the designer's 45 KB, 22-level schema with a bare
    400. The fix is not to weaken what Forge checks -- the decoder and the
    compiler are unchanged and unaware -- but to let the transport carry less,
    visibly.
    """

    NESTED: Mapping[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "title": "Document",
        "additionalProperties": False,
        "properties": {
            "kind": {"const": "box"},
            "size": {"type": "number", "minimum": 0},
            "feature": {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {"a": {"type": "string"}},
                        "additionalProperties": False,
                    },
                    {"type": "object", "properties": {"b": {"type": "string"}}},
                ],
                "description": "one feature",
            },
        },
        "required": ["kind"],
    }

    def test_the_default_dialect_changes_nothing(self) -> None:
        reduced = reduce_schema(self.NESTED, "json_schema")
        self.assertTrue(reduced.lossless)
        self.assertEqual(reduced.fidelity, "exact")
        self.assertEqual(reduced.schema, self.NESTED)
        self.assertEqual(reduced.note(), "")

    def test_the_openapi_dialect_keeps_the_fields_and_drops_the_keywords(
        self,
    ) -> None:
        """The failure that made this test exist: an early version filtered the
        keys of `properties`, deleting the document's fields rather than the
        schema's keywords, and turned 45 KB into 91 bytes."""
        reduced = reduce_schema(self.NESTED, "openapi")
        self.assertEqual(
            sorted(reduced.schema["properties"]), ["feature", "kind", "size"]
        )
        self.assertNotIn("additionalProperties", json.dumps(reduced.schema))
        self.assertNotIn("$schema", reduced.schema)
        self.assertIn("$schema", reduced.dropped)

    def test_a_const_survives_as_a_one_value_enum(self) -> None:
        """Same constraint, expressible in the subset."""
        reduced = reduce_schema(self.NESTED, "openapi")
        self.assertEqual(reduced.schema["properties"]["kind"], {"enum": ["box"]})

    def test_a_oneof_becomes_an_anyof(self) -> None:
        reduced = reduce_schema(self.NESTED, "openapi")
        self.assertIn("anyOf", reduced.schema["properties"]["feature"])
        self.assertIn("oneOf->anyOf", reduced.dropped)

    def test_required_names_are_not_treated_as_keywords(self) -> None:
        reduced = reduce_schema(self.NESTED, "openapi")
        self.assertEqual(reduced.schema["required"], ["kind"])

    def test_the_opaque_dialect_collapses_unions(self) -> None:
        reduced = reduce_schema(self.NESTED, "opaque")
        feature = reduced.schema["properties"]["feature"]
        self.assertEqual(feature["type"], "object")
        self.assertNotIn("anyOf", feature)
        self.assertEqual(feature["description"], "one feature")
        self.assertEqual(reduced.fidelity, "collapsed")

    def test_a_reduction_is_never_silent(self) -> None:
        """The point of the whole module: what was lost is on the record."""
        reduced = reduce_schema(self.NESTED, "opaque")
        self.assertFalse(reduced.lossless)
        self.assertIn("collapsed", reduced.note())
        self.assertIn("enforced locally", reduced.note())
        self.assertGreater(reduced.original_bytes, reduced.sent_bytes)

    def test_the_provider_reports_the_fidelity_it_used(self) -> None:
        provider = OpenAICompatibleProvider(
            model="local", structured_mode="tools", schema_dialect="opaque"
        )
        self.assertEqual(provider.info.schema_fidelity, "exact", "before any call")
        provider._build_payload(_request())  # noqa: SLF001
        self.assertEqual(provider.info.schema_fidelity, "reduced")
        self.assertIn("schema_fidelity", provider.info.as_dict())

    def test_a_real_designer_schema_shrinks_enough_to_be_worth_it(self) -> None:
        from forge_roles.library import ForgeIRDesigner

        full = ForgeIRDesigner().output_schema()
        opaque = reduce_schema(full, "opaque")
        self.assertLess(opaque.sent_bytes, opaque.original_bytes // 4)
        self.assertIn("document", opaque.schema["properties"])


class SchemaComplaints(unittest.TestCase):
    def test_a_400_never_reports_nothing(self) -> None:
        """A 400 whose body this code cannot parse still has to say what came
        back. The first live failure reported `detail: ""` and left the only
        useful fact on the floor."""
        error = urllib.error.HTTPError(
            url="https://example.invalid",
            code=400,
            msg="error",
            hdrs={},  # type: ignore[arg-type]
            fp=io.BytesIO(b"<html>Bad Request: unsupported field</html>"),
        )
        classified = _classify_openai_error(error)
        self.assertIn("Bad Request", classified.detail["body"])

    def test_a_schema_complaint_names_the_flag_that_fixes_it(self) -> None:
        body = json.dumps(
            {
                "error": {
                    "message": (
                        "Invalid JSON payload received. Unknown name "
                        "\"additionalProperties\" at 'tools[0].function_"
                        "declarations[0].parameters'"
                    )
                }
            }
        ).encode("utf-8")
        error = urllib.error.HTTPError(
            url="https://example.invalid",
            code=400,
            msg="error",
            hdrs={},  # type: ignore[arg-type]
            fp=io.BytesIO(body),
        )
        classified = _classify_openai_error(error)
        self.assertIn("schema", classified.message)
        self.assertIn("--schema-dialect", classified.detail["hint"])

    def test_an_array_wrapped_error_body_is_unwrapped(self) -> None:
        """Google's OpenAI-compatible endpoint answers `[{"error": {...}}]`.

        Missing the array cost a real diagnosis: the message was lost, the raw
        preview was matched against the schema heuristic instead, the word
        INVALID_ARGUMENT hit, and a missing API key was reported as a schema
        problem with a confident recommendation to change the dialect.
        """
        body = json.dumps(
            [
                {
                    "error": {
                        "code": 400,
                        "message": "Missing or invalid Authorization header.",
                        "status": "INVALID_ARGUMENT",
                    }
                }
            ]
        ).encode("utf-8")
        error = urllib.error.HTTPError(
            url="https://example.invalid",
            code=400,
            msg="error",
            hdrs={},  # type: ignore[arg-type]
            fp=io.BytesIO(body),
        )
        classified = _classify_openai_error(error)
        self.assertIsInstance(classified, AuthenticationError)
        self.assertIn("Authorization header", classified.detail["detail"])
        self.assertIn("environment variable", classified.detail["hint"])

    def test_a_generic_status_word_is_not_a_schema_complaint(self) -> None:
        """INVALID_ARGUMENT is the status for every bad request. A heuristic
        that fires on it is worse than none, because it is believed."""
        body = json.dumps(
            {"error": {"message": "Request contains an invalid argument."}}
        ).encode("utf-8")
        error = urllib.error.HTTPError(
            url="https://example.invalid",
            code=400,
            msg="error",
            hdrs={},  # type: ignore[arg-type]
            fp=io.BytesIO(body),
        )
        classified = _classify_openai_error(error)
        self.assertNotIn("schema", classified.message)
        self.assertNotIn("hint", classified.detail)


class FailedCallsStillCost(unittest.TestCase):
    """A call that produced an unusable answer was still paid for.

    Found live: a requirements call came back with MALFORMED_FUNCTION_CALL,
    was retried four times, and the run reported 1,160 tokens -- the interpreter
    alone. Roughly 16,000 had been spent.
    """

    class _Wasteful(Provider):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.calls = 0

        @property
        def info(self):  # type: ignore[override]
            from forge_models import ProviderInfo

            return ProviderInfo(name="wasteful", model="w")

        def _send(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            error = StructuredOutputError("nothing usable came back")
            error.usage = Usage(input_tokens=1000, output_tokens=500)
            raise error

    def test_the_budget_counts_calls_that_failed(self) -> None:
        provider = self._Wasteful(
            retry=RetryPolicy(max_attempts=3, initial_delay=0.0, jitter=False),
            budget=Budget(max_total_tokens=None, max_calls=None),
        )
        with self.assertRaises(StructuredOutputError):
            provider.complete(_request())
        self.assertEqual(provider.calls, 3)
        self.assertEqual(
            provider.budget.usage.total_tokens,
            4500,
            "three failed attempts were spent and not counted",
        )

    def test_a_malformed_function_call_is_not_retried(self) -> None:
        """It fails identically every time; four attempts buy only delay."""
        error = StructuredOutputError("x", retryable=False)
        self.assertFalse(error.retryable)
        self.assertTrue(StructuredOutputError("x").retryable)

    def test_the_malformed_case_names_the_flag_that_helps(self) -> None:
        provider = OpenAICompatibleProvider(
            model="m", structured_mode="tools", api_key="x"
        )
        with self.assertRaises(StructuredOutputError) as caught:
            provider._parse(  # noqa: SLF001
                _request(),
                {
                    "choices": [
                        {
                            "message": {"content": ""},
                            "finish_reason": (
                                "function_call_filter: MALFORMED_FUNCTION_CALL"
                            ),
                        }
                    ],
                    "usage": {"prompt_tokens": 2657, "completion_tokens": 1558},
                },
                1.0,
            )
        self.assertFalse(caught.exception.retryable)
        self.assertIn("--schema-dialect opaque", caught.exception.detail["hint"])
        self.assertEqual(caught.exception.usage.total_tokens, 4215)

    def test_the_anthropic_adapter_also_carries_the_cost_of_a_failure(self) -> None:
        """Caught by writing this test: an edit had left the error constructed
        and never raised, so a response with no tool call would have returned
        `structured=None` to a caller that requires it."""
        provider = AnthropicProvider(api_key="x")
        with self.assertRaises(StructuredOutputError) as caught:
            provider._parse(  # noqa: SLF001
                _request(),
                {
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 10, "output_tokens": 4096},
                    "content": [{"type": "text", "text": "{"}],
                },
                0.1,
            )
        self.assertEqual(caught.exception.usage.total_tokens, 4106)

    def test_the_escalation_path_exists_on_both_adapters(self) -> None:
        """A dialect flag that works on one provider is not an escalation path;
        it is a reason to change provider at the worst possible moment."""
        from forge_roles.library import ForgeIRDesigner

        request = _request(schema=ForgeIRDesigner().output_schema())
        anthropic = AnthropicProvider(api_key="x", schema_dialect="opaque")
        payload = anthropic._build_payload(request)  # noqa: SLF001
        self.assertLess(
            len(json.dumps(payload["tools"][0]["input_schema"])), 10_000
        )
        self.assertEqual(anthropic.info.schema_fidelity, "collapsed")


class RateLimitAdvice(unittest.TestCase):
    """An endpoint that says when to come back knows something we do not.

    Observed live: a free-tier quota answered 429 with "Please retry in
    59.549108345s". The delay was in the message rather than a Retry-After
    header, so it was thrown away; the fallback guess was then capped at 30
    seconds, which lands inside the same exhausted minute. Every retry failed
    for a reason the endpoint had already explained.
    """

    def _limited(self, body: str, headers: dict[str, str] | None = None):
        return urllib.error.HTTPError(
            url="https://example.invalid",
            code=429,
            msg="Too Many Requests",
            hdrs=headers or {},  # type: ignore[arg-type]
            fp=io.BytesIO(
                json.dumps({"error": {"message": body}}).encode("utf-8")
            ),
        )

    def test_a_delay_stated_in_the_message_is_read(self) -> None:
        error = _classify_openai_error(
            self._limited(
                "You exceeded your current quota. Quota exceeded for metric: "
                "generate_content_free_tier_requests, limit: 20. "
                "Please retry in 59.549108345s."
            )
        )
        self.assertIsInstance(error, RateLimitError)
        self.assertAlmostEqual(error.retry_after, 59.549108345, places=6)

    def test_a_header_wins_over_the_message(self) -> None:
        error = _classify_openai_error(
            self._limited("Please retry in 59.5s", {"retry-after": "12"})
        )
        self.assertEqual(error.retry_after, 12.0)

    def test_a_minute_long_wait_is_honoured_not_truncated(self) -> None:
        """The cap on our own guesses must not apply to the server's answer."""
        policy = RetryPolicy(maximum_delay=30.0)
        self.assertAlmostEqual(policy.delay_for(1, retry_after=59.5), 59.5)

    def test_a_pathological_wait_is_still_capped(self) -> None:
        policy = RetryPolicy(maximum_retry_after=120.0)
        self.assertEqual(policy.delay_for(1, retry_after=3600.0), 120.0)

    def test_our_own_guesses_stay_short(self) -> None:
        policy = RetryPolicy(maximum_delay=30.0, jitter=False)
        self.assertLessEqual(policy.delay_for(9), 30.0)


class ContextWindowGuard(unittest.TestCase):
    """A local runtime truncates silently; a truncated prompt is a wrong answer.

    The designer's prompt carries the authoring guide. Lose the back half of it
    and the model writes a confident document against instructions it never saw
    -- and the run says nothing, because as far as the transport is concerned
    the call succeeded.

    The guard existed and was blind to two thirds of the request. It counted the
    system prompt and the messages; it did not count the output schema, which
    for the designer is 10,900 tokens against a 5,800-token prompt. Observed
    live on a 16k local model: the check estimated 10k, sent 15.3k plus a 6k
    output reservation, Ollama kept what fit, and the same failure came back
    three times over 82 minutes.
    """

    def _provider(self, window: int | None, **kwargs: Any) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            model="local", context_window=window, **kwargs
        )

    def test_the_schema_counts_as_input(self) -> None:
        """The bug, stated as the property that was missing."""
        request = _request(schema={"type": "object", "x": "y" * 8_000})
        self.assertGreater(request.approximate_schema_tokens(), 1_000)
        self.assertEqual(
            request.approximate_input_tokens(),
            request.approximate_prompt_tokens()
            + request.approximate_schema_tokens(),
        )

    def test_a_request_that_cannot_fit_is_refused_before_it_is_sent(self) -> None:
        with self.assertRaises(ContextTooLargeError) as caught:
            self._provider(4096)._send(  # noqa: SLF001
                _request(messages=(user("x" * 40_000),), max_output_tokens=2048)
            )
        self.assertEqual(caught.exception.detail["context_window"], 4096)
        self.assertIn("num_ctx", caught.exception.detail["hint"])

    def test_the_answer_is_given_what_is_left_rather_than_refused(self) -> None:
        """A reservation larger than the room is a number, not a requirement.

        The designer asks for 16,384 output tokens, which is larger than this
        user's whole context window. Refusing on that basis fails a request
        whose answer is 1,500 tokens long.
        """
        request = _request(messages=(user("x" * 4_000),), max_output_tokens=4096)
        _, reserved = self._provider(4096)._plan_the_request(request)  # noqa: SLF001
        self.assertLess(reserved, 4096)
        self.assertGreaterEqual(reserved, 1024)

    def test_a_window_with_no_room_to_answer_is_still_refused(self) -> None:
        """Shrinking the reservation is not the same as pretending it fits."""
        with self.assertRaises(ContextTooLargeError):
            self._provider(2048)._plan_the_request(  # noqa: SLF001
                _request(messages=(user("x" * 6_000),), max_output_tokens=4096)
            )

    def test_a_schema_too_large_is_narrowed_rather_than_refused(self) -> None:
        """The difference between impossible and comfortable was a flag.

        `opaque` takes the designer's schema from 10,900 tokens to 600, and
        nothing is checked less strictly for it: the document that comes back is
        validated against the real schema either way. A run that fails for want
        of a flag nobody knew to pass has failed for no reason.
        """
        branchy = {
            "type": "object",
            "properties": {
                "feature": {
                    "oneOf": [
                        {
                            "type": "object",
                            "description": "b" * 150,
                            "properties": {
                                "kind": {"const": f"k{index}"},
                                "size": {"type": "number"},
                            },
                            "additionalProperties": False,
                        }
                        for index in range(40)
                    ]
                }
            },
        }
        request = _request(schema=branchy, max_output_tokens=2048)
        # Wide enough for the collapsed schema and an answer, nowhere near
        # enough for the 40 branches as written.
        provider = self._provider(2048, schema_dialect="json_schema")
        dialect, reserved = provider._plan_the_request(request)  # noqa: SLF001
        self.assertEqual(dialect, "opaque")
        self.assertGreaterEqual(reserved, 1024)

    def test_it_never_widens_past_what_was_asked_for(self) -> None:
        """--schema-dialect opaque is a ceiling, not a suggestion."""
        provider = self._provider(200_000, schema_dialect="opaque")
        dialect, _ = provider._plan_the_request(_request())  # noqa: SLF001
        self.assertEqual(dialect, "opaque")

    def test_an_unknown_window_refuses_nothing(self) -> None:
        """Guessing a window would refuse requests that would have worked."""
        provider = self._provider(None)
        try:
            provider._plan_the_request(  # noqa: SLF001
                _request(messages=(user("x" * 400_000),))
            )
        except ContextTooLargeError:  # pragma: no cover
            self.fail("refused a request against a window it does not know")


class SalvagingAnswersInTheWrongWrapper(unittest.TestCase):
    """A model that narrates a tool call has still done the work.

    Observed live against Ollama: llama3.1, told to call a tool, replied

        Here is the JSON for the function call:
        ```
        {"name": "requirements_engineer", "parameters": {...}}
        ```

    Everything needed was there. It was discarded, retried four times at five
    minutes an attempt, and the run failed after 25 minutes.

    This recovers *framing* only. What comes out is validated by the same schema
    and the same semantic checks, and rejected just as readily.
    """

    NARRATED = (
        "Here is the JSON for the function call:\n\n"
        "```\n"
        '{\n  "name": "result",\n  "parameters": {"answer": "42"}\n}\n'
        "```\n"
        "Hope that helps!"
    )

    def _parse(self, text: str, **extra: Any) -> Mapping[str, Any] | None:
        provider = OpenAICompatibleProvider(model="local", structured_mode="tools")
        response = provider._parse(  # noqa: SLF001
            _request(),
            {
                "choices": [
                    {"message": {"content": text, **extra}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
            1.0,
        )
        return response.structured

    def test_a_narrated_tool_call_is_recovered(self) -> None:
        self.assertEqual(self._parse(self.NARRATED), {"answer": "42"})

    def test_a_fenced_block_after_prose_is_found(self) -> None:
        """The old helper only stripped a fence at the very start of the text."""
        self.assertEqual(
            self._parse("Sure!\n\n```json\n{\"answer\": \"42\"}\n```\n"),
            {"answer": "42"},
        )

    def test_a_bare_object_among_prose_is_found(self) -> None:
        self.assertEqual(
            self._parse('Certainly. {"answer": "42"} Let me know!'), {"answer": "42"}
        )

    def test_braces_inside_strings_do_not_confuse_the_scan(self) -> None:
        self.assertEqual(
            self._parse('x {"answer": "a } b {"} y'), {"answer": "a } b {"}
        )

    def test_a_proper_tool_call_still_wins(self) -> None:
        structured = self._parse(
            "ignore this prose",
            tool_calls=[
                {"function": {"name": "result", "arguments": '{"answer": "7"}'}}
            ],
        )
        self.assertEqual(structured, {"answer": "7"})

    def test_arguments_sent_as_an_object_are_accepted(self) -> None:
        """The wire format says a string; several endpoints send the object."""
        structured = self._parse(
            "",
            tool_calls=[{"function": {"name": "result", "arguments": {"answer": "9"}}}],
        )
        self.assertEqual(structured, {"answer": "9"})

    def test_a_document_with_its_own_name_field_is_not_unwrapped(self) -> None:
        """The envelope check must not eat a document that legitimately has a
        `name` -- every ForgeIR document does."""
        payload = '{"name": "Shaft bracket", "revision": 1, "components": []}'
        self.assertEqual(
            self._parse(payload),
            {"name": "Shaft bracket", "revision": 1, "components": []},
        )

    def test_prose_with_no_json_at_all_still_fails(self) -> None:
        with self.assertRaises(StructuredOutputError) as caught:
            self._parse("I would be happy to help with that bracket!")
        self.assertIn("no JSON object", caught.exception.detail["hint"])


class JsonThatIsAlmostValid(unittest.TestCase):
    """Salvaging a complete answer from a nearly-valid document.

    A local model produced a 7 kB ForgeIR document -- correct, complete -- with
    one JavaScript comment in the middle of it:

        "10" // Arbitrary thickness

    That made the whole block unparseable. The fallback then returned the first
    *fragment* that happened to parse, a four-line `units` object nested inside,
    and the run reported "`document` is missing". A confident fragment is worse
    than nothing.
    """

    def _extract(self, text: str) -> Mapping[str, Any] | None:
        from forge_models.openai_compatible import _extract_json_object

        return _extract_json_object(text)

    def test_a_line_comment_does_not_destroy_the_document(self) -> None:
        text = (
            '```json\n{"name": "bracket", "size": [\n  "10" // thickness\n],\n'
            ' "units": {"length": "mm"}}\n```'
        )
        found = self._extract(text)
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "bracket")

    def test_a_block_comment_is_stripped_too(self) -> None:
        found = self._extract('{"a": 1, /* why not */ "b": 2}')
        self.assertEqual(found, {"a": 1, "b": 2})

    def test_a_url_inside_a_string_is_not_a_comment(self) -> None:
        """A naive strip corrupts every URL and path in the document."""
        found = self._extract('{"src": "https://example.com/x", "n": 1}')
        self.assertEqual(found["src"], "https://example.com/x")

    def test_the_largest_candidate_wins_not_the_first(self) -> None:
        """The regression that produced `units` instead of the document."""
        text = (
            '{"document": {"units": {"length": "mm"}}, "broken": ,}\n'
            'and again properly:\n'
            '{"document": {"units": {"length": "mm"}, "components": [1, 2]}}'
        )
        found = self._extract(text)
        self.assertIn("components", found["document"])

    def test_an_escaped_quote_does_not_end_the_string_scan(self) -> None:
        found = self._extract('prose {"note": "a \\" brace } here", "n": 2} tail')
        self.assertEqual(found["n"], 2)

    def test_prose_with_no_json_still_returns_nothing(self) -> None:
        self.assertIsNone(self._extract("I would be delighted to help."))


class ATimeoutThatIsNotAStall(unittest.TestCase):
    """A slow model and a hung one look identical until you do the arithmetic.

    Observed live: a local 3B model measured at 2.5 output tokens a second was
    given `--max-output-tokens 4096` and `--timeout 900`. Those cannot both be
    met -- the ceiling alone needs 27 minutes -- so the call was killed at 15
    having done nothing wrong. Worse, `TimeoutError` is a builtin: it was not a
    ModelError, so the orchestrator never recorded it and the run died with a
    bare traceback and no artefacts. The numbers to diagnose it were all in
    hand; nothing was doing the division.
    """

    def _provider(self, *, timeout: float = 900.0) -> OpenAICompatibleProvider:
        provider = OpenAICompatibleProvider(
            model="forge-qwen", timeout=timeout, structured_mode="tools"
        )
        # The two calls that completed in the run, verbatim.
        provider._tokens_generated = 204 + 354
        provider._seconds_generating = 54.9 + 166.0
        return provider

    def _request(self, ceiling: int = 4096) -> ModelRequest:
        return ModelRequest(
            system="s",
            messages=(user("m"),),
            max_output_tokens=ceiling,
            schema={"type": "object"},
            schema_name="forgeir_designer",
        )

    def test_the_rate_is_measured_not_guessed(self) -> None:
        self.assertAlmostEqual(self._provider().observed_rate, 2.526, places=2)

    def test_no_rate_yet_means_no_arithmetic_claimed(self) -> None:
        fresh = OpenAICompatibleProvider(model="m", timeout=10.0)
        self.assertIsNone(fresh.observed_rate)
        error = fresh._classify_timeout(self._request())
        self.assertTrue(error.retryable)
        self.assertNotIn("seconds_needed_at_that_rate", error.detail)

    def test_a_ceiling_that_cannot_fit_is_not_retried(self) -> None:
        error = self._provider()._classify_timeout(self._request())
        self.assertFalse(error.retryable)
        self.assertIn("not a stall", error.message)

    def test_it_names_the_timeout_that_would_work(self) -> None:
        hint = self._provider()._classify_timeout(self._request()).detail["hint"]
        self.assertIn("2.5 output tokens/second", hint)
        self.assertIn("27 minutes", hint)
        self.assertRegex(hint, r"at least \d+ seconds")

    def test_a_ceiling_that_does_fit_is_treated_as_a_stall(self) -> None:
        """Same clock, a ceiling the rate clears -- now a retry is the answer."""
        error = self._provider()._classify_timeout(self._request(ceiling=512))
        self.assertTrue(error.retryable)
        self.assertIn("stall", error.detail["hint"])

    def test_a_shorter_timeout_changes_the_verdict(self) -> None:
        error = self._provider(timeout=60.0)._classify_timeout(
            self._request(ceiling=512)
        )
        self.assertFalse(error.retryable)

    def test_a_socket_timeout_becomes_a_model_error(self) -> None:
        """The whole point: the orchestrator can only record what it can catch."""
        provider = self._provider()

        def explode(*_: object, **__: object):
            raise TimeoutError("timed out")

        original = urllib.request.urlopen
        urllib.request.urlopen = explode  # type: ignore[assignment]
        try:
            with self.assertRaises(ModelError) as caught:
                provider._send(self._request())
        finally:
            urllib.request.urlopen = original  # type: ignore[assignment]
        self.assertEqual(caught.exception.code, "MD1011_TIMEOUT")

    def test_the_rate_survives_a_call_whose_answer_was_unusable(self) -> None:
        """A call that generated garbage still measured the endpoint's speed."""
        provider = OpenAICompatibleProvider(model="m", structured_mode="tools")
        body = {
            "choices": [{"message": {"content": "not json"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 100},
        }
        with self.assertRaises(StructuredOutputError):
            provider._parse(self._request(), body, latency=50.0)
        self.assertAlmostEqual(provider.observed_rate, 2.0, places=3)


class AnAnswerCutOffAtTheCeiling(unittest.TestCase):
    """Truncation was being reported as a tool-support problem.

    Observed live: a 72-minute run in which all three designer attempts hit
    `finish_reason: length` at 4096 tokens, and each was told "the endpoint
    returned no parseable structured output ... Try --structured-mode
    json_schema, or a model with tool support". Nothing was wrong with the
    mode or the model. The one fact that explained it -- the finish reason --
    was sitting in the detail, unexamined.
    """

    def _provider(self, *, rate: bool = True) -> OpenAICompatibleProvider:
        provider = OpenAICompatibleProvider(
            model="forge-qwen", structured_mode="tools"
        )
        if rate:
            provider._tokens_generated = 558
            provider._seconds_generating = 200.0
        return provider

    def _request(self, ceiling: int = 4096) -> ModelRequest:
        return ModelRequest(
            system="s",
            messages=(user("m"),),
            max_output_tokens=ceiling,
            schema={"type": "object"},
            schema_name="forgeir_designer",
        )

    def _error(
        self, finish: str, *, ceiling: int = 4096, rate: bool = True
    ) -> StructuredOutputError:
        return self._provider(rate=rate)._no_structured_output(
            self._request(ceiling),
            finish,
            '```json\n{\n  "schema_version": "1.0.0",',
            Usage(input_tokens=7000, output_tokens=ceiling),
            finish,
        )

    def test_truncation_is_named_for_what_it_is(self) -> None:
        error = self._error("length")
        self.assertIn("cut off at the output limit", error.message)

    def test_it_is_not_retried_into_the_same_wall(self) -> None:
        self.assertFalse(self._error("length").retryable)

    def test_it_does_not_blame_the_mode_or_the_model(self) -> None:
        hint = self._error("length").detail["hint"]
        self.assertNotIn("json_schema", hint)
        self.assertNotIn("tool support", hint)
        self.assertIn("not a schema or tool-support problem", hint)

    def test_it_says_what_to_raise_and_to_what(self) -> None:
        hint = self._error("length").detail["hint"]
        self.assertIn("--max-output-tokens", hint)
        self.assertIn("8192", hint)

    def test_it_prices_the_advice_in_wall_clock(self) -> None:
        """Doubling the ceiling doubles the wait; say so before it is spent."""
        hint = self._error("length").detail["hint"]
        self.assertIn("2.8 tokens/second", hint)
        self.assertIn("minutes per attempt", hint)

    def test_without_a_measured_rate_it_simply_omits_the_estimate(self) -> None:
        hint = self._error("length", rate=False).detail["hint"]
        self.assertIn("--max-output-tokens", hint)
        self.assertNotIn("minutes per attempt", hint)

    def test_a_large_ceiling_is_doubled_rather_than_floored(self) -> None:
        self.assertIn("16384", self._error("length", ceiling=8192).detail["hint"])

    def test_max_tokens_spelling_is_recognised_too(self) -> None:
        self.assertIn("cut off", self._error("max_tokens").message)

    def test_the_detail_carries_how_far_it_got(self) -> None:
        detail = self._error("length").detail
        self.assertEqual(detail["max_output_tokens"], 4096)
        self.assertEqual(detail["output_tokens"], 4096)
        self.assertGreater(detail["characters_produced"], 0)

    def test_prose_is_still_diagnosed_as_prose(self) -> None:
        error = self._error("stop")
        self.assertIn("no parseable structured output", error.message)
        self.assertTrue(error.retryable)
        self.assertIn("json_schema", error.detail["hint"])

    def test_a_malformed_call_is_still_diagnosed_as_a_schema_problem(self) -> None:
        error = self._error("MALFORMED_FUNCTION_CALL")
        self.assertIn("could not build a call", error.message)
        self.assertFalse(error.retryable)
        self.assertIn("--schema-dialect opaque", error.detail["hint"])


class TheTransportThatActuallyEnforces(unittest.TestCase):
    """Ollama's own endpoint, where `format` is the decoding grammar.

    Forge spoke to local models through the OpenAI-compatible shim with the
    schema attached as a function definition, and that transport was measured
    not to constrain generation at all. A required single-value enum was
    placed at three sites every valid document must pass -- the document, each
    component, each feature -- and the same block was asked for both ways::

        native /api/chat  short prompt: ENFORCED      designer prompt: ENFORCED
        openai shim /v1   short prompt: NOT enforced  designer prompt: NOT enforced

    Under a five-token prompt the shim answered by echoing our own schema back
    as the document, `"type": "object"`, description and all. Nothing was
    holding it to anything.

    These tests pin the contract of the replacement rather than the finding:
    the wire shape it sends, and the failures it must report as themselves.
    """

    def _provider(self, reply: dict, capture: list | None = None):
        from forge_models.ollama_native import OllamaNativeProvider

        provider = OllamaNativeProvider(model="forge-qwen", seed=7)

        def fake(route, payload):
            if capture is not None:
                capture.append((route, payload))
            return reply

        provider._post = fake  # noqa: SLF001
        return provider

    def _request(self, **kwargs):
        from forge_models import ModelRequest, user

        fields = {
            "system": "be brief",
            "messages": (user("a block"),),
            "schema": {"type": "object", "properties": {"a": {"type": "number"}}},
            "schema_name": "document",
        }
        fields.update(kwargs)
        return ModelRequest(**fields)

    def _ok(self, content='{"a": 1}', reason="stop"):
        return {
            "message": {"content": content},
            "done_reason": reason,
            "prompt_eval_count": 7177,
            "eval_count": 42,
        }

    def test_the_schema_is_sent_as_the_grammar_not_as_text(self) -> None:
        """`format` is the whole point; a prompt-borne schema is what failed."""
        seen: list = []
        provider = self._provider(self._ok(), seen)
        provider.complete(self._request())
        route, payload = seen[0]
        self.assertEqual(route, "/api/chat")
        self.assertIn("format", payload)
        self.assertEqual(payload["format"]["type"], "object")
        body = json.dumps(payload["messages"])
        self.assertNotIn("properties", body,
                         "the schema must not ride in the messages")

    def test_the_context_window_is_set_per_request(self) -> None:
        """`--context-window` was a planning hint the runtime never saw."""
        seen: list = []
        provider = self._provider(self._ok(), seen)
        provider.complete(self._request())
        self.assertEqual(seen[0][1]["options"]["num_ctx"], 32768)

    def test_thinking_is_off_and_the_seed_is_fixed(self) -> None:
        """Discarded thinking tokens cost minutes at three tokens a second,
        and a fixed seed is what makes two answers comparable at all."""
        seen: list = []
        provider = self._provider(self._ok(), seen)
        provider.complete(self._request())
        self.assertIs(seen[0][1]["think"], False)
        self.assertEqual(seen[0][1]["options"]["seed"], 7)

    def test_truncation_is_reported_by_the_server_not_estimated(self) -> None:
        """Forge used to infer this from character counts and got it wrong.

        Returned as the truncation it is, not raised: raised, the identical
        call was retried four times under the pinned seed and the role never
        heard it had run out of room. Returned with `MAX_TOKENS`, the role
        asks again with more room, as it does for every other adapter."""
        from forge_models import StopReason

        provider = self._provider(self._ok('{"a": ', reason="length"))
        response = provider.complete(self._request())
        self.assertIs(response.stop_reason, StopReason.MAX_TOKENS)
        self.assertIsNone(response.structured)
        self.assertTrue(any("cut off" in note for note in response.notes),
                        response.notes)

    def test_unparseable_json_is_named_as_a_grammar_failure(self) -> None:
        """Under a grammar this cannot happen. If it does, the endpoint
        accepted `format` without enforcing it, and that is the defect this
        provider exists to remove -- so it must not be reported as the model
        writing bad JSON."""
        from forge_models.errors import StructuredOutputError

        provider = self._provider(self._ok("Here is the document:"))
        with self.assertRaises(StructuredOutputError) as caught:
            provider.complete(self._request())
        self.assertIn("not enforced as a grammar", str(caught.exception))

    def test_a_request_without_a_schema_is_refused(self) -> None:
        from forge_models.errors import ConfigurationError

        provider = self._provider(self._ok())
        with self.assertRaises(ConfigurationError):
            provider.complete(self._request(schema=None))

    def test_a_v1_base_url_is_refused_with_the_fix(self) -> None:
        """The two transports differ by more than a path, and silently
        speaking the wrong one is how this defect survived for a week."""
        from forge_models.errors import ConfigurationError
        from forge_models.ollama_native import OllamaNativeProvider

        with self.assertRaises(ConfigurationError) as caught:
            OllamaNativeProvider(model="x", base_url="http://localhost:11434/v1")
        self.assertIn("/v1", str(caught.exception))

    def test_usage_comes_from_the_servers_own_counters(self) -> None:
        provider = self._provider(self._ok())
        response = provider.complete(self._request())
        self.assertEqual(response.usage.input_tokens, 7177)
        self.assertEqual(response.usage.output_tokens, 42)
        self.assertEqual(response.provider, "ollama-native")

    def test_the_cli_builds_it(self) -> None:
        import argparse

        from forge_cli.design import build_provider
        from forge_models.ollama_native import OllamaNativeProvider

        args = argparse.Namespace(
            provider="ollama", model="forge-qwen", base_url=None,
            context_window=16384, timeout=60.0, max_tokens=None, max_calls=None,
            max_cost=None, record=None, fixtures=None, api_key_env="X",
            structured_mode="tools", schema_dialect="json_schema",
            exact_schema=True,
        )
        provider = build_provider(args)
        self.assertIsInstance(provider, OllamaNativeProvider)
        self.assertEqual(provider.info.context_window, 16384)


class AGrammarNeedsAStoppingRule(unittest.TestCase):
    """Unbounded lists and strings cannot end, so generation does not.

    The first real run on the enforcing transport failed like this::

        brief_interpreter still running, 1111s elapsed
        failed   the reply was cut off at the output limit
        limit: 2048   usage: output_tokens=2048

    The same interpreter answered the same brief in 274 tokens through the
    unconstrained shim. Nothing was wrong with the model: in an unbounded
    `array` the closing bracket is only ever *permitted* and another element
    is always legal too, and in an unbounded `string` the closing quote is
    optional forever. A grammar that never obliges the model to stop will not
    stop a small model that has no instinct for finishing.

    This is the bill that arrives the moment a schema stops being decoration
    and starts being enforced. It was invisible before because nothing was
    enforced.
    """

    def test_every_list_and_string_gets_a_ceiling(self) -> None:
        from forge_models.ollama_native import bounded_for_grammar
        from forge_roles.library import BriefInterpreter, ForgeIRDesigner

        def unbounded(node) -> int:
            count = 0
            if isinstance(node, dict):
                if node.get("type") == "array" and "maxItems" not in node:
                    count += 1
                if (node.get("type") == "string" and "maxLength" not in node
                        and "enum" not in node and "const" not in node):
                    count += 1
                for value in node.values():
                    count += unbounded(value)
            elif isinstance(node, list):
                for value in node:
                    count += unbounded(value)
            return count

        for role in (BriefInterpreter, ForgeIRDesigner):
            with self.subTest(role.__name__):
                schema = role().output_schema()
                self.assertGreater(unbounded(schema), 0, "nothing to fix")
                self.assertEqual(unbounded(bounded_for_grammar(schema)), 0)

    def test_it_changes_nothing_but_the_ceilings(self) -> None:
        """A transport-boundary transform must not alter meaning."""
        from forge_models.ollama_native import bounded_for_grammar
        from forge_roles.library import ForgeIRDesigner

        def strip(node):
            if isinstance(node, dict):
                return {k: strip(v) for k, v in node.items()
                        if k not in ("maxItems", "maxLength")}
            if isinstance(node, list):
                return [strip(v) for v in node]
            return node

        schema = ForgeIRDesigner().output_schema()
        self.assertEqual(strip(bounded_for_grammar(schema)), strip(schema))

    def test_a_bound_the_schema_already_states_is_kept(self) -> None:
        """Never widen someone else's limit -- the designer schema carries
        36 of its own, and overwriting one would loosen a real constraint."""
        from forge_models.ollama_native import bounded_for_grammar

        tight = {"type": "array", "maxItems": 3, "items": {"type": "string"}}
        self.assertEqual(bounded_for_grammar(tight)["maxItems"], 3)

    def test_enums_are_left_alone(self) -> None:
        """An enum bounds itself; a length on one is noise in the grammar."""
        from forge_models.ollama_native import bounded_for_grammar

        node = bounded_for_grammar({"type": "string", "enum": ["mm"]})
        self.assertNotIn("maxLength", node)

    def test_the_bounded_schema_is_what_goes_on_the_wire(self) -> None:
        from forge_models import ModelRequest, user
        from forge_models.ollama_native import OllamaNativeProvider

        seen: list = []
        provider = OllamaNativeProvider(model="m")
        provider._post = lambda route, payload: (  # noqa: SLF001
            seen.append(payload),
            {"message": {"content": "{}"}, "done_reason": "stop",
             "prompt_eval_count": 1, "eval_count": 1},
        )[1]
        provider.complete(ModelRequest(
            system="s", messages=(user("x"),),
            schema={"type": "object", "properties": {
                "notes": {"type": "array", "items": {"type": "string"}}}}))
        self.assertIn("maxItems", seen[0]["format"]["properties"]["notes"])

    def test_the_cut_off_reply_is_returned_with_its_usage(self) -> None:
        """A cut-off reply is returned as a truncation, its tokens counted
        and the likely cause said in its notes. It used to be raised, with
        `usage=` once passed as a keyword that put a Usage object into
        `detail`, which run.json could not serialise -- losing every
        artefact the run had produced. Returned, the record is plain data
        and the role asks again with more room."""
        from forge_models import ModelRequest, StopReason, user
        from forge_models.ollama_native import OllamaNativeProvider

        provider = OllamaNativeProvider(model="m")
        provider._post = lambda route, payload: {  # noqa: SLF001
            "message": {"content": '{"a":'}, "done_reason": "length",
            "prompt_eval_count": 659, "eval_count": 2048}
        response = provider.complete(ModelRequest(
            system="s", messages=(user("x"),), schema={"type": "object"}))
        json.dumps(response.as_dict())
        self.assertIs(response.stop_reason, StopReason.MAX_TOKENS)
        self.assertEqual(response.usage.output_tokens, 2048)
        self.assertEqual(provider.budget.usage.output_tokens, 2048,
                         "the cut-off call is still paid for and counted")
        self.assertTrue(any("array" in note for note in response.notes),
                        "the note must name the likely cause")


class ACeilingThatCutsMustSaySo(unittest.TestCase):
    """A bound that silently truncates is worse than one set too low.

    The grammar forces a list closed at its `maxItems`, so an answer cut at
    the bound LOOKS complete -- which is the shape of every defect this
    project has spent a week chasing. Measured headroom says it should never
    happen: the most complex document anyone has authored holds 15 entries
    against a bound of 64, and a real brief yields 7 stated facts against 24.
    So if it does happen, it is news.

    *News*, though, not a death. Reporting it as a fatal error was tried and
    cost a good run: the entries were distinct and usable, the retries were
    bit-identical under a pinned seed, and the downstream gates would have
    caught any real harm with a far better explanation. The ceiling now
    reports through `ModelResponse.notes`, which the orchestrator writes into
    the run log beside the role that produced it.
    """

    def _provider(self, payload):
        from forge_models.ollama_native import OllamaNativeProvider

        provider = OllamaNativeProvider(model="m")
        provider._post = lambda route, body: {  # noqa: SLF001
            "message": {"content": json.dumps(payload)}, "done_reason": "stop",
            "prompt_eval_count": 10, "eval_count": 20}
        return provider

    def _request(self, limit=None):
        from forge_models import ModelRequest, user

        notes = {"type": "array", "items": {"type": "string"}}
        if limit is not None:
            notes["maxItems"] = limit
        return ModelRequest(
            system="s", messages=(user("x"),),
            schema={"type": "object", "properties": {"notes": notes}})

    def test_a_list_at_its_ceiling_is_reported(self) -> None:
        provider = self._provider({"notes": ["a", "b", "c"]})
        response = provider.complete(self._request(limit=3))
        # The answer survives, whole.
        self.assertEqual(response.structured["notes"], ["a", "b", "c"])
        joined = " ".join(response.notes)
        self.assertIn("ceiling", joined)
        self.assertIn("/notes", joined)

    def test_padding_at_the_ceiling_is_dropped_not_reported_as_a_cut(
        self,
    ) -> None:
        """The observed failure: `implied` came back 24 long, holding four
        distinct sentences and twenty repeats of them."""
        provider = self._provider({"notes": ["a", "b", "a", "b"]})
        response = provider.complete(self._request(limit=4))
        self.assertEqual(response.structured["notes"], ["a", "b"])
        joined = " ".join(response.notes)
        self.assertIn("repeats were dropped", joined)
        self.assertNotIn("may have been cut short", joined)

    def test_a_list_below_its_ceiling_passes(self) -> None:
        provider = self._provider({"notes": ["a", "b"]})
        response = provider.complete(self._request(limit=3))
        self.assertEqual(response.structured["notes"], ["a", "b"])
        self.assertEqual(response.notes, ())

    def test_a_deterministic_provider_does_not_ask_for_a_retry(self) -> None:
        """With `seed` and `temperature` pinned, every retry is bit-identical
        by construction. Marking such a failure retryable spends four times
        four-to-twenty-five minutes to receive the same bytes and then die."""
        from forge_models import ModelRequest, user
        from forge_models.errors import StructuredOutputError
        from forge_models.ollama_native import OllamaNativeProvider

        def answering(text, seed):
            provider = OllamaNativeProvider(model="m", seed=seed)
            provider._post = lambda route, body: {  # noqa: SLF001
                "message": {"content": text}, "done_reason": "stop",
                "prompt_eval_count": 1, "eval_count": 1}
            return provider

        request = ModelRequest(
            system="s", messages=(user("x"),), schema={"type": "object"})
        with self.assertRaises(StructuredOutputError) as pinned:
            answering("[1, 2]", 42).complete(request)
        self.assertFalse(pinned.exception.retryable)
        with self.assertRaises(StructuredOutputError) as free:
            answering("[1, 2]", None).complete(request)
        self.assertTrue(free.exception.retryable)

    def test_the_default_ceilings_do_not_fire_on_real_documents(self) -> None:
        """The clevis is the most complex part in the repository."""
        from forge_models.ollama_native import (
            _lists_at_their_ceiling, bounded_for_grammar,
        )
        from forge_ir import document_schema

        path = pathlib.Path(__file__).resolve().parent.parent / (
            "examples/clevis/clevis.forgeir.json")
        if not path.exists():  # pragma: no cover - example is part of the repo
            self.skipTest("clevis example not present")
        document = json.loads(path.read_text())
        bounded = bounded_for_grammar(document_schema())
        self.assertEqual(_lists_at_their_ceiling(document, bounded), [])

    def test_a_ceiling_never_binds_below_the_limit(self) -> None:
        """Bounding is a backstop, not a budget: the legal tokens at entry 15
        are identical with and without it, so nothing about how the model
        designs changes until the limit is actually reached."""
        from forge_models.ollama_native import bounded_for_grammar

        def strip(node):
            if isinstance(node, dict):
                return {k: strip(v) for k, v in node.items()
                        if k not in ("maxItems", "maxLength")}
            if isinstance(node, list):
                return [strip(v) for v in node]
            return node

        schema = {"type": "array", "items": {"type": "string"}}
        self.assertEqual(strip(bounded_for_grammar(schema)), schema)

    def test_a_fixed_length_list_is_not_a_ceiling(self) -> None:
        """minItems == maxItems mandates a length; it does not cut one.

        Caught by the clevis, whose every coordinate is a three-component
        vector: the first version of this check reported all of them.
        """
        from forge_models.ollama_native import _lists_at_their_ceiling

        vector = {"type": "array", "minItems": 3, "maxItems": 3,
                  "items": {"type": "number"}}
        self.assertEqual(_lists_at_their_ceiling([1, 2, 3], vector), [])
        loose = {"type": "array", "maxItems": 3, "items": {"type": "number"}}
        self.assertEqual(len(_lists_at_their_ceiling([1, 2, 3], loose)), 1)


class OllamasReplyIsReadAsItIsWritten(unittest.TestCase):
    """Run 20261007T160309: the designer's first call sat 2400 s without a
    word and was thrown away at the timeout; asked again, the same call took
    403 s. Unstreamed, a reply being written and a server gone quiet look the
    same. Streamed, the timeout is how long Ollama may stay silent, and the
    wait says what it is."""

    @staticmethod
    def _lines(*chunks):
        return [json.dumps(c).encode() + b"\n" for c in chunks]

    def test_the_chunks_are_one_reply(self) -> None:
        from forge_models.ollama_native import _read_the_stream

        seen = []
        reply = _read_the_stream(self._lines(
            {"message": {"role": "assistant", "content": '{"a"'}, "done": False},
            {"message": {"role": "assistant", "content": ": 1}"}, "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True,
             "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 2}),
            seen.append)
        self.assertEqual(reply["message"]["content"], '{"a": 1}')
        self.assertEqual((reply["done_reason"], reply["prompt_eval_count"],
                          reply["eval_count"]), ("stop", 12, 2))
        self.assertEqual(seen[-1], 2)

    def test_a_reply_of_blank_space_is_stopped(self) -> None:
        from forge_models.errors import StructuredOutputError
        from forge_models.ollama_native import BLANK_RUN_LIMIT, _read_the_stream

        chunks = [{"message": {"content": '{"a": '}, "done": False}] + [
            {"message": {"content": "\n"}, "done": False}
            for _ in range(BLANK_RUN_LIMIT + 5)]
        with self.assertRaises(StructuredOutputError):
            _read_the_stream(self._lines(*chunks))

    def test_ordinary_spacing_is_not_blank_space(self) -> None:
        from forge_models.ollama_native import _read_the_stream

        chunks = [{"message": {"content": c}, "done": False}
                  for c in ['{\n', '  "a"', ': ', '1', ',\n  ', '"b": 2\n', '}']]
        chunks.append({"message": {"content": ""}, "done": True,
                       "done_reason": "stop"})
        reply = _read_the_stream(self._lines(*chunks))
        self.assertEqual(json.loads(reply["message"]["content"]),
                         {"a": 1, "b": 2})

    def test_it_asks_for_a_stream(self) -> None:
        from forge_models import ModelRequest, user
        from forge_models.ollama_native import OllamaNativeProvider

        provider = OllamaNativeProvider(model="m")
        sent = []
        provider._post = lambda route, body: (sent.append(body) or {  # noqa: SLF001
            "message": {"content": '{"x": 1}'}, "done_reason": "stop"})
        provider._send(ModelRequest(  # noqa: SLF001
            system="s", messages=(user("hi"),), schema={"type": "object"}))
        self.assertTrue(sent[0]["stream"])


class TheAnthropicCallTheNewerModelsAccept(unittest.TestCase):
    """Claude Sonnet 5 rejects any sampling parameter but the default, and
    some newer models reject a forced tool choice -- each a 400 that ended
    the run before a single design. A 400 is not billed, so the call is made
    again without what was refused."""

    def _provider(self, model, refuses, thinking="off", replies=None):
        from unittest import mock
        import urllib.error

        sent = []
        provider = AnthropicProvider(api_key="k", model=model,
                                     thinking=thinking)
        queue = list(replies or [])

        def fake(request, timeout=None):
            body = json.loads(request.data)
            sent.append(body)
            for word, key in refuses:
                if key(body):
                    error = urllib.error.HTTPError(
                        "u", 400, "bad", {}, io.BytesIO(json.dumps({
                            "type": "error", "error": {
                                "type": "invalid_request_error",
                                "message": word}}).encode()))
                    raise error
            reply = json.dumps(queue.pop(0) if queue else {
                "content": [{"type": "tool_use", "name": "submit_result",
                             "input": {"answer": 1}}],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 10, "output_tokens": 5}}).encode()
            return mock.MagicMock(__enter__=lambda s: io.BytesIO(reply),
                                  __exit__=lambda s, *a: False)

        return provider, sent, mock.patch(
            "forge_models.anthropic.urllib.request.urlopen", fake)

    def test_sonnet_5_is_sent_no_temperature(self) -> None:
        payload = AnthropicProvider(
            api_key="k", model="claude-sonnet-5")._build_payload(_request())
        self.assertNotIn("temperature", payload)

    def test_an_older_model_still_gets_it(self) -> None:
        payload = AnthropicProvider(
            api_key="k", model="claude-sonnet-4-6",
            thinking="off")._build_payload(_request())
        self.assertIn("temperature", payload)

    def test_a_refused_temperature_is_dropped_and_the_call_made_again(self) -> None:
        provider, sent, patch = self._provider(
            "claude-sonnet-4-6",
            [("temperature is not supported", lambda b: "temperature" in b)])
        with patch:
            response = provider._send(_request())
        self.assertEqual(response.structured, {"answer": 1})
        self.assertEqual(["temperature" in b for b in sent], [True, False])

    def test_a_refused_forced_tool_falls_back_to_auto(self) -> None:
        provider, sent, patch = self._provider(
            "claude-sonnet-5-5",
            [("tool_choice: type \"tool\" is not supported",
              lambda b: b.get("tool_choice", {}).get("type") == "tool")])
        with patch:
            response = provider._send(_request())
        self.assertEqual(response.structured, {"answer": 1})
        self.assertEqual(sent[-1]["tool_choice"], {"type": "auto"})
        self.assertIn("submit_result", sent[-1]["system"][0]["text"])

    def test_a_forced_tool_falls_back_to_auto_with_its_instruction(self) -> None:
        provider, sent, patch = self._provider(
            "claude-sonnet-5-5",
            [("tool_choice: type \"tool\" is not supported with thinking",
              lambda b: b.get("tool_choice", {}).get("type") == "tool")],
            thinking="off")
        with patch:
            provider._send(_request())
        self.assertEqual(sent[-1]["tool_choice"], {"type": "auto"})

    def test_the_instructions_are_cached(self) -> None:
        payload = AnthropicProvider(
            api_key="k", model="claude-sonnet-5")._build_payload(_request())
        self.assertEqual(payload["system"][0]["cache_control"],
                         {"type": "ephemeral"})

    def test_cache_reads_and_writes_are_costed(self) -> None:
        from forge_models.anthropic import _estimate_cost
        from forge_models.types import Usage

        fresh = _estimate_cost("claude-sonnet-5", Usage(1_000_000, 0, 0))
        read = _estimate_cost("claude-sonnet-5", Usage(0, 0, 1_000_000))
        self.assertAlmostEqual(read, fresh * 0.1)
