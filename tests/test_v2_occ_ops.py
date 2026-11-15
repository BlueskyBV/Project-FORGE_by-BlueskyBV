"""V2 stage 3: each operation built, named and held to what it must do (forge_occ.ops, forge_occ.aftercheck; docs/V2-stage3.md, 4, 7, 8, 9).

For each operation: the volume its formula gives (exactly where one exists,
or the bounds 8.2 sets), the names it gives its faces, and its after-check
made to fail on purpose and caught. The traps of section 4, each made to
happen: a shell thicker than the part, a 9.9 mm fillet on a 10 mm box, a
fuse of solids that don't touch, a cut whose tool misses, touching boxes
fused, OpenCascade's one exception class at a step's boundary, a cone with
equal radii. Booleans' flags (a warning allowed by name, any other refused,
an error), junctions and lumps; bends (a prism zone, a mapped one, ``hold``,
a chain); references (every failure of ``match``, ``where``, tangent
closure, a face an earlier step buried).
"""

from __future__ import annotations

import math
import unittest
from dataclasses import replace
from typing import Any
from unittest import mock

import numpy as np
from v2_occ import converted, needs_occ, v2_document, zoo

try:
    from forge_occ import aftercheck, make
    from forge_occ.aftercheck import blend_bounds, blend_section, distances_to
    from forge_occ.backend import OccBackend
    from forge_occ.errors import (
        AfterCheckError,
        BooleanFlagError,
        DesignError,
        OccError,
        OperationError,
        RefError,
    )
    from forge_occ.geom import Motion
    from forge_occ.names import History, Name
    from forge_occ.occt import (
        boundary,
        edges,
        faces,
        plane_of,
        solids,
        vertices,
        volume,
    )
    from forge_occ.ops import bend as bend_module
    from forge_occ.ops import modifiers
    from forge_occ.view import BrepView
    from OCP.BRep import BRep_Tool
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.BRepPrimAPI import (
        BRepPrimAPI_MakeBox,
        BRepPrimAPI_MakeCone,
        BRepPrimAPI_MakeSphere,
    )
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS
except ImportError:  # no OpenCascade here: every class below is skipped
    pass


# --- documents --------------------------------------------------------------------------


def mm(value: float) -> dict[str, Any]:
    return {"magnitude": value, "unit": "mm"}


def deg(value: float) -> dict[str, Any]:
    return {"magnitude": value, "unit": "deg"}


def at(*value: float) -> dict[str, Any]:
    return {"vector": list(value), "unit": "mm"}


def step(
    identifier: str, op: str, inputs: tuple[str, ...] = (), **params: Any
) -> dict[str, Any]:
    return {"id": identifier, "op": op, "inputs": list(inputs), "params": params}


def box(identifier: str, size: tuple[float, float, float], origin: tuple[float, float, float] = (0, 0, 0),
        **more: Any) -> dict[str, Any]:  # fmt: skip
    return {
        **step(identifier, "box", size=at(*size), origin=at(*origin), **more),
        "role": identifier,
    }


def built(*steps: dict[str, Any]) -> Any:
    """The part the steps build (the last is the part)."""
    document = v2_document({"schema_version": "2.0.0", "document_id": "t", "project_id": "t", "revision": 1,
                            "name": "t", "components": [{"id": "part", "steps": list(steps)}]})  # fmt: skip
    return OccBackend().build(document, "part")


def roles(result: Any, step_id: str) -> set[str]:
    return {n.role for n in result.names.every() if n.step == step_id}


def trace(result: Any, step_id: str) -> Any:
    return next(t for t in result.traces if t.step == step_id)


PLANE = step("plane", "datum_plane", base="XY")


def extruded(profile: dict[str, Any], **params: Any) -> Any:
    return built(PLANE, profile, step("part", "extrude", (profile["id"],), **params))


def rectangle(width: float, height: float, **more: Any) -> dict[str, Any]:
    return step(
        "outline",
        "profile_rectangle",
        ("plane",),
        width=mm(width),
        height=mm(height),
        **more,
    )


# --- primitives ------------------------------------------------------------------------


@needs_occ
class Primitives(unittest.TestCase):
    def test_a_box_and_its_names(self) -> None:
        result = built(box("part", (40, 30, 6)))
        self.assertAlmostEqual(volume(result.shape), 7200.0, delta=1e-9)
        self.assertEqual(
            roles(result, "part"),
            {"x_min", "x_max", "y_min", "y_max", "z_min", "z_max"},
        )

    def test_a_box_rounded_all_round_is_its_offset_core(self) -> None:
        a, b, c, r = 40.0, 30.0, 10.0, 2.0
        result = built(box("part", (a, b, c), edge_radius=mm(r), edges="all"))
        x, y, z = a - 2 * r, b - 2 * r, c - 2 * r
        expected = (
            x * y * z
            + 2 * r * (x * y + y * z + x * z)
            + math.pi * r * r * (x + y + z)
            + 4 / 3 * math.pi * r**3
        )
        self.assertAlmostEqual(volume(result.shape), expected, delta=expected * 1e-9)

    def test_a_cylinder_on_any_axis(self) -> None:
        result = built(
            step(
                "part",
                "cylinder",
                diameter=mm(10),
                height=mm(20),
                axis=[1, 1, 0],
                origin=at(1, 2, 3),
            )
        )
        self.assertAlmostEqual(volume(result.shape), math.pi * 25.0 * 20.0, delta=1e-8)
        self.assertEqual(roles(result, "part"), {"lateral", "base", "top"})

    def test_a_cone_its_apex_and_equal_radii(self) -> None:
        for top, expected in ((4.0, math.pi * 10 * (25 + 10 + 4) / 3), (0.0, math.pi * 10 * 25 / 3),
                              (10.0, math.pi * 25 * 10)):  # fmt: skip
            with self.subTest(top=top):
                result = built(
                    step(
                        "part",
                        "cone",
                        bottom_diameter=mm(10),
                        top_diameter=mm(top),
                        height=mm(10),
                    )
                )
                self.assertAlmostEqual(volume(result.shape), expected, delta=1e-8)
        # OpenCascade's own cone refuses equal radii: the step builds a cylinder instead (section 4).
        with self.assertRaises(OccError), boundary("a cone"):
            BRepPrimAPI_MakeCone(5.0, 5.0, 10.0).Shape()

    def test_a_sphere_a_ring_and_a_wedge(self) -> None:
        self.assertAlmostEqual(
            volume(built(step("part", "sphere", diameter=mm(12))).shape),
            288 * math.pi,
            delta=1e-8,
        )
        ring = built(step("part", "torus", diameter=mm(30), tube_diameter=mm(6)))
        self.assertAlmostEqual(volume(ring.shape), 2 * math.pi**2 * 15 * 9, delta=1e-8)
        wedge = built(step("part", "wedge", size=at(20, 10, 6), slope="+x"))
        self.assertAlmostEqual(volume(wedge.shape), 600.0, delta=1e-9)
        self.assertIn("slope", roles(wedge, "part"))

    def test_a_ring_thicker_than_itself_is_refused(self) -> None:
        with self.assertRaises(DesignError) as caught:
            built(step("part", "torus", diameter=mm(10), tube_diameter=mm(10)))
        self.assertEqual(caught.exception.detail["step"], "part")
        self.assertEqual(caught.exception.detail["op"], "torus")


