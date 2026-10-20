"""The ForgeIR document: components, interfaces, requirements and provenance.

The document is the canonical source of truth for a design. CAD applications are
backends that consume it; none of them is the format of record. That separation
is what lets the same design compile to an implicit kernel for fast screening, to
OpenCascade for exact B-Rep, and to a Fusion reconstruction package, without any
of the three becoming privileged.

Two structural decisions carry most of the weight.

**Components are separated from instances.** A component is a definition -- a
parameter graph plus a feature graph plus the interfaces it exposes. An instance
is a placement of one. A bracket used four times is one component and four
instances, so editing it edits all four, and the assembly's degrees of freedom
are computed over instances rather than over duplicated geometry.

**Mates reference interfaces, never faces.** An interface is a functional port:
a bore, a shaft, a planar mount, a bolt pattern. It has a frame, a size, a fit
class and a load-transfer story. Two parts are joined by declaring that this pin
goes in that bore, which stays meaningful when the bore's diameter changes, when
the part is re-extruded, or when the CAD backend is swapped. A mate to "face 47"
would not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Mapping, Sequence

from forge_expr import Parameter, ParameterBounds, ParameterGraph
from forge_units import ForgeUnitsError, Quantity, parse_unit

from .features import FeatureGraph, decode_feature_graph
from .schema import (
    DanglingReferenceError,
    Reader,
    SchemaError,
    SchemaErrorGroup,
    ValueRangeError,
    join_pointer,
    require_unique_ids,
)
from .values import ExpressionValue, decode_scalar

SCHEMA_VERSION = "1.0.0"

RequirementType = Literal[
    "functional", "geometric", "interface", "performance", "manufacturing",
    "safety", "cost", "environmental", "aesthetic", "regulatory",
]
RequirementStrength = Literal["hard", "soft", "preference", "informational"]
RequirementState = Literal[
    "proposed", "accepted", "rejected", "superseded", "satisfied", "failed",
    "blocked", "not_tested",
]
VerificationMethod = Literal[
    "exact_geometry", "analytical", "simulation", "visual_review",
    "user_confirmation", "physical_test", "external_certification", "none",
]
RiskClass = Literal["low", "moderate", "high", "critical"]
InterfaceType = Literal[
    "bore", "shaft", "planar_mount", "bolt_pattern", "keyway",
    "gear_pitch_surface", "slider_rail", "electrical_placeholder",
    "fluid_placeholder", "custom",
]


# ----------------------------------------------------------------------
# Requirements and assumptions
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Requirement:
    """A checkable statement about the design.

    A requirement without a ``verification`` method is not a requirement, it is
    a wish, so the field is required. ``threshold`` is a quantity rather than a
    number for the usual reason: a limit without a unit is not a limit.
    """

    identifier: str
    statement: str
    requirement_type: RequirementType
    strength: RequirementStrength
    verification: VerificationMethod
    threshold: Quantity | None = None
    comparison: Literal["at_least", "at_most", "equals", "within", "none"] = "none"
    #: What to measure, from the vocabulary in :mod:`forge_ir.measurements`.
    #: A requirement with a threshold but no binding cannot be checked, and is
    #: reported ``NOT_TESTED`` rather than quietly ignored -- see ADR-0009.
    measurement: str = ""
    source: str = "user"
    state: RequirementState = "proposed"
    rationale: str = ""
    tags: tuple[str, ...] = ()
    pointer: str = ""

    @property
    def is_critical(self) -> bool:
        return self.strength == "hard"

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.identifier,
            "statement": self.statement,
            "type": self.requirement_type,
            "strength": self.strength,
            "verification": self.verification,
            "source": self.source,
            "state": self.state,
        }
        if self.threshold is not None:
            payload["threshold"] = self.threshold.as_dict()
        if self.comparison != "none":
            payload["comparison"] = self.comparison
        if self.measurement:
            payload["measurement"] = self.measurement
        if self.rationale:
            payload["rationale"] = self.rationale
        if self.tags:
            payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True, slots=True)
class Assumption:
    """A value the design relies on that the user did not supply.

    The ``consequence`` and ``approval`` fields are what stop an assumption from
    behaving like a fact. Only low-risk workflow assumptions may be
    auto-accepted; loads, safety factors, material grades, human anatomy and
    environmental exposure require explicit acceptance, and until they have it
    the requirements that depend on them cannot pass.
    """

    identifier: str
    statement: str
    value: Quantity | None = None
    rationale: str = ""
    consequence_if_wrong: str = ""
    risk: RiskClass = "moderate"
    reversible: bool = True
    approved: bool = False
    pointer: str = ""

    @property
    def requires_explicit_approval(self) -> bool:
        return self.risk in ("high", "critical") or not self.reversible

    @property
    def blocks_release(self) -> bool:
        return self.requires_explicit_approval and not self.approved

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.identifier,
            "statement": self.statement,
            "risk": self.risk,
            "reversible": self.reversible,
            "approved": self.approved,
        }
        if self.value is not None:
            payload["value"] = self.value.as_dict()
        if self.rationale:
            payload["rationale"] = self.rationale
        if self.consequence_if_wrong:
            payload["consequence_if_wrong"] = self.consequence_if_wrong
        return payload


# ----------------------------------------------------------------------
# Interfaces
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Interface:
    """A functional port on a component.

    ``geometry`` names a semantic output published by a feature -- for instance
    ``pivot.bore``. The compiler checks that the name resolves before any
    geometry is built, so an interface pointing at geometry that no longer
    exists is caught at validation rather than at assembly time.
    """

    identifier: str
    interface_type: InterfaceType
    geometry: str
    nominal_size: Quantity | None = None
    fit: str = ""
    load_transfer: str = ""
    allowable_motion: tuple[str, ...] = ()
    description: str = ""
    pointer: str = ""

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.identifier,
            "type": self.interface_type,
            "geometry": self.geometry,
        }
        if self.nominal_size is not None:
            payload["nominal_size"] = self.nominal_size.as_dict()
        if self.fit:
            payload["fit"] = self.fit
        if self.load_transfer:
            payload["load_transfer"] = self.load_transfer
        if self.allowable_motion:
            payload["allowable_motion"] = list(self.allowable_motion)
        if self.description:
            payload["description"] = self.description
        return payload


def _joining_union(terminals: Sequence[Any], graph: Any) -> str:
    """The literal feature that would weld these loose solids into one.

    Describing the fix was not enough. "Add a `union` or `subtract` that
    consumes them all" was delivered three times to a designer whose standoff
    had a `base_plate` and a `hole` hanging loose, and three times it returned
    the same two-terminal graph. The lesson of every prompt fix in this system
    has been the same: a model copies a line far more reliably than it follows
    a description of one.

    Nothing is invented here. The ids are the ones it wrote, and the choice
    that *is* a design decision -- weld or cut -- is left to it, with the
    alternative named alongside.

    The name must survive the edit it is suggesting. An earlier version tried
    `body`, then `body_2`, `body_3`, until it found one free in the graph it
    was looking at -- and a run failed three times because the model pasted
    `body_2` exactly as instructed, then referred to the thing it had just
    added as `body`, which was the obvious name and was no longer taken by
    the time the edit was applied. A suffix that encodes a collision in the
    *previous* draft is a name that rots. Deriving it from the component
    instead gives a name that is stable across attempts and unlikely to
    collide in the first place; `_normalise_document` now applies this edit
    without asking, so this hint is the fallback rather than the path.
    """
    existing = {feature.identifier for feature in graph}
    name = "part_body"
    while name in existing:
        name += "_"
    return json.dumps(
        {
            "id": name,
            "kind": "union",
            "inputs": [feature.identifier for feature in terminals],
        }
    )


# ----------------------------------------------------------------------
# Components
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Component:
    """A parametric part definition."""

    identifier: str
    name: str
    parameters: ParameterGraph
    features: FeatureGraph
    interfaces: tuple[Interface, ...] = ()
    material: str = ""
    description: str = ""
    pointer: str = ""

    def interface(self, identifier: str) -> Interface:
        for candidate in self.interfaces:
            if candidate.identifier == identifier:
                return candidate
        raise DanglingReferenceError(
            "no such interface on this component",
            pointer=self.pointer,
            component=self.identifier,
            interface=identifier,
            available=[i.identifier for i in self.interfaces],
        )

    def validate(self) -> None:
        """Check the cross-references the decoder could not check in isolation."""
        errors: list[SchemaError] = []

        published = self.features.semantic_names()
        for interface in self.interfaces:
            if interface.geometry not in published:
                errors.append(
                    DanglingReferenceError(
                        "interface refers to geometry no feature publishes",
                        pointer=join_pointer(interface.pointer, "geometry"),
                        component=self.identifier,
                        interface=interface.identifier,
                        geometry=interface.geometry,
                        available=sorted(published)[:40],
                    )
                )

        declared = set(self.parameters.identifiers())

        # A parameter defined as itself. Observed live, twice in one
        # document: `mounting_hole_diameter = mounting_hole_diameter`, which
        # is a definition with no value in it. The expression layer catches
        # the cycle, but only when the parameters are resolved, which happens
        # at compile -- so the document decoded cleanly, the designer was
        # told about something else entirely, and the real fault was never
        # named. Caught here instead, beside every other cross-reference, and
        # cheaply: a self-reference needs no graph walk to see.
        for identifier in sorted(self.parameters.identifiers()):
            try:
                depends_on = set(self.parameters.dependencies_of(identifier))
            except Exception:  # noqa: BLE001 - a graph we cannot walk
                continue
            if identifier in depends_on:
                errors.append(
                    DanglingReferenceError(
                        "a parameter is defined as itself",
                        pointer=self.pointer,
                        component=self.identifier,
                        parameter=identifier,
                        hint=f"`{identifier}` is defined as an expression "
                             f"that reads `{identifier}`, so it has no value. "
                             "Give it a `value` with a magnitude and a unit, "
                             "or an `expression` over other parameters.",
                    )
                )

        for feature in self.features:
            for name in sorted(feature.free_names()):
                if name in declared:
                    continue
                try:
                    parse_unit(name)
                except ForgeUnitsError:
                    errors.append(
                        DanglingReferenceError(
                            "feature parameter references an undeclared name",
                            pointer=feature.pointer,
                            component=self.identifier,
                            feature=feature.identifier,
                            missing=name,
                            available=sorted(declared)[:40],
                        )
                    )

        terminals = [f for f in self.features.terminal_features() if f.produces == "solid"]
        if not terminals:
            errors.append(
                ValueRangeError(
                    "component has no terminal solid; every part must end in "
                    "exactly one body",
                    pointer=self.pointer,
                    component=self.identifier,
                )
            )
        elif len(terminals) > 1:
            errors.append(
                ValueRangeError(
                    "component has more than one terminal solid; combine them "
                    "with a boolean or remove the orphan",
                    pointer=self.pointer,
                    component=self.identifier,
                    terminals=[f.identifier for f in terminals],
                    hint=(
                        "these features are each the end of their own chain: "
                        + ", ".join(f.identifier for f in terminals)
                        + ". A part is one solid. Add this feature at the end "
                        "of `features`, exactly as written:\n"
                        + _joining_union(terminals, self.features)
                        + "\nThat welds them together. If you meant to cut one "
                        "away from the other instead, use `subtract` with the "
                        "same `inputs`, body first."
                    ),
                )
            )

        if errors:
            raise SchemaErrorGroup(errors)

    @property
    def body_feature(self) -> str:
        terminals = [
            f for f in self.features.terminal_features() if f.produces == "solid"
        ]
        return terminals[0].identifier

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.identifier,
            "name": self.name,
            **self.parameters.as_dict(),
            "features": self.features.as_json(),
        }
        if self.interfaces:
            payload["interfaces"] = [i.as_json() for i in self.interfaces]
        if self.material:
            payload["material"] = self.material
        if self.description:
            payload["description"] = self.description
        return payload


# ----------------------------------------------------------------------
# Document root
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Units:
    """Declared units of account for the document."""

    length: str = "mm"
    mass: str = "kg"
    time: str = "s"
    angle: str = "deg"
    force: str = "N"
    stress: str = "MPa"

    def as_json(self) -> dict[str, str]:
        return {
            "length": self.length,
            "mass": self.mass,
            "time": self.time,
            "angle": self.angle,
            "force": self.force,
            "stress": self.stress,
        }


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a document came from, for reproducibility."""

    created_by: str = ""
    tool_version: str = ""
    model_provider: str = ""
    model_name: str = ""
    seed: int | None = None
    notes: str = ""

    def as_json(self) -> dict[str, Any]:
        payload = {
            "created_by": self.created_by,
            "tool_version": self.tool_version,
        }
        if self.model_provider:
            payload["model_provider"] = self.model_provider
        if self.model_name:
            payload["model_name"] = self.model_name
        if self.seed is not None:
            payload["seed"] = self.seed  # type: ignore[assignment]
        if self.notes:
            payload["notes"] = self.notes
        return payload


