"""V2 stage 2, step 8: faults the judge must hold, and near-misses it must pass, on generated parts (docs/V2-stage2.md, 8.2).

- **Correlated faults.** A bug is planted in the placement solver (a side
  measured from the far edge, an edge measured to the centre, an offset the
  wrong way, a pattern's pitch a tenth long), and the part built where the
  bugged solver puts its items, as a compiler copying the solver's
  coordinates would build it. The judge places every item itself, from the
  definitions: its placement differs from the bugged solver's
  (``compare_layouts``), face accounting fails, and the moved items' own
  checks fail, measured between built things. This tests the plan's
  central claim: the checks share no mistake with the solver.
- **Whole-part transforms.** Moved by a twentieth of a millimetre, scaled by
  1.001 and by 25.4 (a part drawn in inches), mirrored, turned 90 degrees:
  face accounting fails each, unless the transform leaves the part as it
  was (a part symmetric that way, told from the generator's truth).
- **Near-misses.** Built coarser (and saying so), its vertices jittered by up
  to half its deflection, its coordinates rounded to float32: face
  accounting and every check pass.
"""

from __future__ import annotations

import contextlib
import functools
import sys
import unittest
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

import forge_spec.placement as solver
import numpy as np
from forge_checks.accounting import account_faces
from forge_checks.classes import Verdict
from forge_checks.compiler import CheckSuite, compile_checks
from forge_checks.measure import Probe
from forge_checks.mesh import Mesh, MeshView
from forge_checks.oracle import Oracle, oracle
from forge_checks.place import Placed, compare_layouts, place
from forge_checks.view import ViewProxy
from forge_eval.generator import Case, generate
from forge_eval.truth import Truth
from forge_spec.placement import Layout

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v2_layouts
from test_v2_eval_truth import spec_of
from v2_meshes import HAVE_MANIFOLD, exported
from v2_truth import SAG, build, deflection, moved

#: The generated parts tried, by seed: the first few that each fault touches are judged.
SEEDS = range(40)
#: How many parts each planted bug is judged on.
PER_BUG = 2
#: A copy the bugged solver moves less than this (mm) is where it was.
MOVED = 0.05


@functools.cache
def case(seed: int) -> Case:
    return generate(seed)


@functools.cache
def judged(seed: int) -> tuple[Placed, Oracle, CheckSuite]:
    spec = spec_of(case(seed).items)
    placed = place(spec)
    part = oracle(spec, placed)
    return placed, part, compile_checks(spec, placed, part)


def view_of_mesh(vertices: Any, faces: Any, tolerance: float) -> ViewProxy:
    return ViewProxy(
        MeshView(Mesh(np.asarray(vertices, float), np.asarray(faces, np.int64)), source="mesh-file",
                 deflection=tolerance)
    )  # fmt: skip


def mesh_of(truth: Truth, sag: float = SAG) -> tuple[Any, Any]:
    """The part's mesh as manifold3d makes it: its vertices and its triangles' corners."""
    return exported(build(truth, sag))


# ----------------------------------------------------------------------
# Bugs planted in the solver
# ----------------------------------------------------------------------
def _far_edge() -> contextlib.AbstractContextManager[Any]:
    real = solver._along

    def bugged(position: Any, half: float, foot: float, extent: Any = None) -> float:
        found = real(position, half, foot, extent)
        return -found if position.mode == "side" else found

    return mock.patch.object(solver, "_along", bugged)


def _to_centre() -> contextlib.AbstractContextManager[Any]:
    real = solver._along

    def bugged(position: Any, half: float, foot: float, extent: Any = None) -> float:
        return real(replace(position, to="centre"), half, foot, extent)

    return mock.patch.object(solver, "_along", bugged)


def _offset_flipped() -> contextlib.AbstractContextManager[Any]:
    real = solver._along

    def bugged(position: Any, half: float, foot: float, extent: Any = None) -> float:
        found = real(position, half, foot, extent)
        return -found if position.mode == "offset" else found

    return mock.patch.object(solver, "_along", bugged)


def _long_pitch() -> contextlib.AbstractContextManager[Any]:
    real = solver._pattern_offsets

    def bugged(*args: Any) -> Any:
        found = real(*args)
        return None if found is None else [(1.1 * u, 1.1 * v) for u, v in found]

    return mock.patch.object(solver, "_pattern_offsets", bugged)