# --- sweeps ----------------------------------------------------------------------------


@needs_occ
class Sweeps(unittest.TestCase):
    def test_an_extrusion_is_its_area_times_its_length(self) -> None:
        for mode, (lo, hi) in (
            ("normal", (0.0, 7.0)),
            ("symmetric", (-3.5, 3.5)),
            ("reverse", (-7.0, 0.0)),
        ):
            with self.subTest(mode):
                result = extruded(
                    rectangle(20, 10, corner_radius=mm(2)), distance=mm(7), mode=mode
                )
                self.assertAlmostEqual(
                    volume(result.shape), (200 - (4 - math.pi) * 4) * 7, delta=1e-8
                )
                box_ = BrepView(result.shape).bounds()
                self.assertAlmostEqual(box_.lo[2], lo, delta=1e-7)
                self.assertAlmostEqual(box_.hi[2], hi, delta=1e-7)
                self.assertTrue(
                    {"start_face", "end_face", "side"} <= roles(result, "part")
                )

    def test_a_drafted_extrusion(self) -> None:
        t, h = math.tan(math.radians(5)), 5.0
        inward = extruded(rectangle(10, 10), distance=mm(h), draft_angle=deg(5))
        exact = (
            100 * h - 40 * t * h * h / 2 + 4 * t * t * h**3 / 3
        )  # each side in by t·s, corners mitred
        self.assertAlmostEqual(volume(inward.shape), exact, delta=exact * 1e-9)
        outward = extruded(rectangle(10, 10), distance=mm(h), draft_angle=deg(-5))
        steiner = (
            100 * h + 40 * t * h * h / 2 + math.pi * t * t * h**3 / 3
        )  # convex: rounded corners, Steiner's
        self.assertAlmostEqual(volume(outward.shape), steiner, delta=steiner * 1e-9)

    def test_rounded_ends_take_no_more_than_their_blends_move(self) -> None:
        result = extruded(rectangle(20, 10), distance=mm(6), end_radius=mm(1))
        r, perimeter = 1.0, 60.0
        self.assertLess(volume(result.shape), 1200.0)
        # Each end's rim loses its fillet's section along it; the corners lose less (their blends overlap).
        self.assertGreater(
            volume(result.shape),
            1200.0 - 2 * perimeter * r * r * (1 - math.pi / 4) - 1e-9,
        )
        self.assertIn("round", roles(result, "part"))

    def test_a_revolve_is_as_pappus_says(self) -> None:
        axis = step("axis", "datum_axis", origin=at(0, 0, 0), direction=[0, 0, 1])
        plane = step("plane", "datum_plane", base="XZ")
        outline = step("outline", "profile_rectangle", ("plane",), width=mm(4), height=mm(10), center_u=mm(12),
                       center_v=mm(5))  # fmt: skip
        result = built(
            plane,
            axis,
            outline,
            step("part", "revolve", ("outline", "axis"), angle=deg(90)),
        )
        self.assertAlmostEqual(volume(result.shape), 40 * 12 * math.pi / 2, delta=1e-8)
        self.assertEqual(roles(result, "part"), {"side", "start_face", "end_face"})

    def test_a_coil_is_its_wires_section_times_its_length(self) -> None:
        result = built(
            step(
                "part",
                "coil",
                diameter=mm(20),
                wire_diameter=mm(2),
                pitch=mm(4),
                turns=3,
            )
        )
        expected = math.pi * 1.0 * 3 * math.hypot(2 * math.pi * 10, 4)
        self.assertAlmostEqual(volume(result.shape), expected, delta=expected * 1e-6)
        self.assertEqual(roles(result, "part"), {"surface", "start_face", "end_face"})

    def test_a_loft_of_two_circles_is_a_frustum(self) -> None:
        low = step("low", "profile_circle", ("plane",), diameter=mm(20))
        high_plane = step("high_plane", "datum_plane", base="XY", offset=mm(10))
        high = step("high", "profile_circle", ("high_plane",), diameter=mm(10))
        result = built(
            PLANE, low, high_plane, high, step("part", "loft", ("low", "high"))
        )
        self.assertAlmostEqual(
            volume(result.shape), math.pi * 10 * (100 + 50 + 25) / 3, delta=1e-6
        )

    def test_a_sweep_round_a_bend(self) -> None:
        section = step("section", "profile_circle", ("plane",), diameter=mm(2))
        path = {"points": [[0, 0, 0], [0, 0, 30], [30, 0, 30]], "unit": "mm"}
        result = built(
            PLANE,
            section,
            step("part", "sweep", ("section",), path=path, bend_radius=mm(5)),
        )
        # The runs cut back by the radius at the corner, and a quarter circle of radius 5 between them.
        length = 25 + 25 + 5 * math.pi / 2
        self.assertAlmostEqual(volume(result.shape), math.pi * length, delta=1e-6)


# --- booleans ----------------------------------------------------------------------------


def outlined(points: list[list[float]]) -> dict[str, Any]:
    return step(
        "outline",
        "profile_outline",
        ("plane",),
        points={"points": points, "unit": "mm"},
    )


#: A plate 30 x 20 with a bite of radius 9 out of the middle of its top edge.
BITTEN = [[0, 0], [30, 0], [30, 20], [24, 20], [6, 20, 15, 11], [0, 20], [0, 0]]
#: A knob's half outline: a stem, and a disc whose rim is rounded 2 above and below, tangent to its faces.
KNOB = [[0, 0], [4, 0], [4, 6], [12, 6], [14, 8, 12 + math.sqrt(2), 8 - math.sqrt(2)], [14, 10],
        [12, 12, 12 + math.sqrt(2), 10 + math.sqrt(2)], [0, 12], [0, 0]]  # fmt: skip


