"""V2 stage 3: the second kernel's agreement (forge_kernel.agreement, forge_kernel.implicit_view, forge_occ.agreement; docs/V2-stage3.md, section 13).

The table's formulas against geometry worked by hand; the entries a document
gets; a profile's outline measured against V1's; parts both kernels build
agreeing; and agreement failing where the exact part is made wrong on
purpose: a hole 0.05 mm too big, a hole missing, a boss too tall, a name
dropped.
"""

from __future__ import annotations

import json
import math
import unittest
from typing import Any

import numpy as np
from v2_occ import converted, needs_occ, zoo

try:
    from forge_checks.view import Side
    from forge_kernel import compile_products
    from forge_kernel.agreement import (
        TAU,
        coil_tau,
        entries,
        first_wall_tau,
        path_tau,
        through_hole_tau,
    )
    from forge_kernel.implicit_view import ImplicitView
    from forge_occ.agreement import agree, profile_distance
    from forge_occ.backend import OccBackend
    from forge_occ.names import Name, Names
except ImportError:  # no OpenCascade here: every class below is skipped
    pass


@needs_occ
class TheFormulas(unittest.TestCase):
    def test_a_paths_arcs_as_twelve_chords(self) -> None:
        # A right-angled corner rounded to 10 mm, a 2 mm section: each chord turns 7.5 degrees.
        found = path_tau([(0, 0, 0), (50, 0, 0), (50, 50, 0)], 10.0, 2.0)
        self.assertAlmostEqual(
            found, 12.0 * (1.0 - math.cos(math.radians(7.5) / 2.0)), places=12
        )
        self.assertEqual(path_tau([(0, 0, 0), (50, 0, 0), (50, 50, 0)], 0.0, 2.0), 0.0)
        # A corner too tight for the radius is cut back to half the shorter run, as V1 cuts it.
        short = path_tau([(0, 0, 0), (4, 0, 0), (4, 50, 0)], 10.0, 1.0)
        self.assertAlmostEqual(
            short, 3.0 * (1.0 - math.cos(math.radians(7.5) / 2.0)), places=12
        )

    def test_a_coil(self) -> None:
        along, ends = coil_tau(10.0, 1.0, 5.0)
        half = math.pi * 5.0 / 180.0
        self.assertAlmostEqual(along, 10.0 * (1.0 - math.cos(half)), places=12)
        self.assertAlmostEqual(ends, math.tan(half), places=12)
        # Eight points at least, however few turns.
        along, _ = coil_tau(10.0, 1.0, 0.1)
        self.assertAlmostEqual(
            along, 10.0 * (1.0 - math.cos(math.pi * 0.1 / 8.0)), places=12
        )

    def test_holes(self) -> None:
        self.assertAlmostEqual(
            through_hole_tau((0, 0, 0), (10, 20, 30), (0, 0, 1)),
            30.0 / 511.0 / 2.0,
            places=12,
        )
        self.assertAlmostEqual(through_hole_tau((0, 0, 0), (10, 20, 30), (1, 1, 0)),
                               (30.0 / math.sqrt(2.0)) / 511.0 / 2.0, places=12)  # fmt: skip
        self.assertAlmostEqual(first_wall_tau(8.0), 0.01, places=12)


@needs_occ
class TheEntriesADocumentGets(unittest.TestCase):
    def test_a_blended_union_is_not_compared_where_two_operands_are_near(self) -> None:
        document = converted(zoo()["golden_clevis"])
        found = entries(document, "clevis")
        blend = [e for e in found if e.step == "joined"]
        self.assertEqual(len(blend), 1)
        self.assertFalse(blend[0].applicable)
        self.assertAlmostEqual(blend[0].zone, 6.0)
        self.assertEqual(len(blend[0].apart), 2)
        self.assertIn("base_plate", blend[0].apart[0].steps)
        self.assertIn("ear_left", blend[0].apart[1].steps)

    def test_a_counterbore_through_a_plate_carries_half_v1s_step(self) -> None:
        document = converted(zoo()["zoo2_deep_counterbore"])
        found = [
            e
            for e in entries(document, document.components[0].identifier)
            if e.op == "hole"
        ]
        self.assertTrue(found)
        for e in found:
            self.assertTrue(e.applicable)
            self.assertGreater(e.tau, TAU)
            self.assertEqual(
                e.faces.roles,
                frozenset({"counterbore_wall", "counterbore_floor", "countersink"}),
            )

    def test_a_coil_and_a_pipe(self) -> None:
        for name, op in (("zoo2_spring", "coil"), ("zoo2_handle", "pipe")):
            document = converted(zoo()[name])
            found = [
                e
                for e in entries(document, document.components[0].identifier)
                if e.op == op
            ]
            self.assertTrue(found, name)
            self.assertTrue(all(e.applicable and e.tau > TAU for e in found), name)


