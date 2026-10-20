"""Typed values that may appear as a feature parameter.

A feature parameter is one of a small closed set of sorts. Keeping the set
closed, and keeping every dimensional value unit-bearing, is what enforces
principle 6 of the product brief: dimensional values may never be untyped
floating-point numbers at a system boundary.

The four sorts are:

``QuantityValue``
    A literal magnitude with a unit: ``{"magnitude": 6.0, "unit": "mm"}``, or
    with an explicit tolerance interval.

``ExpressionValue``
    A dimension-checked expression over the parameter graph:
    ``{"expression": "ear_gap + 2 * ear_thickness", "unit": "mm"}``. The
    declared unit is checked against the expression's natural dimension when the
    feature is compiled, so a unit slip is caught at the feature rather than
    three operations downstream.

``VectorValue``
    A direction or a displacement: ``{"vector": [0, 0, 1]}`` for a direction,
    ``{"vector": [0, 0, 16], "unit": "mm"}`` for a displacement. Components may
    themselves be expressions.

``EnumValue`` / ``FlagValue`` / ``CountValue``
    Non-dimensional configuration: an option from a fixed set, a boolean, or a
    count. These carry no unit because they have no dimension, and the decoder
    refuses a bare number where a quantity is expected precisely so that the
    absence of a unit is never accidental.

Every sort resolves, against a :class:`~forge_expr.Resolution`, to a concrete
value the geometry backend can act on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Union

from forge_expr import Expression, ForgeExprError, Resolution
from forge_units import (
    ForgeUnitsError,
    Interval,
    Quantity,
    Unit,
    detail_besides,
    parse_unit,
)

from .schema import Reader, SchemaError, TypeMismatchError, ValueRangeError


class ValueError_(SchemaError):
    code = "IR1010_VALUE"


@dataclass(frozen=True, slots=True)
class QuantityValue:
    """A literal dimensional value."""

    quantity: Quantity

    def resolve(self, resolution: Resolution | None = None) -> Quantity:
        return self.quantity

    def free_names(self) -> frozenset[str]:
        return frozenset()

    def as_json(self) -> dict[str, Any]:
        return self.quantity.as_dict()

    def cache_key(self) -> str:
        magnitude = self.quantity.magnitude
        return f"q:{magnitude.lo!r}:{magnitude.hi!r}:{self.quantity.unit.symbol}"


@dataclass(frozen=True, slots=True)
class ExpressionValue:
    """A dimensional value computed from the parameter graph."""

    expression: Expression
    unit: Unit | None
    pointer: str = ""

    def resolve(self, resolution: Resolution | None = None) -> Quantity:
        if resolution is None:
            raise ValueError_(
                "an expression parameter requires a resolved parameter graph",
                pointer=self.pointer,
                expression=str(self.expression),
            )
        try:
            value = self.expression.evaluate_quantity(resolution.values)
        except ForgeExprError as exc:
            raise ValueError_(
                f"failed to evaluate feature parameter: {exc.message}",
                pointer=self.pointer,
                expression=str(self.expression),
                cause=exc.code,
                **detail_besides(exc.detail, "cause", "pointer", "expression"),
            ) from exc
        if self.unit is None:
            return value
        from forge_units import a_plain_number_in

        read = a_plain_number_in(value, self.unit, str(self.expression))
        if read is not None:
            # `360 / count` in a slot declared in degrees: that many degrees.
            return read
        if value.dimension != self.unit.dimension:
            # A dimensionless result from an expression that refers to nothing
            # is one specific mistake with one specific fix, and the general
            # wording sent a repair round the wrong way: told that
            # `declared_unit='mm'` and `actual_unit=''`, an analyst patched
            # `unit` to the `mm` it already said, changed nothing, and the run
            # died. The unit was never wrong. `{"expression": "4.0"}` is a
            # dimensionless four however the slot beside it is labelled.
            constant = not self.expression.free_names()
            hint = (
                f' -- `{self.expression}` refers to no parameter, so it is a '
                f'plain number and carries no dimension. Its unit is not the '
                f'problem: write it as a value instead, '
                f'{{"magnitude": ..., "unit": "{self.unit.symbol}"}}. An '
                "`expression` is for a value computed from other parameters."
                if constant and not value.unit.symbol else ""
            )
            raise ValueError_(
                "expression result does not have the dimension the parameter "
                "declares" + hint,
                pointer=self.pointer,
                expression=str(self.expression),
                declared_unit=self.unit.symbol,
                declared_measures=self.unit.dimension.describe(),
                actual_unit=value.unit.symbol,
                actual_measures=value.dimension.describe(),
                refers_to_nothing=constant,
            )
        return value.to(self.unit)

    def free_names(self) -> frozenset[str]:
        return self.expression.free_names()

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"expression": str(self.expression)}
        if self.unit is not None:
            payload["unit"] = self.unit.symbol
        return payload

    def cache_key(self) -> str:
        unit = self.unit.symbol if self.unit else ""
        return f"e:{self.expression.source}:{unit}"


@dataclass(frozen=True, slots=True)
class VectorValue:
    """A three-component direction or displacement."""

    components: tuple["ScalarValue", "ScalarValue", "ScalarValue"]
    normalise: bool = False

    def resolve(self, resolution: Resolution | None = None) -> tuple[Quantity, ...]:
        return tuple(component.resolve(resolution) for component in self.components)

    def resolve_direction(self, resolution: Resolution | None = None) -> tuple[float, float, float]:
        """Resolve to a unit-length dimensionless direction.

        A direction with zero length is refused rather than defaulted, because
        an extrude along a zero vector is a degenerate feature and guessing +Z
        would hide the author's mistake.
        """
        import math

        values = [component.resolve(resolution) for component in self.components]
        raw = []
        for value in values:
            if not value.is_dimensionless:
                # A displacement used as a direction: take its SI magnitude, the
                # normalisation removes the scale anyway.
                raw.append(value.si_magnitude.midpoint)
            else:
                raw.append(value.magnitude.midpoint)
        length = math.sqrt(sum(component * component for component in raw))
        if length <= 0.0:
            raise ValueError_(
                "direction vector has zero length",
                components=raw,
                hint="a direction must be non-zero; Forge does not substitute a "
                "default axis, because doing so would silently change the design",
            )
        return (raw[0] / length, raw[1] / length, raw[2] / length)

    def resolve_displacement(
        self, resolution: Resolution | None = None, *, unit: str = "mm"
    ) -> tuple[float, float, float]:
        target = parse_unit(unit)
        out: list[float] = []
        for component in self.components:
            value = component.resolve(resolution)
            if value.is_dimensionless and value.magnitude.midpoint == 0.0:
                out.append(0.0)
                continue
            out.append(value.to(target).magnitude.midpoint)
        return (out[0], out[1], out[2])

    def free_names(self) -> frozenset[str]:
        names: set[str] = set()
        for component in self.components:
            names |= component.free_names()
        return frozenset(names)

    def as_json(self) -> dict[str, Any]:
        return {
            "vector": [component.as_json() for component in self.components],
            **({"normalise": True} if self.normalise else {}),
        }

    def cache_key(self) -> str:
        inner = ",".join(component.cache_key() for component in self.components)
        return f"v:[{inner}]:{int(self.normalise)}"


@dataclass(frozen=True, slots=True)
class EnumValue:
    """A choice from a fixed set of options."""

    option: str

    def resolve(self, resolution: Resolution | None = None) -> str:
        return self.option

    def free_names(self) -> frozenset[str]:
        return frozenset()

    def as_json(self) -> str:
        return self.option

    def cache_key(self) -> str:
        return f"s:{self.option}"


@dataclass(frozen=True, slots=True)
class FlagValue:
    value: bool

    def resolve(self, resolution: Resolution | None = None) -> bool:
        return self.value

    def free_names(self) -> frozenset[str]:
        return frozenset()

    def as_json(self) -> bool:
        return self.value

    def cache_key(self) -> str:
        return f"b:{int(self.value)}"


@dataclass(frozen=True, slots=True)
class CountValue:
    """A whole number of things, literal or driven by a parameter.

    Counts were the one numeric sort a parameter could not drive, and that
    asymmetry was a trap of our own making: the guide tells the designer to
    express anything derivable rather than hard-code it, and then the only way
    to write a bolt count was to hard-code it. A model doing as it was told
    wrote ``{"expression": "bolt_count"}`` and was refused, three times.

    An expression here must resolve to an exact whole number. Four bolts is a
    count; 4.3 bolts is not, and neither is "somewhere between 3 and 5" -- an
    uncertain count would make the topology itself uncertain, and the lineage
    tokens that name each instance are derived from it.
    """

    value: int | None = None
    expression: Expression | None = None
    pointer: str = ""

    def __post_init__(self) -> None:
        if (self.value is None) == (self.expression is None):
            raise ValueError_(
                "a count is either a literal or an expression, not both",
                pointer=self.pointer,
            )

    def resolve(self, resolution: Resolution | None = None) -> int:
        if self.expression is None:
            assert self.value is not None  # guaranteed by __post_init__
            return self.value
        if resolution is None:
            raise ValueError_(
                "a count written as an expression requires a resolved "
                "parameter graph",
                pointer=self.pointer,
                expression=str(self.expression),
            )
        try:
            quantity = self.expression.evaluate_quantity(resolution.values)
        except ForgeExprError as exc:
            raise ValueError_(
                f"failed to evaluate count: {exc.message}",
                pointer=self.pointer,
                expression=str(self.expression),
                cause=exc.code,
                **detail_besides(exc.detail, "cause", "pointer", "expression"),
            ) from exc
        if not quantity.is_dimensionless:
            raise ValueError_(
                "a count must be dimensionless",
                pointer=self.pointer,
                expression=str(self.expression),
                actual_unit=quantity.unit.symbol,
                hint="a count of things carries no unit. Reference a parameter "
                'written as {"magnitude": 4, "unit": ""}.',
            )
        magnitude = quantity.magnitude
        if not magnitude.is_exact:
            raise ValueError_(
                "a count must be exact, and this one is a range",
                pointer=self.pointer,
                expression=str(self.expression),
                interval=[magnitude.lo, magnitude.hi],
                hint="an uncertain count would make the topology uncertain. "
                "Drive it from a parameter with a single value, not one "
                "carrying a tolerance.",
            )
        midpoint = magnitude.midpoint
        nearest = round(midpoint)
        if abs(midpoint - nearest) > 1e-9:
            raise ValueError_(
                "a count must be a whole number",
                pointer=self.pointer,
                expression=str(self.expression),
                got=midpoint,
                hint="there is no such thing as a fractional instance. Round "
                "in the expression if that is what you mean.",
            )
        if nearest < 1:
            raise ValueError_(
                "a count must be at least 1",
                pointer=self.pointer,
                expression=str(self.expression),
                got=nearest,
            )
        from .features import MAX_COUNT

        if nearest > MAX_COUNT:
            raise ValueError_(
                "a count is beyond anything a pattern can be",
                pointer=self.pointer,
                expression=str(self.expression),
                got=nearest,
                limit=MAX_COUNT,
            )
        return int(nearest)

    def free_names(self) -> frozenset[str]:
        if self.expression is None:
            return frozenset()
        return self.expression.free_names()

    def as_json(self) -> int | dict[str, Any]:
        if self.expression is None:
            return self.value  # type: ignore[return-value]
        return {"expression": str(self.expression)}

    def cache_key(self) -> str:
        if self.expression is None:
            return f"i:{self.value}"
        return f"i:({self.expression})"


#: A value that resolves to a single quantity.
ScalarValue = Union[QuantityValue, ExpressionValue]


@dataclass(frozen=True, slots=True)
class PointListValue:
    """A list of points: the corners of a sketched outline, the turns of a
    path. ``{"points": [[0, 0], [40, 0, 5], [40, "h"]], "unit": "mm"}``.

    Each point is two or three coordinates -- a 2D sketch point, optionally
    with a third entry, the radius its corner is rounded to; a 3D path point
    -- and each coordinate may be a number or an expression. Which form a
    feature takes is the feature's to check: the value only carries them.
    """

    points: tuple[tuple["ScalarValue", ...], ...]

    def resolve_lengths(self, resolution: Resolution | None = None,
                        *, unit: str = "mm") -> tuple[tuple[float, ...], ...]:
        target = parse_unit(unit)
        out: list[tuple[float, ...]] = []
        for point in self.points:
            row: list[float] = []
            for component in point:
                value = component.resolve(resolution)
                if value.is_dimensionless:
                    row.append(float(value.magnitude.midpoint))
                else:
                    row.append(float(value.to(target).magnitude.midpoint))
            out.append(tuple(row))
        return tuple(out)

    def free_names(self) -> frozenset[str]:
        names: set[str] = set()
        for point in self.points:
            for component in point:
                names |= component.free_names()
        return frozenset(names)

    def as_json(self) -> dict[str, Any]:
        return {"points": [[c.as_json() for c in point]
                           for point in self.points], "unit": "mm"}

    def cache_key(self) -> str:
        return "p:[" + ";".join(",".join(c.cache_key() for c in point)
                                for point in self.points) + "]"


#: Any feature parameter value.
IRValue = Union[
    QuantityValue, ExpressionValue, VectorValue, EnumValue, FlagValue,
    CountValue, PointListValue,
]


# ----------------------------------------------------------------------
# Decoding
# ----------------------------------------------------------------------
def decode_scalar(reader: Reader, *, allow_bare_number: bool = False) -> ScalarValue:
    """Decode a value that must resolve to a quantity.

    ``allow_bare_number`` permits a plain JSON number, interpreted as
    dimensionless. It is off by default: a bare number where a length belongs is
    the single most common way a unit goes missing, and the decoder's job is to
    make that impossible rather than convenient.
    """
    value = reader.value

    if isinstance(value, bool):
        raise TypeMismatchError(
            "expected a quantity, got a boolean", pointer=reader.pointer
        )

    if isinstance(value, (int, float)):
        if not allow_bare_number:
            # An integer here is almost always a count -- a bolt count, a
            # number of ribs -- and telling it to write `"unit": "mm"` is
            # advice it will rightly refuse to take. Observed live: a
            # `bolt_count` of 4 was rejected three times while the hint
            # proposed four millimetres of bolts. A count still takes the
            # object form in a component parameter; what it needs is the
            # empty unit, and nothing said so.
            counts = isinstance(value, int) and not isinstance(value, bool)
            hint = 'write {"magnitude": %r, "unit": "mm"}' % value
            if counts:
                hint += (
                    ' -- or {"magnitude": %r, "unit": ""} if it is a pure '
                    "count with no dimension" % value
                )
            hint += ". A bare number is never a component parameter's value."
            raise ValueError_(
                "a dimensional parameter must carry a unit",
                pointer=reader.pointer,
                got=value,
                hint=hint,
            )
        return QuantityValue(Quantity(Interval.exact(float(value)), parse_unit("")))

    if isinstance(value, str):
        # A bare string in a scalar position is an expression shorthand, which
        # keeps hand-authored documents readable: "ear_gap / 2" instead of the
        # full object form.
        try:
            return ExpressionValue(
                Expression.parse(value), unit=None, pointer=reader.pointer
            )
        except ForgeExprError as exc:
            raise ValueError_(
                f"invalid expression: {exc.message}",
                pointer=reader.pointer,
                source=value,
                cause=exc.code,
            ) from exc

    if isinstance(value, Mapping):
        if "expression" in value:
            reader.reject_unknown(["expression", "unit"])
            source = reader.require("expression").as_str()
            unit_reader = reader.optional("unit")
            unit = _unit_of(unit_reader) if unit_reader else None
            try:
                expression = Expression.parse(source)
            except ForgeExprError as exc:
                raise ValueError_(
                    f"invalid expression: {exc.message}",
                    pointer=reader.pointer,
                    source=source,
                    cause=exc.code,
                ) from exc
            return ExpressionValue(expression, unit=unit, pointer=reader.pointer)

        if "magnitude" in value or "interval" in value:
            reader.reject_unknown(["magnitude", "unit", "interval"])
            magnitude = value.get("magnitude")
            if isinstance(magnitude, str) and _a_written_number(magnitude):
                # `{"magnitude": "3", "unit": "mm"}` -- a number, quoted. An
                # analyst's patch wrote exactly that into a blend radius; read
                # as an expression it was a dimensionless 3 in a millimetre
                # slot, and the run died in the compiler. A magnitude is a
                # number in the unit beside it, so this one is 3 mm.
                value = {**value, "magnitude": float(magnitude)}
                magnitude = value["magnitude"]
            if isinstance(magnitude, str) and magnitude.strip():
                # `{"magnitude": "fillet_thickness", "unit": "mm"}` -- the name
                # of a parameter where the number goes. The model is saying
                # "this value comes from that parameter", which is exactly what
                # an expression is; only the spelling is wrong, and one spelling
                # of an unambiguous intention is not worth a repair round on a
                # model that takes half an hour to answer.
                unit_reader = reader.optional("unit")
                unit = _unit_of(unit_reader) if unit_reader else None
                try:
                    return ExpressionValue(
                        Expression.parse(magnitude),
                        unit=unit,
                        pointer=reader.pointer,
                    )
                except ForgeExprError as exc:
                    raise ValueError_(
                        "a magnitude must be a number, and this is not one, "
                        f"nor a usable expression: {exc.message}",
                        pointer=reader.pointer,
                        got=magnitude,
                        cause=exc.code,
                        hint='write {"magnitude": 12.0, "unit": "mm"} for a '
                        'number, or {"expression": "plate_thickness / 2", '
                        '"unit": "mm"} to compute it from other parameters.',
                    ) from exc
            try:
                return QuantityValue(Quantity.from_dict(value))
            except ForgeUnitsError as exc:
                raise ValueError_(
                    exc.message, pointer=reader.pointer, cause=exc.code
                ) from exc
            except Exception as exc:  # noqa: BLE001 - as `_unit_of` does
                # Whatever a unit or a number can raise three layers down --
                # an overflow, a recursion limit -- is this slot's fault, said
                # at this slot's pointer, never an internal error upstream.
                raise ValueError_(
                    f"not a usable quantity: {exc}"[:300],
                    pointer=reader.pointer,
                ) from exc

        if "vector" in value:
            # Not a formatting slip, so the generic message leaves the model
            # with no legal move and it re-emits the same thing. Observed live:
            # a `load_direction` parameter holding [0, 0, -1] N was rejected
            # three times over ten minutes each, because "use magnitude/unit"
            # cannot express a direction and nothing said where one belongs.
            raise ValueError_(
                "a parameter holds one number; a direction is not a parameter",
                pointer=reader.pointer,
                keys=sorted(value.keys()),
                hint="drop this parameter. A load and the direction it acts "
                'in are an assumption -- record them as ASM_DESIGN_LOAD with '
                'the magnitude and a statement naming the direction. Geometry '
                'takes its direction from the feature: `axis` on the hole or '
                "extrude that reacts the load.",
            )

        raise ValueError_(
            "object is not a recognised quantity or expression",
            pointer=reader.pointer,
            keys=sorted(value.keys()),
            hint='use {"magnitude": .., "unit": ..} or {"expression": ".."} -- '
            "you wrote " + ", ".join(sorted(value.keys())),
        )

    raise TypeMismatchError(
        "expected a quantity, an expression, or a number",
        pointer=reader.pointer,
        got=type(value).__name__,
    )


def _vector_length_error(reader: Reader, items: Sequence[Any]) -> ValueRangeError:
    """Three components, and the message shows which three.

    "a vector must have exactly three components (got_length: 2)" states the
    rule and leaves the author to guess which axis went missing. It is always
    the same guess -- the components are x, y, z in that order, so a pattern
    spacing written `[10, 0]` means `[10, 0, 0]` -- and writing it out costs
    nothing while a repair round on a local model costs a quarter of an hour.

    Observed live: `"spacing": {"vector": [10, 0], "unit": "mm"}` on a linear
    pattern, refused three times.
    """
    raw = [
        item.value if hasattr(item, "value") else item for item in items
    ]
    detail: dict[str, Any] = {"got_length": len(raw), "got": raw}
    if len(raw) < 3:
        padded = list(raw) + [0] * (3 - len(raw))
        detail["hint"] = (
            "the components are x, y, z in that order, so an axis you do not "
            f"use is 0, not absent: write {json.dumps(padded)}."
        )
    else:
        detail["hint"] = (
            "a vector is three components -- x, y, z. Drop the extras, or if "
            "this was meant to be several vectors, each one is its own "
            "parameter."
        )
    return ValueRangeError(
        "a vector must have exactly three components",
        pointer=reader.pointer,
        **detail,
    )


def _unit_of(unit_reader: Reader) -> Any:
    """The unit a field names, or a schema error at its pointer -- never a
    units error from three layers down, which nothing above the decoder
    catches: `{"magnitude": 5, "unit": "zz"}` in an analyst's patch took a
    run down as an internal error."""
    text = unit_reader.as_str()
    try:
        return parse_unit(text)
    except Exception as exc:  # noqa: BLE001 - every unit fault is this one
        raise ValueError_(
            f"`{text}` is not a unit",
            pointer=unit_reader.pointer,
            hint='write "mm" for a length, "deg" for an angle, or "" for a '
                 "pure number",
        ) from exc


def decode_vector(reader: Reader) -> VectorValue:
    value = reader.value

    if isinstance(value, list):
        items = reader.as_list()
        if len(items) != 3:
            raise _vector_length_error(reader, items)
        return VectorValue(
            tuple(  # type: ignore[arg-type]
                decode_scalar(item, allow_bare_number=True) for item in items
            )
        )

    if isinstance(value, Mapping):
        if "expression" in value and "vector" not in value:
            # Wanting this parametric is right; an expression just cannot stand
            # for a whole vector. It goes inside one, per element. Observed on
            # a `spacing` the model tried to drive from a bolt pitch.
            raise ValueError_(
                "an expression cannot stand for a whole vector",
                pointer=reader.pointer,
                keys=sorted(value.keys()),
                hint='put the expression in the component you mean: {"vector": '
                '["bolt_pitch", 0, 0], "unit": "mm"}. Each element may be a '
                "number or an expression string.",
            )
        if "magnitude" in value and "vector" not in value:
            # A scalar quantity where a vector belongs. The generic
            # unknown-field message lists `normalise, unit, vector` as the
            # allowed names, which is true and tells the model nothing about
            # what shape to write. Observed live on a `spacing` of 10 mm.
            raise ValueError_(
                "this parameter is a vector, not a single magnitude",
                pointer=reader.pointer,
                keys=sorted(value.keys()),
                hint='write {"vector": [x, y, z], "unit": ".."} -- three '
                "components giving the direction and distance, not one number",
            )
        reader.reject_unknown(["vector", "unit", "normalise"])
        inner = reader.require("vector").as_list()
        if len(inner) != 3:
            raise _vector_length_error(reader, inner)
        unit_reader = reader.optional("unit")
        unit = _unit_of(unit_reader) if unit_reader else None
        components: list[ScalarValue] = []
        for item in inner:
            if isinstance(item.value, (int, float)) and not isinstance(
                item.value, bool
            ):
                magnitude = Interval.exact(float(item.value))
                components.append(
                    QuantityValue(
                        Quantity(magnitude, unit if unit else parse_unit(""))
                    )
                )
            else:
                components.append(decode_scalar(item, allow_bare_number=True))
        return VectorValue(
            tuple(components),  # type: ignore[arg-type]
            normalise=reader.optional_bool("normalise", False),
        )

    raise TypeMismatchError(
        "expected a vector as an array of three components or an object with a "
        "'vector' field",
        pointer=reader.pointer,
        got=type(value).__name__,
    )


def decode_points(reader: Reader) -> PointListValue:
    """A list of points, as ``{"points": [[u, v], ...], "unit": "mm"}`` or
    the bare list. Each point has two to four coordinates; a bare number
    takes the list's unit, millimetres when it names none."""
    value = reader.value
    if isinstance(value, Mapping):
        reader.reject_unknown(["points", "unit"])
        rows = reader.require("points").as_list()
        unit_reader = reader.optional("unit")
        unit = _unit_of(unit_reader) if unit_reader else parse_unit("mm")
    elif isinstance(value, list):
        rows = reader.as_list()
        unit = parse_unit("mm")
    else:
        raise TypeMismatchError(
            'expected a list of points: {"points": [[0, 0], [40, 0], [40, 20]], '
            '"unit": "mm"}',
            pointer=reader.pointer, got=type(value).__name__)
    if len(rows) < 2:
        raise ValueRangeError(
            "a list of points needs at least two of them",
            pointer=reader.pointer, got_length=len(rows))
    points: list[tuple[ScalarValue, ...]] = []
    for row in rows:
        items = row.as_list()
        if not 2 <= len(items) <= 4:
            raise ValueRangeError(
                "each point is two coordinates (a sketch: u, v, and optionally "
                "the radius its corner is rounded to) or three (a path: x, y, "
                "z)", pointer=row.pointer, got_length=len(items))
        coordinates: list[ScalarValue] = []
        for item in items:
            if isinstance(item.value, (int, float)) and not isinstance(
                    item.value, bool):
                coordinates.append(QuantityValue(
                    Quantity(Interval.exact(float(item.value)), unit)))
            else:
                coordinates.append(decode_scalar(item, allow_bare_number=True))
        points.append(tuple(coordinates))
    return PointListValue(tuple(points))


