"""forge_units - dimensional algebra with uncertainty in the type system.

This package is the foundation of Forge's deterministic zone. It has **no
third-party dependencies**, by design: everything downstream that makes a
numeric claim about a design ultimately bottoms out here, so the trust surface
is kept as small as the standard library.

The central idea is that engineering values are not floats. A float can be
added to another float of a different unit, silently. A float has no notion of
how well it is known. A float compared against a threshold always answers yes or
no, even when the honest answer is "the evidence does not say". Those three
failure modes cause real engineering errors, so the type system rules them out:

- :class:`~forge_units.dimension.Dimension` makes unit mismatch a raised error.
- :class:`~forge_units.interval.Interval` makes every value carry its spread.
- :class:`~forge_units.trivalent.Trivalent` makes "unknown" a possible answer.

Quick start
-----------
>>> from forge_units import Q
>>> load = Q(500, "N")
>>> arm = Q(35, "mm")
>>> (load * arm).to("Nm")
Quantity(Interval(17.5, 17.5), 'Nm')

>>> thickness = Q(3.0, "mm", plus=0.1, minus=0.1)
>>> thickness.at_least(Q(3.0, "mm"))
<Trivalent.INDETERMINATE: 'indeterminate'>

The last result is the whole point. A nominally 3 mm wall with a +/-0.1 mm
tolerance does not reliably satisfy a 3 mm minimum, and the type system says so
without anyone having to remember to check.
"""

from __future__ import annotations

from .dimension import (
    ACCELERATION,
    ANGLE,
    AREA,
    CONVECTION_COEFFICIENT,
    CURRENT,
    DENSITY,
    DIMENSIONLESS,
    ENERGY,
    FORCE,
    FREQUENCY,
    HEAT_FLUX,
    LENGTH,
    LUMINOSITY,
    MASS,
    MASS_MOMENT_OF_INERTIA,
    MOMENT,
    POWER,
    PRESSURE,
    SECOND_MOMENT_OF_AREA,
    STIFFNESS,
    STRESS,
    SUBSTANCE,
    TEMPERATURE,
    THERMAL_CONDUCTIVITY,
    THERMAL_EXPANSION,
    THERMAL_RESISTANCE,
    TIME,
    TORQUE,
    VELOCITY,
    VOLUME,
    Dimension,
    require_same_dimension,
)
from .errors import (
    detail_besides,
    DimensionalityError,
    ForgeUnitsError,
    IntervalError,
    OffsetUnitError,
    UnitConversionError,
    UnitSyntaxError,
    UnknownUnitError,
)
from .interval import Interval, interval_hull
from .mathfns import CONSTANT_TABLE, FUNCTION_TABLE, MathDomainError
from .quantity import (
    ANGLES_NOT_RADIANS,
    Q,
    Quantity,
    UnitLike,
    a_plain_number_in,
    is_a_plain_number,
    is_finite,
    max_quantity,
    min_quantity,
    sum_quantities,
)
from .trivalent import FALSE, INDETERMINATE, TRUE, Trivalent, all_true, any_true
from .unit import (
    DEGREE,
    DIMENSIONLESS_UNIT,
    GRAM,
    KELVIN,
    KILOGRAM,
    MEGAPASCAL,
    METRE,
    MILLIMETRE,
    NEWTON,
    RADIAN,
    SECOND,
    Unit,
    known_units,
    parse_unit,
    register_unit,
    units_for_dimension,
)

__version__ = "0.1.0"

__all__ = [
    "detail_besides",
    "__version__",
    # dimensions
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
    "VELOCITY",
    "ACCELERATION",
    "FORCE",
    "MOMENT",
    "TORQUE",
    "PRESSURE",
    "STRESS",
    "ENERGY",
    "POWER",
    "DENSITY",
    "STIFFNESS",
    "MASS_MOMENT_OF_INERTIA",
    "FREQUENCY",
    "THERMAL_CONDUCTIVITY",
    "THERMAL_EXPANSION",
    "THERMAL_RESISTANCE",
    "HEAT_FLUX",
    "CONVECTION_COEFFICIENT",
    # units
    "Unit",
    "parse_unit",
    "ANGLES_NOT_RADIANS",
    "a_plain_number_in",
    "is_a_plain_number",
    "register_unit",
    "known_units",
    "units_for_dimension",
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
    # values
    "Interval",
    "interval_hull",
    "Quantity",
    "Q",
    "UnitLike",
    "sum_quantities",
    "min_quantity",
    "max_quantity",
    "is_finite",
    # logic
    "Trivalent",
    "all_true",
    "any_true",
    "TRUE",
    "FALSE",
    "INDETERMINATE",
    # maths
    "FUNCTION_TABLE",
    "CONSTANT_TABLE",
    "MathDomainError",
    # errors
    "ForgeUnitsError",
    "UnitSyntaxError",
    "UnknownUnitError",
    "DimensionalityError",
    "OffsetUnitError",
    "IntervalError",
    "UnitConversionError",
]
