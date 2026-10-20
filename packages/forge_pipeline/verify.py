"""The deterministic verification pipeline.

This module is the spine of the whole system: it takes a ForgeIR document and
produces an evidence graph, with no language model anywhere in the path. That
property is the point. The entire pipeline -- compile, measure, cross-check,
gate, report -- runs from a checked-in document with no model provider
configured, which means the tests are free, fast, reproducible, and incapable of
being influenced by a model's confidence.

What it does, in order:

1. **Compile** the component through the kernel, with incremental caching.
2. **Validate semantic geometry** -- every interface must still name geometry
   that exists on the finished solid.
3. **Measure** mass properties as rigorous enclosures.
4. **Cross-check** the octree measurement against an independently extracted
   surface mesh. Two different algorithms agreeing is evidence; disagreeing is a
   bug, and this is where it surfaces.
5. **Check manufacturability** -- minimum wall thickness by inward ray marching.
6. **Run first-principles analysis** on the declared load case.
7. **Evaluate every gate**, deriving statuses from three-valued comparison.
8. **Decide release status**, which unapproved high-risk assumptions can block
   regardless of how many gates passed.

Step 8 is worth dwelling on. A design can pass every geometric and structural
gate and still not be a release candidate, because the load it was checked
against was an assumption nobody accepted. Forge reports that as ``BLOCKED``
with the assumption named, rather than as a pass with a footnote.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

import numpy as np

from forge_analysis import (
    MaterialError,
    bearing_stress,
    bending_stress,
    cantilever_root_moment,
    direct_shear_stress,
    lookup,
    rectangular_second_moment,
    safety_factor,
)
from forge_evidence import (
    Evidence,
    EvidenceGraph,
    Gate,
    GateResult,
    Method,
    Status,
    ToolIdentity,
    release_status,
)
from forge_geom import (
    EmptyResultError,
    GeometryError,
    extract_manifold_surface,
    extract_surface,
    measure_mass_properties,
    refine_extents,
    minimum_wall_thickness,
    surface_samples,
)
from forge_ir import Component, Document
from .measure import Measurement, declared_load, resolve_measurement
from .response import (
    ParameterResponse,
    measure_the_response,
    the_axis_each_figure_drives,
)
from forge_kernel import CompiledPart, Compiler, EntityStatus, SelectionError
from forge_units import Interval, Q, Quantity, parse_unit

TOOL_KERNEL = ToolIdentity("forge_kernel.implicit", "0.1.0")
TOOL_MEASURE = ToolIdentity("forge_geom.measure.octree", "0.1.0")
TOOL_MESH = ToolIdentity("forge_geom.mesh.surface_nets", "0.1.0")
TOOL_ANALYSIS = ToolIdentity("forge_analysis.checks", "0.1.0")

#: Below this enclosed volume a component is treated as having no material at
#: all. Not zero: the octree returns a bounded enclosure, so a genuinely empty
#: solid measures as a small interval around zero rather than exactly it. One
#: cubic micrometre is far under any real feature and far over that residue.
_EMPTY_VOLUME_MM3 = 1e-9


@dataclass(frozen=True, slots=True)
class LoadCase:
    """A declared load, kept separate from the geometry that carries it."""

    identifier: str
    force: Quantity
    lever_arm: Quantity
    description: str = ""
    #: The assumption this load came from, if it was not supplied by the user.
    assumption_id: str = ""


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Everything a verification run produced."""

    component_id: str
    part: CompiledPart
    evidence: EvidenceGraph
    gate_results: tuple[GateResult, ...]
    overall_status: Status
    release_reasons: tuple[str, ...]
    measurements: Mapping[str, Any]
    duration_seconds: float
    #: The finished surface, as meshed for the checks: what the part is
    #: drawn from (`forge_pipeline.render`) and written out as. None when
    #: no surface could be extracted.
    mesh: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component_id,
            "overall_status": self.overall_status.value,
            "release_reasons": list(self.release_reasons),
            "duration_s": round(self.duration_seconds, 4),
            "compile": {
                "part_hash": self.part.part_hash,
                "backend": self.part.backend,
                "features_built": self.part.features_built,
                "features_reused": self.part.features_reused,
            },
            "measurements": dict(self.measurements),
            "warnings": list(self.warnings),
            "evidence": self.evidence.as_dict(),
        }

    def render(self) -> str:
        lines = [
            f"Component      : {self.component_id}",
            f"Part hash      : {self.part.part_hash}",
            f"Backend        : {self.part.backend}",
            f"Overall status : {self.overall_status.value}",
            "",
            self.evidence.render(),
        ]
        facts = self.measurements.get("part")
        if facts:
            # Beside the verdict, not buried in the JSON. A person reading
            # "PASS" should be able to see the object's real shape in the same
            # glance -- "envelope 38 x 20 x 38, 0 open holes of 3" says more
            # than seven passing dimensional requirements ever did.
            lines.extend(["", render_the_part(facts)])
        if self.release_reasons:
            lines.extend(["", "Not a release candidate because:"])
            lines.extend(f"  - {reason}" for reason in self.release_reasons)
        if self.warnings:
            # Beside the verdict, never under it. A non-critical gate is
            # excluded from the decision on purpose -- a vertical web is a
            # real part -- but excluding it from the decision is not a reason
            # to let a reader miss it.
            #
            # Observed the day the orientation gate shipped: a spacer whose
            # 30 mm square plate had been built 30 x 12, because the base
            # box carried the POST's diameter in its second slot. Every
            # number in the document was right, so every dimensional
            # requirement passed, and the only thing in the whole run that
            # noticed was one non-critical FAIL -- under a heading that said
            # `completed` and `Overall status: PASS`.
            lines.extend(["", "Worth looking at (does not block release):"])
            lines.extend(f"  - {warning}" for warning in self.warnings)
        return "\n".join(lines)

    @property
    def warnings(self) -> tuple[str, ...]:
        """Non-critical gates that failed: real findings, not release blockers."""
        return tuple(
            f"{result.gate.identifier}: {result.gate.claim}"
            for result in self.gate_results
            if not result.gate.critical
            and result.evidence.status is Status.FAIL
        )


def _nothing_to_measure(
    document: Document, component: Component, part: CompiledPart,
    evidence: EvidenceGraph, gate_results: list[GateResult],
    measurements: dict[str, Any], started: float, error: GeometryError,
) -> VerificationReport:
    """The report on a design that encloses no material: one failed gate."""
    gate = Gate(
        identifier="GEOM_NON_EMPTY",
        claim="the component encloses some material",
        comparison="at_least",
        threshold=Q(_EMPTY_VOLUME_MM3, "mm^3"),
        critical=True,
        rationale="Every later check measures a solid. A design whose "
        "features cancel each other out has failed in a way no downstream "
        "number can describe.",
    )
    node = gate.evaluate(
        Q(0, "mm^3"),
        method=Method.EXACT_GEOMETRY,
        tool=TOOL_MEASURE,
        input_hashes=(part.part_hash,),
        limitations=("the octree found no cell holding material anywhere "
                     "inside the design's own envelope",),
        detail={"geometry_error": error.message, **dict(error.detail),
                "hint": "the finished part has no material at all: look "
                "for a subtract whose second input is as large as its "
                "first -- or is the first -- an intersect of solids that do "
                "not overlap, or a size driven to zero."},
    )
    evidence.add(node)
    gate_results.append(GateResult(gate, node))
    measurements["volume"] = "0 mm^3"
    blocking = [a.identifier for a in document.unapproved_blocking_assumptions()]
    overall, reasons = release_status(gate_results, blocking_assumptions=blocking)
    return VerificationReport(
        component_id=component.identifier,
        part=part,
        evidence=evidence,
        gate_results=tuple(gate_results),
        overall_status=overall,
        release_reasons=tuple(reasons),
        measurements=measurements,
        duration_seconds=time.perf_counter() - started,
    )


#: How many edges shared by more than two faces are each looked at again,
#: finer, to tell a solid meeting itself from the grid's guess. Past this
#: many the extraction is not to be second-guessed edge by edge.
_EDGES_LOOKED_AT_CLOSELY = 64