BUGS: dict[str, Callable[[], contextlib.AbstractContextManager[Any]]] = {
    "a side measured from the far edge": _far_edge,
    "an edge measured to the centre": _to_centre,
    "an offset the wrong way": _offset_flipped,
    "a pattern's pitch a tenth long": _long_pitch,
}


def touched(bug: str) -> Iterator[tuple[int, Layout, dict[tuple[str, int], Any]]]:
    """The parts the bug moves some copy of, the bugged solver accepting them: each one's seed, bugged layout and copies moved."""
    for seed in SEEDS:
        c = case(seed)
        assert c.truth is not None
        spec = spec_of(c.items)
        with BUGS[bug]():
            # The solver itself: the run's wrapper (tests/v2_layouts.py) would
            # hold the bugged layout against the definitions' before any part is built.
            layout = v2_layouts._SOLVE(spec)
        if layout.issues:
            continue  # the bugged solver turns it back itself
        by: dict[tuple[str, int], Any] = {}
        for item, copies in c.truth.copies.items():
            for truth, theirs in zip(copies, layout.instances[item], strict=True):
                if not np.allclose(truth.direction, theirs.normal, atol=1e-9):
                    by = {}
                    break  # turned, not moved: not a fault this test builds
                d = np.subtract(theirs.origin, truth.point)
                if float(np.linalg.norm(d)) > MOVED:
                    by[(item, truth.index)] = d
        if by:
            yield seed, layout, by


@unittest.skipUnless(HAVE_MANIFOLD, "the generated parts are built with manifold3d")
class CorrelatedFaults(unittest.TestCase):
    def held(self, bug: str) -> None:
        judged_parts = 0
        for seed, layout, by in touched(bug):
            c = case(seed)
            assert c.truth is not None
            vertices, faces = mesh_of(moved(c.truth, by))
            view = view_of_mesh(vertices, faces, deflection(c.truth))
            if not view.topology().sound:
                continue
            placed, part, suite = judged(seed)
            items = {item for item, _ in by}
            with self.subTest(seed=seed, items=sorted(items)):
                differences = compare_layouts(placed, layout)
                at = {d.at.split("/")[0] for d in differences if d.what == "point"}
                self.assertLessEqual(items, at, differences[:5])
                self.assertIs(account_faces(part, view, 1.0).verdict, Verdict.FAIL)
                probe = Probe(view, part, suite.resolution)
                verdicts = {
                    check.id: check.run(probe).verdict
                    for check in suite.checks
                    if check.item in items
                }
                self.assertIn(Verdict.FAIL, verdicts.values(), verdicts)
            judged_parts += 1
            if judged_parts == PER_BUG:
                return
        self.fail(f"{bug}: only {judged_parts} parts it moves were judged")

    def test_a_side_measured_from_the_far_edge(self) -> None:
        self.held("a side measured from the far edge")

    def test_an_edge_measured_to_the_centre(self) -> None:
        self.held("an edge measured to the centre")

    def test_an_offset_the_wrong_way(self) -> None:
        self.held("an offset the wrong way")

    def test_a_pattern_s_pitch_a_tenth_long(self) -> None:
        self.held("a pattern's pitch a tenth long")


# ----------------------------------------------------------------------
# Whole-part transforms
# ----------------------------------------------------------------------
def _turn_z(points: Any) -> Any:
    return np.column_stack([-points[:, 1], points[:, 0], points[:, 2]])


#: How far the part is moved (mm): past face accounting's tolerance, far inside any design tolerance.
_STEP = np.array([0.05, 0.0, 0.0])
#: A mirror across the x = 0 plane.
_MIRROR = np.array([-1.0, 1.0, 1.0])

TRANSFORMS: dict[str, tuple[Callable[[Any], Any], Callable[[Any], Any], bool]] = {
    # name: (the transform, its inverse, whether it mirrors)
    "moved a twentieth of a millimetre": (lambda p: p + _STEP, lambda p: p - _STEP, False),
    "scaled by 1.001": (lambda p: p * 1.001, lambda p: p / 1.001, False),
    "scaled by 25.4": (lambda p: p * 25.4, lambda p: p / 25.4, False),
    "mirrored": (lambda p: p * _MIRROR, lambda p: p * _MIRROR, True),
    "turned 90 degrees": (_turn_z, lambda p: _turn_z(_turn_z(_turn_z(p))), False),
}  # fmt: skip


