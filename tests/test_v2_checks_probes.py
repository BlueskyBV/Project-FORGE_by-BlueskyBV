"""V2 stage 2, step 8: fresh probes (forge_checks.probes), drawn after the build from a recorded seed.

On generated parts, built from the generator's own truth: every point drawn
is on the side the truth puts it, at least the margin from the truth's
surface; every item's probes pass on the part as asked; the same seed draws
the same points and another seed others; and an item taken away, or moved
well off its place, fails its own probes. A view too coarse for the margin,
or one that can't tell, is inconclusive, never a pass.
"""

from __future__ import annotations

import functools
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from forge_checks.classes import Verdict
from forge_checks.mesh import Mesh, MeshView, box_mesh
from forge_checks.oracle import Oracle, oracle
from forge_checks.place import place
from forge_checks.probes import LEAST, draw
from forge_checks.view import ViewProxy
from forge_eval.generator import Case, Position, generate, render

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_eval_truth import spec_of, view_of
from v2_meshes import HAVE_MANIFOLD
from v2_truth import deflection

#: The generated parts probed, by seed.
PARTS = tuple(range(8))


@functools.cache
def case(seed: int) -> Case:
    return generate(seed)


@functools.cache
def shape(seed: int) -> Oracle:
    spec = spec_of(case(seed).items)
    return oracle(spec, place(spec))


def _directions() -> Any:
    """The 26 ways from a cube's centre to its corners, edge middles and face middles, as unit vectors."""
    ways = np.array(
        [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1) if i or j or k],
        dtype=float,
    )  # fmt: skip
    return ways / np.linalg.norm(ways, axis=1)[:, None]


class Drawn(unittest.TestCase):
    def test_every_point_is_where_the_truth_puts_it_and_clear_of_its_surface(
        self,
    ) -> None:
        for seed in PARTS:
            c = case(seed)
            assert c.truth is not None
            probes = draw(shape(seed), 7, deflection(c.truth))
            with self.subTest(seed=seed):
                self.assertGreater(len(probes), 100)
                self.assertGreaterEqual(probes.margin, LEAST)
                self.assertEqual(
                    c.truth.inside(probes.points).tolist(), probes.inside.tolist()
                )
                # Just short of the margin every way, each point is still on its side.
                for way in _directions():
                    moved = probes.points + 0.999 * probes.margin * way
                    self.assertEqual(
                        c.truth.inside(moved).tolist(), probes.inside.tolist()
                    )
                # Every item of the part, every copy, has its points (none is too small here).
                self.assertEqual(probes.empty, ())
                for item, copies in c.truth.copies.items():
                    mine = np.asarray(probes.items) == item
                    self.assertTrue(mine.any(), item)
                    self.assertEqual(
                        set(probes.copies[mine].tolist()), {c.index for c in copies}
                    )

    def test_a_seed_draws_its_points_again_and_another_draws_others(self) -> None:
        part, tolerance = shape(0), deflection(case(0).truth)  # type: ignore[arg-type]
        one, again, other = (draw(part, s, tolerance) for s in (11, 11, 12))
        np.testing.assert_array_equal(one.points, again.points)
        self.assertEqual(one.items, again.items)
        self.assertEqual((one.seed, other.seed), (11, 12))
        self.assertFalse(
            len(one) == len(other) and np.array_equal(one.points, other.points)
        )

    def test_a_coarse_view_makes_a_wider_margin(self) -> None:
        part = shape(0)
        self.assertEqual(draw(part, 1, 0.0).margin, LEAST)
        self.assertEqual(draw(part, 1, 0.05).margin, 0.2)
        with self.assertRaises(ValueError):
            draw(part, 1, float("nan"))


@unittest.skipUnless(HAVE_MANIFOLD, "the generated parts are built with manifold3d")
class Judged(unittest.TestCase):
    def verdicts(self, seed: int, built: Case) -> dict[str, Verdict]:
        tolerance = deflection(case(seed).truth)  # type: ignore[arg-type]
        probes = draw(shape(seed), 2026, tolerance)
        view = view_of(built)
        if not view.topology().sound:
            self.skipTest("the mesh library made this part's mesh unsoundly")
        found = probes.run(view, tolerance)
        self.assertEqual(
            sorted(e.check for e in found), sorted({f"{i}/fresh" for i in probes.items})
        )
        for e in found:
            self.assertIn("seed 2026", e.reason)
        return {e.check.split("/")[0]: e.verdict for e in found}

    def test_the_part_as_asked_passes_every_item(self) -> None:
        for seed in PARTS:
            with self.subTest(seed=seed):
                found = self.verdicts(seed, case(seed))
                self.assertEqual(
                    {k: v for k, v in found.items() if v is not Verdict.PASS}, {}
                )

    def test_an_item_taken_away_fails_its_own_probes(self) -> None:
        tried = 0
        for seed in PARTS:
            plan = case(seed).plan
            # What stands on it, is cut into it, rounds, threads or hollows it.
            hosts = {f.on[0] for f in plan if f.on is not None} | {
                f.of for f in plan if f.of is not None
            }
            for f in plan[1:]:
                if f.id in hosts:
                    continue  # something stands on it or is cut into it, or rounds it
                gone = render(tuple(g for g in plan if g.id != f.id))
                with self.subTest(seed=seed, item=f.id):
                    found = self.verdicts(seed, gone)
                    self.assertIs(found[f.id], Verdict.FAIL)
                    tried += 1
                break
        self.assertGreaterEqual(tried, 5)

    def test_an_item_moved_well_off_its_place_fails_its_own_probes(self) -> None:
        tried = 0
        for seed in PARTS:
            plan = case(seed).plan
            hosts = {f.on[0] for f in plan if f.on is not None} | {
                f.of for f in plan if f.of is not None
            }
            for f in plan[1:]:
                if f.id in hosts or f.on is None or f.on[1] == "side" or not f.place:
                    continue
                axis = next(iter(f.place))
                for by in (8.0, -8.0, 14.0, -14.0):
                    moved = replace(f, place={**f.place, axis: Position("offset", by)})
                    try:
                        built = render(
                            tuple(moved if g.id == f.id else g for g in plan)
                        )
                    except ValueError:
                        continue
                    with self.subTest(seed=seed, item=f.id, by=by):
                        self.assertIs(self.verdicts(seed, built)[f.id], Verdict.FAIL)
                        tried += 1
                    break
                break
        self.assertGreaterEqual(tried, 4)

    def test_a_view_too_coarse_or_unsure_is_inconclusive(self) -> None:
        tolerance = deflection(case(0).truth)  # type: ignore[arg-type]
        probes = draw(shape(0), 3, tolerance)
        view = view_of(case(0))
        coarse = probes.run(view, probes.margin)  # four times this is past the margin
        self.assertTrue(coarse)
        self.assertTrue(all(e.verdict is Verdict.INCONCLUSIVE for e in coarse))
        # A box whose triangles all face in: no side it can be sure of.
        inside_out = box_mesh((-500, -500, -500), (500, 500, 500))
        flipped = Mesh(inside_out.vertices, inside_out.faces[:, ::-1])
        unsure = probes.run(
            ViewProxy(MeshView(flipped, source="mesh-file", deflection=0.0)), tolerance
        )
        self.assertTrue(all(e.verdict is not Verdict.PASS for e in unsure))


if __name__ == "__main__":
    unittest.main()