def verify_component(
    document: Document,
    component: Component,
    *,
    compiler: Compiler | None = None,
    overrides: Mapping[str, Quantity] | None = None,
    load_case: LoadCase | None = None,
    measurement_depth: int = 9,
    mesh_resolution: int = 110,
) -> VerificationReport:
    """Run the full deterministic verification and return an evidence graph."""
    started = time.perf_counter()
    compiler = compiler or Compiler()
    evidence = EvidenceGraph()
    gate_results: list[GateResult] = []
    measurements: dict[str, Any] = {}

    part = compiler.compile_component(component, overrides=overrides)
    input_hash = part.part_hash

    # -- 1. semantic geometry -------------------------------------------
    gate_results.extend(
        _check_interfaces(component, part, evidence, input_hash)
    )

    # -- 2. mass properties ----------------------------------------------
    try:
        properties = measure_mass_properties(
            part.solid, max_depth=measurement_depth)
    except EmptyResultError as error:
        # The octree proved there is nothing there at all. That is the
        # design fact `GEOM_NON_EMPTY` exists to report, and it reached
        # the user as an internal error instead: a 30 by 30 by 10 slab
        # subtracted from itself, and the run ended in a traceback with no
        # repair attempted.
        return _nothing_to_measure(
            document, component, part, evidence, gate_results, measurements,
            started, error)
    try:
        # The octree's box is as loose as its cells: a 4 mm plate measured
        # 3.675 +/- 0.525 mm thick, and a 3.5 mm one would have passed an
        # "equals 4 mm" claim. Each face is closed in on by itself.
        properties = refine_extents(part.solid, properties)
    except Exception:  # noqa: BLE001 - the octree's own box still encloses
        pass
    measurements["volume"] = str(properties.volume)
    measurements["relative_uncertainty"] = properties.relative_uncertainty
    measurements["centre_of_mass"] = [str(q) for q in properties.centre_of_mass]
    measurements["bounding_box_size"] = [
        str(q) for q in properties.bounding_box_size()
    ]

    measurement_limits = (
        f"rigorous octree enclosure to depth {properties.depth_reached}; "
        f"residual uncertainty {properties.relative_uncertainty:.2%} of volume",
        "implicit backend: this is a bounded enclosure, not a closed-form "
        "analytic volume",
    )

    # -- 2a. is there a part at all? ---------------------------------------
    #
    # A design can remove every scrap of its own material -- a 20 mm hole
    # through a 20 mm cylinder -- and that is a design fact, not an internal
    # error. Observed live: the mesher raised "surface extraction found no
    # boundary cells", which escaped verification, escaped the orchestrator,
    # and ended the run in a traceback. Reported as a gate instead, it is
    # evidence the repair loop can act on, and everything measured so far
    # survives in the report.
    non_empty_gate = Gate(
        identifier="GEOM_NON_EMPTY",
        claim="the component encloses some material",
        comparison="at_least",
        threshold=Q(_EMPTY_VOLUME_MM3, "mm^3"),
        critical=True,
        rationale="Every later check measures a solid. A design whose features "
        "cancel each other out has failed in a way no downstream number can "
        "describe, so it is named here rather than crashing the mesher.",
    )
    non_empty_evidence = non_empty_gate.evaluate(
        properties.volume,
        method=Method.EXACT_GEOMETRY,
        tool=TOOL_MEASURE,
        input_hashes=(input_hash,),
        limitations=measurement_limits,
    )
    evidence.add(non_empty_evidence)
    gate_results.append(GateResult(non_empty_gate, non_empty_evidence))

    # -- 3. cross-backend check -------------------------------------------
    #
    # The octree cannot always *prove* emptiness: a genuinely empty solid
    # measured to a shallow depth returns an enclosure like [0, 10315] mm^3,
    # which is honestly inconclusive rather than zero. The mesher is decisive
    # where the enclosure is not -- no boundary cell anywhere means no surface
    # anywhere -- so its failure is recorded as evidence rather than raised.
    try:
        mesh = extract_manifold_surface(part.solid, resolution=mesh_resolution)
    except GeometryError as error:
        surface_gate = Gate(
            identifier="GEOM_SURFACE_EXISTS",
            claim="a surface can be extracted from the component",
            comparison="at_least",
            threshold=Q(1),
            critical=True,
            rationale="Every measurement past this point describes a surface. "
            "When none can be found the usual cause is a design that removes "
            "all of its own material -- a hole as wide as the body it cuts, a "
            "subtract whose operands are the same size.",
        )
        surface_evidence = surface_gate.evaluate(
            Q(0),
            method=Method.EXACT_GEOMETRY,
            tool=TOOL_MESH,
            input_hashes=(input_hash,),
            limitations=(
                f"searched at resolution {mesh_resolution}; a feature smaller "
                "than one grid cell would also be missed",
            ),
            detail={"geometry_error": error.message, **dict(error.detail)},
        )
        evidence.add(surface_evidence)
        gate_results.append(GateResult(surface_gate, surface_evidence))
        blocking = [
            assumption.identifier
            for assumption in document.unapproved_blocking_assumptions()
        ]
        overall, reasons = release_status(
            gate_results, blocking_assumptions=blocking
        )
        return VerificationReport(
            component_id=component.identifier,
            part=part,
            evidence=evidence,
            gate_results=tuple(gate_results),
            overall_status=overall,
            release_reasons=tuple(reasons),
            measurements=measurements,
            duration_seconds=time.perf_counter() - started,
        )
    mesh_volume = Q(abs(mesh.signed_volume()), "mm^3")
    watertight, mesh_stats = mesh.is_watertight()
    measurements["mesh_volume"] = str(mesh_volume)
    measurements["surface_area"] = str(Q(mesh.surface_area(), "mm^2"))
    measurements["watertight"] = watertight

    cross_gate = Gate(
        identifier="GEOM_CROSS_BACKEND",
        claim="independently extracted mesh volume agrees with the octree "
        "enclosure",
        comparison="within",
        threshold=Q(properties.volume.magnitude.lo * 0.97, "mm^3"),
        upper=Q(properties.volume.magnitude.hi * 1.03, "mm^3"),
        critical=False,
        rationale="Two independent algorithms measuring the same solid should "
        "agree. A disagreement is a defect in one of them, and finding it is "
        "worth more than averaging it away.",
    )
    cross_evidence = cross_gate.evaluate(
        mesh_volume,
        method=Method.CROSS_BACKEND,
        tool=TOOL_MESH,
        input_hashes=(input_hash,),
        limitations=(
            "the mesh volume is a discretised estimate with its own error, "
            "roughly 0.1% at this resolution; agreement is corroboration, not "
            "proof of either result",
        ),
        detail={"mesh": mesh_stats, "faces": mesh.face_count},
    )
    evidence.add(cross_evidence)
    gate_results.append(GateResult(cross_gate, cross_evidence))

    watertight_limits: tuple[str, ...] = ()
    watertight_gate = Gate(
        identifier="GEOM_WATERTIGHT",
        claim="extracted surface is a closed, manifold solid",
        comparison="at_most",
        threshold=Q(0),
    )
    open_edges = int(mesh_stats["boundary_edges"])
    shared_edges = int(mesh_stats["non_manifold_edges"])
    # Two sheets drawn on each other, each closed: every edge shared by two
    # faces, and still no solid's surface (see TriangleMesh.is_watertight).
    drawn_twice = int(mesh_stats.get("edges_drawn_twice", 0))
    looked_closely: tuple[int, int] | None = None
    if (drawn_twice == 0 and open_edges == 0
            and 0 < shared_edges <= _EDGES_LOOKED_AT_CLOSELY):
        # Each shared edge looked at again, eight times finer: is the solid
        # really meeting itself there, or is it the grid's guess on a
        # surface met at a slant? A coil spring right in every figure was
        # held for 13 of these on every grid; two blocks touching along a
        # line are still found, every edge of it.
        from forge_geom.mesh import meets_itself_at

        try:
            shared = mesh.non_manifold_edges()
            where = mesh.vertices[shared].mean(axis=1)
            lengths = np.linalg.norm(
                mesh.vertices[mesh.faces[:, 1]]
                - mesh.vertices[mesh.faces[:, 0]], axis=1)
            cell = float(np.median(lengths))
            # Eight times finer, and what meets itself there again at
            # sixteen: two pieces a fine step apart at eight can be a gap
            # at sixteen, and a solid that really touches itself touches at
            # every scale.
            meeting = meets_itself_at(part.solid, where, cell)
            if meeting.any():
                meeting[meeting] = meets_itself_at(
                    part.solid, where[meeting], cell, fineness=16.0)
            real = int(np.count_nonzero(meeting))
            looked_closely = (real, len(where))
        except Exception:  # noqa: BLE001 - not looked at: as before
            looked_closely = None
    if drawn_twice:
        faces = Q(open_edges + shared_edges + drawn_twice)
        watertight_limits = (
            f"{drawn_twice} edge(s) of the surface lie exactly where an edge "
            "of another sheet of it lies: two sheets drawn on each other, a "
            "skin of no thickness -- a slicer shows it as a face across the "
            "part, and the part is not the solid the design describes",)
    elif looked_closely is not None:
        real, looked = looked_closely
        faces = Q(real)
        watertight_limits = (
            f"{looked} edge(s) are shared by more than two faces on every "
            "grid tried; each was sampled again eight and sixteen times "
            f"finer, and the solid meets itself at {real} of them"
            + ("" if real else
               " -- they are the grid's guess on a surface met at a slant, "
               "not the part's"),)
    elif open_edges == 0 and shared_edges > 0:
        # Closed, but with edges shared by four faces on every grid the
        # mesher tried. Surface nets draw that where a cylinder met at a
        # slant -- its axis along (1, 2, 2) -- has its rim cross all four
        # edges of a cell face, on a solid that is perfectly manifold; and
        # a solid that really touches itself along an edge draws the same.
        # The count cannot tell the two apart, so it is reported as the
        # interval it is: from none, if the grid is the cause, to all of
        # them. The gate comes out INCONCLUSIVE, which still holds the
        # release, rather than FAIL, which sent the analyst to repair a
        # valid primitive.
        faces = Q(Interval(0.0, float(shared_edges)))
        watertight_limits = (
            f"{shared_edges} edge(s) are shared by more than two faces on "
            "every grid tried and none is open; surface nets draw a valid "
            "solid met at a slant this way, so the count is reported as a "
            "range and cannot decide the gate",)
    else:
        faces = Q(open_edges + shared_edges)
    watertight_evidence = watertight_gate.evaluate(
        faces,
        method=Method.EXACT_GEOMETRY,
        tool=TOOL_MESH,
        input_hashes=(input_hash,),
        limitations=watertight_limits,
        detail=mesh_stats,
    )
    evidence.add(watertight_evidence)
    gate_results.append(GateResult(watertight_gate, watertight_evidence))

    # -- 3-bis. is it one piece? --------------------------------------------
    #
    # A pulley hub came back with its hub floating 4.5 mm above its flange --
    # each cylinder's `origin` written as its centre, where a cylinder's
    # origin is its base -- and every gate passed: both bodies were exactly
    # the size asked, every hole was open, and a union of two solids that do
    # not touch is still a valid union. A component is one part, and a part
    # in two pieces is not the part anyone asked for.
    found, air = mesh.pieces_and_hollows()
    pieces = [v for v, _ in found]
    whole = sum(pieces)
    material = [v for v in pieces if whole > 0 and v >= 0.01 * whole]
    # A small piece is a grid fragment of a thin feature, or a body that
    # really stands apart -- two mounting bosses drawn in the air behind a
    # calf shell were each 0.03% of it. Each is looked at again, closely.
    from forge_geom.mesh import floats_free
    edges = mesh.vertices[mesh.faces[:, 1]] - mesh.vertices[mesh.faces[:, 0]] \
        if mesh.face_count else np.zeros((1, 3))
    cell = max(float(np.median(np.linalg.norm(edges, axis=1))), 1e-6)
    adrift = [v for v, vertices in found
              if whole > 0 and v < 0.01 * whole and len(material) >= 1
              and floats_free(part.solid, vertices, cell)]
    measurements["pieces_mm3"] = [round(v, 3) for v in pieces]
    # Air the part closes in on every side: measured once here, on this
    # surface, for a `sealed_voids` claim to read.
    from .measure import sealed_voids_of
    sealed = sealed_voids_of(mesh, air) if air else []
    measurements["sealed_voids_mm3"] = [volume for volume, _ in sealed]
    one_piece_gate = Gate(
        identifier="GEOM_ONE_PIECE",
        claim="the part is one piece: nothing floats apart from the rest",
        comparison="at_most",
        threshold=Q(0),
        rationale="A union of solids that do not touch is a valid union and "
        "a different part. Each separate piece is counted on the extracted "
        "surface, and every piece past the first is a body the rest of the "
        "part does not hold.",
    )
    one_piece_evidence = one_piece_gate.evaluate(
        Q(max(len(material) - 1, 0) + len(adrift)),
        method=Method.EXACT_GEOMETRY,
        tool=TOOL_MESH,
        input_hashes=(input_hash,),
        limitations=(
            f"counted on a surface extracted at resolution {mesh_resolution}; "
            "a piece under 1% of the part's volume counts only if, sampled "
            "again four and eight times finer, it is still apart from the "
            "rest -- so a fragment the extraction grid split off a thin "
            "feature cannot fail the part, and a small body in the air does",
        ),
        detail={"piece_volumes_mm3": [round(v, 3) for v in pieces],
                **({"small_pieces_apart_mm3": [round(v, 3) for v in adrift],
                    "where_mm": [
                        [round(float(c), 1) for c in vertices.mean(axis=0)]
                        for v, vertices in found if v in adrift],
                    "hint": (
                        f"{len(adrift)} small bod"
                        + ("y stands" if len(adrift) == 1 else "ies stand")
                        + " apart from the part, nothing joining "
                        + ("it" if len(adrift) == 1 else "them")
                        + " to it: "
                        + "; ".join(
                            f"{v:.0f} mm^3 about ("
                            + ", ".join(f"{float(c):.1f}"
                                        for c in vertices.mean(axis=0))
                            + ")" for v, vertices in found if v in adrift)
                        + ". A boss, rib or tab placed where the surface it "
                        "should stand on is not -- a lofted or curved face "
                        "moves with height -- floats. Start it inside the "
                        "material it belongs to.")}
                   if adrift else {})},
    )
    evidence.add(one_piece_evidence)
    gate_results.append(GateResult(one_piece_gate, one_piece_evidence))

    # -- 3a. are the through holes actually through? -----------------------
    gate_results.extend(
        _check_through_holes(component, part, evidence, input_hash)
    )

    # -- 3a-bis. is each hole a hole, or a notch in an edge? ---------------
    gate_results.extend(
        _check_holes_are_surrounded(component, part, evidence, input_hash)
    )

    # -- 3b. did every feature actually change the part? -------------------
    gate_results.extend(
        _check_features_contribute(component, part, evidence, input_hash)
    )

    # -- 3c. what does each declared dimension actually do? ----------------
    #
    # The one fact nothing in this pipeline has ever established. Every
    # dimensional check until now compares a number in the document against
    # the same number in the document: true of a plate lying flat, equally
    # true of that plate stood on its edge. Nudging each parameter and
    # watching what moves answers "in which direction", by measurement, at
    # a few milliseconds each. See `forge_pipeline.response`.
    responses = measure_the_response(component, compiler=compiler, baseline=part)
    measurements["dimension_response"] = [r.as_dict() for r in responses]

    gate_results.extend(
        _check_dimensions_drive_the_part(responses, evidence, input_hash)
    )
    gate_results.extend(
        _check_the_build_orientation(
            responses,
            [_centre_of(q) for q in properties.bounding_box_size()],
            evidence,
            input_hash,
        )
    )

    # -- 3d. what did we actually build? -----------------------------------
    measurements["part"] = describe_the_part(component, part, properties)
    measurements["part"]["dimensions"] = [
        r.describe() for r in responses if not r.skipped
    ]

    # -- 4. sampled manufacturability measurement --------------------------
    wall_thickness: Quantity | None = None
    try:
        samples = surface_samples(part.solid, resolution=56)
        wall_thickness, _ = minimum_wall_thickness(part.solid, samples)
        measurements["minimum_wall"] = str(wall_thickness)
    except Exception:  # noqa: BLE001 - a part with no measurable chord
        wall_thickness = None

    # -- 5. requirement gates, via each requirement's measurement binding ---
    load = (
        load_case.force if load_case is not None else declared_load(component, document)
    )
    gate_results.extend(
        _check_document_requirements(
            document,
            component,
            part,
            properties,
            evidence,
            input_hash,
            measurements,
            surface_area=Q(mesh.surface_area(), "mm^2"),
            wall_thickness=wall_thickness,
            load=load,
            axis_of=_figures_with_a_proved_axis(component, responses),
            mesh_extents=_the_extents_of(mesh, part, mesh_resolution),
            hollows=sealed,
        )
    )

    blocking = [
        assumption.identifier
        for assumption in document.unapproved_blocking_assumptions()
    ]
    overall, reasons = release_status(gate_results, blocking_assumptions=blocking)

    return VerificationReport(
        component_id=component.identifier,
        part=part,
        evidence=evidence,
        gate_results=tuple(gate_results),
        overall_status=overall,
        release_reasons=tuple(reasons),
        measurements=measurements,
        duration_seconds=time.perf_counter() - started,
        mesh=mesh,
    )


