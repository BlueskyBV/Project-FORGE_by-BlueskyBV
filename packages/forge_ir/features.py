"""The feature graph: typed, acyclic, semantically tagged construction history.

A component is not a list of CAD commands. It is a directed acyclic graph of
typed feature nodes, each declaring its inputs, its parameters, and -- crucially
-- the *named geometry it produces*. That last part is what distinguishes
ForgeIR from a script: a hole does not merely remove material, it publishes a
``bore`` cylindrical surface that a mate, a load, a mesh group or a fit
tolerance can refer to by name, for as long as the hole exists.

Why a graph rather than a list
------------------------------
A linear timeline forces a total order on operations that are genuinely
independent. Two holes on opposite ends of a bracket do not depend on each
other, and pretending they do costs the incremental compiler dearly: changing
one would invalidate everything after it in the list. In a graph, changing one
dirties only its own cone, and independent subtrees can be compiled in parallel.

Semantic outputs, not topological indices
-----------------------------------------
Every feature declares the roles it emits. ``FeatureSpec.emits`` is a *static*
declaration -- known before any geometry is built -- which is what lets the
compiler verify that a reference like ``pivot_bore.axis`` will resolve, and
report a precise error when it will not, without running the CAD kernel.

This is the foundation the lineage system in :mod:`forge_kernel` builds on, and
together they are Forge's answer to the topological naming problem. See
ADR-0003.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Mapping, Sequence

from forge_units import detail_besides

from .schema import (
    DanglingReferenceError,
    Reader,
    SchemaError,
    SchemaErrorGroup,
    ValueRangeError,
    join_pointer,
    require_unique_ids,
)
from .values import IRValue, decode_scalar, decode_value, decode_vector

#: What a feature produces. The compiler uses this to check that, for example,
#: an extrude is given a profile and a boolean is given solids.
ProductKind = Literal["solid", "profile", "datum_plane", "datum_axis", "datum_point"]

#: The sort of a feature parameter, checked at decode time by JSON shape and at
#: compile time by dimension.
ParameterSort = Literal[
    "length",
    "angle",
    "count",
    "flag",
    "enum",
    "vector",
    "direction",
    "displacement",
    "dimensionless",
    "points",
]


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """Declaration of one feature parameter."""

    name: str
    sort: ParameterSort
    required: bool = True
    options: tuple[str, ...] = ()
    description: str = ""
    minimum: float | None = None

    @property
    def expects_quantity(self) -> bool:
        return self.sort in ("length", "angle", "dimensionless")


@dataclass(frozen=True, slots=True)
class SemanticOutput:
    """A named piece of geometry a feature publishes.

    ``suffix`` is appended to the feature's ``role`` to form the reference name,
    so a hole whose role is ``pivot`` publishes ``pivot.bore``, ``pivot.axis``
    and ``pivot.entry``.
    """

    suffix: str
    entity_type: Literal[
        "planar_face", "cylindrical_face", "conical_face", "spherical_face",
        "swept_face",
        "axis", "point", "frame", "volume", "edge_loop",
    ]
    description: str = ""
    optional: bool = False


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """The static contract of one feature kind."""

    kind: str
    produces: ProductKind
    inputs: tuple[ProductKind, ...] = ()
    variadic_input: ProductKind | None = None
    minimum_inputs: int = 0
    parameters: tuple[ParameterSpec, ...] = ()
    emits: tuple[SemanticOutput, ...] = ()
    summary: str = ""
    #: Backends that cannot represent this feature must say so rather than
    #: approximating it silently. Listed here for documentation; enforcement
    #: lives in each backend's capability table.
    notes: str = ""

    def __post_init__(self) -> None:
        """Catch the one-element-tuple trap at import time.

        ``parameters=(_p("distance", "length"))`` is a parenthesised expression,
        not a tuple, and Python will not complain. The spec then silently holds a
        single ``ParameterSpec`` where a sequence belongs, every iteration over
        it fails, and the feature appears to have no parameters at all until
        something tries to use it.

        This is exactly the kind of defect that hides until a rarely used feature
        is first exercised, so it is checked here rather than trusted to review.
        """
        for field_name, expected in (
            ("parameters", ParameterSpec),
            ("emits", SemanticOutput),
        ):
            value = getattr(self, field_name)
            if isinstance(value, expected):
                raise TypeError(
                    f"FeatureSpec({self.kind!r}).{field_name} is a single "
                    f"{expected.__name__} rather than a tuple of them - a "
                    "missing trailing comma in the declaration"
                )
        if isinstance(self.inputs, str):
            raise TypeError(
                f"FeatureSpec({self.kind!r}).inputs is a string rather than a "
                "tuple of product kinds - a missing trailing comma"
            )

    def parameter(self, name: str) -> ParameterSpec | None:
        for spec in self.parameters:
            if spec.name == name:
                return spec
        return None

    def parameter_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.parameters)

    def required_parameter_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.parameters if spec.required)


# ----------------------------------------------------------------------
# The feature catalogue
# ----------------------------------------------------------------------
def _p(
    name: str,
    sort: ParameterSort,
    *,
    required: bool = True,
    options: Sequence[str] = (),
    description: str = "",
    minimum: float | None = None,
) -> ParameterSpec:
    return ParameterSpec(
        name=name,
        sort=sort,
        required=required,
        options=tuple(options),
        description=description,
        minimum=minimum,
    )


def _o(suffix: str, entity_type: str, description: str = "", optional: bool = False) -> SemanticOutput:
    return SemanticOutput(suffix, entity_type, description, optional)  # type: ignore[arg-type]


_CATALOGUE: tuple[FeatureSpec, ...] = (
    # -- datums --------------------------------------------------------
    FeatureSpec(
        kind="datum_plane",
        produces="datum_plane",
        parameters=(
            _p("base", "enum", options=("XY", "YZ", "XZ"),
               description="Standard plane this datum is offset from"),
            _p("offset", "length", required=False,
               description="The coordinate the plane sits at along the axis "
                           "it is not in: z for XY, x for YZ, y for XZ -- XZ "
                           "offset -40 is the plane y = -40. Its normal, the "
                           "way a `normal` extrude runs, is +Z for XY, +X "
                           "for YZ and -Y for XZ (`reverse` runs the other "
                           "way, `symmetric` both)"),
        ),
        emits=(_o("frame", "frame", "Origin and orientation of the plane"),),
        summary="A construction plane offset from a standard plane.",
    ),
    FeatureSpec(
        kind="datum_axis",
        produces="datum_axis",
        parameters=(
            _p("origin", "displacement", description="A point on the axis"),
            _p("direction", "direction", description="Axis direction"),
        ),
        emits=(_o("axis", "axis"),),
        summary="A construction axis defined by a point and a direction.",
    ),
    FeatureSpec(
        kind="datum_point",
        produces="datum_point",
        parameters=(_p("position", "displacement"),),
        emits=(_o("point", "point"),),
        summary="A construction point.",
    ),
    # -- profiles ------------------------------------------------------
    FeatureSpec(
        kind="profile_rectangle",
        produces="profile",
        inputs=("datum_plane",),
        parameters=(
            _p("width", "length", description="Extent along the plane's u axis"),
            _p("height", "length", description="Extent along the plane's v axis"),
            _p("center_u", "length", required=False),
            _p("center_v", "length", required=False),
            _p("corner_radius", "length", required=False,
               description="Rounds all four corners; must be under half the "
                           "shorter side"),
            _p("corner_chamfer", "length", required=False,
               description="Cuts all four corners at 45 degrees, this far "
                           "back along each side"),
        ),
        emits=(_o("region", "volume", "The enclosed 2D region"),),
        summary="A rectangular profile, optionally with rounded or chamfered "
                "corners.",
    ),
    FeatureSpec(
        kind="profile_sketch",
        produces="profile",
        inputs=("datum_plane",),
        parameters=(
            _p("points", "points",
               description="The outline's corners in order round it, in the "
                           "plane's own u, v: [[0, 0], [60, 0], [60, 20], "
                           "[20, 20], [20, 50], [0, 50]] is an L. A third "
                           "entry rounds that corner: [60, 0, 5]. Any shape "
                           "a flat outline can be -- a lever, a hook, a cam, "
                           "a gusset, a bracket's side"),
            _p("corner_radius", "length", required=False,
               description="Rounds every corner without its own radius"),
            _p("smooth", "flag", required=False,
               description="Pass a smooth curve through the points instead "
                           "of straight sides: an organic outline, an "
                           "ellipse from a few points round it"),
        ),
        emits=(_o("region", "volume", "The enclosed 2D region"),),
        summary="Any closed outline drawn through points: extrude it for a "
                "flat part of any shape, revolve it for any turned part.",
    ),
    FeatureSpec(
        kind="profile_gear",
        produces="profile",
        inputs=("datum_plane",),
        parameters=(
            _p("module", "length",
               description="Tooth size: pitch diameter / teeth. Meshing gears "
                           "share a module"),
            _p("teeth", "count"),
            _p("pressure_angle", "angle", required=False,
               description="Default 20 deg"),
            _p("center_u", "length", required=False),
            _p("center_v", "length", required=False),
            _p("rotation", "angle", required=False),
        ),
        emits=(_o("region", "volume"),),
        summary="A spur gear's outline, involute teeth: extrude it for a spur "
                "gear (pitch diameter = module x teeth, outside diameter = "
                "module x (teeth + 2)); cut the bore with a `hole`.",
    ),
    FeatureSpec(
        kind="profile_circle",
        produces="profile",
        inputs=("datum_plane",),
        parameters=(
            _p("diameter", "length"),
            _p("center_u", "length", required=False),
            _p("center_v", "length", required=False),
        ),
        emits=(_o("region", "volume"),),
        summary="A circular profile.",
    ),
    FeatureSpec(
        kind="profile_polygon",
        produces="profile",
        inputs=("datum_plane",),
        parameters=(
            _p("circumscribed_diameter", "length"),
            _p("sides", "count"),
            _p("rotation", "angle", required=False),
            _p("center_u", "length", required=False),
            _p("center_v", "length", required=False),
            _p("corner_radius", "length", required=False, minimum=0.0,
               description="Rounds each corner to this radius, the sides "
                           "staying where they are: a rounded triangular "
                           "cutout. Not `end_radius` on its extrude -- that "
                           "rounds the edges round the extrusion's end "
                           "faces, not the polygon's corners"),
        ),
        emits=(_o("region", "volume"),),
        summary="A regular polygon profile.",
    ),
    FeatureSpec(
        kind="profile_slot",
        produces="profile",
        inputs=("datum_plane",),
        parameters=(
            _p("length", "length", description="Centre-to-centre plus the width"),
            _p("width", "length"),
            _p("center_u", "length", required=False),
            _p("center_v", "length", required=False),
            _p("rotation", "angle", required=False),
        ),
        emits=(_o("region", "volume"),),
        summary="An obround slot profile.",
    ),
    # -- solids from profiles -------------------------------------------
    FeatureSpec(
        kind="extrude",
        produces="solid",
        inputs=("profile",),
        parameters=(
            _p("distance", "length", minimum=0.0),
            _p("mode", "enum", required=False,
               options=("normal", "reverse", "symmetric"),
               description="Direction relative to the profile plane normal"),
            _p("end_radius", "length", required=False, minimum=0.0,
               description="Rounds the edges round its end faces -- a plate's "
                           "top and bottom edges, a disc's rims"),
            _p("end_chamfer", "length", required=False, minimum=0.0,
               description="Chamfers those edges at 45 degrees instead"),
            _p("ends", "enum", required=False,
               options=("both", "start", "end"),
               description="Which end faces' edges `end_radius` or "
                           "`end_chamfer` applies to; default both"),
            _p("draft_angle", "angle", required=False,
               description="Tapers the sides inward towards the far end by "
                           "this angle -- a moulding draft, a tapered boss"),
        ),
        emits=(
            _o("start_face", "planar_face", "Face on the profile plane"),
            _o("end_face", "planar_face", "Face at the far end of the extrusion"),
            _o("side", "swept_face", "The swept lateral surface"),
            _o("body", "volume"),
        ),
        summary="Sweep a profile normal to its plane.",
    ),
    FeatureSpec(
        kind="revolve",
        produces="solid",
        inputs=("profile", "datum_axis"),
        parameters=(_p("angle", "angle"),),
        emits=(_o("body", "volume"), _o("axis", "axis")),
        summary="Revolve a profile about an axis.",
        notes="The implicit backend supports full revolutions exactly and "
              "partial revolutions by intersection with a wedge.",
    ),
    # -- primitives -----------------------------------------------------
    FeatureSpec(
        kind="box",
        produces="solid",
        parameters=(
            _p("size", "displacement",
               description="Extents along x, y, z IN THAT ORDER. Z is up, so "
                           "a flat plate's thickness is the THIRD entry: a "
                           "30 mm square plate 4 mm thick is [30, 30, 4]. "
                           "[30, 4, 30] is the same plate stood on its edge, "
                           "and it builds and measures cleanly, so nothing "
                           "downstream will tell you"),
            _p("origin", "displacement", required=False,
               description="Position of the minimum corner, or of the centre "
                           "when 'centered' is set"),
            _p("centered", "flag", required=False),
            _p("edge_radius", "length", required=False, minimum=0.0,
               description="Rounds its edges to this radius -- which edges, "
                           "`edges` says"),
            _p("edge_chamfer", "length", required=False, minimum=0.0,
               description="Chamfers its edges at 45 degrees instead"),
            _p("edges", "enum", required=False,
               options=("all", "vertical", "top", "bottom", "top_and_bottom",
                        "along_x", "along_y", "bottom_along_x",
                        "top_along_x", "bottom_along_y", "top_along_y",
                        "vertical_x_min", "vertical_x_max",
                        "vertical_y_min", "vertical_y_max"),
               description="Which edges are rounded or chamfered: all 12 "
                           "(default), the 4 vertical ones, round the top "
                           "or bottom face, or the 4 running along x (or y) "
                           "-- `along_x` with a radius of half the y side "
                           "rounds both ends of an upright tab or link fully "
                           "round, the way a pivot needs; `bottom_along_x` "
                           "only its bottom end, `top_along_x` only its top "
                           "(bottom and top are z). A tab lying flat has its "
                           "ends in plan: `vertical_y_max` rounds only the 2 "
                           "upright edges of its y_max face -- with a radius "
                           "of half the x side, a lug reaching out along +y "
                           "ends in a semicircle and keeps its root square"),
        ),
        emits=(
            _o("x_min", "planar_face"), _o("x_max", "planar_face"),
            _o("y_min", "planar_face"), _o("y_max", "planar_face"),
            _o("z_min", "planar_face"), _o("z_max", "planar_face"),
            _o("body", "volume"),
        ),
        summary="An axis-aligned rectangular prism.",
    ),
    FeatureSpec(
        kind="cylinder",
        produces="solid",
        parameters=(
            _p("diameter", "length", minimum=0.0),
            _p("height", "length", minimum=0.0),
            _p("origin", "displacement", required=False,
               description="Centre of the base face (the base, not the "
               "cylinder's centre)"),
            _p("axis", "direction", required=False),
        ),
        emits=(
            _o("lateral", "cylindrical_face"),
            _o("base", "planar_face"),
            _o("top", "planar_face"),
            _o("axis", "axis"),
            _o("body", "volume"),
        ),
        summary="A right circular cylinder.",
    ),
    FeatureSpec(
        kind="sphere",
        produces="solid",
        parameters=(
            _p("diameter", "length", minimum=0.0),
            _p("origin", "displacement", required=False),
        ),
        emits=(_o("surface", "spherical_face"), _o("body", "volume")),
        summary="A sphere.",
    ),
    FeatureSpec(
        kind="cone",
        produces="solid",
        parameters=(
            _p("bottom_diameter", "length", minimum=0.0,
               description="Diameter at the base, at `origin`"),
            _p("top_diameter", "length", minimum=0.0,
               description="Diameter at the top, `height` along `axis`; 0 "
                           "for a pointed cone"),
            _p("height", "length", minimum=0.0),
            _p("origin", "displacement", required=False,
               description="Centre of the base (the base, not the middle)"),
            _p("axis", "direction", required=False),
        ),
        emits=(
            _o("lateral", "conical_face"),
            _o("base", "planar_face"),
            _o("top", "planar_face", optional=True),
            _o("axis", "axis"),
            _o("body", "volume"),
        ),
        summary="A cone, or a frustum: round, tapering straight from one "
                "diameter to another -- a taper, a countersink cutter, a "
                "funnel, a nozzle.",
    ),
    FeatureSpec(
        kind="torus",
        produces="solid",
        parameters=(
            _p("diameter", "length", minimum=0.0,
               description="Across the ring, to the middle of its tube"),
            _p("tube_diameter", "length", minimum=0.0,
               description="The thickness of the ring's round tube"),
            _p("origin", "displacement", required=False,
               description="Centre of the ring"),
            _p("axis", "direction", required=False),
        ),
        emits=(_o("axis", "axis"), _o("body", "volume")),
        summary="A ring with a round section: an O-ring, a doughnut, a "
                "handle loop.",
    ),
    FeatureSpec(
        kind="wedge",
        produces="solid",
        parameters=(
            _p("size", "displacement",
               description="Extents along x, y, z, as for a box: z is its "
                           "height at the tall end"),
            _p("origin", "displacement", required=False,
               description="Position of the minimum corner, or of the "
                           "centre when 'centered' is set"),
            _p("centered", "flag", required=False),
            _p("slope", "enum", required=False,
               options=("+x", "-x", "+y", "-y"),
               description="The way its top slopes down to nothing: '+x' "
                           "(the default) is full height at its low-x end "
                           "and zero at its high-x end"),
        ),
        emits=(
            _o("base", "planar_face"),
            _o("back", "planar_face", "The full-height end"),
            _o("slope", "planar_face", "The sloping top"),
            _o("body", "volume"),
        ),
        summary="A right-angled wedge: a ramp, a gusset, a triangular rib "
                "-- a box with its top sloping from full height to nothing.",
    ),
    FeatureSpec(
        kind="sweep",
        produces="solid",
        inputs=("profile",),
        parameters=(
            _p("path", "points",
               description="The path's points in order, in x, y, z: [[0, 0, "
                           "0], [80, 0, 0], [80, 0, 40]]. The profile is "
                           "carried along it, square to it, its u along the "
                           "path's first turn"),
            _p("bend_radius", "length", required=False, minimum=0.0,
               description="Bends the path's corners round to this radius, "
                           "as a bar or a tube is bent"),
        ),
        emits=(_o("side", "swept_face"), _o("body", "volume")),
        summary="A profile carried along a path: a handle, a rail, a bent "
                "bar of any section, a channel, a wire form.",
    ),
    FeatureSpec(
        kind="pipe",
        produces="solid",
        parameters=(
            _p("diameter", "length", minimum=0.0),
            _p("path", "points",
               description="The centre line's points, in x, y, z"),
            _p("inner_diameter", "length", required=False, minimum=0.0,
               description="Hollow, to this bore; omit for a solid round bar"),
            _p("bend_radius", "length", required=False, minimum=0.0,
               description="Bends the corners round to this radius"),
        ),
        emits=(_o("surface", "swept_face"), _o("body", "volume")),
        summary="A round bar or tube along a path, cut square at its ends: a "
                "grab handle, a hook, a frame of tube, a wire.",
    ),
    FeatureSpec(
        kind="coil",
        produces="solid",
        parameters=(
            _p("diameter", "length", minimum=0.0,
               description="Across the coil, to the middle of the wire"),
            _p("wire_diameter", "length", minimum=0.0),
            _p("pitch", "length", minimum=0.0,
               description="How far it advances along its axis per turn"),
            _p("turns", "dimensionless"),
            _p("origin", "displacement", required=False,
               description="Centre of its first turn"),
            _p("axis", "direction", required=False),
        ),
        emits=(_o("surface", "swept_face"), _o("body", "volume")),
        summary="A helix of round wire: a spring, a coil.",
    ),
    FeatureSpec(
        kind="loft",
        produces="solid",
        inputs=("profile", "profile"),
        parameters=(),
        emits=(_o("side", "swept_face"), _o("body", "volume")),
        summary="A solid passing smoothly from one profile to another on a "
                "parallel plane: a square-to-round transition, a tapered "
                "neck, a nozzle of any section.",
        notes="Both profiles' planes must be parallel and apart; the loft "
              "runs between them.",
    ),
    # -- booleans -------------------------------------------------------
    FeatureSpec(
        kind="union",
        produces="solid",
        variadic_input="solid",
        minimum_inputs=2,
        parameters=(
            _p("blend_radius", "length", required=False, minimum=0.0,
               description="Fillet radius applied at the junction of the "
                           "operands"),
            _p("chamfer", "length", required=False, minimum=0.0,
               description="A 45 degree chamfer in the junction instead"),
        ),
        emits=(_o("body", "volume"), _o("blend", "volume", optional=True)),
        summary="Combine solids, optionally with a blended (filleted) junction.",
        notes="A blended union is how the implicit backend represents a fillet "
              "at a joint. The blend is created by the boolean rather than "
              "applied afterwards, which is both exact for implicit geometry "
              "and closer to the design intent than selecting edges by index.",
    ),
    FeatureSpec(
        kind="subtract",
        produces="solid",
        variadic_input="solid",
        minimum_inputs=2,
        parameters=(
            _p("blend_radius", "length", required=False, minimum=0.0,
               description="Fillet radius applied where material is removed"),
            _p("chamfer", "length", required=False, minimum=0.0,
               description="A 45 degree chamfer on the cut's edges instead"),
        ),
        emits=(_o("body", "volume"),),
        summary="Remove every later operand from the first.",
    ),
    FeatureSpec(
        kind="intersect",
        produces="solid",
        variadic_input="solid",
        minimum_inputs=2,
        parameters=(
            _p("blend_radius", "length", required=False, minimum=0.0),
            _p("chamfer", "length", required=False, minimum=0.0),
        ),
        emits=(_o("body", "volume"),),
        summary="Keep only material common to every operand.",
    ),
    # -- modifiers ------------------------------------------------------
    FeatureSpec(
        kind="hole",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p("diameter", "length", minimum=0.0),
            _p("position", "displacement",
               description="A point the axis passes through, and it must be "
                           "INSIDE the material. Not where the hole should "
                           "appear on the surface: a 4 mm hole through the "
                           "wall of a 25 mm round body goes at x=0 on the "
                           "centre line, NOT at x=12.5 on the skin, which "
                           "runs the axis along the outside and cuts a "
                           "scratch. Moving it ALONG the axis moves the hole "
                           "nowhere, so a pattern of holes is spread ACROSS "
                           "the axis: down [0,0,1], vary x and y; down "
                           "[1,0,0], vary y and z. Two holes that differ only "
                           "along their shared axis are one hole, and the "
                           "second cuts air"),
            _p("axis", "direction", required=False,
               description="The drilling direction, default [0,0,1]. A hole "
                           "through a flat plate runs down the plate's "
                           "THICKNESS -- for a plate lying flat that is "
                           "[0,0,1]. Drilled across the plate's width instead "
                           "it is still open, still passes every gate, and is "
                           "still not the hole that was asked for. A hole "
                           "through the WALL of a round body is the other "
                           "case and the opposite answer: it runs ACROSS the "
                           "body, not along it, so its axis is [1,0,0] while "
                           "the bore's is [0,0,1]. Two such holes an angle "
                           "apart differ ONLY in this field -- both sit on "
                           "the centre line, and the angle between them is "
                           "the angle between their axes"),
            _p("depth", "length", required=False,
               description="Omit for a through hole, which is cut in BOTH "
                           "directions from `position`. With a depth the cut "
                           "runs from `position` along `axis` only: a set "
                           "screw on a round body's centre line with depth "
                           "= the body's diameter opens one wall into the "
                           "bore, not both"),
            _p("through", "enum", required=False,
               options=("all", "first_wall"),
               description="`first_wall` drills from `position` along "
                           "`axis` through the first wall it meets and "
                           "stops past it, however thick or curved that wall "
                           "is: a hole through ONE wall of a hollow part, "
                           "with `position` anywhere inside the hollow and "
                           "`axis` pointing at that wall; or, from a "
                           "`position` inside a wall, through that whole "
                           "wall -- the way two holes down one line go "
                           "through two separate walls, a clevis's ears, "
                           "each placed in its own. No `depth` with it"),
            _p("counterbore_diameter", "length", required=False,
               description="A wider, flat-bottomed recess at the hole's "
                           "entry for a bolt head; give its depth too"),
            _p("counterbore_depth", "length", required=False),
            _p("countersink_diameter", "length", required=False,
               description="A cone at the entry for a flat-head screw, this "
                           "wide at the surface"),
            _p("countersink_angle", "angle", required=False,
               description="The countersink's included angle, default 90 "
                           "deg"),
            _p("entry", "enum", required=False, options=("start", "end"),
               description="Which side the counterbore or countersink is "
                           "on: `start` (default) where the axis enters the "
                           "material, `end` where it leaves"),
            _p("thread", "enum", required=False,
               options=("none", "M2", "M2.5", "M3", "M4", "M5", "M6", "M8", "M10", "M12"),
               description="Cosmetic thread metadata; no thread geometry is cut"),
            _p("fit", "enum", required=False,
               options=("clearance_close", "clearance_normal", "clearance_loose",
                        "transition", "interference"),
               description="Intended fit class, carried into tolerance analysis"),
        ),
        emits=(
            _o("bore", "cylindrical_face", "The cylindrical bore surface"),
            _o("axis", "axis", "The hole axis"),
            _o("entry", "planar_face", "Annular face where the hole enters",
               optional=True),
            _o("body", "volume"),
        ),
        summary="A cylindrical hole with fit and fastener metadata.",
        notes="A hole is a distinct feature rather than a subtracted cylinder "
              "because the bore and axis it publishes are what mates, bearing "
              "loads, mesh refinement and fit tolerances attach to. "
              "CUT HOLES LAST. A hole only removes material from the solid you "
              "give it, and anything unioned on afterwards fills the bore back "
              "in: drill the post, then union the post to its base plate, and "
              "the plate seals the bottom of the hole. Build the whole body "
              "first and give the finished body to the hole, so `hole` is the "
              "last feature in the graph.",
    ),
    FeatureSpec(
        kind="shell",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p("thickness", "length", minimum=0.0),
            _p("direction", "enum", required=False,
               options=("inward", "outward", "both")),
        ),
        emits=(_o("body", "volume"), _o("inner", "volume")),
        summary="Hollow a solid to a uniform wall thickness, keeping every "
        "face: a SEALED hollow. For a box open at the top -- or on any one "
        "face -- subtract an inner box that runs out through that face "
        "instead.",
    ),
    FeatureSpec(
        kind="offset",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p(
                "distance",
                "length",
                description="Positive grows the solid, negative shrinks it",
            ),
        ),
        emits=(_o("body", "volume"),),
        summary="Grow or shrink a solid by a uniform distance.",
    ),
    # -- arrays and transforms ------------------------------------------
    FeatureSpec(
        kind="pattern_linear",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p("count", "count"),
            _p("spacing", "displacement"),
            _p("symmetric", "flag", required=False),
        ),
        emits=(_o("body", "volume"),),
        summary="Repeat a solid along a direction.",
        notes=(
            "A pattern repeats a *solid*, so patterning a body that already has a hole in it gives you several bodies, not several holes. To repeat a cut: make the cutting shape as its own primitive, pattern that, and `subtract` the result from the body. Four bolt holes are a `cylinder`, a `pattern_linear` of 2 across, another of 2 along, and one `subtract`."
        ),
    ),
    FeatureSpec(
        kind="pattern_circular",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p("count", "count"),
            _p("axis_origin", "displacement"),
            _p("axis_direction", "direction"),
            _p("step_angle", "angle", required=False,
               description="The angle BETWEEN NEIGHBOURS. Two set screws 90 "
                           "degrees apart is count 2 and step_angle 90 deg; "
                           "three bolts 120 degrees apart is count 3 and "
                           "step_angle 120 deg. This is the number a brief "
                           "states, so write it here rather than doing "
                           "arithmetic into `total_angle`"),
            _p("total_angle", "angle", required=False,
               description="The span from the first copy to the LAST, for an "
                           "arc stated end to end. Omit both angles for copies "
                           "spread evenly around the full circle. Give one or "
                           "the other, never both"),
        ),
        emits=(_o("body", "volume"),),
        summary="Repeat a solid about an axis.",
        notes=(
            "As with `pattern_linear`: this repeats a solid. To repeat a cut, "
            "pattern the cutting primitive and `subtract` the result. "
            "This is how an angle stated in a brief becomes geometry. Two set "
            "screws 90 degrees apart around a collar is the set-screw "
            "`cylinder`, a `pattern_circular` of `count` 2 and `step_angle` "
            "90 deg about the collar's own axis, and one `subtract` -- and "
            "then a requirement bound to the parameter driving `step_angle` "
            "measures the part. An angle is never a position: degrees in a "
            "millimetre vector is a dimension error, and two holes placed by "
            "millimetres alone sit wherever the arithmetic put them."
        ),
    ),
    FeatureSpec(
        kind="mirror",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p("plane_origin", "displacement", required=False),
            _p("plane_normal", "direction"),
            _p("keep_original", "flag", required=False),
        ),
        emits=(_o("body", "volume"),),
        summary="Mirror a solid across a plane.",
    ),
    FeatureSpec(
        kind="transform",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p("translate", "displacement", required=False),
            _p("rotate_axis", "direction", required=False),
            _p("rotate_angle", "angle", required=False),
            _p("rotate_origin", "displacement", required=False),
        ),
        emits=(_o("body", "volume"),),
        summary="Rigidly move a solid.",
    ),
    FeatureSpec(
        kind="bend",
        produces="solid",
        inputs=("solid",),
        parameters=(
            _p("angle", "angle",
               description="How far the solid turns, more than 0 and less "
               "than 180 degrees"),
            _p("position", "displacement",
               description="A point on the middle of the bend: where the "
               "curve is centred along the solid"),
            _p("along", "direction",
               description="The way the plate RUNS THROUGH the bend, square "
               "to the crease -- not the crease's own direction: a plate long "
               "in y folded up at y = 50 has `along` [0, 1, 0] and its crease "
               "runs along x"),
            _p("toward", "direction",
               description="The side the solid bends towards, off its face, "
               "e.g. [0, 0, 1] to curl up"),
            _p("radius", "length", required=False, minimum=0.0,
               description="Inside radius of the bend. Small for a fold, "
               "large for a gentle curve"),
            _p("bend_length", "length", required=False, minimum=0.0,
               description="Instead of `radius`: how much of the solid's "
               "length, along its middle, the curve is spread over -- its "
               "whole length for a smooth arc end to end"),
            _p("hold", "enum", required=False, options=("start", "middle"),
               description="What stays where it was: `start` (the default) "
               "the solid before the bend, `middle` the middle of the bend "
               "-- a curve centred on a plate then rises or falls evenly "
               "both ways"),
        ),
        emits=(_o("body", "volume"),),
        summary="Bend a solid through an angle, as sheet metal is bent: a "
        "fold, a gentle curve, or an arc along its whole length.",
        notes="Build the part flat first -- the plate, its holes and cuts -- "
        "and bend the finished flat body last; holes drilled before the bend "
        "stay square to the surface and keep their spacing along it. The "
        "solid keeps its length along its middle, so a plate 70 mm long is "
        "70 mm long along the plate after bending. Several bend points are "
        "several `bend` features, each taking the one before as its input. "
        "Give `radius` or `bend_length`, not both; with neither, the inside "
        "radius is the solid's thickness. Each leg's outside then reaches "
        "past its flat length from `position` by (radius + thickness) less "
        "half the curve: a part the brief sizes by its OUTSIDE legs -- an "
        "L-bracket 50 long and 40 tall -- is boxes joined by a `union`, or an "
        "L sketched and extruded, exact to the brief.",
    ),
)

FEATURE_SPECS: Mapping[str, FeatureSpec] = {spec.kind: spec for spec in _CATALOGUE}

FEATURE_KINDS: tuple[str, ...] = tuple(sorted(FEATURE_SPECS))


def feature_spec(kind: str) -> FeatureSpec:
    spec = FEATURE_SPECS.get(kind)
    if spec is None:
        raise ValueRangeError(
            "unknown feature kind",
            got=kind,
            allowed=list(FEATURE_KINDS),
        )
    return spec


# ----------------------------------------------------------------------
# Feature nodes
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Feature:
    """One node of the feature graph."""

    identifier: str
    kind: str
    inputs: tuple[str, ...] = ()
    parameters: Mapping[str, IRValue] = field(default_factory=dict)
    role: str = ""
    tags: tuple[str, ...] = ()
    description: str = ""
    pointer: str = ""

    @property
    def spec(self) -> FeatureSpec:
        return feature_spec(self.kind)

    @property
    def produces(self) -> ProductKind:
        return self.spec.produces

    def semantic_names(self) -> tuple[str, ...]:
        """Fully-qualified names of the geometry this feature publishes."""
        prefix = self.role or self.identifier
        return tuple(f"{prefix}.{output.suffix}" for output in self.spec.emits)

    def free_names(self) -> frozenset[str]:
        names: set[str] = set()
        for value in self.parameters.values():
            names |= value.free_names()
        return frozenset(names)

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.identifier, "kind": self.kind}
        if self.inputs:
            payload["inputs"] = list(self.inputs)
        if self.parameters:
            payload["parameters"] = {
                name: value.as_json()
                for name, value in sorted(self.parameters.items())
            }
        if self.role:
            payload["role"] = self.role
        if self.tags:
            payload["tags"] = list(self.tags)
        if self.description:
            payload["description"] = self.description
        return payload


_FEATURE_FIELDS = ("id", "kind", "inputs", "parameters", "role", "tags", "description")


def decode_feature(reader: Reader) -> Feature:
    reader.reject_unknown(_FEATURE_FIELDS)
    identifier = reader.require("id").as_identifier()
    kind = reader.require("kind").as_str()
    try:
        spec = feature_spec(kind)
    except ValueRangeError as exc:
        raise ValueRangeError(
            exc.message,
            pointer=join_pointer(reader.pointer, "kind"),
            **detail_besides(exc.detail, "pointer"),
        ) from None

    inputs_reader = reader.optional("inputs")
    inputs = tuple(inputs_reader.as_str_list()) if inputs_reader else ()

    expected_inputs = len(spec.inputs)
    if spec.variadic_input is not None:
        if len(inputs) < spec.minimum_inputs:
            # "too few inputs, minimum 2, got 1" was sent three times to a
            # `subtract` of a cube with nothing to cut it with, and answered
            # identically three times: a count is a diagnosis. Say what the
            # second input is.
            hint = {
                "subtract": (
                    "a `subtract` takes the body first and then the solid to "
                    "cut out of it: `inputs: [body, cutter]`. The cutter is "
                    "its own primitive -- a `box`, a `cylinder`, a `sphere` "
                    "-- declared before the subtract with no `inputs` of its "
                    "own. To hollow a box, or open one of its faces, the "
                    "cutter is a box the size of the space inside, running "
                    "out through the open face."),
                "union": (
                    "a `union` joins two or more solids: `inputs: [first, "
                    "second, ...]`. One solid needs no union -- use it "
                    "directly."),
                "intersect": (
                    "an `intersect` keeps what two or more solids share: "
                    "`inputs: [first, second, ...]`."),
            }.get(kind)
            raise ValueRangeError(
                "feature has too few inputs",
                pointer=join_pointer(reader.pointer, "inputs"),
                kind=kind,
                minimum=spec.minimum_inputs,
                got=len(inputs),
                **({"hint": hint} if hint else {}),
            )
    elif len(inputs) != expected_inputs:
        detail: dict[str, Any] = {}
        if expected_inputs == 0 and spec.produces == "solid":
            # The commonest shape of this mistake: a primitive given something
            # to consume, because the author wants to add or remove material
            # with it. Observed live on two `cylinder` features in one document.
            # The primitive is right; what is missing is the boolean.
            detail["hint"] = (
                f"a `{kind}` makes a solid out of nothing and takes no "
                "`inputs`. To add it to another solid or cut it away, keep it "
                "input-free and add a `union` or `subtract` feature whose "
                f"`inputs` are [the other solid, \"{identifier}\"]. For a round "
                "hole, prefer the `hole` feature -- it publishes the bore and "
                "axis that fits and loads attach to."
            )
        elif not inputs and spec.inputs == ("datum_plane",):
            # A profile is drawn *on* a plane, and the plane is a feature of its
            # own. Nothing about `profile_rectangle` says "first declare where
            # to draw it", so a model reaching for the familiar sketch-then-
            # extrude workflow stops one feature short and cannot see why.
            #
            # Observed live, twice in one run, on a part that wanted no profile
            # at all: a 60 x 40 x 6 plate is a `box`.
            plane_id = f"{identifier}_plane"
            detail["hint"] = (
                f"a `{kind}` is drawn on a plane, and the plane is a feature. "
                "Add one before it and give this feature its id: "
                f'{{"id": "{plane_id}", "kind": "datum_plane", "parameters": '
                '{"base": "XY"}}, then '
                f'{{"id": "{identifier}", "kind": "{kind}", "inputs": '
                f'["{plane_id}"], ...}}. '
                "Before you do: a plain rectangular plate is a `box` and a "
                "round disc or post is a `cylinder` -- neither needs a profile "
                "or a plane. Profiles and `extrude` earn their cost on shapes a "
                "primitive cannot make: an L-section, a slot-ended arm, a "
                "polygon."
            )
        raise ValueRangeError(
            "feature has the wrong number of inputs",
            pointer=join_pointer(reader.pointer, "inputs"),
            kind=kind,
            expected=expected_inputs,
            expected_kinds=list(spec.inputs),
            got=len(inputs),
            **detail,
        )

    parameters = _decode_parameters(reader, spec)

    return Feature(
        identifier=identifier,
        kind=kind,
        inputs=inputs,
        parameters=parameters,
        role=reader.optional_str("role", ""),
        tags=reader.optional_str_tuple("tags"),
        description=reader.optional_str("description", ""),
        pointer=reader.pointer,
    )


def _decode_parameters(reader: Reader, spec: FeatureSpec) -> Mapping[str, IRValue]:
    parameters_reader = reader.optional("parameters")
    raw: Mapping[str, Any] = (
        parameters_reader.as_object() if parameters_reader else {}
    )
    base_pointer = (
        parameters_reader.pointer
        if parameters_reader
        else join_pointer(reader.pointer, "parameters")
    )

    known = set(spec.parameter_names())
    unknown = sorted(name for name in raw if name not in known)
    errors: list[SchemaError] = []
    if unknown:
        errors.append(
            ValueRangeError(
                "unknown parameter(s) for this feature kind",
                pointer=base_pointer,
                kind=spec.kind,
                unknown=unknown,
                allowed=sorted(known),
            )
        )

    decoded: dict[str, IRValue] = {}
    for parameter_spec in spec.parameters:
        name = parameter_spec.name
        if name not in raw:
            if parameter_spec.required:
                errors.append(
                    ValueRangeError(
                        "required parameter is absent",
                        pointer=join_pointer(base_pointer, name),
                        kind=spec.kind,
                        parameter=name,
                        sort=parameter_spec.sort,
                        description=parameter_spec.description,
                    )
                )
            continue
        child = Reader(raw[name], join_pointer(base_pointer, name))
        try:
            decoded[name] = _decode_one_parameter(child, parameter_spec)
        except SchemaErrorGroup as group:
            errors.extend(group.errors)
        except SchemaError as error:
            errors.append(error)

    if errors:
        raise SchemaErrorGroup(errors)
    return decoded


#: No pattern anyone makes repeats a solid more often than this. A count of
#: a thousand million was accepted, and the pattern's field looped over it
#: for ever: the compiler hung where it should have refused.
MAX_COUNT = 10_000


def _decode_count(reader: Reader) -> IRValue:
    """A literal whole number, or an expression that resolves to one."""
    from forge_expr import Expression, ForgeExprError

    from .values import CountValue, ValueError_

    value = reader.value
    source: str | None = None
    if isinstance(value, Mapping) and "magnitude" in value:
        # `{"magnitude": 4, "unit": ""}` -- the form every component parameter
        # takes, written in the one feature position that is documented as
        # bare. It is accepted, because it determines the answer exactly: four,
        # dimensionless, whole. Nothing is guessed and nothing is rounded.
        #
        # This is not leniency for its own sake. Observed live: a design with
        # the correct feature graph -- two primitives, a union, a hole, a bolt
        # pattern -- was rejected over this one spelling, and what came back
        # after the repair round was worse. A decoder that can compute the
        # value exactly and refuses to, on a point of style, is spending the
        # author's time to make itself feel strict.
        #
        # Ambiguity is still refused below: a dimensional count, a fractional
        # one, or one that is a range means something the author has to decide.
        reader.reject_unknown(["magnitude", "unit"])
        magnitude = reader.require("magnitude").as_float()
        unit_reader = reader.optional("unit")
        unit = unit_reader.as_str().strip() if unit_reader is not None else ""
        if unit not in ("", "1"):
            raise ValueError_(
                "a count carries no unit",
                pointer=reader.pointer,
                got=unit,
                hint='a number of things is dimensionless. Write it bare -- 4 '
                '-- or as {"magnitude": 4, "unit": ""}.',
            )
        nearest = round(magnitude)
        if abs(magnitude - nearest) > 1e-9:
            raise ValueError_(
                "a count must be a whole number",
                pointer=reader.pointer,
                got=magnitude,
                hint="there is no such thing as a fractional instance.",
            )
        if nearest < 1:
            raise ValueError_(
                "a count must be at least 1",
                pointer=reader.pointer,
                got=nearest,
            )
        if nearest > MAX_COUNT:
            raise ValueError_(
                "a count is beyond anything a pattern can be",
                pointer=reader.pointer,
                got=nearest,
                limit=MAX_COUNT,
            )
        return CountValue(int(nearest))
    if isinstance(value, Mapping):
        # `unit` is accepted and ignored. A count is dimensionless, so the only
        # unit that could be meant is the empty one -- and every model that
        # writes an expression here writes `"unit": ""` beside it out of habit,
        # because that is what every other expression takes. Refusing the
        # habit teaches nothing and costs a repair round.
        reader.reject_unknown(["expression", "unit"])
        source = reader.require("expression").as_str()
        unit_reader = reader.optional("unit")
        if unit_reader is not None and unit_reader.as_str().strip() not in ("", "1"):
            raise ValueError_(
                "a count carries no unit",
                pointer=reader.pointer,
                got=unit_reader.as_str(),
                hint='drop the unit, or write "" -- a number of things is '
                "dimensionless",
            )
    elif isinstance(value, str):
        # The shorthand a scalar already accepts. Refusing it here would be an
        # inconsistency the author has no way to predict.
        source = value
    if source is None:
        return CountValue(reader.as_int(minimum=1, maximum=MAX_COUNT))
    try:
        return CountValue(expression=Expression.parse(source), pointer=reader.pointer)
    except ForgeExprError as exc:
        raise ValueError_(
            f"invalid expression: {exc.message}",
            pointer=reader.pointer,
            source=source,
            cause=exc.code,
        ) from exc


def _decode_one_parameter(reader: Reader, spec: ParameterSpec) -> IRValue:
    from .values import CountValue, EnumValue, FlagValue

    if spec.sort == "count":
        return _decode_count(reader)
    if spec.sort == "flag":
        return FlagValue(reader.as_bool())
    if spec.sort == "enum":
        return EnumValue(reader.as_str(allowed=spec.options))
    if spec.sort in ("vector", "direction", "displacement"):
        return decode_vector(reader)
    if spec.sort == "points":
        from .values import decode_points

        return decode_points(reader)
    # length, angle, dimensionless
    return decode_scalar(reader, allow_bare_number=spec.sort == "dimensionless")


# ----------------------------------------------------------------------
# The graph
# ----------------------------------------------------------------------
class FeatureGraph:
    """An acyclic graph of features with a deterministic evaluation order."""

    __slots__ = ("_features", "_order", "_pointer")

    def __init__(self, features: Sequence[Feature], *, pointer: str = "") -> None:
        self._pointer = pointer
        self._features: dict[str, Feature] = {}
        for feature in features:
            if feature.identifier in self._features:
                raise ValueRangeError(
                    "duplicate feature identifier",
                    pointer=feature.pointer,
                    identifier=feature.identifier,
                )
            self._features[feature.identifier] = feature
        self._validate_references()
        self._order = self._topological_order()

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._features)

    def __contains__(self, identifier: str) -> bool:
        return identifier in self._features

    def __getitem__(self, identifier: str) -> Feature:
        try:
            return self._features[identifier]
        except KeyError:
            raise DanglingReferenceError(
                "no such feature",
                pointer=self._pointer,
                identifier=identifier,
                available=sorted(self._features)[:40],
            ) from None

    def __iter__(self) -> Iterator[Feature]:
        """Iterate in dependency order."""
        return (self._features[identifier] for identifier in self._order)

    @property
    def order(self) -> tuple[str, ...]:
        return self._order

    def features(self) -> tuple[Feature, ...]:
        return tuple(self._features[identifier] for identifier in self._order)

    def identifiers(self) -> tuple[str, ...]:
        return tuple(sorted(self._features))

    def terminal_features(self) -> tuple[Feature, ...]:
        """Features no other feature consumes.

        A well-formed component has exactly one terminal solid: its body. More
        than one means the author left an orphan, which is reported rather than
        guessed at, because picking 'the last one' would silently discard work.
        """
        consumed = {
            source
            for feature in self._features.values()
            for source in feature.inputs
        }
        return tuple(
            self._features[identifier]
            for identifier in self._order
            if identifier not in consumed
        )

    def _has_a_starting_solid(self) -> bool:
        """Whether anything here makes a solid without consuming one first."""
        return any(
            not feature.inputs and feature.spec.produces == "solid"
            for feature in self._features.values()
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate_references(self) -> None:
        errors: list[SchemaError] = []
        for feature in self._features.values():
            spec = feature.spec
            for index, source_id in enumerate(feature.inputs):
                source = self._features.get(source_id)
                if source is None:
                    detail: dict[str, Any] = {}
                    if not self._has_a_starting_solid():
                        # Every feature here consumes something and nothing
                        # creates anything: the part has no base to cut into.
                        # Observed live, twice: a `hole` and a `pattern_linear`
                        # both taking a `body` that was never authored. Listing
                        # the available ids is true but unhelpful when the real
                        # answer is that the first feature is missing.
                        detail["hint"] = (
                            "no feature in this component creates a solid from "
                            "nothing, so there is nothing to cut into. Begin "
                            "with a `box` or `cylinder` that has no `inputs`, "
                            f"give it `\"id\": \"{source_id}\"`, and let the "
                            "rest consume it."
                        )
                    errors.append(
                        DanglingReferenceError(
                            "feature input refers to an unknown feature",
                            pointer=join_pointer(
                                join_pointer(feature.pointer, "inputs"), index
                            ),
                            feature=feature.identifier,
                            missing=source_id,
                            available=sorted(self._features)[:40],
                            **detail,
                        )
                    )
                    continue
                expected = (
                    spec.variadic_input
                    if spec.variadic_input is not None
                    else (spec.inputs[index] if index < len(spec.inputs) else None)
                )
                if expected is not None and source.produces != expected:
                    errors.append(
                        ValueRangeError(
                            "feature input has the wrong product kind",
                            pointer=join_pointer(
                                join_pointer(feature.pointer, "inputs"), index
                            ),
                            feature=feature.identifier,
                            input=source_id,
                            expected=expected,
                            got=source.produces,
                        )
                    )
        errors.extend(self._booleans_that_undo_themselves())
        errors.extend(self._names_that_collide())
        errors.extend(self._holes_that_are_the_same_hole())
        if errors:
            raise SchemaErrorGroup(errors)

    def _holes_that_are_the_same_hole(self) -> list[SchemaError]:
        """Two holes drilled down the same line are one hole.

        A hole is a line, not a point: its `position` fixes where the axis
        passes, and moving the position ALONG that axis moves it nowhere. So
        two holes sharing an axis and differing only in the component parallel
        to it describe the same cut, and the second one removes material the
        first already removed.

        Observed live, and it cost a whole run::

            bore            position [0,          0, post_height/2]  axis [1,0,0]
            mounting_hole_1 position [spacing/2,  0, post_height/2]  axis [1,0,0]
            mounting_hole_2 position [-spacing/2, 0, post_height/2]  axis [1,0,0]

        The spacing was applied along x, which is the drilling direction, so
        all three are the line y=0, z=post_height/2. The 5 mm bore cut its
        channel and both 3 mm mounting holes then cut inside it, contributing
        nothing. `GEOM_BORES_SURVIVE` and `GEOM_FEATURES_CONTRIBUTE` both
        failed -- correctly, but only after compiling and measuring a part
        that could have been refused in milliseconds, with the reason.

        Compared as written rather than evaluated, because a parameter scope
        is not available here. That direction is the safe one: two expressions
        that merely happen to be equal are not reported, and everything
        reported is genuinely identical.
        """

        def written(value: Any) -> str:
            return json.dumps(value.as_json(), sort_keys=True) if value else ""

        def components(value: Any) -> list[str]:
            payload = value.as_json() if value else {}
            vector = payload.get("vector") if isinstance(payload, Mapping) else None
            if not isinstance(vector, list) or len(vector) != 3:
                return []
            return [json.dumps(entry, sort_keys=True) for entry in vector]

        def only_axis(value: Any) -> int:
            """Which single axis this vector points down, or -1."""
            entries = value.as_json().get("vector") if value else None
            if not isinstance(entries, list) or len(entries) != 3:
                return -1
            nonzero = [
                index
                for index, entry in enumerate(entries)
                if not (
                    isinstance(entry, Mapping)
                    and entry.get("magnitude") in (0, 0.0)
                )
            ]
            return nonzero[0] if len(nonzero) == 1 else -1

        lines: dict[tuple[Any, ...], list[Feature]] = {}
        for feature in self._features.values():
            if feature.kind != "hole":
                continue
            axis = feature.parameters.get("axis")
            position = feature.parameters.get("position")
            along = only_axis(axis)
            place = components(position)
            if along < 0 or not place:
                # A diagonal axis, or a position Forge cannot read as a
                # vector. Saying nothing is correct: the check only claims
                # what it can prove.
                continue
            across = tuple(
                entry for index, entry in enumerate(place) if index != along
            )
            lines.setdefault((written(axis), across), []).append(feature)

        errors: list[SchemaError] = []
        for _, holes in lines.items():
            if len(holes) < 2:
                continue
            # A blind hole of one size over a hole of another is a stepped
            # hole -- a 10 mm recess 4 mm deep over a 5.5 mm hole is a
            # counterbore drawn by hand -- and each cuts what the other does
            # not. Refused as "the same hole", four corner counterbores could
            # not be drawn that way at all. Through holes on one line, of any
            # sizes, still are one hole: the widest takes it all.
            sizes = {written(h.parameters.get("diameter")) for h in holes}
            if len(sizes) == len(holes) and any(
                    h.parameters.get("depth") for h in holes):
                continue
            # Holes through the first wall each meets, started from
            # different points along their line, cut different walls -- a
            # partition's and the shell's, or the near wall from inside and
            # the far one from beyond it.
            starts = {json.dumps(components(h.parameters.get("position")),
                                 sort_keys=True) for h in holes}
            if len(starts) == len(holes) and any(
                    str(getattr(h.parameters.get("through"), "option",
                                h.parameters.get("through")) or "")
                    == "first_wall" for h in holes):
                continue
            names = [hole.identifier for hole in holes]
            errors.append(
                ValueRangeError(
                    "these holes are all the same hole",
                    pointer=join_pointer(holes[1].pointer, "parameters"),
                    features=names,
                    hint=(
                        f"{', '.join(names)} share an axis and differ only in "
                        "the direction they are drilled, so they are one line "
                        "through the part. A hole's `position` says where its "
                        "axis passes; sliding it along that axis changes "
                        "nothing. Whichever is cut first takes the material "
                        "and the rest cut air. Offset them ACROSS the axis "
                        "instead: a hole drilled down `[0, 0, 1]` is spread "
                        "over x and y, one down `[1, 0, 0]` over y and z. If "
                        "the spacing is meant to lie along the axis, then the "
                        "axis is the wrong one -- a hole through a flat plate "
                        "runs down the plate's thickness."
                    ),
                )
            )
        return errors

    def _names_that_collide(self) -> list[SchemaError]:
        """Two features publishing the same geometry names.

        A feature's `role` is the handle its geometry is addressed by: a hole
        with `"role": "shaft"` publishes `shaft.bore` and `shaft.axis`. Give
        two features the same role and they publish the same names, the
        geometry map keeps one of them, and the other's bore, axis and entry
        face simply do not exist as far as anything downstream is concerned.

        Observed live: three holes, all with `"role": "shaft"`. One bore
        survived in the map. Every check that resolves geometry by name --
        interfaces, entity measurements, the burial report, the part's own fact
        sheet -- was describing one hole and calling it three.

        Silent, because nothing was wrong with any feature on its own.
        """
        published: dict[str, list[str]] = {}
        for feature in self._features.values():
            for name in feature.semantic_names():
                published.setdefault(name, []).append(feature.identifier)

        errors: list[SchemaError] = []
        seen: set[tuple[str, ...]] = set()
        for name, owners in sorted(published.items()):
            if len(owners) < 2:
                continue
            key = tuple(sorted(owners))
            if key in seen:
                continue  # one error per colliding group, not one per name
            seen.add(key)
            feature = self._features[owners[0]]
            errors.append(
                ValueRangeError(
                    "two features publish the same geometry names",
                    pointer=feature.pointer,
                    features=list(key),
                    role=feature.role or feature.identifier,
                    example=name,
                    hint=(
                        f"{', '.join(key)} all publish `{name}`, because they "
                        f"share the role `{feature.role or feature.identifier}`. "
                        "Geometry is addressed by these names, so only one of "
                        "them exists downstream and the others are invisible to "
                        "every interface, measurement and check. Delete `role` "
                        "from each of them: the feature's `id` is used instead, "
                        "and those are unique already. Do NOT rename the roles "
                        "-- a role is the name its geometry is published under, "
                        "so renaming one silently breaks every interface and "
                        "measurement that refers to the old name."
                    ),
                )
            )
        return errors

    def _booleans_that_undo_themselves(self) -> list[SchemaError]:
        """A boolean whose operands are all the same solid with bits missing.

        Three `hole` features each take the finished body and hand back a copy
        with one hole in it. Union those three copies and every hole is filled
        in again, because each copy still has the material the other two
        removed. The result is the original body, and it compiles, measures and
        meshes perfectly.

        Observed live, and it is the reason a run reported PASS on a part with
        no holes in it at all::

            {"id": "body_2", "kind": "union",
             "inputs": ["hole", "mounting_hole_1", "mounting_hole_2"]}

        Detectable without building anything: the operands share an ancestor,
        so each carries the whole of it. The fix is a chain -- each hole cuts
        the result of the one before -- and the terminal feature is the last
        hole, not a union of them.
        """
        errors: list[SchemaError] = []
        for feature in self._features.values():
            if feature.kind not in ("union", "intersect") or len(feature.inputs) < 2:
                continue
            shared = None
            for source_id in feature.inputs:
                lineage = self._ancestors(source_id) | {source_id}
                shared = lineage if shared is None else (shared & lineage)
                if not shared:
                    break
            # Only a shared *solid* carries material into every operand. Two
            # slot cutters sketched on one datum plane share the plane, and
            # a plane has no material to restore: their union is one cutter
            # with both slots in it -- on Claude, refused as if it were three
            # holes unioned back into the plate.
            shared = {
                name for name in (shared or ())
                if name in self._features
                and getattr(FEATURE_SPECS.get(self._features[name].kind),
                            "produces", None) == "solid"
            }
            if not shared:
                continue
            common = sorted(shared)[0]
            errors.append(
                ValueRangeError(
                    "a boolean whose operands are all the same solid undoes "
                    "the work done to them",
                    pointer=join_pointer(feature.pointer, "inputs"),
                    feature=feature.identifier,
                    kind=feature.kind,
                    inputs=list(feature.inputs),
                    common_ancestor=common,
                    hint=(
                        f"every input to `{feature.identifier}` is built from "
                        f"`{common}`, so each one carries the whole of it. "
                        f"A `{feature.kind}` of them restores whatever the "
                        "others removed -- three holes unioned together is a "
                        "body with no holes. Chain them instead: give each "
                        "feature the id of the previous one as its input "
                        f"({' -> '.join(feature.inputs)}), and let the last "
                        f"one be the part. Delete `{feature.identifier}`."
                    ),
                )
            )
        return errors

    def _ancestors(self, identifier: str) -> set[str]:
        """Every feature this one is built from, transitively."""
        seen: set[str] = set()
        stack = list(self._features[identifier].inputs) if identifier in self._features else []
        while stack:
            current = stack.pop()
            if current in seen or current not in self._features:
                continue
            seen.add(current)
            stack.extend(self._features[current].inputs)
        return seen

    def _topological_order(self) -> tuple[str, ...]:
        """Dependency order with alphabetical tie-breaking.

        Deterministic ordering is not a nicety here: the order participates in
        the compiler's cache key, so a nondeterministic sort would produce a
        different key for an identical document and defeat caching entirely.
        """
        white, grey, black = 0, 1, 2
        colour = {identifier: white for identifier in self._features}
        order: list[str] = []
        for root in sorted(self._features):
            if colour[root] != white:
                continue
            stack: list[tuple[str, Iterator[str]]] = [
                (root, iter(sorted(self._features[root].inputs)))
            ]
            colour[root] = grey
            path = [root]
            while stack:
                node, dependencies = stack[-1]
                advanced = False
                for dependency in dependencies:
                    state = colour[dependency]
                    if state == grey:
                        start = path.index(dependency)
                        cycle = path[start:] + [dependency]
                        raise ValueRangeError(
                            "feature graph contains a cycle",
                            pointer=self._pointer,
                            cycle=cycle,
                            rendered=" -> ".join(cycle),
                        )
                    if state == white:
                        colour[dependency] = grey
                        path.append(dependency)
                        stack.append(
                            (
                                dependency,
                                iter(sorted(self._features[dependency].inputs)),
                            )
                        )
                        advanced = True
                        break
                if advanced:
                    continue
                stack.pop()
                colour[node] = black
                order.append(node)
                if path and path[-1] == node:
                    path.pop()
        return tuple(order)

    # ------------------------------------------------------------------
    # Impact analysis
    # ------------------------------------------------------------------
    def dependents_of(self, identifier: str) -> frozenset[str]:
        """Every feature downstream of ``identifier``, transitively.

        This is the dirty cone the incremental compiler must rebuild when a
        feature changes, and the set of evidence the UI must mark stale.
        """
        if identifier not in self._features:
            raise DanglingReferenceError(
                "no such feature", identifier=identifier, pointer=self._pointer
            )
        reverse: dict[str, set[str]] = {name: set() for name in self._features}
        for name, feature in self._features.items():
            for source in feature.inputs:
                if source in reverse:
                    reverse[source].add(name)
        seen: set[str] = set()
        frontier = [identifier]
        while frontier:
            current = frontier.pop()
            for dependent in reverse.get(current, ()):
                if dependent not in seen:
                    seen.add(dependent)
                    frontier.append(dependent)
        return frozenset(seen)

    def ancestors_of(self, identifier: str) -> frozenset[str]:
        """Every feature ``identifier`` depends on, transitively."""
        seen: set[str] = set()
        frontier = list(self[identifier].inputs)
        while frontier:
            current = frontier.pop()
            if current in seen or current not in self._features:
                continue
            seen.add(current)
            frontier.extend(self._features[current].inputs)
        return frozenset(seen)

    def free_names(self) -> frozenset[str]:
        names: set[str] = set()
        for feature in self._features.values():
            names |= feature.free_names()
        return frozenset(names)

    def semantic_names(self) -> Mapping[str, str]:
        """Map every published semantic name to the feature that publishes it."""
        mapping: dict[str, str] = {}
        for feature in self.features():
            for name in feature.semantic_names():
                mapping[name] = feature.identifier
        return mapping

    def as_json(self) -> list[dict[str, Any]]:
        return [feature.as_json() for feature in self.features()]


def decode_feature_graph(reader: Reader) -> FeatureGraph:
    features = reader.decode_list(decode_feature)
    require_unique_ids(
        [feature.identifier for feature in features],
        pointer=reader.pointer,
        kind="feature",
    )
    return FeatureGraph(features, pointer=reader.pointer)


__all__ = [
    "Feature",
    "FeatureGraph",
    "FeatureSpec",
    "ParameterSpec",
    "SemanticOutput",
    "ProductKind",
    "ParameterSort",
    "FEATURE_SPECS",
    "FEATURE_KINDS",
    "feature_spec",
    "decode_feature",
    "decode_feature_graph",
]