@dataclass(frozen=True, slots=True)
class Document:
    """A complete ForgeIR design revision."""

    schema_version: str
    document_id: str
    project_id: str
    revision: int
    name: str
    units: Units = field(default_factory=Units)
    components: tuple[Component, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    provenance: Provenance = field(default_factory=Provenance)
    risk_class: RiskClass = "low"
    parent_revision_id: str | None = None
    description: str = ""

    # -- access --------------------------------------------------------
    def component(self, identifier: str) -> Component:
        for candidate in self.components:
            if candidate.identifier == identifier:
                return candidate
        raise DanglingReferenceError(
            "no such component",
            component=identifier,
            available=[c.identifier for c in self.components],
        )

    def __iter__(self) -> Iterator[Component]:
        return iter(self.components)

    def hard_requirements(self) -> tuple[Requirement, ...]:
        return tuple(r for r in self.requirements if r.is_critical)

    def unapproved_blocking_assumptions(self) -> tuple[Assumption, ...]:
        return tuple(a for a in self.assumptions if a.blocks_release)

    # -- validation ----------------------------------------------------
    def validate(self) -> None:
        errors: list[SchemaError] = []
        for component in self.components:
            try:
                component.validate()
            except SchemaErrorGroup as group:
                errors.extend(group.errors)
            except SchemaError as error:
                errors.append(error)
        if errors:
            raise SchemaErrorGroup(errors)

    # -- serialisation --------------------------------------------------
    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "document_id": self.document_id,
            "project_id": self.project_id,
            "revision": self.revision,
            "name": self.name,
            "units": self.units.as_json(),
            "risk_class": self.risk_class,
            "components": [c.as_json() for c in self.components],
        }
        if self.parent_revision_id:
            payload["parent_revision_id"] = self.parent_revision_id
        if self.requirements:
            payload["requirements"] = [r.as_json() for r in self.requirements]
        if self.assumptions:
            payload["assumptions"] = [a.as_json() for a in self.assumptions]
        provenance = self.provenance.as_json()
        if provenance:
            payload["provenance"] = provenance
        if self.description:
            payload["description"] = self.description
        return payload

    def to_json(self, *, indent: int = 2) -> str:
        """Serialise canonically: sorted keys and a fixed separator.

        Canonical form matters because the document's bytes are hashed into
        every downstream provenance record. Two serialisations of the same
        design must produce the same hash.
        """
        return json.dumps(
            self.as_json(), indent=indent, sort_keys=True, separators=(",", ": ")
        )

    @classmethod
    def from_json(cls, text: str | bytes) -> "Document":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SchemaError(
                f"document is not valid JSON: {exc.msg}",
                pointer="",
                line=exc.lineno,
                column=exc.colno,
            ) from exc
        except RecursionError as exc:
            raise SchemaError(
                "document is nested too deeply to be a ForgeIR document",
                pointer="",
            ) from exc
        return decode_document(Reader(payload, ""))