# ----------------------------------------------------------------------
# Individual check groups
# ----------------------------------------------------------------------
def _check_interfaces(
    component: Component,
    part: CompiledPart,
    evidence: EvidenceGraph,
    input_hash: str,
) -> list[GateResult]:
    """Every interface must still name geometry that exists.

    This is where a topology change is caught. A parameter change cannot break
    an interface -- the lineage token is unchanged by construction -- but a
    feature edit that buries a named face can, and must not pass silently.
    """
    results: list[GateResult] = []
    for interface in component.interfaces:
        gate = Gate(
            identifier=f"IFACE_{interface.identifier.upper()}",
            claim=f"interface '{interface.identifier}' resolves to live geometry "
            f"({interface.geometry})",
            comparison="at_least",
            threshold=Q(1),
            rationale="An interface that names geometry the current build no "
            "longer produces is a broken reference, not a warning.",
        )
        try:
            entity = part.geometry_map.resolve(interface.geometry)
        except SelectionError as exc:
            node = gate.evaluate(
                Q(0),
                method=Method.EXACT_GEOMETRY,
                tool=TOOL_KERNEL,
                input_hashes=(input_hash,),
                limitations=(exc.message,),
                detail=exc.as_dict(),
            )
        else:
            node = gate.evaluate(
                Q(1),
                method=Method.EXACT_GEOMETRY,
                tool=TOOL_KERNEL,
                input_hashes=(input_hash,),
                detail={
                    "token": entity.token,
                    "type": entity.entity_type,
                    "status": entity.status.value,
                    "note": entity.note,
                    "dimensions": dict(entity.dimensions),
                },
            )
        evidence.add(node)
        results.append(GateResult(gate, node))

    buried = part.buried_entities()
    if buried:
        gate = Gate(
            identifier="GEOM_BURIED_ENTITIES",
            claim="named geometry buried by later features is reported",
            comparison="at_least",
            threshold=Q(0),
            critical=False,
            rationale="Burial is legitimate -- an ear's underside is supposed to "
            "disappear into the base -- but it is recorded so a reviewer can "
            "see which names are no longer selectable.",
        )
        node = gate.evaluate(
            Q(len(buried)),
            method=Method.EXACT_GEOMETRY,
            tool=TOOL_KERNEL,
            input_hashes=(input_hash,),
            detail={
                "buried": [
                    {"name": e.name, "reason": e.note} for e in buried
                ]
            },
        )
        evidence.add(node)
        results.append(GateResult(gate, node))

        results.extend(
            _check_bores_survive(component, part, buried, evidence, input_hash)
        )
    return results


def _check_bores_survive(
    component: Component,
    part: CompiledPart,
    buried: Sequence[Any],
    evidence: EvidenceGraph,
    input_hash: str,
) -> list[GateResult]:
    """A hole whose bore is buried is a hole that is not in the part.

    Burial is usually legitimate: a post's base disappears into the plate it
    stands on, and that is the design working. A *bore* is different. The bore
    is the hole -- it is the surface the hole exists to create -- and if none
    of it survives on the boundary then the hole was filled back in by
    something built after it. There is no design in which that is what the
    author meant.

    ``GEOM_BURIED_ENTITIES`` knew this and could not act on it: it is a
    counter, compared `at_least 0`, so it can never fail. Observed live twice.
    On the second occasion it listed `shaft.bore` as 100% interior, reported
    PASS, and the run completed green on a part with no holes in it at all.
    """
    holes = {
        (feature.role or feature.identifier): feature
        for feature in component.features
        if feature.kind == "hole"
    }
    lost = [
        entity
        for entity in buried
        if entity.entity_type == "cylindrical_face"
        and entity.name.rpartition(".")[0] in holes
    ]
    if not lost:
        return []

    names = ", ".join(sorted(entity.name for entity in lost))
    # A hole that never cut anything has no bore on the part either, and was
    # told it "was filled back in by a later feature" -- on a design with no
    # feature after it. The analyst, reading that beside "it never cut
    # anything", judged the two reports contradictory and gave up.
    empty = sorted(
        entity.name for entity in lost
        if not the_bore_found_material(part, holes[entity.name.rpartition(".")[0]]))
    refilled = sorted(entity.name for entity in lost if entity.name not in empty)
    gate = Gate(
        identifier="GEOM_BORES_SURVIVE",
        claim="every hole's bore is present on the finished part",
        comparison="at_most",
        threshold=Q(0),
        critical=True,
        rationale="A bore is the hole. Burying a face is often the design "
        "working as intended, but a bore that is entirely interior means the "
        "hole was filled in by something built after it, and the part has no "
        "hole where the document says there is one.",
    )
    node = gate.evaluate(
        Q(len(lost)),
        method=Method.EXACT_GEOMETRY,
        tool=TOOL_KERNEL,
        input_hashes=(input_hash,),
        detail={
            "lost": [{"name": e.name, "reason": e.note} for e in lost],
            "hint": (
                (f"{', '.join(empty)}: no bore on the part because the hole "
                 "never cut any material -- it was placed where the part is "
                 "not (see GEOM_FEATURES_CONTRIBUTE for where its axis runs "
                 "and where the material is). Nothing filled it in; move it. "
                 if empty else "")
                + (f"{', '.join(refilled)} exists in the document and not on "
                   "the part: no part of the bore is on the boundary, so the "
                   "hole was filled back in by a later feature. The usual "
                   "cause is a boolean after the hole that adds a solid the "
                   "hole was never cut through, or a `union` of several cut "
                   "copies of one body. Cut every hole from the finished "
                   "body, each one taking the previous feature as its input, "
                   "and let the last hole be the part."
                   if refilled else "")
            ).strip(),
        },
    )
    evidence.add(node)
    return [GateResult(gate, node)]


#: Verification methods a requirement can demand that a geometry kernel cannot
#: carry out. Each needs a person, a laboratory, a solver Forge does not ship,
#: or a certifying body.
#:
#: The method a requirement names is a promise about *how* the claim will be
#: established, and it is part of the claim. Answering "verify by physical
#: test" with a number read off a mesh is not a weaker check -- it is a
#: different check, reported under the first one's name. Forge measures such a
#: requirement anyway and keeps the value in `detail`, because it is useful to
#: whoever performs the real procedure; it just never counts as having
#: performed it.
_METHODS_FORGE_CANNOT_PERFORM = frozenset(
    {
        "simulation",
        "visual_review",
        "user_confirmation",
        "physical_test",
        "external_certification",
    }
)

#: The evidence method each demanded verification maps to, so the untested
#: node is filed under the procedure that was asked for rather than under the
#: measurement that was not performed.
_DEMANDED_METHOD = {
    "simulation": Method.NUMERICAL_SIMULATION,
    "visual_review": Method.VISUAL_REVIEW,
    "user_confirmation": Method.USER_CONFIRMATION,
    "physical_test": Method.PHYSICAL_TEST,
    "external_certification": Method.EXTERNAL_CERTIFICATION,
}

#: A point this far inside the solid counts as material. The clipped sample
#: segment ends exactly on the bounding box, where the field is zero, so the
#: margin also keeps those endpoints from reading as solid.
_ON_SURFACE_MM = 1e-6

#: Samples along a hole's centre line, spread over the part's own extent. On a
#: 70 mm part that is a reading every 0.3 mm -- finer than any wall a printer
#: or a mill will produce, and one field evaluation per sample.
_AXIS_SAMPLES = 257


def _segment_inside_box(
    origin: np.ndarray, direction: np.ndarray, box: Any
) -> tuple[float, float] | None:
    """The range of ``t`` for which ``origin + t*direction`` lies in ``box``.

    The standard slab clip. Returns ``None`` when the line misses the box
    entirely, which for a hole axis means the hole passes nowhere near the
    part -- a different defect, and one the burial check already names.
    """
    lower = -float("inf")
    upper = float("inf")
    for axis in range(3):
        step = float(direction[axis])
        start = float(origin[axis])
        box_lo = float(box.lo[axis])
        box_hi = float(box.hi[axis])
        if abs(step) < 1e-12:
            if start < box_lo or start > box_hi:
                return None
            continue
        first = (box_lo - start) / step
        second = (box_hi - start) / step
        if first > second:
            first, second = second, first
        lower = max(lower, first)
        upper = min(upper, second)
    if not upper > lower:
        return None
    return lower, upper


def _solid_runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Index ranges of consecutive ``True`` values, inclusive at both ends."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(bool(value) for value in flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


def _refine_run(
    solid: Any,
    origin: np.ndarray,
    direction: np.ndarray,
    distances: np.ndarray,
    start: int,
    end: int,
) -> tuple[float, float]:
    """Where the material in one sampled run really begins and ends.

    The samples bracket each surface crossing; bisecting between the last empty
    reading and the first solid one finds it to well under a micrometre, which
    is the difference between "your plate is 4.95 mm thick" and "your plate is
    5 mm thick and it is sitting in the bore".
    """

    def crossing(solid_at: float, empty_at: float) -> float:
        for _ in range(40):
            middle = 0.5 * (solid_at + empty_at)
            point = origin + direction * middle
            if float(solid(point)) < -_ON_SURFACE_MM:
                solid_at = middle
            else:
                empty_at = middle
        return 0.5 * (solid_at + empty_at)

    first = float(distances[start])
    last = float(distances[end])
    # A run that touches the end of the sampled segment has no empty neighbour
    # to bisect against: the material continues to the edge of the part.
    if start > 0:
        first = crossing(first, float(distances[start - 1]))
    if end < len(distances) - 1:
        last = crossing(last, float(distances[end + 1]))
    return first, last


def _option_of(feature: Any, name: str) -> str:
    """A feature's enum parameter as written, or ''."""
    value = (getattr(feature, "parameters", None) or {}).get(name)
    return str(getattr(value, "option", value) or "")


