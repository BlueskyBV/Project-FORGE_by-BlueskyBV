"""Quantity: a magnitude interval attached to a unit.

This is the value type that flows through the whole of Forge. Three properties
distinguish it from the usual "float plus unit" pair:

1. **The magnitude is always an interval.** An exactly known value is an
   interval of zero width. There is no separate exact path, so uncertainty
   cannot be lost by forgetting to propagate it.

2. **Dimensional errors are raised, never coerced.** Adding a length to a force
   raises; multiplying them produces the correct new dimension. The unit of a
   product is derived symbolically, so ``N * mm`` yields ``N*mm`` rather than
   being silently normalised to joules.

3. **Comparison is three-valued.** ``thickness >= minimum`` returns
   :class:`~forge_units.trivalent.Trivalent`, so a comparison whose answer the
   evidence does not determine reports ``INDETERMINATE`` instead of guessing.

Quantities are immutable and hashable, which lets them appear directly in the
compiler's content-addressed cache keys.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Iterable, Mapping, Sequence

from .dimension import Dimension
from .errors import DimensionalityError, OffsetUnitError, UnitConversionError
from .interval import Interval, Number
from .trivalent import Trivalent
from .unit import Unit, parse_unit, require_compatible, units_for_dimension

UnitLike = Unit | str


def _resolve_unit(unit: UnitLike) -> Unit:
    return unit if isinstance(unit, Unit) else parse_unit(unit)


def _a_number(payload: Mapping[str, Any], key: str, where: str) -> float:
    """One field of a serialised quantity, as a float, or a stated failure.

    ``float()`` on whatever arrived was the whole of this, and it raised a bare
    ``ValueError`` whenever the value was not a number. That exception is not a
    ``ForgeUnitsError``, so every layer above passed it along untouched: it went
    through the decoder, the role, the orchestrator and out of the CLI as a
    one-line traceback, taking a fifty-minute run's artefacts with it.

    Observed live: `{"magnitude": "fillet_thickness", "unit": "mm"}` -- a model
    naming the parameter it wanted the value to come from, which is a real
    intention with a real spelling (`{"expression": "fillet_thickness"}`) and
    deserves to be told so.
    """
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
        got = f"'{value}'" if isinstance(value, str) else type(value).__name__
        hint = (
            f"write a number, e.g. {{\"{key}\": 12.0, \"unit\": \"mm\"}}."
        )
        if isinstance(value, str):
            hint += (
                f" To take the value from another parameter, that is an "
                f'expression, not a magnitude: {{"expression": "{value}", '
                '"unit": "mm"}.'
            )
        raise UnitConversionError(
            f"a quantity's {where} must be a number",
            got=got,
            hint=hint,
        )
    number = float(value)
    if not math.isfinite(number):
        # `1e400` and the JSON `Infinity` literal both decode to inf, which
        # the reader's own float check never sees; a diameter of inf then
        # built, and every later function of it raised a bare ValueError.
        raise UnitConversionError(
            f"a quantity's {where} must be finite",
            got=str(value),
        )
    return number


#: Angle units other than the radian. An angle is dimensionless here (ADR-0004),
#: so a plain number IS an angle -- in radians -- and nothing stops it being
#: added to one or converted into one.
ANGLES_NOT_RADIANS = frozenset({"deg", "rev", "arcmin", "arcsec"})
_RADIAN_WORDS = re.compile(r"(?<![A-Za-z0-9_])(pi|tau|asin|acos|atan|atan2)(?![A-Za-z0-9_])")


def is_a_plain_number(value: "Quantity") -> bool:
    """A quantity with no unit at all: not an angle, a ratio unit or a count
    in some scaled unit -- `360 / n`, a bare `10`."""
    return value.unit.symbol == "" and value.unit.scale == 1.0 \
        and value.unit.offset == 0.0


def a_plain_number_in(value: "Quantity", unit: Unit,
                      source: str = "") -> "Quantity | None":
    """`value` read in `unit`, where `unit` is an angle other than the
    radian and `value` is a plain number written without radians in mind.

    The stepper plate's bolt circle: `bolt_circle_angle_step` declared in
    degrees as `360 / bolt_circle_hole_count`. The expression is a plain 60,
    and a plain number is an angle in radians, so the step came out 60
    radians -- 3437.7 degrees -- and the six holes landed at uneven angles
    round the circle, every figure the brief gave right. In a slot declared
    in degrees a plain number is that many degrees, exactly as a plain
    number in a millimetre slot is that many millimetres. Not when the
    source works in radians: `2 * pi / n` is a radian figure whatever the
    slot is labelled. None when the rule does not apply.
    """
    if unit.symbol not in ANGLES_NOT_RADIANS or not is_a_plain_number(value):
        return None
    if source and _RADIAN_WORDS.search(source):
        return None
    return Quantity(value.magnitude, unit)


@dataclass(frozen=True, slots=True)
class Quantity:
    """A physical quantity: an interval of magnitude in a stated unit.

    Examples
    --------
    >>> Q(6.0, "mm").to("m").magnitude.midpoint
    0.006
    >>> (Q(500, "N") * Q(35, "mm")).to("Nm").magnitude.midpoint
    17.5
    >>> Q(2.9, "mm", plus=0.2, minus=0.0).at_least(Q(3.0, "mm"))
    <Trivalent.INDETERMINATE: 'indeterminate'>
    """

    magnitude: Interval
    unit: Unit

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        if not isinstance(self.magnitude, Interval):
            raise TypeError("Quantity.magnitude must be an Interval")
        if not isinstance(self.unit, Unit):
            raise TypeError("Quantity.unit must be a Unit")

    @classmethod
    def of(
        cls,
        value: Number | Interval,
        unit: UnitLike = "",
        *,
        plus: Number | None = None,
        minus: Number | None = None,
        relative: Number | None = None,
    ) -> "Quantity":
        """Build a quantity, optionally with an engineering tolerance.

        ``plus``/``minus`` express an asymmetric tolerance in the same unit;
        ``relative`` expresses a symmetric fractional tolerance. Supplying both
        forms is an error, because the intended combination is ambiguous.
        """
        resolved = _resolve_unit(unit)
        has_absolute = plus is not None or minus is not None
        if has_absolute and relative is not None:
            raise DimensionalityError(
                "specify either an absolute (plus/minus) or a relative tolerance, "
                "not both",
                unit=resolved.symbol,
            )

        if isinstance(value, Interval):
            if has_absolute or relative is not None:
                raise DimensionalityError(
                    "a tolerance cannot be applied to a value that is already an "
                    "interval; widen the interval instead",
                    unit=resolved.symbol,
                )
            return cls(value, resolved)

        if has_absolute:
            interval = Interval.tolerance(
                value, minus if minus is not None else 0.0, plus if plus is not None else 0.0
            )
        elif relative is not None:
            interval = Interval.relative(value, relative)
        else:
            interval = Interval.exact(value)
        return cls(interval, resolved)

    @classmethod
    def exact(cls, value: Number, unit: UnitLike = "") -> "Quantity":
        return cls(Interval.exact(value), _resolve_unit(unit))

    @classmethod
    def range(cls, low: Number, high: Number, unit: UnitLike = "") -> "Quantity":
        """An explicit range, used for scenario bounds and material data spreads."""
        return cls(Interval(float(low), float(high)), _resolve_unit(unit))

    @classmethod
    def zero(cls, unit: UnitLike = "") -> "Quantity":
        return cls(Interval.exact(0.0), _resolve_unit(unit))

    @classmethod
    def parse(cls, text: str) -> "Quantity":
        """Parse ``"6 mm"``, ``"6mm"``, ``"500 N"``, ``"2.5"``, ``"[4, 6] mm"``.

        Intended for human-authored configuration and test fixtures, not for the
        wire format; serialised documents use the explicit dict form so that no
        parsing ambiguity can reach the compiler.
        """
        stripped = text.strip()
        if not stripped:
            raise UnitConversionError("cannot parse an empty quantity string")

        if stripped.startswith("["):
            close = stripped.find("]")
            if close == -1:
                raise UnitConversionError(
                    "unterminated interval in quantity string", text=text
                )
            inner = stripped[1:close]
            parts = [p.strip() for p in inner.split(",")]
            if len(parts) != 2:
                raise UnitConversionError(
                    "interval must have exactly two endpoints", text=text
                )
            unit_text = stripped[close + 1 :].strip()
            return cls(Interval(float(parts[0]), float(parts[1])), _resolve_unit(unit_text))

        index = 0
        seen_digit = False
        while index < len(stripped):
            char = stripped[index]
            if char.isdigit():
                seen_digit = True
                index += 1
            elif char in "+-." :
                index += 1
            elif char in "eE" and seen_digit and index + 1 < len(stripped) and (
                stripped[index + 1].isdigit() or stripped[index + 1] in "+-"
            ):
                index += 2
            else:
                break
        number_text = stripped[:index].strip()
        unit_text = stripped[index:].strip()
        if not number_text:
            raise UnitConversionError(
                "quantity string has no numeric magnitude", text=text
            )
        try:
            value = float(number_text)
        except ValueError as exc:
            raise UnitConversionError(
                "quantity magnitude is not a number", text=text, magnitude=number_text
            ) from exc
        return cls(Interval.exact(value), _resolve_unit(unit_text))

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    @property
    def dimension(self) -> Dimension:
        return self.unit.dimension

    @property
    def is_exact(self) -> bool:
        return self.magnitude.is_exact

    @property
    def is_dimensionless(self) -> bool:
        return self.unit.dimension.is_dimensionless

    @property
    def nominal(self) -> float:
        """The interval midpoint, for display and for seeding a solver.

        Never use this to make a decision. Decisions go through the three-valued
        comparison methods so that an uncertain answer stays uncertain.
        """
        return self.magnitude.midpoint

    @property
    def si_magnitude(self) -> Interval:
        """The magnitude converted to the coherent SI unit of its dimension."""
        unit = self.unit
        if unit.offset == 0.0:
            return self.magnitude * unit.scale
        return self.magnitude * unit.scale + unit.offset

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------
    def to(self, unit: UnitLike) -> "Quantity":
        """Convert to another unit of the same dimension."""
        target = _resolve_unit(unit)
        require_compatible(self.unit, target, operation="conversion")
        if target == self.unit:
            return self
        si = self.si_magnitude
        if target.offset == 0.0:
            converted = si / target.scale
        else:
            converted = (si - target.offset) / target.scale
        return Quantity(converted, target)

    def to_si(self) -> "Quantity":
        """Convert to the coherent SI unit, choosing a registered symbol for it."""
        candidates = units_for_dimension(self.dimension)
        for symbol in candidates:
            candidate = parse_unit(symbol)
            if candidate.scale == 1.0 and candidate.offset == 0.0:
                return self.to(candidate)
        # No named coherent unit (e.g. an unusual compound dimension): keep the
        # magnitude in SI and synthesise a symbol from the dimension vector.
        return Quantity(self.si_magnitude, Unit(str(self.dimension), self.dimension, 1.0))

    def magnitude_in(self, unit: UnitLike) -> Interval:
        """The magnitude interval expressed in ``unit``, without rewrapping."""
        return self.to(unit).magnitude

    def value_in(self, unit: UnitLike) -> float:
        """The midpoint magnitude in ``unit``.

        Provided for interoperating with numeric libraries that cannot accept an
        interval. Using it discards uncertainty, so call sites that do are
        expected to record that fact in the evidence they produce.
        """
        return self.to(unit).magnitude.midpoint

    # ------------------------------------------------------------------
    # Arithmetic
    # ------------------------------------------------------------------
    def _require_ratio_unit(self, operation: str) -> None:
        if self.unit.is_affine:
            raise OffsetUnitError(
                f"{operation} is not defined on an affine temperature scale; "
                "convert to K first, or use a temperature difference",
                unit=self.unit.symbol,
                operation=operation,
            )

    def __add__(self, other: "Quantity") -> "Quantity":
        if not isinstance(other, Quantity):
            return NotImplemented
        require_compatible(self.unit, other.unit, operation="addition")
        if self.unit.is_affine or other.unit.is_affine:
            raise OffsetUnitError(
                "addition on an affine temperature scale is ambiguous; "
                "add a difference in K to an absolute temperature instead",
                left_unit=self.unit.symbol,
                right_unit=other.unit.symbol,
            )
        return Quantity(self.magnitude + other.to(self.unit).magnitude, self.unit)

    def __sub__(self, other: "Quantity") -> "Quantity":
        if not isinstance(other, Quantity):
            return NotImplemented
        require_compatible(self.unit, other.unit, operation="subtraction")
        if self.unit.is_affine and other.unit.is_affine:
            # The difference of two absolute temperatures is a temperature
            # difference, correctly expressed in kelvin.
            kelvin = parse_unit("K")
            return Quantity(
                self.to(kelvin).magnitude - other.to(kelvin).magnitude, kelvin
            )
        if self.unit.is_affine or other.unit.is_affine:
            raise OffsetUnitError(
                "mixing an affine temperature with a ratio quantity under "
                "subtraction is ambiguous",
                left_unit=self.unit.symbol,
                right_unit=other.unit.symbol,
            )
        return Quantity(self.magnitude - other.to(self.unit).magnitude, self.unit)

    def __neg__(self) -> "Quantity":
        self._require_ratio_unit("negation")
        return Quantity(-self.magnitude, self.unit)

    def __mul__(self, other: "Quantity | Number") -> "Quantity":
        if isinstance(other, Quantity):
            self._require_ratio_unit("multiplication")
            other._require_ratio_unit("multiplication")
            return Quantity(
                self.magnitude * other.magnitude,
                _compose_unit(self.unit, other.unit, exponent=1),
            )
        if isinstance(other, (int, float, Fraction)):
            self._require_ratio_unit("multiplication")
            return Quantity(self.magnitude * float(other), self.unit)
        if isinstance(other, Interval):
            self._require_ratio_unit("multiplication")
            return Quantity(self.magnitude * other, self.unit)
        return NotImplemented

    __rmul__ = __mul__

    def __truediv__(self, other: "Quantity | Number") -> "Quantity":
        if isinstance(other, Quantity):
            self._require_ratio_unit("division")
            other._require_ratio_unit("division")
            return Quantity(
                self.magnitude / other.magnitude,
                _compose_unit(self.unit, other.unit, exponent=-1),
            )
        if isinstance(other, (int, float, Fraction)):
            self._require_ratio_unit("division")
            return Quantity(self.magnitude / float(other), self.unit)
        if isinstance(other, Interval):
            self._require_ratio_unit("division")
            return Quantity(self.magnitude / other, self.unit)
        return NotImplemented

    def __rtruediv__(self, other: Number) -> "Quantity":
        if not isinstance(other, (int, float, Fraction)):
            return NotImplemented
        self._require_ratio_unit("division")
        inverted = Unit(
            symbol=_invert_symbol(self.unit.symbol),
            dimension=self.unit.dimension.inverse(),
            scale=1.0 / self.unit.scale,
        )
        return Quantity(Interval.exact(float(other)) / self.magnitude, inverted)

    def __pow__(self, exponent: Number) -> "Quantity":
        self._require_ratio_unit("exponentiation")
        power = Fraction(exponent).limit_denominator(1_000_000) if not isinstance(
            exponent, Fraction
        ) else exponent
        return Quantity(
            self.magnitude**power,
            Unit(
                symbol=_power_symbol(self.unit.symbol, power),
                dimension=self.unit.dimension**power,
                scale=self.unit.scale ** float(power),
            ),
        )

    def sqrt(self) -> "Quantity":
        return self ** Fraction(1, 2)

    def __abs__(self) -> "Quantity":
        self._require_ratio_unit("absolute value")
        return Quantity(abs(self.magnitude), self.unit)

    # ------------------------------------------------------------------
    # Three-valued comparison
    # ------------------------------------------------------------------
    def _comparable(self, other: "Quantity | Number", operation: str) -> Interval:
        if isinstance(other, Quantity):
            require_compatible(self.unit, other.unit, operation=operation)
            return other.to(self.unit).magnitude
        if isinstance(other, (int, float, Fraction)):
            if not self.is_dimensionless:
                raise DimensionalityError(
                    f"{operation} against a bare number requires a dimensionless "
                    "quantity",
                    operation=operation,
                    unit=self.unit.symbol,
                    measures=self.dimension.describe(),
                )
            return Interval.exact(float(other))
        raise TypeError(f"cannot compare Quantity with {type(other).__name__}")

    def at_least(self, other: "Quantity | Number") -> Trivalent:
        return self.magnitude.at_least(self._comparable(other, "comparison >="))

    def at_most(self, other: "Quantity | Number") -> Trivalent:
        return self.magnitude.at_most(self._comparable(other, "comparison <="))

    def greater_than(self, other: "Quantity | Number") -> Trivalent:
        return self.magnitude.greater_than(self._comparable(other, "comparison >"))

    def less_than(self, other: "Quantity | Number") -> Trivalent:
        return self.magnitude.less_than(self._comparable(other, "comparison <"))

    def within(self, low: "Quantity", high: "Quantity") -> Trivalent:
        return self.at_least(low) & self.at_most(high)

    def approximately_equals(
        self, other: "Quantity", *, tolerance: "Quantity"
    ) -> Trivalent:
        require_compatible(self.unit, tolerance.unit, operation="tolerance comparison")
        return self.magnitude.approximately_equals(
            self._comparable(other, "comparison =="),
            tolerance=tolerance.to(self.unit).magnitude.hi,
        )

    # Rich comparison operators are deliberately NOT defined. `a < b` on a
    # Quantity would return a Trivalent, which has no boolean interpretation,
    # producing a confusing TypeError deep inside unrelated code (for instance
    # when sorting). Comparison is therefore always spelled out by name.
    def __lt__(self, other: object) -> bool:
        raise TypeError(
            "Quantity does not support '<'; use .less_than(...) which returns a "
            "three-valued Trivalent, or compare .nominal explicitly when a total "
            "order is genuinely wanted (e.g. sorting for display)"
        )

    __le__ = __gt__ = __ge__ = __lt__  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def as_dict(self) -> dict[str, Any]:
        """The canonical wire form.

        An exact quantity serialises as ``{"magnitude": x, "unit": "mm"}``; an
        uncertain one carries explicit bounds. Round-tripping is lossless.
        """
        if self.magnitude.is_exact:
            return {"magnitude": self.magnitude.lo, "unit": self.unit.symbol}
        return {
            "magnitude": self.magnitude.midpoint,
            "unit": self.unit.symbol,
            "interval": {"lo": self.magnitude.lo, "hi": self.magnitude.hi},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Quantity":
        if "unit" not in payload:
            raise UnitConversionError(
                "serialised quantity is missing the required 'unit' field",
                keys=sorted(payload.keys()),
            )
        unit = parse_unit(str(payload["unit"]))
        if "interval" in payload and payload["interval"] is not None:
            bounds = payload["interval"]
            if not isinstance(bounds, Mapping):
                raise UnitConversionError(
                    "a quantity's interval must be an object {lo, hi}",
                    got=type(bounds).__name__,
                )
            return cls(
                Interval(
                    _a_number(bounds, "lo", "interval.lo"),
                    _a_number(bounds, "hi", "interval.hi"),
                ),
                unit,
            )
        if "magnitude" not in payload:
            raise UnitConversionError(
                "serialised quantity is missing the required 'magnitude' field",
                keys=sorted(payload.keys()),
            )
        return cls(Interval.exact(_a_number(payload, "magnitude", "magnitude")), unit)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def __str__(self) -> str:
        symbol = self.unit.symbol
        rendered = str(self.magnitude)
        return f"{rendered} {symbol}" if symbol else rendered

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Quantity({self.magnitude!r}, {self.unit.symbol!r})"


def _compose_unit(left: Unit, right: Unit, *, exponent: int) -> Unit:
    """Unit of a product (``exponent=1``) or quotient (``exponent=-1``).

    The symbol is composed textually rather than normalised to a named unit, so
    that ``N * mm`` displays as ``N*mm`` and not as ``mJ``. Preserving the
    engineer's unit of account is the point; :meth:`Quantity.to` is how you move
    between accounts, and it is always an explicit act.
    """
    if left.is_dimensionless and left.scale == 1.0 and not left.symbol:
        return right if exponent == 1 else Unit(
            _invert_symbol(right.symbol), right.dimension.inverse(), 1.0 / right.scale
        )
    if right.is_dimensionless and right.scale == 1.0 and not right.symbol:
        return left

    if exponent == 1:
        symbol = f"{left.symbol}*{right.symbol}" if left.symbol and right.symbol else (
            left.symbol or right.symbol
        )
        dimension = left.dimension * right.dimension
        scale = left.scale * right.scale
    else:
        symbol = (
            f"{left.symbol}/{_parenthesise(right.symbol)}"
            if left.symbol
            else _invert_symbol(right.symbol)
        )
        dimension = left.dimension / right.dimension
        scale = left.scale / right.scale
    return Unit(symbol=symbol, dimension=dimension, scale=scale)


def _parenthesise(symbol: str) -> str:
    return f"({symbol})" if ("*" in symbol or "/" in symbol) else symbol


def _invert_symbol(symbol: str) -> str:
    if not symbol:
        return ""
    return f"1/{_parenthesise(symbol)}"


def _power_symbol(symbol: str, exponent: Fraction) -> str:
    if not symbol:
        return ""
    if exponent == 1:
        return symbol
    base = _parenthesise(symbol)
    if exponent.denominator == 1:
        return f"{base}^{exponent.numerator}"
    return f"{base}^({exponent.numerator}/{exponent.denominator})"


# ----------------------------------------------------------------------
# Convenience helpers
# ----------------------------------------------------------------------
def Q(  # noqa: N802 - a deliberately short constructor, used constantly
    value: Number | Interval,
    unit: UnitLike = "",
    *,
    plus: Number | None = None,
    minus: Number | None = None,
    relative: Number | None = None,
) -> Quantity:
    """Shorthand for :meth:`Quantity.of`."""
    return Quantity.of(value, unit, plus=plus, minus=minus, relative=relative)


def sum_quantities(values: Iterable[Quantity]) -> Quantity:
    """Sum a non-empty iterable of dimensionally compatible quantities."""
    iterator = iter(values)
    try:
        total = next(iterator)
    except StopIteration:
        raise DimensionalityError(
            "cannot sum an empty collection of quantities; the unit of the "
            "result would be undefined"
        ) from None
    for value in iterator:
        total = total + value
    return total


def min_quantity(values: Sequence[Quantity]) -> Quantity:
    """Interval-sound minimum: bounds are the elementwise min of the bounds."""
    if not values:
        raise DimensionalityError("min of an empty collection of quantities")
    unit = values[0].unit
    intervals = [v.to(unit).magnitude for v in values]
    return Quantity(
        Interval(min(i.lo for i in intervals), min(i.hi for i in intervals)), unit
    )


def max_quantity(values: Sequence[Quantity]) -> Quantity:
    """Interval-sound maximum: bounds are the elementwise max of the bounds."""
    if not values:
        raise DimensionalityError("max of an empty collection of quantities")
    unit = values[0].unit
    intervals = [v.to(unit).magnitude for v in values]
    return Quantity(
        Interval(max(i.lo for i in intervals), max(i.hi for i in intervals)), unit
    )


def is_finite(value: Quantity) -> bool:
    return math.isfinite(value.magnitude.lo) and math.isfinite(value.magnitude.hi)


__all__ = [
    "Quantity",
    "Q",
    "UnitLike",
    "sum_quantities",
    "min_quantity",
    "max_quantity",
    "is_finite",
]
