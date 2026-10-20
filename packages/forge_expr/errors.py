"""Structured exceptions for the expression engine.

Every error carries the source text and, where the failure is attributable to a
specific sub-expression, the column span of the offending node. Diagnostics are
consumed by the Failure Analyst role, which needs to know *which token* was
wrong, not merely that something was.
"""

from __future__ import annotations

from typing import Any, Mapping


class ForgeExprError(Exception):
    """Base class for expression-engine failures."""

    code = "FE0000_EXPR_ERROR"

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail: Mapping[str, Any] = dict(detail)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}

    def __str__(self) -> str:
        parts = [f"[{self.code}] {self.message}"]
        source = self.detail.get("source")
        span = self.detail.get("span")
        if isinstance(source, str) and isinstance(span, (list, tuple)) and len(span) == 2:
            start, end = int(span[0]), int(span[1])
            caret = " " * start + "^" * max(1, end - start)
            parts.append(f"\n    {source}\n    {caret}")
        extra = {
            key: value
            for key, value in sorted(self.detail.items())
            if key not in ("source", "span")
        }
        if extra:
            parts.append(
                " (" + ", ".join(f"{k}={v!r}" for k, v in extra.items()) + ")"
            )
        return "".join(parts)


class ExpressionSyntaxError(ForgeExprError):
    """The expression is not syntactically valid."""

    code = "FE1001_SYNTAX"


class DisallowedConstructError(ForgeExprError):
    """The expression used a language construct outside the allowlist.

    This is a security boundary as much as a usability one: expressions can
    originate from a language model or an imported document, and the allowlist is
    what guarantees an expression cannot reach attributes, imports, subscripts,
    comprehensions, lambdas, or any other route to arbitrary execution.
    """

    code = "FE1002_DISALLOWED_CONSTRUCT"


class UnknownNameError(ForgeExprError):
    """A name in the expression resolves to no parameter, constant or unit."""

    code = "FE1003_UNKNOWN_NAME"


class UnknownFunctionError(ForgeExprError):
    """A call named a function outside the vetted function table."""

    code = "FE1004_UNKNOWN_FUNCTION"


class ArityError(ForgeExprError):
    """A function was called with the wrong number of arguments."""

    code = "FE1005_ARITY"


class ExpressionTypeError(ForgeExprError):
    """A sub-expression produced the wrong kind of value.

    Expressions are two-sorted: they evaluate either to a
    :class:`~forge_units.quantity.Quantity` or to a three-valued
    :class:`~forge_units.trivalent.Trivalent`. Mixing the sorts (adding a
    comparison to a length, say) is caught here.
    """

    code = "FE1006_TYPE"


class ExpressionComplexityError(ForgeExprError):
    """The expression exceeded the configured size or depth budget."""

    code = "FE1007_COMPLEXITY"


class ParameterCycleError(ForgeExprError):
    """The parameter dependency graph contains a cycle."""

    code = "FE1008_PARAMETER_CYCLE"


class ParameterResolutionError(ForgeExprError):
    """A parameter could not be resolved."""

    code = "FE1009_PARAMETER_RESOLUTION"


class ReservedNameError(ForgeExprError):
    """A parameter was declared with a name that shadows a unit or constant."""

    code = "FE1010_RESERVED_NAME"


class EvaluationError(ForgeExprError):
    """Evaluation failed for a reason attributable to a specific node."""

    code = "FE1011_EVALUATION"


__all__ = [
    "ForgeExprError",
    "ExpressionSyntaxError",
    "DisallowedConstructError",
    "UnknownNameError",
    "UnknownFunctionError",
    "ArityError",
    "ExpressionTypeError",
    "ExpressionComplexityError",
    "ParameterCycleError",
    "ParameterResolutionError",
    "ReservedNameError",
    "EvaluationError",
]
