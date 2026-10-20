"""Resolving a requirement's measurement binding against a compiled part.

One function, :func:`resolve_measurement`, turns a binding like
``entity:shaft.bore:diameter`` into a :class:`~forge_units.Quantity` measured
from the actual geometry -- or into an honest reason it could not be measured.

The reason matters as much as the value. A binding that names a parameter the
document does not declare, an interface that no longer resolves, or a mass on a
component with no material, all produce a ``BLOCKED`` gate naming what was
missing. None of them produce a number.
"""

from __future__ import annotations

import re

import math
from dataclasses import dataclass
from typing import Any, Mapping

from forge_analysis import (
    bending_stress,
    cantilever_root_moment,
    MaterialError,
    bearing_stress,
    direct_shear_stress,
    lookup,
    safety_factor,
)
from forge_geom import MassProperties
from forge_ir import Component
from forge_ir.measurements import MeasurementBinding, MeasurementError, parse_measurement
from forge_kernel import CompiledPart, SelectionError
from forge_units import Q, Quantity


@dataclass(frozen=True, slots=True)
class Measurement:
    """A measured value, or a stated reason there is none."""

    value: Quantity | None
    #: Empty when the measurement succeeded.
    blocked_reason: str = ""
    method: str = "exact_geometry"
    limitations: tuple[str, ...] = ()
    detail: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.detail is None:
            object.__setattr__(self, "detail", {})

    @property
    def ok(self) -> bool:
        return self.value is not None and not self.blocked_reason


def _blocked(reason: str, **detail: Any) -> Measurement:
    return Measurement(value=None, blocked_reason=reason, detail=detail)


def resolve_measurement(
    binding_text: str,
    *,
    component: Component,
    part: CompiledPart,
    properties: MassProperties,
    surface_area: Quantity | None = None,
    wall_thickness: Quantity | None = None,
    load: Quantity | None = None,
    hollows: Any = None,
) -> Measurement:
    """Measure whatever ``binding_text`` names, on this compiled part.

    ``hollows`` is the sealed voids verification already found on the
    surface it extracted -- ``(volume_mm3, centre)`` each -- so they are not
    looked for twice."""
    try:
        binding = parse_measurement(binding_text)
    except MeasurementError as error:
        return _blocked(str(error), binding=binding_text)

    kind = binding.kind

    # -- bulk properties ------------------------------------------------
    if kind == "volume":
        return Measurement(properties.volume, limitations=_enclosure_note(properties))
    if kind == "surface_area":
        if surface_area is None:
            return _blocked("no surface mesh was extracted")
        return Measurement(
            surface_area,
            method="sampling",
            limitations=("area from the extracted surface mesh, not exact",),
        )
    if kind == "mass":
        if not component.material:
            return _blocked(
                "the component declares no material, so its mass cannot be "
                "computed. Name a specific grade and condition."
            )
        try:
            material = lookup(component.material)
        except MaterialError as error:
            return _blocked(error.message, material=component.material)
        return Measurement(
            properties.mass(material.density),
            limitations=_enclosure_note(properties)
            + (f"density from {material.identifier} ({material.basis})",),
        )

    if kind.startswith("bounding_box_"):
        axis = "xyz".index(kind[-1])
        # Where it starts and ends, not only how long it is: a calf shell
        # 400 of 430 mm tall said nothing of which tab came out short, and
        # it was both, 15 mm at each end.
        try:
            from forge_units import parse_unit

            mm = parse_unit("mm")
            low = float(properties.bounding_box_lo[axis].to(
                mm).magnitude.midpoint)
            high = float(properties.bounding_box_hi[axis].to(
                mm).magnitude.midpoint)
            spans = {"spans": f"{kind[-1]} = {low:.1f} to {high:.1f} mm"}
        except Exception:  # noqa: BLE001 - the size alone, as before
            spans = {}
        return Measurement(
            properties.bounding_box_size()[axis],
            limitations=_enclosure_note(properties),
            detail=spans,
        )
    if kind in ("footprint_side", "extent_side"):
        # Which side of the part a figure said of the whole part is, is the
        # one thing the brief does not settle -- "40 mm wide" is X or Y
        # depending on how the part was turned. The nearer side is the one
        # the figure can be about; any other is further from it still.
        sizes = properties.bounding_box_size()
        axes = (0, 1) if kind == "footprint_side" else (0, 1, 2)
        figure = float(binding.argument)
        axis = min(axes, key=lambda i: abs(
            float(sizes[i].magnitude.midpoint) - figure))
        return Measurement(
            sizes[axis], limitations=_enclosure_note(properties),
            detail={"axis": "xyz"[axis]})
    if kind.startswith("centre_of_mass_"):
        axis = "xyz".index(kind[-1])
        return Measurement(
            properties.centre_of_mass[axis], limitations=_enclosure_note(properties)
        )

    if kind == "sealed_voids":
        return _sealed_voids(part, hollows)

    if kind == "minimum_wall_thickness":
        if wall_thickness is None:
            return _blocked("wall thickness was not sampled")
        return Measurement(
            wall_thickness,
            method="sampling",
            limitations=(
                "sampled by inward ray marching; finds only thin walls a sample "
                "landed on, so it is an upper bound on the true minimum",
            ),
        )

    # -- document lookups -------------------------------------------------
    if kind == "parameter":
        name = binding.argument
        if name not in part.resolution:
            return _blocked(
                f"no parameter named '{name}' is declared",
                available=list(part.resolution.order)[:30],
            )
        return Measurement(part.resolution[name])

    if kind == "feature_count":
        # Without a tag this counts every feature of the kind, which is the
        # right answer to the wrong question whenever a part has holes for more
        # than one purpose: a plate with a central bore and four bolt holes has
        # five `hole` features, and "there shall be four mounting holes" then
        # fails against a perfectly good design. The tag is how a requirement
        # says which ones it means.
        matching = [
            feature for feature in component.features if feature.kind == binding.argument
        ]
        if binding.sub_argument:
            tagged = [f for f in matching if binding.sub_argument in f.tags]
            anywhere = [f for f in component.features
                        if binding.sub_argument in f.tags]
            # A tagged pattern is as many of the thing as it makes: "two
            # hinge tabs" built as one tab patterned twice is two tabs, and
            # counted as one feature it failed a calf shell that had both.
            def instances(feature: Any) -> int:
                if feature.kind in ("pattern_linear", "pattern_circular"):
                    count = feature.parameters.get("count")
                    # A count driven by a parameter -- `{"expression":
                    # "rod_count"}` -- is resolved like any other. Read as
                    # its literal it was None, so one: the hydra's six rods,
                    # one circular pattern, counted 1, and the repair round
                    # "fixed" it by patterning the ring five more times.
                    try:
                        return max(1, int(count.resolve(
                            _the_resolution_of(component))))
                    except Exception:  # noqa: BLE001 - as written, or one
                        value = getattr(count, "value", None)
                    try:
                        return max(1, int(value))
                    except (TypeError, ValueError):
                        return 1
                if feature.kind == "mirror":
                    return 2
                return 1
            if not tagged and anywhere and binding.argument == "hole":
                # Openings cut another way and tagged for what they are: "one
                # rectangular access opening", built as an extrude taken away
                # from the shell by a `subtract` carrying `access_opening`.
                # A count of `hole`s tagged so read nothing, the requirement
                # was unbound and reported NOT_TESTED, and the shell, whose
                # opening was there, could not be released.
                cut, which = _openings_cut_by_the_tag(
                    component, binding.sub_argument, instances)
                if cut:
                    return Measurement(Q(cut), detail={
                        "counted": which,
                        "note": "no hole carries the tag; counted the "
                                "openings the cuts carrying it make"})
            if not tagged and matching:
                return _blocked(
                    f"no {binding.argument} feature is tagged "
                    f"'{binding.sub_argument}', so there is nothing to count",
                    tags_present=sorted({t for f in matching for t in f.tags})[:20],
                    hint=(
                        f"tag the {binding.argument} features this requirement "
                        f"is about with \"tags\": [\"{binding.sub_argument}\"], "
                        "or bind the requirement to "
                        f"`feature_count:{binding.argument}` to count all "
                        f"{len(matching)} of them"
                    ),
                )
            if any(f.kind in ("pattern_linear", "pattern_circular", "mirror")
                   for f in tagged or anywhere):
                pool = tagged if tagged else anywhere
                if tagged or not matching:
                    return Measurement(Q(sum(instances(f) for f in pool)),
                                       detail={
                        "counted": [f"{f.identifier} x{instances(f)}"
                                    for f in pool],
                        "note": "a tagged pattern counts as each thing it "
                                "makes"})
            if not matching and anywhere:
                # No feature of the kind at all: the design built these
                # another way -- a tongue as a box, not an extrude -- and
                # tagged them for what they are. Counted by kind alone, a
                # part with both its tongues failed for having none. With
                # nothing of the kind and nothing tagged, there are none:
                # zero, which "no mounting holes" on a dome is right to read.
                return Measurement(Q(len(anywhere)), detail={
                    "counted": [f.identifier for f in anywhere],
                    "note": f"no {binding.argument} feature; counted what "
                            f"carries '{binding.sub_argument}' instead"})
            matching = tagged
        if binding.argument == "coil" and matching:
            # A spring's coils are its turns. "10 coils" built as one coil of
            # ten turns -- the spring the brief describes -- counted 1, and
            # the repair split it into ten one-turn coils joined end to end,
            # whose joins left the surface no longer cleanly closed, and the
            # spring was held for it.
            turns = [_the_turns_of(feature, component) for feature in matching]
            return Measurement(Q(sum(turns)), detail={
                "counted": [f"{f.identifier} x{t:g} turns"
                            for f, t in zip(matching, turns)],
                "note": "a coil counts as many coils as it has turns"})
        return Measurement(Q(len(matching)))

    if kind == "roundness_about_z":
        return _roundness_about_z(part)

    if kind == "roundness":
        return _roundness(part)

    if kind == "roundness_every_way":
        return _roundness_every_way(part)

    if kind == "holes_of_diameter":
        return _holes_of_diameter(component, part, binding)

    if kind == "openings_of_size":
        return _openings_of_size(part, binding.argument)

    if kind == "opening_at":
        return _an_opening_at(part, binding)

    if kind == "openings_on_circle":
        return _openings_on_a_circle(part, binding)

    if kind == "openings_apart":
        return _openings_apart(part, binding)
    if kind == "hole_at":
        return _hole_at(component, part, binding)

    if kind == "walls_crossed":
        return _walls_crossed(component, part, binding)

    if kind == "windows_of_size":
        return _windows_of_size(part, properties, binding.argument,
                                binding.sub_argument or "")

    if kind == "counterbores":
        return _counterbores(part, binding)

    if kind == "standing_at":
        return _standing_at(part, binding)

    if kind in ("wall_thickness", "floor_thickness", "opening_depth"):
        return _a_container(part, properties, kind,
                            binding.argument or "top")

    if kind == "flat_face":
        return _a_flat_face(part, properties, binding.argument)

    if kind in ("bend_angle", "bend_count", "bend_centre", "bend_spread",
                "bend_off_centre", "bent_along", "bend_convex"):
        return _the_bends(part, kind)

    if kind == "flat_extent_side":
        return _a_flat_extent(part, float(binding.argument))

    if kind == "ends_round":
        return _ends_round(part, binding)

    if kind == "angle_between":
        return _angle_between(component, part, binding)

    if kind == "interface_size":
        try:
            interface = component.interface(binding.argument)
        except Exception:  # noqa: BLE001 - a dangling id is a blocked measurement
            return _blocked(
                f"no interface named '{binding.argument}' is declared",
                available=[i.identifier for i in component.interfaces],
            )
        entity = _entity_or_none(part, interface.geometry)
        if entity is None:
            return _blocked(
                f"interface '{binding.argument}' names geometry that does not "
                f"resolve: {interface.geometry}"
            )
        measured = _entity_dimension(entity, "diameter")
        if measured is None:
            return _blocked(
                f"interface '{binding.argument}' has no measurable size on a "
                f"{entity.entity_type}"
            )
        return Measurement(measured, detail={"token": entity.token})

    if kind == "entity":
        entity = _entity_or_none(part, binding.argument)
        if entity is None:
            return _blocked(
                f"no live geometry is published as '{binding.argument}'",
                available=list(part.geometry_map.names())[:30],
            )
        measured = _entity_dimension(entity, binding.sub_argument)
        if measured is None:
            return _blocked(
                f"'{binding.argument}' has no dimension "
                f"'{binding.sub_argument}'",
                available=sorted(entity.dimensions) + ["diameter"],
            )
        return Measurement(measured, detail={"token": entity.token})

    # -- derived structural margins ----------------------------------------
    if kind == "safety_factor":
        return _safety_factor(binding, component, part, load)

    return _blocked(f"measurement '{binding_text}' is not implemented")


#: Samples along each line a container is measured on, before each crossing
#: is bisected to well under a micrometre.
_SAMPLES_ALONG_A_LINE = 4001


def _the_turns_of(feature: Any, component: Any) -> float:
    """How many turns a coil makes, resolved like any other parameter; one
    when it cannot be read."""
    turns = feature.parameters.get("turns")
    try:
        value = turns.resolve(_the_resolution_of(component))
        magnitude = getattr(value, "magnitude", value)
        figure = float(getattr(magnitude, "midpoint", magnitude))
    except Exception:  # noqa: BLE001 - as written, or one
        try:
            figure = float(getattr(turns, "value", turns))
        except (TypeError, ValueError):
            return 1.0
    return figure if figure > 0 else 1.0


def _the_resolution_of(component: Any) -> Any:
    """The component's parameters resolved, or None when they do not."""
    try:
        return component.parameters.resolve()
    except Exception:  # noqa: BLE001 - unresolvable: literals only
        return None


def _across_the_wall(part: CompiledPart, through: list[float], axis: int,
                     run: tuple[float, float]) -> float:
    """A wall's thickness from where a line crosses it: square to its faces.

    The line runs along an axis; a wall that leans -- the side of a calf
    tapering to its ankle, a drafted box -- is crossed on the slant, and the
    run of material is longer than the wall is thick by 1/cos of the lean.
    The surface normal where the line goes in and where it comes out gives
    the lean, so the run is turned square to the wall. A wall that does not
    lean is unchanged; one crossed nearly edge-on is left as read.
    """
    import numpy as np

    length = run[1] - run[0]
    ends = np.tile(np.asarray(through, dtype=float), (2, 1))
    ends[0, axis], ends[1, axis] = run[0], run[1]
    try:
        normals = np.asarray(part.solid.gradient(ends, step=1e-4), dtype=float)
    except Exception:  # noqa: BLE001 - no normal, no correction
        return length
    sizes = np.linalg.norm(normals, axis=1)
    if not np.all(sizes > 1e-9):
        return length
    cosines = np.abs(normals[:, axis]) / sizes
    if float(cosines.min()) < 0.5:
        return length
    return length * float(cosines.mean())


def _material_along(
    part: CompiledPart, lo: list[float], hi: list[float], axis: int,
    through: list[float],
) -> list[tuple[float, float]]:
    """Where there is material on one line parallel to `axis`, in mm.

    The line runs through `through` (its coordinate along `axis` ignored)
    from just below the part to just above it. Each run of material is
    returned as its start and end along the axis, each crossing bisected
    between the last empty sample and the first solid one.
    """
    import numpy as np

    start, end = lo[axis] - 1.0, hi[axis] + 1.0
    along = np.linspace(start, end, _SAMPLES_ALONG_A_LINE)
    points = np.tile(np.asarray(through, dtype=float), (along.size, 1))
    points[:, axis] = along
    solid = np.asarray(part.solid(points), dtype=float) < 0.0

    def at(t: float) -> bool:
        point = np.asarray(through, dtype=float).copy()
        point[axis] = t
        return float(part.solid(point[None, :])[0]) < 0.0

    def crossing(inside: float, outside: float) -> float:
        for _ in range(40):
            middle = 0.5 * (inside + outside)
            if at(middle):
                inside = middle
            else:
                outside = middle
        return 0.5 * (inside + outside)

    runs: list[tuple[float, float]] = []
    index = 0
    while index < along.size:
        if not solid[index]:
            index += 1
            continue
        first = index
        while index + 1 < along.size and solid[index + 1]:
            index += 1
        last = index
        begin = (crossing(float(along[first]), float(along[first - 1]))
                 if first > 0 else float(along[first]))
        finish = (crossing(float(along[last]), float(along[last + 1]))
                  if last + 1 < along.size else float(along[last]))
        runs.append((begin, finish))
        index += 1
    return runs


# ----------------------------------------------------------------------
# Bent parts
# ----------------------------------------------------------------------
def _the_bend_chain(solid: Any) -> tuple[list[Any], Any] | None:
    """The bends a part was made with, innermost first, and the flat solid.

    None when there are none, or when they are not one chain -- two bent
    pieces joined side by side -- since then no one flat part was bent.
    """
    from dataclasses import fields, is_dataclass

    from forge_geom import Bend

    found: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, Bend):
            found.append(node)
        if not is_dataclass(node):
            return
        for item in fields(node):
            value = getattr(node, item.name, None)
            if isinstance(value, (tuple, list)):
                for child in value:
                    if is_dataclass(child):
                        walk(child)
            elif is_dataclass(value):
                walk(value)

    walk(solid)
    if not found:
        return None
    # One chain: each bend's solid holds the next one in.
    ordered = []
    for bend in found:
        inner = [other for other in found if other is not bend
                 and _holds(bend.solid, other)]
        ordered.append((len(inner), bend))
    ordered.sort(key=lambda pair: pair[0])
    chain = [bend for _, bend in ordered]
    if [count for count, _ in ordered] != list(range(len(chain))):
        return None
    return chain, chain[0].solid