# ----------------------------------------------------------------------
# Decoders
# ----------------------------------------------------------------------
def _decode_quantity(reader: Reader) -> Quantity:
    value = decode_scalar(reader)
    resolved = value.resolve(None)
    return resolved


def decode_requirement(reader: Reader) -> Requirement:
    reader.reject_unknown(
        [
            "id", "statement", "type", "strength", "verification", "threshold",
            "comparison", "measurement", "source", "state", "rationale", "tags",
        ]
    )
    threshold_reader = reader.optional("threshold")
    return Requirement(
        identifier=reader.require("id").as_identifier(),
        statement=reader.require("statement").as_str(),
        requirement_type=reader.require("type").as_str(  # type: ignore[arg-type]
            allowed=(
                "functional", "geometric", "interface", "performance",
                "manufacturing", "safety", "cost", "environmental", "aesthetic",
                "regulatory",
            )
        ),
        strength=reader.require("strength").as_str(  # type: ignore[arg-type]
            allowed=("hard", "soft", "preference", "informational")
        ),
        verification=reader.require("verification").as_str(  # type: ignore[arg-type]
            allowed=(
                "exact_geometry", "analytical", "simulation", "visual_review",
                "user_confirmation", "physical_test", "external_certification",
                "none",
            )
        ),
        threshold=_decode_quantity(threshold_reader) if threshold_reader else None,
        comparison=_one_of(  # type: ignore[arg-type]
            reader, "comparison", "none",
            ("none", "at_least", "at_most", "equals", "greater_than",
             "less_than", "within")),
        measurement=reader.optional_str("measurement", ""),
        source=reader.optional_str("source", "user"),
        state=_one_of(  # type: ignore[arg-type]
            reader, "state", "proposed",
            ("proposed", "accepted", "rejected", "superseded", "satisfied",
             "failed", "blocked", "not_tested")),
        rationale=reader.optional_str("rationale", ""),
        tags=reader.optional_str_tuple("tags"),
        pointer=reader.pointer,
    )