@needs_occ
class AProfilesOutline(unittest.TestCase):
    def outline(self, op: str, params: dict[str, Any]) -> tuple[Any, Any]:
        steps = [{"id": "plane", "op": "datum_plane", "params": {"base": "XY"}},
                 {"id": "shape", "op": op, "inputs": ["plane"], "params": params},
                 {"id": "part", "op": "extrude", "inputs": ["shape"], "params": {"distance": {"magnitude": 2, "unit": "mm"}}}]  # fmt: skip
        document = _document(steps)
        exact = OccBackend().build(document, "part")
        v1 = compile_products(document.down_converted().component("part"))
        return exact.products["shape"], v1["shape"].profile

    def test_analytic_outlines_are_the_same(self) -> None:
        mm = {"unit": "mm"}
        for op, params in (
            ("profile_rectangle", {"width": {"magnitude": 30, **mm}, "height": {"magnitude": 20, **mm},
                                   "corner_radius": {"magnitude": 3, **mm}}),
            ("profile_circle", {"diameter": {"magnitude": 12, **mm}}),
            ("profile_slot", {"length": {"magnitude": 30, **mm}, "width": {"magnitude": 8, **mm}}),
            ("profile_polygon", {"circumscribed_diameter": {"magnitude": 20, **mm}, "sides": 6}),
        ):  # fmt: skip
            exact, v1 = self.outline(op, params)
            self.assertLess(profile_distance(exact, v1), 1e-6, op)

    def test_a_sketchs_rounded_corners_are_ten_chords(self) -> None:
        points = [[0, 0], [40, 0], [40, 30], [0, 30]]
        exact, v1 = self.outline(
            "profile_sketch",
            {
                "points": {"points": points, "unit": "mm"},
                "corner_radius": {"magnitude": 5, "unit": "mm"},
            },
        )
        expected = 5.0 * (1.0 - math.cos(math.pi / 2.0 / 20.0))
        self.assertAlmostEqual(
            profile_distance(exact, v1), expected, delta=expected * 0.05
        )

    def test_a_smooth_sketch_is_further(self) -> None:
        points = [[0, 0], [40, 0], [40, 30], [0, 30]]
        exact, v1 = self.outline(
            "profile_sketch",
            {"points": {"points": points, "unit": "mm"}, "smooth": True},
        )
        self.assertGreater(profile_distance(exact, v1), 1e-3)


def _document(steps: list[dict[str, Any]]) -> Any:
    from v2_occ import v2_document

    return v2_document({"schema_version": "2.0.0", "document_id": "t", "project_id": "t", "revision": 1, "name": "t",
                        "components": [{"id": "part", "steps": steps}]})  # fmt: skip


@needs_occ
class TheImplicitView(unittest.TestCase):
    def test_sides_volume_and_box(self) -> None:
        document = converted(zoo()["zoo_tray"])
        from forge_kernel import Compiler

        part = Compiler().compile_component(document.down_converted().components[0])
        view = ImplicitView(part.solid)
        box = view.bounds()
        far = np.asarray(box.hi) + 10.0
        self.assertEqual(int(view.classify(far[None])[0]), Side.OUT)
        volume = view.volume()
        exact = OccBackend().build(document, document.components[0].identifier)
        from forge_occ.measure import volume_interval

        found = volume_interval(exact.shape)
        self.assertLessEqual(volume.lo, found.lo)
        self.assertLessEqual(found.hi, volume.hi)
        points, normals = view.surface()
        self.assertGreater(len(points), 100)
        np.testing.assert_allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-9)
        self.assertLess(float(np.abs(view.field(points)).max()), 1e-6)


@needs_occ
class PartsBothKernelsBuildAgree(unittest.TestCase):
    def test_a_few_of_the_zoo(self) -> None:
        for name in (
            "golden_clevis",
            "zoo_knob",
            "zoo2_pulley",
            "zoo2_deep_counterbore",
            "zoo_l_bracket_bent",
        ):
            with self.subTest(name):
                document = converted(zoo()[name])
                report = agree(document, document.components[0].identifier)
                self.assertTrue(
                    report.holds, json.dumps(report.as_dict(), default=str)[:2000]
                )
                self.assertGreater(report.compared, 10_000)