def _check_through_holes(
    component: Component,
    part: CompiledPart,
    evidence: EvidenceGraph,
    input_hash: str,
) -> list[GateResult]:
    """Every hole declared without a ``depth`` must actually be open.

    A ``hole`` with no ``depth`` is a through hole: the backend cuts it with a
    tool long enough to clear the envelope in both directions, so at the moment
    of the cut nothing is left on its centre line. A *later* feature can put the
    material back, and nothing downstream notices -- the volume is plausible,
    the mesh is watertight, every requirement about diameters and thicknesses
    still passes, and the part is wrong in the one way that matters.

    Observed live: a standoff whose post was drilled and *then* unioned with its
    base plate. The union refilled the bottom 5 mm of the bore, and the part
    printed as a post with a blind pocket. ``GEOM_BURIED_ENTITIES`` saw the
    symptom -- the post's base face was 100% interior -- and passed anyway,
    because burial is usually legitimate and that gate only counts.

    So this gate does not count; it measures. For each declared through hole it
    walks the centre line across the part's own extent and asks the field
    whether there is material there. Material on the centre line of a through
    hole is not a judgement call.
    """
    holes = [
        feature
        for feature in component.features
        if feature.kind == "hole" and "depth" not in feature.parameters
    ]
    if not holes:
        return []

    envelope = part.solid.envelope
    if envelope.is_empty:
        return []

    blocked: list[dict[str, Any]] = []
    checked: list[str] = []
    for feature in holes:
        prefix = feature.role or feature.identifier
        entity = part.geometry_map.get(f"{prefix}.axis")
        if entity is None:
            # The hole's branch never reached the terminal solid, so there is no
            # bore in the finished part to be open or blocked.
            continue
        origin = np.asarray(entity.frame.origin, dtype=float)
        direction = np.asarray(entity.frame.z_axis, dtype=float)
        norm = float(np.linalg.norm(direction))
        if norm < 1e-12:
            continue
        direction = direction / norm

        segment = _segment_inside_box(origin, direction, envelope)
        if segment is None:
            continue
        bore = part.geometry_map.get(f"{prefix}.bore")
        one_wall = _option_of(feature, "through") == "first_wall"
        if bore is not None and (bore.warps or one_wall) \
                and "length" in bore.dimensions:
            # Through ONE wall: a hole drilled from inside a hollow part
            # through the wall it points at is open through that wall, and
            # the wall across the hollow is meant to stay whole. Walked along
            # the whole line, the six holes in a calf shell's rear wall were
            # reported blocked by its front wall -- three repair rounds, and
            # the run stopped, on a part with every hole where the brief
            # put it.
            #
            # Bent since it was drilled: the hole goes through the plate it
            # was drilled in, and its line, carried round with the bend, can
            # run on into another part of the same plate -- a wing folded
            # back over the base. Walked along the bore's own length, where
            # a later feature filling it would be found.
            centre = float((np.asarray(bore.frame.origin, dtype=float)
                            - origin) @ direction)
            half = float(bore.dimensions["length"]) / 2.0 + 0.5
            segment = (max(segment[0], centre - half),
                       min(segment[1], centre + half))
            if segment[0] >= segment[1]:
                continue
        checked.append(feature.identifier)

        lower, upper = segment
        distances = np.linspace(lower, upper, _AXIS_SAMPLES)
        points = origin + np.outer(distances, direction)
        solid_here = np.asarray(part.solid(points)) < -_ON_SURFACE_MM
        if not bool(solid_here.any()):
            continue

        # The samples say roughly where the blockage is; the field says exactly.
        # Reporting the sample grid instead would tell a reader the plate they
        # can measure with callipers is 4.95 mm thick, which invites them to
        # doubt the finding rather than fix it.
        runs = [
            _refine_run(part.solid, origin, direction, distances, start, end)
            for start, end in _solid_runs(solid_here)
        ]
        blocked.append(
            {
                "feature": feature.identifier,
                "from": [
                    round(float(v), 3) for v in origin + direction * runs[0][0]
                ],
                "to": [
                    round(float(v), 3) for v in origin + direction * runs[-1][1]
                ],
                "blocked_length_mm": round(
                    sum(end - start for start, end in runs), 3
                ),
                "obstructions": len(runs),
                "axis": [round(float(v), 6) for v in direction],
            }
        )

    if not checked:
        return []

    gate = Gate(
        identifier="GEOM_THROUGH_HOLES_OPEN",
        claim="every hole declared without a depth is open through the part",
        comparison="at_most",
        threshold=Q(0),
        critical=True,
        rationale="A hole with no `depth` is a through hole by definition. If "
        "the finished solid still has material on its centre line, a later "
        "feature refilled the bore, and the part that gets printed has a "
        "pocket where the document says there is a hole. Volume, watertightness "
        "and every dimensional requirement can all pass while this is wrong, so "
        "it is measured directly rather than inferred.",
    )
    detail: dict[str, Any] = {
        "checked": checked,
        "blocked": blocked,
    }
    if blocked:
        names = ", ".join(f"`{entry['feature']}`" for entry in blocked)
        subject = (
            f"{names} declares no `depth`, so it is a through hole, but the "
            "finished part still has material on its centre line"
            if len(blocked) == 1
            else f"{names} declare no `depth`, so they are through holes, but "
            "the finished part still has material on their centre lines"
        )
        detail["hint"] = (
            f"{subject}. Something built after the cut put material back into "
            "the bore -- nearly always a `union` that adds a solid the hole "
            "was never cut through. Order the features so the hole is cut "
            "LAST: build the whole body first, then give the `hole` feature "
            "that body's id as its input, so the bore passes through "
            "everything. (If the material is meant to be there, it is not a "
            "through hole: a hole through ONE wall of a hollow part is "
            "`through: first_wall`, with `position` inside the hollow and "
            "`axis` pointing at that wall and no `depth`; any other hole that "
            "stops gets a `depth` saying how deep it goes.)"
        )
    node = gate.evaluate(
        Q(len(blocked)),
        method=Method.EXACT_GEOMETRY,
        tool=TOOL_KERNEL,
        input_hashes=(input_hash,),
        limitations=(
            f"the centre line is sampled at {_AXIS_SAMPLES} points across the "
            "part's extent; a blockage thinner than the sample spacing would "
            "be missed",
            "only the centre line is tested, so a bore partly obstructed off "
            "axis is not detected here",
        ),
        detail=detail,
    )
    evidence.add(node)
    return [GateResult(gate, node)]


def _the_material_across_a_hole(part: CompiledPart, centre: Any,
                                direction: Any) -> str:
    """Where the material is on the two lines square to a hole through its
    centre: a pivot at the very tip of a tab reads "z = -30.8 to 25" -- the
    tab runs up from the hole and not below it."""
    try:
        centre = np.asarray(centre, dtype=float)
        direction = np.asarray(direction, dtype=float)
        envelope = part.solid.envelope
        reach = float(np.linalg.norm(np.asarray(envelope.hi, dtype=float)
                                     - np.asarray(envelope.lo, dtype=float)))
        said = []
        for k in range(3):
            if abs(float(direction[k])) > 0.5:
                continue
            line = np.zeros(3)
            line[k] = 1.0
            ts = np.linspace(-reach, reach, 3001)
            inside = np.asarray(part.solid(centre[None, :] + ts[:, None]
                                           * line[None, :])) < 0.0
            runs, start = [], None
            for t, flag in zip(ts, inside):
                if flag and start is None:
                    start = t
                elif not flag and start is not None:
                    runs.append((float(centre[k] + start),
                                 float(centre[k] + t)))
                    start = None
            near = [r for r in runs if r[0] - 30 <= centre[k] <= r[1] + 30]
            said.append(f"along {'xyz'[k]}, material at " + (", ".join(
                f"{a:.1f} to {b:.1f}" for a, b in near[:3]) or "none nearby"))
        return "; ".join(said) + "." if said else ""
    except Exception:  # noqa: BLE001 - no numbers is no worse than before
        return ""


def where_a_hole_is_and_the_material_is(part: CompiledPart, feature: Any) -> str:
    """In numbers: the stretch a hole cuts along its axis, and where the
    part's material is on that line.

    "No point on the axis lies inside the solid" is true and not enough. On a
    calf shell six mounting holes were drilled from the middle of the hollow
    20 mm toward the shin, into air, and the analyst -- told only that they
    cut nothing -- could not see where the wall was and gave up. The wall's
    place on that very line is the fact it needed.
    """
    prefix = getattr(feature, "role", "") or feature.identifier
    bore = part.geometry_map.get(prefix + ".bore")
    if bore is None:
        return ""
    try:
        origin = np.asarray(bore.frame.origin, dtype=float)
        direction = np.asarray(bore.frame.z_axis, dtype=float)
        direction = direction / max(float(np.linalg.norm(direction)), 1e-12)
        envelope = part.solid.envelope
        lo = np.asarray(envelope.lo, dtype=float)
        hi = np.asarray(envelope.hi, dtype=float)
        reach = float(np.linalg.norm(hi - lo)) + 10.0
        ts = np.linspace(-reach, reach, 4001)
        points = origin[None, :] + ts[:, None] * direction[None, :]
        inside = np.asarray(part.solid(points)) < 0.0
    except Exception:  # noqa: BLE001 - no numbers is no worse than before
        return ""
    axis = int(np.argmax(np.abs(direction)))
    aligned = abs(abs(float(direction[axis])) - 1.0) < 1e-6

    def coordinate(t: float) -> float:
        return float((origin + t * direction)[axis]) if aligned else float(t)

    runs = []
    start = None
    for t, flag in zip(ts, inside):
        if flag and start is None:
            start = t
        elif not flag and start is not None:
            runs.append((coordinate(start), coordinate(t)))
            start = None
    half = float(bore.dimensions.get("length", 0.0)) / 2.0
    name = "xyz"[axis] if aligned else "t"
    across = ", ".join(f"{'xyz'[i]}={float(origin[i]):g}" for i in range(3)
                       if not aligned or i != axis)
    cut = sorted((coordinate(-half), coordinate(half)))
    found = "; ".join(f"{name} = {min(a, b):.1f} to {max(a, b):.1f}"
                      for a, b in runs[:6])
    if found:
        found = f"on that line the part's material is at {found}."
    else:
        # A line that misses the part entirely: say which way, and how far,
        # the material is -- a pivot on the tip of a tab drawn 2.5 mm short
        # misses it by about that much.
        found = "that line misses the part's material entirely"
        try:
            values = np.asarray(part.solid(points), dtype=float)
            closest = points[int(np.argmin(values))]
            gap = float(values.min())
            where = ", ".join(f"{'xyz'[i]}={float(closest[i]):.1f}"
                              for i in range(3))
            # Which way the material is: step out square to the axis along
            # each of the other axes, both senses (a gradient is no use when
            # the line runs midway between two walls).
            ways = []
            steps = np.arange(0.25, max(gap, 2.0) + 6.0, 0.25)
            # From the hole's own centre first: a field bound is not a
            # distance, so the point it calls closest can be off to the side.
            for start in (origin, closest):
              if ways:
                break
              for i in range(3):
                if abs(float(direction[i])) > 0.9:
                    continue
                for sense in (1.0, -1.0):
                    e = np.zeros(3)
                    e[i] = sense
                    probe = start[None, :] + steps[:, None] * e[None, :]
                    hit = np.nonzero(np.asarray(part.solid(probe)) < 0.0)[0]
                    if hit.size:
                        at = ", ".join(f"{'xyz'[q]}={float(probe[hit[0], q]):.1f}"
                                       for q in range(3))
                        ways.append(f"{'+' if sense > 0 else '-'}{'xyz'[i]} "
                                    f"(first material at ({at}))")
            found += "; the nearest material"
            del where
            found += (" from its centre lies toward " + " and ".join(ways) + "."
                      if ways else f" is about {gap:.1f} mm from the line.")
        except Exception:  # noqa: BLE001
            found += "."
    return (f"`{feature.identifier}` runs along {name} through ({across}) and "
            f"cuts {name} = {cut[0]:.1f} to {cut[1]:.1f}; {found}")


def the_bore_found_material(part: CompiledPart, feature: Any) -> bool:
    """Whether this hole, as compiled, cuts through any material at all.

    Read off the published bore rather than probed for: the backend reports a
    `bearing_length` of exactly zero when no point on the hole's axis lies
    inside the solid it was handed. That is the cheapest possible detector for
    "this hole is in empty space", and it needs no field evaluation of ours.

    Public, and defined here beside the gate that needs it, because two copies
    of this reader existed and only one of them was ever used to explain a
    failure to anybody.
    """
    name = (getattr(feature, "role", "") or feature.identifier) + ".bore"
    entity = part.geometry_map.get(name)
    if entity is None:
        return False
    length = (getattr(entity, "dimensions", None) or {}).get("bearing_length")
    try:
        return float(getattr(length, "magnitude", length)) > 0.0
    except (TypeError, ValueError):
        return False


def _check_features_contribute(
    component: Component,
    part: CompiledPart,
    evidence: EvidenceGraph,
    input_hash: str,
) -> list[GateResult]:
    """Every feature must leave a mark on the finished part.

    A feature publishes named faces. If not one of them survives on the
    boundary, that feature changed nothing that anybody can see or touch: it
    was filled back in, swallowed by a blend, placed outside the material, or
    cancelled by a boolean. The document says the part has it. The part does
    not have it.

    This is the check the last live failure needed, and it is more general than
    any of the specific ones it subsumes. On that run all three holes published
    a bore and not one bore was on the boundary -- the part had no holes at all
    -- while `GEOM_BURIED_ENTITIES` counted them and passed, because it is a
    counter compared `at_least 0` and cannot fail.

    Burial of *some* faces is normal and stays legitimate: a post's base
    disappears into the plate it stands on, and the plate's top is partly
    covered by the post. The claim here is only that something of each feature
    remains.
    """
    checked, absent = _features_left_without_a_surface(component, part)
    if not checked:
        return []
    return _the_contribution_gate(component, part, evidence, input_hash,
                                  checked, absent)


def _features_left_without_a_surface(
    component: Component, part: CompiledPart
) -> tuple[int, list[dict[str, Any]]]:
    """How many features were judged, and each that left nothing of its own
    on the part. One answer for the gate and for the fact sheet: the sheet
    once listed a cutter as absent the gate had found on the part, and the
    analyst was told both."""
    buried = {entity.name for entity in part.buried_entities()}
    absent: list[dict[str, Any]] = []
    checked = 0
    # A solid a `shell` or an `offset` is made from has its whole surface
    # drawn again by that feature, moved off it: a shell `both` ways puts
    # every wall a half-thickness either side of the face it came from, and
    # none of the original face is left -- while every bit of the part is
    # that solid's. Its contribution is the shell's, and is not a missing
    # feature. Observed: a cylinder shelled `both` ways, reported as having
    # contributed nothing.
    # Only where no face is left where it was: an inward shell keeps the
    # outer face and an outward one the inner, and those stay checked.
    redrawn = {
        name
        for feature in component.features
        if feature.kind == "offset" or (
            feature.kind == "shell"
            and getattr(feature.parameters.get("direction"), "option", "")
            == "both")
        for name in feature.inputs
    }
    for feature in component.features:
        if feature.identifier in redrawn:
            continue
        faces = [
            name
            for name in feature.semantic_names()
            if (entity := part.geometry_map.get(name)) is not None
            and entity.entity_type.endswith("face")
        ]
        if not faces:
            continue
        checked += 1
        if any(name not in buried for name in faces):
            continue
        if feature.kind != "hole" and _some_of_its_surface_is_left(part, faces):
            # "Buried" is a quarter of a face gone or more; contributing is
            # any of it left. Not for a hole: a bore whose axis only grazes
            # the skin touches the boundary along a line and cut nothing,
            # and has its own test of whether it did. The box that cuts a hollow dome in half keeps
            # only the ring of its face where the shell was cut -- an eighth
            # of the square -- and that ring is the dome's rim.
            continue
        absent.append(
            {
                "feature": feature.identifier,
                "kind": feature.kind,
                "faces": faces,
                # Which of the two ways a hole can vanish this one is. The
                # gate used to name only the first and prescribe its fix,
                # which sent one repair loop chasing a `union` that was not
                # there while the real fault -- an axis lying on the outer
                # surface, cutting nothing -- went unmentioned for two
                # rounds. The backend already knows; it costs nothing to ask.
                "cut_nothing": (
                    feature.kind == "hole"
                    and not the_bore_found_material(part, feature)
                ),
            }
        )
    return checked, absent


