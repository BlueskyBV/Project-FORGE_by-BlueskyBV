"""Dimensionally aware mathematical functions over :class:`Quantity`.

Every function here is *total on its declared domain and explicit about it*. A
function that would be applied outside its validity domain raises rather than
returning a number that looks usable, and every function that is not monotonic
over the whole real line handles interval inputs by locating the extrema inside
the interval rather than merely evaluating the endpoints.

That last point is where naive implementations go wrong. ``cos`` of the interval
``[0.1 rad, 6.2 rad]`` is *not* ``[cos(0.1), cos(6.2)]``: the true range is
``[-1, 1]``, because the interval contains a turning point. Getting this right is
what makes the uncertainty propagation sound rather than decorative.

This table is the complete set of functions callable from a ForgeIR expression.
It is deliberately small. Anything not here cannot appear in a design document,
which keeps the expression language analysable.
"""

from __future__ import annotations

import math
from typing import Callable, Mapping

from .dimension import DIMENSIONLESS
from .errors import DimensionalityError, ForgeUnitsError
from .interval import Interval
from .quantity import Quantity
from .unit import DIMENSIONLESS_UNIT, RADIAN, parse_unit


class MathDomainError(ForgeUnitsError):
    """A function was applied outside its validity domain."""

    code = "FU1007_MATH_DOMAIN"


def _require_dimensionless(value: Quantity, *, function: str) -> Interval:
    if not value.is_dimensionless:
        raise DimensionalityError(
            f"{function} requires a dimensionless argument",
            function=function,
            unit=value.unit.symbol,
            measures=value.dimension.describe(),
        )
    # Angles are dimensionless but carry a scale (deg -> rad), so convert
    # through the unit rather than reading the raw magnitude.
    return value.to(DIMENSIONLESS_UNIT).magnitude


def _dimensionless(interval: Interval) -> Quantity:
    return Quantity(interval, DIMENSIONLESS_UNIT)


# ----------------------------------------------------------------------
# Periodic trigonometric functions, with correct interval ranges
# ----------------------------------------------------------------------
_TWO_PI = 2.0 * math.pi


def _periodic_extrema(
    interval: Interval,
    func: Callable[[float], float],
    critical_offset: float,
) -> Interval:
    """Range of a sinusoid over an interval, accounting for turning points.

    ``critical_offset`` is the phase of the first maximum: ``pi/2`` for ``sin``,
    ``0`` for ``cos``. Maxima occur at ``critical_offset + 2*k*pi`` and minima at
    ``critical_offset + (2*k+1)*pi``.
    """
    if interval.width >= _TWO_PI:
        return Interval(-1.0, 1.0)

    lo_value, hi_value = func(interval.lo), func(interval.hi)
    low = min(lo_value, hi_value)
    high = max(lo_value, hi_value)

    # Does the interval contain a maximum (value +1)?
    k_start = math.floor((interval.lo - critical_offset) / _TWO_PI)
    for k in (k_start, k_start + 1, k_start + 2):
        turning = critical_offset + k * _TWO_PI
        if interval.lo <= turning <= interval.hi:
            high = 1.0
            break

    # Does it contain a minimum (value -1)?
    trough_offset = critical_offset + math.pi
    k_start = math.floor((interval.lo - trough_offset) / _TWO_PI)
    for k in (k_start, k_start + 1, k_start + 2):
        turning = trough_offset + k * _TWO_PI
        if interval.lo <= turning <= interval.hi:
            low = -1.0
            break

    return Interval(max(low, -1.0), min(high, 1.0))


def sin(value: Quantity) -> Quantity:
    """Sine of an angle. Accepts ``deg`` or ``rad``; both are dimensionless."""
    radians = _require_dimensionless(value, function="sin")
    return _dimensionless(_periodic_extrema(radians, math.sin, math.pi / 2.0))


def cos(value: Quantity) -> Quantity:
    radians = _require_dimensionless(value, function="cos")
    return _dimensionless(_periodic_extrema(radians, math.cos, 0.0))