def decode_assumption(reader: Reader) -> Assumption:
    reader.reject_unknown(
        [
            "id", "statement", "value", "rationale", "consequence_if_wrong",
            "risk", "reversible", "approved",
        ]
    )
    value_reader = reader.optional("value")
    return Assumption(
        identifier=reader.require("id").as_identifier(),
        statement=reader.require("statement").as_str(),
        value=_decode_quantity(value_reader) if value_reader else None,
        rationale=reader.optional_str("rationale", ""),
        consequence_if_wrong=reader.optional_str("consequence_if_wrong", ""),
        # Validated, and folded to lower case first. `requires_explicit_approval`
        # tests `risk in ("high", "critical")`: unvalidated, an unapproved
        # assumption written `"risk": "HIGH"` or `"severe"` decoded cleanly
        # and simply stopped blocking release -- the one human gate in the
        # system, bypassed by spelling.
        risk=_one_of(  # type: ignore[arg-type]
            reader, "risk", "moderate", ("low", "moderate", "high", "critical")),
        reversible=reader.optional_bool("reversible", True),
        approved=reader.optional_bool("approved", False),
        pointer=reader.pointer,
    )


def decode_interface(reader: Reader) -> Interface:
    reader.reject_unknown(
        [
            "id", "type", "geometry", "nominal_size", "fit", "load_transfer",
            "allowable_motion", "description",
        ]
    )
    size_reader = reader.optional("nominal_size")
    return Interface(
        identifier=reader.require("id").as_identifier(),
        interface_type=reader.require("type").as_str(  # type: ignore[arg-type]
            allowed=(
                "bore", "shaft", "planar_mount", "bolt_pattern", "keyway",
                "gear_pitch_surface", "slider_rail", "electrical_placeholder",
                "fluid_placeholder", "custom",
            )
        ),
        geometry=reader.require("geometry").as_str(),
        nominal_size=_decode_quantity(size_reader) if size_reader else None,
        fit=reader.optional_str("fit", ""),
        load_transfer=reader.optional_str("load_transfer", ""),
        allowable_motion=reader.optional_str_tuple("allowable_motion"),
        description=reader.optional_str("description", ""),
        pointer=reader.pointer,
    )


