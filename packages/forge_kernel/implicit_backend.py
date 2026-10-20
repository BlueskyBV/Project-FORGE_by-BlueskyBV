"""The implicit geometry backend: ForgeIR features to signed distance fields.

One builder per feature kind. Each receives the feature's *resolved* parameters
(units already applied, expressions already evaluated, everything in
millimetres and radians) together with its already-compiled inputs, and returns
a product plus the semantic entities that feature publishes.

The entities are the important half. A cylinder does not merely produce a
distance field; it publishes ``<role>.lateral``, ``<role>.base``, ``<role>.top``
and ``<role>.axis`` as analytically described geometry with lineage tokens. That
is what a mate, a bearing load, a mesh refinement region or a fit tolerance
attaches to, and it is why those references survive a parameter change.

Adding a feature kind means adding a builder here and a spec in
:mod:`forge_ir.features`. A backend that cannot build a kind declares it absent
rather than approximating it, so an unsupported feature produces a ``BLOCKED``
result naming what is missing instead of a plausible wrong solid.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from forge_geom import (
    Bend,
    SDF,
    Box,
    BoxSDF,
    CircleProfile,
    ConeSDF,
    CylinderSDF,
    DegenerateGeometryError,
    Difference,
    ExtrusionSDF,
    GeometryError,
    HalfSpaceSDF,
    Intersection,
    Mirror,
    Offset,
    PolygonProfile,
    RectangleProfile,
    Repeat,
    Revolve,
    Shell,
    GearProfile,
    SketchProfile,
    SlotProfile,
    SphereSDF,
    SweepSDF,
    TorusSDF,
    Transform,
    TubeSDF,
    LoftSDF,
    stack_lofts,
    Union,
    gear_outline,
    helix_points,
    round_the_path,
    sketch_outline,
)

from .lineage import Frame, SemanticEntity, lineage_token
from .products import (
    DatumAxisProduct,
    DatumPlaneProduct,
    DatumPointProduct,
    Product,
    ProfileProduct,
    SolidProduct,
)

BACKEND_IDENTITY = "implicit-sdf/0.1.0"

#: Standard planes, as (origin, u axis, v axis, normal).
_STANDARD_PLANES: Mapping[str, tuple[tuple[float, ...], ...]] = {
    "XY": ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "YZ": ((0, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 0)),
    "XZ": ((0, 0, 0), (1, 0, 0), (0, 0, 1), (0, -1, 0)),
}


class BackendError(GeometryError):
    """The backend cannot build this feature as specified."""

    code = "KN1100_BACKEND"


class UnsupportedFeatureError(BackendError):
    """The backend has no builder for this feature kind."""

    code = "KN1101_UNSUPPORTED_FEATURE"


Builder = Callable[["BuildContext"], Product]


class BuildContext:
    """Everything a builder needs: the feature, its parameters, its inputs."""

    __slots__ = ("feature_id", "kind", "role", "parameters", "inputs")

    def __init__(
        self,
        *,
        feature_id: str,
        kind: str,
        role: str,
        parameters: Mapping[str, Any],
        inputs: Sequence[Product],
    ) -> None:
        self.feature_id = feature_id
        self.kind = kind
        self.role = role or feature_id
        self.parameters = parameters
        self.inputs = tuple(inputs)

    # -- parameter access ----------------------------------------------
    def length(self, name: str, default: float | None = None) -> float:
        value = self.parameters.get(name)
        if value is None:
            if default is None:
                raise BackendError(
                    "required length parameter is missing",
                    feature=self.feature_id,
                    parameter=name,
                )
            return default
        return float(value)

    def angle(self, name: str, default: float | None = None) -> float:
        """Angles reach builders already converted to radians."""
        value = self.parameters.get(name)
        if value is None:
            if default is None:
                raise BackendError(
                    "required angle parameter is missing",
                    feature=self.feature_id,
                    parameter=name,
                )
            return default
        return float(value)

    def vector(
        self, name: str, default: tuple[float, float, float] | None = None
    ) -> tuple[float, float, float]:
        value = self.parameters.get(name)
        if value is None:
            if default is None:
                raise BackendError(
                    "required vector parameter is missing",
                    feature=self.feature_id,
                    parameter=name,
                )
            return default
        return tuple(float(component) for component in value)  # type: ignore[return-value]

    def option(self, name: str, default: str = "") -> str:
        value = self.parameters.get(name)
        return default if value is None else str(value)

    def flag(self, name: str, default: bool = False) -> bool:
        value = self.parameters.get(name)
        return default if value is None else bool(value)

    def count(self, name: str, default: int | None = None) -> int:
        value = self.parameters.get(name)
        if value is None:
            if default is None:
                raise BackendError(
                    "required count parameter is missing",
                    feature=self.feature_id,
                    parameter=name,
                )
            return default
        return int(value)

    # -- input access ---------------------------------------------------
    def solids(self) -> tuple[SDF, ...]:
        result: list[SDF] = []
        for index, product in enumerate(self.inputs):
            if not isinstance(product, SolidProduct):
                raise BackendError(
                    "expected a solid input",
                    feature=self.feature_id,
                    input_index=index,
                    got=product.kind,
                )
            result.append(product.solid)
        return tuple(result)

    def solid(self, index: int = 0) -> SDF:
        return self.solids()[index]

    def inherited_entities(self) -> tuple[SemanticEntity, ...]:
        """Entities published by inputs, carried forward unchanged.

        Carrying them is what makes a name like ``base.z_min`` still resolvable
        after the base has been unioned into a larger body and had holes put
        through it. Whether each one *survives* that treatment is settled later
        by :func:`~forge_kernel.lineage.validate_entities`, against the finished
        solid rather than by guesswork here.
        """
        entities: list[SemanticEntity] = []
        for product in self.inputs:
            entities.extend(product.entities)
        return tuple(entities)

    def profile(self, index: int = 0) -> ProfileProduct:
        product = self.inputs[index]
        if not isinstance(product, ProfileProduct):
            raise BackendError(
                "expected a profile input",
                feature=self.feature_id,
                input_index=index,
                got=product.kind,
            )
        return product

    def plane(self, index: int = 0) -> DatumPlaneProduct:
        product = self.inputs[index]
        if not isinstance(product, DatumPlaneProduct):
            raise BackendError(
                "expected a datum plane input",
                feature=self.feature_id,
                input_index=index,
                got=product.kind,
            )
        return product

    def axis_input(self, index: int) -> DatumAxisProduct:
        product = self.inputs[index]
        if not isinstance(product, DatumAxisProduct):
            raise BackendError(
                "expected a datum axis input",
                feature=self.feature_id,
                input_index=index,
                got=product.kind,
            )
        return product

    # -- entity helpers -------------------------------------------------
    def entity(
        self,
        suffix: str,
        entity_type: str,
        frame: Frame,
        dimensions: Mapping[str, float] | None = None,
        ordinal: int = 0,
    ) -> SemanticEntity:
        return SemanticEntity(
            name=f"{self.role}.{suffix}",
            token=lineage_token(self.feature_id, suffix, ordinal),
            entity_type=entity_type,
            frame=frame,
            dimensions=dict(dimensions or {}),
            owning_feature=self.feature_id,
        )


# ----------------------------------------------------------------------
# Datums
# ----------------------------------------------------------------------
def _build_datum_plane(context: BuildContext) -> DatumPlaneProduct:
    base = context.option("base", "XY")
    origin, u_axis, v_axis, normal = _STANDARD_PLANES[base]
    offset = context.length("offset", 0.0)
    # The offset is the coordinate the plane sits at along the axis it is
    # not in -- z for XY, x for YZ, y for XZ -- which is what anyone writing
    # "XZ, offset -200" means. Along the normal it was the same for XY and
    # YZ, and the opposite for XZ, whose normal is -Y so that x and z stay a
    # right-handed pair: a calf shell's rear opening, put at y = -200 by its
    # designer, was cut through the front wall.
    along = {"XY": (0.0, 0.0, 1.0), "YZ": (1.0, 0.0, 0.0),
             "XZ": (0.0, 1.0, 0.0)}[base]
    shifted = tuple(o + a * offset for o, a in zip(origin, along))
    frame = Frame(shifted, u_axis, v_axis, normal)  # type: ignore[arg-type]
    return DatumPlaneProduct(
        frame=frame,
        entities=(context.entity("frame", "frame", frame),),
    )


def _build_datum_axis(context: BuildContext) -> DatumAxisProduct:
    origin = context.vector("origin")
    direction = context.vector("direction")
    frame = Frame.from_axis(origin, direction)
    return DatumAxisProduct(
        origin=origin,
        direction=direction,
        entities=(context.entity("axis", "axis", frame),),
    )


def _build_datum_point(context: BuildContext) -> DatumPointProduct:
    position = context.vector("position")
    frame = Frame(position)
    return DatumPointProduct(
        position=position,
        entities=(context.entity("point", "point", frame),),
    )


# ----------------------------------------------------------------------
# Profiles
# ----------------------------------------------------------------------
def _build_profile_rectangle(context: BuildContext) -> ProfileProduct:
    plane = context.plane(0)
    width = context.length("width")
    height = context.length("height")
    profile = RectangleProfile(
        centre=(context.length("center_u", 0.0), context.length("center_v", 0.0)),
        half_width=width / 2.0,
        half_height=height / 2.0,
        corner_radius=context.length("corner_radius", 0.0),
        corner_chamfer=context.length("corner_chamfer", 0.0),
    )
    return ProfileProduct(
        profile=profile,
        frame=plane.frame,
        entities=(context.entity("region", "volume", plane.frame),),
    )


def _build_profile_circle(context: BuildContext) -> ProfileProduct:
    plane = context.plane(0)
    profile = CircleProfile(
        centre=(context.length("center_u", 0.0), context.length("center_v", 0.0)),
        radius=context.length("diameter") / 2.0,
    )
    return ProfileProduct(
        profile=profile,
        frame=plane.frame,
        entities=(context.entity("region", "volume", plane.frame),),
    )


def _build_profile_polygon(context: BuildContext) -> ProfileProduct:
    plane = context.plane(0)
    profile = PolygonProfile(
        centre=(context.length("center_u", 0.0), context.length("center_v", 0.0)),
        circumradius=context.length("circumscribed_diameter") / 2.0,
        sides=context.count("sides"),
        rotation=context.angle("rotation", 0.0),
        corner_radius=context.length("corner_radius", 0.0),
    )
    return ProfileProduct(
        profile=profile,
        frame=plane.frame,
        entities=(context.entity("region", "volume", plane.frame),),
    )


def _build_profile_slot(context: BuildContext) -> ProfileProduct:
    plane = context.plane(0)
    profile = SlotProfile(
        centre=(context.length("center_u", 0.0), context.length("center_v", 0.0)),
        length=context.length("length"),
        width=context.length("width"),
        rotation=context.angle("rotation", 0.0),
    )
    return ProfileProduct(
        profile=profile,
        frame=plane.frame,
        entities=(context.entity("region", "volume", plane.frame),),
    )


def _build_profile_sketch(context: BuildContext) -> ProfileProduct:
    plane = context.plane(0)
    points = context.parameters.get("points") or ()
    if any(len(p) not in (2, 3) for p in points):
        raise BackendError(
            "a sketch's points are [u, v], or [u, v, corner radius]",
            feature=context.feature_id)
    profile = SketchProfile(sketch_outline(
        points, corner_radius=context.length("corner_radius", 0.0),
        smooth=context.flag("smooth", False)))
    return ProfileProduct(
        profile=profile,
        frame=plane.frame,
        entities=(context.entity("region", "volume", plane.frame),),
    )


def _build_profile_gear(context: BuildContext) -> ProfileProduct:
    plane = context.plane(0)
    profile = GearProfile(
        module=context.length("module"), teeth=context.count("teeth"),
        pressure_angle=context.angle("pressure_angle", math.radians(20.0)),
        centre=(context.length("center_u", 0.0), context.length("center_v", 0.0)),
        rotation=context.angle("rotation", 0.0))
    return ProfileProduct(
        profile=profile,
        frame=plane.frame,
        entities=(context.entity("region", "volume", plane.frame),),
    )


# ----------------------------------------------------------------------
# Solids from profiles
# ----------------------------------------------------------------------
def _build_extrude(context: BuildContext) -> SolidProduct:
    source = context.profile(0)
    distance = context.length("distance")
    mode = context.option("mode", "normal")

    if mode == "symmetric":
        offset = -distance / 2.0
    elif mode == "reverse":
        offset = -distance
    else:
        offset = 0.0

    frame = source.frame
    ends = context.option("ends", "both")
    radius = context.length("end_radius", 0.0)
    chamfer = context.length("end_chamfer", 0.0)
    # "start" is the face on the profile's plane; with a reversed or
    # symmetric extrusion that is no longer the low end, so the ends are
    # named by which face, and the field's own low end is the far one when
    # the extrusion runs back.
    near, far = ((ends in ("both", "start")), (ends in ("both", "end")))
    if mode == "reverse":
        near, far = far, near
    solid = ExtrusionSDF(
        profile=source.profile,
        origin=frame.origin,
        u_axis=frame.x_axis,
        v_axis=frame.y_axis,
        w_axis=frame.z_axis,
        distance=distance,
        offset=offset,
        start_round=radius if near else 0.0,
        end_round=radius if far else 0.0,
        start_chamfer=chamfer if near else 0.0,
        end_chamfer=chamfer if far else 0.0,
        taper=math.tan(context.angle("draft_angle", 0.0)),
    )

    normal = np.asarray(frame.z_axis, dtype=float)
    u_lo, u_hi, v_lo, v_hi = source.profile.bounds()
    half_u, half_v = (u_hi - u_lo) / 2.0, (v_hi - v_lo) / 2.0
    # The end faces where the profile is, not where its plane's origin is: a
    # slot sketched 38 mm off the plane's origin had its faces sampled at
    # the origin, on solid plate.
    middle = (np.asarray(frame.origin, dtype=float)
              + np.asarray(frame.x_axis, dtype=float) * (u_lo + u_hi) / 2.0
              + np.asarray(frame.y_axis, dtype=float) * (v_lo + v_hi) / 2.0)
    base_origin = middle + normal * offset
    top_origin = base_origin + normal * distance

    entities = (
        context.entity(
            "start_face",
            "planar_face",
            Frame(
                tuple(base_origin.tolist()),  # type: ignore[arg-type]
                frame.x_axis,
                frame.y_axis,
                tuple((-normal).tolist()),  # type: ignore[arg-type]
            ),
            {"half_u": half_u, "half_v": half_v},
        ),
        context.entity(
            "end_face",
            "planar_face",
            Frame(
                tuple(top_origin.tolist()),  # type: ignore[arg-type]
                frame.x_axis,
                frame.y_axis,
                frame.z_axis,
            ),
            {"half_u": half_u, "half_v": half_v},
        ),
        context.entity("side", "swept_face", frame, {
            "samples": _points_round_a_profile(source.profile, offset,
                                               distance),
            # The ring and the stretch it is swept over: enough to sample
            # the side as finely as a thin wall needs, when it is asked.
            "ring": _a_ring_round_a_profile(source.profile),
            "span": (float(offset), float(distance))}),
        context.entity("body", "volume", frame),
    )
    return SolidProduct(solid=solid, entities=entities)


def _a_ring_round_a_profile(profile: Any) -> tuple[tuple[float, float], ...]:
    """The (u, v) points round a profile's edge that its swept side is
    sampled at."""
    ring = _points_round_a_profile(profile, 0.0, 1.0, stations=1)
    return tuple((float(u), float(v)) for u, v, _ in ring)


def _points_round_a_profile(profile: Any, offset: float,
                            distance: float, stations: int | None = None
                            ) -> tuple[tuple[float, ...], ...]:
    """Points on an extrusion's swept side, in its plane's frame: round the
    profile's edge, a quarter, half and three quarters of the way along.

    The side is the one face of a cutter drawn through a part that is left
    on it -- a slot's walls -- and with nothing to sample it by, a slot cut
    by an extrusion was reported as having contributed nothing.
    """
    u_lo, u_hi, v_lo, v_hi = profile.bounds()
    pad = 0.05 * max(u_hi - u_lo, v_hi - v_lo, 1e-6)
    us = np.linspace(u_lo - pad, u_hi + pad, 48)
    vs = np.linspace(v_lo - pad, v_hi + pad, 48)
    grid_u, grid_v = np.meshgrid(us, vs, indexing="ij")
    u, v = grid_u.ravel(), grid_v.ravel()
    step = 1e-4 * max(u_hi - u_lo, v_hi - v_lo, 1e-6)
    for _ in range(6):
        d = profile.distance(u, v)
        gu = (profile.distance(u + step, v) - profile.distance(u - step, v)) / (
            2 * step)
        gv = (profile.distance(u, v + step) - profile.distance(u, v - step)) / (
            2 * step)
        g2 = np.maximum(gu * gu + gv * gv, 1e-12)
        u, v = u - d * gu / g2, v - d * gv / g2
    on = np.abs(profile.distance(u, v)) < 1e-6 * max(u_hi - u_lo, 1.0)
    u, v = u[on], v[on]
    if u.size == 0:
        return ()
    centre_u, centre_v = (u_lo + u_hi) / 2.0, (v_lo + v_hi) / 2.0
    order = np.argsort(np.arctan2(v - centre_v, u - centre_u))
    pick = order[np.linspace(0, order.size - 1, min(24, order.size)).astype(int)]
    # Along the whole length, a station every millimetre or so: a cutter
    # 400 mm long drawn through one 8 mm wall of a calf shell leaves its
    # side only where the wall was, and three stations at a quarter, half
    # and three quarters of the way all fell in the air either side of it --
    # an opening that was there, reported as a cutter that did nothing.
    if stations is None:
        stations = int(min(160, max(3, math.ceil(abs(distance) / 1.0))))
    return tuple(
        (float(u[i]), float(v[i]), float(offset + distance * (k + 0.5)
                                         / stations))
        for k in range(stations) for i in pick)


def _build_revolve(context: BuildContext) -> SolidProduct:
    source = context.profile(0)
    axis = context.axis_input(1)
    angle = context.angle("angle")
    frame = Frame.from_axis(axis.origin, axis.direction)
    solid = Revolve(
        profile=source.profile,
        origin=axis.origin,
        axis=axis.direction,
        reference=frame.x_axis,
        angle=angle,
    )
    return SolidProduct(
        solid=solid,
        entities=(
            context.entity("body", "volume", frame),
            context.entity("axis", "axis", frame),
        ),
    )


# ----------------------------------------------------------------------
# Primitives
# ----------------------------------------------------------------------
def _build_box(context: BuildContext) -> SolidProduct:
    size = np.asarray(context.vector("size"), dtype=float)
    origin = np.asarray(context.vector("origin", (0.0, 0.0, 0.0)), dtype=float)
    centered = context.flag("centered", False)
    half = size / 2.0
    centre = origin if centered else origin + half
    radius = context.length("edge_radius", 0.0)
    chamfer = context.length("edge_chamfer", 0.0)
    if radius > 0.0 and chamfer <= 0.0 and context.option(
            "edges", "all") == "all":
        # Every edge rounded: the box `radius` smaller each way, grown back
        # by it -- exact, and with the box's own tight interval bounds.
        if radius * 2.0 >= float(min(size)):
            raise DegenerateGeometryError(
                "an edge radius must be under half the box's smallest side",
                feature=context.feature_id, edge_radius=radius,
                smallest_side=float(min(size)))
        solid = Offset(BoxSDF(tuple(centre.tolist()),  # type: ignore[arg-type]
                              tuple((half - radius).tolist())),  # type: ignore[arg-type]
                       radius)
    elif (radius > 0.0 or chamfer > 0.0) and context.option(
            "edges", "all").endswith(("along_x", "along_y")):
        # The four edges running along one axis: the box's section across
        # that axis, its corners rounded, extruded along it. A tab 12 thick,
        # 30 wide and 75 long, `along_x` at 15 mm, is a link with both ends
        # fully round -- exact, and the box's own extents.
        edges = context.option("edges", "all")
        w = 0 if edges.endswith("along_x") else 1
        u, v = (1, 2) if w == 0 else (2, 0)
        unit = np.eye(3)
        section = RectangleProfile(
            centre=(float(centre[u]), float(centre[v])),
            half_width=float(half[u]), half_height=float(half[v]),
            corner_radius=radius, corner_chamfer=chamfer)
        start = np.zeros(3)
        start[w] = float(centre[w] - half[w])
        solid = ExtrusionSDF(
            profile=section, origin=tuple(start.tolist()),
            u_axis=tuple(unit[u].tolist()), v_axis=tuple(unit[v].tolist()),
            w_axis=tuple(unit[w].tolist()), distance=float(size[w]))
        if edges.startswith(("bottom_", "top_")):
            # One end only: the other half of the box kept square. A hinge
            # tab's outer end round, its root square where it is embedded.
            lo = centre - half
            hi = centre + half
            if edges.startswith("bottom_"):
                lo = lo.copy()
                lo[2] = float(centre[2])
            else:
                hi = hi.copy()
                hi[2] = float(centre[2])
            square = BoxSDF(tuple(((lo + hi) / 2.0).tolist()),  # type: ignore[arg-type]
                            tuple(((hi - lo) / 2.0).tolist()))  # type: ignore[arg-type]
            solid = Union((solid, square))
    elif (radius > 0.0 or chamfer > 0.0) and context.option(
            "edges", "all").startswith("vertical_"):
        # The two upright edges of one face only: a flat tab's free end
        # rounded in plan, its root square where it joins the body. A lug 24
        # wide reaching 22 out along +y, `vertical_y_max` at 12 mm, ends in a
        # semicircle about the point 12 back from that face -- a rounding no
        # four-cornered footprint can take, 12 being more than half its reach.
        edges = context.option("edges", "all")
        normal = 0 if edges.startswith("vertical_x") else 1
        across = 1 - normal
        sign = 1.0 if edges.endswith("_max") else -1.0
        depth = radius if radius > 0.0 else chamfer
        if depth > float(half[across]) + 1e-9:
            raise DegenerateGeometryError(
                "an end's edge radius must be at most half the width of the "
                "face it rounds", feature=context.feature_id,
                edge_radius=depth, face_width=float(size[across]))
        if depth > float(size[normal]) + 1e-9:
            raise DegenerateGeometryError(
                "an end's edge radius must be at most the box's length "
                "behind that face", feature=context.feature_id,
                edge_radius=depth, length=float(size[normal]))
        end = float(centre[normal] + sign * half[normal])
        middle = [float(centre[0]), float(centre[1])]
        extent = [float(half[0]), float(half[1])]
        middle[normal] = end - sign * depth
        extent[normal] = depth
        rounded = ExtrusionSDF(
            profile=RectangleProfile(
                centre=(middle[0], middle[1]),
                half_width=extent[0], half_height=extent[1],
                corner_radius=radius, corner_chamfer=chamfer),
            origin=(0.0, 0.0, float(centre[2] - half[2])),
            u_axis=(1.0, 0.0, 0.0), v_axis=(0.0, 1.0, 0.0),
            w_axis=(0.0, 0.0, 1.0), distance=float(size[2]))
        whole = BoxSDF(tuple(centre.tolist()),  # type: ignore[arg-type]
                       tuple(half.tolist()))  # type: ignore[arg-type]
        # Its rounded profile reaches 2 x depth back from the face; past the
        # box's other face it is cut off, and short of it the box is square.
        solid = Intersection((rounded, whole))
        lo = centre - half
        hi = centre + half
        if float(size[normal]) - depth > 1e-9:
            lo, hi = lo.copy(), hi.copy()
            if sign > 0:
                hi[normal] = end - depth
            else:
                lo[normal] = end + depth
            square = BoxSDF(tuple(((lo + hi) / 2.0).tolist()),  # type: ignore[arg-type]
                            tuple(((hi - lo) / 2.0).tolist()))  # type: ignore[arg-type]
            solid = Union((square, solid))
    elif radius > 0.0 or chamfer > 0.0:
        # A box with its edges rounded or chamfered is its footprint -- a
        # rectangle with those corners, for the vertical edges -- extruded
        # up its height, the edges round its top and bottom faces done the
        # same way. Exact, and the same box where nothing is rounded.
        edges = context.option("edges", "all")
        vertical = edges in ("all", "vertical")
        top = edges in ("all", "top", "top_and_bottom")
        bottom = edges in ("all", "bottom", "top_and_bottom")
        footprint = RectangleProfile(
            centre=(float(centre[0]), float(centre[1])),
            half_width=float(half[0]), half_height=float(half[1]),
            corner_radius=radius if vertical else 0.0,
            corner_chamfer=chamfer if vertical else 0.0)
        solid = ExtrusionSDF(
            profile=footprint, origin=(0.0, 0.0, float(centre[2] - half[2])),
            u_axis=(1.0, 0.0, 0.0), v_axis=(0.0, 1.0, 0.0),
            w_axis=(0.0, 0.0, 1.0), distance=float(size[2]),
            start_round=radius if bottom else 0.0,
            end_round=radius if top else 0.0,
            start_chamfer=chamfer if bottom else 0.0,
            end_chamfer=chamfer if top else 0.0)
    else:
        solid = BoxSDF(
            tuple(centre.tolist()),  # type: ignore[arg-type]
            tuple(half.tolist()),  # type: ignore[arg-type]
        )

    axes = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    entities: list[SemanticEntity] = []
    names = (("x_min", "x_max"), ("y_min", "y_max"), ("z_min", "z_max"))
    for axis_index in range(3):
        others = [i for i in range(3) if i != axis_index]
        for side, suffix in enumerate(names[axis_index]):
            direction = -1.0 if side == 0 else 1.0
            face_centre = centre.copy()
            face_centre[axis_index] += direction * half[axis_index]
            normal = tuple(direction * v for v in axes[axis_index])
            frame = Frame(
                tuple(face_centre.tolist()),  # type: ignore[arg-type]
                axes[others[0]],
                axes[others[1]],
                normal,  # type: ignore[arg-type]
            )
            entities.append(
                context.entity(
                    suffix,
                    "planar_face",
                    frame,
                    {
                        "half_u": float(half[others[0]]),
                        "half_v": float(half[others[1]]),
                    },
                )
            )
    entities.append(
        context.entity("body", "volume", Frame(tuple(centre.tolist())))  # type: ignore[arg-type]
    )
    return SolidProduct(solid=solid, entities=tuple(entities))


def _build_cylinder(context: BuildContext) -> SolidProduct:
    radius = context.length("diameter") / 2.0
    height = context.length("height")
    origin = np.asarray(context.vector("origin", (0.0, 0.0, 0.0)), dtype=float)
    axis = np.asarray(context.vector("axis", (0.0, 0.0, 1.0)), dtype=float)
    length = float(np.linalg.norm(axis))
    if length < 1e-12:
        raise DegenerateGeometryError(
            "cylinder axis has zero length", feature=context.feature_id
        )
    axis = axis / length

    solid = CylinderSDF(
        base=tuple(origin.tolist()),  # type: ignore[arg-type]
        axis=tuple(axis.tolist()),  # type: ignore[arg-type]
        radius=radius,
        height=height,
    )

    mid = origin + axis * (height / 2.0)
    lateral_frame = Frame.from_axis(mid, axis)
    base_frame = Frame.from_axis(origin, -axis)
    top_frame = Frame.from_axis(origin + axis * height, axis)

    entities = (
        context.entity(
            "lateral",
            "cylindrical_face",
            lateral_frame,
            {"radius": radius, "length": height},
        ),
        context.entity(
            "base", "planar_face", base_frame, {"half_u": radius, "half_v": radius}
        ),
        context.entity(
            "top", "planar_face", top_frame, {"half_u": radius, "half_v": radius}
        ),
        context.entity("axis", "axis", lateral_frame, {"length": height}),
        context.entity("body", "volume", lateral_frame),
    )
    return SolidProduct(solid=solid, entities=entities)


def _build_sphere(context: BuildContext) -> SolidProduct:
    radius = context.length("diameter") / 2.0
    origin = context.vector("origin", (0.0, 0.0, 0.0))
    frame = Frame(origin)
    return SolidProduct(
        solid=SphereSDF(origin, radius),
        entities=(
            context.entity("surface", "spherical_face", frame, {"radius": radius}),
            context.entity("body", "volume", frame),
        ),
    )


def _build_cone(context: BuildContext) -> SolidProduct:
    bottom = context.length("bottom_diameter") / 2.0
    top = context.length("top_diameter") / 2.0
    height = context.length("height")
    origin = np.asarray(context.vector("origin", (0.0, 0.0, 0.0)), dtype=float)
    axis = np.asarray(context.vector("axis", (0.0, 0.0, 1.0)), dtype=float)
    length = float(np.linalg.norm(axis))
    if length < 1e-12:
        raise DegenerateGeometryError(
            "cone axis has zero length", feature=context.feature_id)
    axis = axis / length
    solid = ConeSDF(base=tuple(origin.tolist()),  # type: ignore[arg-type]
                    axis=tuple(axis.tolist()),  # type: ignore[arg-type]
                    bottom_radius=bottom, top_radius=top, height=height)
    mid = origin + axis * (height / 2.0)
    middle_frame = Frame.from_axis(mid, axis)
    entities = [
        context.entity("lateral", "conical_face", middle_frame,
                       {"bottom_radius": bottom, "top_radius": top,
                        "length": height}),
        context.entity("axis", "axis", middle_frame, {"length": height}),
        context.entity("body", "volume", middle_frame),
    ]
    if bottom > 0.0:
        entities.append(context.entity(
            "base", "planar_face", Frame.from_axis(origin, -axis),
            {"half_u": bottom * 0.7, "half_v": bottom * 0.7}))
    if top > 0.0:
        entities.append(context.entity(
            "top", "planar_face", Frame.from_axis(origin + axis * height, axis),
            {"half_u": top * 0.7, "half_v": top * 0.7}))
    return SolidProduct(solid=solid, entities=tuple(entities))


def _build_torus(context: BuildContext) -> SolidProduct:
    radius = context.length("diameter") / 2.0
    tube = context.length("tube_diameter") / 2.0
    origin = np.asarray(context.vector("origin", (0.0, 0.0, 0.0)), dtype=float)
    axis = np.asarray(context.vector("axis", (0.0, 0.0, 1.0)), dtype=float)
    length = float(np.linalg.norm(axis))
    if length < 1e-12:
        raise DegenerateGeometryError(
            "ring axis has zero length", feature=context.feature_id)
    axis = axis / length
    if tube >= radius:
        raise DegenerateGeometryError(
            "a ring's tube is thicker than the ring is across: its "
            "`tube_diameter` must be less than its `diameter`",
            feature=context.feature_id, diameter=2 * radius,
            tube_diameter=2 * tube)
    solid = TorusSDF(centre=tuple(origin.tolist()),  # type: ignore[arg-type]
                     axis=tuple(axis.tolist()),  # type: ignore[arg-type]
                     radius=radius, tube_radius=tube)
    frame = Frame.from_axis(origin, axis)
    return SolidProduct(solid=solid, entities=(
        context.entity("axis", "axis", frame, {"length": 2 * tube}),
        context.entity("body", "volume", frame)))


def _build_wedge(context: BuildContext) -> SolidProduct:
    size = np.asarray(context.vector("size"), dtype=float)
    if np.any(size <= 0.0):
        raise DegenerateGeometryError(
            "a wedge needs every extent greater than zero",
            feature=context.feature_id, size=size.tolist())
    origin = np.asarray(context.vector("origin", (0.0, 0.0, 0.0)), dtype=float)
    lo = origin - size / 2.0 if context.flag("centered") else origin
    hi = lo + size
    slope = context.option("slope", "+x")
    if slope not in ("+x", "-x", "+y", "-y"):
        raise BackendError(
            "a wedge slopes towards +x, -x, +y or -y",
            feature=context.feature_id, slope=slope)
    along = 0 if slope.endswith("x") else 1
    sign = 1.0 if slope.startswith("+") else -1.0
    # The sloping top: through the top edge at the tall end and the bottom
    # edge at the low end. Its outward normal leans the way it falls.
    tall = lo[along] if sign > 0 else hi[along]
    run, rise = size[along], size[2]
    normal = np.zeros(3)
    normal[along] = sign * rise
    normal[2] = run
    normal /= np.linalg.norm(normal)
    point = np.array(lo, dtype=float)
    point[along] = tall
    point[2] = hi[2]
    centre = (lo + hi) / 2.0
    solid = Intersection((
        BoxSDF(tuple(centre.tolist()),  # type: ignore[arg-type]
               tuple((size / 2.0).tolist())),  # type: ignore[arg-type]
        HalfSpaceSDF(tuple(point.tolist()),  # type: ignore[arg-type]
                     tuple(normal.tolist()))))  # type: ignore[arg-type]
    other = 1 - along
    base_frame = Frame((centre[0], centre[1], lo[2]), (1.0, 0.0, 0.0),
                       (0.0, -1.0, 0.0), (0.0, 0.0, -1.0))
    back_origin = centre.copy()
    back_origin[along] = tall
    back_normal = np.zeros(3)
    back_normal[along] = -sign
    back_frame = Frame.from_axis(tuple(back_origin.tolist()),
                                 tuple(back_normal.tolist()))
    slope_origin = centre.copy()
    slope_frame = Frame.from_axis(tuple(slope_origin.tolist()),
                                  tuple(normal.tolist()))
    half_run = math.hypot(run, rise) / 2.0
    entities = (
        context.entity("base", "planar_face", base_frame,
                       {"half_u": size[0] / 2.0, "half_v": size[1] / 2.0}),
        # Square patches inside each face, whichever way the frame's own
        # axes fall on it.
        context.entity("back", "planar_face", back_frame,
                       {"half_u": 0.45 * min(size[other], size[2]),
                        "half_v": 0.45 * min(size[other], size[2])}),
        context.entity("slope", "planar_face", slope_frame,
                       {"half_u": 0.45 * min(size[other], 2 * half_run),
                        "half_v": 0.45 * min(size[other], 2 * half_run)}),
        context.entity("body", "volume", Frame(tuple(centre.tolist()))),
    )
    return SolidProduct(solid=solid, entities=entities)


def _points_on_the_surface(solid: SDF, count: int = 72) -> tuple[tuple[float, ...], ...]:
    """Points on a solid's surface, found from its own field: a grid over
    its envelope, each point walked onto the surface along the gradient.
    How a shape with no simple face -- a sweep, a coil, a loft -- is given
    samples to show whether it survives into the part."""
    envelope = solid.envelope
    lo = np.asarray(envelope.lo, dtype=float)
    hi = np.asarray(envelope.hi, dtype=float)
    side = 9
    grid = np.stack(np.meshgrid(*[np.linspace(lo[i], hi[i], side)
                                  for i in range(3)], indexing="ij"),
                    axis=-1).reshape(-1, 3)
    points = grid
    for _ in range(8):
        value = solid(points)
        gradient = solid.gradient(points, step=1e-4 * max(
            float(np.max(hi - lo)), 1.0))
        g2 = np.maximum(np.einsum("ij,ij->i", gradient, gradient), 1e-12)
        points = points - (value / g2)[:, None] * gradient
    value = np.abs(solid(points))
    on = points[value < 1e-4 * max(float(np.max(hi - lo)), 1.0)]
    if on.shape[0] == 0:
        return ()
    pick = np.linspace(0, on.shape[0] - 1, min(count, on.shape[0])).astype(int)
    return tuple(tuple(float(c) for c in on[i]) for i in pick)


def _build_sweep(context: BuildContext) -> SolidProduct:
    source = context.profile(0)
    path = context.parameters.get("path") or ()
    if len(path) < 2 or any(len(p) != 3 for p in path):
        raise BackendError("a sweep's path is two or more [x, y, z] points",
                           feature=context.feature_id)
    path = round_the_path(path, context.length("bend_radius", 0.0))
    solid = SweepSDF(profile=source.profile, path=path)
    world = Frame((0.0, 0.0, 0.0))
    return SolidProduct(solid=solid, entities=(
        context.entity("side", "swept_face", world,
                       {"samples": _points_on_the_surface(solid)}),
        context.entity("body", "volume", Frame(solid.envelope.centre)),
    ))


def _build_pipe(context: BuildContext) -> SolidProduct:
    path = context.parameters.get("path") or ()
    if len(path) < 2 or any(len(p) != 3 for p in path):
        raise BackendError("a pipe's path is two or more [x, y, z] points",
                           feature=context.feature_id)
    path = round_the_path(path, context.length("bend_radius", 0.0))
    solid = TubeSDF(path=path, radius=context.length("diameter") / 2.0,
                    inner_radius=context.length("inner_diameter", 0.0) / 2.0)
    world = Frame((0.0, 0.0, 0.0))
    return SolidProduct(solid=solid, entities=(
        context.entity("surface", "swept_face", world,
                       {"samples": _points_on_the_surface(solid)}),
        context.entity("body", "volume", Frame(solid.envelope.centre)),
    ))


def _build_coil(context: BuildContext) -> SolidProduct:
    turns = float(context.parameters.get("turns") or 0.0)
    path = helix_points(
        context.length("diameter") / 2.0, context.length("pitch"), turns,
        origin=context.vector("origin", (0.0, 0.0, 0.0)),
        axis=context.vector("axis", (0.0, 0.0, 1.0)))
    wire = context.length("wire_diameter") / 2.0
    if context.length("pitch") < 2.0 * wire - 1e-9 and turns > 1.0:
        raise DegenerateGeometryError(
            "a coil's pitch must be at least its wire's diameter, or its turns "
            "run into each other", feature=context.feature_id,
            pitch=context.length("pitch"), wire_diameter=2.0 * wire)
    solid = TubeSDF(path=path, radius=wire)
    world = Frame((0.0, 0.0, 0.0))
    return SolidProduct(solid=solid, entities=(
        context.entity("surface", "swept_face", world,
                       {"samples": _points_on_the_surface(solid)}),
        context.entity("body", "volume", Frame(solid.envelope.centre)),
    ))


def _build_loft(context: BuildContext) -> SolidProduct:
    first, second = context.profile(0), context.profile(1)
    a, b = first.frame, second.frame
    normal = np.asarray(a.z_axis, dtype=float)
    if abs(abs(float(normal @ np.asarray(b.z_axis, dtype=float))) - 1.0) > 1e-6:
        raise DegenerateGeometryError(
            "a loft's two profiles must lie on parallel planes",
            feature=context.feature_id)
    delta = np.asarray(b.origin, dtype=float) - np.asarray(a.origin, dtype=float)
    height = float(delta @ normal)
    # B's own u, v may run the other way to A's: its outline is read in
    # A's frame by mapping through both.
    second_profile = second.profile
    flip_u = float(np.asarray(b.x_axis) @ np.asarray(a.x_axis)) < 0
    flip_v = float(np.asarray(b.y_axis) @ np.asarray(a.y_axis)) < 0
    if flip_u or flip_v:
        raise DegenerateGeometryError(
            "a loft's two profiles must be sketched on planes facing the same "
            "way -- both on XY, or both on the same base", feature=context.feature_id)
    if height < 0:
        first, second = second, first
        a, b = b, a
        delta, height = -delta, -height
        second_profile = second.profile
    shift = (float(delta @ np.asarray(a.x_axis)), float(delta @ np.asarray(a.y_axis)))
    solid = LoftSDF(first=first.profile, second=second_profile,
                    origin=a.origin, u_axis=a.x_axis, v_axis=a.y_axis,
                    w_axis=a.z_axis, height=height, shift=shift)
    world = Frame((0.0, 0.0, 0.0))
    return SolidProduct(solid=solid, entities=(
        context.entity("side", "swept_face", world,
                       {"samples": _points_on_the_surface(solid)}),
        context.entity("body", "volume", Frame(solid.envelope.centre)),
    ))


# ----------------------------------------------------------------------
# Booleans
# ----------------------------------------------------------------------
def _build_union(context: BuildContext) -> SolidProduct:
    blend = context.length("blend_radius", 0.0)
    chamfer = context.length("chamfer", 0.0)
    operands = tuple(context.solids())
    if not blend and not chamfer:
        # Lofts that run on from one another are one loft: unioned, each
        # one's closed ends would stay inside the part as faces, and a shell
        # of it would wall every section off. See LoftStackSDF. A sharp
        # union of sharp unions is one union, so lofts unioned two at a time
        # -- `stack_a = loft_1 + loft_2`, `stack_b = stack_a + loft_3` --
        # are found as well.
        flat: list[SDF] = []
        for operand in operands:
            if (isinstance(operand, Union) and not operand.blend_radius
                    and not operand.chamfer):
                flat.extend(operand.operands)
            else:
                flat.append(operand)
        stacked = stack_lofts(flat)
        if len(stacked) < len(flat):
            operands = tuple(stacked)
    solid = Union(operands, blend_radius=blend, chamfer=chamfer)
    entities = list(context.inherited_entities())
    entities.append(
        context.entity("body", "volume", Frame(solid.envelope.centre))
    )
    if blend > 0.0:
        entities.append(
            context.entity("blend", "volume", Frame(solid.envelope.centre))
        )
    return SolidProduct(solid=solid, entities=tuple(entities))


def _taken_from(base: SDF, tools: tuple[SDF, ...]) -> SDF:
    """`base` with `tools` taken away, sharply. A chain of cuts -- fifteen
    holes, each cut from the one before -- is one difference with all their
    tools: `max(max(b, -t1), -t2)` is `max(b, -t1, -t2)` exactly, and one
    node can cull its tools by where they are, where fifteen nested ones
    each looked at every point."""
    if isinstance(base, Difference) and base.blend_radius <= 0.0 \
            and base.chamfer <= 0.0:
        return Difference(base.base, tuple(base.tools) + tuple(tools))
    return Difference(base, tuple(tools))


def _build_subtract(context: BuildContext) -> SolidProduct:
    solids = context.solids()
    blend = context.length("blend_radius", 0.0)
    chamfer = context.length("chamfer", 0.0)
    solid = (_taken_from(solids[0], tuple(solids[1:]))
             if blend <= 0.0 and chamfer <= 0.0 else
             Difference(solids[0], solids[1:], blend_radius=blend,
                        chamfer=chamfer))
    entities = list(context.inherited_entities())
    entities.append(context.entity("body", "volume", Frame(solid.envelope.centre)))
    return SolidProduct(solid=solid, entities=tuple(entities))


def _build_intersect(context: BuildContext) -> SolidProduct:
    solid = Intersection(
        context.solids(), blend_radius=context.length("blend_radius", 0.0),
        chamfer=context.length("chamfer", 0.0),
    )
    entities = list(context.inherited_entities())
    entities.append(context.entity("body", "volume", Frame(solid.envelope.centre)))
    return SolidProduct(solid=solid, entities=tuple(entities))


# ----------------------------------------------------------------------
# Modifiers
# ----------------------------------------------------------------------
def _depth_through_the_first_wall(base: SDF, position: Any, axis: Any,
                                  envelope: Any, radius: float,
                                  feature: str) -> tuple[float, float]:
    """How deep a hole from `position` along `axis` must go to pass through
    the first material it meets, and no further.

    The calf shell's mounting holes, drilled "through the rear wall only",
    were given depths by hand -- from the middle of the hollow, 20 mm, into
    air -- because the wall's place along the axis is a curve the model
    could not work out. The solid knows where it is: walk the axis from the
    position, find the first stretch of material, and stop a little past its
    far side, never as far as the next wall.
    """
    reach = float(envelope.diagonal) * 2.0 + 4.0 * radius
    step = max(0.05, reach / 20_000.0)
    ts = np.arange(0.0, reach, step)
    points = np.asarray(position, dtype=float)[None, :] + ts[:, None] * axis[None, :]
    inside = np.asarray(base(points), dtype=float) < 0.0
    hits = np.nonzero(inside)[0]
    if hits.size == 0:
        raise DegenerateGeometryError(
            "`through: first_wall` meets no material along the hole's axis "
            "from its position; point `axis` at the wall",
            feature=feature, position=[round(float(c), 3) for c in position],
            axis=[round(float(c), 3) for c in axis])
    first = int(hits[0])
    margin = max(0.5, 0.25 * radius)
    enters = max(0.0, float(ts[first]) - margin)
    if first == 0:
        # Started inside the wall: the first wall it meets is the one it is
        # in, and through it is through the whole of it -- back to its near
        # face as well. Cut from the position on, it went through half: the
        # clevis's two pin holes, each placed in the middle of its ear,
        # bored each ear from the middle out.
        back = np.asarray(position, dtype=float)[None, :] - \
            ts[:, None] * axis[None, :]
        behind = np.asarray(base(back), dtype=float) < 0.0
        out = np.nonzero(~behind)[0]
        if out.size:
            near_face = float(ts[int(out[0])])
            earlier = np.nonzero(behind[int(out[0]):])[0]
            reach_back = near_face + margin
            if earlier.size:
                previous_wall = float(ts[int(out[0]) + int(earlier[0])])
                reach_back = min(reach_back, (near_face + previous_wall) / 2.0)
            enters = -reach_back
    after = np.nonzero(~inside[first:])[0]
    if after.size == 0:
        return enters, float(ts[-1])
    leaves = first + int(after[0])
    exit_at = float(ts[leaves])
    later = np.nonzero(inside[leaves:])[0]
    if later.size:
        next_wall = float(ts[leaves + int(later[0])])
        return enters, min(exit_at + margin, (exit_at + next_wall) / 2.0)
    return enters, exit_at + margin


def _the_first_wall_s_faces(base: SDF, position: Any, axis: Any,
                            start: float, end: float) -> tuple[float, float]:
    """Where, along the axis from `position`, the first wall's near and far
    faces are -- inside the stretch the hole cuts, [start, end]. A counterbore
    is measured from the face, not from the margin cut before it: a 4 mm
    counterbore on a first-wall hole came out 3.2 mm."""
    ts = np.linspace(start, end, 801)
    points = np.asarray(position, dtype=float)[None, :] + ts[:, None] * \
        np.asarray(axis, dtype=float)[None, :]
    inside = np.asarray(base(points), dtype=float) < 0.0
    hits = np.nonzero(inside)[0]
    if hits.size == 0:
        return start, end
    near = float(ts[hits[0]])
    gone = np.nonzero(~inside[hits[0]:])[0]
    far = float(ts[hits[0] + int(gone[0])]) if gone.size else end
    return near, far


def _build_hole(context: BuildContext) -> SolidProduct:
    base = context.solid(0)
    radius = context.length("diameter") / 2.0
    position = np.asarray(context.vector("position"), dtype=float)
    axis = np.asarray(context.vector("axis", (0.0, 0.0, 1.0)), dtype=float)
    norm = float(np.linalg.norm(axis))
    if norm < 1e-12:
        raise DegenerateGeometryError(
            "hole axis has zero length", feature=context.feature_id
        )
    axis = axis / norm

    envelope = base.envelope
    span = envelope.diagonal
    # How much material the bore actually passes through, measured along its own
    # axis at its own position.
    #
    # The cheap approximation -- the envelope's extent along the axis -- is badly
    # wrong for the common case of a bore through a thin web on a long part: a
    # 12 mm web on a 70 mm plate would have its bore described as 70 mm long, and
    # the burial check would then scatter most of its sample points through empty
    # air and conclude that a perfectly healthy bore is 83% absent. Sampling the
    # solid along the axis costs one field evaluation and gets it right.
    depth_value = context.parameters.get("depth")
    if context.option("through", "all") == "first_wall":
        if depth_value is not None:
            raise DegenerateGeometryError(
                "`through: first_wall` finds its own depth; give no `depth` "
                "with it", feature=context.feature_id)
        start, end = _depth_through_the_first_wall(
            base, position, axis, envelope, radius, context.feature_id)
        near, far = _the_first_wall_s_faces(base, position, axis, start, end)
        wall_faces = (position + axis * near, position + axis * far)
        # Cut from just before the wall: the bore is the wall's, not the
        # hollow's the hole was drilled across.
        position = position + axis * start
        depth_value = end - start
    else:
        wall_faces = None
    # A blind hole's bore is where it cuts: from its position, `depth` along
    # its axis. Read along the whole line instead, a set screw drilled from a
    # collar's axis out through its wall had its bore centred on the axis,
    # inside the empty main bore -- every check sample in air, and a hole
    # plainly in the part reported "not in the part" four ways.
    axial_extent, axial_centre, bearing_length = _material_span_along_axis(
        base, position, axis, envelope,
        within=None if depth_value is None else (0.0, float(depth_value)),
    )
    walls = _walls_along_axis(
        base, position, axis, envelope,
        within=None if depth_value is None else (0.0, float(depth_value)),
    )

    if depth_value is None:
        # A through hole is cut with a tool long enough to clear the envelope in
        # both directions, so "through" does not depend on the part's current
        # size and stays through when a parameter changes.
        cut_length = span * 2.0 + 4.0 * radius
        cut_base = position - axis * (cut_length / 2.0)
        bore_length = axial_extent
    else:
        depth = float(depth_value)
        if depth <= 0.0:
            raise DegenerateGeometryError(
                "hole depth must be positive",
                feature=context.feature_id,
                depth=depth,
            )
        cut_base = position
        cut_length = depth
        bore_length = depth

    tool: SDF = CylinderSDF(
        base=tuple(cut_base.tolist()),  # type: ignore[arg-type]
        axis=tuple(axis.tolist()),  # type: ignore[arg-type]
        radius=radius,
        height=cut_length,
    )

    tools: list[SDF] = [tool]

    # Where the hole meets the material: the counterbore or countersink is
    # cut there, not at the point the hole was declared through -- a hole
    # declared at the middle of a plate has its counterbore at the plate's
    # face, not half way through it.
    if wall_faces is not None:
        start_at, end_at = wall_faces
    elif depth_value is None:
        start_at = position + axis * (axial_centre - axial_extent / 2.0)
        end_at = position + axis * (axial_centre + axial_extent / 2.0)
    else:
        start_at = position
        end_at = position + axis * float(depth_value)
    if context.option("entry", "start") == "end":
        surface, inward = end_at, -axis
    else:
        surface, inward = start_at, axis
    margin = max(span * 0.05, 1.0)

    counterbore_diameter = context.parameters.get("counterbore_diameter")
    counterbore_depth = context.parameters.get("counterbore_depth")
    if counterbore_diameter is not None:
        if counterbore_depth is None:
            raise DegenerateGeometryError(
                "a counterbore needs its depth as well as its diameter",
                feature=context.feature_id)
        cb_radius = float(counterbore_diameter) / 2.0
        cb_depth = float(counterbore_depth)
        if cb_radius <= radius:
            raise DegenerateGeometryError(
                "counterbore diameter must exceed the hole diameter",
                feature=context.feature_id,
                counterbore_diameter=cb_radius * 2.0,
                diameter=radius * 2.0,
            )
        tools.append(
            CylinderSDF(
                base=tuple((surface - inward * margin).tolist()),  # type: ignore[arg-type]
                axis=tuple(inward.tolist()),  # type: ignore[arg-type]
                radius=cb_radius,
                height=margin + cb_depth,
            )
        )
    countersink_diameter = context.parameters.get("countersink_diameter")
    if countersink_diameter is not None:
        cs_radius = float(countersink_diameter) / 2.0
        if cs_radius <= radius:
            raise DegenerateGeometryError(
                "countersink diameter must exceed the hole diameter",
                feature=context.feature_id,
                countersink_diameter=cs_radius * 2.0, diameter=radius * 2.0)
        half_angle = context.angle("countersink_angle", math.radians(90.0)) / 2.0
        if not 0.05 < half_angle < 1.5:
            raise DegenerateGeometryError(
                "a countersink's angle is between a few and 170 degrees",
                feature=context.feature_id)
        slope = math.tan(half_angle)
        # From outside the surface, as wide there as it is at the surface
        # plus the margin's worth of cone, down to the hole's own size.
        outer = cs_radius + margin * slope
        sink = (cs_radius - radius) / slope
        tools.append(ConeSDF(
            base=tuple((surface - inward * margin).tolist()),  # type: ignore[arg-type]
            axis=tuple(inward.tolist()),  # type: ignore[arg-type]
            bottom_radius=outer, top_radius=radius,
            height=margin + sink))

    solid = _taken_from(base, tuple(tools))

    # Centre the published bore on the material it passes through, not on the
    # position the document declared -- see _material_span_along_axis.
    bore_frame = Frame.from_axis(position + axis * axial_centre, axis)
    entities = list(context.inherited_entities())
    entities.extend(
        (
            context.entity(
                "bore",
                "cylindrical_face",
                bore_frame,
                {
                    "radius": radius,
                    # Material the bore passes through, gaps excluded. This is
                    # the bearing length; `length` below is the overall span and
                    # is used for placing surface samples.
                    "bearing_length": min(bearing_length, axial_extent),
                    # The bore's own length is the part's extent along the axis,
                    # not the oversized cutting tool's, so the surface samples
                    # used for burial checking land on real material.
                    "length": min(bore_length, axial_extent),
                    # How many separate pieces of material it cuts: one for
                    # a plate or a single wall, two through a hollow part's
                    # facing walls -- or a clevis's two ears.
                    "walls": float(walls),
                },
            ),
            context.entity("axis", "axis", bore_frame, {"length": bore_length}),
            context.entity("body", "volume", Frame(solid.envelope.centre)),
        )
    )
    return SolidProduct(solid=solid, entities=tuple(entities))


def _build_shell(context: BuildContext) -> SolidProduct:
    solid = Shell(
        solid=context.solid(0),
        thickness=context.length("thickness"),
        direction=context.option("direction", "inward"),
    )
    entities = list(context.inherited_entities())
    entities.append(context.entity("body", "volume", Frame(solid.envelope.centre)))
    entities.append(context.entity("inner", "volume", Frame(solid.envelope.centre)))
    return SolidProduct(solid=solid, entities=tuple(entities))


def _build_offset(context: BuildContext) -> SolidProduct:
    solid = Offset(solid=context.solid(0), distance=context.length("distance"))
    entities = list(context.inherited_entities())
    entities.append(context.entity("body", "volume", Frame(solid.envelope.centre)))
    return SolidProduct(solid=solid, entities=tuple(entities))


# ----------------------------------------------------------------------
# Arrays and transforms
# ----------------------------------------------------------------------
def _build_pattern_linear(context: BuildContext) -> SolidProduct:
    count = context.count("count")
    spacing = context.vector("spacing")
    source = context.solid(0)
    entities = list(context.inherited_entities())
    if context.flag("symmetric", False):
        shift = tuple(-component * (count - 1) / 2.0 for component in spacing)
        source = Transform(source, tuple(np.eye(3).ravel()), shift)  # type: ignore[arg-type]
        # The named geometry goes with the solid: left where it was drawn,
        # an ear patterned twice about its own place had its bore named in
        # the air between the two copies, and was reported buried.
        entities = [entity.transformed(np.eye(3), np.asarray(shift, dtype=float))
                    for entity in entities]
    solid = Repeat(solid=source, step=spacing, count=count)
    entities.append(context.entity("body", "volume", Frame(solid.envelope.centre)))
    return SolidProduct(solid=solid, entities=tuple(entities))


def _build_pattern_circular(context: BuildContext) -> SolidProduct:
    count = context.count("count")
    origin = np.asarray(context.vector("axis_origin"), dtype=float)
    axis = np.asarray(context.vector("axis_direction"), dtype=float)
    axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
    # Two ways to say where the copies go, and they are the two ways people
    # say it. `step_angle` is the angle between neighbours -- "90 degrees
    # apart" -- which is the number a brief states and the one a requirement
    # can be bound to. `total_angle` is the span from the first copy to the
    # last, for an arc described end to end. Giving both would let a design
    # state the same placement twice and disagree with itself, so it is
    # refused here rather than silently resolved in favour of one of them.
    step = context.parameters.get("step_angle")
    total_given = context.parameters.get("total_angle")
    if step is not None and total_given is not None:
        raise BackendError(
            "a circular pattern is placed by `step_angle` or by "
            "`total_angle`, not by both",
            feature=context.feature_id,
            step_angle=float(step),
            total_angle=float(total_given),
        )
    if step is not None:
        # The angle between neighbours, applied index by index. No division
        # by the count, so the spacing the design states is the spacing the
        # geometry gets, whatever the count turns out to be.
        placements = [context.angle("step_angle") * index for index in range(1, count)]
    else:
        total = context.angle("total_angle", 2.0 * math.pi)
        # A full circle divides by the count, because the first and last copy
        # would otherwise land on top of each other; an arc divides by the
        # gaps between copies, because its end points are both wanted.
        divisor = count if total >= 2.0 * math.pi - 1e-9 else max(count - 1, 1)
        placements = [total * index / divisor for index in range(1, count)]

    source = context.solid(0)

    copies: list[SDF] = [source]
    for angle in placements:
        rotation = _axis_angle_matrix(axis, angle)
        translation = origin - rotation @ origin
        copies.append(
            Transform(source, tuple(rotation.ravel().tolist()), tuple(translation.tolist()))  # type: ignore[arg-type]
        )
    solid = Union(tuple(copies))
    entities = list(context.inherited_entities())
    entities.append(context.entity("body", "volume", Frame(solid.envelope.centre)))
    return SolidProduct(solid=solid, entities=tuple(entities))


def _build_mirror(context: BuildContext) -> SolidProduct:
    keep = context.flag("keep_original", True)
    point = np.asarray(context.vector("plane_origin", (0.0, 0.0, 0.0)),
                       dtype=float)
    normal = np.asarray(context.vector("plane_normal"), dtype=float)
    solid = Mirror(
        solid=context.solid(0),
        point=tuple(point.tolist()),  # type: ignore[arg-type]
        normal=tuple(normal.tolist()),  # type: ignore[arg-type]
        keep_original=keep,
    )
    entities = list(context.inherited_entities())
    length = float(np.linalg.norm(normal))
    if not keep and length > 1e-12:
        # The original gone, its named geometry is where its image is.
        n = normal / length
        reflection = np.eye(3) - 2.0 * np.outer(n, n)
        entities = [entity.transformed(reflection,
                                       2.0 * float(point @ n) * n)
                    for entity in entities]
    entities.append(context.entity("body", "volume", Frame(solid.envelope.centre)))
    return SolidProduct(solid=solid, entities=tuple(entities))


def _build_transform(context: BuildContext) -> SolidProduct:
    translate = np.asarray(
        context.vector("translate", (0.0, 0.0, 0.0)), dtype=float
    )
    angle = context.angle("rotate_angle", 0.0)
    if angle != 0.0:
        axis = np.asarray(context.vector("rotate_axis", (0.0, 0.0, 1.0)), dtype=float)
        axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
        rotation = _axis_angle_matrix(axis, angle)
        pivot = np.asarray(
            context.vector("rotate_origin", (0.0, 0.0, 0.0)), dtype=float
        )
        translation = pivot - rotation @ pivot + translate
    else:
        rotation = np.eye(3)
        translation = translate

    source = context.solid(0)
    solid = Transform(
        source,
        tuple(rotation.ravel().tolist()),  # type: ignore[arg-type]
        tuple(translation.tolist()),  # type: ignore[arg-type]
    )
    # Entities move with the body, keeping their tokens: a transform relocates
    # geometry, it does not create new geometry.
    entities = [
        entity.transformed(rotation, translation)
        for entity in context.inherited_entities()
    ]
    entities.append(context.entity("body", "volume", Frame(solid.envelope.centre)))
    return SolidProduct(solid=solid, entities=tuple(entities))


def _build_bend(context: BuildContext) -> SolidProduct:
    """A solid bent through an angle, as sheet metal is.

    The inside radius is stated, or follows from how much of the solid's
    length the curve is spread over (``bend_length``, along its middle), or
    is the solid's own thickness, the usual inside radius of a fold.

    Several bends in a row are each stated on the flat part -- "bent at 20
    mm and at 50 mm" -- so a bend taking another bend's result is folded
    into one chain over the flat solid, and applied from the far end in:
    each fold then meets flat material, and turns everything past it.
    """
    from dataclasses import replace

    source = context.solid(0)
    angle = context.angle("angle")
    radius = context.parameters.get("radius")
    spread = context.parameters.get("bend_length")
    if radius is not None and spread is not None:
        raise BackendError(
            "a bend is sized by `radius` or by `bend_length`, not by both",
            feature=context.feature_id, radius=float(radius),
            bend_length=float(spread))
    position = context.vector("position")
    along = context.vector("along")
    toward = context.vector("toward")
    # Peel the bends this one follows, back to the flat solid.
    earlier: list[Bend] = []
    flat = source
    while isinstance(flat, Bend):
        earlier.append(flat)
        flat = flat.solid
    probe = Bend(flat, position=position, along=along, toward=toward,
                 angle=angle if 0.0 < angle < math.pi else math.pi / 2,
                 radius=1.0)
    e1 = probe.frame[0]
    if any(abs(abs(float(np.dot(bend.frame[0], e1))) - 1.0) > 1e-9
           for bend in earlier):
        # Bends across one another: this one acts on the solid as it is.
        earlier, flat = [], source
        probe = Bend(flat, position=position, along=along, toward=toward,
                     angle=angle if 0.0 < angle < math.pi else math.pi / 2,
                     radius=1.0)
    face, thickness = probe.faces_of(flat)
    if radius is None and spread is not None:
        if angle <= 0.0:
            radius = 1.0
        else:
            radius = float(spread) / angle - thickness / 2.0
            if radius <= 0.0:
                raise BackendError(
                    "the bend is tighter than the solid is thick: spread over "
                    f"{float(spread):g} mm, {math.degrees(angle):g} degrees "
                    "needs a solid thinner than "
                    f"{2.0 * float(spread) / angle:g} mm",
                    feature=context.feature_id, thickness=thickness)
    if radius is None:
        radius = thickness
    held = context.option("hold", "start") == "middle"
    this = Bend(flat, position=position, along=along, toward=toward,
                angle=angle, radius=float(radius), face=face,
                thickness=thickness, hold=angle / 2.0 if held else 0.0)
    # Far end first: each fold is applied while what it bends is still flat.
    specs = [this] + [replace(bend, solid=flat) for bend in earlier]
    if len(specs) > 1:
        # Held level is for one bend: in a chain each is stated on the flat
        # part, and a turn back would move the zones of the others.
        specs = [replace(spec, hold=0.0) for spec in specs]
    specs.sort(key=lambda bend: -float(np.dot(
        np.asarray(bend.position, dtype=float), e1)))
    chain: list[Bend] = []
    solid: SDF = flat
    for spec in specs:
        flat_face, flat_thickness = (spec.face, spec.thickness) if (
            spec.face is not None) else spec.faces_of(flat)
        solid = replace(spec, solid=solid, face=flat_face,
                        thickness=flat_thickness)
        chain.append(solid)  # type: ignore[arg-type]

    def moved(entity: SemanticEntity) -> SemanticEntity:
        if earlier and entity.warps:
            # Back to where it was made, then through the whole chain.
            entity = replace(entity, frame=entity.sample_frame or entity.frame,
                             warps=(), sample_frame=None)
        for bend in chain:
            origin = np.asarray(entity.frame.origin, dtype=float)[None, :]
            rotation = bend.rotation_by(
                float(bend.turn_at(origin)[0]) - bend.hold)
            where = bend.forward(origin)[0]
            axes = [rotation @ np.asarray(axis, dtype=float) for axis in (
                entity.frame.x_axis, entity.frame.y_axis, entity.frame.z_axis)]
            entity = entity.warped(bend.forward, Frame(
                tuple(where.tolist()),  # type: ignore[arg-type]
                tuple(axes[0].tolist()),  # type: ignore[arg-type]
                tuple(axes[1].tolist()),  # type: ignore[arg-type]
                tuple(axes[2].tolist()),  # type: ignore[arg-type]
            ))
        return entity

    entities = [moved(entity) for entity in context.inherited_entities()]
    entities.append(context.entity("body", "volume", Frame(solid.envelope.centre)))
    return SolidProduct(solid=solid, entities=tuple(entities))


def _walls_along_axis(
    solid: SDF,
    position: np.ndarray,
    axis: np.ndarray,
    envelope: "Box",
    *,
    samples: int = 2048,
    within: tuple[float, float] | None = None,
) -> int:
    """How many separate runs of material the line through a hole's axis
    crosses, over the stretch the hole cuts."""
    corners = np.array([[x, y, z] for x in (envelope.lo[0], envelope.hi[0])
                        for y in (envelope.lo[1], envelope.hi[1])
                        for z in (envelope.lo[2], envelope.hi[2])])
    projections = corners @ axis
    origin_offset = float(position @ axis)
    start = float(projections.min()) - origin_offset
    stop = float(projections.max()) - origin_offset
    if within is not None:
        start, stop = max(start, within[0]), min(stop, within[1])
    if not stop > start:
        return 0
    distances = np.linspace(start, stop, samples)
    points = position[None, :] + distances[:, None] * axis[None, :]
    inside = np.asarray(solid(points)) < 0.0
    return int(np.count_nonzero(inside[1:] & ~inside[:-1]) + int(inside[0]))


def _material_span_along_axis(
    solid: SDF,
    position: np.ndarray,
    axis: np.ndarray,
    envelope: "Box",
    *,
    samples: int = 512,
    within: tuple[float, float] | None = None,
) -> tuple[float, float, float]:
    """Extent, midpoint and total material along a line through a point.

    Walks the line through ``position`` in direction ``axis`` over the range the
    envelope allows, and returns how far apart the first and last inside samples
    are, together with the offset from ``position`` to the middle of that span.

    All three matter, and the third is easy to miss.

    The **extent** stops a 12 mm bore through a thin web on a 70 mm plate from
    being described as 70 mm long. The **midpoint** stops the bore's frame from
    being centred on the hole's *declared* position, which for a through hole is
    usually a point on the surface rather than in the middle of the material -- a
    bolt hole declared at ``z = 0`` through an 8 mm plate would otherwise have
    half its check samples hanging in the air below the part and report itself
    50% absent.

    The **material length** is the extent minus any gaps, and it is a different
    number whenever the bore crosses one. A clevis pin passes through two 6 mm
    ears separated by a 12 mm gap: the extent is 24 mm and the metal is 12 mm.
    Using the extent as the bearing length would halve the computed bearing
    stress and double the reported safety factor -- a confident, wrong, and
    entirely plausible-looking number.

    Falls back to the envelope's extent when no sample lands inside, which means
    the hole misses the part entirely. That is worth knowing, and the burial
    check will report the bore as absent rather than this function inventing a
    plausible length for it.
    """
    corners = np.array(
        [
            [x, y, z]
            for x in (envelope.lo[0], envelope.hi[0])
            for y in (envelope.lo[1], envelope.hi[1])
            for z in (envelope.lo[2], envelope.hi[2])
        ]
    )
    projections = corners @ axis
    lo, hi = float(projections.min()), float(projections.max())
    envelope_extent = hi - lo
    if envelope_extent <= 0.0:
        return envelope.diagonal

    origin_offset = float(position @ axis)
    start, stop = lo - origin_offset, hi - origin_offset
    if within is not None:
        # A blind hole cuts only from its position to its depth: the material
        # it bores is what lies along that stretch, not the whole line.
        start, stop = max(start, within[0]), min(stop, within[1])
        if stop <= start:
            return (max(within[1] - within[0], 0.0),
                    (within[0] + within[1]) / 2.0, 0.0)
        envelope_extent = stop - start
    distances = np.linspace(start, stop, samples)
    points = position[None, :] + distances[:, None] * axis[None, :]
    inside = solid(points) < 0.0
    if not np.any(inside):
        return (envelope_extent,
                (start + stop) / 2.0 if within is not None else 0.0, 0.0)

    indices = np.flatnonzero(inside)
    first = float(distances[indices[0]])
    last = float(distances[indices[-1]])
    step = envelope_extent / max(samples - 1, 1)
    material = float(indices.size) * step
    return (last - first) + step, (first + last) / 2.0, material


def _axis_angle_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues' rotation formula."""
    x, y, z = axis
    cross = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return (
        np.eye(3)
        + math.sin(angle) * cross
        + (1.0 - math.cos(angle)) * (cross @ cross)
    )


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------
BUILDERS: Mapping[str, Builder] = {
    "datum_plane": _build_datum_plane,
    "datum_axis": _build_datum_axis,
    "datum_point": _build_datum_point,
    "profile_rectangle": _build_profile_rectangle,
    "profile_circle": _build_profile_circle,
    "profile_polygon": _build_profile_polygon,
    "profile_slot": _build_profile_slot,
    "profile_sketch": _build_profile_sketch,
    "profile_gear": _build_profile_gear,
    "extrude": _build_extrude,
    "revolve": _build_revolve,
    "box": _build_box,
    "cylinder": _build_cylinder,
    "sphere": _build_sphere,
    "cone": _build_cone,
    "torus": _build_torus,
    "wedge": _build_wedge,
    "sweep": _build_sweep,
    "pipe": _build_pipe,
    "coil": _build_coil,
    "loft": _build_loft,
    "union": _build_union,
    "subtract": _build_subtract,
    "intersect": _build_intersect,
    "hole": _build_hole,
    "shell": _build_shell,
    "offset": _build_offset,
    "pattern_linear": _build_pattern_linear,
    "pattern_circular": _build_pattern_circular,
    "mirror": _build_mirror,
    "transform": _build_transform,
    "bend": _build_bend,
}


def builder_for(kind: str) -> Builder:
    builder = BUILDERS.get(kind)
    if builder is None:
        raise UnsupportedFeatureError(
            "the implicit backend has no builder for this feature kind",
            kind=kind,
            supported=sorted(BUILDERS),
            hint="the exact B-Rep backend may support it; this backend declares "
            "the gap rather than approximating the feature",
        )
    return builder


def supported_kinds() -> tuple[str, ...]:
    return tuple(sorted(BUILDERS))


__all__ = [
    "BACKEND_IDENTITY",
    "BUILDERS",
    "BuildContext",
    "BackendError",
    "UnsupportedFeatureError",
    "builder_for",
    "supported_kinds",
]