@needs_occ
class Outlines(unittest.TestCase):
    """A v2 outline of straight sides and true arcs, extruded and turned (docs/V2-stage4.md, 6.5)."""

    def test_extruded_its_volume_is_its_area_times_its_length(self) -> None:
        result = extruded(outlined(BITTEN), distance=mm(8))
        self.assertAlmostEqual(
            volume(result.shape), (600 - math.pi * 81 / 2) * 8, delta=1e-8
        )
        self.assertTrue({"start_face", "end_face", "side"} <= roles(result, "part"))

    def test_one_that_crosses_itself_is_refused(self) -> None:
        # Two triangles meeting where its sides cross: its face's area, or the solid made of it, is refused.
        bow = [[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]]
        with self.assertRaises(OccError):
            extruded(outlined(bow), distance=mm(2))

    def test_turned_its_flat_ends_are_its_top_and_base(self) -> None:
        axis = step(
            "axis",
            "datum_axis",
            origin=at(0, 0, 0),
            direction={"vector": [0, 0, 1], "unit": ""},
        )
        result = built(
            PLANE,
            outlined(KNOB),
            axis,
            step("part", "revolve", ("outline", "axis"), angle=deg(360)),
        )
        found = {}
        for face, names in result.names.items():
            plane = plane_of(face)
            for name in names:
                if name.role in ("top", "base"):
                    found[name.role] = plane
        self.assertEqual(set(found), {"top", "base"})
        top, base = found["top"], found["base"]
        assert top is not None and base is not None
        self.assertEqual((top[0][2], top[1]), (12.0, (0.0, 0.0, 1.0)))
        # The base's plane is drawn left-handed by the revolve: its outward normal is still down.
        self.assertEqual((base[0][2], base[1]), (0.0, (0.0, 0.0, -1.0)))
        self.assertEqual(roles(result, "part"), {"side", "top", "base"})


@needs_occ
class Booleans(unittest.TestCase):
    def test_touching_boxes_fused_are_one_box_of_six_faces(self) -> None:
        result = built(
            box("a", (10, 10, 10)),
            box("b", (10, 10, 10), (10, 0, 0)),
            step("part", "union", ("a", "b")),
        )
        self.assertEqual(len(faces(result.shape)), 6)
        self.assertAlmostEqual(volume(result.shape), 2000.0, delta=1e-9)
        # The merged faces keep both operands' names.
        top = [n for f, n in result.names.items() if Name("a", "z_max") in n]
        self.assertEqual(len(top), 1)
        self.assertIn(Name("b", "z_max"), top[0])

    def test_a_fuse_of_solids_that_dont_touch_is_two_solids_and_says_so(self) -> None:
        result = built(
            box("a", (10, 10, 10)),
            box("b", (10, 10, 10), (20, 0, 0)),
            step("part", "union", ("a", "b")),
        )
        self.assertEqual(trace(result, "part").solids, 2)
        self.assertAlmostEqual(volume(result.shape), 2000.0, delta=1e-9)

    def test_a_cut_whose_tool_misses_removed_nothing(self) -> None:
        result = built(
            box("a", (10, 10, 10)),
            box("b", (5, 5, 5), (30, 0, 0)),
            step("part", "subtract", ("a", "b")),
        )
        self.assertAlmostEqual(volume(result.shape), 1000.0, delta=1e-9)
        self.assertTrue(
            any("removed nothing" in n for n in trace(result, "part").notes)
        )

    def test_a_cut_that_splits_a_part_leaves_lumps(self) -> None:
        result = built(
            box("a", (30, 10, 10)),
            box("b", (10, 20, 20), (10, -5, -5)),
            step("part", "subtract", ("a", "b")),
        )
        self.assertEqual(trace(result, "part").solids, 2)
        self.assertAlmostEqual(volume(result.shape), 2000.0, delta=1e-9)

    def test_a_blended_junction_adds_material_in_the_crease(self) -> None:
        plate = box("plate", (40, 40, 5))
        boss = {
            **step(
                "boss", "cylinder", diameter=mm(10), height=mm(10), origin=at(20, 20, 5)
            ),
            "role": "boss",
        }
        plain = built(plate, boss, step("part", "union", ("plate", "boss")))
        blended = built(
            plate, boss, step("part", "union", ("plate", "boss"), blend_radius=mm(2))
        )
        added = volume(blended.shape) - volume(plain.shape)
        # A rolling ball of 2 mm round a boss of radius 5: its section r²(1 - π/4) turned about the axis at
        # its centroid's radius, 5 + r(10 - 3π)/(3(4 - π)).
        section = 4 * (1 - math.pi / 4)
        reach = 5 + 2 * (10 - 3 * math.pi) / (3 * (4 - math.pi))
        self.assertAlmostEqual(added, section * 2 * math.pi * reach, delta=1e-6)
        self.assertIn("round", roles(blended, "part"))

    def test_an_allowed_warning_passes_and_any_other_is_refused(self) -> None:
        # A box standing on a sphere's pole: the pave filler can't orient a face it only touches.
        ball = BRepPrimAPI_MakeSphere(5.0).Shape()
        lid = BRepPrimAPI_MakeBox(gp_Pnt(-5, -5, 5), 10.0, 10.0, 2.0).Shape()
        done = make.boolean("union", [ball], [lid])
        for warning in done.warnings:
            self.assertIn(warning, make.ALLOWED_WARNINGS)
        if done.warnings:
            with (
                mock.patch.dict(make.ALLOWED_WARNINGS, clear=True),
                self.assertRaises(BooleanFlagError),
            ):
                make.boolean("union", [ball], [lid])

    def test_an_error_flag_fails_the_step(self) -> None:
        real = make.BOPAlgo_PaveFiller

        class Failing(real):  # type: ignore[misc, valid-type]
            def HasErrors(self) -> bool:  # noqa: N802 - OpenCascade's interface
                return True

        with (
            mock.patch.object(make, "BOPAlgo_PaveFiller", Failing),
            self.assertRaises(BooleanFlagError),
        ):
            make.boolean("union", [BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()],
                         [BRepPrimAPI_MakeBox(gp_Pnt(0.5, 0, 0), 1.0, 1.0, 1.0).Shape()])  # fmt: skip

    def test_a_boolean_leaves_its_arguments_as_they_were(self) -> None:
        a = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
        b = BRepPrimAPI_MakeBox(gp_Pnt(5, 5, 5), 10.0, 10.0, 10.0).Shape()
        before = [BRep_Tool.Tolerance_s(TopoDS.Vertex(v)) for v in vertices(a)]
        make.boolean("union", [a], [b])
        self.assertEqual(
            [BRep_Tool.Tolerance_s(TopoDS.Vertex(v)) for v in vertices(a)], before
        )


# --- fillets, chamfers and their bounds ----------------------------------------------------


def _top_edges(count: tuple[int, int] = (4, 4), **where: Any) -> dict[str, Any]:
    query: dict[str, Any] = {
        "of": {"created_by": "body", "role": "z_max"},
        "match": {"count": list(count)},
    }
    if where:
        query["where"] = where
    return query