def _holds(node: Any, target: Any) -> bool:
    from dataclasses import fields, is_dataclass

    if node is target:
        return True
    if not is_dataclass(node):
        return False
    for item in fields(node):
        value = getattr(node, item.name, None)
        children = value if isinstance(value, (tuple, list)) else (value,)
        if any(is_dataclass(c) and _holds(c, target) for c in children):
            return True
    return False


def _flat_to_part(chain: list[Any] | None):
    """The map from the flat part to the finished one: each bend in turn."""
    import numpy as np

    def forward(points: Any) -> Any:
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        for bend in chain or ():
            points = bend.forward(points)
        return points

    return forward


def _the_flat_part(part: CompiledPart):
    """The finished part laid flat: a membership test in its flat frame, and
    the box it lies in there.

    Every point of the flat frame is carried through the bends to where it
    ended up and asked whether the finished part has material there, so a
    hole drilled after bending is a hole in the flat part too.
    """
    import numpy as np

    found = _the_bend_chain(part.solid)
    chain, flat = (found if found else (None, part.solid))
    forward = _flat_to_part(chain)
    envelope = flat.envelope

    def inside(points: Any) -> Any:
        return np.asarray(part.solid(forward(points)), dtype=float) < 0.0

    return inside, envelope, forward, chain


def _ends_round(part: CompiledPart, binding: MeasurementBinding) -> Measurement:
    """How far the part's two ends are from semicircles of a radius, in mm.

    "A flat PLA strip 110 mm long, 16 mm wide and 2 mm thick with both ends
    fully rounded." The exo arm's wrist link strip passed 25 of 25 with its
    ends square: nothing measured them, and the last look, shown a picture
    of square ends, said they were round. Seen from above, through the
    middle of the part's thickness, each end along its longer side is read
    where it is: its tip on the middle line, then its half-width at a
    tenth, a quarter, a half, three quarters of the radius back from the
    tip and at the radius itself, on each side -- against a semicircle's
    `sqrt(d (2 r - d))`. The measurement is the worst of the twenty.
    """
    import numpy as np

    radius = float(binding.argument)
    try:
        frame = _the_faces_of_the_flat_part(part)
    except Exception:  # noqa: BLE001 - said as not measured
        frame = None
    if frame is None:
        return _blocked("the part could not be laid flat and sampled")
    inside = frame["inside"]
    lo = np.asarray(frame["lo"], dtype=float) - 1.0
    hi = np.asarray(frame["hi"], dtype=float) + 1.0
    a, b = frame["axes"]
    along, across = (a, b) if hi[a] - lo[a] >= hi[b] - lo[b] else (b, a)
    level = (float(frame["bottom"]) + float(frame["top"])) / 2.0

    def where_material_starts(starts: Any, axis: int, sign: float,
                              length: float) -> Any:
        """Along each ray from `starts`, `sign` along `axis`: the distance
        to the first material, to a micron; nan where there is none, or
        where the ray starts in it."""
        count = int(np.ceil(length / 0.02)) + 2
        t = np.linspace(0.0, length, count)
        points = np.repeat(starts[:, None, :], count, axis=1)
        points[:, :, axis] += sign * t[None, :]
        hit = np.asarray(inside(points.reshape(-1, 3)),
                         dtype=bool).reshape(len(starts), count)
        first = np.where(hit.any(axis=1), hit.argmax(axis=1), 0)
        usable = first > 0
        low = t[np.maximum(first - 1, 0)].astype(float)
        high = t[first].astype(float)
        for _ in range(26):
            middle = (low + high) / 2.0
            probe = starts.copy()
            probe[:, axis] += sign * middle
            now = np.asarray(inside(probe), dtype=bool)
            high = np.where(now, middle, high)
            low = np.where(now, low, middle)
        return np.where(usable, high, np.nan)

    def start(at_along: float, at_across: float) -> Any:
        point = np.zeros(3)
        point[along], point[across] = at_along, at_across
        point[frame["thin"]] = level
        return point

    # The part's own middle line and tips, not its envelope's.
    halfway = (lo[along] + hi[along]) / 2.0
    span = float(hi[across] - lo[across])
    above = where_material_starts(np.array([start(halfway, hi[across])]),
                                  across, -1.0, span)
    below = where_material_starts(np.array([start(halfway, lo[across])]),
                                  across, 1.0, span)
    if np.isnan(above).any() or np.isnan(below).any():
        return _blocked("the part's sides could not be found across it")
    top_side, bottom_side = hi[across] - above[0], lo[across] + below[0]
    centre = (top_side + bottom_side) / 2.0
    ends = []
    for at, sign in ((hi[along], -1.0), (lo[along], 1.0)):
        found = where_material_starts(np.array([start(at, centre)]), along,
                                      sign, float(hi[along] - lo[along]))
        if np.isnan(found).any():
            return _blocked("the part has no material along its middle line")
        ends.append((float(at + sign * found[0]), sign))
    length = ends[0][0] - ends[1][0]
    if length < 2.0 * radius - 0.5:
        return _blocked(
            f"the part is {length:.2f} mm long: too short for two ends each "
            f"a semicircle of {radius:g} mm")
    fractions = (0.1, 0.25, 0.5, 0.75, 1.0)
    readings: list[dict[str, Any]] = []
    worst = 0.0
    for tip, inward in ends:
        for fraction in fractions:
            back = fraction * radius
            expected = float(np.sqrt(back * (2.0 * radius - back)))
            at = tip + inward * back
            above = where_material_starts(
                np.array([start(at, hi[across])]), across, -1.0,
                float(hi[across] - centre))
            below = where_material_starts(
                np.array([start(at, lo[across])]), across, 1.0,
                float(centre - lo[across]))
            halves = [
                0.0 if np.isnan(above[0]) else float(
                    hi[across] - above[0] - centre),
                0.0 if np.isnan(below[0]) else float(
                    centre - (lo[across] + below[0]))]
            for half in halves:
                off = abs(half - expected)
                worst = max(worst, off)
                readings.append({"end": "high" if inward < 0 else "low",
                                 "back_mm": round(back, 3),
                                 "half_width_mm": round(half, 3),
                                 "semicircle_mm": round(expected, 3)})
    return Measurement(
        Q(round(worst, 4), "mm"),
        method="sampling",
        detail={"axis_along": "xyz"[along], "radius_mm": radius,
                "tips_mm": [round(ends[1][0], 3), round(ends[0][0], 3)],
                "readings": readings},
        limitations=("read through the middle of the part's thickness, seen "
                     "from above, at five places along each end",),
    )


