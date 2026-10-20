"""First-principles analytical checks.

Every function here is a closed-form engineering formula, and every one of them
declares four things that formulas in codebases usually do not:

- **Units**, through :class:`~forge_units.Quantity`, so a moment in N·mm cannot
  be handed to a function expecting N·m.
- **Validity limits**, as an explicit list attached to the result. Euler
  buckling below a slenderness of about 80 does not govern; the function says so
  rather than returning a number that is technically computed and practically
  wrong.
- **A source**, so a reviewer can check the formula rather than trust it.
- **Uncertainty**, for free, because interval-valued inputs give interval-valued
  outputs.

Why these matter more than the finite-element results
-----------------------------------------------------
A closed-form estimate and a finite-element result disagreeing by a factor of
three means one of them is wrong, and it is usually not the algebra. The cheap
check is the thing that catches a mis-specified boundary condition, a unit slip
in a load, or a mesh that never converged -- failures that produce beautifully
rendered stress plots and completely wrong numbers.

So Forge runs the analytical check first and cross-checks the simulation against
it. A simulation result that cannot be reconciled with a first-principles
estimate is reported as ``INCONCLUSIVE``, not as a refinement of it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from forge_units import (
    Interval,
    Q,
    Quantity,
    Trivalent,
    parse_unit,
)


class AnalysisError(Exception):
    """A check was called outside its declared applicability."""

    code = "AN1000_ANALYSIS"

    def __init__(self, message: str, **detail: object) -> None:
        super().__init__(message)
        self.message = message
        self.detail = dict(detail)

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}

    def __str__(self) -> str:
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.detail.items()))
        return f"[{self.code}] {self.message} ({rendered})" if rendered else (
            f"[{self.code}] {self.message}"
        )


@dataclass(frozen=True, slots=True)
class CheckResult:
    """The outcome of one analytical check, with its provenance and limits."""

    name: str
    value: Quantity
    formula: str
    source: str
    limitations: tuple[str, ...] = ()
    intermediate: Mapping[str, Quantity] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value.as_dict(),
            "value_rendered": str(self.value),
            "formula": self.formula,
            "source": self.source,
            "limitations": list(self.limitations),
            "intermediate": {
                key: value.as_dict() for key, value in sorted(self.intermediate.items())
            },
        }


# ----------------------------------------------------------------------
# Section properties
# ----------------------------------------------------------------------
def rectangular_second_moment(width: Quantity, height: Quantity) -> CheckResult:
    """Second moment of area of a rectangle about its centroidal axis.

    ``I = b h^3 / 12``, bending about the axis perpendicular to ``height``.
    """
    value = (width * height**3 / 12.0).to("mm^4")
    return CheckResult(
        name="rectangular_second_moment",
        value=value,
        formula="I = b*h^3/12",
        source="Standard result; e.g. Young & Budynas, Roark's Formulas for "
        "Stress and Strain, 7th ed., Table A.1",
        limitations=(
            "bending about the centroidal axis perpendicular to h",
            "assumes a solid, prismatic, homogeneous section",
        ),
        intermediate={"b": width, "h": height},
    )


def circular_second_moment(diameter: Quantity) -> CheckResult:
    value = (math.pi * diameter**4 / 64.0).to("mm^4")
    return CheckResult(
        name="circular_second_moment",
        value=value,
        formula="I = pi*d^4/64",
        source="Standard result; Roark's Formulas for Stress and Strain, "
        "Table A.1",
        limitations=("solid circular section",),
        intermediate={"d": diameter},
    )


def radius_of_gyration(
    second_moment: Quantity, area: Quantity
) -> CheckResult:
    value = (second_moment / area).sqrt().to("mm")
    return CheckResult(
        name="radius_of_gyration",
        value=value,
        formula="r = sqrt(I/A)",
        source="Definition",
        limitations=(),
        intermediate={"I": second_moment, "A": area},
    )


# ----------------------------------------------------------------------
# Direct stress
# ----------------------------------------------------------------------
def axial_stress(force: Quantity, area: Quantity) -> CheckResult:
    value = (force / area).to("MPa")
    return CheckResult(
        name="axial_stress",
        value=value,
        formula="sigma = F/A",
        source="Definition of engineering normal stress",
        limitations=(
            "uniform stress distribution; not valid near load introduction "
            "points or geometric discontinuities",
            "no stress concentration factor applied",
        ),
        intermediate={"F": force, "A": area},
    )


def direct_shear_stress(
    force: Quantity, area: Quantity, *, double_shear: bool = False
) -> CheckResult:
    """Average shear stress. ``double_shear`` halves it, as for a clevis pin."""
    effective = area * 2.0 if double_shear else area
    value = (force / effective).to("MPa")
    return CheckResult(
        name="direct_shear_stress",
        value=value,
        formula="tau = F/(n*A), n = 2 in double shear",
        source="Standard average-shear approximation; Shigley's Mechanical "
        "Engineering Design, ch. 3",
        limitations=(
            "average shear only; the true distribution is parabolic and peaks "
            "about 33% higher in a circular section",
            "assumes the load divides equally between shear planes",
        ),
        intermediate={"F": force, "A": effective},
    )


def bearing_stress(
    force: Quantity, diameter: Quantity, thickness: Quantity
) -> CheckResult:
    """Projected-area bearing stress, as between a pin and a lug."""
    area = (diameter * thickness).to("mm^2")
    value = (force / area).to("MPa")
    return CheckResult(
        name="bearing_stress",
        value=value,
        formula="sigma_b = F/(d*t)",
        source="Projected-area convention; Shigley's Mechanical Engineering "
        "Design, ch. 3",
        limitations=(
            "projected area convention; the real contact pressure peaks higher "
            "and depends on the fit clearance",
            "assumes the pin is stiff relative to the lug",
        ),
        intermediate={"F": force, "d": diameter, "t": thickness, "A_proj": area},
    )


# ----------------------------------------------------------------------
# Bending
# ----------------------------------------------------------------------
def bending_stress(
    moment: Quantity, distance_to_fibre: Quantity, second_moment: Quantity
) -> CheckResult:
    value = (moment * distance_to_fibre / second_moment).to("MPa")
    return CheckResult(
        name="bending_stress",
        value=value,
        formula="sigma = M*c/I",
        source="Euler-Bernoulli beam theory",
        limitations=(
            "linear elastic, small deflection, plane sections remain plane",
            "no stress concentration; a fillet or hole at the critical section "
            "raises the true peak substantially",
            "valid away from load introduction and supports",
        ),
        intermediate={"M": moment, "c": distance_to_fibre, "I": second_moment},
    )


def cantilever_tip_deflection(
    force: Quantity, length: Quantity, modulus: Quantity, second_moment: Quantity
) -> CheckResult:
    value = (force * length**3 / (3.0 * modulus * second_moment)).to("mm")
    return CheckResult(
        name="cantilever_tip_deflection",
        value=value,
        formula="delta = F*L^3/(3*E*I)",
        source="Euler-Bernoulli beam theory; Roark's Formulas, Table 8.1 case 1a",
        limitations=(
            "linear elastic, small deflection",
            "neglects shear deformation; adds roughly (h/L)^2 error, "
            "significant for stubby beams with L/h below about 10",
            "assumes a perfectly rigid built-in support",
        ),
        intermediate={"F": force, "L": length, "E": modulus, "I": second_moment},
    )


def cantilever_root_moment(force: Quantity, arm: Quantity) -> CheckResult:
    value = (force * arm).to("Nmm")
    return CheckResult(
        name="cantilever_root_moment",
        value=value,
        formula="M = F*L",
        source="Statics",
        limitations=("point load, rigid geometry, no load redistribution",),
        intermediate={"F": force, "L": arm},
    )


# ----------------------------------------------------------------------
# Buckling
# ----------------------------------------------------------------------
def euler_buckling_load(
    modulus: Quantity,
    second_moment: Quantity,
    length: Quantity,
    *,
    effective_length_factor: float = 1.0,
    area: Quantity | None = None,
    yield_strength: Quantity | None = None,
) -> CheckResult:
    """Euler critical load, with an explicit slenderness applicability check.

    Euler's formula assumes elastic buckling. Below a transition slenderness the
    column yields before it buckles, and the formula returns a load the column
    cannot reach. When ``area`` and ``yield_strength`` are supplied the check
    computes the slenderness ratio and says so in its limitations rather than
    leaving the caller to remember.
    """
    effective_length = length * effective_length_factor
    value = (
        math.pi**2 * modulus * second_moment / effective_length**2
    ).to("N")

    limitations = [
        "elastic (Euler) buckling only; inelastic buckling governs short columns",
        f"assumes an effective-length factor K = {effective_length_factor}, "
        "which depends on the real end restraint and is easy to get wrong",
        "assumes a perfectly straight, concentrically loaded, homogeneous column",
    ]
    intermediate: dict[str, Quantity] = {
        "E": modulus,
        "I": second_moment,
        "L_eff": effective_length,
    }

    if area is not None:
        gyration = (second_moment / area).sqrt()
        slenderness = (effective_length / gyration).to("")
        intermediate["r"] = gyration.to("mm")
        intermediate["slenderness"] = slenderness
        if yield_strength is not None:
            transition = (
                (2.0 * math.pi**2 * modulus / yield_strength).to("").sqrt()
            )
            intermediate["transition_slenderness"] = transition
            if slenderness.less_than(transition) is not Trivalent.FALSE:
                limitations.append(
                    f"slenderness {slenderness.nominal:.0f} is at or below the "
                    f"transition value {transition.nominal:.0f}: this column "
                    "yields before it buckles elastically, so the Euler load is "
                    "an overestimate and must not be used as the capacity"
                )

    return CheckResult(
        name="euler_buckling_load",
        value=value,
        formula="P_cr = pi^2*E*I/(K*L)^2",
        source="Euler column theory; Shigley's Mechanical Engineering Design, "
        "ch. 4",
        limitations=tuple(limitations),
        intermediate=intermediate,
    )


# ----------------------------------------------------------------------
# Torsion
# ----------------------------------------------------------------------
def torsional_shear_stress_circular(
    torque: Quantity, diameter: Quantity
) -> CheckResult:
    polar = (math.pi * diameter**4 / 32.0).to("mm^4")
    value = (torque * (diameter / 2.0) / polar).to("MPa")
    return CheckResult(
        name="torsional_shear_stress_circular",
        value=value,
        formula="tau = T*r/J,  J = pi*d^4/32",
        source="Classical torsion theory for circular sections",
        limitations=(
            "circular cross-sections only; non-circular sections warp and this "
            "formula does not apply to them at all",
            "linear elastic, uniform torque along the length",
        ),
        intermediate={"T": torque, "d": diameter, "J": polar},
    )


# ----------------------------------------------------------------------
# Margins
# ----------------------------------------------------------------------
def safety_factor(
    capacity: Quantity, demand: Quantity, *, name: str = "safety_factor"
) -> CheckResult:
    """Capacity over demand, with interval arithmetic doing the honest work.

    When either input is uncertain the result is an interval, so a safety factor
    of ``[1.8, 2.4]`` against a target of 2.0 produces an ``INCONCLUSIVE`` gate
    rather than a reassuring 2.1.
    """
    if demand.magnitude.straddles_zero:
        raise AnalysisError(
            "cannot compute a safety factor against a demand interval that "
            "includes zero",
            demand=str(demand),
            hint="a zero or sign-changing demand means the load case is not "
            "well posed for this check",
        )
    value = (capacity / demand).to("")
    return CheckResult(
        name=name,
        value=value,
        formula="n = capacity / demand",
        source="Definition",
        limitations=(
            "a ratio against a single load case and a single failure mode; it "
            "is not a margin against every way the part can fail",
            "carries every limitation of the capacity and demand it was "
            "computed from",
        ),
        intermediate={"capacity": capacity, "demand": demand},
    )


def von_mises_stress(
    sigma_x: Quantity,
    sigma_y: Quantity | None = None,
    tau_xy: Quantity | None = None,
) -> CheckResult:
    """Plane-stress von Mises equivalent stress."""
    zero = Q(0.0, "MPa")
    sx = sigma_x.to("MPa")
    sy = (sigma_y or zero).to("MPa")
    txy = (tau_xy or zero).to("MPa")
    value = (sx**2 - sx * sy + sy**2 + 3.0 * txy**2).sqrt().to("MPa")
    return CheckResult(
        name="von_mises_stress",
        value=value,
        formula="sigma_vm = sqrt(sx^2 - sx*sy + sy^2 + 3*txy^2)",
        source="Distortion-energy (von Mises) yield criterion, plane stress",
        limitations=(
            "plane stress; a full triaxial state needs the general form",
            "a ductile-yield criterion; it does not predict brittle fracture, "
            "fatigue, or buckling",
        ),
        intermediate={"sigma_x": sx, "sigma_y": sy, "tau_xy": txy},
    )


# ----------------------------------------------------------------------
# Thermal
# ----------------------------------------------------------------------
def conduction_resistance(
    length: Quantity, area: Quantity, conductivity: Quantity
) -> CheckResult:
    value = (length / (conductivity * area)).to("K/W")
    return CheckResult(
        name="conduction_resistance",
        value=value,
        formula="R = L/(k*A)",
        source="One-dimensional Fourier conduction",
        limitations=(
            "one-dimensional, steady state, constant conductivity",
            "ignores contact resistance at interfaces, which often dominates",
        ),
        intermediate={"L": length, "A": area, "k": conductivity},
    )


def convection_resistance(
    area: Quantity, coefficient: Quantity
) -> CheckResult:
    value = (1.0 / (coefficient * area)).to("K/W")
    return CheckResult(
        name="convection_resistance",
        value=value,
        formula="R = 1/(h*A)",
        source="Newton's law of cooling",
        limitations=(
            "steady state; the convection coefficient is itself an estimate "
            "with typically 25-50% uncertainty",
        ),
        intermediate={"A": area, "h": coefficient},
    )


# ----------------------------------------------------------------------
# Kinematics
# ----------------------------------------------------------------------
def lever_mechanical_advantage(
    input_arm: Quantity, output_arm: Quantity
) -> CheckResult:
    value = (input_arm / output_arm).to("")
    return CheckResult(
        name="lever_mechanical_advantage",
        value=value,
        formula="MA = a_in / a_out",
        source="Statics of a rigid lever",
        limitations=(
            "ideal rigid lever, frictionless pivot, quasi-static",
            "valid at one configuration only; mechanical advantage varies over "
            "the travel of any real linkage",
        ),
        intermediate={"a_in": input_arm, "a_out": output_arm},
    )


def gear_ratio(driving_teeth: Quantity, driven_teeth: Quantity) -> CheckResult:
    value = (driven_teeth / driving_teeth).to("")
    return CheckResult(
        name="gear_ratio",
        value=value,
        formula="i = N_driven / N_driving",
        source="Kinematics of a gear pair",
        limitations=(
            "ideal, backlash-free, no efficiency loss",
        ),
        intermediate={"N_driving": driving_teeth, "N_driven": driven_teeth},
    )


def actuator_torque(force: Quantity, arm: Quantity) -> CheckResult:
    value = (force * arm).to("Nm")
    return CheckResult(
        name="actuator_torque",
        value=value,
        formula="T = F*r",
        source="Statics",
        limitations=(
            "quasi-static; adds no inertia, friction or acceleration allowance",
            "computed at one configuration",
        ),
        intermediate={"F": force, "r": arm},
    )


ALL_CHECKS = (
    rectangular_second_moment,
    circular_second_moment,
    radius_of_gyration,
    axial_stress,
    direct_shear_stress,
    bearing_stress,
    bending_stress,
    cantilever_tip_deflection,
    cantilever_root_moment,
    euler_buckling_load,
    torsional_shear_stress_circular,
    safety_factor,
    von_mises_stress,
    conduction_resistance,
    convection_resistance,
    lever_mechanical_advantage,
    gear_ratio,
    actuator_torque,
)

__all__ = [
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
]
