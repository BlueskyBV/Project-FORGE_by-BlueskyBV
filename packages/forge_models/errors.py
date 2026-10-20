"""Structured provider errors, classified by what the caller should do.

The important distinction is between errors worth retrying and errors that will
fail identically forever. A 429 is a delay; a 400 is a bug in the request. Retrying
the second wastes money and time and hides the defect, so the classification is
part of the type rather than a guess at the call site.
"""

from __future__ import annotations

from typing import Any, Mapping


class ModelError(Exception):
    """Base class for provider failures."""

    code = "MD0000_MODEL_ERROR"
    #: Whether retrying the identical request could plausibly succeed.
    retryable = False

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail: Mapping[str, Any] = dict(detail)
        #: Tokens the failed call consumed, when the provider reported them. A
        #: call that produced an unusable answer was still paid for, and a run
        #: that does not count it under-reports its own spending -- which, for a
        #: retry loop, can be by a factor of four.
        self.usage: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "detail": dict(self.detail),
        }

    def __str__(self) -> str:
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.detail.items()))
        return f"[{self.code}] {self.message}" + (f" ({rendered})" if rendered else "")


class ConfigurationError(ModelError):
    """The provider is not configured -- usually a missing API key."""

    code = "MD1001_CONFIGURATION"


class AuthenticationError(ModelError):
    """The credential was rejected."""

    code = "MD1002_AUTHENTICATION"


class RateLimitError(ModelError):
    """Rate limited. Retry after a delay."""

    code = "MD1003_RATE_LIMIT"
    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None, **detail: Any):
        super().__init__(message, **detail)
        self.retry_after = retry_after


class TransientError(ModelError):
    """A network failure or a 5xx. Retry."""

    code = "MD1004_TRANSIENT"
    retryable = True


class RequestError(ModelError):
    """The request was malformed. Retrying will fail identically."""

    code = "MD1005_BAD_REQUEST"


class StructuredOutputError(ModelError):
    """The provider returned no usable structured output.

    Distinct from a schema *validation* failure, which is the role's problem and
    is handled by bounded repair. This one means the transport did not produce
    the shape it promised -- no tool-use block, unparseable JSON -- and is a
    provider or configuration fault.

    Retryable by default, because the usual cause is a truncation that a second
    attempt survives. Not always, though: an endpoint that cannot build a call
    from *this schema* will fail identically every time, and four attempts with
    backoff spend two minutes and four times the tokens to learn nothing. Such a
    failure sets ``retryable`` false on the instance and says what to change.
    """

    code = "MD1006_STRUCTURED_OUTPUT"
    retryable = True

    def __init__(
        self, message: str, *, retryable: bool | None = None, **detail: Any
    ) -> None:
        super().__init__(message, **detail)
        if retryable is not None:
            self.retryable = retryable


class BudgetExceededError(ModelError):
    """The run would exceed its declared token or cost budget.

    Never retryable, and deliberately a hard stop: an agent that quietly spends
    past its budget is a worse failure than one that halts.
    """

    code = "MD1007_BUDGET_EXCEEDED"


class CancelledError(ModelError):
    """The caller cancelled the request."""

    code = "MD1008_CANCELLED"


class ContextTooLargeError(ModelError):
    """The request does not fit the model's context window."""

    code = "MD1009_CONTEXT_TOO_LARGE"


class RequestTimeoutError(ModelError):
    """The endpoint did not answer within the socket timeout.

    Two very different situations wear this face. A remote endpoint that stalls
    is transient and a second attempt usually lands. A local model generating at
    a measured rate is not stalled at all -- it is working, slowly, and the
    timeout is simply shorter than the token ceiling takes. Retrying the second
    kind costs another full timeout to learn nothing, so the classification is
    made by arithmetic at the raise site rather than assumed here.
    """

    code = "MD1011_TIMEOUT"
    retryable = True

    def __init__(
        self, message: str, *, retryable: bool | None = None, **detail: Any
    ) -> None:
        super().__init__(message, **detail)
        if retryable is not None:
            self.retryable = retryable


class FixtureMissingError(ModelError):
    """No recorded response matches this request.

    Raised by the fixture provider in replay mode. It carries the request
    fingerprint and its purpose, because the usual cause is an intentional
    prompt change -- and the fix is to re-record, not to loosen the matching.
    """

    code = "MD1010_FIXTURE_MISSING"


__all__ = [
    "ModelError",
    "ConfigurationError",
    "AuthenticationError",
    "RateLimitError",
    "TransientError",
    "RequestError",
    "StructuredOutputError",
    "BudgetExceededError",
    "CancelledError",
    "ContextTooLargeError",
    "RequestTimeoutError",
    "FixtureMissingError",
]