def _a_flat_extent(part: CompiledPart, figure: float) -> Measurement:
    """The part's size laid flat, along whichever axis is nearest the figure.

    "A curved plate 70 mm long": a plate bent keeps its length along its
    middle, so 70 mm is its length laid flat, not the straight span it ends
    up with. With no bend this is the part's own extent.
    """
    import numpy as np

    from forge_units import Interval

    inside, envelope, _, chain = _the_flat_part(part)
    if envelope.is_empty:
        return _blocked("the part has no envelope to lay flat")
    lo = np.asarray(envelope.lo, dtype=float) - 0.5
    hi = np.asarray(envelope.hi, dtype=float) + 0.5
    size = hi - lo
    step = max(float(np.prod(size) / 250_000.0) ** (1.0 / 3.0), 0.05)
    axes = [np.arange(lo[i], hi[i] + step, step) for i in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    solid = inside(grid)
    if not solid.any():
        return _blocked("the part laid flat has no material")
    material = grid[solid]
    extents = []
    for axis in range(3):
        ends = []
        for sign in (-1.0, 1.0):
            # Every sample on the outermost layer, not the first one found:
            # a plate with rounded corners has its outermost samples along
            # the whole straight edge, and one picked near a corner was
            # bisected out to the arc -- 74.5 mm on a 75 mm plate.
            along = material[:, axis] * sign
            layer = material[along >= along.max() - 1e-9]
            if layer.shape[0] > 256:
                layer = layer[np.linspace(0, layer.shape[0] - 1, 256).astype(
                    int)]
            inner = layer[:, axis].copy()
            outer = inner + sign * step
            for _ in range(40):
                middle = 0.5 * (inner + outer)
                probe = layer.copy()
                probe[:, axis] = middle
                hit = inside(probe)
                inner = np.where(hit, middle, inner)
                outer = np.where(hit, outer, middle)
            reached = 0.5 * (inner + outer)
            ends.append(float(reached.max() if sign > 0 else reached.min()))
        extents.append(abs(ends[1] - ends[0]))
    axis = min(range(3), key=lambda i: abs(extents[i] - figure))
    # Good to the grid's step at a slanted edge: the extremes are bisected
    # along the axis from the furthest sample found, which on a flat part's
    # faces is exact and on a corner can miss by part of a step.
    return Measurement(
        Q(extents[axis], "mm"), method="sampling",
        limitations=(
            "measured on the part laid flat"
            + (f", its {len(chain)} bend(s) undone" if chain else
               " (it has no bend)")
            + "; each end bisected to well under a micrometre",),
        detail={"axis": "xyz"[axis],
                "flat_extents_mm": [round(e, 4) for e in extents]})


def _the_bends(part: CompiledPart, kind: str) -> Measurement:
    """How far the finished part turns, how many bends, and where the first is.

    Measured on the finished surface: along the middle of the part's broad
    face, laid flat, each point is carried to where it ended up and the
    finished surface's own normal is read there. The angle between the
    first normal and each later one, about the bend axis, is the part's turn
    so far; the turn at the far end, summed over every change of direction,
    is the bend angle. A flat part turns 0 degrees, however it was drawn.
    """
    import numpy as np

    inside, envelope, forward, chain = _the_flat_part(part)
    lo = np.asarray(envelope.lo, dtype=float)
    hi = np.asarray(envelope.hi, dtype=float)
    size = hi - lo
    thin = int(np.argmin(size))
    lengths = [i for i in range(3) if i != thin]
    centre = (lo + hi) / 2.0

    def top_at(points: Any) -> Any:
        """The broad face's outer point above each point, or NaN."""
        tops = np.full(points.shape[0], np.nan)
        heights = np.linspace(hi[thin] + 0.5, lo[thin] - 0.5, 161)
        column = np.repeat(points[:, None, :], heights.size, axis=1)
        column[:, :, thin] = heights[None, :]
        solid = inside(column.reshape(-1, 3)).reshape(points.shape[0], -1)
        hit = solid.any(axis=1)
        first = np.argmax(solid, axis=1)
        rows = np.flatnonzero(hit)
        if rows.size == 0:
            return tops
        k = first[rows]
        inner = heights[k]
        outer = np.where(k > 0, heights[np.maximum(k - 1, 0)], inner + 1.0)
        probe = points[rows].copy()
        for _ in range(40):
            middle = 0.5 * (inner + outer)
            probe[:, thin] = middle
            solid_now = inside(probe)
            inner = np.where(solid_now, middle, inner)
            outer = np.where(solid_now, outer, middle)
        tops[rows] = inner
        return tops

    best = None
    for along in lengths:
        across = next(i for i in lengths if i != along)
        count = int(min(max(size[along] / 0.25, 64), 600))
        # Short of the very ends: a reading on an end's edge takes the end
        # face's normal for the broad face's, a quarter turn out -- on a
        # plate curved both ways from its middle, that read as 90 degrees
        # of bend. The curve is carried on to each end at its own rate.
        inset = min(0.75, 0.05 * float(size[along]))
        us = np.linspace(lo[along] + inset, hi[along] - inset, count)
        normals = []
        positions = []
        places = []
        # Three lines across the face, so a hole on one of them is not a
        # gap in the reading.
        for offset in (0.0, 0.2, -0.2):
            points = np.tile(centre, (count, 1))
            points[:, along] = us
            points[:, across] = centre[across] + offset * size[across]
            tops = top_at(points)
            ok = ~np.isnan(tops)
            if ok.sum() < 8:
                continue
            surface = points[ok].copy()
            surface[:, thin] = tops[ok] - 1e-4
            where = forward(surface)
            step = 1e-3
            gradient = np.zeros_like(where)
            for axis in range(3):
                shift = np.zeros(3)
                shift[axis] = step
                gradient[:, axis] = (
                    np.asarray(part.solid(where + shift), dtype=float)
                    - np.asarray(part.solid(where - shift), dtype=float)
                ) / (2.0 * step)
            norm = np.linalg.norm(gradient, axis=1)
            good = (norm > 0.9) & (norm < 1.1)
            normals.append(gradient[good] / norm[good, None])
            positions.append(surface[good, along])
            places.append(where[good])
        if not normals:
            continue
        n = np.concatenate(normals)
        u = np.concatenate(positions)
        x = np.concatenate(places)
        order = np.argsort(u)
        n, u, x = n[order], u[order], x[order]
        if n.shape[0] < 8:
            continue
        # The bend axis: the direction the normals do not turn about.
        tensor = n.T @ n
        values, vectors = np.linalg.eigh(tensor)
        axis_b = vectors[:, 0]
        first = n[0] - axis_b * float(n[0] @ axis_b)
        first /= max(float(np.linalg.norm(first)), 1e-12)
        side = np.cross(axis_b, first)
        turn = np.degrees(np.arctan2(n @ side, n @ first))
        # Per bin of a millimetre, the median: holes' rims and corners
        # read as outliers and drop out.
        bins = np.floor((u - u[0]) / 1.0).astype(int)
        keys = np.unique(bins)
        bu = np.array([np.median(u[bins == k]) for k in keys])
        bt = np.array([np.median(turn[bins == k]) for k in keys])
        changes = np.diff(bt)
        moving = np.abs(changes) > 0.02
        total = float(np.abs(changes[moving]).sum())
        # A curve running out to an end of the part turns on past the last
        # reading: carried on at its own rate to the end.
        if bu.size >= 3:
            for near, next_, end in ((0, 1, float(lo[along])),
                                     (-1, -2, float(hi[along]))):
                if moving[near if near == 0 else -1]:
                    rate = abs((bt[next_] - bt[near]) / max(
                        abs(bu[next_] - bu[near]), 1e-9))
                    total += rate * abs(bu[near] - end)
        # Which way it curves: the face read here is the one that was up
        # when flat. Moving along it, its normal swings the way the surface
        # goes on an arch (the face on the outside) and against it on a
        # dish; summed over the turning, weighted by how far it turns.
        dn = np.diff(n, axis=0)
        dx = np.diff(x, axis=0)
        swing = np.einsum("ij,ij->i", dn, dx)
        convex = float(swing.sum())
        if best is None or total > best[0]:
            best = (total, bu, bt, moving, along, convex)
    if best is None:
        return _blocked("no broad face was found to read the part's turn on")
    total, bu, bt, moving, along, convex = best
    # Separate bends: runs of turning, apart by more than 2 mm of flat.
    runs: list[list[int]] = []
    for index in np.flatnonzero(moving):
        if runs and bu[index] - bu[runs[-1][-1] + 1] <= 2.0:
            runs[-1].append(int(index))
        else:
            runs.append([int(index)])
    note = ("read on the finished surface's own normals, along the middle "
            "of its broad face laid flat, in 1 mm steps"
            + (f"; {len(chain)} bend(s) in its making" if chain else ""),)
    if kind == "bend_angle":
        return Measurement(Q(round(total, 3), "deg"), method="sampling",
                           limitations=note,
                           detail={"bends": len(runs), "axis": "xyz"[along]})
    if kind == "bend_count":
        return Measurement(Q(len(runs)), method="sampling",
                           limitations=note)
    if kind == "bend_convex":
        if not runs:
            return Measurement(Q(0), method="sampling", limitations=note,
                               detail={"note": "the part does not bend"})
        return Measurement(
            Q(1 if convex > 0 else -1), method="sampling", limitations=note,
            detail={"note": "1: the face that was up when flat is on the "
                            "outside of the bend (an arch); -1: on the inside "
                            "(a dish)"})
    if kind == "bent_along":
        # Which way it bends: the part's length, laid flat, in the
        # direction it turns along -- a 70 by 50 plate folded across its
        # width turns along its 70.
        if not runs:
            return _blocked("the part does not bend, so it bends along "
                            "nothing")
        extent = _a_flat_extent(part, float(hi[along] - lo[along]))
        flat = extent.detail.get("flat_extents_mm") if extent.ok else None
        value = float(flat["xyz".index(extent.detail["axis"])]) if flat and \
            extent.detail.get("axis") == "xyz"[along] else float(
                hi[along] - lo[along])
        if flat:
            value = float(flat[along])
        return Measurement(Q(round(value, 4), "mm"), method="sampling",
                           limitations=note, detail={"axis": "xyz"[along]})
    if not runs:
        return _blocked("the part does not bend, so it has no bend "
                        + {"bend_centre": "centre", "bend_spread": "spread",
                           "bend_off_centre": "centre"}[kind])
    run = runs[0]
    start, end = bu[run[0]], bu[run[-1] + 1]
    turned = bt[run[0]], bt[run[-1] + 1]
    halfway = 0.5 * (turned[0] + turned[1])
    segment = bt[run[0]:run[-1] + 2]
    places = bu[run[0]:run[-1] + 2]
    centre_u = float(np.interp(halfway, segment, places)) if segment[-1] >= \
        segment[0] else float(np.interp(halfway, segment[::-1], places[::-1]))
    flat_lo, flat_hi = float(lo[along]), float(hi[along])
    from_end = min(centre_u - flat_lo, flat_hi - centre_u)
    if kind == "bend_spread":
        # From the first reading that turned to the last, each a bin's
        # width from where the turning really starts and ends; carried to
        # the part's end where the curve runs out to it.
        first, last = float(bu[run[0]]), float(bu[run[-1] + 1])
        if run[0] == 0:
            first = flat_lo
        if run[-1] + 1 == bu.size - 1:
            last = flat_hi
        return Measurement(
            Q(round(last - first, 3), "mm"), method="sampling",
            limitations=note + ("good to the 1 mm step it is read in",),
            detail={"bend_from_mm": round(first - flat_lo, 3),
                    "bend_to_mm": round(last - flat_lo, 3)})
    if kind == "bend_off_centre":
        middle = 0.5 * (flat_lo + flat_hi)
        return Measurement(
            Q(round(abs(centre_u - middle), 3), "mm"), method="sampling",
            limitations=note, detail={"axis": "xyz"[along]})
    return Measurement(
        Q(round(from_end, 3), "mm"), method="sampling", limitations=note,
        detail={"bend_from_mm": round(float(start - flat_lo), 3),
                "bend_to_mm": round(float(end - flat_lo), 3)})


#: Lines across a part searched for its outermost point on a side, each
#: way, and the samples along each.
_LINES_ACROSS = 41
_SAMPLES_ON_A_SEARCH_LINE = 1201
#: How far inside its outermost plane a face is read, in mm: under any
#: printed or machined tolerance, and deep enough that a curved surface
#: tangent to the plane shows as the speck it is.
_A_FACE_INSET = 0.05


def _a_flat_face(
    part: CompiledPart, properties: MassProperties, side: str
) -> Measurement:
    """The area of the part lying flat in its outermost plane on one side.

    "Half of a 50 mm sphere, flat side up": a dome flat side up and one
    flat side down have the same three extents, and a `bounding_box_*`
    equality is read whichever way round the part lies, so nothing could
    tell them apart -- one was released the wrong way up with every gate
    passing. A flat face is a real side. The part's outermost point that
    way is found on lines across it, bisected, and the material in the
    plane 0.05 mm inside it is counted on a fine grid: a dome's whole disc
    on its flat side, a speck where its curve touches the plane.
    """
    import numpy as np

    from forge_ir.measurements import CONTAINER_SIDES
    from forge_units import parse_unit

    if side not in CONTAINER_SIDES:
        return _blocked(f"`flat_face:{side}` names no side")
    up, toward = CONTAINER_SIDES[side]
    across = [axis for axis in range(3) if axis != up]
    millimetre = parse_unit("mm")
    lo = [float(q.to(millimetre).magnitude.lo) for q in
          properties.bounding_box_lo]
    hi = [float(q.to(millimetre).magnitude.hi) for q in
          properties.bounding_box_hi]
    # The outermost point that way: on lines along `up` through a grid
    # across the part, the last solid sample from that end, then bisected.
    a = np.linspace(lo[across[0]], hi[across[0]], _LINES_ACROSS)
    b = np.linspace(lo[across[1]], hi[across[1]], _LINES_ACROSS)
    along = np.linspace(lo[up] - 1.0, hi[up] + 1.0, _SAMPLES_ON_A_SEARCH_LINE)
    if toward > 0:
        along = along[::-1]
    A, B, T = np.meshgrid(a, b, along, indexing="ij")
    points = np.empty((A.size, 3))
    points[:, across[0]] = A.ravel()
    points[:, across[1]] = B.ravel()
    points[:, up] = T.ravel()
    solid = (np.asarray(part.solid(points), dtype=float) < 0.0).reshape(
        A.shape)
    hit = solid.any(axis=2)
    if not hit.any():
        return _blocked("no material was found on any line across the part")
    first = np.where(hit, solid.argmax(axis=2), along.size)
    i, j = np.unravel_index(int(first.argmin()), first.shape)
    k = int(first[i, j])
    through = np.zeros(3)
    through[across[0]], through[across[1]] = a[i], b[j]

    def inside(t: float) -> bool:
        point = through.copy()
        point[up] = t
        return float(part.solid(point[None, :])[0]) < 0.0

    solid_at, empty_at = float(along[k]), float(along[max(k - 1, 0)])
    for _ in range(40):
        middle = 0.5 * (solid_at + empty_at)
        if inside(middle):
            solid_at = middle
        else:
            empty_at = middle
    plane = solid_at - toward * _A_FACE_INSET
    # The material in that plane, on a grid fine enough for a 2 mm rim.
    n = 241
    a = np.linspace(lo[across[0]], hi[across[0]], n)
    b = np.linspace(lo[across[1]], hi[across[1]], n)
    A, B = np.meshgrid(a, b, indexing="ij")
    points = np.empty((A.size, 3))
    points[:, across[0]] = A.ravel()
    points[:, across[1]] = B.ravel()
    points[:, up] = plane
    count = int((np.asarray(part.solid(points), dtype=float) < 0.0).sum())
    cell = ((hi[across[0]] - lo[across[0]]) / (n - 1)) * (
        (hi[across[1]] - lo[across[1]]) / (n - 1))
    area = count * cell
    return Measurement(
        Q(area, "mm^2"), method="sampling",
        limitations=(
            f"material counted on a {n} by {n} grid in the plane "
            f"{_A_FACE_INSET:g} mm inside the part's outermost point on its "
            f"{side}; good to a cell's edge round the face",),
        detail={"side": side, "plane_mm": round(solid_at, 4),
                "axis": "xyz"[up], "cell_mm2": round(cell, 5)})


def _a_container(
    part: CompiledPart, properties: MassProperties, kind: str,
    side: str = "top",
) -> Measurement:
    """The walls, the floor and the opening of a part that holds something.

    A box, a tray, a cup: a part standing on its floor with material round
    a space. Nothing in the vocabulary could say whether it was one. An
    open-top box 60 by 40 by 30 with 2 mm walls and a 2 mm floor has
    exactly the bounding box of a solid block 60 by 40 by 30, and of a
    sealed hollow one; a design built as a 40 by 30 by 2 plate was the first
    answer to the brief, and nothing that could be claimed would have told
    the three apart.

    Measured on lines through the centre of the part's footprint, where a
    container's space is:

    - `floor_thickness`: the material the vertical line meets first, from
      the bottom of the part -- 0 if there is none at the bottom.
    - `opening_depth`: how far down that line is open from the top of the
      part before it meets material -- 0 when the top is closed.
    - `wall_thickness`: at half the part's height, the first and last run of
      material on the lines along X and along Y -- four walls, reported as
      the range from the thinnest to the thickest, so that one wall of the
      wrong thickness fails a claim the other three meet.

    With a side -- `opening_depth:left` for a cube "open on the left" -- the
    same three, turned so the way in runs from that face: the floor is the
    wall opposite it, and the walls are the four round the way in.
    """
    import numpy as np

    from forge_ir.measurements import CONTAINER_SIDES
    from forge_units import parse_unit

    # Open on another side -- "open on the left" -- the same three
    # measurements, turned: the way in runs along `up`, from the open end
    # (`toward` +1 the high end, -1 the low), the floor is the wall at the
    # other end, and the walls are on the two lines across.
    up, toward = CONTAINER_SIDES.get(side, (2, 1))
    across = [axis for axis in range(3) if axis != up]
    millimetre = parse_unit("mm")
    lo = [float(q.to(millimetre).magnitude.midpoint)
          for q in properties.bounding_box_lo]
    hi = [float(q.to(millimetre).magnitude.midpoint)
          for q in properties.bounding_box_hi]
    centre = [0.5 * (a + b) for a, b in zip(lo, hi)]
    note = ("measured on lines through the middle of the part's footprint, "
            "each crossing bisected to under a micrometre",)
    if side != "top":
        note += (f"the part is open on its {side}: the way in runs along "
                 f"{'xyz'[up]}, and the floor is the wall at the other end",)

    # The walls: halfway along the way in, the first and last run of
    # material on the lines across it through the middle.
    walls: list[float] = []
    rims: list[list[float]] = []
    lines = {}
    for axis in across:
        line = list(centre)
        runs = _material_along(part, lo, hi, axis, line)
        if len(runs) < 2:
            # The line through the middle runs inside a wall across the
            # space -- a tray's divider, a rib -- and meets no space at all:
            # the tray's walls read 2 and 60 mm, the 60 being the divider
            # from end to end. The walls are read beside it instead, on the
            # nearest line that crosses the space.
            other = next(a for a in across if a != axis)
            half = 0.5 * (hi[other] - lo[other])
            for fraction in (0.125, -0.125, 0.25, -0.25, 0.375, -0.375):
                shifted = list(centre)
                shifted[other] = centre[other] + fraction * half
                tried = _material_along(part, lo, hi, axis, shifted)
                if len(tried) >= 2:
                    runs, line = tried, shifted
                    break
        lines["xyz"[axis]] = [[round(a, 4), round(b, 4)] for a, b in runs]
        for run in (runs[:1] + runs[-1:]) if runs else []:
            walls.append(_across_the_wall(part, line, axis, run))
            through = list(line)
            through[axis] = 0.5 * (run[0] + run[1])
            rims.append(through)
    if kind == "wall_thickness":
        if not walls:
            return _blocked(
                "there is no material on the lines across the middle of the "
                "part, so it has no walls there to measure",
                runs_mm=lines)
        thinnest, thickest = min(walls), max(walls)
        from forge_units import Interval

        return Measurement(
            Q(Interval(thinnest, thickest), "mm") if thickest - thinnest > 1e-9
            else Q(thinnest, "mm"),
            limitations=note,
            detail={"walls_mm": [round(w, 4) for w in walls], "runs_mm": lines,
                    "at_mm": round(centre[up], 4), "open_side": side})

    # The floor and the opening, on the line through the middle along the
    # way in. The part's own two ends are read on lines through the walls
    # -- the rim -- as well, bisected like everything else: the octree's
    # envelope is an enclosure, and an opening measured against it would
    # carry its uncertainty.
    middle = _material_along(part, lo, hi, up, centre)
    # And on lines out towards the edge on each side: a bowl's rim is not
    # where its wall is at half its height -- a shell curves -- and an
    # opening measured from the wall's line started ten millimetres below
    # the rim of a hollow dome.
    edges = []
    for axis in across:
        for fraction in (0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98):
            for sign in (-1.0, 1.0):
                point = list(centre)
                point[axis] = centre[axis] + sign * fraction * 0.5 * (
                    hi[axis] - lo[axis])
                edges.append(point)
    verticals = [middle] + [_material_along(part, lo, hi, up, r)
                            for r in rims + edges]
    # Where the body's floor is reckoned from: the bottom of its walls, read
    # on the lines down through them. The part's own lowest point is not it
    # when something hangs below the body -- a hinge tab under a calf shell
    # put the "bottom" 12 mm below its floor, and an 8 mm floor read 0.
    wall_lines = [_material_along(part, lo, hi, up, r) for r in rims]
    wall_starts = [runs[0][0] for runs in wall_lines if runs]
    starts = [runs[0][0] for runs in verticals if runs]
    ends = [runs[-1][1] for runs in verticals if runs]
    bottom = min(starts) if starts else lo[up]
    top = max(ends) if ends else hi[up]
    detail = {"runs_mm": [[round(a, 4), round(b, 4)] for a, b in middle],
              "part_bottom_mm": round(bottom, 4), "part_top_mm": round(top, 4),
              "open_side": side}
    if toward < 0:
        # Seen from the open end, the far end is the floor: the runs read
        # backwards.
        bottom, top = -top, -bottom
    base = bottom
    if toward >= 0 and wall_starts:
        base = max(bottom, min(wall_starts))
    elif toward < 0 and wall_lines:
        ends_of_walls = [runs[-1][1] for runs in wall_lines if runs]
        if ends_of_walls:
            base = max(bottom, -max(ends_of_walls))

    def read(runs: list[tuple[float, float]]) -> tuple[float, float]:
        """The floor under a line, and how deep it is open above it."""
        if toward < 0:
            runs = [(-b, -a) for a, b in reversed(runs)]
        floor = (runs[0][1] - runs[0][0]
                 if runs and (abs(runs[0][0] - bottom) <= 0.05
                              or runs[0][0] <= base + 0.05) else 0.0)
        reached = runs[-1][1] if runs else bottom
        return floor, max(top - reached, 0.0)

    floor, depth = read(middle)
    if not (floor > 0.0 and depth > 0.0):
        # The middle of the floor is pierced -- a cup with a drain hole, a
        # tray with a cable hole -- and the line through it meets no floor:
        # a 2 mm floor read 0 and a 38 mm opening read the cup's whole
        # 40. Read beside the hole instead: on the nearest lines round the
        # middle that do stand on a floor with the space open above.
        found: list[tuple[float, float]] = []
        for fraction in (0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5):
            for turn in range(8):
                angle = turn * math.pi / 4.0
                point = list(centre)
                point[across[0]] += fraction * 0.5 * (
                    hi[across[0]] - lo[across[0]]) * math.cos(angle)
                point[across[1]] += fraction * 0.5 * (
                    hi[across[1]] - lo[across[1]]) * math.sin(angle)
                there = read(_material_along(part, lo, hi, up, point))
                if there[0] > 0.0 and there[1] > 0.0:
                    found.append(there)
            if found:
                break
        if found:
            floor = float(np.median([f for f, _ in found]))
            depth = float(np.median([d for _, d in found]))
            detail["read_beside_the_middle"] = (
                "the line through the middle meets no floor -- an opening "
                f"through it -- so the floor and depth are the median of "
                f"{len(found)} line(s) nearest the middle that stand on one")
    if kind == "floor_thickness":
        return Measurement(Q(floor, "mm"), limitations=note, detail=detail)
    return Measurement(Q(depth, "mm"), limitations=note, detail=detail)


def _enclosure_note(properties: MassProperties) -> tuple[str, ...]:
    note = (
        f"rigorous octree enclosure to depth {properties.depth_reached}; "
        f"residual uncertainty {properties.relative_uncertainty:.2%} of volume",
    )
    if not properties.converged:
        note += (
            "the measurement hit its cell budget before converging; the "
            "interval is wider than the requested target",
        )
    return note


#: How many directions the width is measured across. 72 is every 2.5
#: degrees over the half-turn, which resolves a hexagon's flats and costs
#: nothing beside the surface sampling itself.
_DIRECTIONS_ACROSS = 72


def _roundness_about_z(part: CompiledPart) -> Measurement:
    """How nearly the part is the same width across every direction in XY.

    1 for a cylinder, 0.707 for a square block, 0.866 for a hexagon, and in
    general cos(pi/n) for a regular n-sided prism.

    It exists because two equal bounding boxes do not say a part is round,
    and a run proved it: asked for a shaft collar 25 mm in outer diameter,
    the design built a 25 by 25 by 15 BOX. `bounding_box_x` and
    `bounding_box_y` both measured 25 and both passed, exactly as they would
    have on the cylinder, because a square and its circumscribed circle have
    the same bounding box. Every other gate passed too. The part had a bore,
    two set screws correctly 90 degrees apart, and was not a collar.

    Measured as a support width: project the surface onto each of many
    in-plane directions and take the spread. A circle is the only convex
    shape whose width is the same in every direction, so the ratio of the
    smallest width to the largest is a direct statement about roundness --
    and it is read off the built surface, so no design can declare its way
    past it.

    Holes do not disturb it. They remove material inside the silhouette, and
    the width across a direction is set by the outermost surface.
    """
    import numpy as np

    from forge_geom.measure import surface_samples

    try:
        points = np.asarray(surface_samples(part.solid), dtype=float)
    except Exception:  # noqa: BLE001 - an unsamplable solid is not a verdict
        return _blocked("the part's surface could not be sampled")
    if points.size == 0 or points.shape[0] < 8:
        return _blocked("too little surface was found to measure roundness")

    widths = _widths_across(points, (0, 1))
    if widths is None:
        return _blocked("the part has no width in the XY plane")
    narrowest, widest = widths
    return Measurement(
        Q(narrowest / widest),
        detail={
            "narrowest_width_mm": round(narrowest, 4),
            "widest_width_mm": round(widest, 4),
            "directions": _DIRECTIONS_ACROSS,
            "note": "1 is a cylinder; a square block is 0.707",
        },
    )


def _widths_across(points: Any, plane: tuple[int, int]) -> tuple[float, float] | None:
    """Narrowest and widest support width of `points` within one plane."""
    import numpy as np

    angles = np.linspace(0.0, math.pi, _DIRECTIONS_ACROSS, endpoint=False)
    directions = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    projected = points[:, list(plane)] @ directions.T
    widths = projected.max(axis=0) - projected.min(axis=0)
    widest = float(widths.max())
    if widest <= 1e-9:
        return None
    return float(widths.min()), widest


def _roundness(part: CompiledPart) -> Measurement:
    """How nearly round the part is about whichever axis it is roundest about.

    `roundness_about_z` answers for Z, which is where every collar so far
    has been built -- and is exactly wrong for a pin or a shaft built lying
    along X, which is round and would measure as a 12 by 100 rectangle. The
    claim a brief makes ("a 12 mm pin", "a 25 mm collar") says the part is
    round, not which way it lies, so this measures all three coordinate axes
    and reports the roundest, and says which one.

    It does not weaken the check. A square block is 0.707 about every axis
    that runs through two of its faces, so taking the best of three cannot
    turn a block round; it only stops a round part being called square for
    lying on its side.
    """
    import numpy as np

    from forge_geom.measure import surface_samples

    try:
        points = np.asarray(surface_samples(part.solid), dtype=float)
    except Exception:  # noqa: BLE001 - an unsamplable solid is not a verdict
        return _blocked("the part's surface could not be sampled")
    if points.size == 0 or points.shape[0] < 8:
        return _blocked("too little surface was found to measure roundness")

    best: tuple[float, str, float, float] | None = None
    for axis, plane in (("z", (0, 1)), ("x", (1, 2)), ("y", (0, 2))):
        widths = _widths_across(points, plane)
        if widths is None:
            continue
        ratio = widths[0] / widths[1]
        if best is None or ratio > best[0] + 1e-12:
            best = (ratio, axis, widths[0], widths[1])
    if best is None:
        return _blocked("the part has no width in any plane")
    ratio, axis, narrowest, widest = best
    return Measurement(
        Q(ratio),
        detail={
            "about": axis,
            "narrowest_width_mm": round(narrowest, 4),
            "widest_width_mm": round(widest, 4),
            "directions": _DIRECTIONS_ACROSS,
            "note": "1 is a cylinder; a square block is 0.707",
        },
    )


def sealed_voids_of(
    mesh: Any, hollows: Any = None,
) -> list[tuple[float, tuple[float, ...]]]:
    """The pockets of air sealed inside the part on this extracted surface:
    each one's volume in mm^3 and the middle of the surface round it.

    One grid cell or less is the extraction's own noise, not a void: a
    pocket that small cannot be told from a grid step, so it is left out."""
    import numpy as np

    if mesh is None or not getattr(mesh, "face_count", 0):
        return []
    edges = mesh.vertices[mesh.faces[:, 1]] - mesh.vertices[mesh.faces[:, 0]]
    cell = max(float(np.median(np.linalg.norm(edges, axis=1))), 1e-6)
    return [(round(volume, 3),
             tuple(round(float(c), 2) for c in vertices.mean(axis=0)))
            for volume, vertices in (
                mesh.hollows() if hollows is None else hollows)
            if volume > cell ** 3]


def _sealed_voids(part: CompiledPart, hollows: Any) -> Measurement:
    """How many pockets of air the part closes in on every side.

    A 20 mm cube of 1018 steel must weigh no more than 50 g; solid, it
    weighs 63. A repair kept the cube 20 mm on every side and shelled it
    inside to a 3 mm skin, and every claim passed: the envelope is the
    envelope, the weight is under the limit. The part looks exactly like
    the cube in every view and cannot be machined, and nothing the user
    asked for said it was hollow. A void sealed inside a part is invisible
    from outside, traps powder or resin in a print, and changes what it
    weighs and how strong it is -- so it is counted, on the surface the
    part was measured on."""
    if hollows is None:
        try:
            from forge_geom import extract_manifold_surface

            hollows = sealed_voids_of(
                extract_manifold_surface(part.solid, resolution=110))
        except Exception:  # noqa: BLE001 - no surface is not a verdict
            return _blocked("no surface could be extracted to look for "
                            "sealed voids")
    found = list(hollows)
    return Measurement(
        Q(len(found)),
        method="exact_geometry",
        limitations=(
            "counted on the extracted surface: a closed surface inside the "
            "part, connected to nothing, round air; a pocket under one grid "
            "cell is below what the extraction can tell from noise",),
        detail={
            "volumes_mm3": [volume for volume, _ in found],
            "where_mm": [list(centre) for _, centre in found],
            **({"hint": (
                f"{len(found)} pocket"
                + ("" if len(found) == 1 else "s")
                + " of air sealed inside the part, nothing joining "
                + ("it" if len(found) == 1 else "them")
                + " to the outside: "
                + "; ".join(f"{volume:.0f} mm^3 about ("
                            + ", ".join(f"{c:.1f}" for c in centre) + ")"
                            for volume, centre in found)
                + ". A shell, or a cut that stops inside the material, "
                "closes air in.")} if found else {}),
        },
    )


#: Directions in space the width of a ball is measured across: a
#: Fibonacci spiral over the half-sphere, near-uniform, about 6 degrees
#: apart -- a cube's corner (0.577) and a cylinder's rim (0.707) are both
#: far coarser than that.
_DIRECTIONS_IN_SPACE = 600


def _roundness_every_way(part: CompiledPart) -> Measurement:
    """How nearly the part is the same width in every direction in space.

    1 for a ball, 0.707 for a cylinder as tall as it is wide, 0.577 for a
    cube. It exists because roundness about an axis does not say a part is
    a ball, and a run proved it: asked for "a PLA sphere with a 100 mm
    diameter", the design built a 100 by 100 cylinder. It was round about
    its axis (0.9998), 100 across all three ways, and every claim passed.

    Measured as `roundness` is, as a support width -- the spread of the
    surface along each direction -- but over directions all round the
    sphere of directions rather than in one plane. A ball is the only
    convex shape as wide every way, and holes inside its silhouette do not
    change any width.
    """
    import numpy as np

    from forge_geom.measure import surface_samples

    try:
        points = np.asarray(surface_samples(part.solid), dtype=float)
    except Exception:  # noqa: BLE001 - an unsamplable solid is not a verdict
        return _blocked("the part's surface could not be sampled")
    if points.size == 0 or points.shape[0] < 8:
        return _blocked("too little surface was found to measure roundness")
    count = _DIRECTIONS_IN_SPACE
    index = np.arange(count, dtype=float) + 0.5
    z = index / count  # the upper half: a width is the same both ways
    radius = np.sqrt(np.clip(1.0 - z * z, 0.0, 1.0))
    turn = index * math.pi * (3.0 - math.sqrt(5.0))
    directions = np.stack([radius * np.cos(turn), radius * np.sin(turn), z],
                          axis=1)
    # The coordinate axes themselves, exactly: a block's narrowest widths.
    directions = np.vstack([directions, np.eye(3)])
    projected = points @ directions.T
    widths = projected.max(axis=0) - projected.min(axis=0)
    widest = float(widths.max())
    if widest <= 1e-9:
        return _blocked("the part has no width")
    narrowest = float(widths.min())
    return Measurement(
        Q(narrowest / widest),
        detail={
            "narrowest_width_mm": round(narrowest, 4),
            "widest_width_mm": round(widest, 4),
            "directions": int(directions.shape[0]),
            "note": "1 is a ball; a cylinder as tall as it is wide is "
                    "0.707, a cube 0.577",
        },
    )


#: The last few parts' openings, laid flat: several claims read the same
#: part, and sampling it once is enough. Held with the part itself, so an
#: id reused by a later part is never mistaken for it.
_OPENINGS_READ: list[tuple[Any, Any]] = []


def _the_openings_laid_flat(part: CompiledPart) -> dict[str, Any] | None:
    for seen, result in _OPENINGS_READ:
        if seen is part:
            return result
    result = _read_the_openings_laid_flat(part)
    _OPENINGS_READ.insert(0, (part, result))
    del _OPENINGS_READ[4:]
    return result


def _the_material_s_own_reach(U: Any, V: Any, solid: Any, step: float,
                              lo: Any, hi: Any, a: int, b: int) -> tuple[Any, Any]:
    """The flat part's ends and sides as its material reaches them.

    The envelope only bounds the part, and it can bound it loosely: a boss
    blended into its plate with a 2 mm fillet grew the envelope by the
    fillet, and every opening placed "14 mm in from each end" was measured
    from an end 2 mm out in the air -- two slots, drawn right, 2 mm off.
    Where the sampled material and the envelope agree to a grid step, the
    envelope's exact figure is kept; where they do not, the material's.
    """
    import numpy as np

    lo, hi = np.array(lo, dtype=float), np.array(hi, dtype=float)
    if not solid.any():
        return lo, hi
    for axis, grid in ((a, U), (b, V)):
        low = float(grid[solid].min()) - step / 2.0
        high = float(grid[solid].max()) + step / 2.0
        if abs(low - lo[axis]) > 1.5 * step:
            lo[axis] = low
        if abs(high - hi[axis]) > 1.5 * step:
            hi[axis] = high
    return lo, hi


def _columns_meeting_material(part: CompiledPart, U: Any, V: Any, a: int, b: int,
                              thin: int, z0: float, z1: float,
                              floor: float) -> Any:
    """Which columns of the flat part, each run right through its thin way
    from `z0` to `z1`, meet material anywhere along them.

    An opening is a column with no material all the way through. Asking at
    a quarter, a half and three quarters through was asking at three depths
    only: a flange's bolt holes are cut in a 6 mm disc under a hub that
    stands 30 mm, and all three depths were above the disc -- the whole disc
    read as air, its holes as part of the air round it, none found. Holes
    under counterbores 5 mm deep in a 6 mm plate read as the counterbores.
    Each column is walked from end to end instead, by the distance the
    part's own field says is clear (halved, so a field stretched by a bend
    is still walked safely), never by more than the plate's thinnest wall
    worth finding nor by less than `floor`.
    """
    import numpy as np

    found = _the_bend_chain(part.solid)
    forward = _flat_to_part(found[0] if found else None)
    count = U.size
    points = np.zeros((count, 3))
    points[:, a] = U.ravel()
    points[:, b] = V.ravel()
    solid = np.zeros(count, dtype=bool)
    # The three depths first, as before: most columns meet material there
    # and need no walk at all.
    for fraction in (0.25, 0.5, 0.75):
        open_ = np.flatnonzero(~solid)
        if not open_.size:
            break
        here = points[open_]
        here[:, thin] = z0 + fraction * (z1 - z0)
        solid[open_] = np.asarray(part.solid(forward(here)), dtype=float) < 0.0
    floor = max(float(floor), 1e-3)
    active = np.flatnonzero(~solid)
    level = np.full(active.size, z0)
    finished = np.zeros(active.size, dtype=bool)
    # A walk that has not ended within this many steps is cut short with
    # its column taken as solid: no opening is ever read from a column
    # that was not walked to its end.
    for _ in range(int(np.ceil((z1 - z0) / floor)) + 8):
        if not active.size:
            break
        here = points[active]
        here[:, thin] = level
        distance = np.asarray(part.solid(forward(here)), dtype=float)
        met = distance < 0.0
        solid[active[met]] = True
        at_the_end = finished | met
        level = np.where(finished, level,
                         np.minimum(level + np.maximum(0.5 * np.abs(distance), floor), z1))
        finished = (level >= z1) & ~finished
        keep = ~at_the_end
        active, level, finished = active[keep], level[keep], finished[keep]
    solid[active] = True
    return solid.reshape(U.shape)


def _read_the_openings_laid_flat(part: CompiledPart) -> dict[str, Any] | None:
    """Every opening right through the part's thinnest way, laid flat.

    A plate is cut through its thickness by its holes, its slots and its
    windows; laid flat, each is a region of the plate's face with no
    material under it all the way through. Sampled on a grid over the face,
    each column walked right through the part (`_columns_meeting_material`),
    each empty region inside the outline (not reaching the edge of the grid)
    is one opening: its length and width along and across its own long axis,
    and its centre.

    Returned with the frame they were read in: the two in-plane axes, the
    flat part's low and high corners, and the grid step.
    """
    import numpy as np

    inside, envelope, _, _ = _the_flat_part(part)
    if envelope.is_empty:
        return None
    lo = np.asarray(envelope.lo, dtype=float)
    hi = np.asarray(envelope.hi, dtype=float)
    size = hi - lo
    thin = int(np.argmin(size))
    a, b = [i for i in range(3) if i != thin]
    step = max(float(np.sqrt(size[a] * size[b] / 300_000.0)), 0.05)
    us = np.arange(lo[a] - step, hi[a] + 2 * step, step)
    vs = np.arange(lo[b] - step, hi[b] + 2 * step, step)
    U, V = np.meshgrid(us, vs, indexing="ij")
    solid = _columns_meeting_material(
        part, U, V, a, b, thin, float(lo[thin]), float(hi[thin]),
        floor=min(step, float(size[thin]) / 48.0))
    lo, hi = _the_material_s_own_reach(U, V, solid, step, lo, hi, a, b)
    openings = _the_regions_read(U, V, solid, step)
    openings = _small_openings_read_closely(
        part, openings, step, a, b, thin, envelope, lo, hi)
    return {"openings": openings, "step": step, "axes": (a, b),
            "thin": thin, "lo": lo.tolist(), "hi": hi.tolist()}


def _of_size(opening: Mapping[str, float], length: float, width: float,
             step: float) -> bool:
    """Whether an opening is the size named, to the step it was read at:
    a grid step and a half, or 2 per cent, whichever is the more."""
    own = float(opening.get("step", step))
    return (abs(opening["length"] - length) <= max(1.5 * own, 0.02 * length)
            and abs(opening["width"] - width) <= max(1.5 * own, 0.02 * width))


def _the_regions_read(U: Any, V: Any, solid: Any,
                      step: float) -> list[dict[str, float]]:
    """Each empty region of a sampled grid that does not reach its edge:
    its length and width along and across its own long axis, its centre,
    and the step it was read at."""
    import numpy as np

    labels, count = _regions_of(~solid)
    border = set(np.unique(np.concatenate([
        labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]])).tolist())
    openings: list[dict[str, float]] = []
    for label in range(1, count + 1):
        if label in border:
            continue
        mask = labels == label
        cells = int(mask.sum())
        if cells < 4:
            continue
        pts = np.stack([U[mask], V[mask]], axis=1)
        middle = pts.mean(axis=0)
        centred = pts - middle
        _, vectors = np.linalg.eigh(centred.T @ centred)
        along = centred @ vectors[:, 1]
        across = centred @ vectors[:, 0]
        length = float(along.max() - along.min()) + step
        width = float(across.max() - across.min()) + step
        # The middle of its extent, not the mean of its cells: a slot's
        # cells are even about its middle either way, a notch's are not.
        mid_a = float((U[mask].max() + U[mask].min()) / 2.0)
        mid_b = float((V[mask].max() + V[mask].min()) / 2.0)
        openings.append({"length": round(length, 3), "width": round(width, 3),
                         "at_a": round(mid_a, 4), "at_b": round(mid_b, 4),
                         "step": step})
    return openings


