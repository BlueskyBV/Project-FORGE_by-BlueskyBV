"""Units: named scale factors onto the SI base, and the parser for unit strings.

A :class:`Unit` is a dimension plus a linear map onto SI: ``si_value = scale *
value + offset``. Almost every engineering unit has ``offset == 0``; the
exceptions are the affine temperature scales (°C, °F), which are handled
separately and deliberately restricted, because ``20 °C * 2`` is meaningless
while ``20 K * 2`` is not.

The parser accepts the compact forms engineers actually write::

    mm            N/mm^2         kg*m/s^2      kg/m^3
    N*m           MPa            1/s           mm^2

Grammar (whitespace-insensitive)::

    unit      := term (('*' | '/' | ' ') term)*
    term      := symbol ('^' exponent)?
    exponent  := ['-'] digits ('/' digits)?

Design note: unit *aliases* are resolved to a canonical symbol at parse time, so
``"millimetre"``, ``"millimeter"`` and ``"mm"`` all produce the identical
:class:`Unit` object. That matters because units participate in the compiler's
content-addressed cache keys, and two spellings of the same unit must not
produce two cache entries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Mapping

from . import dimension as dim
from .dimension import Dimension
from .errors import (
    DimensionalityError,
    OffsetUnitError,
    UnitSyntaxError,
    UnknownUnitError,
)


@dataclass(frozen=True, slots=True)
class Unit:
    """A unit of measure.

    Attributes
    ----------
    symbol:
        Canonical symbol used for serialisation and display.
    dimension:
        The physical dimension this unit measures.
    scale:
        Multiplicative factor converting a magnitude in this unit to the
        coherent SI unit of the same dimension.
    offset:
        Additive term applied *after* scaling, non-zero only for affine
        temperature scales.
    """

    symbol: str
    dimension: Dimension
    scale: float = 1.0
    offset: float = 0.0

    @property
    def is_affine(self) -> bool:
        return self.offset != 0.0

    @property
    def is_dimensionless(self) -> bool:
        return self.dimension.is_dimensionless

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.symbol

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Unit({self.symbol!r})"


# ----------------------------------------------------------------------
# Base and derived unit table
# ----------------------------------------------------------------------
# Each entry: symbol -> (dimension, scale-to-SI, offset, aliases)
_UNIT_TABLE: dict[str, tuple[Dimension, float, float, tuple[str, ...]]] = {
    # -- dimensionless -------------------------------------------------
    "": (dim.DIMENSIONLESS, 1.0, 0.0, ("1", "dimensionless", "-", "unitless")),
    "%": (dim.DIMENSIONLESS, 0.01, 0.0, ("percent", "pct")),
    "ppm": (dim.DIMENSIONLESS, 1e-6, 0.0, ()),
    # -- plane angle (dimensionless, see ADR-0004) ---------------------
    "rad": (dim.DIMENSIONLESS, 1.0, 0.0, ("radian", "radians")),
    "deg": (dim.DIMENSIONLESS, 0.017453292519943295, 0.0, ("degree", "degrees", "°")),
    "rev": (dim.DIMENSIONLESS, 6.283185307179586, 0.0, ("revolution", "turn")),
    "arcmin": (dim.DIMENSIONLESS, 2.908882086657216e-4, 0.0, ()),
    "arcsec": (dim.DIMENSIONLESS, 4.84813681109536e-6, 0.0, ()),
    # -- length --------------------------------------------------------
    "m": (dim.LENGTH, 1.0, 0.0, ("metre", "meter", "metres", "meters")),
    "km": (dim.LENGTH, 1e3, 0.0, ("kilometre", "kilometer")),
    "cm": (dim.LENGTH, 1e-2, 0.0, ("centimetre", "centimeter")),
    "mm": (dim.LENGTH, 1e-3, 0.0, ("millimetre", "millimeter", "millimetres")),
    "um": (dim.LENGTH, 1e-6, 0.0, ("micrometre", "micrometer", "micron", "µm")),
    "nm": (dim.LENGTH, 1e-9, 0.0, ("nanometre", "nanometer")),
    "in": (dim.LENGTH, 0.0254, 0.0, ("inch", "inches", '"')),
    "ft": (dim.LENGTH, 0.3048, 0.0, ("foot", "feet")),
    "yd": (dim.LENGTH, 0.9144, 0.0, ("yard",)),
    "mil": (dim.LENGTH, 2.54e-5, 0.0, ("thou",)),
    # -- mass ----------------------------------------------------------
    "kg": (dim.MASS, 1.0, 0.0, ("kilogram", "kilogrammes", "kilograms")),
    "g": (dim.MASS, 1e-3, 0.0, ("gram", "grams", "gramme")),
    "mg": (dim.MASS, 1e-6, 0.0, ("milligram",)),
    "t": (dim.MASS, 1e3, 0.0, ("tonne", "metric_ton")),
    "lb": (dim.MASS, 0.45359237, 0.0, ("lbm", "pound", "pounds")),
    "oz": (dim.MASS, 0.028349523125, 0.0, ("ounce",)),
    "slug": (dim.MASS, 14.593902937206364, 0.0, ()),
    # -- time ----------------------------------------------------------
    "s": (dim.TIME, 1.0, 0.0, ("sec", "second", "seconds")),
    "ms": (dim.TIME, 1e-3, 0.0, ("millisecond",)),
    "us": (dim.TIME, 1e-6, 0.0, ("microsecond", "µs")),
    "min": (dim.TIME, 60.0, 0.0, ("minute", "minutes")),
    "h": (dim.TIME, 3600.0, 0.0, ("hr", "hour", "hours")),
    "day": (dim.TIME, 86400.0, 0.0, ("days",)),
    # -- current, substance, luminosity --------------------------------
    "A": (dim.CURRENT, 1.0, 0.0, ("amp", "ampere", "amperes")),
    "mA": (dim.CURRENT, 1e-3, 0.0, ("milliamp",)),
    "mol": (dim.SUBSTANCE, 1.0, 0.0, ("mole",)),
    "cd": (dim.LUMINOSITY, 1.0, 0.0, ("candela",)),
    # -- temperature ---------------------------------------------------
    "K": (dim.TEMPERATURE, 1.0, 0.0, ("kelvin",)),
    "degC": (dim.TEMPERATURE, 1.0, 273.15, ("celsius", "C", "°C")),
    "degF": (
        dim.TEMPERATURE,
        0.5555555555555556,
        255.3722222222222,
        ("fahrenheit", "F", "°F"),
    ),
    "degR": (dim.TEMPERATURE, 0.5555555555555556, 0.0, ("rankine",)),
    "delta_degC": (dim.TEMPERATURE, 1.0, 0.0, ("deltaC", "K_diff")),
    # -- force ---------------------------------------------------------
    "N": (dim.FORCE, 1.0, 0.0, ("newton", "newtons")),
    "kN": (dim.FORCE, 1e3, 0.0, ("kilonewton",)),
    "MN": (dim.FORCE, 1e6, 0.0, ()),
    "mN": (dim.FORCE, 1e-3, 0.0, ()),
    "lbf": (dim.FORCE, 4.4482216152605, 0.0, ("pound_force",)),
    "kgf": (dim.FORCE, 9.80665, 0.0, ("kilogram_force",)),
    # -- pressure / stress ---------------------------------------------
    "Pa": (dim.PRESSURE, 1.0, 0.0, ("pascal",)),
    "kPa": (dim.PRESSURE, 1e3, 0.0, ("kilopascal",)),
    "MPa": (dim.PRESSURE, 1e6, 0.0, ("megapascal",)),
    "GPa": (dim.PRESSURE, 1e9, 0.0, ("gigapascal",)),
    "bar": (dim.PRESSURE, 1e5, 0.0, ()),
    "mbar": (dim.PRESSURE, 1e2, 0.0, ()),
    "atm": (dim.PRESSURE, 101325.0, 0.0, ()),
    "psi": (dim.PRESSURE, 6894.757293168361, 0.0, ("lbf_per_in2",)),
    "ksi": (dim.PRESSURE, 6894757.293168361, 0.0, ()),
    # -- energy / power ------------------------------------------------
    "J": (dim.ENERGY, 1.0, 0.0, ("joule", "joules")),
    "kJ": (dim.ENERGY, 1e3, 0.0, ()),
    "Wh": (dim.ENERGY, 3600.0, 0.0, ()),
    "W": (dim.POWER, 1.0, 0.0, ("watt", "watts")),
    "kW": (dim.POWER, 1e3, 0.0, ()),
    "mW": (dim.POWER, 1e-3, 0.0, ()),
    "hp": (dim.POWER, 745.6998715822702, 0.0, ("horsepower",)),
    # -- moment --------------------------------------------------------
    "Nm": (dim.MOMENT, 1.0, 0.0, ("newton_metre", "newton_meter")),
    "Nmm": (dim.MOMENT, 1e-3, 0.0, ()),
    "kNm": (dim.MOMENT, 1e3, 0.0, ()),
    # -- frequency -----------------------------------------------------
    "Hz": (dim.FREQUENCY, 1.0, 0.0, ("hertz",)),
    "kHz": (dim.FREQUENCY, 1e3, 0.0, ()),
    # rpm is rev/min. Because a revolution is 2*pi radians and radians are
    # dimensionless, 1 rpm = 2*pi/60 s^-1. This keeps parse_unit("rpm") and
    # parse_unit("rev/min") numerically identical; defining rpm as 1/60 would
    # make the two spellings disagree by a factor of 2*pi, which is precisely
    # the kind of silent factor this module exists to prevent.
    "rpm": (dim.FREQUENCY, 0.10471975511965977, 0.0, ("RPM",)),
    # -- volume --------------------------------------------------------
    "L": (dim.VOLUME, 1e-3, 0.0, ("litre", "liter", "l")),
    "mL": (dim.VOLUME, 1e-6, 0.0, ("millilitre", "milliliter")),
}

# Symbols that must never be prefix-decomposed or aliased loosely, because a
# naive match would collide with a different unit ("min" is minutes, not
# milli-inches; "mol" is not milli-ol).
_PROTECTED_SYMBOLS = frozenset({"min", "mol", "mil", "m", "in", "rad", "rev"})

_ALIAS_TO_SYMBOL: dict[str, str] = {}
for _symbol, (_d, _s, _o, _aliases) in _UNIT_TABLE.items():
    _ALIAS_TO_SYMBOL[_symbol] = _symbol
    for _alias in _aliases:
        if _alias in _ALIAS_TO_SYMBOL and _ALIAS_TO_SYMBOL[_alias] != _symbol:
            raise RuntimeError(
                f"ambiguous unit alias {_alias!r}: "
                f"{_ALIAS_TO_SYMBOL[_alias]!r} vs {_symbol!r}"
            )
        _ALIAS_TO_SYMBOL[_alias] = _symbol

_UNIT_CACHE: dict[str, Unit] = {}
#: Interned instances keyed by canonical symbol. Every spelling of a registry
#: unit resolves to the *same object*, not merely an equal one, so that identity
#: comparison is meaningful and the compiler's content-addressed cache cannot be
#: split across two spellings of one unit.
_INTERNED: dict[str, Unit] = {}


def _base_unit(symbol: str) -> Unit:
    canonical = _ALIAS_TO_SYMBOL.get(symbol)
    if canonical is None:
        raise UnknownUnitError(
            "unit symbol is not in the registry",
            symbol=symbol,
            hint="add it to _UNIT_TABLE in forge_units.unit, "
            "or express it as a compound of known units",
        )
    interned = _INTERNED.get(canonical)
    if interned is not None:
        return interned
    d, scale, offset, _ = _UNIT_TABLE[canonical]
    unit = Unit(symbol=canonical, dimension=d, scale=scale, offset=offset)
    _INTERNED[canonical] = unit
    return unit


_SYMBOL_RE = re.compile(r'^([A-Za-z_\u00b0\u00b5%"\'][A-Za-z_0-9\u00b0\u00b5%"\']*|1)$')


class _UnitParser:
    """Recursive-descent parser for compound unit strings.

    Grammar::

        expr   := term (('*' | '/' | whitespace) term)*
        term   := factor ('^' exponent)?
        factor := symbol | '(' expr ')'

    Parentheses matter more here than they might seem. ``W/(m*K)`` and ``W/m*K``
    denote different things -- the first is thermal conductivity, the second is
    ``W*K/m`` -- and thermal conductivity is written the first way in every
    reference an engineer will copy a value from. A parser that quietly accepted
    the string and computed the second meaning would hand back a plausible
    number carrying the wrong dimension, which is exactly the failure this
    package exists to prevent.
    """

    __slots__ = ("text", "position", "saw_affine", "depth")

    def __init__(self, text: str) -> None:
        self.text = text
        self.position = 0
        self.depth = 0
        self.saw_affine: str | None = None

    # -- lexing helpers -------------------------------------------------
    def _skip_space(self) -> None:
        while self.position < len(self.text) and self.text[self.position].isspace():
            self.position += 1

    def _peek(self) -> str:
        return self.text[self.position] if self.position < len(self.text) else ""

    def _at_end(self) -> bool:
        self._skip_space()
        return self.position >= len(self.text)

    # -- grammar --------------------------------------------------------
    def parse(self) -> tuple[Dimension, float]:
        dimension, scale = self._expr()
        if not self._at_end():
            raise UnitSyntaxError(
                "unexpected character in unit string",
                text=self.text,
                position=self.position,
                found=self._peek(),
            )
        return dimension, scale

    def _expr(self) -> tuple[Dimension, float]:
        dimension, scale = self._term()
        while True:
            self._skip_space()
            char = self._peek()
            if char in ("*", "/"):
                self.position += 1
                operator = char
            elif char and char != ")":
                # Adjacent terms separated only by whitespace multiply, so
                # "N m" and "N*m" are the same unit.
                operator = "*"
            else:
                break
            right_dimension, right_scale = self._term()
            if operator == "*":
                dimension = dimension * right_dimension
                scale *= right_scale
            else:
                dimension = dimension / right_dimension
                scale /= right_scale
        return dimension, scale

    #: No unit anyone writes has an exponent past this, and `km^99999`
    #: overflowed the scale into an OverflowError no decoder catches.
    _LARGEST_EXPONENT = 64
    #: Nor parentheses nested past this: two thousand of them reached the
    #: interpreter's recursion limit as a RecursionError.
    _DEEPEST_NESTING = 16

    def _term(self) -> tuple[Dimension, float]:
        dimension, scale = self._factor()
        self._skip_space()
        if self._peek() == "^":
            self.position += 1
            exponent = self._exponent()
            if abs(float(exponent)) > self._LARGEST_EXPONENT:
                raise UnitSyntaxError(
                    "unit exponent is beyond anything a unit can carry",
                    text=self.text,
                    position=self.position,
                    exponent=str(exponent),
                )
            dimension = dimension**exponent
            try:
                scale = scale ** float(exponent)
            except OverflowError as exc:
                raise UnitSyntaxError(
                    "unit scale overflows at this exponent",
                    text=self.text,
                    position=self.position,
                    exponent=str(exponent),
                ) from exc
        return dimension, scale

    def _factor(self) -> tuple[Dimension, float]:
        self._skip_space()
        if self._peek() == "(":
            self.depth += 1
            if self.depth > self._DEEPEST_NESTING:
                raise UnitSyntaxError(
                    "unit string is nested too deeply",
                    text=self.text,
                    position=self.position,
                )
            self.position += 1
            dimension, scale = self._expr()
            self.depth -= 1
            self._skip_space()
            if self._peek() != ")":
                raise UnitSyntaxError(
                    "unbalanced parenthesis in unit string",
                    text=self.text,
                    position=self.position,
                )
            self.position += 1
            return dimension, scale
        return self._symbol()

    def _symbol(self) -> tuple[Dimension, float]:
        self._skip_space()
        start = self.position
        while self.position < len(self.text):
            char = self.text[self.position]
            if char.isspace() or char in "*/^()":
                break
            self.position += 1
        raw = self.text[start : self.position]
        if not raw:
            raise UnitSyntaxError(
                "expected a unit symbol",
                text=self.text,
                position=start,
                found=self._peek() or "<end of string>",
            )
        if not _SYMBOL_RE.match(raw):
            raise UnitSyntaxError(
                "unit symbol is not well formed",
                text=self.text,
                symbol=raw,
                position=start,
            )
        base = _base_unit("" if raw == "1" else raw)
        if base.is_affine:
            self.saw_affine = base.symbol
        return base.dimension, base.scale

    def _exponent(self) -> Fraction:
        self._skip_space()
        sign = 1
        if self._peek() in ("+", "-"):
            if self._peek() == "-":
                sign = -1
            self.position += 1
        self._skip_space()
        if self._peek() == "(":
            self.position += 1
            inner_start = self.position
            while self.position < len(self.text) and self._peek() != ")":
                self.position += 1
            if self._peek() != ")":
                raise UnitSyntaxError(
                    "unbalanced parenthesis in unit exponent",
                    text=self.text,
                    position=self.position,
                )
            body = self.text[inner_start : self.position]
            self.position += 1
        else:
            start = self.position
            while self.position < len(self.text) and (
                self.text[self.position].isdigit() or self.text[self.position] == "/"
            ):
                self.position += 1
            body = self.text[start : self.position]
        if not body:
            raise UnitSyntaxError(
                "unit exponent is missing", text=self.text, position=self.position
            )
        try:
            return sign * Fraction(body)
        except (ValueError, ZeroDivisionError) as exc:
            raise UnitSyntaxError(
                "unit exponent is not a rational number",
                text=self.text,
                exponent=body,
            ) from exc


#: Unicode superscripts, as everyone writes exponents outside a code editor.
_SUPERSCRIPTS = {
    "¹": "^1", "²": "^2", "³": "^3", "⁴": "^4",
    "⁵": "^5", "⁶": "^6", "⁷": "^7", "⁸": "^8",
    "⁹": "^9", "⁰": "^0", "⁻": "^-",
}


def _normalise_superscripts(text: str) -> str:
    """``mm²`` is ``mm^2``. Refusing it teaches nothing and costs a round.

    Observed live: a requirements set carrying `mm²` and `mm³` thresholds,
    refused three times with "`mm²` is not a unit". It is a unit -- it is the
    way a person writes one -- and the only thing Forge gained by refusing was
    twenty minutes and an identical answer.

    Done as a text substitution before parsing rather than as registry aliases,
    so it works for every unit and every exponent, including ones nobody has
    written down yet.
    """
    if not any(character in text for character in _SUPERSCRIPTS):
        return text
    out: list[str] = []
    for character in text:
        replacement = _SUPERSCRIPTS.get(character)
        if replacement is None:
            out.append(character)
            continue
        # Consecutive superscripts are one exponent: mm² stays mm^2, and a
        # hypothetical m¹² becomes m^12 rather than m^1^2 -- and a
        # superscript minus continues into its digits, so s⁻¹ is s^-1
        # rather than s^-^1, which read as a missing exponent.
        if out and (out[-1][-1].isdigit() or out[-1] == "^-") \
                and len(replacement) == 2:
            out.append(replacement[1])
        else:
            out.append(replacement)
    return "".join(out)


def parse_unit(text: str) -> Unit:
    """Parse a unit string into a :class:`Unit`.

    Examples
    --------
    >>> parse_unit("mm").dimension == dim.LENGTH
    True
    >>> parse_unit("N/mm^2").dimension == dim.PRESSURE
    True
    >>> round(parse_unit("N/mm^2").scale)
    1000000
    >>> parse_unit("kg*m/s^2").dimension == dim.FORCE
    True
    """
    if not isinstance(text, str):
        raise UnitSyntaxError("unit must be a string", got=type(text).__name__)
    # Greek small mu (U+03BC) is the micro sign (U+00B5) as a keyboard writes
    # it; the registry spells micro with the latter.
    key = _normalise_superscripts(text.strip().replace("μ", "µ"))
    cached = _UNIT_CACHE.get(key)
    if cached is not None:
        return cached

    # A bare registry symbol is by far the common case; take the fast path so
    # that "mm" does not go through the full parser on every parameter lookup.
    if key in _ALIAS_TO_SYMBOL:
        unit = _base_unit(key)
        _UNIT_CACHE[key] = unit
        return unit

    parser = _UnitParser(key)
    dimension, scale = parser.parse()

    if parser.saw_affine is not None:
        # An affine scale is only meaningful standing alone. "degC" is an
        # absolute temperature; "J/degC" is not a unit at all, because the
        # offset has no consistent meaning inside a ratio. A bare affine symbol
        # never reaches here: it is served by the registry fast path above.
        raise OffsetUnitError(
            "an affine temperature unit cannot appear inside a compound unit; "
            "use K for temperature differences and rates",
            unit=parser.saw_affine,
            text=text,
            hint="write W/(m*K) not W/(m*degC); use delta_degC for a "
            "temperature difference in Celsius degrees",
        )

    unit = Unit(
        symbol=_canonical_symbol(key),
        dimension=dimension,
        scale=scale,
        offset=0.0,
    )
    _UNIT_CACHE[key] = unit
    return unit


def _canonical_symbol(text: str) -> str:
    """Normalise a compound unit symbol for stable serialisation.

    Whitespace between terms means multiplication and becomes ``*``; spacing
    around explicit operators and parentheses is removed. Two spellings of the
    same unit must normalise identically, because the symbol participates in the
    compiler's content-addressed cache keys and two spellings would otherwise
    split one cache entry into two.
    """
    collapsed = re.sub(r"\s*([*/^()])\s*", r"\1", text.strip())
    return re.sub(r"\s+", "*", collapsed)


def register_unit(
    symbol: str,
    *,
    dimension: Dimension,
    scale: float,
    offset: float = 0.0,
    aliases: tuple[str, ...] = (),
) -> Unit:
    """Add a unit to the registry at runtime.

    Used by domain packs that legitimately need a unit the core does not ship
    (for example a discipline-specific hardness scale). Registering a symbol that
    already exists is an error, because silently shadowing a unit would change
    the meaning of previously valid documents.
    """
    if symbol in _UNIT_TABLE:
        raise UnknownUnitError("unit symbol is already registered", symbol=symbol)
    for alias in (symbol, *aliases):
        if alias in _ALIAS_TO_SYMBOL:
            raise UnknownUnitError(
                "unit alias collides with an existing unit",
                alias=alias,
                existing=_ALIAS_TO_SYMBOL[alias],
            )
    _UNIT_TABLE[symbol] = (dimension, scale, offset, aliases)
    _ALIAS_TO_SYMBOL[symbol] = symbol
    for alias in aliases:
        _ALIAS_TO_SYMBOL[alias] = symbol
    _UNIT_CACHE.clear()
    _INTERNED.pop(symbol, None)
    return _base_unit(symbol)


def known_units() -> Mapping[str, Dimension]:
    """Return every registered canonical symbol and the dimension it measures."""
    return {symbol: entry[0] for symbol, entry in sorted(_UNIT_TABLE.items())}


def units_for_dimension(target: Dimension) -> tuple[str, ...]:
    """Every registered unit symbol measuring ``target``, useful in diagnostics."""
    return tuple(
        symbol for symbol, entry in sorted(_UNIT_TABLE.items()) if entry[0] == target
    )


def require_compatible(left: Unit, right: Unit, *, operation: str) -> None:
    if left.dimension != right.dimension:
        raise DimensionalityError(
            f"{operation} requires compatible units",
            operation=operation,
            left_unit=left.symbol,
            left_dimension=str(left.dimension),
            left_measures=left.dimension.describe(),
            right_unit=right.symbol,
            right_dimension=str(right.dimension),
            right_measures=right.dimension.describe(),
        )


# Frequently used units, pre-resolved.
DIMENSIONLESS_UNIT = _base_unit("")
MILLIMETRE = _base_unit("mm")
METRE = _base_unit("m")
KILOGRAM = _base_unit("kg")
GRAM = _base_unit("g")
SECOND = _base_unit("s")
NEWTON = _base_unit("N")
MEGAPASCAL = _base_unit("MPa")
DEGREE = _base_unit("deg")
RADIAN = _base_unit("rad")
KELVIN = _base_unit("K")

__all__ = [
    "Unit",
    "parse_unit",
    "register_unit",
    "known_units",
    "units_for_dimension",
    "require_compatible",
    "DIMENSIONLESS_UNIT",
    "MILLIMETRE",
    "METRE",
    "KILOGRAM",
    "GRAM",
    "SECOND",
    "NEWTON",
    "MEGAPASCAL",
    "DEGREE",
    "RADIAN",
    "KELVIN",
]