def _the_contribution_gate(
    component: Component,
    part: CompiledPart,
    evidence: EvidenceGraph,
    input_hash: str,
    checked: int,
    absent: list[dict[str, Any]],
) -> list[GateResult]:
    gate = Gate(
        identifier="GEOM_FEATURES_CONTRIBUTE",
        claim="every feature leaves some of its own surface on the part",
        comparison="at_most",
        threshold=Q(0),
        critical=True,
        rationale="A feature whose every published face is interior did not "
        "change the finished part. The document describes something the object "
        "does not have, and every measurement downstream is measuring a "
        "different part from the one that was specified.",
    )
    detail: dict[str, Any] = {"features_checked": checked, "absent": absent}
    if absent:
        named = ", ".join(f"`{entry['feature']}`" for entry in absent)
        kinds = {entry["kind"] for entry in absent}
        cut_nothing = [e for e in absent if e.get("cut_nothing")]
        refilled = [
            e for e in absent
            if e["kind"] == "hole" and not e.get("cut_nothing")
        ]
        located = [where_a_hole_is_and_the_material_is(
            part, next(f for f in component.features
                       if f.identifier == e["feature"])) for e in cut_nothing]
        located = [x for x in located if x]
        if located:
            detail["where_each_is"] = located
        detail["hint"] = (
            f"{named} contributed nothing to the finished part: every face "
            "each one publishes is interior, so the object does not have it. "
            + (
                ", ".join(f"`{e['feature']}`" for e in cut_nothing)
                + " never cut anything: the stretch of its axis it cuts lies "
                "wholly outside the solid it was handed. This is a placement "
                "fault, not a graph fault -- chaining it differently will not "
                "help. "
                + (" ".join(located) + " " if located else "")
                + "`position` is a point the AXIS PASSES THROUGH, and the "
                "hole cuts along its axis from there; move each so the "
                "stretch it cuts crosses the material on its line, with the "
                "point inside the material or the cut long enough to reach "
                "it. For a hole through one wall of a hollow part, give it "
                "`through: first_wall` with `position` inside the hollow "
                "and `axis` pointing at that wall -- it finds the wall and "
                "stops past it; for a radial "
                "hole through a solid round body, its centre line works. "
                if cut_nothing else ""
            )
            + (
                ", ".join(f"`{e['feature']}`" for e in refilled)
                + " did cut material, and then lost it: something built "
                "afterwards filled the bore back in -- a `union` that adds a "
                "solid the hole was never cut through, or a boolean whose "
                "operands are all copies of one body. Cut each hole from the "
                "finished body, chaining them so each takes the previous "
                "feature as its input. "
                if refilled else ""
            )
            + (
                "A solid disappears like this when it sits entirely inside "
                "another, or when a `blend_radius` large enough to swallow it "
                "is applied to the boolean that joins them."
                if kinds - {"hole"} else ""
            )
        ).strip()
    node = gate.evaluate(
        Q(len(absent)),
        method=Method.EXACT_GEOMETRY,
        tool=TOOL_KERNEL,
        input_hashes=(input_hash,),
        limitations=(
            "a feature is judged by the faces it publishes; a feature that "
            "publishes none -- a boolean, a transform -- is not checked here",
        ),
        detail=detail,
    )
    evidence.add(node)
    return [GateResult(gate, node)]


def _some_of_its_surface_is_left(part: CompiledPart, faces: Sequence[str]) -> bool:
    """Whether any face of these leaves a real patch of itself on the part.

    The same neighbourhood test the lineage uses -- material and space both
    within a whisker of the sample -- but asking for a patch, not a quarter:
    two in a hundred of a face's samples on the boundary, which a face
    merely grazing an edge does not reach.
    """
    solid = part.solid
    tolerance = max(solid.envelope.diagonal * 1e-3, 1e-6)
    probes = np.array([[1.0, 0, 0], [-1.0, 0, 0], [0, 1.0, 0], [0, -1.0, 0],
                       [0, 0, 1.0], [0, 0, -1.0]]) * tolerance
    for name in faces:
        entity = part.geometry_map.get(name)
        if entity is None:
            continue
        try:
            samples = np.asarray(entity.sample_points(), dtype=float)
        except Exception:  # noqa: BLE001 - an entity with no samples says nothing
            continue
        if samples.ndim != 2 or samples.shape[0] == 0:
            continue
        field = solid((samples[:, None, :] + probes[None, :, :]).reshape(
            -1, 3)).reshape(samples.shape[0], probes.shape[0])
        on = np.any(field < 0.0, axis=1) & np.any(field > 0.0, axis=1)
        # A share of the face, or a patch of points whatever the share: the
        # side of a long cutter through one thin wall is a few millimetres
        # of its length, and those few are the opening's walls.
        if float(on.mean()) >= 0.02 or int(on.sum()) >= 6:
            return True
    # Looked at again, a sample every millimetre or so: a box 60 mm long
    # cutting a window in a 3 mm wall has its faces sampled in rows 8 mm
    # apart, every one of them in the air either side of the wall.
    for name in faces:
        entity = part.geometry_map.get(name)
        if entity is None or (entity.entity_type == "swept_face"
                              and not entity.dimensions.get("ring")):
            continue
        try:
            samples = np.asarray(entity.sample_points(spacing=0.5), dtype=float)
        except Exception:  # noqa: BLE001 - an entity with no samples says nothing
            continue
        if samples.ndim != 2 or samples.shape[0] == 0:
            continue
        field = solid((samples[:, None, :] + probes[None, :, :]).reshape(
            -1, 3)).reshape(samples.shape[0], probes.shape[0])
        on = np.any(field < 0.0, axis=1) & np.any(field > 0.0, axis=1)
        if int(on.sum()) >= 6:
            return True
    return False


#: Stations along a hole's axis at which Forge looks for a full wall around it.
_WALL_STATIONS = 97
#: Points on each ring of wall. Sixteen is a point every 22.5 degrees: a
#: notch in an edge is open over half the circle, so it cannot hide between.
_WALL_POINTS = 16


def _check_holes_are_surrounded(
    component: Component,
    part: CompiledPart,
    evidence: EvidenceGraph,
    input_hash: str,
) -> list[GateResult]:
    """Somewhere along its length, every hole has material all the way round.

    A hole on the very edge of a part is not a hole. It is a half-round
    channel in a face, and every other hole gate passes it: it cut material,
    so it contributes; its centre line is clear, so it is open; its entities
    exist, so nothing is buried. Observed on a collar built as a block
    centred on the origin, with its set screws at `length / 2` -- which on a
    body running from -7.5 to +7.5 is the top face. Two notches along the top
    edge, every hole gate green, and the brief had said "halfway along".

    The frame mix-up that produces it is common and silent: a primitive
    `centered` on the origin, and features placed as if it started there. So
    this asks the one question that separates a hole from a notch. At each of
    many stations along the axis, is there material on a ring just outside
    the hole's radius, all the way round? A hole through a wall has such a
    station wherever it is in the wall. A notch has none, anywhere.

    Only holes that cut material at all are judged; a hole through nothing
    is `GEOM_FEATURES_CONTRIBUTE`'s to report, and saying it twice helps no
    one. The ring sits a small margin outside the bore, so a hole whose edge
    comes near a face without breaking it is not called a notch.
    """
    envelope = part.solid.envelope
    if envelope.is_empty:
        return []

    notched: list[dict[str, Any]] = []
    checked: list[str] = []
    for feature in component.features:
        if feature.kind != "hole":
            continue
        prefix = feature.role or feature.identifier
        axis_entity = part.geometry_map.get(f"{prefix}.axis")
        bore = part.geometry_map.get(f"{prefix}.bore")
        if axis_entity is None or bore is None:
            continue
        radius = float(bore.dimensions.get("radius", 0.0))
        if radius <= 0.0:
            continue
        origin = np.asarray(axis_entity.frame.origin, dtype=float)
        direction = np.asarray(axis_entity.frame.z_axis, dtype=float)
        norm = float(np.linalg.norm(direction))
        if norm < 1e-12:
            continue
        direction = direction / norm
        segment = _segment_inside_box(origin, direction, envelope)
        if segment is None:
            continue

        # Two directions across the axis, for the ring.
        helper_axis = np.array([1.0, 0.0, 0.0])
        if abs(float(direction @ helper_axis)) > 0.9:
            helper_axis = np.array([0.0, 1.0, 0.0])
        across = np.cross(direction, helper_axis)
        across /= np.linalg.norm(across)
        other = np.cross(direction, across)
        margin = min(0.5, 0.25 * radius)
        ring_radius = radius + margin
        angles = np.linspace(0.0, 2.0 * np.pi, _WALL_POINTS, endpoint=False)
        ring = ring_radius * (
            np.outer(np.cos(angles), across) + np.outer(np.sin(angles), other)
        )

        lower, upper = segment
        # Only where the hole cuts: a mounting hole drilled 20 mm into the
        # hollow of a calf shell grazed the side wall, and the walls its
        # LINE went on to cross, front and back, had material all round --
        # so a groove passed as a hole. The bore's own stretch is the hole.
        length = float(bore.dimensions.get("length", 0.0))
        if length > 0.0:
            mid = float((np.asarray(bore.frame.origin, dtype=float) - origin)
                        @ direction)
            lower = max(lower, mid - length / 2.0)
            upper = min(upper, mid + length / 2.0)
            if upper <= lower:
                continue
        stations = np.linspace(lower, upper, _WALL_STATIONS)
        centres = origin + np.outer(stations, direction)
        points = (centres[:, None, :] + ring[None, :, :]).reshape(-1, 3)
        inside = (np.asarray(part.solid(points)) < -_ON_SURFACE_MM).reshape(
            len(stations), _WALL_POINTS)
        if not bool(inside.any()):
            # Nothing around it anywhere: it cuts nothing, which is another
            # gate's finding.
            continue
        checked.append(feature.identifier)
        if bool(inside.all(axis=1).any() or inside.any(axis=0).all()):
            # All round at one station, or every way round at some station:
            # a hole tilted through a thin plate is the second.
            continue
        best = int(inside.sum(axis=1).max())
        notched.append({
            "feature": feature.identifier,
            "centre": [round(float(v), 3) for v in origin],
            "axis": [round(float(v), 6) for v in direction],
            "most_wall_found": f"{best} of {_WALL_POINTS} directions",
            "around_it": _the_material_across_a_hole(part, origin, direction),
        })

    if not checked:
        return []

    gate = Gate(
        identifier="GEOM_HOLES_ARE_HOLES",
        claim="every hole has material all the way round it somewhere along "
        "its length",
        comparison="at_most",
        threshold=Q(0),
        critical=True,
        rationale="A hole whose axis runs along a face of the part cuts a "
        "half-round channel in that face. It removes material, its centre "
        "line is clear and its entities exist, so every other hole gate "
        "passes it -- and it is not a hole.",
    )
    detail: dict[str, Any] = {"checked": checked, "notched": notched}
    if notched:
        names = ", ".join(f"`{entry['feature']}`" for entry in notched)
        around = " ".join(f"`{e['feature']}`, centred at "
                          f"({', '.join(f'{v:g}' for v in e['centre'])}): "
                          f"{e['around_it']}" for e in notched
                          if e.get("around_it"))
        detail["hint"] = (
            f"{names} never has material all the way round it: its axis runs "
            "along the edge or a face of the part, so it cuts a channel, not "
            "a hole. "
            + (around + " " if around else "")
            + "The usual cause is a hole placed at the end or edge of the "
            "solid it belongs to -- a pivot at the very tip of a tab whose "
            "end was drawn short -- or a body `centered` on the origin with "
            "features placed as if it started there. Put the hole where the "
            "material is, with material on every side of it."
        )
    node = gate.evaluate(
        Q(len(notched)),
        method=Method.EXACT_GEOMETRY,
        tool=TOOL_KERNEL,
        input_hashes=(input_hash,),
        limitations=(
            f"{_WALL_STATIONS} stations along each axis and {_WALL_POINTS} "
            "directions round it; the ring sits "
            "min(0.5 mm, a quarter of the radius) outside the bore",
        ),
        detail=detail,
    )
    evidence.add(node)
    return [GateResult(gate, node)]