#: An opening fewer grid steps across than this is read again, closely.
_FEW_STEPS = 12
#: At most this many places are read again closely, per part.
_CLOSE_READS = 400


def _small_openings_read_closely(
    part: CompiledPart, openings: list[dict[str, float]], step: float,
    a: int, b: int, thin: int, envelope: Any, lo: Any, hi: Any,
) -> list[dict[str, float]]:
    """Openings a few grid steps across, read again on a grid fine enough
    to measure them -- and the small holes the grid stepped over, found.

    The grid is sized to the part: 300 000 columns over its face, a step of
    1.4 mm on a 1000 by 600 mm plate. A 3 mm hole there was read as 4.2 by
    2.8; a 5 mm hole on a 2000 mm plate was not found at all, and both were
    failed as the wrong size or missing -- on parts drawn exactly right.

    So each opening only a few steps across is sampled again over a small
    window round it, forty steps across the opening; and so is the
    place of every round hole the part names -- a bore along the thin way,
    smaller than a few steps -- which the grid may have stepped over
    entirely. What a close read finds replaces what the coarse one made of
    the same opening. Nothing is invented: every opening is still a region
    of columns with no material right through the part.
    """
    import numpy as np

    # Each place: its centre, the half-width of the window round it, and
    # the size of what is there, which sets how fine the close read is.
    places: list[tuple[float, float, float, float]] = []
    for opening in openings:
        across = max(opening["length"], opening["width"])
        if across < _FEW_STEPS * step:
            places.append((opening["at_a"], opening["at_b"],
                           across / 2.0 + 2.0 * step, across))
    if _the_bend_chain(part.solid) is None:
        # The part is not bent: its named faces are where they were made,
        # and a round hole's place on it is its bore's axis.
        for entity in getattr(part, "geometry_map", ()) or ():
            try:
                radius = float(entity.dimensions.get("radius", 0.0))
                axis = np.asarray(entity.frame.z_axis, dtype=float)
                origin = np.asarray(entity.frame.origin, dtype=float)
            except Exception:  # noqa: BLE001 - a face it cannot read adds none
                continue
            norm = float(np.linalg.norm(axis))
            if not (0.0 < radius < _FEW_STEPS * step / 2.0) or norm < 1e-12 \
                    or abs(axis[thin]) / norm < 0.99:
                continue
            if not (lo[a] < origin[a] < hi[a] and lo[b] < origin[b] < hi[b]):
                continue
            places.append((float(origin[a]), float(origin[b]),
                           radius + 2.0 * step, 2.0 * radius))
    if not places:
        return openings
    elo = np.asarray(envelope.lo, dtype=float)
    ehi = np.asarray(envelope.hi, dtype=float)
    depth = float(ehi[thin] - elo[thin])
    closely: list[dict[str, float]] = []
    for at_a, at_b, half, across in places[:_CLOSE_READS]:
        fine = max(min(step, across / 40.0), 0.02)
        us = np.arange(at_a - half, at_a + half + fine, fine)
        vs = np.arange(at_b - half, at_b + half + fine, fine)
        U, V = np.meshgrid(us, vs, indexing="ij")
        solid = _columns_meeting_material(
            part, U, V, a, b, thin, float(elo[thin]), float(ehi[thin]),
            floor=min(fine, depth / 48.0))
        for found in _the_regions_read(U, V, solid, fine):
            if any(abs(found["at_a"] - o["at_a"]) <= 2.0 * fine
                   and abs(found["at_b"] - o["at_b"]) <= 2.0 * fine
                   for o in closely):
                continue
            closely.append(found)
    if not closely:
        return openings

    def the_same(coarse: Mapping[str, float]) -> bool:
        return any(
            abs(coarse["at_a"] - o["at_a"]) <= (o["length"] + coarse[
                "length"]) / 2.0 + step
            and abs(coarse["at_b"] - o["at_b"]) <= (o["length"] + coarse[
                "length"]) / 2.0 + step
            for o in closely)

    kept = [o for o in openings
            if max(o["length"], o["width"]) >= _FEW_STEPS * step
            or not the_same(o)]
    return kept + closely