def _one_of(reader: Reader, name: str, default: str,
            allowed: Sequence[str]) -> str:
    """An enumerated field, folded to lower case and checked against its
    options, at its own pointer. A model that writes `HIGH` means `high`;
    one that writes `severe` is told what the options are."""
    text = reader.optional_str(name, default)
    folded = str(text).strip().lower()
    if folded not in allowed:
        raise ValueRangeError(
            f"`{name}` is not one of the permitted options",
            pointer=join_pointer(reader.pointer, name),
            got=text,
            allowed=sorted(allowed),
        )
    return folded


def decode_parameter(reader: Reader) -> Parameter:
    """A component parameter, every fault said as a SchemaError.

    `Parameter.__post_init__` refuses a reserved name (`pi`, `e`, `g0`) and
    an id the reader admits but Python does not (`a-b`, `a.b`) with the
    expression engine's own exceptions, and a bound in another dimension
    from the value was accepted here and refused at resolution. Each is a
    fault in this object, pointed at this object.
    """
    from forge_expr import ForgeExprError

    try:
        parameter = _decode_parameter_fields(reader)
    except ForgeExprError as exc:
        raise ValueRangeError(
            exc.message,
            pointer=join_pointer(reader.pointer, "id"),
            cause=exc.code,
            **{key: value for key, value in exc.detail.items()
               if key not in ("pointer", "cause")},
        ) from exc
    bounds = parameter.bounds
    unit = parameter.unit
    if bounds is not None and unit is not None:
        for name in ("minimum", "maximum"):
            limit = getattr(bounds, name, None)
            if limit is not None and limit.dimension != unit.dimension:
                raise ValueRangeError(
                    f"the parameter's {name} bound is not in the parameter's "
                    "own dimension",
                    pointer=join_pointer(
                        join_pointer(reader.pointer, "bounds"),
                        "min" if name == "minimum" else "max"),
                    bound=str(limit),
                    unit=unit.symbol,
                )
    return parameter