def describe_the_part(
    component: Component, part: CompiledPart, properties: Any
) -> dict[str, Any]:
    """What Forge measured about the object it actually built.

    The system had no sense of what it made. It wrote a document blind, and
    everything downstream reported on *numbers in that document* -- which is
    why a part with its plate in the wrong plane and no holes in it could pass
    seven dimensional requirements and be called a release candidate.

    This is the sensing organ: measured, deterministic, no model anywhere near
    it. It goes in the report, so a person sees the object's real shape beside
    the verdict, and it goes into the repair prompt, so the analyst is looking
    at the part it built instead of guessing from gate names.
    """
    size = properties.bounding_box_size()
    holes: list[dict[str, Any]] = []
    buried = {entity.name for entity in part.buried_entities()}
    for feature in component.features:
        if feature.kind != "hole":
            continue
        prefix = feature.role or feature.identifier
        bore = part.geometry_map.get(f"{prefix}.bore")
        entry: dict[str, Any] = {"feature": feature.identifier}
        if bore is None:
            entry["present"] = False
            entry["note"] = "no bore in the finished part"
        else:
            entry["present"] = f"{prefix}.bore" not in buried
            entry["diameter_mm"] = round(
                2.0 * float(bore.dimensions.get("radius", 0.0)), 3
            )
            entry["centre_mm"] = [round(v, 2) for v in bore.frame.origin]
            if not entry["present"]:
                entry["note"] = "filled in by a later feature"
        holes.append(entry)

    return {
        "envelope_mm": [round(q.magnitude.midpoint, 2) for q in size],
        "volume_mm3": round(properties.volume.magnitude.midpoint, 1),
        "holes": holes,
        "open_holes": sum(1 for h in holes if h.get("present")),
        "features_without_a_surface": [
            entry["feature"]
            for entry in _features_left_without_a_surface(component, part)[1]
        ],
    }


def render_the_part(facts: Mapping[str, Any]) -> str:
    """The fact sheet in words, for a terminal and for a prompt."""
    lines = [
        "The part as built and measured:",
        "  envelope   {} x {} x {} mm".format(*facts["envelope_mm"]),
        f"  volume     {facts['volume_mm3']} mm^3",
    ]
    if facts["holes"]:
        lines.append(
            f"  holes      {facts['open_holes']} open of "
            f"{len(facts['holes'])} declared"
        )
        for hole in facts["holes"]:
            where = (
                f"{hole['diameter_mm']} mm at "
                f"({', '.join(str(v) for v in hole['centre_mm'])})"
                if "diameter_mm" in hole
                else "not built"
            )
            state = "open" if hole.get("present") else "NOT IN THE PART"
            lines.append(f"    - {hole['feature']:<18} {where:<28} {state}")
    if facts["features_without_a_surface"]:
        lines.append(
            "  absent     "
            + ", ".join(facts["features_without_a_surface"])
            + " left no surface on the part"
        )
    if facts.get("dimensions"):
        # Which way each declared dimension actually runs. Measured by
        # `forge_pipeline.response`, and printed here because a report that
        # computes this and does not show it is no use to anybody.
        #
        # Earned immediately. A spacer whose brief asked for a 30 mm SQUARE
        # plate came back 30 x 12, because the base box carried the POST's
        # diameter in its second slot. Every number in the document was
        # right, so every dimensional requirement passed and the run said
        # `completed`. This line says `post_diameter: drives the y extent`
        # on a part whose plate is supposed to be square, which is the whole
        # defect in five words and the only place in the report it appears.
        lines.append("  each dimension, and what it actually drives:")
        lines.extend(f"    - {entry}" for entry in facts["dimensions"])
    return "\n".join(lines)


def _measured_or_blocked(binding: str, **kwargs: Any) -> Measurement:
    """`resolve_measurement`, with a fault inside one reader reported as that
    requirement's BLOCKED evidence rather than the end of the run.

    Thirty-odd readers measure the vocabulary, each written for the parts it
    had seen. One tripping over a part it had not -- a NaN out of a degenerate
    bend chain, an index past a short run -- left `verify_component` as a
    bare exception, which the orchestrator records as an internal error, and
    a run that had built and measured a part ended with no evidence at all.
    Fail closed, as evidence instead: the claim is BLOCKED, named as Forge's
    own defect so it is fixed rather than lived with, and every other claim
    on the part is still measured and reported.
    """
    try:
        return resolve_measurement(binding, **kwargs)
    except Exception as error:  # noqa: BLE001 - see the docstring
        import traceback

        return Measurement(
            value=None,
            blocked_reason=(
                "FORGE DEFECT: measuring this claim failed inside Forge "
                f"({type(error).__name__}: {str(error)[:300]}). Nothing is "
                "known about it, and it blocks release until the defect is "
                "fixed; the traceback is in this node's detail."),
            detail={"forge_defect": traceback.format_exc()[-2000:]},
        )


def _check_document_requirements(
    document: Document,
    component: Component,
    part: CompiledPart,
    properties: Any,
    evidence: EvidenceGraph,
    input_hash: str,
    measurements: dict[str, Any],
    *,
    surface_area: Quantity | None,
    wall_thickness: Quantity | None,
    load: Quantity | None,
    axis_of: Mapping[str, str] | None = None,
    mesh_extents: Sequence[Quantity] | None = None,
    hollows: Any = None,
) -> list[GateResult]:
    """Turn each declared requirement into a gate, via its measurement binding.

    A requirement that declares a threshold but no ``measurement`` is reported
    ``NOT_TESTED`` with an explanation. That is the honest outcome: nothing
    checked it. The earlier version of this function inferred what to measure
    from hard-coded parameter names, which verified exactly one part in the world
    and silently checked nothing on any other.
    """
    results: list[GateResult] = []

    # Figures the design declares and this set already checks exactly. A
    # `parameter:` binding reads the resolved parameter table, so it is exact
    # and cannot itself be a measurement error. Used below to tell a wrong
    # envelope claim from one that merely restates a number already verified.
    #
    # Only a figure that is a size INSIDE the part -- a bore, a hole, a
    # spacing, a fillet -- by the parameter's own name. A dome's `height`
    # is the part's own height: the dome came back a whole sphere 50 tall,
    # `height = 25` declared and read by a box nothing needed, the claim on
    # its outside excused as "restating" that figure, and the run released
    # as PASS. A claim about the part's outside is only excused by a figure
    # that cannot be on the outside.
    exactly_checked = {
        _figure(requirement.threshold): requirement.identifier
        for requirement in document.requirements
        if str(requirement.measurement or "").startswith("parameter:")
        and _figure(requirement.threshold)
        and _a_size_inside_the_part(
            str(requirement.measurement).partition(":")[2])
    }

    for requirement in document.requirements:
        gate = Gate(
            identifier=requirement.identifier,
            claim=requirement.statement,
            comparison=requirement.comparison,
            threshold=requirement.threshold,
            tolerance=_default_tolerance(
                requirement.threshold, requirement.measurement
            ),
            requirement_id=requirement.identifier,
            critical=requirement.is_critical,
        )

        if requirement.comparison in ("", "none") or requirement.threshold is None:
            # A qualitative requirement. It is recorded, and it is not pretended
            # to have been checked.
            node = gate.evaluate(
                None,
                method=Method.EXACT_GEOMETRY,
                tool=TOOL_KERNEL,
                input_hashes=(input_hash,),
                blocked_reason="",
                limitations=(
                    "qualitative requirement with no numeric threshold; it "
                    "cannot be checked automatically",
                ),
            )
            evidence.add(node)
            results.append(GateResult(gate, node))
            continue

        if requirement.verification in _METHODS_FORGE_CANNOT_PERFORM:
            # The requirement named the procedure that would satisfy it, and
            # it is not one a geometry kernel can carry out. Measuring the
            # part anyway and reporting PASS says a physical test happened.
            #
            # Found by audit and reproduced: a requirement asking for
            # `physical_test` was answered with `Method.EXACT_GEOMETRY`, given
            # PASS, and carried into an overall PASS. Nothing in the report
            # said no test was run. The measurement is still taken and still
            # recorded in `detail`, because it is useful to whoever does run
            # the test -- it is just not evidence that the test happened.
            measured = _measured_or_blocked(
                requirement.measurement,
                component=component,
                part=part,
                properties=properties,
                surface_area=surface_area,
                wall_thickness=wall_thickness,
                load=load,
                hollows=hollows,
            )
            node = gate.evaluate(
                None,
                method=_DEMANDED_METHOD[requirement.verification],
                tool=TOOL_KERNEL,
                input_hashes=(input_hash,),
                blocked_reason=(
                    f"this requirement asks to be verified by "
                    f"`{requirement.verification}`, which Forge cannot "
                    "perform. It is recorded as untested rather than checked "
                    "against the geometry, because a measurement is not the "
                    "procedure the requirement named."
                ),
                limitations=(
                    f"`{requirement.verification}` needs evidence from "
                    "outside this system; no deterministic measurement "
                    "substitutes for it",
                ),
                detail={
                    "measurement": requirement.measurement,
                    "demanded_verification": requirement.verification,
                    "measured_anyway": (
                        str(measured.value) if measured.ok and measured.value
                        is not None else ""
                    ),
                    "hint": (
                        "If a dimensional check was meant, set "
                        "`verification` to `exact_geometry` and Forge will "
                        "measure it. If the physical procedure is genuinely "
                        "required, this requirement stays untested until "
                        "someone performs it and the run stays blocked, "
                        "which is the honest outcome."
                    ),
                },
            )
            evidence.add(node)
            results.append(GateResult(gate, node))
            continue

        if not requirement.measurement:
            node = gate.evaluate(
                None,
                method=Method.EXACT_GEOMETRY,
                tool=TOOL_KERNEL,
                input_hashes=(input_hash,),
                limitations=(
                    "this requirement declares a threshold but no `measurement` "
                    "binding, so nothing measured it. Bind it to one of the "
                    "measurement vocabulary entries to have it checked.",
                ),
            )
            evidence.add(node)
            results.append(GateResult(gate, node))
            continue

        measured = _measured_or_blocked(
            requirement.measurement,
            component=component,
            part=part,
            properties=properties,
            surface_area=surface_area,
            wall_thickness=wall_thickness,
            load=load,
            hollows=hollows,
        )
        loose = _an_enclosure_too_loose_to_judge(
            requirement.measurement, measured, mesh_extents)
        if loose is not None:
            measured = loose
        if measured.ok and measured.value is not None:
            measurements[requirement.measurement] = str(measured.value)

        method = {
            "exact_geometry": Method.EXACT_GEOMETRY,
            "analytical": Method.ANALYTICAL,
            "sampling": Method.SAMPLING,
        }.get(measured.method, Method.EXACT_GEOMETRY)

        # A tolerance finer than the measurement is a guaranteed non-answer,
        # so the gate is rebuilt at the precision this measurement reached.
        # Only ever widened, only for `equals`, and never silently: the
        # sentence goes into the node's limitations beside the verdict.
        limitations = tuple(measured.limitations)
        if requirement.comparison == "equals" and measured.value is not None:
            instead, why = _the_extent_this_claim_is_really_about(
                requirement.measurement, requirement.comparison,
                requirement.threshold, properties, axis_of)
            if instead is not None:
                measured = replace(measured, value=instead)
                measurements[requirement.measurement] = str(instead)
                limitations = limitations + (why,)
        if requirement.comparison == "equals":
            widened, why = _tolerance_you_can_actually_measure(
                gate.tolerance, measured.value)
            if why:
                gate = replace(gate, tolerance=widened)
                limitations = limitations + (why,)

        try:
            node = gate.evaluate(
                measured.value,
                method=method,
                tool=(
                    TOOL_ANALYSIS
                    if method is Method.ANALYTICAL
                    else (TOOL_MEASURE if method is Method.SAMPLING else TOOL_KERNEL)
                ),
                input_hashes=(input_hash,),
                limitations=limitations,
                blocked_reason=measured.blocked_reason,
                detail={"measurement": requirement.measurement, **dict(measured.detail)},
            )
        except ValueError as error:
            # A gate that cannot be evaluated is a fact about the requirement,
            # not an internal error -- most often an `equals` with no tolerance
            # on something that is not a length. Raising here would take the
            # whole run down and lose every measurement already made; reported
            # as evidence, the repair loop can fix the requirement instead.
            node = gate.evaluate(
                None,
                method=Method.EXACT_GEOMETRY,
                tool=TOOL_KERNEL,
                input_hashes=(input_hash,),
                blocked_reason=f"this requirement cannot be checked: {error}",
                limitations=(str(error),),
                detail={
                    "measurement": requirement.measurement,
                    "hint": (
                        f"Requirement {requirement.identifier} compares with "
                        f"`{requirement.comparison}` against "
                        f"{requirement.threshold}. Give it a `tolerance` in the "
                        "same unit, or state it as `at_most` / `at_least`, "
                        "which need none."
                    ),
                },
            )
        # An extent claim that is wrong AND restates a figure already
        # checked exactly is the model's bookkeeping, not the user's
        # requirement. Observed on a shaft collar: `bounding_box_z equals
        # 12 mm`, where 12 mm is the bore -- a hole, not an extent of
        # anything -- and `REQ_BORE_DIAMETER` checks that same 12 mm and
        # passes. Failing the run over it fails a part that is right.
        #
        # NOT_APPLICABLE rather than PASS, and the difference is the whole
        # point: Forge is not saying the part is 12 mm in some direction. It
        # is saying this claim does not apply to the finished object, and
        # naming the requirement that does check the figure. A claim whose
        # number nothing else verifies still FAILS.
        checker = exactly_checked.get(_figure(requirement.threshold), "")
        if (
            node.status is Status.FAIL
            and checker
            and checker != requirement.identifier
            and requirement.comparison == "equals"
            and str(requirement.measurement or "").startswith("bounding_box_")
        ):
            node = replace(
                node,
                status=Status.NOT_APPLICABLE,
                limitations=tuple(node.limitations) + (
                    f"no extent of the finished part is {requirement.threshold}, "
                    f"and `{checker}` already checks that same figure exactly. "
                    "This claim restates a number the design declares and puts "
                    "it on the outside of the part, where it is not -- so it is "
                    "reported as not applying rather than as a failure of the "
                    "geometry, which is right",
                ),
            )
        evidence.add(node)
        results.append(GateResult(gate, node))

    return results