def _openings_through(part: CompiledPart) -> tuple[list[tuple[float, float]], float] | None:
    """Every opening right through the part, each as (length, width) in mm,
    read on the part laid flat -- see `_the_openings_laid_flat`."""
    found = _the_openings_laid_flat(part)
    if found is None:
        return None
    return ([(o["length"], o["width"], o.get("step", found["step"]))
             for o in found["openings"]], found["step"])


def _regions_of(mask: Any) -> tuple[Any, int]:
    """Label the 4-connected regions of a 2-D boolean grid: (labels, count),
    0 outside every region. NumPy only -- Forge's one dependency -- by runs
    along each row, joined to the overlapping runs of the row before."""
    import numpy as np

    rows, cols = mask.shape
    parent: list[int] = []

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    runs: list[tuple[int, int, int, int]] = []  # row, start, stop, id
    previous: list[tuple[int, int, int]] = []
    for r in range(rows):
        line = np.concatenate(([False], mask[r], [False])).astype(np.int8)
        edges = np.flatnonzero(np.diff(line))
        current: list[tuple[int, int, int]] = []
        for start, stop in zip(edges[0::2], edges[1::2]):
            identifier = len(parent)
            parent.append(identifier)
            for p_start, p_stop, p_id in previous:
                if p_start < stop and start < p_stop:
                    a, b = root(identifier), root(p_id)
                    if a != b:
                        parent[max(a, b)] = min(a, b)
            current.append((int(start), int(stop), identifier))
            runs.append((r, int(start), int(stop), identifier))
        previous = current
    labels = np.zeros(mask.shape, dtype=np.int32)
    numbering: dict[int, int] = {}
    for r, start, stop, identifier in runs:
        label = numbering.setdefault(root(identifier), len(numbering) + 1)
        labels[r, start:stop] = label
    return labels, len(numbering)


def _openings_of_size(part: CompiledPart, argument: str) -> Measurement:
    """How many openings right through the part are this long and wide.

    "Two 28 x 5 mm holes, centred across the width": slots, which no hole
    count reads -- a slot is not a hole of any one diameter. Counted on the
    part laid flat (`_openings_through`), each opening's length and width
    along and across its own long axis, either way round, to within a
    sampling step and 2 % of the figure.
    """
    import re as _re

    sizes = _re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[x*]\s*(\d+(?:\.\d+)?)\s*",
                          argument)
    if not sizes:
        return _blocked(f"`{argument}` is not a length and a width")
    wanted = sorted((float(sizes.group(1)), float(sizes.group(2))),
                    reverse=True)
    try:
        found = _openings_through(part)
    except Exception:  # noqa: BLE001 - an unsamplable part is not a verdict
        found = None
    if found is None:
        return _blocked("the part could not be laid flat and sampled")
    openings, step = found
    matching = [o[:2] for o in openings
                if abs(o[0] - wanted[0]) <= max(1.5 * o[2], 0.02 * wanted[0])
                and abs(o[1] - wanted[1]) <= max(1.5 * o[2], 0.02 * wanted[1])]
    openings = [o[:2] for o in openings]
    return Measurement(
        Q(len(matching)), method="sampling",
        limitations=(f"read on a {step:.2f} mm grid over the part laid flat, "
                     "each column walked right through it; an opening a few "
                     "steps across read again on a finer grid round it",),
        detail={"openings_mm": [list(o) for o in openings],
                "matching_mm": [list(o) for o in matching],
                "wanted_mm": wanted,
                "hint": (
                    f"openings right through the part, {wanted[0]:g} by "
                    f"{wanted[1]:g} mm, counted laid flat: "
                    f"{len(matching)} of that size among "
                    + (", ".join(f"{a:g} x {b:g}" for a, b in openings)
                       or "none") + ". A slot is a `profile_slot` (`length` "
                    "is its overall length, `rotation` turns it) on a "
                    "`datum_plane` off the part, `extrude`d right through it "
                    "and cut with a `subtract`; two openings that run into "
                    "each other are one.")})


def _an_opening_at(part: CompiledPart, binding: MeasurementBinding) -> Measurement:
    """How far the nearest opening of a size is from where it should be.

    "Two 8.2 mm mounting holes on the centreline, the first 18 mm from the
    distal edge, 30 mm apart." Counting 8.2 mm holes says two; it does not
    say where. This reads it on the built part: laid flat, every opening
    right through it found with its size and centre (`_the_openings_laid_
    flat`), and the distance in mm from the place the binding names to the
    centre of the nearest opening of that size.

    The place is along the flat part's longer side and across its shorter:
    in from one end (`lo`, `hi`), in from either (`end`), the same across
    (`side`), or off the middle (`mid`, `mid+5`). A part as wide as it is
    long is read both ways round, and the nearer taken: which way it was
    turned is not the brief's to say.
    """
    import math
    import re as _re

    import numpy as np

    figures = [float(x) for x in _re.findall(r"\d+(?:\.\d+)?", binding.argument)]
    wanted = sorted(figures if len(figures) == 2 else figures * 2, reverse=True)
    try:
        found = _the_openings_laid_flat(part)
    except Exception:  # noqa: BLE001 - an unsamplable part is not a verdict
        found = None
    if found is None:
        return _blocked("the part could not be laid flat and sampled")
    step = found["step"]
    a, b = found["axes"]
    lo, hi = found["lo"], found["hi"]
    sized = [o for o in found["openings"]
             if _of_size(o, wanted[0], wanted[1], step)]
    everything = ", ".join(
        f"{o['length']:g} x {o['width']:g} at ({o['at_a']:g}, {o['at_b']:g})"
        for o in found["openings"]) or "none"
    label = ("x" if len(figures) == 2 else " mm").join(
        f"{f:g}" for f in figures) + (" mm" if len(figures) == 2 else "")
    if not sized:
        return _blocked(
            f"the part has no opening right through it of {label}, so there "
            "is none to place",
            openings=everything,
            hint=f"openings laid flat, (length x width at centre): {everything}")
    along_spec, across_spec = binding.sub_argument.split(",")

    def targets(spec: str, axis: int) -> list[float]:
        low, high = float(lo[axis]), float(hi[axis])
        if spec.startswith("mid"):
            offset = float(spec[3:] or 0.0)
            return [(low + high) / 2.0 + offset]
        figure = float(_re.sub(r"[a-z]", "", spec))
        if spec.startswith("lo"):
            return [low + figure]
        if spec.startswith("hi"):
            return [high - figure]
        return [low + figure, high - figure]  # end / side: either one

    sides = {a: float(hi[a] - lo[a]), b: float(hi[b] - lo[b])}
    longer, shorter = (a, b) if sides[a] >= sides[b] else (b, a)
    frames = [(longer, shorter)]
    if abs(sides[a] - sides[b]) <= max(0.01 * max(sides.values()), step):
        frames.append((shorter, longer))
    best = None
    for along_axis, across_axis in frames:
        for t_along in targets(along_spec, along_axis):
            for t_across in targets(across_spec, across_axis):
                spot = {along_axis: t_along, across_axis: t_across}
                for opening in sized:
                    where = {a: opening["at_a"], b: opening["at_b"]}
                    gap = math.hypot(where[along_axis] - spot[along_axis],
                                     where[across_axis] - spot[across_axis])
                    if best is None or gap < best[0]:
                        best = (gap, opening, spot, along_axis, across_axis)
    gap, opening, spot, along_axis, across_axis = best
    axis_name = "xyz"
    return Measurement(
        Q(round(gap, 3), "mm"), method="sampling",
        limitations=(f"read on a {step:.2f} mm grid over the part laid flat; "
                     "the centre is the middle of the opening's extent",),
        detail={
            "measurement": f"opening_at:{binding.argument}:{binding.sub_argument}",
            "wanted_at_mm": {axis_name[k]: round(v, 3) for k, v in spot.items()},
            "nearest_at_mm": {axis_name[a]: opening["at_a"],
                              axis_name[b]: opening["at_b"]},
            "along": axis_name[along_axis], "across": axis_name[across_axis],
            "flat_part_mm": {axis_name[k]: [round(float(lo[k]), 3),
                                            round(float(hi[k]), 3)]
                             for k in (a, b)},
            "hint": (
                f"the {label} opening nearest where it belongs is centred at "
                f"{axis_name[a]}={opening['at_a']:g}, {axis_name[b]}="
                f"{opening['at_b']:g} mm on the part laid flat, "
                f"{gap:.2f} mm from where the brief puts it ("
                + ", ".join(f"{axis_name[k]}={v:g}" for k, v in spot.items())
                + f"). The flat part runs {axis_name[along_axis]} "
                f"{lo[along_axis]:g} to {hi[along_axis]:g} along and "
                f"{axis_name[across_axis]} {lo[across_axis]:g} to "
                f"{hi[across_axis]:g} across. Every opening laid flat: "
                f"{everything}.")})


def _openings_on_a_circle(part: CompiledPart, binding: MeasurementBinding) -> Measurement:
    """How many openings of a size are centred on a circle about the part's
    middle, laid flat -- "four 8 mm holes equally spaced on a 60 mm bolt
    circle". The count of 8 mm holes says four; this says where they are.
    Each opening's centre within half a millimetre (or two grid steps) of
    the circle counts; the angles between neighbours are reported, so equal
    spacing can be read off them."""
    import math

    import numpy as np

    size, circle = float(binding.argument), float(binding.sub_argument)
    try:
        found = _the_openings_laid_flat(part)
    except Exception:  # noqa: BLE001 - an unsamplable part is not a verdict
        found = None
    if found is None:
        return _blocked("the part could not be laid flat and sampled")
    step = found["step"]
    a, b = found["axes"]
    lo, hi = found["lo"], found["hi"]
    middle = ((lo[a] + hi[a]) / 2.0, (lo[b] + hi[b]) / 2.0)
    sized = [o for o in found["openings"] if _of_size(o, size, size, step)]
    reach = max(0.5, 2 * min([o.get("step", step) for o in sized] or [step]))
    on: list[tuple[float, float, float]] = []
    elsewhere: list[str] = []
    for opening in sized:
        du, dv = opening["at_a"] - middle[0], opening["at_b"] - middle[1]
        radius = math.hypot(du, dv)
        if abs(2.0 * radius - circle) <= 2.0 * reach:
            on.append((math.degrees(math.atan2(dv, du)) % 360.0,
                       opening["at_a"], opening["at_b"]))
        else:
            elsewhere.append(f"({opening['at_a']:g}, {opening['at_b']:g}) on a "
                             f"{2 * radius:.2f} mm circle")
    on.sort()
    gaps = [round((on[(i + 1) % len(on)][0] - on[i][0]) % 360.0, 2)
            for i in range(len(on))] if len(on) > 1 else []
    # On the circle is half of it: the brief spaces them equally. Six holes
    # bunched on one side of a 56 mm circle were six holes on it. Counted
    # instead: the most of them at an equal spacing round the circle, from
    # any one of them -- all of them when they are spaced as the brief says.
    spaced = len(on)
    if len(on) > 1:
        pitch = 360.0 / len(on)
        tolerance = max(1.0, math.degrees(reach / max(circle / 2.0, 1e-9)))
        spaced = max(
            sum(1 for other in on
                if min(((other[0] - first[0]) % pitch),
                       pitch - ((other[0] - first[0]) % pitch)) <= tolerance)
            for first in on)
    return Measurement(
        Q(spaced), method="sampling",
        limitations=(f"read on a {step:.2f} mm grid over the part laid flat",),
        detail={
            "measurement": f"openings_on_circle:{size:g}:{circle:g}",
            "angles_deg": [round(x[0], 2) for x in on],
            "angles_between_deg": gaps,
            "hint": (
                f"{len(on)} openings of {size:g} mm are centred on the "
                f"{circle:g} mm circle, {spaced} of them equally spaced, "
                f"about the part's middle ("
                f"{'xyz'[a]}={middle[0]:g}, {'xyz'[b]}={middle[1]:g}), at "
                + (", ".join(f"{x[0]:.1f} deg" for x in on) or "none")
                + (f"; {size:g} mm openings off it: " + "; ".join(elsewhere)
                   if elsewhere else "") + ". Holes on a bolt circle are at "
                "its radius from the part's own centre, spread round it.")})


def a_bore_with_material_all_round(part: CompiledPart, bore: Any) -> bool:
    """Whether, somewhere along the stretch it cuts, a hole has material on a
    ring just outside its radius all the way round -- a hole, not a groove.

    A calf shell's two lowest mounting holes were drilled 20 mm into the
    hollow; 0.75 mm of each one's edge grazed the side wall, so its bore was
    on the part and it counted as an open 4.5 mm hole. It was a groove. The
    same question `GEOM_HOLES_ARE_HOLES` asks, here so a count of holes
    counts holes. A bore whose frame cannot be read is given the benefit.
    """
    import numpy as np

    try:
        radius = float(bore.dimensions.get("radius", 0.0))
        length = float(bore.dimensions.get("length", 0.0))
        centre = np.asarray(bore.frame.origin, dtype=float)
        direction = np.asarray(bore.frame.z_axis, dtype=float)
        direction = direction / max(float(np.linalg.norm(direction)), 1e-12)
    except Exception:  # noqa: BLE001
        return True
    if radius <= 0.0 or length <= 0.0:
        return True
    helper = np.array([1.0, 0.0, 0.0])
    if abs(float(direction @ helper)) > 0.9:
        helper = np.array([0.0, 1.0, 0.0])
    across = np.cross(direction, helper)
    across /= np.linalg.norm(across)
    other = np.cross(direction, across)
    ring_radius = radius + min(0.5, 0.25 * radius)
    angles = np.linspace(0.0, 2.0 * np.pi, 16, endpoint=False)
    ring = ring_radius * (np.outer(np.cos(angles), across)
                          + np.outer(np.sin(angles), other))
    stations = np.linspace(-length / 2.0, length / 2.0, 97)
    centres = centre + np.outer(stations, direction)
    points = (centres[:, None, :] + ring[None, :, :]).reshape(-1, 3)
    inside = (np.asarray(part.solid(points)) < -1e-6).reshape(97, 16)
    # Every way round, material somewhere along it: a hole tilted through a
    # thin plate has its whole ring in the plate at no single station -- the
    # plate takes one side here and the other side there -- and is a hole.
    # A notch is open over half its circle all the way along, and is not.
    return bool(inside.all(axis=1).any() or inside.any(axis=0).all())


def _hole_at(
    component: Component, part: CompiledPart, binding: MeasurementBinding
) -> Measurement:
    """How many open holes of one diameter have their axis through a point
    the brief gives in the part's own coordinates.

    "Each tab has one 8.5 mm pivot hole ... the lower one centred at X=0,
    Y=0, Z=-37.5." A hole count says the hole is there; nothing said where:
    a pivot drilled at the tip of a tab, 2.5 mm off, counted as a pivot. A
    coordinate given as `*` is left free -- a hole "at X/Z position
    (-36, 50)" drilled along Y may be anywhere along Y. Read off the
    geometry the kernel published for each hole, as `holes_of_diameter`
    does: a hole filled back in, or one that cut nothing, is not there.
    """
    import numpy as np

    size = float(binding.argument)
    tolerance = max(0.01, size * 1e-3)
    places = binding.sub_argument.split(",")
    point = np.array([0.0 if w == "*" else float(w) for w in places])
    free = [i for i, w in enumerate(places) if w == "*"]
    buried = {entity.name for entity in part.buried_entities()}
    near = 0.5
    count = 0
    nearest: tuple[float, str, Any] | None = None
    candidates: list[tuple[str, Any]] = []
    for feature in component.features:
        if feature.kind != "hole":
            continue
        prefix = feature.role or feature.identifier
        bore = part.geometry_map.get(f"{prefix}.bore")
        if bore is None or f"{prefix}.bore" in buried:
            continue
        candidates.append((feature.identifier, bore))
    # The holes a `subtract` cut with a cylinder, each copy of a pattern of
    # them where it is: placed holes that no `hole` feature drilled.
    candidates += [(b.name, b) for b in _bores_cut_by_tools(component, part)]
    for identifier, bore in candidates:
        if abs(2.0 * float(bore.dimensions.get("radius", 0.0)) - size) > tolerance:
            continue
        if not a_bore_with_material_all_round(part, bore):
            continue
        try:
            centre = np.asarray(bore.frame.origin, dtype=float)
            direction = np.asarray(bore.frame.z_axis, dtype=float)
            direction = direction / max(float(np.linalg.norm(direction)), 1e-12)
        except Exception:  # noqa: BLE001 - a hole with no frame has no place
            continue
        # The nearest the axis comes to the point, the free coordinates
        # taking whatever values bring them closest.
        columns = [direction] + [-np.eye(3)[i] for i in free]
        solved, *_ = np.linalg.lstsq(np.stack(columns, axis=1),
                                     point - centre, rcond=None)
        gap = float(np.linalg.norm(
            np.stack(columns, axis=1) @ solved - (point - centre)))
        if not free:
            # The point must be on the stretch the hole cuts, not on the
            # line it would make if it went on.
            reach = float(bore.dimensions.get("length", 0.0)) / 2.0
            beyond = max(0.0, abs(float(solved[0])) - reach)
            gap = float(np.hypot(gap, beyond))
        if gap <= near:
            count += 1
        if nearest is None or gap < nearest[0]:
            nearest = (gap, identifier, centre)
    wanted = ", ".join(f"{'xyz'[i]}={w}" for i, w in enumerate(places)
                       if w != "*")
    if nearest is None:
        said = f"No open hole of {size:g} mm is on the part at all."
    else:
        gap, name, centre = nearest
        said = (f"The nearest open {size:g} mm hole, `{name}`, has its axis "
                f"{gap:.2f} mm from ({wanted}); its bore is centred at ("
                + ", ".join(f"{'xyz'[i]}={float(centre[i]):.2f}"
                            for i in range(3)) + ").")
    return Measurement(
        Q(count),
        detail={
            "measurement": f"hole_at:{size:g}:{binding.sub_argument}",
            "wanted_at_mm": wanted,
            "hint": (f"{count} open {size:g} mm hole(s) with the axis through "
                     f"({wanted}), to {near:g} mm. {said} Put the hole where "
                     "the brief puts it, in the part's own coordinates -- "
                     "and the material it belongs to round it there.")})


