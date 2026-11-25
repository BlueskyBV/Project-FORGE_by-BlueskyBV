"""V2: what the corpus's fifth run found (docs/V2-stage4.md, 14.11).

- **A triangle meets a box where a point of it is in the box:** the turned
  block, drawn as a rectangle turned 30 degrees, built and passed on its
  B-rep, and its STL was held. A long triangle on one of its sides spans,
  corner to corner, the finer box round its hole, which the side never
  comes near: read back, it was held to the box's tolerance, finer than
  its face was meshed to. A triangle's tolerance is now the least of the
  boxes the triangle itself meets, not its corners' box (the separating
  axis test).
- **Where a place on an outline's end is measured from:** the elbow-brace
  rails were drawn with their pivot at the outline's point (0, 0), and their
  holes placed from it. A place on an outline's end is measured from the
  middle of the box round the outline: the question asked of a copy that
  runs past the face's edge says where that middle is, and the writer is
  told (guide 34). Positions measured from a point of the part are a gap
  (V2-gaps.md, section 10).

The drafts are the runs' own (tests/fixtures/corpus_fourth_run.json,
corpus_fifth_run.json).
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forge_roles.spec_writer import read_answer
from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.guide import instructions
from v2_occ import needs_occ

HERE = Path(__file__).resolve().parent
FOURTH = json.loads((HERE / "fixtures" / "corpus_fourth_run.json").read_text(encoding="utf-8"))
FIFTH = json.loads((HERE / "fixtures" / "corpus_fifth_run.json").read_text(encoding="utf-8"))


def _draft(run: dict[str, Any], key: str) -> tuple[Any, dict[str, Any]]:
    found = run["drafts"][key]
    return number_words(found["brief"]), read_answer(copy.deepcopy(found["answer"]))


def _problems(b: Any, d: dict[str, Any]) -> list[tuple[str, str]]:
    return [(p.kind, p.message) for p in check_draft(b, d).problems]


def _clipped(triangle: Any, lo: Any, hi: Any) -> bool:
    """Whether anything of the triangle is left, clipped to the box's six sides in turn (the test's own reckoning)."""
    polygon = [np.asarray(p, dtype=np.float64) for p in triangle]
    for axis in range(3):
        for bound, below in ((hi[axis], True), (lo[axis], False)):
            kept = []
            for k, a in enumerate(polygon):
                b = polygon[(k + 1) % len(polygon)]
                fa, fb = (a[axis] - bound, b[axis] - bound) if below else (bound - a[axis], bound - b[axis])
                if fa <= 0:
                    kept.append(a)
                if fa < 0 < fb or fb < 0 < fa:
                    kept.append(a + fa / (fa - fb) * (b - a))
            polygon = kept
            if not polygon:
                return False
    return True


HOLE_BOX = ((-3.5, -3.5, -1.0), (3.5, 3.5, 11.0))
#: A triangle of the turned block's side, 10 mm from its middle, and one of its top round the hole.
SIDE = [[22.32, 1.34, 10.0], [-12.32, -18.66, 10.0], [-12.32, -18.66, 0.0]]
TOP = [[2.5, 0.0, 10.0], [20.0, 1.0, 10.0], [20.0, -1.0, 10.0]]


class ATriangleMeetsABox(unittest.TestCase):
    def test_where_a_point_of_it_is_in_the_box(self) -> None:
        from forge_checks.view import Box
        from forge_occ.export import triangles_meet

        rng = np.random.default_rng(5)
        lo, hi = np.array([-1.0, -2.0, -0.5]), np.array([1.5, 1.0, 0.5])
        triangles = rng.uniform(-4.0, 4.0, (3000, 3, 3)) * rng.uniform(0.1, 1.5, (3000, 1, 1))
        triangles += rng.uniform(-3.0, 3.0, (3000, 1, 3))
        found = triangles_meet(triangles, Box(tuple(lo), tuple(hi)))
        self.assertEqual(found.tolist(), [_clipped(t, lo, hi) for t in triangles])
        corners = np.all(triangles.min(axis=1) <= hi, axis=1) & np.all(triangles.max(axis=1) >= lo, axis=1)
        self.assertGreater(int((corners & ~found).sum()), 300)  # many whose corners' box meets it, the triangle not
        # Touching it is meeting it: at a corner, along a side.
        touching = np.array([[[1.5, 1.0, 0.5], [3.0, 1.0, 0.5], [3.0, 3.0, 2.0]],
                             [[1.5, -5.0, 0.0], [1.5, 5.0, 0.0], [4.0, 0.0, 0.0]]])  # fmt: skip
        self.assertEqual(triangles_meet(touching, Box(tuple(lo), tuple(hi))).tolist(), [True, True])

    def test_the_turned_block_s_side_is_held_to_its_own_tolerance(self) -> None:
        from forge_checks.view import Box
        from forge_occ.export import ExportTolerance

        tolerance = ExportTolerance(0.01, 0.1, ((Box(*HOLE_BOX), 0.005),))
        self.assertEqual(tolerance.of_triangles(np.array([SIDE, TOP])).tolist(), [0.01, 0.005])

    @needs_occ
    def test_the_turned_block_s_files_read_back(self) -> None:
        from forge_checks.judge import Judge
        from forge_cli.build import export_tolerance
        from forge_occ.export import (
            check_mesh_file,
            mesh_part,
            plate_shift,
            stl_bytes,
            threemf_bytes,
        )
        from forge_occ.planned import build_plan
        from forge_plan import plan
        from forge_spec.lock import lock

        b, d = _draft(FOURTH, "zoo2_rotated_block")
        confirmed = lock(check_draft(b, d), b, by="draft", strict=False)
        shape = build_plan(plan(confirmed)).result.shape
        tolerance = export_tolerance(Judge.of(confirmed.spec).suite)
        self.assertEqual(len(tolerance.finer), 1)
        meshed = mesh_part(shape, tolerance)
        self.assertEqual(check_mesh_file(stl_bytes(meshed.mesh), shape, meshed, tolerance).kind, "stl")
        shift = plate_shift(meshed.mesh)
        found = check_mesh_file(threemf_bytes(meshed.mesh, "turned-block", shift), shape, meshed, tolerance, shift=shift)
        self.assertEqual(found.kind, "3mf")


def _past_the_edge(item: str, face: str, middle: str | None) -> tuple[str, str]:
    said = "" if middle is None else (
        f" (a place on an outline's end is measured from the middle of the box round the outline, at {middle} in the "
        "outline's own coordinates, not from its point (0, 0))")  # fmt: skip
    return ("question", f"{item} copy 1 runs past the edge of face {face}{said}")


def _moved(profile: dict[str, Any], dx: float) -> None:
    """An outline drawn ``dx`` further along its first coordinate."""
    profile["start"][0] += dx
    for segment in profile["segments"]:
        for key in ("line_to", "arc_to", "centre"):
            if key in segment:
                segment[key][0] += dx


class WhereAPlaceOnAnOutlinesEndIsMeasuredFrom(unittest.TestCase):
    def test_the_rails_are_told(self) -> None:
        found = _problems(*_draft(FIFTH, "exo_forearm_rail_lug_clamped"))
        for item, face in (("mid_holes", "+end"), ("lug_boss", "+end"), ("lug_hole", "-end")):
            self.assertIn(_past_the_edge(item, face, "(84.5, 8)"), found)
        found = _problems(*_draft(FIFTH, "exo_upper_rail_held_round"))
        for item in ("hole_225", "hole_245"):
            self.assertIn(_past_the_edge(item, "-end", "(119.5, 0)"), found)

    def test_an_outline_drawn_about_its_middle_is_told_nothing_more(self) -> None:
        b, d = _draft(FIFTH, "exo_upper_rail_held_round")
        _moved(d["items"][0]["profile"], -119.5)
        found = _problems(b, d)
        self.assertIn(_past_the_edge("hole_245", "-end", None), found)
        self.assertFalse(any("the middle of the box" in m for _, m in found))

    def test_the_writer_is_told(self) -> None:
        self.assertIn('On an outline\'s end (an extrusion\'s "+end" or "-end") the face\'s centre is the middle of the '
                      "box round the outline, not the outline's point (0, 0)", instructions())  # fmt: skip


if __name__ == "__main__":
    unittest.main()