#: Words that name a size inside a part, never one of its extents.
_INSIDE_WORDS = frozenset({
    "bore", "bores", "hole", "holes", "inner", "inside", "internal", "id",
    "slot", "slots", "pocket", "pockets", "cavity", "recess", "groove",
    "fillet", "chamfer", "blend", "radius", "thread", "spacing", "pitch",
    "distance", "apart", "offset", "counterbore", "countersink", "screw",
    "bolt", "pin", "shaft", "pattern", "circle", "pcd", "clearance",
})


def _a_size_inside_the_part(name: str) -> bool:
    """Whether a parameter's name says it is a size inside the part."""
    return bool(set(name.lower().split("_")) & _INSIDE_WORDS)


def _the_extents_of(mesh: Any, part: Any, resolution: int) -> list[Quantity] | None:
    """The extracted surface's own extent on each axis, to a mesh cell."""
    try:
        vertices = np.asarray(mesh.vertices, dtype=float)
        if vertices.size == 0:
            return None
        size = vertices.max(axis=0) - vertices.min(axis=0)
        envelope = np.asarray(part.solid.envelope.size, dtype=float)
        cell = float(envelope.max()) * 1.04 / max(resolution, 8)
        return [Q(Interval(max(float(v) - cell, 0.0), float(v) + cell), "mm")
                for v in size]
    except Exception:  # noqa: BLE001 - a fallback is never worth a crash
        return None


def _an_enclosure_too_loose_to_judge(
    binding: str | None, measured: Any, mesh_extents: Sequence[Quantity] | None
) -> Any:
    """A bounding box the octree could not close in on, read off the mesh.

    The hollow dome, its other half cut away by a box: the octree's
    enclosure of the result was 38.6 +/- 13.9 mm tall -- 95 % of the volume
    still unresolved at the depth reached -- and an equality claim on 25 mm
    passed inside it, as would one on 38. The extracted surface knows the
    part's extent to a mesh cell, and is the measurement where the
    enclosure is wider than a millimetre or 5 % of itself.
    """
    text = str(binding or "")
    head, _, figure = text.partition(":")
    if head not in ("footprint_side", "extent_side") and not text.startswith(
            "bounding_box_") or (
            mesh_extents is None or len(mesh_extents) != 3 or measured is None
            or not measured.ok or measured.value is None):
        return None
    if head in ("footprint_side", "extent_side"):
        # The side nearest the figure, among the same axes the measurement
        # itself chooses from.
        try:
            wanted = float(figure)
        except ValueError:
            return None
        axes = (0, 1) if head == "footprint_side" else (0, 1, 2)
        axis = min(axes, key=lambda i: abs(
            float(mesh_extents[i].magnitude.midpoint) - wanted))
    else:
        axis = "xyz".find(text[-1])
        if axis < 0:
            return None
    magnitude = getattr(measured.value, "magnitude", None)
    if not (hasattr(magnitude, "lo") and hasattr(magnitude, "hi")):
        return None
    width = abs(float(magnitude.hi) - float(magnitude.lo))
    centre = abs(float(magnitude.midpoint))
    if width <= max(1.0, 0.05 * centre) * 2:
        return None
    return replace(
        measured, value=mesh_extents[axis],
        limitations=tuple(measured.limitations) + (
            f"the octree's enclosure of this extent was {measured.value}, too "
            "loose to judge; measured instead on the extracted surface, to "
            "within one mesh cell",))


def _default_tolerance(
    threshold: Quantity | None, measurement: str = ""
) -> Quantity | None:
    """A tolerance for equality gates, when the requirement declares none.

    0.05 mm is the release threshold the build specification names for golden
    dimensions. It is applied only to lengths, because a tolerance invented for
    a quantity nobody specified one for is a number that looks checked.

    A count is the exception, and it is not really an exception: "there shall
    be four mounting holes" is satisfied by four and by nothing else. The count
    is an exact integer, so zero is the right tolerance rather than an absent
    one -- and an absent one used to raise ``ValueError`` out of the gate,
    through the verifier, and end the run in a traceback, which is how a
    perfectly reasonable requirement destroyed a half-hour run.

    The third case is the one that reveals what the rule above is really
    about, and it is not the dimension. A `parameter:` binding does not
    measure anything: it resolves a number the document declares, through
    exact arithmetic, to an interval of zero width. "Invented tolerance" is a
    hazard for a quantity somebody had to go and measure -- a mass, an
    envelope -- because there the tolerance decides what counts as close
    enough, and nobody chose it. It is not a hazard for a number the design
    wrote down, where the only question is whether two floats are the same
    float.

    Without this, every `equals` claim on a declared parameter outside
    millimetres is unanswerable. A collar whose two set screws are 90 degrees
    apart, built exactly right, reported BLOCKED: "compares for equality but
    declares no tolerance". So did any safety factor, any declared angle, any
    dimensionless ratio. The claim was correct, the part was correct, and the
    gate could not say so.

    The figure is a floating-point epsilon rather than an engineering
    tolerance, scaled to the threshold so it means the same thing at 90 deg
    and at 0.001. It admits arithmetic noise from a derived parameter and
    nothing else: 90 against 90.0000000001 passes, 90 against 90.1 does not.
    Lengths keep 0.05 mm, which is a real engineering tolerance from the
    build specification and is left exactly as it was.
    """
    if threshold is None:
        return None
    if measurement in ("bend_centre", "bend_off_centre"):
        # Where a curve's middle is, read in millimetre steps along it.
        return Q(0.5, "mm")
    if measurement == "bent_along":
        # The flat extent the turning runs along, bisected to the face.
        return Q(0.05, "mm")
    if measurement == "bend_spread":
        # Where a bend starts and ends, each good to a 1 mm step.
        return Q(2.0, "mm")
    if threshold.dimension == parse_unit("mm").dimension:
        return Q(0.05, "mm")
    if measurement.startswith(("feature_count", "holes_of_diameter",
                               "openings_of_size", "openings_on_circle",
                               "openings_apart", "hole_at",
                               "walls_crossed",
                               "windows_of_size",
                               "counterbores",
                               "bend_count", "bend_convex",
                               "roundness_every_way")):
        return Q(0)
    if measurement == "bend_angle":
        # Read off the finished surface's normals: half a degree, as for
        # an angle between features.
        return Q(0.5, "deg")
    if measurement.startswith("parameter:"):
        figure = abs(_centre_of(threshold))
        return Q(max(figure * 1e-9, 1e-12), threshold.unit)

    # The fourth case: an angle measured between two features. Unlike a
    # declared parameter this really is a measurement, so an epsilon is the
    # wrong instrument -- a designer writing 45 degrees as
    # `[0.7071, 0.7071, 0]` builds 45.0000x, which is right, and an epsilon
    # would report it wrong. And unlike a mass, leaving it with no default is
    # not the safe answer either: without one, EVERY angular claim reports
    # BLOCKED and the measurement cannot answer anything at all.
    #
    # Half a degree, then, and stated rather than implied: it is coarser than
    # any rounding a hand-written direction vector introduces, and far finer
    # than every mistake this check exists to catch -- the collar that
    # prompted it measured 0 degrees against a required 90. A requirement
    # that wants a tighter angle says so in its own `tolerance`.
    if measurement.startswith("angle_between:"):
        return Q(0.5, "deg")
    return None


def _centre_of(quantity: Any) -> float:
    """The midpoint of a measured interval, as a plain number."""
    magnitude = getattr(quantity, "magnitude", quantity)
    if hasattr(magnitude, "lo") and hasattr(magnitude, "hi"):
        return (float(magnitude.lo) + float(magnitude.hi)) / 2.0
    return float(magnitude)


def _figures_with_a_proved_axis(
    component: Component, responses: Sequence[ParameterResponse]
) -> dict[str, str]:
    """Figure -> the axis a parameter carrying it is measured to drive.

    An extent claim carries a threshold and no parameter name, so the lookup
    is by figure. Where one exists it beats guessing by nearest match, and
    it is the difference between "25 mm is closest to x" and "the parameter
    whose value is 25 mm is the one that moves x".
    """
    try:
        values = dict(component.parameters.resolve().values)
    except Exception:  # noqa: BLE001 - a design that will not resolve is
        return {}     # already failing somewhere that says so properly
    return the_axis_each_figure_drives(responses, values)


def _check_dimensions_drive_the_part(
    responses: Sequence[ParameterResponse],
    evidence: EvidenceGraph,
    input_hash: str,
) -> list[GateResult]:
    """Every dimension the design declares must change the finished object.

    The strongest form of "the paperwork matches the part", and the one that
    needs no intent whatever. A parameter is already required to be
    *referenced* by the feature graph -- but being referenced is not the
    same as mattering. A dimension wired into a feature that is wholly
    buried inside another, or into a cut that removes nothing, is declared,
    checked by a requirement, reported as passing, and absent from the
    object.

    Proved by doing it: the parameter is nudged, the part is rebuilt, and
    nothing about it moves. Not a heuristic and not a name -- a measurement.

    A parameter that could not be probed is never counted here. A probe that
    did not run is not evidence that nothing happened, and accusing a design
    over a measurement Forge declined to take would be exactly the kind of
    confident emptiness this system exists to refuse.
    """
    probed = [r for r in responses if not r.skipped]
    if not probed:
        return []
    inert = [r for r in probed if r.drives_nothing]

    gate = Gate(
        identifier="GEOM_DIMENSIONS_DRIVE_THE_PART",
        claim="every dimension the design declares changes the finished part",
        comparison="at_most",
        threshold=Q(0),
        critical=True,
        rationale="A declared dimension that moves nothing is a number the "
        "document carries and the object does not have. A requirement bound "
        "to it reads the parameter table, finds the figure, and passes -- "
        "against a part the figure describes no part of.",
    )
    detail: dict[str, Any] = {
        "probed": len(probed),
        "response": [r.as_dict() for r in probed],
    }
    if inert:
        detail["hint"] = (
            ", ".join(f"`{r.parameter}`" for r in inert)
            + " changed nothing about the part when moved. Each was rebuilt "
            "with a different value and the object came out identical -- same "
            "volume, same extents. Either the feature it drives is consumed "
            "or buried by something built afterwards, or it removes material "
            "that was not there. Wire it to geometry that survives into the "
            "finished part, or drop the parameter: a dimension nothing can "
            "measure is not a dimension of this part."
        )
    node = gate.evaluate(
        Q(len(inert)),
        method=Method.EXACT_GEOMETRY,
        tool=TOOL_KERNEL,
        input_hashes=(input_hash,),
        limitations=(
            "each dimension was moved by a tenth of its value and the part "
            "rebuilt; a response below the measurement's own resolution "
            "counts as no response",
            "derived parameters, counts and angles are not probed and are "
            "not counted either way",
        ),
        detail=detail,
    )
    evidence.add(node)
    return [GateResult(gate, node)]