@needs_occ
class FilletsAndChamfers(unittest.TestCase):
    def test_one_edge_moves_exactly_its_section_along_it(self) -> None:
        edge = {"between": [{"created_by": "body", "role": "z_max"}, {"created_by": "body", "role": "x_max"}],
                "match": {"count": [1, 1]}}  # fmt: skip
        body = box("body", (40, 30, 10))
        fillet = built(
            body, step("part", "fillet", ("body",), radius=mm(2), edges=edge)
        )
        self.assertAlmostEqual(
            12000 - volume(fillet.shape), 30 * 4 * (1 - math.pi / 4), delta=1e-8
        )
        chamfer = built(
            body, step("part", "chamfer", ("body",), distance=mm(2), edges=edge)
        )
        self.assertAlmostEqual(12000 - volume(chamfer.shape), 30 * 2.0, delta=1e-8)
        self.assertIn("round", roles(fillet, "part"))
        self.assertIn("bevel", roles(chamfer, "part"))

    def test_a_crease_gains_what_a_ridge_loses(self) -> None:
        # An L: a plate and a wall standing on it; the inside edge between them rounded.
        plate, wall = box("plate", (40, 30, 5)), box("wall", (5, 30, 20), (0, 0, 5))
        inside = {"between": [{"created_by": "plate", "role": "z_max"}, {"created_by": "wall", "role": "x_max"}],
                  "match": {"count": [1, 1]}}  # fmt: skip
        result = built(plate, wall, step("body", "union", ("plate", "wall")),
                       step("part", "fillet", ("body",), radius=mm(3), edges=inside))  # fmt: skip
        self.assertAlmostEqual(
            volume(result.shape) - (6000 + 3000), 30 * 9 * (1 - math.pi / 4), delta=1e-8
        )

    def test_the_bounds_hold_and_tell_ridges_from_creases(self) -> None:
        shape = BRepPrimAPI_MakeBox(40.0, 30.0, 10.0).Shape()
        top = [
            e
            for e in edges(shape)
            if BrepView(shape).bounds().hi[2] - 1e-9 <= _middle(e)[2]
        ]
        self.assertEqual(len(top), 4)
        removed, added = blend_bounds(shape, top, [2.0] * 4, bevel=False)
        self.assertEqual(added, 0.0)
        made = make.round_edges(shape, top, 2.0)
        self.assertLessEqual(volume(shape) - volume(made.shape), removed)
        self.assertGreater(volume(shape) - volume(made.shape), 0.0)
        self.assertAlmostEqual(
            blend_section(math.pi / 2, 2.0, bevel=False),
            4 * (1 - math.pi / 4),
            places=12,
        )
        self.assertAlmostEqual(
            blend_section(math.pi / 3, 2.0, bevel=True),
            4 * math.sin(math.pi / 3) / 2,
            places=12,
        )

    def test_tangent_edges_are_closed_over_and_said(self) -> None:
        outline = rectangle(20, 10, corner_radius=mm(3))
        body = step("body", "extrude", ("outline",), distance=mm(6))
        # One straight edge chosen: the arcs and edges running on from it smoothly are added, and the
        # count (checked after) allows them.
        one = {"of": {"created_by": "body", "role": "end_face"}, "where": {"kind": "line", "axis": [1, 0, 0],
               "side": "max_y"}, "match": {"count": [1, 8]}}  # fmt: skip
        result = built(
            PLANE,
            outline,
            body,
            step("part", "fillet", ("body",), radius=mm(1), edges=one),
        )
        self.assertTrue(
            any(
                "meet the chosen ones smoothly" in n
                for n in trace(result, "part").notes
            )
        )
        self.assertGreaterEqual(
            sum(1 for _, n in result.names.items() if Name("part", "round") in n), 8
        )

    def test_a_fillet_too_big_for_its_box_is_refused(self) -> None:
        # Section 4: OpenCascade calls a 9.9 mm fillet on a 10 mm box done; it is invalid and larger than the box.
        with self.assertRaises(OccError) as caught:
            built(
                box("body", (10, 10, 10)),
                step("part", "fillet", ("body",), radius=mm(9.9), edges=_top_edges()),
            )
        self.assertIn("invalid", caught.exception.message)
        self.assertEqual(caught.exception.detail["step"], "part")

    def test_a_fillet_that_moves_volume_the_wrong_way_is_caught(self) -> None:
        real = modifiers.round_edges

        def swelling(shape: Any, chosen: Any, size: Any, *, bevel: bool = False) -> Any:
            made = real(shape, chosen, size, bevel=bevel)
            # A block stood on top: more than the box had, where a fillet of ridges can only take away.
            bigger = BRepAlgoAPI_Fuse(
                made.shape,
                BRepPrimAPI_MakeBox(gp_Pnt(10, 10, 9), 10.0, 10.0, 10.0).Shape(),
            ).Shape()
            return replace(made, shape=bigger, history=History(make._Unchanged()))

        with (
            mock.patch.object(modifiers, "round_edges", swelling),
            self.assertRaises(AfterCheckError),
        ):
            built(
                box("body", (40, 30, 10)),
                step("part", "fillet", ("body",), radius=mm(2), edges=_top_edges()),
            )

    def test_a_fillet_that_made_no_face_is_caught(self) -> None:
        real = modifiers.round_edges

        def nothing(shape: Any, chosen: Any, size: Any, *, bevel: bool = False) -> Any:
            made = real(shape, chosen, size, bevel=bevel)
            return replace(made, shape=shape, history=History(make._Unchanged()))

        with (
            mock.patch.object(modifiers, "round_edges", nothing),
            self.assertRaises(AfterCheckError) as caught,
        ):
            built(
                box("body", (40, 30, 10)),
                step("part", "fillet", ("body",), radius=mm(2), edges=_top_edges()),
            )
        self.assertIn("made no face", caught.exception.message)


def _middle(edge: Any) -> Any:
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    curve = BRepAdaptor_Curve(TopoDS.Edge(edge))
    p = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2.0)
    return (p.X(), p.Y(), p.Z())


# --- letters ---------------------------------------------------------------------------------


def _letters(text: str, mode: str = "engrave", *, height: float = 5.0, depth: float = 0.5,
             origin: tuple[float, float, float] = (20, 10, 5), up: tuple[float, float, float] = (0, 1, 0),
             right: tuple[float, float, float] = (1, 0, 0)) -> dict[str, Any]:  # fmt: skip
    return step("part", "text", ("body",), text=text, height=mm(height), origin=at(*origin),
                up={"vector": list(up)}, right={"vector": list(right)}, depth=mm(depth), mode=mode)  # fmt: skip


def _ink_area(text: str, height: float) -> float:
    """The letters' area, the judge's way: Green's theorem round the region's own edge (each stretch with the letters on its side)."""
    from forge_checks.letters import Ink

    total = 0.0
    for edge in Ink.of(text, height).edges:
        (x0, y0), (x1, y1), (x2, y2) = edge.q
        share = (
            2 * (x0 * y1 - y0 * x1) + 2 * (x1 * y2 - y1 * x2) + (x0 * y2 - y0 * x2)
        ) / 6
        total += edge.side * share
    return total