@needs_occ
class AMeshTooCoarseForAHole(unittest.TestCase):
    def test_made_again_finer_it_agrees(self) -> None:
        """Generated part 190's hole, 1.52 mm across in a block 100 mm long, closes in the implicit mesh 96 cells across: the genus is one fewer than the exact part's. Made again at 192 cells, the counts agree."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import v2_exit4
        from forge_eval.generator import render
        from v2_regressions import REGRESSIONS

        spec = v2_exit4._spec(render(REGRESSIONS[190][1]).items)
        plan, built = v2_exit4._built(spec)
        report = agree(plan.document(built.choice), "part", exact=built.result)
        self.assertTrue(report.holds, json.dumps(report.as_dict(), default=str)[:2000])
        self.assertEqual(
            report.topology["exact"]["genus"], report.topology["implicit"]["genus"]
        )
        self.assertTrue(report.topology["counted"])
        self.assertIn(
            "the implicit kernel's mesh made again at 192 cells across", report.notes
        )

    def test_one_not_sound_is_not_made_again(self) -> None:
        """A cone on a plate: the mesh at 96 cells isn't sound at the apex, and made again at 192 it needed more than 4 GB, unsound still. Reported, not counted, and not made again."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_v2_plan_agree import agreed

        _, _, report = agreed("cone on a plate")
        self.assertTrue(report.holds)
        self.assertFalse(report.topology["counted"])
        self.assertFalse(report.topology["implicit"]["sound"])
        self.assertFalse([n for n in report.notes if "cells" in n])


@needs_occ
class AWallTooThinForTheMesh(unittest.TestCase):
    def test_its_topology_is_reported_not_counted(self) -> None:
        """Generated part 9530: four holes stand 0.118 mm from a pocket's side. The implicit kernel's field and the exact part agree at every point compared, but its mesh, made again at 256 cells across in cells of some 0.4 mm, steps over each wall (genus 8 for 4). The wall is found on the exact part, under two of the mesh's cells: the counts are reported, not counted."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import v2_exit4
        from forge_eval.generator import render
        from v2_regressions import REGRESSIONS

        spec = v2_exit4._spec(render(REGRESSIONS[9530][1]).items)
        plan, built = v2_exit4._built(spec)
        report = agree(plan.document(built.choice), "part", exact=built.result)
        self.assertTrue(report.holds, json.dumps(report.as_dict(), default=str)[:2000])
        self.assertEqual(report.disagreements, 0)
        self.assertEqual(report.topology["exact"]["genus"], [4])
        self.assertEqual(report.topology["implicit"]["genus"], [8])
        self.assertFalse(report.topology["counted"])
        self.assertAlmostEqual(report.topology["thinnest"]["across"], 0.118, places=6)
        self.assertTrue(
            any("a wall or a gap 0.118 mm across" in n for n in report.notes),
            report.notes,
        )


@needs_occ
class AMotionOfAnotherSolid(unittest.TestCase):
    def test_leaves_the_faces_lost_before_it_excused(self) -> None:
        """Generated part 620: a boss on a block's side and holes in another, then a round-ended tab turned in a third
        face, made by turning its own stadium (a transform) before it is kept and joined. The faces the boss's foot and
        the holes' far ends lost were taken as moved by that motion, which moves only the stadium, and went
        unexcused; now a move counts only for what is made from the step that made the face."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import v2_exit4
        from forge_eval.generator import render
        from v2_regressions import REGRESSIONS

        spec = v2_exit4._spec(render(REGRESSIONS[620][1]).items)
        plan, built = v2_exit4._built(spec)
        document = plan.document(built.choice)
        self.assertIn("transform", [s.op for s in document.steps("part")])
        report = agree(document, "part", exact=built.result)
        self.assertTrue(report.holds, json.dumps(report.as_dict(), default=str)[:2000])
        self.assertEqual(report.names["missing"], [])