def _decode_parameter_fields(reader: Reader) -> Parameter:
    reader.reject_unknown(
        ["id", "value", "expression", "unit", "bounds", "optimizable",
         "description", "tags"]
    )
    identifier = reader.require("id").as_identifier()
    unit_reader = reader.optional("unit")
    from .values import _unit_of

    unit = _unit_of(unit_reader) if unit_reader else None

    bounds_reader = reader.optional("bounds")
    minimum = maximum = None
    if bounds_reader is not None:
        bounds_reader.reject_unknown(["min", "max"])
        min_reader = bounds_reader.optional("min")
        max_reader = bounds_reader.optional("max")
        minimum = _decode_quantity(min_reader) if min_reader else None
        maximum = _decode_quantity(max_reader) if max_reader else None
    bounds = (
        ParameterBounds(minimum, maximum)
        if (minimum is not None or maximum is not None)
        else None
    )

    expression_reader = reader.optional("expression")
    value_reader = reader.optional("value")

    if (expression_reader is None) == (value_reader is None):
        raise ValueRangeError(
            "a parameter must declare exactly one of 'value' or 'expression'",
            pointer=reader.pointer,
            parameter=identifier,
            has_value=value_reader is not None,
            has_expression=expression_reader is not None,
        )

    if expression_reader is not None:
        from forge_expr import Expression, ForgeExprError

        source = expression_reader.as_str()
        try:
            expression = Expression.parse(source)
        except ForgeExprError as exc:
            # The one place a component parameter's expression was parsed
            # unguarded. `a *`, an empty string, `a.b` each left the decoder
            # as the expression engine's own exception, which no caller of
            # `Document.from_json` expects: the designer's judge turns a
            # SchemaError into a correction the model can act on, and
            # anything else into a generic "Forge could not read this
            # answer" retry that names a Forge traceback instead of the
            # mistake. A feature's expression has always been wrapped this
            # way in `decode_scalar`; a component's now is too.
            raise ValueRangeError(
                f"invalid expression: {exc.message}",
                pointer=join_pointer(reader.pointer, "expression"),
                parameter=identifier,
                source=source,
                cause=exc.code,
                hint="an expression is arithmetic over other parameters' "
                'ids, e.g. "plate_length / 2 - hole_offset"; a figure with '
                'its unit is written "30 * mm"',
            ) from exc
        return Parameter(
            identifier=identifier,
            expression=expression,
            unit=unit,
            bounds=bounds,
            description=reader.optional_str("description", ""),
            tags=reader.optional_str_tuple("tags"),
        )

    assert value_reader is not None
    scalar = decode_scalar(value_reader)
    if isinstance(scalar, ExpressionValue):
        # `{"value": {"expression": "plate_length - 16"}}` -- the expression put
        # where a literal goes. It is the wrong spelling and it is an entirely
        # reasonable mistake: in a *feature* parameter `{"expression": ...}` is
        # exactly how a value is written, and only a *component* parameter
        # carries the expression as a sibling of `id`. Both mean one thing, so
        # it is read rather than refused.
        #
        # Refusing cost a live run 82 minutes: the message it produced --
        # "an expression parameter requires a resolved parameter graph" --
        # describes an internal precondition, names neither the mistake nor the
        # fix, and the model returned the same document three times.
        return Parameter(
            identifier=identifier,
            expression=scalar.expression,
            unit=unit or scalar.unit,
            bounds=bounds,
            description=reader.optional_str("description", ""),
            tags=reader.optional_str_tuple("tags"),
        )
    quantity = scalar.resolve(None)
    return Parameter(
        identifier=identifier,
        value=quantity,
        unit=unit or quantity.unit,
        bounds=bounds,
        optimizable=reader.optional_bool("optimizable", False),
        description=reader.optional_str("description", ""),
        tags=reader.optional_str_tuple("tags"),
    )