def tan(value: Quantity) -> Quantity:
    """Tangent. Raises if the interval spans a pole, where the range is unbounded."""
    radians = _require_dimensionless(value, function="tan")
    # Poles at pi/2 + k*pi.
    k_start = math.floor((radians.lo - math.pi / 2.0) / math.pi)
    for k in (k_start, k_start + 1, k_start + 2):
        pole = math.pi / 2.0 + k * math.pi
        if radians.lo <= pole <= radians.hi:
            raise MathDomainError(
                "tan is unbounded across a pole inside the argument interval; "
                "narrow the angle or reformulate to avoid the singularity",
                argument=[radians.lo, radians.hi],
                pole=pole,
            )
    return _dimensionless(radians.map_monotonic(math.tan))


def asin(value: Quantity) -> Quantity:
    """Arcsine, returning radians. Domain ``[-1, 1]``."""
    argument = _require_dimensionless(value, function="asin")
    if argument.lo < -1.0 or argument.hi > 1.0:
        raise MathDomainError(
            "asin requires an argument interval within [-1, 1]",
            argument=[argument.lo, argument.hi],
            hint="a value outside this range usually means a geometric "
            "construction is infeasible, e.g. a link too short to close a loop",
        )
    return Quantity(argument.map_monotonic(math.asin), RADIAN)


def acos(value: Quantity) -> Quantity:
    argument = _require_dimensionless(value, function="acos")
    if argument.lo < -1.0 or argument.hi > 1.0:
        raise MathDomainError(
            "acos requires an argument interval within [-1, 1]",
            argument=[argument.lo, argument.hi],
            hint="a value outside this range usually means a geometric "
            "construction is infeasible, e.g. a link too short to close a loop",
        )
    return Quantity(argument.map_monotonic(math.acos), RADIAN)


def atan(value: Quantity) -> Quantity:
    argument = _require_dimensionless(value, function="atan")
    return Quantity(argument.map_monotonic(math.atan), RADIAN)


def atan2(y: Quantity, x: Quantity) -> Quantity:
    """Two-argument arctangent, returning radians in ``(-pi, pi]``.

    Both arguments must share a dimension (they are typically both lengths), and
    the result is dimensionless. Interval handling is conservative: when the
    inputs straddle the branch cut on the negative x-axis, the full range is
    returned rather than an interval that wraps.
    """
    if y.dimension != x.dimension:
        raise DimensionalityError(
            "atan2 requires both arguments to share a dimension",
            y_unit=y.unit.symbol,
            x_unit=x.unit.symbol,
        )
    # Both operands are reduced to SI so that two dimensionless arguments given
    # in different angular units (deg and rad) cannot silently disagree.
    yi = y.si_magnitude
    xi = x.si_magnitude
    if xi.lo < 0.0 and yi.straddles_zero:
        # The branch cut (the negative x axis) lies inside the box whenever
        # x reaches below zero and y touches zero -- not only when x is
        # wholly negative. Guarded on `xi.hi < 0`, atan2([-1, 1], [-2, 1])
        # came back [-2.678, 2.678], which excludes atan2(0, -2) = pi.
        return Quantity(Interval(-math.pi, math.pi), RADIAN)
    corners = [
        math.atan2(a, b) for a in (yi.lo, yi.hi) for b in (xi.lo, xi.hi)
    ]
    return Quantity(Interval(min(corners), max(corners)), RADIAN)


# ----------------------------------------------------------------------
# Algebraic functions
# ----------------------------------------------------------------------
def sqrt(value: Quantity) -> Quantity:
    """Square root, halving the dimension. ``sqrt(4 mm^2) == 2 mm``."""
    if value.magnitude.lo < 0.0:
        raise MathDomainError(
            "sqrt requires a non-negative argument interval",
            argument=[value.magnitude.lo, value.magnitude.hi],
            unit=value.unit.symbol,
        )
    return value.sqrt()


def hypot(a: Quantity, b: Quantity) -> Quantity:
    """Euclidean norm, preserving the shared dimension."""
    if a.dimension != b.dimension:
        raise DimensionalityError(
            "hypot requires both arguments to share a dimension",
            a_unit=a.unit.symbol,
            b_unit=b.unit.symbol,
        )
    converted = b.to(a.unit)
    return sqrt(a * a + converted * converted)


def abs_(value: Quantity) -> Quantity:
    return abs(value)


