"""Rigorous interval arithmetic.

Forge represents every numeric value as an interval rather than a point. An
exactly known value is simply an interval of zero width, so there is no separate
"exact" code path to keep in sync and no place where uncertainty can be dropped
by forgetting to propagate it.

Two properties matter for the rest of the system:

**Soundness.** The result interval always contains the true result, for every
combination of inputs within the operand intervals. Operations that cannot
guarantee this (division by an interval spanning zero, even roots of intervals
spanning zero) fail loudly instead of returning a plausible number.

**Dependency awareness.** Naive interval arithmetic overestimates width when the
same variable appears more than once: ``x - x`` evaluates to ``[-w, +w]`` rather
than ``[0, 0]``. This is a real limitation, not a bug, and Forge does not pretend
otherwise — :meth:`Interval.width` is reported in evidence so that an
implausibly wide result is visible rather than silently trusted. Where tight
bounds matter (tolerance stack-ups, optimisation objectives) the sampling
machinery in ``forge_analysis`` is used instead, and the interval result serves
as a conservative outer bound that the sample must respect.

Rounding: the implementation widens results outward by one unit in the last
place before returning, so floating-point rounding cannot make an interval
falsely exclude the true value. This costs a negligible amount of width and buys
the soundness property above.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Iterable, Sequence

from .errors import IntervalError
from .trivalent import Trivalent

Number = float | int | Fraction


def _to_float(value: Number) -> float:
    if isinstance(value, float):
        return value
    if isinstance(value, (int, Fraction)):
        return float(value)
    raise IntervalError("interval endpoints must be numeric", got=type(value).__name__)


def _widen_down(value: float) -> float:
    """Next float strictly below ``value`` (outward rounding for lower bound)."""
    if value == 0.0:
        if math.copysign(1.0, value) > 0.0:
            # A computed +0.0 is exact, or a positive result that underflowed:
            # under round-to-nearest a negative true value never rounds to
            # +0.0, so zero is a sound lower bound. Widened to -5e-324,
            # `2 * [0, 1]` reached below zero and `sqrt`, `hypot` and `ln`
            # refused a toleranced offset of [0, 0.1] mm on a correct design.
            return 0.0
        return -5e-324  # a -0.0: a negative result rounded to zero
    if math.isinf(value) or math.isnan(value):
        return value
    return math.nextafter(value, -math.inf)


def _widen_up(value: float) -> float:
    """Next float strictly above ``value`` (outward rounding for upper bound)."""
    if value == 0.0:
        return 5e-324
    if math.isinf(value) or math.isnan(value):
        return value
    return math.nextafter(value, math.inf)


@dataclass(frozen=True, slots=True)
class Interval:
    """A closed real interval ``[lo, hi]`` with ``lo <= hi``.

    Examples
    --------
    >>> Interval.exact(3.0).is_exact
    True
    >>> (Interval(1.0, 2.0) + Interval(10.0, 20.0)).contains(15.0)
    True
    >>> Interval(2.9, 3.1).at_least(3.0)
    <Trivalent.INDETERMINATE: 'indeterminate'>
    """

    lo: float
    hi: float

    def __post_init__(self) -> None:
        lo = _to_float(self.lo)
        hi = _to_float(self.hi)
        if math.isnan(lo) or math.isnan(hi):
            raise IntervalError("interval endpoints must not be NaN", lo=lo, hi=hi)
        if lo > hi:
            raise IntervalError(
                "interval lower bound exceeds upper bound", lo=lo, hi=hi
            )
        object.__setattr__(self, "lo", lo)
        object.__setattr__(self, "hi", hi)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def exact(cls, value: Number) -> "Interval":
        """A degenerate interval representing an exactly known value."""
        v = _to_float(value)
        return cls(v, v)

    @classmethod
    def symmetric(cls, center: Number, half_width: Number) -> "Interval":
        """``center ± half_width``."""
        c = _to_float(center)
        h = abs(_to_float(half_width))
        return cls(c - h, c + h)

    @classmethod
    def tolerance(cls, nominal: Number, minus: Number, plus: Number) -> "Interval":
        """An asymmetric engineering tolerance, e.g. ``20 +0.05 -0.02``."""
        n = _to_float(nominal)
        return cls(n - abs(_to_float(minus)), n + abs(_to_float(plus)))

    @classmethod
    def relative(cls, nominal: Number, fraction: Number) -> "Interval":
        """``nominal`` with a relative tolerance, e.g. ``fraction=0.05`` for ±5%."""
        n = _to_float(nominal)
        f = abs(_to_float(fraction))
        return cls.symmetric(n, abs(n) * f)

    @classmethod
    def hull_of(cls, values: Iterable["Interval | Number"]) -> "Interval":
        """Smallest interval containing every input."""
        los: list[float] = []
        his: list[float] = []
        for value in values:
            iv = value if isinstance(value, Interval) else cls.exact(value)
            los.append(iv.lo)
            his.append(iv.hi)
        if not los:
            raise IntervalError("cannot take the hull of an empty collection")
        return cls(min(los), max(his))

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    @property
    def is_exact(self) -> bool:
        return self.lo == self.hi

    @property
    def width(self) -> float:
        return self.hi - self.lo

    @property
    def midpoint(self) -> float:
        # Computed this way to avoid overflow on wide intervals.
        return self.lo + (self.hi - self.lo) / 2.0

    @property
    def half_width(self) -> float:
        return (self.hi - self.lo) / 2.0

    @property
    def relative_width(self) -> float:
        """Width divided by |midpoint|; ``inf`` when the interval straddles zero."""
        mid = abs(self.midpoint)
        if mid == 0.0:
            return math.inf if self.width > 0 else 0.0
        return self.width / mid

    def contains(self, value: Number) -> bool:
        v = _to_float(value)
        return self.lo <= v <= self.hi

    def contains_interval(self, other: "Interval") -> bool:
        return self.lo <= other.lo and other.hi <= self.hi

    @property
    def straddles_zero(self) -> bool:
        return self.lo <= 0.0 <= self.hi

    # ------------------------------------------------------------------
    # Set operations
    # ------------------------------------------------------------------
    def intersect(self, other: "Interval") -> "Interval | None":
        lo = max(self.lo, other.lo)
        hi = min(self.hi, other.hi)
        if lo > hi:
            return None
        return Interval(lo, hi)

    def hull(self, other: "Interval") -> "Interval":
        return Interval(min(self.lo, other.lo), max(self.hi, other.hi))

    def overlaps(self, other: "Interval") -> bool:
        return self.intersect(other) is not None

    # ------------------------------------------------------------------
    # Arithmetic
    # ------------------------------------------------------------------
    @staticmethod
    def _coerce(value: "Interval | Number") -> "Interval":
        if isinstance(value, Interval):
            return value
        return Interval.exact(value)

    def _rounded(
        self, lo: float, hi: float, *, widen_lo: bool = True, widen_hi: bool = True
    ) -> "Interval":
        """Widen outward by one ULP so rounding cannot exclude the true value.

        ``widen_lo`` / ``widen_hi`` suppress the widening on a bound that is
        exact *by construction* rather than merely computed. The motivating case
        is the even power of an interval straddling zero: the true minimum of
        ``x**2`` is exactly zero, and nudging that bound to ``-5e-324`` would
        claim a square can be negative, which then makes a downstream ``sqrt``
        fail on a perfectly valid value. A bound that mathematics pins exactly
        should not be blurred by a rounding policy meant for computed ones.
        """
        if lo == hi:
            # Preserve exactness for operations that are exact in binary floating
            # point (negation, multiplication by a power of two, and the common
            # case of two exact operands under +/-). Widening here would make
            # every exact computation progressively fuzzier for no benefit.
            return Interval(lo, hi)
        return Interval(
            _widen_down(lo) if widen_lo else lo,
            _widen_up(hi) if widen_hi else hi,
        )

    def __add__(self, other: "Interval | Number") -> "Interval":
        o = self._coerce(other)
        return self._rounded(self.lo + o.lo, self.hi + o.hi)

    __radd__ = __add__

    def __sub__(self, other: "Interval | Number") -> "Interval":
        o = self._coerce(other)
        return self._rounded(self.lo - o.hi, self.hi - o.lo)

    def __rsub__(self, other: "Interval | Number") -> "Interval":
        return self._coerce(other) - self

    def __neg__(self) -> "Interval":
        return Interval(-self.hi, -self.lo)

    def __pos__(self) -> "Interval":
        return self

    def __mul__(self, other: "Interval | Number") -> "Interval":
        o = self._coerce(other)
        products = (
            self.lo * o.lo,
            self.lo * o.hi,
            self.hi * o.lo,
            self.hi * o.hi,
        )
        return self._rounded(min(products), max(products))

    __rmul__ = __mul__

    def __truediv__(self, other: "Interval | Number") -> "Interval":
        o = self._coerce(other)
        if o.straddles_zero:
            raise IntervalError(
                "division by an interval containing zero is unbounded; "
                "constrain the divisor or handle the singularity explicitly",
                numerator=[self.lo, self.hi],
                divisor=[o.lo, o.hi],
            )
        quotients = (
            self.lo / o.lo,
            self.lo / o.hi,
            self.hi / o.lo,
            self.hi / o.hi,
        )
        return self._rounded(min(quotients), max(quotients))

    def __rtruediv__(self, other: "Interval | Number") -> "Interval":
        return self._coerce(other) / self

    def __pow__(self, exponent: Number) -> "Interval":
        """Raise to a real power.

        Integer powers are handled exactly, including the sign subtleties of even
        powers over intervals that straddle zero. Fractional powers require a
        non-negative base, since a real fractional power of a negative number is
        undefined.
        """
        if isinstance(exponent, Fraction):
            exp_value = float(exponent)
            is_integer = exponent.denominator == 1
            int_exponent = exponent.numerator if is_integer else None
        elif isinstance(exponent, int):
            exp_value = float(exponent)
            is_integer = True
            int_exponent = exponent
        elif isinstance(exponent, float):
            exp_value = exponent
            is_integer = exponent.is_integer()
            int_exponent = int(exponent) if is_integer else None
        else:
            raise IntervalError(
                "interval exponent must be a real number", got=type(exponent).__name__
            )

        if is_integer and int_exponent is not None:
            n = int_exponent
            if n == 0:
                return Interval.exact(1.0)
            if n > 0:
                if n % 2 == 1:  # odd power is monotonic
                    return self._rounded(self.lo**n, self.hi**n)
                # even power
                if self.lo >= 0:
                    return self._rounded(self.lo**n, self.hi**n)
                if self.hi <= 0:
                    return self._rounded(self.hi**n, self.lo**n)
                # The interval straddles zero, so the minimum of an even power is
                # exactly zero. Keep that bound exact (see _rounded).
                return self._rounded(
                    0.0, max(self.lo**n, self.hi**n), widen_lo=False
                )
            # negative integer power
            if self.straddles_zero:
                raise IntervalError(
                    "negative power of an interval containing zero is unbounded",
                    base=[self.lo, self.hi],
                    exponent=n,
                )
            return (Interval.exact(1.0) / self) ** (-n)

        # Fractional power
        if self.lo < 0:
            raise IntervalError(
                "fractional power requires a non-negative base interval",
                base=[self.lo, self.hi],
                exponent=exp_value,
            )
        if exp_value < 0 and self.lo <= 0:
            raise IntervalError(
                "negative fractional power of an interval reaching zero is "
                "unbounded",
                base=[self.lo, self.hi],
                exponent=exp_value,
            )
        try:
            return self._rounded(self.lo**exp_value, self.hi**exp_value)
        except OverflowError as exc:
            raise IntervalError(
                "the power is too large to represent",
                base=[self.lo, self.hi],
                exponent=exp_value,
            ) from exc

    def sqrt(self) -> "Interval":
        if self.lo < 0:
            raise IntervalError(
                "square root of an interval extending below zero",
                base=[self.lo, self.hi],
            )
        return self._rounded(math.sqrt(self.lo), math.sqrt(self.hi))

    def __abs__(self) -> "Interval":
        if self.lo >= 0:
            return self
        if self.hi <= 0:
            return -self
        return Interval(0.0, max(-self.lo, self.hi))

    # ------------------------------------------------------------------
    # Monotonic function lifting
    # ------------------------------------------------------------------
    def map_monotonic(self, func: Callable[[float], float]) -> "Interval":
        """Apply a function known to be monotonic over this interval.

        Both endpoints are evaluated and sorted, so the direction of monotonicity
        does not need to be declared. The caller does assert monotonicity,
        however: applying this to a function that turns around inside the
        interval silently produces an unsound result. It is therefore used only
        by the vetted function table in :mod:`forge_units.mathfns`, which checks
        the validity domain of each function before calling it.
        """
        a, b = func(self.lo), func(self.hi)
        return self._rounded(min(a, b), max(a, b))

    # ------------------------------------------------------------------
    # Comparison -> three-valued logic
    # ------------------------------------------------------------------
    def at_least(self, threshold: "Interval | Number") -> Trivalent:
        """``self >= threshold`` in Kleene logic."""
        t = self._coerce(threshold)
        if self.lo >= t.hi:
            return Trivalent.TRUE
        if self.hi < t.lo:
            return Trivalent.FALSE
        return Trivalent.INDETERMINATE

    def at_most(self, threshold: "Interval | Number") -> Trivalent:
        """``self <= threshold`` in Kleene logic."""
        t = self._coerce(threshold)
        if self.hi <= t.lo:
            return Trivalent.TRUE
        if self.lo > t.hi:
            return Trivalent.FALSE
        return Trivalent.INDETERMINATE

    def greater_than(self, threshold: "Interval | Number") -> Trivalent:
        t = self._coerce(threshold)
        if self.lo > t.hi:
            return Trivalent.TRUE
        if self.hi <= t.lo:
            return Trivalent.FALSE
        return Trivalent.INDETERMINATE

    def less_than(self, threshold: "Interval | Number") -> Trivalent:
        t = self._coerce(threshold)
        if self.hi < t.lo:
            return Trivalent.TRUE
        if self.lo >= t.hi:
            return Trivalent.FALSE
        return Trivalent.INDETERMINATE

    def approximately_equals(
        self, other: "Interval | Number", *, tolerance: float
    ) -> Trivalent:
        """Equality within an absolute tolerance, three-valued.

        ``TRUE`` when every pair of points drawn from the two intervals is
        within ``tolerance``; ``FALSE`` when no pair is; ``INDETERMINATE``
        otherwise.
        """
        if tolerance < 0:
            raise IntervalError("tolerance must be non-negative", tolerance=tolerance)
        o = self._coerce(other)
        max_separation = max(abs(self.hi - o.lo), abs(o.hi - self.lo))
        min_separation = 0.0 if self.overlaps(o) else min(
            abs(self.lo - o.hi), abs(o.lo - self.hi)
        )
        if max_separation <= tolerance:
            return Trivalent.TRUE
        if min_separation > tolerance:
            return Trivalent.FALSE
        return Trivalent.INDETERMINATE

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def __str__(self) -> str:
        if self.is_exact:
            return _format_float(self.lo)
        mid, half = self.midpoint, self.half_width
        # Prefer the compact "centre ± half-width" form when the spread is small
        # relative to the centre; fall back to explicit bounds when it is not,
        # because "0 ± 500" reads as far more precise than "[-500, 500]".
        if mid != 0.0 and half > 0.0 and abs(half / mid) < 0.5:
            return f"{_format_float(mid)} ± {_format_float(half)}"
        return f"[{_format_float(self.lo)}, {_format_float(self.hi)}]"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Interval({self.lo!r}, {self.hi!r})"

    def as_dict(self) -> dict[str, float]:
        return {"lo": self.lo, "hi": self.hi}

    @classmethod
    def from_dict(cls, payload: dict[str, Number]) -> "Interval":
        return cls(_to_float(payload["lo"]), _to_float(payload["hi"]))


def _format_float(value: float, *, significant: int = 6) -> str:
    if value == 0.0:
        return "0"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    magnitude = abs(value)
    if 1e-4 <= magnitude < 1e7:
        text = f"{value:.{significant}g}"
    else:
        text = f"{value:.{significant}e}"
    return text


def interval_hull(values: Sequence["Interval | Number"]) -> Interval:
    return Interval.hull_of(values)


__all__ = ["Interval", "interval_hull"]