def _openings_apart(part: CompiledPart, binding: MeasurementBinding) -> Measurement:
    """How many pairs of openings of a size have their centres a distance
    apart, laid flat -- "two 8.2 mm mounting holes spaced 60 mm apart".

    A spacing bound to the design's own parameter reads back the number the
    design declares, wherever the holes are: an exoskeleton rail declared
    `mounting_hole_spacing` = 60 mm and drilled its two holes 130 mm apart,
    and the claim passed. This reads the centres off the part."""
    import math

    size, apart = float(binding.argument), float(binding.sub_argument)
    try:
        found = _the_openings_laid_flat(part)
    except Exception:  # noqa: BLE001 - an unsamplable part is not a verdict
        found = None
    if found is None:
        return _blocked("the part could not be laid flat and sampled")
    step = found["step"]
    a, b = found["axes"]
    sized = [o for o in found["openings"] if _of_size(o, size, size, step)]
    reach = max(0.5, 2 * min([o.get("step", step) for o in sized] or [step]))
    centres = [(o["at_a"], o["at_b"]) for o in sized]
    pairs = 0
    seen: list[str] = []
    for i in range(len(centres)):
        for j in range(i + 1, len(centres)):
            gap = math.dist(centres[i], centres[j])
            seen.append(f"{gap:.2f}")
            if abs(gap - apart) <= reach:
                pairs += 1
    return Measurement(
        Q(pairs), method="sampling",
        limitations=(f"read on a {step:.2f} mm grid over the part laid flat",),
        detail={
            "measurement": f"openings_apart:{size:g}:{apart:g}",
            "centres_mm": [[round(u, 2), round(v, 2)] for u, v in centres],
            "hint": (
                f"{len(centres)} openings of {size:g} mm, centres at "
                + (", ".join(f"({'xyz'[a]}={u:g}, {'xyz'[b]}={v:g})"
                             for u, v in centres) or "none")
                + f"; centre to centre: {', '.join(seen) or 'none'} mm. "
                f"{pairs} pair(s) are {apart:g} mm apart, as the brief "
                "spaces them.")})


def _the_faces_of_the_flat_part(part: CompiledPart) -> dict[str, Any] | None:
    """The flat part's frame, with the true top and bottom of its material
    along its thin way: the envelope only bounds them."""
    import numpy as np

    inside, envelope, _, _ = _the_flat_part(part)
    if envelope.is_empty:
        return None
    lo = np.asarray(envelope.lo, dtype=float)
    hi = np.asarray(envelope.hi, dtype=float)
    size = hi - lo
    thin = int(np.argmin(size))
    a, b = [i for i in range(3) if i != thin]
    step = max(float(np.sqrt(size[a] * size[b] / 60_000.0)), 0.1)
    us = np.arange(lo[a], hi[a] + step, step)
    vs = np.arange(lo[b], hi[b] + step, step)
    U, V = np.meshgrid(us, vs, indexing="ij")
    levels = np.linspace(lo[thin], hi[thin], 97)

    def filled(index: int) -> bool:
        points = np.zeros((U.size, 3))
        points[:, a], points[:, b], points[:, thin] = (
            U.ravel(), V.ravel(), levels[index])
        return bool(inside(points).any())

    # The first level with material from the bottom, and from the top: the
    # same two answers as filling in all 97 levels, from the two or three
    # each end actually needs. All 97, twice per verification, was a third
    # of a stepper plate's.
    first = next((i for i in range(len(levels)) if filled(i)), None)
    if first is None:
        return None
    last = next(i for i in range(len(levels) - 1, first - 1, -1)
                if i == first or filled(i))
    spacing = float(levels[1] - levels[0])
    return {"inside": inside, "lo": lo, "hi": hi, "thin": thin, "axes": (a, b),
            "bottom": float(levels[first]), "top": float(levels[last]),
            "resolution": spacing}


def _ring(inside: Any, frame: dict[str, Any], centre: tuple[float, float],
          radius: float, level: float, count: int = 24) -> Any:
    """Whether the part has material at each of `count` points round a
    circle in the plane at `level` along the flat part's thin way."""
    import numpy as np

    a, b = frame["axes"]
    angles = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False)
    points = np.zeros((count, 3))
    points[:, a] = centre[0] + radius * np.cos(angles)
    points[:, b] = centre[1] + radius * np.sin(angles)
    points[:, frame["thin"]] = level
    return np.asarray(inside(points), dtype=bool)


def _counterbores(part: CompiledPart, binding: MeasurementBinding) -> Measurement:
    """How many holes of a size are counterbored as the brief says.

    "Four 5.5 mm corner holes, each counterbored 10 mm in diameter and 4 mm
    deep from the top." A count of 5.5 mm holes passes with the counterbores
    on the bottom, or missing; so does a parameter that holds 10 mm. Each
    5.5 mm hole right through the part laid flat is probed instead: from the
    face round it, on the named side, a recess of the counterbore's diameter
    -- empty just inside that diameter and solid just outside it, half its
    depth in -- with a floor at its depth: empty 0.3 mm short of it, solid
    0.3 mm past it.
    """
    import re as _re

    hole = float(binding.argument)
    m = _re.fullmatch(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?),(top|bottom|any)",
                      binding.sub_argument)
    if not m:
        return _blocked(f"`counterbores:{binding.argument}:"
                        f"{binding.sub_argument}` could not be read")
    bore, depth, side = float(m.group(1)), float(m.group(2)), m.group(3)
    try:
        found = _the_openings_laid_flat(part)
        frame = _the_faces_of_the_flat_part(part)
    except Exception:  # noqa: BLE001 - an unsamplable part is not a verdict
        found = frame = None
    if found is None or frame is None:
        return _blocked("the part could not be laid flat and sampled")
    inside = frame["inside"]
    step = found["step"]
    holes = [o for o in found["openings"] if _of_size(o, hole, hole, step)]
    probe = frame["resolution"] / 4.0
    margin = 0.3

    def counterbored(centre: tuple[float, float], way: int) -> bool:
        # The face round the hole: the first material met coming in from
        # that side, just outside the counterbore.
        start = frame["top"] if way > 0 else frame["bottom"]
        start += way * frame["resolution"]
        limit = frame["bottom"] if way > 0 else frame["top"]
        face = None
        level = start
        while (level - limit) * way > 0:
            if _ring(inside, frame, centre, bore / 2.0 + 1.0, level).mean() > 0.5:
                face = level + way * probe / 2.0
                break
            level -= way * probe
        if face is None:
            return False
        middle = face - way * depth / 2.0
        between = (hole / 2.0 + bore / 2.0) / 2.0
        # Material round the counterbore and under it on most of each ring,
        # not all: a neighbour's counterbore or a hole beside it can take a
        # bite out of the ring -- two counterbores 10 mm across on centres
        # 10 mm apart meet -- and each is still the counterbore it was asked
        # to be. Nothing in the counterbore itself is ever allowed.
        return bool(
            not _ring(inside, frame, centre, bore / 2.0 - margin, middle).any()
            and _ring(inside, frame, centre, bore / 2.0 + margin,
                      middle).mean() >= 0.75
            and not _ring(inside, frame, centre, between,
                          face - way * (depth - margin)).any()
            and _ring(inside, frame, centre, between,
                      face - way * (depth + margin)).mean() >= 0.75)

    ways = {"top": (1,), "bottom": (-1,), "any": (1, -1)}[side]
    done = [o for o in holes
            if any(counterbored((o["at_a"], o["at_b"]), w) for w in ways)]
    return Measurement(
        Q(len(done)), method="sampling",
        limitations=(f"probed on rings {margin} mm either side of the "
                     "counterbore's diameter and depth",),
        detail={
            "measurement": f"counterbores:{binding.argument}:"
                           f"{binding.sub_argument}",
            "hint": (
                f"{len(holes)} holes of {hole:g} mm go right through the part; "
                f"{len(done)} of them are counterbored {bore:g} mm across and "
                f"{depth:g} mm deep from the "
                + ("top or bottom" if side == "any" else side)
                + " face. A counterbore is on the side its hole is entered "
                "from: `entry` and the hole's `axis` say which.")})


def _standing_at(part: CompiledPart, binding: MeasurementBinding) -> Measurement:
    """How far a round solid standing on the part is from where it belongs.

    "On top, in the centre of the plate, a cylindrical boss 36 mm in
    diameter standing 6 mm proud." A parameter holding 36 mm passes with the
    boss anywhere -- or a different size. The part laid flat is cut halfway
    up the boss, `h / 2` below its top; each separate piece of material in
    that cut about `D` across both ways is a candidate, and the measurement
    is the distance from where the binding puts it to the nearest one's
    centre.
    """
    import math
    import re as _re

    import numpy as np

    diameter, height = (float(x) for x in binding.argument.split("x"))
    try:
        frame = _the_faces_of_the_flat_part(part)
    except Exception:  # noqa: BLE001
        frame = None
    if frame is None:
        return _blocked("the part could not be laid flat and sampled")
    inside, lo, hi = frame["inside"], frame["lo"], frame["hi"]
    a, b = frame["axes"]
    size = hi - lo
    step = max(float(np.sqrt(size[a] * size[b] / 300_000.0)), 0.05)
    us = np.arange(lo[a] - step, hi[a] + 2 * step, step)
    vs = np.arange(lo[b] - step, hi[b] + 2 * step, step)
    U, V = np.meshgrid(us, vs, indexing="ij")
    level = frame["top"] - height / 2.0
    points = np.zeros((U.size, 3))
    points[:, a], points[:, b], points[:, frame["thin"]] = U.ravel(), V.ravel(), level
    solid = np.asarray(inside(points), dtype=bool).reshape(U.shape)
    labels, count = _regions_of(solid)
    # Where the part's ends and sides are: its plate's, laid flat, read
    # where its openings are read.
    flat = _the_openings_laid_flat(part)
    if flat is not None:
        lo, hi = np.asarray(flat["lo"], dtype=float), np.asarray(
            flat["hi"], dtype=float)
    def the_pieces(U: Any, V: Any, solid: Any, labels: Any, count: int,
                   step: float, whole: bool) -> list[dict[str, Any]]:
        border = set() if whole else set(np.unique(np.concatenate([
            labels[0, :], labels[-1, :], labels[:, 0],
            labels[:, -1]])).tolist())
        found = []
        for label in range(1, count + 1):
            mask = labels == label
            if label in border or int(mask.sum()) < (4 if whole else 1):
                continue
            across_a = float(U[mask].max() - U[mask].min()) + step
            across_b = float(V[mask].max() - V[mask].min()) + step
            found.append({
                "across": (round(across_a, 3), round(across_b, 3)),
                "at": ((float(U[mask].max()) + float(U[mask].min())) / 2,
                       (float(V[mask].max()) + float(V[mask].min())) / 2),
                "step": step})
        return found

    pieces = the_pieces(U, V, solid, labels, count, step, True)
    # A piece a few grid steps across, or one the grid barely touched, read
    # again on a fine grid round it: a 10 mm boss on a 2000 mm plate is three
    # steps of 3.6 mm across, and was either skipped as too small to be a
    # piece or read as a size it is not.
    small = []
    for label in range(1, count + 1):
        mask = labels == label
        extent = max(float(U[mask].max() - U[mask].min()),
                     float(V[mask].max() - V[mask].min())) + step
        if extent < _FEW_STEPS * step:
            small.append(((float(U[mask].max()) + float(U[mask].min())) / 2,
                          (float(V[mask].max()) + float(V[mask].min())) / 2,
                          extent / 2.0 + 2.0 * step, extent))
    if small:
        closely: list[dict[str, Any]] = []
        for at_a, at_b, half, extent in small[:_CLOSE_READS]:
            fine = max(min(step, extent / 40.0), 0.02)
            fu = np.arange(at_a - half, at_a + half + fine, fine)
            fv = np.arange(at_b - half, at_b + half + fine, fine)
            FU, FV = np.meshgrid(fu, fv, indexing="ij")
            near = np.zeros((FU.size, 3))
            near[:, a], near[:, b], near[:, frame["thin"]] = (
                FU.ravel(), FV.ravel(), level)
            there = np.asarray(inside(near), dtype=bool).reshape(FU.shape)
            flabels, fcount = _regions_of(there)
            for piece in the_pieces(FU, FV, there, flabels, fcount, fine,
                                    False):
                if not any(math.dist(piece["at"], other["at"]) <= 2 * fine
                           for other in closely):
                    closely.append(piece)
        if closely:
            pieces = [p for p in pieces
                      if max(p["across"]) >= _FEW_STEPS * step
                      or not any(math.dist(p["at"], c["at"])
                                 <= max(c["across"]) / 2.0 + step
                                 for c in closely)] + closely
    sized = [p for p in pieces if all(
        abs(x - diameter) <= max(1.5 * p["step"], 0.02 * diameter)
        for x in p["across"])]
    everything = ", ".join(f"{p['across'][0]:g} x {p['across'][1]:g} at "
                           f"({p['at'][0]:g}, {p['at'][1]:g})"
                           for p in pieces) or "none"
    if not sized:
        return _blocked(
            f"nothing {diameter:g} mm across stands {height:g} mm proud of "
            "the part",
            hint=(f"cut {height / 2:g} mm below the part's top, at "
                  f"{'xyz'[frame['thin']]}={level:g}, the pieces of material "
                  f"are: {everything}"))
    along_spec, across_spec = binding.sub_argument.split(",")

    def targets(spec: str, axis: int) -> list[float]:
        low, high = float(lo[axis]), float(hi[axis])
        if spec.startswith("mid"):
            return [(low + high) / 2.0 + float(spec[3:] or 0.0)]
        figure = float(_re.sub(r"[a-z]", "", spec))
        if spec.startswith("lo"):
            return [low + figure]
        if spec.startswith("hi"):
            return [high - figure]
        return [low + figure, high - figure]

    longer, shorter = (a, b) if size[a] >= size[b] else (b, a)
    best = None
    for t_along in targets(along_spec, longer):
        for t_across in targets(across_spec, shorter):
            spot = {longer: t_along, shorter: t_across}
            for piece in sized:
                where = {a: piece["at"][0], b: piece["at"][1]}
                gap = math.hypot(where[a] - spot[a], where[b] - spot[b])
                if best is None or gap < best[0]:
                    best = (gap, piece, spot)
    gap, piece, spot = best
    return Measurement(
        Q(round(gap, 3), "mm"), method="sampling",
        limitations=(f"read on a {step:.2f} mm grid, {height / 2:g} mm below "
                     "the part's top",),
        detail={
            "measurement": f"standing_at:{binding.argument}:"
                           f"{binding.sub_argument}",
            "hint": (f"the {diameter:g} mm round solid standing {height:g} mm "
                     f"proud is centred at ({piece['at'][0]:g}, "
                     f"{piece['at'][1]:g}), {gap:.2f} mm from where it belongs ("
                     + ", ".join(f"{'xyz'[k]}={v:g}" for k, v in spot.items())
                     + f"). Pieces of material at that height: {everything}.")})


class _ToolBore:
    """A bore cut by a cylinder taken away by a `subtract` -- the guide's own
    way to repeat a cut: a cylinder, patterned, subtracted -- shaped like the
    bore a `hole` publishes, so it is counted and placed the same way."""

    entity_type = "cylindrical_face"

    def __init__(self, name: str, centre: Any, direction: Any, radius: float,
                 length: float) -> None:
        from forge_kernel.lineage import Frame

        self.name = name
        self.frame = Frame.from_axis(tuple(float(c) for c in centre),
                                     tuple(float(c) for c in direction))
        self.dimensions = {"radius": float(radius), "length": float(length)}
        self.warps = ()