def _check_the_build_orientation(
    responses: Sequence[ParameterResponse],
    extents: Sequence[float],
    evidence: EvidenceGraph,
    input_hash: str,
) -> list[GateResult]:
    """Whether the part's thinnest declared dimension runs up the Z axis.

    The oldest unfixed failure in this system: a spacer whose plate was
    built in the wrong plane reported PASS on seven dimensional
    requirements, every one of them telling the truth. The document said the
    plate was 4 mm thick and it was -- sideways.

    Forge's own authoring guide states the convention this checks: "Z is up.
    A flat plate's thickness is its Z." That is not an inference about what
    the user wanted, it is an instruction Forge gave, and a design that
    contradicts it has contradicted something it was told.

    **Deliberately not critical, and that is the whole design of it.** The
    guide names the exception in the same breath -- "unless the part is
    genuinely a vertical web" -- and a vertical web is a real part that a
    blocking gate would refuse for being itself. So this reports and never
    refuses: it appears in every report, beside a verdict it cannot change,
    which is the honest weight for a convention with a legitimate exception.
    A person reading "the thinnest dimension runs along y" sees in one glance
    what seven passing checks could not tell them.

    It fires only on a part that is plate-like by measurement -- one
    dimension at most half of two others that run crosswise to it -- so a
    rod, a cube or a boss is never remarked on at all.
    """
    driving = {
        r.axis: r for r in responses
        if r.axis and not r.skipped
    }
    if len(driving) < 3 or len(extents) != 3:
        # Fewer than three dimensions each owning an axis: not a shape this
        # convention has anything to say about.
        return []

    # Which axis is thinnest is a fact about the OBJECT, read off the
    # measured bounding box. The first version of this took it from each
    # parameter's response instead -- how far the extent moved when the
    # dimension was nudged -- which is the size of the nudge and has nothing
    # to do with the size of the part. It made the verdict close to
    # arbitrary: a spacer 30 x 12 x 14 was called thin along y because y
    # happened to be nudged least.
    #
    # The response map answers the other half, and only the other half:
    # WHICH dimension owns that axis, so the hint can name it.
    sizes = {axis: float(extents["xyz".index(axis)]) for axis in driving}
    thinnest = min(sizes, key=lambda axis: sizes[axis])
    others = [sizes[a] for a in sizes if a != thinnest]
    plate_like = sizes[thinnest] * 2.0 <= min(others) if others else False

    gate = Gate(
        identifier="GEOM_BUILD_ORIENTATION",
        claim="the part's thinnest dimension runs up the Z axis",
        comparison="at_most",
        threshold=Q(0),
        critical=False,
        rationale="Z is up, by the convention the authoring guide states and "
        "the designer is given. A flat part built across it measures "
        "correctly on every dimension and is still the wrong part -- and "
        "prints standing on its edge.",
    )
    wrong = 1 if (plate_like and thinnest != "z") else 0
    detail: dict[str, Any] = {
        "plate_like": plate_like,
        "thinnest_axis": thinnest,
        "extent_mm": {a: round(sizes[a], 3) for a in sizes},
        "driven_by": {a: r.parameter for a, r in driving.items()},
    }
    if wrong:
        detail["hint"] = (
            f"the part measures {sizes[thinnest]:.2f} mm along {thinnest}, "
            f"its thinnest direction, driven by "
            f"`{driving[thinnest].parameter}` -- and that is not z. The part is "
            "plate-like, so by the convention the authoring guide states -- "
            "Z is up, a flat plate's thickness is its Z -- it is lying on "
            "its edge: it will measure correctly on every dimension and "
            "print standing up. Put the thinnest extent last in the `size` "
            "vector. If this really is a vertical web, it is right as it is "
            "and this note is the exception the guide names."
        )
    node = gate.evaluate(
        Q(wrong),
        method=Method.EXACT_GEOMETRY,
        tool=TOOL_KERNEL,
        input_hashes=(input_hash,),
        limitations=(
            "a convention with a legitimate exception, so this is reported "
            "and never blocks a release: a vertical web is a real part",
            "only remarked on for a plate-like part -- one dimension at most "
            "half of the two that run crosswise to it",
        ),
        detail=detail,
    )
    evidence.add(node)
    return [GateResult(gate, node)]


def _figure(threshold: Quantity | None) -> str:
    """A comparable key for a threshold: its magnitude and unit."""
    if threshold is None:
        return ""
    try:
        magnitude = threshold.magnitude
        centre = (
            (float(magnitude.lo) + float(magnitude.hi)) / 2.0
            if hasattr(magnitude, "lo") else float(magnitude)
        )
        return f"{centre:.9g}|{threshold.unit.symbol}"
    except Exception:  # noqa: BLE001 - an unusable threshold matches nothing
        return ""


def _the_extent_this_claim_is_really_about(
    measurement: str,
    comparison: str,
    threshold: Quantity | None,
    properties: Any,
    axis_of: Mapping[str, str] | None = None,
) -> tuple[Quantity | None, str]:
    """Bind an equality claim about size to the axis it is actually about.

    The requirements engineer writes its requirements before the design
    exists. The designer chooses the orientation afterwards and
    independently. So `bounding_box_x equals 25 mm`, written at that stage,
    is a claim about a coordinate frame nobody has fixed yet -- and the axis
    in it is not a statement, it is the only way the transport let the claim
    be written down. What the author meant, and all they were in a position
    to mean, is *the part is 25 mm across, somewhere*.

    Forge is not in that position. By the time this runs the part is built
    and measured, and binding a figure to an axis has stopped being a guess
    and become a lookup. So the claim is evaluated against the extent it is
    actually about: of the part's three, the one nearest the figure claimed.

    This is not a relaxation, and the distinction matters. The claim still
    has to be true of the finished object: a part with no 25 mm extent fails
    exactly as before, and a part built at ten times its size fails on every
    one. What is dropped is only the assertion about which of three
    interchangeable labels the figure lands on -- the part of the claim its
    author could not have known and did not mean.

    Only `equals`. A bound is different and its axis is real: "it must stand
    no taller than 32 mm" is about height, Z is up by convention, and the
    author both knew that and meant it. Read orientation-free, the same
    sentence would be satisfied by the part's thinnest direction, which is
    not what anybody said. Bounds are left exactly alone.

    Stated for a strong model too, because it is not a crutch: no model can
    know an orientation that has not been chosen yet. A better model writes
    a better claim; it still cannot see the future. This removes the guess
    for all of them.
    """
    if not measurement.startswith("bounding_box_"):
        return None, ""
    if comparison != "equals" or threshold is None:
        return None, ""
    try:
        extents = properties.bounding_box_size()
    except Exception:  # noqa: BLE001 - a measurement is never worth a crash
        return None, ""
    named = {"bounding_box_x": 0, "bounding_box_y": 1, "bounding_box_z": 2}
    axis = named.get(measurement)
    if axis is None or len(extents) != 3:
        return None, ""

    def midpoint(quantity: Any) -> float | None:
        magnitude = getattr(quantity, "magnitude", None)
        if hasattr(magnitude, "lo") and hasattr(magnitude, "hi"):
            return (float(magnitude.lo) + float(magnitude.hi)) / 2.0
        try:
            return float(magnitude)
        except (TypeError, ValueError):
            return None

    try:
        wanted = threshold.to(extents[0].unit).magnitude.midpoint
    except Exception:  # noqa: BLE001 - a different dimension cannot match
        return None, ""

    # The axis named is right when the part is that size along it: nothing
    # to read again. A parameter that happens to carry the same figure and
    # drives another axis -- a boss set 20 mm off centre, on a part 20 mm
    # wide -- is not this claim's, and rebinding to it failed a part that
    # met the claim exactly as written.
    named_extent = extents[axis]
    named_centre = midpoint(named_extent)
    spread = getattr(getattr(named_extent, "magnitude", None), "width", 0.0)
    try:
        spread = float(spread or 0.0)
    except (TypeError, ValueError):
        spread = 0.0
    if named_centre is not None and abs(named_centre - wanted) <= max(
            0.05, spread / 2.0 + 1e-9):
        return None, ""

    # Where a parameter carrying this figure was *measured* to drive an
    # axis, that is the answer and there is nothing to choose between.
    # Nearest-match is the fallback for a figure no parameter carries.
    proved = (axis_of or {}).get(f"{wanted:.6g}", "")
    if proved:
        best = "xyz".index(proved)
        how = "the parameter carrying this figure was measured to drive it"
    else:
        distances: list[tuple[float, int]] = []
        for index, extent in enumerate(extents):
            centre = midpoint(extent)
            if centre is None:
                return None, ""
            distances.append((abs(centre - wanted), index))
        distances.sort()
        best = distances[0][1]
        how = "of the three extents it is the one this figure is about"
    if best == axis:
        return None, ""

    letters = "xyz"
    return extents[best], (
        f"read as a claim about the part's size rather than about an axis: "
        f"`{measurement}` names {letters[axis]}, and {how}: {letters[best]}. "
        f"The requirements were "
        "written before the design existed, so which axis a dimension lands "
        "on was not something their author could know; the size claimed is "
        "still checked against the finished part, and a part that is not "
        "that size in any direction still fails"
    )


def _tolerance_you_can_actually_measure(
    declared: Quantity | None, measured: Quantity | None
) -> tuple[Quantity | None, str]:
    """Widen an equality tolerance to the precision of the measurement.

    A collar built to exactly 25 mm across measured `24.8145 +/- 0.205078 mm`
    -- a rigorous octree enclosure, correct, and 0.41 mm wide. It was compared
    against `== 25 mm` with the default tolerance of 0.05 mm, and reported
    INCONCLUSIVE. It would have reported INCONCLUSIVE at any diameter, because
    an interval 0.41 mm wide cannot fit inside a band 0.1 mm wide. The gate
    was asking a question its own instrument could not answer.

    0.05 mm is the release threshold the build specification names for golden
    dimensions, and it is right for a number the document *declares*: those
    resolve exactly, the interval has zero width, and nothing here changes
    them. It is wrong for a quantity that was *measured*, where asserting
    equality to a finer precision than the measurement is not strictness, it
    is a guaranteed non-answer.

    So the tolerance becomes the wider of the two: what the requirement asks
    for, or what the measurement can resolve. The comparison stays a rigorous
    three-valued one -- a part measured at 15 mm against a 25 mm claim still
    FAILS, and one whose interval straddles the band is still INCONCLUSIVE.
    What changes is that a correct part can now be shown to be correct.

    Widening is never silent: the caller records the returned sentence as a
    limitation, so nobody reads the PASS as a 0.05 mm check.
    """
    if measured is None or declared is None:
        return declared, ""
    magnitude = getattr(measured, "magnitude", None)
    if not (hasattr(magnitude, "lo") and hasattr(magnitude, "hi")):
        return declared, ""
    try:
        width = abs(float(magnitude.hi) - float(magnitude.lo))
        if width <= 0.0:
            return declared, ""
        precision = Q(width, measured.unit.symbol).to(declared.unit)
        if precision.magnitude.midpoint <= declared.magnitude.midpoint:
            return declared, ""
        # Never past what a measurement can honestly be said to have
        # resolved: a 1 mm, or 5 % of the figure itself. An octree that
        # could not close in on a cut face reported a 25 mm dome as
        # "38.6 +/- 13.9 mm", and widened to that, equality passed 25 and
        # 38 alike. Wider than this, the gate stays as asked and the
        # straddling interval reports INCONCLUSIVE -- which is what it is.
        centre = abs(float(measured.magnitude.midpoint))
        if width > max(1.0, 0.05 * centre) * 2:
            return declared, ""
    except Exception:  # noqa: BLE001 - a tolerance is never worth a crash
        return declared, ""
    return precision, (
        f"the requirement's tolerance of {declared} is finer than this "
        f"measurement resolves ({precision}), so equality was judged at the "
        "measurement's own precision; a tighter check would report "
        "INCONCLUSIVE whatever the part measured"
    )


__all__ = [
    "LoadCase",
    "the_bore_found_material",
    "VerificationReport",
    "verify_component",
    "TOOL_KERNEL",
    "TOOL_MEASURE",
    "TOOL_MESH",
    "TOOL_ANALYSIS",
]
