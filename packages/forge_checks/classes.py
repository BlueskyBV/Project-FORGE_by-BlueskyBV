"""Verification classes, design tolerances, and the verdict a measurement gives.

**Verification classes** (plan, section 4.5): every region of the part's
surface is checked one of three ways, and the report says which.

- :attr:`VerificationClass.EXACT`: every point and every surface is known
  exactly from the definitions;
- :attr:`VerificationClass.BOUNDED`: known exactly at its defining sizes,
  and between them the built part must lie between an inner and an outer
  limit (where roundings meet at a corner, a thread's flanks, letters'
  outlines until the font is read);
- :attr:`VerificationClass.CONSTRAINED`: a freeform region, held to its
  envelope and its constraints only.

**Design tolerances** (docs/definitions/sizes.md): a value's own
``+plus / -minus``, or the general tolerance, ISO 2768-1 class m: by the
nominal size, for linear sizes and for radii and chamfer heights; for
angles, by the length of the angle's shorter side. Under 0.5 mm, where the
standard gives nothing, Forge uses ±0.05 mm. Lengths are in millimetres and
angles in degrees here, whatever unit the spec wrote them in.

**The verdict** is interval logic (docs/V2-stage2.md, section 6). A
measurement is an interval: the value found, and how far it can be off at
worst. It PASSES when the whole interval lies within the tolerance, FAILS
when none of it does, and is INCONCLUSIVE otherwise, which holds the part as
a failure does. A measurement is fine enough only when its uncertainty is at
most an eighth of the tolerance band (a quarter of a symmetric tolerance's
half-width): then a part ``2u`` inside a limit is sure to pass, and one ``2u``
outside sure to fail (:func:`brackets`).

>>> general(25.0)
Tolerance(plus=0.2, minus=0.2, source='ISO 2768-m')
>>> general(4.0, RADIUS).plus, general(0.3).plus, general_angle(60.0).plus
(0.5, 0.05, 0.3333333333333333)
>>> judge(Interval(9.95, 10.05), 10.0, general(10.0)), judge(Interval(10.3, 10.4), 10.0, general(10.0))
(<Verdict.PASS: 'pass'>, <Verdict.FAIL: 'fail'>)
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass

from forge_spec.values import Value
from forge_units import DIMENSIONLESS, LENGTH, Interval, Q

__all__ = [
    "LINEAR",
    "RADIUS",
    "Brackets",
    "Tolerance",
    "Verdict",
    "VerificationClass",
    "brackets",
    "fine_enough",
    "general",
    "general_angle",
    "judge",
    "tolerance_of",
]


class VerificationClass(enum.Enum):
    """How a region of the part's surface is checked."""

    EXACT = "exact"
    BOUNDED = "bounded"
    CONSTRAINED = "constrained"


class Verdict(enum.Enum):
    """What a check finds: INCONCLUSIVE holds the part, as FAIL does."""

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


#: The general tolerance's two columns (sizes.md).
LINEAR, RADIUS = "linear", "radius"

#: ISO 2768-1 class m: (nominal up to, linear ±, radii and chamfer heights ±), in mm.
_TABLE = (
    (3.0, 0.1, 0.2),
    (6.0, 0.1, 0.5),
    (30.0, 0.2, 1.0),
    (120.0, 0.3, 1.0),
    (400.0, 0.5, 1.0),
    (1000.0, 0.8, 1.0),
    (2000.0, 1.2, 1.0),
    (4000.0, 2.0, 1.0),
)
#: Below the standard's least size, 0.5 mm.
_SMALL, _SMALL_TOLERANCE = 0.5, 0.05
#: ISO 2768-1 class m angles: (the shorter side up to, ± in degrees).
_ANGLES = (
    (10.0, 1.0),
    (50.0, 30 / 60),
    (120.0, 20 / 60),
    (400.0, 10 / 60),
    (math.inf, 5 / 60),
)
GENERAL = "ISO 2768-m"
STATED = "stated"
_ANGLE_UNITS = frozenset({"deg", "rad", "rev", "arcmin", "arcsec"})


@dataclass(frozen=True)
class Tolerance:
    """How far a made size may be from its nominal one: up to ``plus`` above and ``minus`` below (mm or degrees)."""

    plus: float
    minus: float
    source: str = STATED

    def __post_init__(self) -> None:
        for name in ("plus", "minus"):
            bound = getattr(self, name)
            if not (isinstance(bound, float) and math.isfinite(bound) and bound >= 0):
                raise ValueError(
                    f"a tolerance's {name} is a finite float >= 0: {bound!r}"
                )
        if self.plus + self.minus <= 0:
            raise ValueError("a tolerance allows something: +0/-0 is none")

    @property
    def band(self) -> float:
        """How wide the range of good sizes is."""
        return self.plus + self.minus

    def limits(self, nominal: float) -> Interval:
        """The good sizes: from the nominal less ``minus`` to the nominal plus ``plus``."""
        return Interval(nominal - self.minus, nominal + self.plus)