def _cylinders_taken_away(solid: Any) -> list[tuple[Any, Any, float, float]]:
    """Every cylinder a difference in the solid takes away, where it is in
    the world: (base, unit axis, radius, height). Through rigid moves,
    linear and circular patterns, mirrors and unions of tools."""
    import numpy as np

    from forge_geom.sdf import (
        CylinderSDF, Difference, Mirror, Repeat, Transform, Union,
    )

    found: list[tuple[Any, Any, float, float]] = []

    def tools(node: Any, rotation: Any, shift: Any, depth: int) -> None:
        if depth > 40:
            return
        if isinstance(node, CylinderSDF):
            axis = np.asarray(node.axis, dtype=float)
            axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
            base = rotation @ np.asarray(node.base, dtype=float) + shift
            found.append((base, rotation @ axis, float(node.radius),
                          float(node.height)))
        elif isinstance(node, Transform):
            moved = node.matrix
            tools(node.solid, rotation @ moved,
                  rotation @ np.asarray(node.translation, dtype=float) + shift,
                  depth + 1)
        elif isinstance(node, Repeat):
            step = np.asarray(node.step, dtype=float)
            for index in range(int(node.count)):
                tools(node.solid, rotation, shift + rotation @ (step * index),
                      depth + 1)
        elif isinstance(node, Mirror):
            normal = np.asarray(node.normal, dtype=float)
            normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
            reflection = np.eye(3) - 2.0 * np.outer(normal, normal)
            offset = 2.0 * float(np.asarray(node.point, dtype=float) @ normal) \
                * normal
            if node.keep_original:
                tools(node.solid, rotation, shift, depth + 1)
            tools(node.solid, rotation @ reflection,
                  rotation @ offset + shift, depth + 1)
        elif isinstance(node, Union):
            for operand in node.operands:
                tools(operand, rotation, shift, depth + 1)

    from forge_geom.sdf import Intersection, Offset, Shell

    def walk(node: Any, rotation: Any, shift: Any, depth: int) -> None:
        # Only through what leaves space where it was -- unions, rigid
        # moves, patterns, mirrors, shells -- carrying each move with it. A
        # bend, a revolve, carries what is inside it somewhere else: the
        # four holes of a curved plate, read from inside its bend, were
        # four more holes in the flat plate's places, and the plate was
        # failed for having eight.
        if node is None or depth > 60:
            return
        if isinstance(node, Difference):
            for tool in node.tools:
                tools(tool, rotation, shift, 0)
            walk(node.base, rotation, shift, depth + 1)
        elif isinstance(node, (Union, Intersection)):
            for operand in node.operands:
                walk(operand, rotation, shift, depth + 1)
        elif isinstance(node, (Shell, Offset)):
            walk(getattr(node, "solid", None), rotation, shift, depth + 1)
        elif isinstance(node, Transform):
            walk(node.solid, rotation @ node.matrix,
                 rotation @ np.asarray(node.translation, dtype=float) + shift,
                 depth + 1)
        elif isinstance(node, Repeat):
            step = np.asarray(node.step, dtype=float)
            for index in range(int(node.count)):
                walk(node.solid, rotation, shift + rotation @ (step * index),
                     depth + 1)
        elif isinstance(node, Mirror):
            normal = np.asarray(node.normal, dtype=float)
            normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
            reflection = np.eye(3) - 2.0 * np.outer(normal, normal)
            offset = 2.0 * float(np.asarray(node.point, dtype=float) @ normal) \
                * normal
            if node.keep_original:
                walk(node.solid, rotation, shift, depth + 1)
            walk(node.solid, rotation @ reflection, rotation @ offset + shift,
                 depth + 1)

    try:
        walk(solid, np.eye(3), np.zeros(3), 0)
    except Exception:  # noqa: BLE001 - a tree it cannot read has none
        return []
    return found


def _bores_cut_by_tools(component: Component, part: CompiledPart
                        ) -> list[_ToolBore]:
    """The open holes the part has that no `hole` feature drilled: cylinders
    taken away by a `subtract`, each copy of a patterned one on its own --
    found on the part, not read off the document. A cylinder on the line of
    a `hole` (its own cut, or a counterbore) is that hole's."""
    import numpy as np

    lines = []
    for feature in component.features:
        if feature.kind != "hole":
            continue
        prefix = feature.role or feature.identifier
        axis = part.geometry_map.get(f"{prefix}.axis") or part.geometry_map.get(
            f"{prefix}.bore")
        if axis is None:
            continue
        direction = np.asarray(axis.frame.z_axis, dtype=float)
        direction = direction / max(float(np.linalg.norm(direction)), 1e-12)
        lines.append((np.asarray(axis.frame.origin, dtype=float), direction))

    bores: list[_ToolBore] = []
    taken: list[tuple[Any, Any, float]] = []
    for index, (base, axis, radius, height) in enumerate(
            _cylinders_taken_away(part.solid)):
        if radius <= 0.0 or height <= 0.0:
            continue
        on_a_hole = False
        for point, direction in lines:
            if abs(abs(float(axis @ direction)) - 1.0) > 1e-6:
                continue
            gap = base - point
            gap = gap - (gap @ direction) * direction
            if float(np.linalg.norm(gap)) < max(1e-3, 0.05 * radius):
                on_a_hole = True
                break
        if on_a_hole:
            continue
        duplicate = False
        for point, direction, other in taken:
            if abs(other - radius) > 1e-6 or abs(
                    abs(float(axis @ direction)) - 1.0) > 1e-6:
                continue
            gap = base - point
            gap = gap - (gap @ direction) * direction
            if float(np.linalg.norm(gap)) < max(1e-3, 0.05 * radius):
                duplicate = True
                break
        if duplicate:
            continue
        # Where along its length it cuts the part: the stretch where a ring
        # just outside it finds material and its own centre finds none.
        stations = np.linspace(0.0, height, 97)
        centres = base + np.outer(stations, axis)
        helper = np.array([1.0, 0.0, 0.0])
        if abs(float(axis @ helper)) > 0.9:
            helper = np.array([0.0, 1.0, 0.0])
        across = np.cross(axis, helper)
        across /= np.linalg.norm(across)
        other_way = np.cross(axis, across)
        angles = np.linspace(0.0, 2.0 * np.pi, 16, endpoint=False)
        ring = (radius + min(0.5, 0.25 * radius)) * (
            np.outer(np.cos(angles), across)
            + np.outer(np.sin(angles), other_way))
        try:
            outside = (np.asarray(part.solid((centres[:, None, :]
                                              + ring[None, :, :]).reshape(
                -1, 3))) < -1e-6).reshape(97, 16)
            middle = np.asarray(part.solid(centres)) > 1e-6
        except Exception:  # noqa: BLE001
            continue
        walled = outside.any(axis=1) & middle
        if not walled.any():
            continue
        if not (outside[walled].all(axis=1).any()
                or outside[walled].any(axis=0).all()):
            continue  # a groove or a notch, not a hole
        where = stations[walled]
        start, stop = float(where.min()), float(where.max())
        centre = base + axis * ((start + stop) / 2.0)
        taken.append((base, axis, radius))
        bores.append(_ToolBore(f"cut_{index}", centre, axis, radius,
                               max(stop - start, height / 96.0)))
    return bores


def _holes_of_diameter(
    component: Component, part: CompiledPart, binding: MeasurementBinding
) -> Measurement:
    """How many open holes of one diameter the built part has.

    Read off the geometry the kernel published for each hole: its bore's
    radius and its axis. A hole whose bore a later feature filled back in is
    not counted, because the part does not have it.

    With `on_axis`, only holes running down the axis the part is roundest
    about, through its centre -- a collar's bore, not its set screws. That
    axis is taken even on a part that fails to be round: whether the part is
    round is `roundness`'s claim to make, and a square block drilled down its
    middle still has its bore where the brief put it.
    """
    import numpy as np

    size = float(binding.argument)
    tolerance = max(0.01, size * 1e-3)
    buried = {entity.name for entity in part.buried_entities()}

    axis_index: int | None = None
    centre = None
    if binding.sub_argument == "on_axis":
        round_about = _roundness(part)
        if not round_about.ok:
            return round_about
        axis_index = "xyz".index(round_about.detail["about"])
        envelope = part.solid.envelope
        centre = (np.asarray(envelope.lo, dtype=float)
                  + np.asarray(envelope.hi, dtype=float)) / 2.0

    found: list[float] = []
    counted: list[str] = []
    merged: list[str] = []
    notches: list[str] = []
    lines: list[tuple[Any, Any]] = []
    for feature in component.features:
        if feature.kind != "hole":
            continue
        prefix = feature.role or feature.identifier
        bore = part.geometry_map.get(f"{prefix}.bore")
        if bore is None or f"{prefix}.bore" in buried:
            continue
        diameter = 2.0 * float(bore.dimensions.get("radius", 0.0))
        found.append(round(diameter, 4))
        if abs(diameter - size) > tolerance:
            continue
        if not a_bore_with_material_all_round(part, bore):
            notches.append(feature.identifier)
            continue
        if axis_index is not None:
            axis = part.geometry_map.get(f"{prefix}.axis")
            if axis is None:
                continue
            direction = np.asarray(axis.frame.z_axis, dtype=float)
            direction = direction / max(float(np.linalg.norm(direction)), 1e-12)
            if abs(abs(float(direction[axis_index])) - 1.0) > 1e-3:
                continue
            origin = np.asarray(axis.frame.origin, dtype=float)
            offset = origin - centre
            offset[axis_index] = 0.0
            if float(np.linalg.norm(offset)) > max(0.5, 0.1 * size):
                continue
        # Two holes down one line are one opening: an exoskeleton rail's
        # mounting hole drilled exactly where its pivot was counted as a
        # third 8.2 mm hole on a part that has two.
        axis_entity = part.geometry_map.get(f"{prefix}.axis") or bore
        try:
            direction = np.asarray(axis_entity.frame.z_axis, dtype=float)
            direction = direction / max(float(np.linalg.norm(direction)),
                                        1e-12)
            through = np.asarray(axis_entity.frame.origin, dtype=float)
        except Exception:  # noqa: BLE001 - a hole with no frame is counted
            direction = through = None
        if direction is not None:
            same = False
            # Its own name: `centre` is the part's middle, which the on-axis
            # test of every later hole reads.
            here = np.asarray(bore.frame.origin, dtype=float)
            reach = float(bore.dimensions.get("length", 0.0)) / 2.0
            for other_direction, other_point, other_centre, other_reach in lines:
                if abs(abs(float(direction @ other_direction)) - 1.0) > 1e-6:
                    continue
                gap = through - other_point
                gap = gap - (gap @ direction) * direction
                apart = abs(float((here - other_centre) @ direction))
                if (float(np.linalg.norm(gap)) <= 0.25 * size
                        and apart <= reach + other_reach + 1e-6):
                    same = True
                    break
            if same:
                merged.append(feature.identifier)
                continue
            lines.append((direction, through, here, reach))
        counted.append(feature.identifier)
    # And the holes no `hole` drilled: cylinders taken away by a `subtract`,
    # a pattern of them counted as each copy it makes -- the construction the
    # authoring guide teaches for repeated cuts, which counted as none.
    for bore in _bores_cut_by_tools(component, part):
        diameter = 2.0 * float(bore.dimensions["radius"])
        found.append(round(diameter, 4))
        if abs(diameter - size) > tolerance:
            continue
        if axis_index is not None:
            direction = np.asarray(bore.frame.z_axis, dtype=float)
            if abs(abs(float(direction[axis_index])) - 1.0) > 1e-3:
                continue
            offset = np.asarray(bore.frame.origin, dtype=float) - np.asarray(
                centre if centre is not None else bore.frame.origin)
            offset[axis_index] = 0.0
            if float(np.linalg.norm(offset)) > max(0.5, 0.1 * size):
                continue
        counted.append(bore.name)
    said = []
    if merged:
        said.append(", ".join(f"`{m}`" for m in merged)
                    + " run down the same line as another hole of the same "
                    "size: one opening, not two. Place each where the brief "
                    "puts it.")
    if notches:
        said.append(", ".join(f"`{m}`" for m in notches)
                    + " cut material without having any all the way round it "
                    "anywhere along what it cuts: a groove or a notch, not a "
                    "hole. See GEOM_HOLES_ARE_HOLES for where each runs.")
    return Measurement(
        Q(len(counted)),
        detail={
            "counted": counted,
            **({"one_opening_with_another": merged} if merged else {}),
            **({"not_holes": notches} if notches else {}),
            **({"hint": " ".join(said)} if said else {}),
            "every_open_hole_mm": sorted(found),
            "on_axis": binding.sub_argument == "on_axis",
        },
    )


def _the_wall_a_window_is_in(part: CompiledPart, window: Mapping[str, Any],
                             lo: Any, hi: Any) -> str:
    """Which wall a window goes through, "-y" or "+x": the wall its rays
    miss that the rays just beside it cross."""
    import numpy as np

    along = "xyz".index(window["along"])
    u, v = [i for i in range(3) if i != along]
    cu, cv = window["centre_mm"]
    su, sv = window["size_mm"]
    ts = np.arange(lo[along] - 1.0, hi[along] + 1.0, 0.25)

    def runs(pu: float, pv: float) -> list[tuple[float, float]]:
        ray = np.zeros((ts.size, 3))
        ray[:, u], ray[:, v], ray[:, along] = pu, pv, ts
        inside = np.asarray(part.solid(ray)) < 0.0
        found, start = [], None
        for t, flag in zip(ts, inside):
            if flag and start is None:
                start = t
            elif not flag and start is not None:
                found.append((float(start), float(t)))
                start = None
        return found

    through = runs(cu, cv)
    beside: list[tuple[float, float]] = []
    for du, dv in ((su / 2 + 3, 0), (-su / 2 - 3, 0), (0, sv / 2 + 3),
                   (0, -sv / 2 - 3)):
        beside = runs(cu + du, cv + dv)
        missing = [r for r in beside
                   if not any(a < r[1] and r[0] < b for a, b in through)]
        if missing:
            middle = (lo[along] + hi[along]) / 2.0
            centre = (missing[0][0] + missing[0][1]) / 2.0
            return ("+" if centre > middle else "-") + "xyz"[along]
    return ""