@needs_occ
class Letters(unittest.TestCase):
    """``text``: a line of letters in the pinned font, engraved or embossed (docs/V2-stage4.md, 7.1)."""

    def test_engraved_they_take_their_area_times_their_depth(self) -> None:
        # The cedilla overlaps the C, and the ampersand crosses itself: the region is their nonzero winding.
        for words in ("FORGE", "Ç&j"):
            with self.subTest(words=words):
                result = built(box("body", (40, 20, 5)), _letters(words))
                taken = 40 * 20 * 5 - volume(result.shape)
                self.assertAlmostEqual(taken, _ink_area(words, 5.0) * 0.5, delta=1e-6)
                self.assertTrue(
                    {"letter_wall", "letter_floor"} <= roles(result, "part")
                )
                self.assertNotIn("letter_top", roles(result, "part"))

    def test_embossed_they_add_it(self) -> None:
        result = built(box("body", (40, 20, 5)), _letters("V2", "emboss", depth=0.4))
        added = volume(result.shape) - 40 * 20 * 5
        self.assertAlmostEqual(added, _ink_area("V2", 5.0) * 0.4, delta=1e-6)
        self.assertTrue({"letter_wall", "letter_top"} <= roles(result, "part"))

    def test_they_read_the_right_way_round_on_any_face(self) -> None:
        # On the box's -y face: up along z, outward -y, so right is up x out = +x. The F's stem is at the left.
        result = built(
            box("body", (40, 20, 10)),
            _letters("F", origin=(20, 0, 5), up=(0, 0, 1), right=(1, 0, 0), height=6.0),
        )
        floors = [
            face
            for face, names in result.names.items()
            if any(n.role == "letter_floor" for n in names)
        ]
        self.assertTrue(floors)
        for face in floors:
            plane = plane_of(face)
            assert plane is not None
            self.assertAlmostEqual(plane[0][1], 0.5, delta=1e-9)
            self.assertEqual(plane[1], (0.0, -1.0, 0.0))
        from forge_checks.view import Side
        from forge_spec.font import ADVANCES, CAP_HEIGHT

        # In the F's stem (188 to 573 font units along, below its crossbars), and the same point mirrored in the line.
        scale = 6.0 / CAP_HEIGHT
        stem, low = 20 - (ADVANCES["F"] / 2 - 380) * scale, 2 + 300 * scale
        sides = BrepView(result.shape).classify(
            np.array([[stem, 0.25, low], [40 - stem, 0.25, low]])
        )
        self.assertEqual(list(sides), [Side.OUT, Side.IN])

    def test_every_letter_s_region_is_the_judge_s(self) -> None:
        # Each letter alone (one contour or many), and runs whose letters touch, overlap or cross.
        from forge_occ.ops.letters import _area, letters_region
        from forge_spec.font import ADVANCES

        runs = ["__", "——", "fi", "ff", "///", "%%", "©®", "@@", "ÇÇ", "....", "||", "~~", "88", "ØØ"]  # fmt: skip
        runs.append("Hello, World!")
        for words in [*ADVANCES, *runs]:
            with self.subTest(words=words):
                region, _ = letters_region(words, 7.0, (0, 0, 0), (0, 1, 0), (1, 0, 0))
                expected = _ink_area(words, 7.0)
                self.assertAlmostEqual(
                    sum(_area(f) for f in region),
                    expected,
                    delta=1e-7 * max(1.0, expected),
                )

    def test_spaces_alone_leave_the_part_as_it_was(self) -> None:
        result = built(box("body", (40, 20, 5)), _letters("   "))
        self.assertAlmostEqual(volume(result.shape), 4000.0, delta=1e-9)

    def test_what_is_refused(self) -> None:
        for bad, expected in (
            (_letters("FORGE\u0416"), "no such letters"),
            (_letters("FORGE", up=(0, 1, 0), right=(1, 1, 0)), "square"),
            (_letters("FORGE", depth=0.0), "a height and a depth"),
        ):
            with self.subTest(expected=expected), self.assertRaises(OccError) as caught:
                built(box("body", (40, 20, 5)), bad)
            self.assertIn(expected, str(caught.exception))

    def test_letters_that_take_more_than_their_prism_are_caught(self) -> None:
        from forge_occ.ops import letters as letters_module

        real = letters_module.boolean
        calls = []

        def deeper(kind: str, shapes: Any, tools: Any, **more: Any) -> Any:
            made = real(kind, shapes, tools, **more)
            calls.append(kind)
            if kind != "subtract" or len(calls) > 1:
                return made
            # A notch besides the letters: the part loses more than the letters' prism holds.
            notch = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 4), 2.0, 2.0, 1.0).Shape()
            return real("subtract", [made.shape], [notch])

        with (
            mock.patch.object(letters_module, "boolean", deeper),
            self.assertRaises(AfterCheckError),
        ):
            built(box("body", (40, 20, 5)), _letters("FORGE"))


# --- threads ---------------------------------------------------------------------------------


def _rod(diameter: float = 8.0, height: float = 12.0, axis: tuple[float, float, float] = (0, 0, 1),
         origin: tuple[float, float, float] = (0, 0, 0)) -> dict[str, Any]:  # fmt: skip
    return step(
        "rod",
        "cylinder",
        diameter=mm(diameter),
        height=mm(height),
        axis=list(axis),
        origin=at(*origin),
    )


def _thread(hand: str = "right", length: float = 8.0, *, diameter: float = 8.0, pitch: float = 1.25,
            rod: float = 12.0, axis: tuple[float, float, float] = (0, 0, 1),
            origin: tuple[float, float, float] = (0, 0, 0), on: str = "rod") -> dict[str, Any]:  # fmt: skip
    return step("part", "thread", (on,), axis_origin=at(*origin), axis={"vector": list(axis)},
                major_diameter=mm(diameter), pitch=mm(pitch), hand=hand, length=mm(length), rod_start=mm(0),
                rod_end=mm(rod))  # fmt: skip


def _taken(radius: float, pitch: float, length: float) -> float:
    """What an ISO 68-1 basic thread takes from a whole rod, worked out here: each cross-section's groove, the share of each circle it takes (a quarter at the root, 7/8 at the crest's radius, straight between), integrated by Simpson's rule (exact for the cubic it is)."""
    depth = 5 / 8 * math.sqrt(3) / 2 * pitch
    minor = radius - depth

    def ring(r: float) -> float:
        return 2 * math.pi * r * (0.25 + (r - minor) / depth * (7 / 8 - 1 / 4))

    return (
        length * depth / 6 * (ring(minor) + 4 * ring(minor + depth / 2) + ring(radius))
    )


