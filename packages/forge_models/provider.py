"""The provider protocol, retry policy and budget enforcement.

A provider implements one method: turn a :class:`~forge_models.types.ModelRequest`
into a :class:`~forge_models.types.ModelResponse`. Everything shared -- retries,
backoff, budget checks, usage accounting, cancellation -- lives in
:class:`Provider` so that each adapter is only transport.
"""

from __future__ import annotations

import math
import random
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .errors import (
    BudgetExceededError,
    CancelledError,
    ModelError,
    RateLimitError,
    TransientError,
)
from .types import ModelRequest, ModelResponse, ProviderInfo, Usage


@dataclass(slots=True)
class RetryPolicy:
    """Exponential backoff with full jitter.

    Full jitter rather than a fixed multiplier because several roles may be in
    flight at once; synchronised retries after a shared rate limit would arrive
    together and be rejected together.
    """

    max_attempts: int = 4
    initial_delay: float = 0.6
    multiplier: float = 2.4
    #: Ceiling on delays this policy *guesses*.
    maximum_delay: float = 30.0
    #: Ceiling on a delay the server *asked* for. Higher on purpose: a
    #: per-minute quota window is around 60 seconds, and capping the server's
    #: own "retry in 59.5s" at 30 guarantees the retry lands inside the same
    #: exhausted window and fails too. That is not caution, it is a slow way of
    #: refusing free advice -- observed live against a free-tier quota.
    maximum_retry_after: float = 120.0
    jitter: bool = True

    def delay_for(self, attempt: int, *, retry_after: float | None = None) -> float:
        if retry_after is not None and math.isfinite(retry_after) \
                and retry_after >= 0.0:
            # A server that tells us when to come back knows something we do
            # not. Honour it, capped only against a pathological value. A
            # header that parsed to NaN or a negative number is no advice:
            # `time.sleep` refuses both with a ValueError that is not a
            # ModelError, and the plain-sleep path has nothing to catch it.
            return min(retry_after, self.maximum_retry_after)
        base = min(self.initial_delay * (self.multiplier ** (attempt - 1)),
                   self.maximum_delay)
        return random.uniform(0.0, base) if self.jitter else base


@dataclass(slots=True)
class Budget:
    """A hard ceiling on what a run may spend.

    Checked before each call and after each response. Exceeding it raises rather
    than warning: an agent that quietly spends past its budget is a worse failure
    than one that stops and says so.
    """

    # Fresh input (cache writes included, since they are) and output. Raised
    # from 400 000 when cache writes began to be counted: the same run, the
    # same allowance, the tokens it always spent now seen.
    max_total_tokens: int | None = 600_000
    max_calls: int | None = 60
    max_cost_usd: float | None = None

    calls: int = 0
    usage: Usage = field(default_factory=Usage)
    #: The most one request can cost, where the provider can say
    #: (``AnthropicProvider.worst_cost_usd``). Given, the cost ceiling holds
    #: before a call, not only after one: a call whose worst cost would take
    #: the run past it is refused, and each retry is checked again. Not
    #: given, the ceiling refuses the call after the one that reaches it, as
    #: it always has (docs/V2-stage4.md, 14.4).
    price: Callable[[ModelRequest], float | None] | None = None

    def check_before(self, request: ModelRequest) -> None:
        # The cost ceiling is held here, before a call, and not after one: a
        # call that has been paid for is kept and used, and the one after it
        # is refused. Raised after the answer, the money was spent and the
        # answer thrown away.
        if (
            self.max_cost_usd is not None
            and self.usage.cost_usd is not None
            and self.usage.cost_usd >= self.max_cost_usd
        ):
            raise BudgetExceededError(
                "the run has reached its cost budget",
                spent_usd=round(self.usage.cost_usd, 4),
                limit_usd=self.max_cost_usd,
            )
        if (
            self.max_cost_usd is not None
            and self.calls > 0
            and self.usage.cost_usd is None
        ):
            # A cost ceiling on calls nobody can price is not a ceiling. A
            # model outside the price table, or an endpoint that reports no
            # price, left `cost_usd` None and the check above silently never
            # fired -- `--max-cost` was a hard stop in the help text and a
            # no-op in the run. Said after the first call, when it is known
            # that no price arrived, rather than guessed at before it.
            raise BudgetExceededError(
                "the run has a cost budget and this provider cannot price its "
                "calls, so the budget cannot be enforced",
                calls=self.calls,
                limit_usd=self.max_cost_usd,
                hint="bound the run with --max-tokens or --max-calls instead, "
                "or add the model to the provider's price table",
            )
        if self.max_cost_usd is not None and self.price is not None:
            worst = self.price(request)
            spent = self.usage.cost_usd or 0.0
            if worst is not None and spent + worst > self.max_cost_usd:
                raise BudgetExceededError(
                    "the next call could take the run past its cost budget",
                    spent_usd=round(spent, 4),
                    worst_usd=round(worst, 4),
                    limit_usd=self.max_cost_usd,
                )
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise BudgetExceededError(
                "the run has reached its model-call budget",
                calls=self.calls,
                limit=self.max_calls,
            )
        if self.max_total_tokens is not None:
            projected = (
                self.usage.total_tokens
                + request.approximate_input_tokens()
                + request.max_output_tokens
            )
            if projected > self.max_total_tokens:
                raise BudgetExceededError(
                    "this call would exceed the run's token budget",
                    spent=self.usage.total_tokens,
                    projected=projected,
                    limit=self.max_total_tokens,
                )

    def record(self, usage: Usage) -> None:
        self.calls += 1
        self.usage = self.usage + usage

    def remaining_tokens(self) -> int | None:
        if self.max_total_tokens is None:
            return None
        return max(0, self.max_total_tokens - self.usage.total_tokens)

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "limits": {
                "max_calls": self.max_calls,
                "max_total_tokens": self.max_total_tokens,
                "max_cost_usd": self.max_cost_usd,
            },
            "usage": self.usage.as_dict(),
        }