def _windows_of_size(part: CompiledPart, properties: MassProperties,
                     size: str, side: str = "") -> Measurement:
    """How many openings of a length and width go through a wall.

    Laid flat, an opening is a place where nothing is in the way. In a
    hollow part that is never so: through a window in the rear wall the
    view runs on to the inside of the front. A calf shell's 210 by 60 mm
    access opening was cut with a box too shallow for its tapering back --
    open for the top 130 mm, a skin 1 to 6 mm thick below -- and passed,
    because the only claim on it read the design's own parameters.

    So: rays along each axis, over a grid across the other two, each
    counting the separate walls it crosses. A window is a patch of rays
    crossing fewer walls than every ray round it, enclosed by them; its
    size is the patch's extent. Counted when it is the size asked, either
    way round, to within two grid steps.
    """
    import numpy as np
    from forge_units import parse_unit

    a, b = (float(x) for x in re.split(r"[x*]", size))
    length, width = max(a, b), min(a, b)
    millimetre = parse_unit("mm")
    lo = np.array([float(q.to(millimetre).magnitude.midpoint)
                   for q in properties.bounding_box_lo])
    hi = np.array([float(q.to(millimetre).magnitude.midpoint)
                   for q in properties.bounding_box_hi])
    extent = hi - lo
    step = max(0.5, float(extent.max()) / 320.0, width / 30.0)
    found: list[dict[str, Any]] = []
    for along in range(3):
        u, v = [i for i in range(3) if i != along]
        us = np.arange(lo[u] + step / 2, hi[u], step)
        vs = np.arange(lo[v] + step / 2, hi[v], step)
        if us.size < 3 or vs.size < 3:
            continue
        ds = min(step / 2.0, 0.5)
        ts = np.arange(lo[along] - ds, hi[along] + ds, ds)
        walls = np.zeros((us.size, vs.size), dtype=int)
        for i, uu in enumerate(us):
            grid = np.empty((vs.size * ts.size, 3))
            grid[:, u] = uu
            grid[:, v] = np.repeat(vs, ts.size)
            grid[:, along] = np.tile(ts, vs.size)
            inside = (np.asarray(part.solid(grid)) < 0.0).reshape(vs.size,
                                                                  ts.size)
            walls[i] = (np.count_nonzero(inside[:, 1:] & ~inside[:, :-1],
                                         axis=1) + inside[:, 0])
        for level in sorted(set(walls.ravel().tolist()), reverse=True):
            if level < 1:
                continue
            mask = walls < level
            label = -np.ones(mask.shape, dtype=int)
            count = 0
            for start in zip(*np.nonzero(mask)):
                if label[start] >= 0:
                    continue
                stack, cells = [start], []
                label[start] = count
                while stack:
                    ci, cj = stack.pop()
                    cells.append((ci, cj))
                    for ni, nj in ((ci + 1, cj), (ci - 1, cj), (ci, cj + 1),
                                   (ci, cj - 1)):
                        if 0 <= ni < mask.shape[0] and 0 <= nj < mask.shape[1] \
                                and mask[ni, nj] and label[ni, nj] < 0:
                            label[ni, nj] = count
                            stack.append((ni, nj))
                count += 1
                rows = [c[0] for c in cells]
                cols = [c[1] for c in cells]
                if min(rows) == 0 or min(cols) == 0 or max(
                        rows) == mask.shape[0] - 1 or max(
                        cols) == mask.shape[1] - 1:
                    continue  # runs off the part: an edge, not a window
                ring = set()
                for ci, cj in cells:
                    for ni, nj in ((ci + 1, cj), (ci - 1, cj), (ci, cj + 1),
                                   (ci, cj - 1)):
                        if not mask[ni, nj]:
                            ring.add(int(walls[ni, nj]))
                if min(ring, default=0) < level:
                    continue
                span_u = (max(rows) - min(rows) + 1) * step
                span_v = (max(cols) - min(cols) + 1) * step
                window = {"along": "xyz"[along],
                          "size_mm": [round(span_u, 2), round(span_v, 2)],
                          "centre_mm": [
                              round(float(us[(min(rows) + max(rows)) // 2]), 2),
                              round(float(vs[(min(cols) + max(cols)) // 2]), 2)],
                          "cells": len(cells)}
                if window not in found:
                    found.append(window)
    slack = 2.0 * step + 0.5
    matching = [w for w in found
                if abs(max(w["size_mm"]) - length) <= slack
                and abs(min(w["size_mm"]) - width) <= slack]
    # Through which wall: "the rear wall only, on the negative-Y side". A
    # calf shell's opening the right size, cut through the front, counted.
    wrong_side: list[str] = []
    if side:
        for w in matching:
            w["wall"] = _the_wall_a_window_is_in(part, w, lo, hi)
        wrong_side = [w["wall"] or "?" for w in matching if w["wall"] != side]
        matching = [w for w in matching if w["wall"] == side]
    seen = sorted({tuple(sorted(w["size_mm"], reverse=True)) for w in found},
                  reverse=True)[:8]
    # Where the wall still stands, in numbers: along the ray through the
    # nearest opening found, at stations across the length asked for. The
    # analyst of a calf shell whose opening came out 102 of 210 mm tall knew
    # only that the cutter was too shallow, not where the wall was.
    walls_there = ""
    if not matching and found:
        best = min(found, key=lambda w: abs(min(w["size_mm"]) - width)
                   + abs(max(w["size_mm"]) - length))
        along = "xyz".index(best["along"])
        u, v = [i for i in range(3) if i != along]
        # The asked length runs across the found window's side that is not
        # the asked width: a 60 x 22 slot at the top of a 210 x 60 window
        # wanted is 60 across and 22 of the 210 up.
        su, sv = best["size_mm"]
        long_is_u = abs(sv - width) <= abs(su - width)
        k, other = (u, v) if long_is_u else (v, u)
        cu, cv = best["centre_mm"]
        centre_k = cu if long_is_u else cv
        fixed = cv if long_is_u else cu
        said = []
        for t in np.linspace(centre_k - length / 2 + 2.0,
                             centre_k + length / 2 - 2.0, 7):
            ts = np.arange(lo[along] - 1.0, hi[along] + 1.0, 0.25)
            ray = np.zeros((ts.size, 3))
            ray[:, k], ray[:, other], ray[:, along] = t, fixed, ts
            inside = np.asarray(part.solid(ray)) < 0.0
            runs, start = [], None
            for value, flag in zip(ts, inside):
                if flag and start is None:
                    start = value
                elif not flag and start is not None:
                    runs.append(f"{start:.1f} to {value:.1f}")
                    start = None
            said.append(f"{'xyz'[k]}={t:.0f}: " + (", ".join(runs) or "none"))
        walls_there = (
            f" Through the nearest one ({max(best['size_mm']):g} x "
            f"{min(best['size_mm']):g} at {'xyz'[u]}={cu:g}, {'xyz'[v]}={cv:g}, "
            f"seen along {best['along']}), the material along {best['along']} "
            f"across the {length:g} mm asked is at -- " + "; ".join(said)
            + ". Wherever two walls still show, the cut has not reached the "
            "near one.")
    return Measurement(
        Q(len(matching)), method="sampling",
        limitations=(f"read on rays {step:.2f} mm apart along each axis",),
        detail={"windows": found[:12], "hint": (
            f"{len(matching)} opening(s) {length:g} by {width:g} mm through a "
            "wall; openings found: " + (", ".join(
                f"{s[0]:g} x {s[1]:g}" for s in seen) or "none")
            + ". An opening cut through a wall that leans or curves needs a "
            "cutter deep enough to clear the wall over all of it."
            + (f" {len(wrong_side)} of that size went through the wrong "
               f"wall ({', '.join(wrong_side)}), not the {side} one the brief "
               "names: move the cutter to that side of the part."
               if wrong_side else "")
            + ("" if wrong_side else walls_there))})


def _walls_crossed(
    component: Component, part: CompiledPart, binding: MeasurementBinding
) -> Measurement:
    """The most separate walls any open hole of one diameter cuts.

    Six mounting holes "on the rear surface" of a hollow calf shell were
    drilled straight through it on Y: each opened in the rear wall, crossed
    the hollow, and opened again in the front -- twelve holes in the shell,
    six of them on a face the brief never put a hole on, and every gate
    passed. Read off what the kernel found along each hole's axis, over the
    stretch it cuts, in the solid it was cut from."""
    size = float(binding.argument)
    tolerance = max(0.01, size * 1e-3)
    buried = {entity.name for entity in part.buried_entities()}
    each: dict[str, int] = {}
    for feature in component.features:
        if feature.kind != "hole":
            continue
        prefix = feature.role or feature.identifier
        bore = part.geometry_map.get(f"{prefix}.bore")
        if bore is None or f"{prefix}.bore" in buried:
            continue
        diameter = 2.0 * float(bore.dimensions.get("radius", 0.0))
        if abs(diameter - size) > tolerance:
            continue
        each[feature.identifier] = int(bore.dimensions.get("walls", 1))
    if not each:
        return Measurement(Q(0), detail={"holes": {}, "hint": (
            f"no open {size:g} mm hole to read")})
    most = max(each.values())
    through_two = sorted(k for k, v in each.items() if v > 1)
    return Measurement(
        Q(most),
        detail={"walls_each_cuts": each, "hint": (
            (", ".join(f"`{k}`" for k in through_two)
             + " run on through the facing wall: each opens in the wall it "
             "is drilled from, crosses the hollow, and opens again on the far "
             "side. Give each `through: first_wall`, with `position` inside "
             "the hollow and `axis` pointing at the wall it belongs to, and "
             "drop its `depth`: it then cuts that wall alone, however thick "
             "or curved the wall is there.")
            if through_two else f"each {size:g} mm hole cuts one wall")})


def _angle_between(
    component: Component, part: CompiledPart, binding: MeasurementBinding
) -> Measurement:
    """The angle between the axes of the two tagged features, on the part.

    The first measurement in this vocabulary that is about a RELATIONSHIP
    between two pieces of geometry rather than a quantity of one.

    It exists because of a collar that passed every geometric gate it had and
    was still the wrong part. Its two set screw holes were drilled parallel
    to the bore, down the length of the wall, 180 degrees apart, opening into
    nothing. They cut material, they reached the surface, their bores
    survived, every dimension drove something -- so `GEOM_BORES_SURVIVE`,
    `GEOM_FEATURES_CONTRIBUTE` and the rest were all satisfied, correctly.
    Nothing in the system looked at where the holes POINTED.

    The brief said "90 degrees apart". The only way to check that was
    `parameter:<id>`, which reads back a number the design wrote about
    itself, and the design duly wrote `angle = 90 deg` while building 0. This
    reads the axes off the finished geometry instead, so a design cannot
    satisfy it by declaring anything.

    Exactly two, because "apart" is a statement about a pair. More or fewer
    is reported BLOCKED naming what was found, which also makes this a
    count check in passing: a requirement that two things are 90 degrees
    apart is not met by three things or by one.
    """
    matching = [
        feature for feature in component.features
        if feature.kind == binding.argument
    ]
    tagged = [f for f in matching if binding.sub_argument in f.tags]
    if len(tagged) != 2:
        return _blocked(
            f"the angle is between two features and "
            f"{len(tagged)} `{binding.argument}` features are tagged "
            f"'{binding.sub_argument}'",
            tagged=[f.identifier for f in tagged],
            tags_present=sorted({t for f in matching for t in f.tags})[:20],
            hint=(
                f"tag exactly the two `{binding.argument}` features this "
                f'requirement is about with "tags": '
                f'["{binding.sub_argument}"]'
            ),
        )

    axes: list[tuple[str, Any]] = []
    for feature in tagged:
        name = f"{feature.role or feature.identifier}.axis"
        entity = _entity_or_none(part, name)
        if entity is None:
            return _blocked(
                f"`{feature.identifier}` publishes no axis, so there is no "
                "direction to measure",
                looked_for=name,
            )
        axes.append((feature.identifier, entity.frame.z_axis))

    (first_name, first), (second_name, second) = axes
    one = [float(v) for v in first]
    two = [float(v) for v in second]
    scale_one = math.sqrt(sum(v * v for v in one))
    scale_two = math.sqrt(sum(v * v for v in two))
    if scale_one < 1e-12 or scale_two < 1e-12:
        return _blocked("a tagged feature has no direction to measure")
    dot = sum(a * b for a, b in zip(one, two)) / (scale_one * scale_two)
    degrees = math.degrees(math.acos(max(-1.0, min(1.0, dot))))
    return Measurement(
        Q(degrees, "deg"),
        detail={
            "between": [first_name, second_name],
            f"{first_name}_axis": [round(v / scale_one, 6) for v in one],
            f"{second_name}_axis": [round(v / scale_two, 6) for v in two],
        },
    )


def _entity_or_none(part: CompiledPart, name: str) -> Any:
    try:
        return part.geometry_map.resolve(name)
    except SelectionError:
        return None


def _entity_dimension(entity: Any, key: str) -> Quantity | None:
    """Read a dimension off a published entity.

    ``diameter`` is accepted as sugar for twice the radius. Engineers specify
    bores by diameter, the geometry stores a radius, and making the document
    author do that conversion invites exactly the factor-of-two error the units
    layer exists to prevent.
    """
    dimensions = entity.dimensions
    if key == "diameter":
        radius = dimensions.get("radius")
        return Q(float(radius) * 2.0, "mm") if radius is not None else None
    if key in dimensions:
        return Q(float(dimensions[key]), "mm")
    return None


def _safety_factor(
    binding: MeasurementBinding,
    component: Component,
    part: CompiledPart,
    load: Quantity | None,
) -> Measurement:
    """Screening margins derived from a declared bore interface and a load.

    Only the checks that follow from what the document actually declares are
    computed. Root bending, notably, is *not*: it needs a section the geometry
    does not label, and guessing one would produce a confident number about the
    wrong cross-section. That gap is reported rather than filled.
    """
    if load is None:
        return _blocked(
            "no load is declared in the document, so no structural margin can "
            "be computed. State the load as an assumption with a force value."
        )
    if not component.material:
        return _blocked("the component declares no material")
    try:
        material = lookup(component.material)
    except MaterialError as error:
        return _blocked(error.message, material=component.material)

    if binding.argument == "bending":
        return _bending_of_a_bar(component, part, load, material)

    bore = _first_bore(component, part)
    if bore is None:
        return _blocked(
            "no `bore` interface resolves on this component, so there is "
            "nothing to compute a bearing or pin margin against",
            interfaces=[i.identifier for i in component.interfaces],
        )
    entity, interface_id = bore
    radius = float(entity.dimensions.get("radius", 0.0))
    # The metal the pin actually bears on, which is not the same as the bore's
    # overall span whenever the bore crosses a gap -- see the note in
    # forge_kernel's _material_span_along_axis.
    length = float(
        entity.dimensions.get("bearing_length", entity.dimensions.get("length", 0.0))
    )
    if radius <= 0.0 or length <= 0.0:
        return _blocked("the bore has no usable radius or bearing length")

    diameter = Q(radius * 2.0, "mm")
    limitations = (
        "closed-form screening against a single static load case",
        "no stress concentration factor is applied; the true peak is higher",
        f"bearing length taken as the {length:.1f} mm of material the bore "
        "passes through",
    )

    if binding.argument == "bearing":
        demand = bearing_stress(load, diameter, Q(length, "mm"))
        margin = safety_factor(material.yield_strength, demand.value)
        return Measurement(
            margin.value,
            method="analytical",
            limitations=limitations + tuple(demand.limitations),
            detail={
                "interface": interface_id,
                "formula": demand.formula,
                "demand": str(demand.value),
            },
        )

    if binding.argument == "pin_shear":
        area = Q(math.pi * radius * radius, "mm^2")
        demand = direct_shear_stress(load, area, double_shear=True)
        margin = safety_factor(material.yield_strength * 0.577, demand.value)
        return Measurement(
            margin.value,
            method="analytical",
            limitations=limitations
            + tuple(demand.limitations)
            + (
                "shear yield taken as 0.577 x tensile yield (von Mises); a "
                "convention, not a measured property",
                "the pin is assumed to share the component's material, which a "
                "real shoulder pin will not",
            ),
            detail={
                "interface": interface_id,
                "formula": demand.formula,
                "demand": str(demand.value),
            },
        )

    return _blocked(f"unknown safety factor '{binding.argument}'")


def _bending_of_a_bar(
    component: Component, part: CompiledPart, load: Quantity, material: Any
) -> Measurement:
    """The root bending margin of a straight bar bolted at one end.

    The cantilever bracket: a 60 x 20 x 6 bar, two bolt holes near one end,
    150 N on the other. The bar's own faces give its length, width and
    thickness; the holes through its thickness say which end is held. The
    support is taken at the bolt nearest the free end -- everything beyond
    it is the arm -- and the section there is the bar's width less the holes
    that cross it, bending about its thin direction:

        M = F * arm,  sigma = M * (t/2) / (b_net * t^3 / 12)

    Only for what that formula is true of: one box and the holes in it. An
    L, a ribbed or tapered arm, or a bar with no hole to hold it by has no
    single section and arm to read off, and is reported as not computed
    rather than given a number about the wrong cross-section.
    """
    kinds = {feature.kind for feature in component.features}
    boxes = [f for f in component.features if f.kind == "box"]
    if len(boxes) != 1 or not kinds <= {"box", "hole"}:
        return _blocked(
            "a bending margin is computed for a straight bar -- one box with "
            "holes in it -- and this part is built from "
            + ", ".join(sorted(kinds)),
        )
    bar = boxes[0].role or boxes[0].identifier
    faces = []
    for axis in "xyz":
        low = _entity_or_none(part, f"{bar}.{axis}_min")
        high = _entity_or_none(part, f"{bar}.{axis}_max")
        if low is None or high is None:
            return _blocked(f"`{bar}` publishes no {axis} faces to measure")
        index = "xyz".index(axis)
        faces.append((float(low.frame.origin[index]),
                      float(high.frame.origin[index])))
    sides = [hi - lo for lo, hi in faces]
    along = max(range(3), key=lambda i: sides[i])
    thin = min(range(3), key=lambda i: sides[i])
    if along == thin:
        return _blocked("the bar has no length to bend along")
    across = 3 - along - thin

    holes = []
    for feature in component.features:
        if feature.kind != "hole":
            continue
        bore = _entity_or_none(part, f"{feature.role or feature.identifier}.bore")
        if bore is None:
            continue
        direction = [float(v) for v in bore.frame.z_axis]
        if abs(abs(direction[thin]) - 1.0) > 1e-6:
            continue
        holes.append((float(bore.frame.origin[along]),
                      float(bore.dimensions.get("radius", 0.0)),
                      feature.identifier))
    if not holes:
        return _blocked(
            "no hole runs through the bar's thickness, so nothing says which "
            "end is held: there is no support to bend about")
    middle = (faces[along][0] + faces[along][1]) / 2
    mean = sum(h[0] for h in holes) / len(holes)
    if abs(mean - middle) < 1e-6:
        return _blocked(
            "the holes are centred on the bar, so neither end is the held one")
    held_high = mean > middle
    free_face = faces[along][0] if held_high else faces[along][1]
    support = min(holes, key=lambda h: abs(h[0] - free_face))
    arm = abs(support[0] - free_face)
    width = sides[across]
    crossing = [h for h in holes if abs(h[0] - support[0]) < h[1]]
    net = width - sum(2.0 * h[1] for h in crossing)
    if net <= 0.0 or arm <= 0.0:
        return _blocked("the bar has no material left at its support")
    thickness = sides[thin]
    moment = cantilever_root_moment(load, Q(arm, "mm"))
    demand = bending_stress(moment.value, Q(thickness / 2.0, "mm"),
                            Q(net * thickness ** 3 / 12.0, "mm^4"))
    margin = safety_factor(material.yield_strength, demand.value)
    return Measurement(
        margin.value,
        method="analytical",
        limitations=(
            "closed-form screening against a single static load case",
            "the load taken at the very end of the bar, square to its "
            "thickness -- its weakest way to bend",
            "the bolts taken as a rigid built-in support at the one nearest "
            "the free end",
            "no stress concentration factor at the bolt holes; the true peak "
            "at a hole edge is higher",
        ) + tuple(demand.limitations),
        detail={
            "formula": "sigma = F*arm*(t/2) / (b_net*t^3/12)",
            "arm_mm": round(arm, 3),
            "support_hole": support[2],
            "section_mm": [round(net, 3), round(thickness, 3)],
            "moment": str(moment.value),
            "demand": str(demand.value),
        },
    )


def _first_bore(component: Component, part: CompiledPart) -> tuple[Any, str] | None:
    for interface in component.interfaces:
        if interface.interface_type != "bore":
            continue
        entity = _entity_or_none(part, interface.geometry)
        if entity is not None and entity.entity_type == "cylindrical_face":
            return entity, interface.identifier
    return None


def declared_load(component: Component, document: Any) -> Quantity | None:
    """The load the document itself states, or ``None``.

    Deliberately returns ``None`` rather than a default. A pipeline that
    substitutes a plausible load here would verify every design against a
    fiction, and report that it passed.
    """
    force_dimension = Q(1.0, "N").dimension
    for assumption in document.assumptions:
        if (
            assumption.value is not None
            and assumption.value.dimension == force_dimension
        ):
            return assumption.value
    for requirement in document.requirements:
        if (
            requirement.threshold is not None
            and requirement.threshold.dimension == force_dimension
        ):
            return requirement.threshold
    return None


__all__ = ["Measurement", "resolve_measurement", "declared_load"]


def _openings_cut_by_the_tag(component: Any, tag: str,
                             instances: Any) -> tuple[int, list[str]]:
    """How many openings the cuts carrying `tag` make, and which they are.

    A `subtract` carrying it makes one per tool it takes away (a patterned
    tool, one per copy); a tool carrying it is itself one. A tool tagged and
    taken away by a tagged `subtract` is counted once."""
    from forge_kernel.compiler import _cutting_tools

    by_id = {f.identifier: f for f in component.features}
    tools = _cutting_tools(component)
    total, which = 0, []
    for feature in component.features:
        if tag not in feature.tags:
            continue
        if feature.kind == "subtract":
            for name in list(feature.inputs or ())[1:]:
                tool = by_id.get(str(name))
                if tool is None or tag in tool.tags:
                    continue
                total += instances(tool)
                which.append(f"{feature.identifier}: {tool.identifier}")
        elif feature.identifier in tools:
            total += instances(feature)
            which.append(feature.identifier)
    return total, which

