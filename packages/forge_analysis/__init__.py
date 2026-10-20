"""forge_analysis - first-principles checks and honest material data.

Two things live here, and both exist to keep the expensive machinery honest.

**Analytical checks.** Closed-form formulas that each declare their units, their
validity limits, and their source. They are cheap, so Forge runs them first; and
because they are algebra rather than discretisation, they catch the failure modes
that produce convincing but wrong simulation results -- a mis-specified boundary
condition, a unit slip in a load, a mesh that never converged. A finite-element
result that cannot be reconciled with a first-principles estimate is reported as
``INCONCLUSIVE``, not as a refinement of it.

**Material records.** With sources, and with ranges instead of convenient point
values. :func:`~forge_analysis.materials.lookup` refuses family names outright:
asking for "aluminium" raises and lists the specific grades available, because
yield strength within that family varies by more than a factor of three and
silently picking a representative value turns a strength claim into fiction.

>>> from forge_units import Q
>>> from forge_analysis import bearing_stress, lookup, safety_factor
>>> material = lookup("aluminium_6061_t6")
>>> demand = bearing_stress(Q(500, "N"), Q(8.2, "mm"), Q(6, "mm")).value
>>> safety_factor(material.yield_strength, demand).value
Quantity(Interval(23.616, 27.1584), '')

The safety factor comes back as a range because the material's yield strength is
recorded as a minimum-to-typical range, which is what the source actually says.
"""

from __future__ import annotations

from .checks import (
    ALL_CHECKS,
    AnalysisError,
    CheckResult,
    actuator_torque,
    axial_stress,
    bearing_stress,
    bending_stress,
    cantilever_root_moment,
    cantilever_tip_deflection,
    circular_second_moment,
    conduction_resistance,
    convection_resistance,
    direct_shear_stress,
    euler_buckling_load,
    gear_ratio,
    lever_mechanical_advantage,
    radius_of_gyration,
    rectangular_second_moment,
    safety_factor,
    torsional_shear_stress_circular,
    von_mises_stress,
)
from .materials import Material, MaterialError, available, lookup, register, scenario

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "AnalysisError",
    "CheckResult",
    "ALL_CHECKS",
    "rectangular_second_moment",
    "circular_second_moment",
    "radius_of_gyration",
    "axial_stress",
    "direct_shear_stress",
    "bearing_stress",
    "bending_stress",
    "cantilever_tip_deflection",
    "cantilever_root_moment",
    "euler_buckling_load",
    "torsional_shear_stress_circular",
    "safety_factor",
    "von_mises_stress",
    "conduction_resistance",
    "convection_resistance",
    "lever_mechanical_advantage",
    "gear_ratio",
    "actuator_torque",
    "Material",
    "MaterialError",
    "lookup",
    "register",
    "available",
    "scenario",
]