@needs_occ
class Threads(unittest.TestCase):
    """``thread``: a rod's round side cut into ISO 68-1's basic profile (docs/V2-stage4.md, 7.2)."""

    def test_either_hand_takes_its_groove_from_a_whole_rod(self) -> None:
        for hand in ("right", "left"):
            with self.subTest(hand=hand):
                result = built(_rod(), _thread(hand))
                taken = math.pi * 16 * 12 - volume(result.shape)
                self.assertAlmostEqual(taken, _taken(4.0, 1.25, 8.0), delta=1e-4)
                self.assertEqual(roles(result, "part"), {"flank", "root", "runout"})
                self.assertEqual(trace(result, "part").tolerance, 1e-5)

    def test_it_winds_the_way_its_hand_says(self) -> None:
        from forge_checks.view import Side

        # Points half way down the thread, round the axis and along it: the groove's are out of the part.
        # Each hand's helix (u = s - hand theta P / 2 pi) puts them in and out of its groove; only one fits.
        rng = np.random.default_rng(3)
        theta, s = rng.uniform(0, 2 * math.pi, 400), rng.uniform(5.5, 10.5, 400)
        r = 4.0 - 5 / 16 * math.sqrt(3) / 2 * 1.25  # half way down
        groove = 1.25 / 8 + 5 / 16 * math.sqrt(3) / 2 * 1.25 * math.tan(
            math.radians(30)
        )  # its half-width there
        points = np.stack([r * np.cos(theta), r * np.sin(theta), s], axis=1)
        for hand, sign in (("right", 1.0), ("left", -1.0)):
            with self.subTest(hand=hand):
                out = (
                    BrepView(built(_rod(), _thread(hand)).shape).classify(points)
                    == Side.OUT
                )
                fits = {}
                for turn in (sign, -sign):
                    phase = np.mod(s - turn * theta * 1.25 / (2 * math.pi), 1.25)
                    # The best start: the groove where the points are out, the thread where they're in.
                    fits[turn] = max(float(np.mean((np.abs(np.mod(phase - start, 1.25) - 0.625) > 0.625 - groove) == out))
                                     for start in np.linspace(0, 1.25, 1250, endpoint=False))  # fmt: skip
                self.assertGreater(fits[sign], 0.97)
                self.assertLess(fits[-sign], 0.8)

    def test_a_long_fine_thread_on_a_tilted_rod_and_one_the_whole_rod_long(
        self,
    ) -> None:
        # 24 turns, the rod tilted: the groove swept in pieces of a turn, each held to the profile.
        result = built(_rod(4.0, 18.0, (1, 1, 1), (1, 2, 3)),
                       _thread("left", 17.0, diameter=4.0, pitch=0.7, rod=18.0, axis=(1, 1, 1), origin=(1, 2, 3)))  # fmt: skip
        taken = math.pi * 4 * 18 - volume(result.shape)
        self.assertAlmostEqual(taken, _taken(2.0, 0.7, 17.0), delta=1e-4)
        whole = built(_rod(), _thread(length=12.0))
        self.assertAlmostEqual(
            math.pi * 16 * 12 - volume(whole.shape), _taken(4.0, 1.25, 12.0), delta=1e-4
        )
        self.assertNotIn("runout", roles(whole, "part"))

    def test_a_rod_with_a_hole_across_it(self) -> None:
        # Not a whole rod there: what it takes is measured, and the groove's points are held.
        across = step(
            "across",
            "cylinder",
            diameter=mm(3),
            height=mm(20),
            axis=[1, 0, 0],
            origin=at(-10, 0, 8),
        )
        holed = step("holed", "subtract", ("rod", "across"))
        result = built(_rod(), across, holed, _thread(on="holed"))
        before = (
            math.pi * 16 * 12 - math.pi * 2.25 * 8
        )  # the hole runs 8 through the rod
        taken = before - volume(result.shape)
        self.assertLess(taken, _taken(4.0, 1.25, 8.0) - 1.0)
        self.assertGreater(taken, _taken(4.0, 1.25, 8.0) - 8.0)

    def test_something_besides_the_rod_in_its_way_is_caught(self) -> None:
        # A block against the rod's side, over the threaded length: the groove would cut into it.
        block = box("block", (6, 6, 12), (3.98, -3, 0))
        joined = step("joined", "union", ("rod", "block"))
        with self.assertRaises(AfterCheckError) as caught:
            built(_rod(), block, joined, _thread(on="joined"))
        self.assertIn("in its way", caught.exception.message)

    def test_what_is_refused(self) -> None:
        for bad, expected in (
            (_thread(length=13.0), "no longer than its rod"),
            (_thread(diameter=1.0, pitch=1.25), "thicker than its depth"),
        ):
            with self.subTest(expected=expected), self.assertRaises(OccError) as caught:
                built(_rod(), bad)
            self.assertIn(expected, str(caught.exception))

    def test_a_cut_gone_wrong_silently_is_caught_and_made_again(self) -> None:
        from forge_occ.ops import threads

        real = threads.boolean
        wrong: list[int] = []

        def silent(times: int) -> Any:
            def fake(kind: str, shapes: Any, tools: Any) -> Any:
                if kind == "subtract" and len(wrong) < times:
                    wrong.append(1)
                    # The part as it was, as OpenCascade sometimes leaves it.
                    return make.Boolean(shapes[0], History(make._Unchanged()), ())
                return real(kind, shapes, tools)

            return fake

        with mock.patch.object(threads, "boolean", silent(1)):
            result = built(_rod(), _thread())
        self.assertAlmostEqual(
            math.pi * 16 * 12 - volume(result.shape), _taken(4.0, 1.25, 8.0), delta=1e-4
        )
        wrong.clear()
        with (
            mock.patch.object(threads, "boolean", silent(3)),
            self.assertRaises(AfterCheckError) as caught,
        ):
            built(_rod(), _thread())
        self.assertIn("so that it holds", caught.exception.message)


# --- shells, offsets and holes ---------------------------------------------------------------


