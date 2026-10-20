"""forge_models - the provider-neutral model layer.

No provider SDK type reaches the engineering layers. A role asks for a
completion and gets a :class:`ModelResponse`; whether that came from Anthropic,
from a local model behind an OpenAI-compatible endpoint, or from a recorded
fixture is configuration.

Written on the standard library, like the rest of the trust core. That began as a
constraint and turned out to be the right shape: the adapters are one HTTPS POST
and a response parse each.

Three things this layer insists on:

**Structured output is forced, not requested.** Schemas are declared as tool
input schemas with the tool choice pinned, so the model must emit a conforming
object. Asking politely for JSON yields markdown fences and trailing commentary
often enough that the parsing becomes its own failure source.

**Budgets are hard stops.** An agent that quietly spends past its token or cost
ceiling is a worse failure than one that halts and says so.

**Every call is accountable.** Which provider answered, how many tokens, how
long, how many attempts, and -- recorded on every run -- whether design data left
the machine.

>>> from forge_models import AnthropicProvider, FixtureProvider
>>> provider = AnthropicProvider()          # DEFAULT_MODEL, key from the env
>>> provider.is_configured          # reads ANTHROPIC_API_KEY
False
>>> offline = FixtureProvider("tests/fixtures/models")   # free, deterministic
"""

from __future__ import annotations

from .anthropic import API_URL, DEFAULT_MODEL, PRICE_TABLE, AnthropicProvider
from .errors import (
    AuthenticationError,
    BudgetExceededError,
    CancelledError,
    ConfigurationError,
    ContextTooLargeError,
    FixtureMissingError,
    ModelError,
    RateLimitError,
    RequestError,
    RequestTimeoutError,
    StructuredOutputError,
    TransientError,
)
from .fixtures import (
    Fixture,
    FixtureLibrary,
    FixtureProvider,
    RecordingProvider,
    ScriptedProvider,
)
from .ollama_native import OllamaNativeProvider
from .openai_compatible import OpenAICompatibleProvider, StructuredMode
from .provider import Budget, CancellationToken, Observer, Provider, RetryPolicy
from .types import (
    Message,
    ModelRequest,
    ModelResponse,
    ProviderInfo,
    Role,
    StopReason,
    Usage,
    assistant,
    user,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # types
    "Message",
    "ModelRequest",
    "ModelResponse",
    "ProviderInfo",
    "Role",
    "StopReason",
    "Usage",
    "user",
    "assistant",
    # provider machinery
    "Provider",
    "RetryPolicy",
    "Budget",
    "CancellationToken",
    "Observer",
    # adapters
    "AnthropicProvider",
    "OllamaNativeProvider",
    "OpenAICompatibleProvider",
    "StructuredMode",
    "FixtureProvider",
    "RecordingProvider",
    "ScriptedProvider",
    "FixtureLibrary",
    "Fixture",
    "API_URL",
    "DEFAULT_MODEL",
    "PRICE_TABLE",
    # errors
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