def decode_component(reader: Reader) -> Component:
    reader.reject_unknown(
        ["id", "name", "parameters", "features", "interfaces", "material",
         "description"]
    )
    identifier = reader.require("id").as_identifier()

    parameters_reader = reader.optional("parameters")
    declared = (
        parameters_reader.decode_list(decode_parameter) if parameters_reader else []
    )
    # Components, features and interfaces were checked for duplicate ids;
    # parameters were not, and the graph refused the second with its own
    # exception, which is not a SchemaError.
    require_unique_ids(
        [p.identifier for p in declared],
        pointer=parameters_reader.pointer if parameters_reader else reader.pointer,
        kind="parameter",
    )
    parameters = ParameterGraph(declared)

    features = decode_feature_graph(reader.require("features"))

    interfaces_reader = reader.optional("interfaces")
    interfaces = tuple(
        interfaces_reader.decode_list(decode_interface) if interfaces_reader else []
    )
    require_unique_ids(
        [i.identifier for i in interfaces],
        pointer=interfaces_reader.pointer if interfaces_reader else reader.pointer,
        kind="interface",
    )

    return Component(
        identifier=identifier,
        name=reader.optional_str("name", identifier),
        parameters=parameters,
        features=features,
        interfaces=interfaces,
        material=reader.optional_str("material", ""),
        description=reader.optional_str("description", ""),
        pointer=reader.pointer,
    )


def decode_units(reader: Reader) -> Units:
    reader.reject_unknown(["length", "mass", "time", "angle", "force", "stress"])
    unit_fields = {
        "length": "mm", "mass": "kg", "time": "s",
        "angle": "deg", "force": "N", "stress": "MPa",
    }
    resolved: dict[str, str] = {}
    for name, default in unit_fields.items():
        symbol = reader.optional_str(name, default)
        try:
            parse_unit(symbol)
        except ForgeUnitsError as exc:
            raise ValueRangeError(
                f"declared {name} unit is not recognised: {exc.message}",
                pointer=join_pointer(reader.pointer, name),
                symbol=symbol,
            ) from exc
        except Exception as exc:  # noqa: BLE001 - as `_unit_of` in values.py
            raise ValueRangeError(
                f"declared {name} unit is not usable: {exc}"[:300],
                pointer=join_pointer(reader.pointer, name),
                symbol=symbol[:80],
            ) from exc
        resolved[name] = symbol
    return Units(**resolved)


