"""SI dimension vectors.

A dimension is an exponent vector over the seven SI base dimensions. Using
``Fraction`` exponents rather than ``int`` is deliberate: square roots appear
legitimately in engineering (the stress-intensity factor ``K`` has dimension
``M L^-1/2 T^-2``, radius of gyration involves ``sqrt(I/A)``), and silently
truncating a half-exponent to zero would turn a dimensional bug into a
plausible-looking number.

Dimensions are immutable, hashable, and totally ordered by their canonical
string form, which makes them usable as dictionary keys in the compiler's
content-addressed cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Iterator, Mapping

from .errors import DimensionalityError

#: Canonical order of the seven SI base dimensions.
BASE_DIMENSION_SYMBOLS: tuple[str, ...] = ("L", "M", "T", "I", "Th", "N", "J")

#: Human-readable names, used in diagnostics.
BASE_DIMENSION_NAMES: tuple[str, ...] = (
    "length",
    "mass",
    "time",
    "electric_current",
    "thermodynamic_temperature",
    "amount_of_substance",
    "luminous_intensity",
)

_NUM_BASE = len(BASE_DIMENSION_SYMBOLS)


def _as_fraction(value: object) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        # Limit the denominator so that 0.5 and 1/3 round-trip cleanly while
        # floating-point noise does not spawn absurd fractions.
        return Fraction(value).limit_denominator(1_000_000)
    if isinstance(value, str):
        return Fraction(value)
    raise DimensionalityError(
        "exponent is not convertible to a rational number", value=repr(value)
    )


@dataclass(frozen=True, slots=True)
class Dimension:
    """An immutable exponent vector over the SI base dimensions.

    Examples
    --------
    >>> LENGTH * LENGTH == AREA
    True
    >>> (FORCE / AREA) == PRESSURE
    True
    >>> Dimension.parse("L^1 M^1 T^-2") == FORCE
    True
    """

    exponents: tuple[Fraction, ...]

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        if len(self.exponents) != _NUM_BASE:
            raise DimensionalityError(
                "dimension vector has the wrong arity",
                expected=_NUM_BASE,
                got=len(self.exponents),
            )
        for exponent in self.exponents:
            if not isinstance(exponent, Fraction):
                raise DimensionalityError(
                    "dimension exponents must be Fraction instances",
                    got=type(exponent).__name__,
                )

    @classmethod
    def of(cls, **components: object) -> "Dimension":
        """Build a dimension from named base components.

        >>> Dimension.of(L=1, M=1, T=-2) == FORCE
        True
        """
        vector = [Fraction(0)] * _NUM_BASE
        index_by_symbol = {sym: i for i, sym in enumerate(BASE_DIMENSION_SYMBOLS)}
        index_by_name = {name: i for i, name in enumerate(BASE_DIMENSION_NAMES)}
        for key, raw in components.items():
            if key in index_by_symbol:
                idx = index_by_symbol[key]
            elif key in index_by_name:
                idx = index_by_name[key]
            else:
                raise DimensionalityError(
                    "unknown base dimension",
                    component=key,
                    known=list(BASE_DIMENSION_SYMBOLS),
                )
            vector[idx] = _as_fraction(raw)
        return cls(tuple(vector))

    @classmethod
    def from_iterable(cls, values: Iterable[object]) -> "Dimension":
        return cls(tuple(_as_fraction(v) for v in values))

    @classmethod
    def parse(cls, text: str) -> "Dimension":
        """Parse the canonical string form, e.g. ``"L^1 M^1 T^-2"``.

        The empty string and ``"1"`` both denote the dimensionless dimension.
        """
        stripped = text.strip()
        if stripped in ("", "1", "dimensionless"):
            return DIMENSIONLESS
        components: dict[str, object] = {}
        for token in stripped.split():
            if "^" in token:
                symbol, _, exponent = token.partition("^")
            else:
                symbol, exponent = token, "1"
            symbol = symbol.strip()
            if symbol not in BASE_DIMENSION_SYMBOLS:
                raise DimensionalityError(
                    "unknown base dimension symbol while parsing",
                    token=token,
                    text=text,
                )
            components[symbol] = exponent.strip()
        return cls.of(**components)

    # ------------------------------------------------------------------
    # Algebra
    # ------------------------------------------------------------------
    def __mul__(self, other: "Dimension") -> "Dimension":
        if not isinstance(other, Dimension):
            return NotImplemented
        return Dimension(tuple(a + b for a, b in zip(self.exponents, other.exponents)))

    def __truediv__(self, other: "Dimension") -> "Dimension":
        if not isinstance(other, Dimension):
            return NotImplemented
        return Dimension(tuple(a - b for a, b in zip(self.exponents, other.exponents)))

    def __pow__(self, exponent: object) -> "Dimension":
        power = _as_fraction(exponent)
        return Dimension(tuple(e * power for e in self.exponents))

    def root(self, degree: int) -> "Dimension":
        """Take the ``degree``-th root, e.g. ``AREA.root(2) == LENGTH``."""
        if degree == 0:
            raise DimensionalityError("cannot take the zeroth root of a dimension")
        return self ** Fraction(1, degree)

    def inverse(self) -> "Dimension":
        return Dimension(tuple(-e for e in self.exponents))

    # ------------------------------------------------------------------
    # Predicates and accessors
    # ------------------------------------------------------------------
    @property
    def is_dimensionless(self) -> bool:
        return all(e == 0 for e in self.exponents)

    def __getitem__(self, symbol: str) -> Fraction:
        try:
            return self.exponents[BASE_DIMENSION_SYMBOLS.index(symbol)]
        except ValueError as exc:  # pragma: no cover - defensive
            raise DimensionalityError("unknown base dimension", component=symbol) from exc

    def __iter__(self) -> Iterator[Fraction]:
        return iter(self.exponents)

    def as_mapping(self) -> Mapping[str, Fraction]:
        """Return only the non-zero components, keyed by base symbol."""
        return {
            symbol: exponent
            for symbol, exponent in zip(BASE_DIMENSION_SYMBOLS, self.exponents)
            if exponent != 0
        }

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def __str__(self) -> str:
        parts: list[str] = []
        for symbol, exponent in zip(BASE_DIMENSION_SYMBOLS, self.exponents):
            if exponent == 0:
                continue
            if exponent == 1:
                parts.append(symbol)
            else:
                parts.append(f"{symbol}^{exponent}")
        return " ".join(parts) if parts else "1"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Dimension({str(self)!r})"

    def describe(self) -> str:
        """Return a human-friendly name when one is known, else the vector."""
        known = _NAMED_DIMENSIONS.get(self)
        return known if known is not None else str(self)


def require_same_dimension(
    left: Dimension, right: Dimension, *, operation: str
) -> None:
    """Raise a precise :class:`DimensionalityError` when dimensions differ."""
    if left != right:
        raise DimensionalityError(
            f"{operation} requires matching dimensions",
            operation=operation,
            left=str(left),
            left_name=left.describe(),
            right=str(right),
            right_name=right.describe(),
        )


# ----------------------------------------------------------------------
# Canonical dimensions
# ----------------------------------------------------------------------
DIMENSIONLESS = Dimension(tuple(Fraction(0) for _ in range(_NUM_BASE)))

LENGTH = Dimension.of(L=1)
MASS = Dimension.of(M=1)
TIME = Dimension.of(T=1)
CURRENT = Dimension.of(I=1)
TEMPERATURE = Dimension.of(Th=1)
SUBSTANCE = Dimension.of(N=1)
LUMINOSITY = Dimension.of(J=1)

ANGLE = DIMENSIONLESS  # Plane angle is dimensionless; see ADR-0004.
AREA = LENGTH**2
VOLUME = LENGTH**3
SECOND_MOMENT_OF_AREA = LENGTH**4
SECTION_MODULUS = LENGTH**3

VELOCITY = LENGTH / TIME
ACCELERATION = VELOCITY / TIME
ANGULAR_VELOCITY = DIMENSIONLESS / TIME
ANGULAR_ACCELERATION = DIMENSIONLESS / TIME**2

FORCE = MASS * ACCELERATION
MOMENT = FORCE * LENGTH
TORQUE = MOMENT
PRESSURE = FORCE / AREA
STRESS = PRESSURE
ENERGY = FORCE * LENGTH
POWER = ENERGY / TIME
MOMENTUM = MASS * VELOCITY
DENSITY = MASS / VOLUME
MASS_MOMENT_OF_INERTIA = MASS * AREA
STIFFNESS = FORCE / LENGTH
ROTATIONAL_STIFFNESS = MOMENT / DIMENSIONLESS

SPECIFIC_HEAT = ENERGY / (MASS * TEMPERATURE)
THERMAL_CONDUCTIVITY = POWER / (LENGTH * TEMPERATURE)
HEAT_FLUX = POWER / AREA
CONVECTION_COEFFICIENT = POWER / (AREA * TEMPERATURE)
THERMAL_RESISTANCE = TEMPERATURE / POWER
THERMAL_EXPANSION = DIMENSIONLESS / TEMPERATURE

FREQUENCY = DIMENSIONLESS / TIME

_NAMED_DIMENSIONS: dict[Dimension, str] = {
    DIMENSIONLESS: "dimensionless",
    LENGTH: "length",
    MASS: "mass",
    TIME: "time",
    CURRENT: "electric current",
    TEMPERATURE: "temperature",
    SUBSTANCE: "amount of substance",
    LUMINOSITY: "luminous intensity",
    AREA: "area",
    VOLUME: "volume",
    SECOND_MOMENT_OF_AREA: "second moment of area",
    VELOCITY: "velocity",
    ACCELERATION: "acceleration",
    FORCE: "force",
    MOMENT: "moment or torque",
    PRESSURE: "pressure or stress",
    ENERGY: "energy",
    POWER: "power",
    DENSITY: "density",
    STIFFNESS: "translational stiffness",
    MASS_MOMENT_OF_INERTIA: "mass moment of inertia",
    SPECIFIC_HEAT: "specific heat capacity",
    THERMAL_CONDUCTIVITY: "thermal conductivity",
    HEAT_FLUX: "heat flux",
    CONVECTION_COEFFICIENT: "convection coefficient",
    THERMAL_RESISTANCE: "thermal resistance",
    THERMAL_EXPANSION: "coefficient of thermal expansion",
}

__all__ = [
    "BASE_DIMENSION_NAMES",
    "BASE_DIMENSION_SYMBOLS",
    "Dimension",
    "require_same_dimension",
    "DIMENSIONLESS",
    "LENGTH",
    "MASS",
    "TIME",
    "CURRENT",
    "TEMPERATURE",
    "SUBSTANCE",
    "LUMINOSITY",
    "ANGLE",
    "AREA",
    "VOLUME",
    "SECOND_MOMENT_OF_AREA",
    "SECTION_MODULUS",
    "VELOCITY",
    "ACCELERATION",
    "ANGULAR_VELOCITY",
    "ANGULAR_ACCELERATION",
    "FORCE",
    "MOMENT",
    "TORQUE",
    "PRESSURE",
    "STRESS",
    "ENERGY",
    "POWER",
    "MOMENTUM",
    "DENSITY",
    "MASS_MOMENT_OF_INERTIA",
    "STIFFNESS",
    "ROTATIONAL_STIFFNESS",
    "SPECIFIC_HEAT",
    "THERMAL_CONDUCTIVITY",
    "HEAT_FLUX",
    "CONVECTION_COEFFICIENT",
    "THERMAL_RESISTANCE",
    "THERMAL_EXPANSION",
    "FREQUENCY",
]