@needs_occ
class BossesFlushWithEdges(unittest.TestCase):
    def test_the_exact_part_counts_no_through_hole_for_them(self) -> None:
        """Generated part 450: two blocks, each crossed by a through slot that four deep round slots meet, a boss flush with each block's edge, and a tube with a hole into its bore: genus 11. Counted by its faces' wires alone, each boss's face (its circle touching the face's outline at a point) lost one from the Euler characteristic, and the exact part said 12; the implicit kernel's mesh, sound at 256 cells, said 11 and was right."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import v2_exit4
        from forge_eval.generator import render
        from v2_regressions import REGRESSIONS

        spec = v2_exit4._spec(render(REGRESSIONS[450][1]).items)
        plan, built = v2_exit4._built(spec)
        report = agree(plan.document(built.choice), "part", exact=built.result)
        self.assertTrue(report.holds, json.dumps(report.as_dict(), default=str)[:2000])
        self.assertEqual(report.topology["exact"]["genus"], [11])
        if report.topology["counted"]:
            self.assertEqual(report.topology["implicit"]["genus"], [11])


@needs_occ
class AThinFaceJoinedFlush(unittest.TestCase):
    def test_its_lost_name_is_excused(self) -> None:
        """Generated part 6820: an extrusion's L-shaped foot, its legs 0.49 mm wide, joined flush to a block. V1 calls the foot's face live (its samples, the box round the L, lie on the block's face); the exact part rightly has none. Sampled finely enough to find the face's inside clear of its rim, the step that joined it is shown to have lost it rightly."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import v2_exit4
        from forge_eval.generator import render
        from v2_regressions import REGRESSIONS

        spec = v2_exit4._spec(render(REGRESSIONS[6820][1]).items)
        plan, built = v2_exit4._built(spec)
        report = agree(plan.document(built.choice), "part", exact=built.result)
        self.assertTrue(report.holds, json.dumps(report.as_dict(), default=str)[:2000])
        self.assertIn(
            "i0.0.body.end_face: step i0.join lost it rightly",
            " | ".join(report.names["excused"]),
        )


@needs_occ
class ANarrowCutsMouth(unittest.TestCase):
    def test_its_lost_names_are_excused(self) -> None:
        """Generated part 670: an L-shaped pocket right through a post, its legs 0.28 mm wide, on a part 119 mm across. No point of its tool's end faces lies twice the view's reach (0.12 mm) clear of their rims; held to the exact kernel's own tolerance, as the step's part is, points clear of the rim show the step that cut it lost them rightly."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import v2_exit4
        from forge_eval.generator import render
        from v2_regressions import REGRESSIONS

        spec = v2_exit4._spec(render(REGRESSIONS[670][1]).items)
        plan, built = v2_exit4._built(spec)
        report = agree(plan.document(built.choice), "part", exact=built.result)
        self.assertTrue(report.holds, json.dumps(report.as_dict(), default=str)[:2000])
        self.assertEqual(report.names["missing"], [])
        excused = " | ".join(report.names["excused"])
        for face in ("start_face", "end_face"):
            self.assertIn(f"i4.0.cut.{face}: step i4.cut lost it rightly", excused)


class AgreementFindsAnExactPartMadeWrong(unittest.TestCase):
    """The implicit part from the document; the exact one from a document changed on purpose."""

    def changed(self, name: str, change: Any) -> tuple[Any, Any]:
        text = zoo()[name]
        document = converted(text)
        payload = json.loads(text)
        change(payload)
        wrong = converted(json.dumps(payload))
        component = document.components[0].identifier
        return document, OccBackend().build(wrong, component)

    def test_a_hole_five_hundredths_too_big(self) -> None:
        def bigger(payload: dict[str, Any]) -> None:
            diameter = next(
                p
                for p in payload["components"][0]["parameters"]
                if p["id"] == "hole_diameter"
            )
            diameter["value"] = {
                "magnitude": diameter["value"]["magnitude"] + 0.05,
                "unit": "mm",
            }

        document, exact = self.changed("zoo_plate_4_holes", bigger)
        report = agree(document, document.components[0].identifier, exact=exact)
        self.assertFalse(report.holds)
        self.assertGreater(report.disagreements, 0)

    def test_a_hole_missing(self) -> None:
        def no_hole(payload: dict[str, Any]) -> None:
            features = payload["components"][0]["features"]
            hole = next(f for f in features if f["kind"] == "hole")
            hole["parameters"]["diameter"] = {"magnitude": 0.01, "unit": "mm"}

        document, exact = self.changed("zoo_plate_4_holes", no_hole)
        report = agree(document, document.components[0].identifier, exact=exact)
        self.assertFalse(report.holds)
        self.assertGreater(report.disagreements, 0)

    def test_a_dropped_name(self) -> None:
        document = converted(zoo()["golden_clevis"])
        exact = OccBackend().build(document, "clevis")
        table = tuple(frozenset(n for n in held if not (n.step == "pivot" and n.role == "bore")) or
                      frozenset({Name("pivot", "other")}) for held in exact.names.table)  # fmt: skip
        from dataclasses import replace

        renamed = replace(exact, names=Names(exact.shape, table))
        report = agree(document, "clevis", exact=renamed)
        self.assertFalse(report.names["holds"])
        self.assertIn("pivot.bore", report.names["missing"])


if __name__ == "__main__":
    unittest.main()
