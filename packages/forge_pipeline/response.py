"""What each declared dimension actually does to the finished object.

Every check in this system until now compares a *number* against a *number*.
`parameter:plate_thickness equals 4 mm` reads the design's own parameter table
and finds 4, which is true of a plate lying flat and equally true of the same
plate stood on its edge. The document says 4 mm and the object is 4 mm thick;
nothing anywhere asks **in which direction**.

That gap is the oldest unfixed thing in Forge. A run once reported PASS on a
spacer whose plate was built in the wrong plane, and the seven dimensional
requirements that passed were all telling the truth. Five later runs of a
shaft collar failed on bounding-box claims for the mirror-image reason: the
requirements engineer writes its claims before the design exists, so the axis
in `bounding_box_x` was a guess, and the guess was wrong two times in three.

Both are the same missing fact, and the kernel has always been able to supply
it. Nudge one parameter, recompile, measure, and see what moved. If raising
`plate_thickness` grows the part along Y and leaves Z alone, then that plate's
thickness runs along Y -- not as an inference, not as a reading of a name, but
as a measurement. It needs no model, no language, and no convention: it is the
design's own behaviour, observed.

Two properties make it practical rather than merely correct:

* **It is cheap.** The compiler is incremental and the override path already
  exists, so a probe is one warm compile and one coarse measurement -- about
  8 ms per parameter against the eight to eighteen *minutes* a local model
  spends writing the document. A part with a dozen dimensions costs a tenth of
  a second to interrogate completely.
* **It is deterministic.** No sampling, no heuristics, no names. The same
  document gives the same answer on every machine, which is the property that
  lets it be evidence rather than a hint.

What it deliberately does NOT do is guess intent. Knowing that the thickness
runs along Y does not tell Forge the plate is wrong -- a vertical web is a
real part, and the authoring guide says so. So the response is reported as the
fact it is, next to the requirement that named the dimension, where a person
reading "drives the y extent" sees in one glance what seven passing checks
could not tell them. The one thing it *does* assert is the one thing that
needs no intent at all: a dimension the design declares must change the
object. A number that moves nothing is paperwork.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from forge_geom import measure_mass_properties
from forge_ir import Component
from forge_kernel import CompiledPart, Compiler
from forge_units import Q, Quantity, parse_unit

#: Octree depth for a probe. Deliberately coarse: this measurement answers
#: "did it move, and along which axis", never "by exactly how much". The nudge
#: is chosen far larger than a cell, so the comparison has enormous margin and
#: the cost is a fraction of the verification measurement's.
PROBE_DEPTH = 6

#: A nudge must be unmistakable against a coarse measurement, and small enough
#: to stay inside any declared bounds. A tenth of the value, floored, is both.
_NUDGE_FRACTION = 0.10
_NUDGE_FLOOR_MM = 0.5

#: What counts as a response. An extent driven by a dimension moves nearly
#: one-for-one with it, so a twentieth of the nudge is a wide margin on both
#: sides; a dimension that changes anything at all moves volume by whole
#: percent, so a thousandth is likewise. Both are differences between two
#: measurements of nearly the same solid at the same depth, where the octree's
#: systematic error cancels and only its jitter remains.
_RESPONSE_FRACTION_OF_NUDGE = 0.05
_RESPONSE_FRACTION_OF_VOLUME = 0.001

#: Samples per axis in the shape fingerprint. The field is smooth, so this is
#: about resolving *where* a change happened, not whether one did: a change
#: anywhere perturbs the distance at many samples at once.
_FINGERPRINT_RESOLUTION = 16


@dataclass(frozen=True, slots=True)
class ParameterResponse:
    """How the finished part answered when one dimension was changed."""

    parameter: str
    #: "x", "y", "z" and/or "volume" -- what moved by more than the
    #: measurement could confuse with noise.
    moves: tuple[str, ...]
    #: Signed change in each extent, in millimetres.
    extent_change: tuple[float, float, float]
    #: Signed change in enclosed volume, in cubic millimetres.
    volume_change: float
    #: What was done, recorded so the number can be read in context.
    nudge: str
    #: Empty when the probe ran. Otherwise why it could not.
    skipped: str = ""
    #: How far a cutter reaches, and nothing else: past the material, any
    #: longer cuts the same. Moved and changing nothing, it is still the
    #: reach the cut needs -- not a dimension the part lacks.
    reach: bool = False

    @property
    def drives_nothing(self) -> bool:
        """The design declares this dimension and the object does not have it."""
        return not self.skipped and not self.moves and not self.reach

    @property
    def axis(self) -> str:
        """The single extent this dimension drives, when there is exactly one."""
        axes = tuple(m for m in self.moves if m in ("x", "y", "z"))
        return axes[0] if len(axes) == 1 else ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "moves": list(self.moves),
            "extent_change_mm": [round(v, 4) for v in self.extent_change],
            "volume_change_mm3": round(self.volume_change, 4),
            "nudge": self.nudge,
            "skipped": self.skipped,
            **({"reach": True} if self.reach else {}),
        }

    def describe(self) -> str:
        if self.skipped:
            return f"{self.parameter}: not probed ({self.skipped})"
        if not self.moves and self.reach:
            return (f"{self.parameter}: how far a cutter reaches -- already "
                    "past the material, so longer cuts the same")
        if not self.moves:
            return f"{self.parameter}: changes nothing about the part"
        if tuple(self.moves) == ("shape",):
            return (f"{self.parameter}: changes the part's shape without "
                    "measurably changing its size or volume -- a position, "
                    "or a small feature")
        axes = ", ".join(
            f"the {m} extent" for m in self.moves
            if m not in ("volume", "shape"))
        if "volume" in self.moves and not axes:
            return f"{self.parameter}: changes the volume and no extent"
        volume = " and the volume" if "volume" in self.moves else ""
        return f"{self.parameter}: drives {axes}{volume}"


def _centre(quantity: Any) -> float:
    magnitude = getattr(quantity, "magnitude", quantity)
    if hasattr(magnitude, "lo") and hasattr(magnitude, "hi"):
        return (float(magnitude.lo) + float(magnitude.hi)) / 2.0
    return float(magnitude)


def _width(quantity: Any) -> float:
    magnitude = getattr(quantity, "magnitude", quantity)
    if hasattr(magnitude, "lo") and hasattr(magnitude, "hi"):
        return abs(float(magnitude.hi) - float(magnitude.lo))
    return 0.0


def _sampling_grid(solid: Any, resolution: int = _FINGERPRINT_RESOLUTION) -> Any:
    """A fixed lattice of points spanning the part, with room around it.

    Fixed is the operative word: every probe is evaluated on this same grid,
    built once from the design as written, so two fingerprints are always
    comparable. Padded, because a dimension that grows the part would
    otherwise push the change outside the window that is watching for it.
    """
    envelope = solid.envelope
    lo = np.asarray(envelope.lo, dtype=float)
    hi = np.asarray(envelope.hi, dtype=float)
    span = np.maximum(hi - lo, 1e-6)
    lo, hi = lo - span * 0.25, hi + span * 0.25
    axes = [np.linspace(lo[i], hi[i], resolution) for i in range(3)]
    mesh = np.meshgrid(*axes, indexing="ij")
    return np.stack([m.ravel() for m in mesh], axis=1)


def _with_the_surface(solid: Any, grid: Any) -> Any:
    """The lattice, plus points on the part's own surface.

    The lattice alone is 16 samples a side over the padded envelope -- a
    point every 4 mm on a 40 mm plate, every 10 on a 100 mm one. A 3 mm hole
    fits between them, and so does everything that happens to its wall: a
    3 mm hole in a 2 mm plate, nudged to 3.5, moved no lattice sample, moved
    the volume by 0.16 per cent -- under the thousandth that counts as a
    change -- and was reported as a dimension the part does not have. A
    small hole in a plate is the commonest feature there is, and GEOM_
    DIMENSIONS_DRIVE_THE_PART failed a correct part over it.

    Points ON the surface are where any change to it shows first: nudge the
    hole and the distance at every sample on its wall moves by the nudge.
    Nothing is made easier to pass -- a dimension that really drives nothing
    leaves every one of these distances exactly where it was.
    """
    try:
        from forge_geom.measure import surface_samples

        surface = np.asarray(surface_samples(solid), dtype=float)
    except Exception:  # noqa: BLE001 - the lattice alone is still a fingerprint
        return grid
    if surface.ndim != 2 or surface.shape[0] == 0:
        return grid
    return np.concatenate([grid, surface.reshape(-1, 3)], axis=0)


def _with_each_feature_s_own_surface(part: CompiledPart, grid: Any) -> Any:
    """The lattice and the surface, plus points on every named face.

    The surface is sampled evenly over the whole part, so on a big one a
    small feature gets none: a 4 mm hole in a 1000 by 600 mm plate has a
    wall of 38 square millimetres among three million, no sample landed on
    it, and its diameter -- nudged half a millimetre, the hole plainly
    bigger -- was failed as a dimension the part does not have. A critical
    gate, on a correct part: the analyst called in to fix nothing.

    Every feature names its own faces, wherever and however small; points on
    each are where a change to that feature shows first. Nothing is made
    easier to pass: a dimension that moves nothing leaves the distance at
    every one of these points where it was.
    """
    extra = []
    for entity in getattr(part, "geometry_map", ()) or ():
        try:
            if not getattr(entity, "is_checkable", False):
                continue
            points = np.asarray(entity.sample_points(48), dtype=float)
        except Exception:  # noqa: BLE001 - a face it cannot sample adds none
            continue
        if points.ndim == 2 and points.shape[1] == 3 and points.shape[0]:
            extra.append(points[np.all(np.isfinite(points), axis=1)])
    if not extra:
        return grid
    return np.concatenate([grid] + extra, axis=0)


def _fingerprint(solid: Any, grid: Any) -> Any:
    """The signed distance field sampled on the grid.

    A complete shape comparison in one array, and the reason this module can
    make a *negative* claim safely. Volume, extents and centroid are all
    integrals: each throws away almost everything about where the material
    is. Two bolt holes moved symmetrically apart -- the construction the
    authoring guide itself teaches, `+spacing / 2` and `-spacing / 2` --
    change the volume not at all, the extents not at all and the centroid
    not at all, and a gate built on those three would have called
    `mounting_hole_spacing` a dimension the part does not have.

    The distance field has no such blind spot. Move anything and the
    distance to it changes, at many samples at once, and no symmetry cancels
    it. Two hundred microseconds for the whole part.
    """
    try:
        return np.asarray(solid(grid), dtype=float)
    except Exception:  # noqa: BLE001 - an unsamplable solid simply has none
        return None


def _shape(part: CompiledPart, depth: int) -> tuple[list[float], float, list[float], float]:
    """Extents and volume of a built part, with the width of each enclosure.

    The widths come back with the values because they are what "it moved" has
    to be measured against: a change smaller than the measurement's own
    uncertainty is not a change anybody observed.
    """
    properties = measure_mass_properties(part.solid, max_depth=depth)
    extents = list(properties.bounding_box_size())
    return (
        [_centre(e) for e in extents],
        _centre(properties.volume),
        [_width(e) for e in extents],
        _width(properties.volume),
    )


def _nudged(value: Quantity, parameter: Any) -> tuple[Quantity, str] | None:
    """A changed value that stays inside whatever bounds were declared.

    Upwards by preference. A parameter sitting at its own maximum is nudged
    down instead, because a bound is a contract the compiler enforces and a
    probe that violates it measures nothing but the refusal.
    """
    try:
        centre = _centre(value)
        unit = value.unit
    except Exception:  # noqa: BLE001 - an unusable value is simply not probed
        return None
    step = max(abs(centre) * _NUDGE_FRACTION, _NUDGE_FLOOR_MM)
    if step <= 0.0:
        return None

    bounds = getattr(parameter, "bounds", None)

    def allowed(candidate: float) -> bool:
        if bounds is None:
            return True
        for attribute, comparison in (("min", False), ("max", True)):
            limit = getattr(bounds, attribute, None)
            if limit is None:
                continue
            try:
                edge = _centre(limit.to(unit))
            except Exception:  # noqa: BLE001 - an unreadable bound binds nothing
                continue
            if comparison and candidate > edge:
                return False
            if not comparison and candidate < edge:
                return False
        return True

    for candidate, word in ((centre + step, "+"), (centre - step, "-")):
        if allowed(candidate):
            return Q(candidate, unit.symbol), f"{word}{step:g} {unit.symbol}"
    return None


#: The fields of a cutter that say how far it reaches along its cut.
_REACH_FIELDS = ("distance", "depth", "height", "length")


def _reaches_only(component: Component) -> frozenset[str]:
    """Parameters read by nothing but how far a cutter reaches.

    "Cut the opening through the rear wall": an extrude 200 mm long from the
    middle of a calf shell, through a wall 60 mm away. Nudged to 220 it cuts
    the same opening, and the shell was failed for a dimension "the part
    does not have" -- which the analyst could not fix, because nothing was
    wrong. A cutter's reach is a length that only has to be long enough.
    Only a parameter read by a cutter's `distance`, `depth`, `height` or
    `length`, and by nothing else at all: a cutter's width, or a reach also
    used to place something, is a dimension like any other.
    """
    from forge_expr import free_names
    from forge_kernel.compiler import _cutting_tools

    tools = _cutting_tools(component)
    if not tools:
        return frozenset()

    def names_in(value: Any) -> set[str]:
        found: set[str] = set()
        stack = [value.as_json() if hasattr(value, "as_json") else value]
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                try:
                    found |= set(free_names(item))
                except Exception:  # noqa: BLE001 - not an expression
                    pass
            elif isinstance(item, Mapping):
                stack.extend(item.values())
            elif isinstance(item, (list, tuple)):
                stack.extend(item)
        return found

    reaching: set[str] = set()
    elsewhere: set[str] = set()
    for feature in component.features:
        for field, value in (feature.parameters or {}).items():
            used = names_in(value)
            if feature.identifier in tools and field in _REACH_FIELDS:
                reaching |= used
            else:
                elsewhere |= used
    graph = component.parameters
    for identifier in graph.identifiers():
        parameter = graph[identifier]
        expression = getattr(parameter, "expression", None)
        if expression:
            elsewhere |= names_in(str(getattr(expression, "source",
                                              expression)))
    for interface in getattr(component, "interfaces", ()) or ():
        elsewhere |= names_in(getattr(interface, "geometry", ""))
    return frozenset(reaching - elsewhere)


def measure_the_response(
    component: Component,
    *,
    compiler: Compiler | None = None,
    depth: int = PROBE_DEPTH,
    baseline: CompiledPart | None = None,
) -> tuple[ParameterResponse, ...]:
    """Probe every free dimension and report what each one moves.

    Derived parameters are not probed: their value is a consequence of the
    free ones, so overriding them would measure a design the document does
    not describe. Their effect shows up through whatever they are computed
    from, which is the honest place for it.

    Anything that cannot be probed -- a count, an angle, a value the compiler
    refuses -- comes back marked `skipped` rather than silently counted as
    inert. A probe that did not run is not evidence that nothing happened.
    """
    compiler = compiler or Compiler()
    graph = component.parameters
    try:
        resolution = graph.resolve()
        values = dict(resolution.values)
    except Exception:  # noqa: BLE001 - the compile below reports this properly
        return ()

    built = baseline if baseline is not None else compiler.compile_component(
        component, validate_geometry=False)
    base_extents, base_volume, _, _ = _shape(built, depth)
    grid = _with_each_feature_s_own_surface(
        built, _with_the_surface(built.solid, _sampling_grid(built.solid)))
    base_print = _fingerprint(built.solid, grid)
    scale = max(float(np.max(np.abs(base_print))) if base_print is not None
                else 1.0, 1e-6)

    millimetre = parse_unit("mm")
    # `free_parameters()` yields the parameters themselves, not their names.
    free = {
        str(getattr(parameter, "identifier", ""))
        for parameter in getattr(graph, "free_parameters", lambda: ())()
    } or set(graph.identifiers())

    try:
        reaches = _reaches_only(component)
    except Exception:  # noqa: BLE001 - without it every dimension is judged
        reaches = frozenset()

    responses: list[ParameterResponse] = []
    for identifier in sorted(graph.identifiers()):
        parameter = graph[identifier]
        if identifier not in free or getattr(parameter, "is_derived", False):
            responses.append(ParameterResponse(
                identifier, (), (0.0, 0.0, 0.0), 0.0, "",
                skipped="derived from other parameters"))
            continue
        value = values.get(identifier)
        if value is None or value.dimension != millimetre.dimension:
            responses.append(ParameterResponse(
                identifier, (), (0.0, 0.0, 0.0), 0.0, "",
                skipped="not a length"))
            continue
        step = _nudged(value, parameter)
        if step is None:
            responses.append(ParameterResponse(
                identifier, (), (0.0, 0.0, 0.0), 0.0, "",
                skipped="no value inside its bounds to move to"))
            continue
        replacement, described = step
        try:
            probe = compiler.compile_component(
                component, overrides={identifier: replacement},
                validate_geometry=False)
            extents, volume, _, _ = _shape(probe, depth)
            probe_print = _fingerprint(probe.solid, grid)
        except Exception as error:  # noqa: BLE001 - a probe never fails a run
            responses.append(ParameterResponse(
                identifier, (), (0.0, 0.0, 0.0), 0.0, described,
                skipped=f"the design does not compile at {described}: "
                        f"{type(error).__name__}"))
            continue

        # What counts as a response, and why these numbers.
        #
        # The first draft compared each change against the *width of the
        # octree enclosure* at this depth, and got it badly wrong: the
        # worked example's `boss_diameter` moves 3,962 mm^3 of material and
        # was reported as driving nothing, because a coarse enclosure of a
        # 60 x 40 x 35 part is thousands of cubic millimetres wide.
        #
        # The enclosure width is the wrong statistic. It measures how well a
        # single volume is known in absolute terms; what is being asked here
        # is whether a *difference between two measurements of nearly the
        # same solid at the same depth* is real -- and there the cell
        # structure is almost identical and the systematic error cancels.
        # So the floors are relative to the thing being changed, and set far
        # below any genuine geometric effect and far above any jitter:
        # a real dimension moves its extent nearly one-for-one with the
        # nudge, and moves volume by whole percent.
        nudge_size = abs(_centre(replacement) - _centre(value))
        extent_floor = max(nudge_size * _RESPONSE_FRACTION_OF_NUDGE, 1e-6)
        volume_floor = max(abs(base_volume) * _RESPONSE_FRACTION_OF_VOLUME, 1e-6)
        change = tuple(
            extents[i] - base_extents[i] for i in range(3)
        )
        volume_change = volume - base_volume
        moves: list[str] = []
        for index, letter in enumerate("xyz"):
            if abs(change[index]) > extent_floor:
                moves.append(letter)
        if abs(volume_change) > volume_floor:
            moves.append("volume")

        # Whether the SHAPE changed at all, which is a different and much
        # harder question than whether any integral of it did. Decided on
        # the distance field, so a change that volume, extents and centroid
        # are all blind to -- two holes moved symmetrically apart -- is
        # still a change, and `drives_nothing` can be asserted safely.
        shape_moved = True
        if base_print is not None and probe_print is not None:
            shape_moved = bool(
                np.max(np.abs(probe_print - base_print)) > scale * 1e-6)
        if shape_moved and not moves:
            moves = ["shape"]

        responses.append(ParameterResponse(
            parameter=identifier,
            moves=tuple(moves),
            extent_change=(change[0], change[1], change[2]),
            volume_change=volume_change,
            nudge=described,
            reach=not moves and identifier in reaches,
        ))
    return tuple(responses)


def the_axis_each_figure_drives(
    responses: Sequence[ParameterResponse],
    values: Mapping[str, Quantity],
) -> dict[str, str]:
    """Figure -> the single axis a parameter carrying it is proved to drive.

    Keyed by the figure rather than the parameter name, because the thing
    asking is a requirement that carries a threshold and not a name: an
    extent claim never says which parameter it came from. A figure carried by
    two parameters that drive different axes is left out entirely -- an
    ambiguous answer is worse than none.
    """
    from forge_units import parse_unit as _unit

    millimetre = _unit("mm")
    found: dict[str, set[str]] = {}
    for response in responses:
        axis = response.axis
        if not axis:
            continue
        value = values.get(response.parameter)
        if value is None:
            continue
        try:
            key = f"{_centre(value.to(millimetre)):.6g}"
        except Exception:  # noqa: BLE001 - a non-length carries no figure
            continue
        found.setdefault(key, set()).add(axis)
    return {key: next(iter(axes)) for key, axes in found.items() if len(axes) == 1}


__all__ = [
    "PROBE_DEPTH",
    "ParameterResponse",
    "measure_the_response",
    "the_axis_each_figure_drives",
]
