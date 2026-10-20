"""Structured exceptions for the dimensional type system.

Every Forge exception carries a stable diagnostic code so that failures can be
classified by machine (routed to a repair strategy, counted in benchmarks)
rather than matched by substring against a human-readable message.
"""

from __future__ import annotations

from typing import Any, Mapping


def detail_besides(detail: Mapping[str, Any], *named: str) -> dict[str, Any]:
    """A nested error's context, minus the keys the caller sets itself.

    Wrapping one Forge error in another is written as::

        raise EvaluationError(exc.message, cause=exc.code, **dict(exc.detail))

    which is correct exactly until ``exc.detail`` already contains ``cause`` --
    and it does, the moment an error has been wrapped once already. Python then
    raises for the duplicate keyword *at the call*, inside the ``except`` block,
    and what escapes is that bookkeeping error rather than the failure being
    reported.

    Observed live: a parameter dividing by zero. The units layer said so, the
    expression layer wrapped it, and the third wrap produced
    ``could not resolve feature parameter: 'cause'`` -- a message about a
    dictionary key, in place of one that named the division.
    """
    return {key: value for key, value in dict(detail).items() if key not in named}


class ForgeUnitsError(Exception):
    """Base class for every error raised by :mod:`forge_units`.

    Attributes
    ----------
    code:
        Stable, machine-readable diagnostic code. Never change an existing code
        once released; add a new one instead.
    detail:
        Structured context suitable for JSON serialisation into an evidence
        node or a compiler diagnostic.
    """

    code: str = "FU0000_UNITS_ERROR"

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail: Mapping[str, Any] = dict(detail)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.detail:
            rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.detail.items()))
            return f"[{self.code}] {self.message} ({rendered})"
        return f"[{self.code}] {self.message}"


class UnitSyntaxError(ForgeUnitsError):
    """The unit string could not be parsed."""

    code = "FU1001_UNIT_SYNTAX"


class UnknownUnitError(ForgeUnitsError):
    """The unit symbol is not present in the registry."""

    code = "FU1002_UNKNOWN_UNIT"


class DimensionalityError(ForgeUnitsError):
    """An operation combined quantities whose dimensions are incompatible."""

    code = "FU1003_DIMENSIONALITY"


class OffsetUnitError(ForgeUnitsError):
    """An affine (offset) unit was used where only a ratio unit is valid."""

    code = "FU1004_OFFSET_UNIT_MISUSE"


class IntervalError(ForgeUnitsError):
    """An interval was constructed or combined illegally."""

    code = "FU1005_INTERVAL"


class UnitConversionError(ForgeUnitsError):
    """A conversion between two units of the same dimension failed."""

    code = "FU1006_CONVERSION"
