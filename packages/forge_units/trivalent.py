"""Three-valued logic for engineering comparisons.

Classical two-valued logic is the wrong tool for comparing engineering values,
because engineering values are almost never points. If a wall thickness is known
to lie in ``[2.9, 3.1] mm`` and the manufacturing rule demands ``>= 3.0 mm``,
neither ``True`` nor ``False`` is an honest answer. The honest answer is
``INDETERMINATE``: the evidence does not decide the question.

Forge therefore makes this a first-class value rather than a judgement call made
later by a human reading a report. The six-status gate vocabulary in
:mod:`forge_evidence` maps directly onto it: an ``INDETERMINATE`` comparison
becomes an ``INCONCLUSIVE`` gate, and no amount of language-model confidence can
promote it to ``PASS``.

The connectives implemented here are Kleene's strong three-valued logic, chosen
because it has the property Forge needs: ``INDETERMINATE`` is absorbing for
conjunction unless some operand is already decisively ``FALSE``. In other words,
one unknown does not poison an already-failing gate (you still learn it failed),
but it does prevent an otherwise-passing gate from claiming success.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class Trivalent(Enum):
    """A truth value that admits ignorance."""

    FALSE = "false"
    INDETERMINATE = "indeterminate"
    TRUE = "true"

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def of(cls, value: object) -> "Trivalent":
        """Coerce a Python truth value, or pass a :class:`Trivalent` through.

        ``None`` is interpreted as ``INDETERMINATE``, which makes it convenient
        to lift optional results.
        """
        if isinstance(value, Trivalent):
            return value
        if value is None:
            return cls.INDETERMINATE
        return cls.TRUE if value else cls.FALSE

    # ------------------------------------------------------------------
    # Kleene connectives
    # ------------------------------------------------------------------
    def __and__(self, other: "Trivalent") -> "Trivalent":
        if not isinstance(other, Trivalent):
            return NotImplemented
        if self is Trivalent.FALSE or other is Trivalent.FALSE:
            return Trivalent.FALSE
        if self is Trivalent.INDETERMINATE or other is Trivalent.INDETERMINATE:
            return Trivalent.INDETERMINATE
        return Trivalent.TRUE

    def __or__(self, other: "Trivalent") -> "Trivalent":
        if not isinstance(other, Trivalent):
            return NotImplemented
        if self is Trivalent.TRUE or other is Trivalent.TRUE:
            return Trivalent.TRUE
        if self is Trivalent.INDETERMINATE or other is Trivalent.INDETERMINATE:
            return Trivalent.INDETERMINATE
        return Trivalent.FALSE

    def __invert__(self) -> "Trivalent":
        if self is Trivalent.TRUE:
            return Trivalent.FALSE
        if self is Trivalent.FALSE:
            return Trivalent.TRUE
        return Trivalent.INDETERMINATE

    def implies(self, other: "Trivalent") -> "Trivalent":
        return (~self) | other

    # ------------------------------------------------------------------
    # Interrogation
    # ------------------------------------------------------------------
    @property
    def is_known(self) -> bool:
        return self is not Trivalent.INDETERMINATE

    @property
    def is_true(self) -> bool:
        """Strictly true. ``INDETERMINATE`` is *not* true."""
        return self is Trivalent.TRUE

    @property
    def is_false(self) -> bool:
        """Strictly false. ``INDETERMINATE`` is *not* false."""
        return self is Trivalent.FALSE

    def __bool__(self) -> bool:
        """Deliberately unavailable.

        Allowing ``bool()`` would let ``if comparison:`` silently treat an
        unknown result as a failure, which is exactly the class of bug this type
        exists to prevent. Call :attr:`is_true` or :attr:`is_false` and say which
        one you mean.
        """
        raise TypeError(
            "Trivalent has no boolean interpretation; "
            "use .is_true / .is_false / .is_known so that the handling of "
            "INDETERMINATE is explicit at the call site"
        )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


def all_true(values: Iterable[Trivalent]) -> Trivalent:
    """Kleene conjunction over an iterable. Empty iterable yields ``TRUE``."""
    result = Trivalent.TRUE
    for value in values:
        result = result & value
        if result is Trivalent.FALSE:
            # FALSE is absorbing; short-circuit but keep the result honest.
            return Trivalent.FALSE
    return result


def any_true(values: Iterable[Trivalent]) -> Trivalent:
    """Kleene disjunction over an iterable. Empty iterable yields ``FALSE``."""
    result = Trivalent.FALSE
    for value in values:
        result = result | value
        if result is Trivalent.TRUE:
            return Trivalent.TRUE
    return result


TRUE = Trivalent.TRUE
FALSE = Trivalent.FALSE
INDETERMINATE = Trivalent.INDETERMINATE

__all__ = ["Trivalent", "all_true", "any_true", "TRUE", "FALSE", "INDETERMINATE"]
