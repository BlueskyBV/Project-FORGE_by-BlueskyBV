"""Material records, with sources and ranges rather than convenient point values.

The rule this module exists to enforce: **a generic material name is not an
engineering material.** "Aluminium" has a density that varies by 5% across
common alloys and a yield strength that varies by a factor of ten. Treating a
generic name as a specific grade is how a strength claim becomes fiction.

So :func:`lookup` refuses generic names. Asking for ``"aluminium"`` raises and
tells you which specific grades are available. If the design genuinely does not
know the grade yet, the honest response is to run scenarios across candidate
grades, or to block the strength claim -- both of which are supported, and
neither of which involves inventing a number.

Properties are stored as intervals wherever the source gives a range or a
distinction between typical and minimum values. Those intervals propagate: a
safety factor computed from a minimum-to-typical yield range comes out as a
range, and a gate against it can honestly return ``INCONCLUSIVE``.

Provenance note: the values below are drawn from widely published references and
are adequate for the synthetic validation examples this repository ships. They
are **not** a certified materials database. A real design should load a licensed
or measured dataset through :func:`register`, and the report says which source
was used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from forge_units import Q, Quantity


class MaterialError(Exception):
    """A material could not be resolved, or was too vague to use."""

    code = "AN1100_MATERIAL"

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
class Material:
    """A specific material grade in a specific condition."""

    identifier: str
    family: str
    grade: str
    condition: str
    density: Quantity
    elastic_modulus: Quantity
    poisson_ratio: Quantity
    yield_strength: Quantity
    ultimate_strength: Quantity
    thermal_conductivity: Quantity | None = None
    thermal_expansion: Quantity | None = None
    specific_heat: Quantity | None = None
    source: str = ""
    notes: tuple[str, ...] = ()
    #: Whether the properties are typical, minimum-guaranteed, or measured.
    basis: str = "typical"

    @property
    def display_name(self) -> str:
        return f"{self.grade} {self.condition}".strip()

    def allowable_stress(self, safety_factor: float) -> Quantity:
        """Yield strength divided by a design factor."""
        if safety_factor <= 0:
            raise MaterialError(
                "safety factor must be positive", safety_factor=safety_factor
            )
        return self.yield_strength / safety_factor

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.identifier,
            "family": self.family,
            "grade": self.grade,
            "condition": self.condition,
            "basis": self.basis,
            "source": self.source,
            "density": self.density.as_dict(),
            "elastic_modulus": self.elastic_modulus.as_dict(),
            "poisson_ratio": self.poisson_ratio.as_dict(),
            "yield_strength": self.yield_strength.as_dict(),
            "ultimate_strength": self.ultimate_strength.as_dict(),
        }
        for name, value in (
            ("thermal_conductivity", self.thermal_conductivity),
            ("thermal_expansion", self.thermal_expansion),
            ("specific_heat", self.specific_heat),
        ):
            if value is not None:
                payload[name] = value.as_dict()
        if self.notes:
            payload["notes"] = list(self.notes)
        return payload


_LIBRARY: dict[str, Material] = {}


def register(material: Material) -> Material:
    _LIBRARY[material.identifier] = material
    return material


#: Names that are families, not materials. Asking for one of these is an error
#: with a helpful message rather than a silently substituted guess.
_GENERIC_NAMES: Mapping[str, str] = {
    "aluminium": "aluminium",
    "aluminum": "aluminium",
    "steel": "steel",
    "stainless": "stainless steel",
    "stainless_steel": "stainless steel",
    "plastic": "polymer",
    "abs": "ABS",
    "pla": "PLA",
    "titanium": "titanium",
    "brass": "brass",
    "metal": "metal",
}


register(
    Material(
        identifier="aluminium_6061_t6",
        family="aluminium",
        grade="6061",
        condition="T6",
        density=Q(2700.0, "kg/m^3", relative=0.01),
        elastic_modulus=Q(68.9, "GPa", relative=0.03),
        poisson_ratio=Q(0.33, relative=0.05),
        # Minimum-to-typical spread, which is the honest way to carry the
        # difference between a specification minimum and a mill certificate.
        yield_strength=Q(Q(240.0, "MPa").magnitude.hull(Q(276.0, "MPa").magnitude), "MPa"),
        ultimate_strength=Q(Q(290.0, "MPa").magnitude.hull(Q(310.0, "MPa").magnitude), "MPa"),
        thermal_conductivity=Q(167.0, "W/(m*K)", relative=0.05),
        thermal_expansion=Q(23.6e-6, "1/K", relative=0.05),
        specific_heat=Q(896.0, "J/(kg*K)", relative=0.05),
        source="Widely published handbook values for 6061-T6 (e.g. ASM "
        "Aerospace Specification Metals datasheet). Not a certified dataset.",
        basis="minimum-to-typical range",
        notes=(
            "Properties in the heat-affected zone of a weld are substantially "
            "lower and are not represented here.",
            "T6 temper assumed throughout; a different temper changes the "
            "yield strength by more than a factor of three.",
        ),
    )
)

register(
    Material(
        identifier="steel_1018_cd",
        family="steel",
        grade="AISI 1018",
        condition="cold drawn",
        density=Q(7870.0, "kg/m^3", relative=0.01),
        elastic_modulus=Q(205.0, "GPa", relative=0.03),
        poisson_ratio=Q(0.29, relative=0.05),
        yield_strength=Q(Q(370.0, "MPa").magnitude.hull(Q(440.0, "MPa").magnitude), "MPa"),
        ultimate_strength=Q(Q(440.0, "MPa").magnitude.hull(Q(500.0, "MPa").magnitude), "MPa"),
        thermal_conductivity=Q(51.9, "W/(m*K)", relative=0.05),
        thermal_expansion=Q(11.5e-6, "1/K", relative=0.05),
        specific_heat=Q(486.0, "J/(kg*K)", relative=0.05),
        source="Widely published handbook values for AISI 1018 cold drawn. "
        "Not a certified dataset.",
        basis="minimum-to-typical range",
        notes=(
            "Cold-drawn properties are directional; transverse ductility is "
            "lower than longitudinal.",
        ),
    )
)

register(
    Material(
        identifier="stainless_304",
        family="stainless steel",
        grade="AISI 304",
        condition="annealed",
        density=Q(8000.0, "kg/m^3", relative=0.01),
        elastic_modulus=Q(193.0, "GPa", relative=0.03),
        poisson_ratio=Q(0.29, relative=0.05),
        yield_strength=Q(Q(205.0, "MPa").magnitude.hull(Q(310.0, "MPa").magnitude), "MPa"),
        ultimate_strength=Q(Q(515.0, "MPa").magnitude.hull(Q(620.0, "MPa").magnitude), "MPa"),
        thermal_conductivity=Q(16.2, "W/(m*K)", relative=0.05),
        thermal_expansion=Q(17.3e-6, "1/K", relative=0.05),
        specific_heat=Q(500.0, "J/(kg*K)", relative=0.05),
        source="Widely published handbook values for AISI 304 annealed. "
        "Not a certified dataset.",
        basis="minimum-to-typical range",
        notes=("Work hardens rapidly; formed sections are stronger and less ductile.",),
    )
)

register(
    Material(
        identifier="pla_fdm",
        family="polymer",
        grade="PLA",
        condition="FDM printed, 100% infill",
        density=Q(1240.0, "kg/m^3", relative=0.03),
        # The spread here is genuine and large: printed properties depend on
        # temperature, layer height and cooling as much as on the polymer.
        elastic_modulus=Q(Q(2.7, "GPa").magnitude.hull(Q(3.6, "GPa").magnitude), "GPa"),
        poisson_ratio=Q(0.36, relative=0.1),
        yield_strength=Q(Q(35.0, "MPa").magnitude.hull(Q(55.0, "MPa").magnitude), "MPa"),
        ultimate_strength=Q(Q(40.0, "MPa").magnitude.hull(Q(60.0, "MPa").magnitude), "MPa"),
        thermal_conductivity=Q(0.13, "W/(m*K)", relative=0.2),
        thermal_expansion=Q(68e-6, "1/K", relative=0.2),
        source="Representative published ranges for FDM-printed PLA. Printed "
        "polymer properties are process-dependent and should be measured for "
        "any load-bearing use.",
        basis="typical published range",
        notes=(
            "Strongly anisotropic: interlayer (Z) strength is commonly 40-60% "
            "of in-plane strength, and this record does not capture that.",
            "Creeps under sustained load at room temperature.",
            "Glass transition near 60 C; unsuitable for warm environments.",
        ),
    )
)


def lookup(identifier: str) -> Material:
    """Resolve a material, refusing family names.

    >>> lookup("aluminium_6061_t6").grade
    '6061'
    >>> lookup("aluminium")
    Traceback (most recent call last):
        ...
    forge_analysis.materials.MaterialError: ...
    """
    material = _LIBRARY.get(identifier)
    if material is not None:
        return material

    normalised = identifier.strip().lower().replace(" ", "_")
    if normalised in _GENERIC_NAMES:
        family = _GENERIC_NAMES[normalised]
        candidates = [
            key for key, value in _LIBRARY.items() if value.family == family
        ]
        raise MaterialError(
            f"'{identifier}' names a material family, not a specific grade and "
            "condition. Forge will not substitute a representative value: "
            "within this family the yield strength varies by more than a "
            "factor of three, so a strength claim based on the family name "
            "would be fiction.",
            requested=identifier,
            family=family,
            candidates=sorted(candidates) or sorted(_LIBRARY),
            hint="name a specific grade, or run scenarios across candidates and "
            "report the range",
        )

    raise MaterialError(
        "unknown material",
        requested=identifier,
        available=sorted(_LIBRARY),
    )


def available() -> tuple[str, ...]:
    return tuple(sorted(_LIBRARY))


def scenario(identifiers: tuple[str, ...]) -> tuple[Material, ...]:
    """Resolve several candidate grades, for a bounded-scenario analysis."""
    return tuple(lookup(identifier) for identifier in identifiers)


__all__ = [
    "Material",
    "MaterialError",
    "lookup",
    "register",
    "available",
    "scenario",
]