@needs_occ
class ShellsOffsetsAndHoles(unittest.TestCase):
    def test_an_inward_shell_and_its_wall(self) -> None:
        result = built(
            box("body", (20, 20, 20)), step("part", "shell", ("body",), thickness=mm(2))
        )
        self.assertAlmostEqual(volume(result.shape), 8000 - 16**3, delta=1e-6)
        inner = [
            f
            for f, n in result.names.items()
            if n == frozenset({Name("part", "inner")})
        ]
        self.assertEqual(len(inner), 6)

    def test_a_shell_thicker_than_the_part_is_refused(self) -> None:
        # Section 4: an inward shell thicker than the part "succeeds", unchanged, as OpenCascade makes it.
        # Refused one way or the other: OpenCascade can't offset it, or its offset isn't at the thickness.
        with self.assertRaises((DesignError, AfterCheckError)) as caught:
            built(
                box("body", (20, 20, 10)),
                step("part", "shell", ("body",), thickness=mm(11)),
            )
        self.assertTrue(
            "doesn't fit" in caught.exception.message
            or "wall is 11 mm" in caught.exception.message
        )

    def test_an_offset_is_steiners(self) -> None:
        a, b, c, d = 20.0, 10.0, 6.0, 1.0
        result = built(
            box("body", (a, b, c)), step("part", "offset", ("body",), distance=mm(d))
        )
        expected = (
            a * b * c
            + 2 * (a * b + b * c + a * c) * d
            + math.pi * (a + b + c) * d * d
            + 4 / 3 * math.pi * d**3
        )
        self.assertAlmostEqual(volume(result.shape), expected, delta=expected * 1e-9)

    def test_a_through_hole_and_its_names(self) -> None:
        result = built(box("body", (30, 30, 6)),
                       {**step("part", "hole", ("body",), diameter=mm(5), position=at(15, 15, 3), through="all"),
                        "role": "pivot"})  # fmt: skip
        self.assertAlmostEqual(
            volume(result.shape), 5400 - math.pi * 6.25 * 6, delta=1e-8
        )
        self.assertIn("bore", roles(result, "part"))

    def test_a_counterbore(self) -> None:
        result = built(box("body", (30, 30, 10)),
                       step("part", "hole", ("body",), diameter=mm(5), position=at(15, 15, 5), through="all",
                            counterbore_diameter=mm(9), counterbore_depth=mm(3)))  # fmt: skip
        expected = 9000 - math.pi * 6.25 * 7 - math.pi * 20.25 * 3
        self.assertAlmostEqual(volume(result.shape), expected, delta=1e-8)
        self.assertTrue(
            {"bore", "counterbore_wall", "counterbore_floor"} <= roles(result, "part")
        )

    def test_a_distance_from_inside_is_to_the_surface(self) -> None:
        # Section 4: BRepExtrema from a point inside a solid gives 0; measured to the faces it doesn't.
        shape = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
        self.assertAlmostEqual(
            float(distances_to([(5.0, 5.0, 2.0)], shape)[0]), 2.0, delta=1e-12
        )


# --- patterns, mirrors and moves ----------------------------------------------------------------


@needs_occ
class Copies(unittest.TestCase):
    def test_a_linear_pattern_and_its_copies_names(self) -> None:
        result = built(
            box("body", (5, 5, 5)),
            step("part", "pattern_linear", ("body",), count=3, spacing=at(10, 0, 0)),
        )
        self.assertAlmostEqual(volume(result.shape), 375.0, delta=1e-9)
        self.assertEqual(trace(result, "part").solids, 3)
        self.assertEqual(
            {n.copy for n in result.names.every() if n.step == "body"}, {0, 1, 2}
        )

    def test_a_circular_pattern(self) -> None:
        result = built(box("body", (4, 2, 2), (10, -1, 0)),
                       step("part", "pattern_circular", ("body",), count=4, axis_origin=at(0, 0, 0),
                            axis_direction=[0, 0, 1]))  # fmt: skip
        self.assertAlmostEqual(volume(result.shape), 64.0, delta=1e-9)
        self.assertEqual(trace(result, "part").solids, 4)

    def test_a_mirror_kept_and_not(self) -> None:
        body = box("body", (5, 5, 5), (1, 0, 0))
        kept = built(body, step("part", "mirror", ("body",), plane_normal=[1, 0, 0]))
        self.assertAlmostEqual(volume(kept.shape), 250.0, delta=1e-9)
        alone = built(
            body,
            step(
                "part", "mirror", ("body",), plane_normal=[1, 0, 0], keep_original=False
            ),
        )
        self.assertAlmostEqual(BrepView(alone.shape).bounds().hi[0], -1.0, delta=1e-12)

    def test_a_copy_put_anywhere_but_where_its_motion_says_is_caught(self) -> None:
        real = Motion.apply

        def astray(self: Any, shape: Any) -> Any:
            return real(
                self.then(
                    Motion.of([[1, 0, 0], [0, 1, 0], [0, 0, 1]], (0.0, 0.0, 1e-3))
                ),
                shape,
            )

        with (
            mock.patch.object(Motion, "apply", astray),
            self.assertRaises(AfterCheckError),
        ):
            built(
                box("body", (5, 5, 5)),
                step("part", "transform", ("body",), translate=at(10, 0, 0)),
            )


# --- bends -----------------------------------------------------------------------------------


def _plate_bent(
    *more: dict[str, Any], hold: str | None = None, hole: bool = False
) -> list[dict[str, Any]]:
    steps = [box("plate", (60, 20, 2))]
    if hole:
        steps.append({**step("drilled", "hole", ("plate",), diameter=mm(4), position=at(30, 10, 1), through="all"),
                      "role": "drilled"})  # fmt: skip
    params: dict[str, Any] = {"angle": deg(90), "position": at(30, 10, 1), "along": [1, 0, 0], "toward": [0, 0, 1],
                              "radius": mm(3)}  # fmt: skip
    if hold:
        params["hold"] = hold
    steps.append(
        step("part" if not more else "first", "bend", (steps[-1]["id"],), **params)
    )
    return [*steps, *more]


@needs_occ
class Bends(unittest.TestCase):
    def test_a_prism_zone_is_turned_exactly(self) -> None:
        result = built(*_plate_bent())
        self.assertAlmostEqual(
            volume(result.shape), 2400.0, delta=1e-8
        )  # a bend's middle surface keeps its length
        self.assertEqual(trace(result, "part").tolerance, 0.0)
        self.assertTrue({"x_min", "x_max", "z_max", "z_min"} <= roles(result, "plate"))

    def test_a_mapped_zone_states_its_fit(self) -> None:
        result = built(*_plate_bent(hole=True))
        self.assertGreater(trace(result, "part").tolerance, 0.0)
        self.assertLess(trace(result, "part").tolerance, 1e-5)
        self.assertIn("bore", roles(result, "drilled"))
        self.assertAlmostEqual(
            volume(result.shape), 2400.0 - math.pi * 4 * 2, delta=1e-3
        )

    def test_held_at_the_middle_the_zones_middle_stays(self) -> None:
        result = built(*_plate_bent(hold="middle"))
        # The middle of the zone's middle surface, where it was flat: (30, 10, 1).
        self.assertLess(
            float(BrepView(result.shape).distance([(30.0, 10.0, 0.0)])[0]), 1.0 + 1e-6
        )
        self.assertEqual(
            int(BrepView(result.shape).classify([(30.0, 10.0, 1.0)])[0]), 1
        )  # inside

    def test_a_chain_of_two(self) -> None:
        second = step("part", "bend", ("first",), angle=deg(90), position=at(15, 10, 1), along=[1, 0, 0],
                      toward=[0, 0, 1], radius=mm(3))  # fmt: skip
        result = built(*_plate_bent(second))
        self.assertEqual(len(result.products["part"].chain), 2)
        self.assertAlmostEqual(volume(result.shape), 2400.0, delta=1e-8)

    def test_a_zone_wrapped_wrong_is_caught(self) -> None:
        real = bend_module._revolved

        def short(step_id: str, zone: Any, spec: Any, start: float) -> Any:
            return real(step_id, zone, replace(spec, angle=spec.angle * 0.99), start)

        with (
            mock.patch.object(bend_module, "_revolved", short),
            self.assertRaises(AfterCheckError),
        ):
            built(*_plate_bent())

    def test_the_recorded_bends_build(self) -> None:
        document = converted(zoo()["zoo_l_bracket_bent"])
        result = OccBackend().build(document, document.components[0].identifier)
        self.assertEqual(result.solids, 1)