def general(nominal: float, column: str = LINEAR) -> Tolerance:
    """ISO 2768-1 class m for a size: linear (lengths, diameters, depths, positions) or radius (radii and chamfer heights)."""
    if column not in (LINEAR, RADIUS):
        raise ValueError(
            f"the general tolerance's columns are {LINEAR!r} and {RADIUS!r}"
        )
    size = abs(float(nominal))
    if not math.isfinite(size):
        raise ValueError(f"a size is finite: {nominal!r}")
    if size < _SMALL:
        return Tolerance(_SMALL_TOLERANCE, _SMALL_TOLERANCE, GENERAL)
    for up_to, linear, radius in _TABLE:
        if size <= up_to:
            plus = linear if column == LINEAR else radius
            return Tolerance(plus, plus, GENERAL)
    raise ValueError(
        f"ISO 2768-1 gives no general tolerance over {_TABLE[-1][0]:g} mm: {nominal:g} mm"
    )


def general_angle(shorter_side: float) -> Tolerance:
    """ISO 2768-1 class m for an angle, in degrees, by the length of its shorter side (mm)."""
    side = float(shorter_side)
    if not (math.isfinite(side) and side >= 0):
        raise ValueError(f"an angle's shorter side is a length >= 0: {shorter_side!r}")
    for up_to, degrees in _ANGLES:
        if side <= up_to:
            return Tolerance(degrees, degrees, GENERAL)
    raise AssertionError("the last row has no end")  # pragma: no cover


def tolerance_of(
    value: Value, column: str = LINEAR, shorter_side: float | None = None
) -> Tolerance:
    """A spec value's tolerance in mm (or degrees, for an angle), about the size it is made to: its own, or the general one.

    A value is made at the middle of its tolerance (``Value.made``,
    sizes.md), and every check's nominal is the made size, so a stated
    tolerance is given as half its band either way: the same limits as
    written (10 mm +0.1/-0 is 10.05 mm ±0.05). It is in the value's own
    unit, and is converted as the value is. An angle's general tolerance
    goes by the length of its shorter side.
    """
    unit = value.quantity.unit
    if unit.dimension == LENGTH:
        target = "mm"
    elif unit.dimension == DIMENSIONLESS and unit.symbol in _ANGLE_UNITS:
        target = "deg"
    else:
        raise ValueError(
            f"a size or an angle has a tolerance, not a value in {unit.symbol!r}"
        )
    if value.tolerance is not None:
        band = value.tolerance.plus + value.tolerance.minus
        half = float(Q(band / 2, unit.symbol).value_in(target))
        return Tolerance(half, half, STATED)
    if target == "deg":
        if shorter_side is None:
            raise ValueError("an angle's general tolerance goes by its shorter side")
        return general_angle(shorter_side)
    return general(value.made_in("mm"), column)


def judge(measured: Interval, nominal: float, tolerance: Tolerance) -> Verdict:
    """PASS when all the measurement lies within the tolerance, FAIL when none does, INCONCLUSIVE between."""
    good = tolerance.limits(nominal)
    if not (math.isfinite(measured.lo) and math.isfinite(measured.hi)):
        return Verdict.INCONCLUSIVE
    if good.contains_interval(measured):
        return Verdict.PASS
    if not good.overlaps(measured):
        return Verdict.FAIL
    return Verdict.INCONCLUSIVE


def fine_enough(uncertainty: float, tolerance: Tolerance) -> bool:
    """Whether a measurement this uncertain can judge the tolerance: at most an eighth of its band."""
    return 0 <= uncertainty <= tolerance.band / 8


@dataclass(frozen=True)
class Brackets:
    """Sizes a check must pass (``near``, 2u inside each limit) and fail (``beyond``, 2u outside)."""

    near: tuple[float, float]
    beyond: tuple[float, float]


def brackets(nominal: float, tolerance: Tolerance, uncertainty: float) -> Brackets:
    """The near-misses and mutants round a tolerance's limits, for a measurement ``uncertainty`` uncertain."""
    if not fine_enough(uncertainty, tolerance):
        raise ValueError(
            f"a measurement uncertain by {uncertainty:g} can't judge a band of {tolerance.band:g}"
        )
    low, high = nominal - tolerance.minus, nominal + tolerance.plus
    margin = 2 * uncertainty
    return Brackets((low + margin, high - margin), (low - margin, high + margin))


def bracket_mutants(
    nominal: float, tolerance: Tolerance, uncertainty: float
) -> tuple[tuple[float, Verdict], ...]:
    """Values a built part must pass at (``2u`` inside each limit) and fail at (``2u`` outside)."""
    b = brackets(nominal, tolerance, uncertainty)
    return (
        (b.near[0], Verdict.PASS),
        (b.near[1], Verdict.PASS),
        (b.beyond[0], Verdict.FAIL),
        (b.beyond[1], Verdict.FAIL),
    )