def exp(value: Quantity) -> Quantity:
    """Exponential. Requires a dimensionless argument."""
    argument = _require_dimensionless(value, function="exp")
    if argument.hi > 709.0:
        raise MathDomainError(
            "exp would overflow double precision",
            argument=[argument.lo, argument.hi],
        )
    return _dimensionless(argument.map_monotonic(math.exp))


def ln(value: Quantity) -> Quantity:
    """Natural logarithm. Requires a strictly positive dimensionless argument."""
    argument = _require_dimensionless(value, function="ln")
    if argument.lo <= 0.0:
        raise MathDomainError(
            "ln requires a strictly positive argument interval",
            argument=[argument.lo, argument.hi],
        )
    return _dimensionless(argument.map_monotonic(math.log))


def log10(value: Quantity) -> Quantity:
    argument = _require_dimensionless(value, function="log10")
    if argument.lo <= 0.0:
        raise MathDomainError(
            "log10 requires a strictly positive argument interval",
            argument=[argument.lo, argument.hi],
        )
    return _dimensionless(argument.map_monotonic(math.log10))


# ----------------------------------------------------------------------
# Selection and rounding
# ----------------------------------------------------------------------
def min_(a: Quantity, b: Quantity) -> Quantity:
    from .quantity import min_quantity

    return min_quantity([a, b])


def max_(a: Quantity, b: Quantity) -> Quantity:
    from .quantity import max_quantity

    return max_quantity([a, b])


def clamp(value: Quantity, low: Quantity, high: Quantity) -> Quantity:
    return min_(max_(value, low), high)


def round_to(value: Quantity, step: Quantity) -> Quantity:
    """Round to the nearest multiple of ``step``, preserving interval width.

    Used for snapping a computed dimension onto a manufacturing increment (a
    0.5 mm grid, a standard drill size). The interval is rounded outward so the
    result still contains every value the input could have taken.
    """
    if value.dimension != step.dimension:
        raise DimensionalityError(
            "round_to requires the step to share the value's dimension",
            value_unit=value.unit.symbol,
            step_unit=step.unit.symbol,
        )
    increment = step.to(value.unit).magnitude
    if not increment.is_exact or increment.lo <= 0.0:
        raise MathDomainError(
            "round_to requires an exact, strictly positive step",
            step=[increment.lo, increment.hi],
        )
    size = increment.lo
    lo = math.floor(value.magnitude.lo / size) * size
    hi = math.ceil(value.magnitude.hi / size) * size
    return Quantity(Interval(lo, hi), value.unit)


def deg(value: Quantity) -> Quantity:
    """Convert an angle to degrees."""
    return value.to(parse_unit("deg"))


def rad(value: Quantity) -> Quantity:
    """Convert an angle to radians."""
    return value.to(RADIAN)


#: The complete set of functions callable from a ForgeIR expression.
FUNCTION_TABLE: Mapping[str, Callable[..., Quantity]] = {
    "sin": sin,
    "cos": cos,
    "tan": tan,
    "asin": asin,
    "acos": acos,
    "atan": atan,
    "atan2": atan2,
    "sqrt": sqrt,
    "hypot": hypot,
    "abs": abs_,
    "exp": exp,
    "ln": ln,
    "log10": log10,
    "min": min_,
    "max": max_,
    "clamp": clamp,
    "round_to": round_to,
    "deg": deg,
    "rad": rad,
}

#: Named dimensionless constants available inside expressions.
CONSTANT_TABLE: Mapping[str, Quantity] = {
    "pi": Quantity(Interval.exact(math.pi), DIMENSIONLESS_UNIT),
    "tau": Quantity(Interval.exact(_TWO_PI), DIMENSIONLESS_UNIT),
    "e": Quantity(Interval.exact(math.e), DIMENSIONLESS_UNIT),
    "g0": Quantity(Interval.exact(9.80665), parse_unit("m/s^2")),
}

__all__ = [
    "FUNCTION_TABLE",
    "CONSTANT_TABLE",
    "MathDomainError",
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "atan2",
    "sqrt",
    "hypot",
    "exp",
    "ln",
    "log10",
    "clamp",
    "round_to",
    "deg",
    "rad",
]