class CancellationToken:
    """Cooperative cancellation, checked between attempts."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancelledError("the run was cancelled")

    def wait(self, seconds: float) -> None:
        """Sleep, but wake immediately on cancellation."""
        if self._event.wait(seconds):
            raise CancelledError("the run was cancelled while backing off")


#: Called with each completed request/response pair, for logging and provenance.
Observer = Callable[[ModelRequest, ModelResponse], None]


class Provider(ABC):
    """Base class handling retries, budget and accounting."""

    def __init__(
        self,
        *,
        retry: RetryPolicy | None = None,
        budget: Budget | None = None,
        observers: list[Observer] | None = None,
    ) -> None:
        self.retry = retry or RetryPolicy()
        self.budget = budget or Budget()
        self.observers: list[Observer] = list(observers or [])

    # -- to implement -------------------------------------------------
    @property
    @abstractmethod
    def info(self) -> ProviderInfo: ...

    @abstractmethod
    def _send(self, request: ModelRequest) -> ModelResponse:
        """One attempt. Raise a :class:`ModelError` subclass on failure."""

    # -- the public call ------------------------------------------------
    def complete(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> ModelResponse:
        self.budget.check_before(request)

        last: ModelError | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            if attempt > 1 and self.budget.price is not None:
                # A retry is paid for like the first try: a ceiling that
                # holds before a call holds before each attempt at it.
                self.budget.check_before(request)
            try:
                response = self._send(request)
            except ModelError as error:
                last = error
                # A call that produced an unusable answer was still paid for.
                # Counting it is what keeps the budget honest across a retry
                # loop, where the unusable answers can outnumber the usable one.
                spent = getattr(error, "usage", None)
                if spent is not None:
                    self.budget.record(spent)
                if not error.retryable or attempt == self.retry.max_attempts:
                    raise
                limit = getattr(error, "retry_limit", None)
                if limit is not None and attempt >= int(limit):
                    # A request that timed out after minutes is not resent
                    # three more times: each costs the same minutes again.
                    raise
                delay = self.retry.delay_for(
                    attempt,
                    retry_after=getattr(error, "retry_after", None),
                )
                # A network that is briefly unreachable is waited out over
                # tens of seconds, not the few that four quick tries take.
                floor = getattr(error, "minimum_delay", None)
                if isinstance(floor, (int, float)) and floor > 0:
                    delay = max(delay, float(floor) * attempt)
                status = (getattr(error, "detail", None) or {}).get("status")
                if isinstance(status, int) and status >= 500:
                    # An overloaded or failing server (500-529) recovers in
                    # seconds, not the fraction of one the first backoff
                    # waits: four quick tries all landed in the same outage.
                    delay = max(delay, 4.0 * attempt)
                if cancellation is not None:
                    cancellation.wait(delay)
                else:
                    time.sleep(delay)
                continue

            response = _with_attempts(response, attempt)
            self.budget.record(response.usage)
            for observe in self.observers:
                observe(request, response)
            return response

        # The loop always returns or raises; this is for the type checker.
        raise last or TransientError("the provider failed without an error")

    def observe(self, observer: Observer) -> None:
        self.observers.append(observer)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}(model={self.info.model!r})"


def _with_attempts(response: ModelResponse, attempts: int) -> ModelResponse:
    if attempts == response.attempts:
        return response
    # Every other field as it came, `notes` included: rebuilt field by field,
    # the notes a transport attached -- "this list may have been cut short at
    # its ceiling" -- were lost on any response that took more than one
    # attempt, and the run log never heard what the adapter had settled.
    from dataclasses import replace

    return replace(response, attempts=attempts)


__all__ = [
    "Provider",
    "RetryPolicy",
    "Budget",
    "CancellationToken",
    "Observer",
]