def decode_provenance(reader: Reader) -> Provenance:
    reader.reject_unknown(
        ["created_by", "tool_version", "model_provider", "model_name", "seed",
         "notes"]
    )
    seed_reader = reader.optional("seed")
    return Provenance(
        created_by=reader.optional_str("created_by", ""),
        tool_version=reader.optional_str("tool_version", ""),
        model_provider=reader.optional_str("model_provider", ""),
        model_name=reader.optional_str("model_name", ""),
        seed=seed_reader.as_int() if seed_reader else None,
        notes=reader.optional_str("notes", ""),
    )


_DOCUMENT_FIELDS = (
    "schema_version", "document_id", "project_id", "revision", "name", "units",
    "components", "requirements", "assumptions", "provenance", "risk_class",
    "parent_revision_id", "description",
)


def decode_document(reader: Reader) -> Document:
    reader.reject_unknown(_DOCUMENT_FIELDS)

    schema_version = reader.require("schema_version").as_str()
    major = schema_version.split(".")[0]
    if major != SCHEMA_VERSION.split(".")[0]:
        raise ValueRangeError(
            "document schema major version is not supported by this build",
            pointer=join_pointer(reader.pointer, "schema_version"),
            got=schema_version,
            supported=SCHEMA_VERSION,
        )

    units_reader = reader.optional("units")
    provenance_reader = reader.optional("provenance")
    components_reader = reader.optional("components")
    requirements_reader = reader.optional("requirements")
    assumptions_reader = reader.optional("assumptions")
    parent = reader.optional("parent_revision_id")

    components = tuple(
        components_reader.decode_list(decode_component) if components_reader else []
    )
    require_unique_ids(
        [c.identifier for c in components],
        pointer=components_reader.pointer if components_reader else reader.pointer,
        kind="component",
    )

    requirements = tuple(
        requirements_reader.decode_list(decode_requirement)
        if requirements_reader
        else []
    )
    assumptions = tuple(
        assumptions_reader.decode_list(decode_assumption)
        if assumptions_reader
        else []
    )
    # Addressed by id everywhere downstream -- a gate per requirement, an
    # approval per assumption -- so two of one id are refused here, where
    # the pointer says which, rather than by the evidence graph at verify
    # time with the run half done.
    require_unique_ids(
        [r.identifier for r in requirements],
        pointer=requirements_reader.pointer if requirements_reader
        else reader.pointer,
        kind="requirement",
    )
    require_unique_ids(
        [a.identifier for a in assumptions],
        pointer=assumptions_reader.pointer if assumptions_reader
        else reader.pointer,
        kind="assumption",
    )

    document = Document(
        schema_version=schema_version,
        document_id=reader.require("document_id").as_str(),
        project_id=reader.require("project_id").as_str(),
        revision=reader.require("revision").as_int(minimum=1),
        name=reader.optional_str("name", ""),
        units=decode_units(units_reader) if units_reader else Units(),
        components=components,
        requirements=requirements,
        assumptions=assumptions,
        provenance=(
            decode_provenance(provenance_reader) if provenance_reader else Provenance()
        ),
        risk_class=_one_of(  # type: ignore[arg-type]
            reader, "risk_class", "low", ("low", "moderate", "high", "critical")),
        parent_revision_id=parent.as_str() if parent else None,
        description=reader.optional_str("description", ""),
    )
    document.validate()
    return document


__all__ = [
    "SCHEMA_VERSION",
    "Document",
    "Component",
    "Interface",
    "Requirement",
    "Assumption",
    "Units",
    "Provenance",
    "RiskClass",
    "InterfaceType",
    "RequirementType",
    "RequirementStrength",
    "RequirementState",
    "VerificationMethod",
    "decode_document",
    "decode_component",
    "decode_interface",
    "decode_requirement",
    "decode_assumption",
    "decode_parameter",
]