# --- references -------------------------------------------------------------------------------


@needs_occ
class References(unittest.TestCase):
    def fillet(self, edges_: dict[str, Any], *more: dict[str, Any]) -> Any:
        return built(box("body", (40, 30, 10)), *more,
                     step("part", "fillet", (more[-1]["id"] if more else "body",), radius=mm(1), edges=edges_))  # fmt: skip

    def test_a_count_out_of_range_lists_what_was_found(self) -> None:
        with self.assertRaises(RefError) as caught:
            self.fillet(_top_edges((1, 2)))
        self.assertIn("found 4, the reference allows 1 to 2", caught.exception.message)
        self.assertEqual(len(caught.exception.detail["found"]), 4)

    def test_where_tells_pieces_apart_and_says_what_it_dropped(self) -> None:
        self.fillet(_top_edges((2, 2), kind="line", axis=[1, 0, 0]))
        with self.assertRaises(RefError) as caught:
            self.fillet(_top_edges((1, 1), kind="line", axis=[1, 0, 0]))
        dropped = caught.exception.detail["dropped"]
        self.assertEqual(len(dropped), 2)
        self.assertTrue(all("axis runs another way" in d["dropped"] for d in dropped))

    def test_covers_whole_refuses_a_where_that_left_some_out(self) -> None:
        query = _top_edges((2, 2), kind="line", axis=[1, 0, 0])
        query["match"]["covers"] = "whole"
        with self.assertRaises(RefError) as caught:
            self.fillet(query)
        self.assertIn("left some out", caught.exception.message)

    def test_covers_full_circle(self) -> None:
        boss = {
            **step(
                "boss", "cylinder", diameter=mm(8), height=mm(5), origin=at(20, 15, 10)
            ),
            "role": "boss",
        }
        joined = step("joined", "union", ("body", "boss"))
        root = {"between": [{"created_by": "boss", "role": "lateral"}, {"created_by": "body", "role": "z_max"}],
                "match": {"count": [1, 4], "covers": "full_circle"}}  # fmt: skip
        result = self.fillet(root, boss, joined)
        self.assertIn("round", roles(result, "part"))
        top = {"of": {"created_by": "boss", "role": "top"}, "where": {"kind": "circle"},
               "match": {"count": [1, 4], "covers": "full_circle"}}  # fmt: skip
        self.fillet(top, boss, joined)
        half = {
            "of": {"created_by": "body", "role": "z_max"},
            "match": {"count": [1, 8], "covers": "full_circle"},
        }
        with self.assertRaises(RefError) as caught:
            self.fillet(half, boss, joined)
        self.assertIn("aren't all arcs", caught.exception.message)

    def test_a_piece_clear_of_the_stretch_is_another_edge(self) -> None:
        # The bitten plate's top edge on y = 20 is two sides in line, either side of the bite: each
        # side's stretch finds its own piece, the other dropped as elsewhere on the line.
        query = {"between": [{"created_by": "body", "role": "end_face"}, {"created_by": "body", "role": "side"}],
                 "where": {"kind": "line", "axis": [1, 0, 0], "through": [30, 20, 8], "within": [[24, 20, 8], [30, 20, 8]]},
                 "match": {"count": [1, 1]}}  # fmt: skip
        result = built(PLANE, outlined(BITTEN), step("body", "extrude", ("outline",), distance=mm(8)),
                       step("part", "fillet", ("body",), radius=mm(1), edges=query))  # fmt: skip
        self.assertIn("round", roles(result, "part"))
        # Running on past its stretch (the stretch is only half the side): refused.
        query["where"]["within"] = [[27, 20, 8], [30, 20, 8]]
        with self.assertRaises(RefError) as caught:
            built(PLANE, outlined(BITTEN), step("body", "extrude", ("outline",), distance=mm(8)),
                  step("part", "fillet", ("body",), radius=mm(1), edges=query))  # fmt: skip
        self.assertIn("mm past the stretch", caught.exception.message)

    def test_a_face_an_earlier_step_buried_is_said_to_be(self) -> None:
        # The cut takes the whole top of the box away: its z_max faces are gone.
        cutter = box("cutter", (50, 40, 5), (-5, -5, 8))
        cut = step("cut", "subtract", ("body", "cutter"))
        with self.assertRaises(RefError) as caught:
            self.fillet(_top_edges((4, 4)), cutter, cut)
        self.assertIn("body.z_max was buried by step cut", caught.exception.message)
        self.assertEqual(caught.exception.detail["buried_by"], {"body.z_max": "cut"})


@needs_occ
class TheBoundary(unittest.TestCase):
    def test_opencascades_exception_becomes_an_error_saying_what_was_done(self) -> None:
        with self.assertRaises(OperationError) as caught, boundary("a cone", size=5):
            BRepPrimAPI_MakeCone(5.0, 5.0, 10.0).Shape()
        self.assertIn("a cone: OpenCascade refused it", caught.exception.message)
        self.assertEqual(caught.exception.detail, {"size": 5})

    def test_every_steps_result_is_validated(self) -> None:
        self.assertEqual(len(solids(built(box("part", (1, 1, 1))).shape)), 1)
        with self.assertRaises(OccError):
            aftercheck.validate(BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).BottomFace())

    def test_a_tolerance_at_the_limit_is_within_it(self) -> None:
        """A tolerance OpenCascade sets to 1e-4 carries its own rounding: at the limit, not above it (generated part 181's pocket floor)."""
        self.assertFalse(aftercheck.too_loose(1.0000000000000003e-4))
        self.assertFalse(aftercheck.too_loose(aftercheck.TOLERANCE))
        self.assertTrue(aftercheck.too_loose(1.0001e-4))


if __name__ == "__main__":
    unittest.main()