def decode_value(reader: Reader, *, allow_bare_number: bool = False) -> IRValue:
    """Decode any feature-parameter value, dispatching on its JSON shape."""
    value = reader.value
    if isinstance(value, bool):
        return FlagValue(value)
    if isinstance(value, int) and not isinstance(value, bool):
        # An integer in a generic position is a count; a dimensional integer
        # must use the explicit quantity form.
        return CountValue(value)
    if isinstance(value, list):
        return decode_vector(reader)
    if isinstance(value, Mapping) and "vector" in value:
        return decode_vector(reader)
    if isinstance(value, Mapping) and "points" in value:
        return decode_points(reader)
    if isinstance(value, str) and _looks_like_enum(value):
        return EnumValue(value)
    return decode_scalar(reader, allow_bare_number=allow_bare_number)


def _looks_like_enum(text: str) -> bool:
    """Distinguish an option name from an expression shorthand.

    A bare identifier that is also a plausible option ("symmetric", "blind") is
    ambiguous with a parameter reference. The rule is deliberately narrow: only
    strings that are pure lower-case identifiers with no operators are treated
    as enum options, and feature schemas that expect an option declare it, so
    the ambiguity never actually reaches this function in practice.
    """
    if not text or any(char in text for char in "+-*/^()., "):
        return False
    return text.islower() and text.replace("_", "").isalnum()


def value_free_names(value: IRValue) -> frozenset[str]:
    return value.free_names()


def encode_value(value: IRValue) -> Any:
    return value.as_json()


__all__ = [
    "QuantityValue",
    "ExpressionValue",
    "VectorValue",
    "EnumValue",
    "FlagValue",
    "CountValue",
    "PointListValue",
    "ScalarValue",
    "IRValue",
    "decode_scalar",
    "decode_vector",
    "decode_points",
    "decode_value",
    "encode_value",
    "value_free_names",
]


def _a_written_number(text: str) -> bool:
    """A plain decimal number written as text: "3", "-2.5", "1e3"."""
    import math as _math

    try:
        number = float(text.strip())
    except ValueError:
        return False
    return _math.isfinite(number)