def same_part(truth: Truth, inverse: Callable[[Any], Any]) -> bool:
    """Whether a transform leaves the part as it was: the same side at 20,000 points round it, seeded."""
    lo, hi = truth.box()
    points = np.random.default_rng(0).uniform(lo - 2, hi + 2, size=(20000, 3))
    sure = ~truth.unsure(points) & ~truth.unsure(
        inverse(points)
    )  # a thread's zone: the truth doesn't say
    return bool(
        np.array_equal(truth.inside(points)[sure], truth.inside(inverse(points))[sure])
    )


@unittest.skipUnless(HAVE_MANIFOLD, "the generated parts are built with manifold3d")
class WholePartTransforms(unittest.TestCase):
    def transformed(self, name: str) -> None:
        forward, inverse, mirrors = TRANSFORMS[name]
        judged_parts = 0
        for seed in (0, 1, 3):
            c = case(seed)
            assert c.truth is not None
            if same_part(c.truth, inverse):
                continue
            vertices, faces = mesh_of(c.truth)
            view = view_of_mesh(
                forward(vertices),
                faces[:, ::-1] if mirrors else faces,
                deflection(c.truth),
            )
            self.assertTrue(view.topology().sound)
            _, part, _ = judged(seed)
            with self.subTest(seed=seed):
                self.assertIs(account_faces(part, view, 1.0).verdict, Verdict.FAIL)
            judged_parts += 1
        self.assertGreaterEqual(judged_parts, 2)

    def test_moved_a_twentieth_of_a_millimetre(self) -> None:
        self.transformed("moved a twentieth of a millimetre")

    def test_scaled_by_1_001(self) -> None:
        self.transformed("scaled by 1.001")

    def test_scaled_by_25_4(self) -> None:
        self.transformed("scaled by 25.4")

    def test_mirrored(self) -> None:
        self.transformed("mirrored")

    def test_turned_90_degrees(self) -> None:
        self.transformed("turned 90 degrees")


# ----------------------------------------------------------------------
# Near-misses
# ----------------------------------------------------------------------
@unittest.skipUnless(HAVE_MANIFOLD, "the generated parts are built with manifold3d")
class NearMisses(unittest.TestCase):
    def passes(self, seed: int, view: ViewProxy) -> None:
        if not view.topology().sound:
            self.skipTest("the mesh library made this part's mesh unsoundly")
        _, part, suite = judged(seed)
        found = account_faces(part, view, 1.0)
        self.assertIs(found.verdict, Verdict.PASS, found.misses[:3])
        probe = Probe(view, part, suite.resolution)
        for check in suite.checks:
            with self.subTest(seed=seed, check=check.id):
                evidence = check.run(probe)
                self.assertIs(evidence.verdict, Verdict.PASS, evidence)

    def test_built_four_times_coarser_and_saying_so(self) -> None:
        c = case(1)
        assert c.truth is not None
        vertices, faces = mesh_of(c.truth, 4 * SAG)
        self.passes(1, view_of_mesh(vertices, faces, deflection(c.truth, 4 * SAG)))

    def test_vertices_jittered_by_up_to_half_the_deflection(self) -> None:
        c = case(3)
        assert c.truth is not None
        vertices, faces = mesh_of(c.truth)
        tolerance = deflection(c.truth)
        rng = np.random.default_rng(8)
        way = rng.normal(size=vertices.shape)
        way /= np.linalg.norm(way, axis=1)[:, None]
        jitter = way * rng.uniform(0.0, tolerance / 2, size=(len(vertices), 1))
        self.passes(3, view_of_mesh(vertices + jitter, faces, tolerance))

    def test_coordinates_rounded_to_float32(self) -> None:
        c = case(0)
        assert c.truth is not None
        vertices, faces = mesh_of(c.truth)
        rounded = vertices.astype(np.float32).astype(np.float64)
        self.passes(0, view_of_mesh(rounded, faces, deflection(c.truth)))


if __name__ == "__main__":
    unittest.main()
