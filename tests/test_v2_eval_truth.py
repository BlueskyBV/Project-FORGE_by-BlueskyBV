"""V2 stage 2, step 7: generated parts, their truth, and the three placements tested against each other.

The generator (forge_eval.generator) makes parts no one picked, and works out
from the definitions alone where every copy goes and what solid the part is
(forge_eval.truth), sharing nothing with the placement solver, the judge's
placement or the oracle. So:

- the **three placements** agree: on every copy of every generated part, the
  solver's, the judge's and the generator's points, directions and axes;
- the **impossible** parts end CAN'T: the solver turns each back, and the
  judge too where it is its own rule that is broken (a cut off its face);
- the **oracle** agrees with the truth on which side of the part every point
  is (away from its surface);
- built with manifold3d from the truth, a generated part is a **reference
  part**: its mesh passes face accounting at its honest deflection, and every
  check compiled from its spec passes;
- **rule R1, a mutant per leaf:** for every leaf field of every item, the
  part with that one value changed beyond its tolerance, accepted by the
  solver as a part of its own, is rejected by that leaf's own checks, or by
  face accounting where that alone holds it (a line's words) (a change that
  leaves the shape as it was, a hole through moved to the far face, is no
  mutant: face accounting says so).

A mesh the mesh library makes unsoundly (two solids meeting in a degenerate
way, by chance) is no fair reference: such parts are counted and skipped, and
must stay rare.
"""

from __future__ import annotations

import functools
import re
import sys
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from forge_checks.accounting import account_faces
from forge_checks.classes import Verdict
from forge_checks.compiler import CheckSuite, compile_checks
from forge_checks.measure import Probe
from forge_checks.mesh import Mesh, MeshView
from forge_checks.oracle import Oracle, oracle
from forge_checks.place import PlaceError, place
from forge_checks.view import Side, ViewProxy
from forge_eval.generator import (
    Case,
    DoesNotFitError,
    draft_of,
    generate,
    impossible,
    mutants,
    render,
)
from forge_eval.truth import Outline2, Truth
from forge_spec.draft import read_draft
from forge_spec.placement import solve

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_meshes import HAVE_MANIFOLD
from v2_regressions import REFUSED, REGRESSIONS
from v2_truth import deflection, meshed

#: The generated parts the reference-part and mutant tests build, by seed: the first twelve, and
#: each that once found a fault in the judge, kept as its plan (tests/v2_regressions.py).
BUILT = (*range(12), *REGRESSIONS)
#: The generated parts whose leaves are each mutated (each a test of its own).
MUTATED = (1, 3, 5, 9)


def _standing(kind: str) -> Callable[[Case], bool]:
    return lambda c: any(f.kind == kind and f.on is not None for f in c.plan)


def _hollowed(kind: str, inside: bool = False) -> Callable[[Case], bool]:
    def test(c: Case) -> bool:
        if not any(f.kind == "shell" for f in c.plan) or c.plan[0].kind != kind:
            return False
        return not inside or any(
            f.on is not None and f.on[1].startswith("inner") for f in c.plan
        )

    return test


def _rounded(kind: str, which: str, how: str = "") -> Callable[[Case], bool]:
    def test(c: Case) -> bool:
        kinds = {f.id: f.kind for f in c.plan}
        return any(f.kind in (how or ("fillet", "chamfer")) and kinds.get(f.of or "") == kind
                   and f.choices.get("which") == which for f in c.plan)  # fmt: skip

    return test


#: The sorts of part stage 4 widened the generator to draw (docs/V2-stage4.md, 12.2), each tested on the first
#: generated part that is one (of the first thousand; most sorts are among the first 200, and their counts there
#: are tested).
WIDENED: dict[str, Callable[[Case], bool]] = {
    "an extrusion standing": _standing("extrusion"),
    "a revolution standing": _standing("revolution"),
    "a block hollowed, things in it": _hollowed("block", inside=True),
    "a cylinder hollowed": _hollowed("cylinder"),
    "a dome hollowed": _hollowed("sphere"),
    "a block's edges all rounded": _rounded("block", "all"),
    "a block's top edges rounded": _rounded("block", "top"),
    "a pocket's floor bevelled": _rounded("pocket", "bottom", "chamfer"),
    "a pocket's floor rounded": _rounded("pocket", "bottom", "fillet"),
    "a joint rounded": lambda c: (
        _rounded("boss", "joint")(c) or _rounded("post", "joint")(c)
    ),
    "a hole's mouth rounded": _rounded("hole", "top"),
    "a box's edges rounded twice": lambda c: any(
        f.id.endswith("_also") for f in c.plan
    ),
    "a block hollowed round its rounded corners": lambda c: (
        _hollowed("block")(c) and _rounded("block", "vertical")(c)
    ),
    "a box standing flush with an edge": lambda c: any(_flush(f) == 1 for f in c.plan),
    "a box standing flush in a corner": lambda c: any(_flush(f) == 2 for f in c.plan),
    "a block overhanging its face": lambda c: _overhangs(c),
    "a boss touching a face's edge": lambda c: any(
        f.kind == "boss" and _flush(f) for f in c.plan
    ),
    "a boss or a post standing round a rod": lambda c: any(
        f.kind in ("boss", "post") and f.on is not None and f.on[1] == "side"
        for f in c.plan
    ),
    # 4b.0c, 1b's third move, step 5.1: a block standing on a face hollowed, upright or turned in it.
    "a block standing on a face hollowed": lambda c: _standing_hollowed(c, turned=False),
    "a block turned in its face hollowed": lambda c: _standing_hollowed(c, turned=True),
    # Item 3b's first two steps: round a side at any angle; on a ball's or a dome's surface.
    "a boss or a post round a side at any angle": lambda c: any(
        f.on is not None and f.on[1] == "side" and f.kind in ("boss", "post") and (f.angle or 0.0) % 90
        for f in c.plan
    ),
    "on a ball's or a dome's surface": lambda c: any(f.on is not None and f.on[1] == "surface" for f in c.plan),
}


def _standing_hollowed(c: Case, turned: bool) -> bool:
    """Whether a shell hollows a block standing on a face, turned in it or not."""
    by = {f.id: f for f in c.plan}
    return any(f.kind == "shell" and by[f.of].on is not None and bool(by[f.of].turn) is turned
               for f in c.plan if f.of in by)  # fmt: skip


def _overhangs(c: Case) -> bool:
    """Whether a block standing on a face reaches past it (its truth's box past the face's edges)."""
    from forge_eval.generator import _build, _overhang

    for i, f in enumerate(c.plan):
        if f.kind != "block" or f.on is None or f.pattern is not None:
            continue
        face = _build(c.plan[:i], True).flats.get((f.on[0], 0, f.on[1]))
        if face is None:
            continue
        assert c.truth is not None
        point = c.truth.copies[f.id][0].point
        at = tuple(float(point["xyz".index(a)]) for a in face.axes)
        if _overhang(f, face, [face.foot(f, (at[0], at[1]))], False):
            return True
    return False


def _flush(f: Any) -> int:
    """How many of the face's sides an item stands flush with."""
    return sum(p.mode == "side" and p.distance == 0 for p in f.place.values())


@functools.cache
def first_of(sort: str) -> int:
    """The first generated part of a sort (:data:`WIDENED`)."""
    return next(seed for seed in range(1000) if WIDENED[sort](generated(seed)))


def first_mutable(sort: str, kinds: tuple[str, ...], least: int) -> int:
    """The first generated part of a sort with at least ``least`` leaves of its items of these ``kinds`` that a change makes another valid part of (a part's own fit may leave few)."""
    for seed in range(1000):
        found = generated(seed)
        if seed in REGRESSIONS or not WIDENED[sort](found):
            continue
        kind = {f.id: f.kind for f in found.plan}
        if sum(kind[item] in kinds for (item, _), _ in mutants(found)) >= least:
            return seed
    raise AssertionError(f"no part of the sort {sort!r} has {least} such leaves")


#: How many of a part's leaves are mutated, at most: spread over its items.
LEAVES = 10


def same_shape(one: Case, other: Case, item: str) -> bool:
    """Whether two parts are the same where the item is in either: at 4000 points in each box round its solids, seeded."""
    assert one.truth is not None and other.truth is not None
    rng = np.random.default_rng(0)
    for truth in (one.truth, other.truth):
        for step in truth.steps:
            if step.item != item:
                continue
            lo, hi = _box(step)
            points = rng.uniform(lo - 0.5, hi + 0.5, size=(4000, 3))
            sure = ~one.truth.unsure(points) & ~other.truth.unsure(points)
            if not np.array_equal(
                one.truth.inside(points)[sure], other.truth.inside(points)[sure]
            ):
                return False
    return True


def _box(step: Any) -> tuple[Any, Any]:
    """A box round a step's solid, added or taken away."""
    return Truth({}, (replace(step, add=True),)).box()


def unsaid(x: Any) -> Any:
    """A draft, or a part of one, without its citations: what it says, not where in the brief it says it."""
    if isinstance(x, dict):
        return {k: unsaid(v) for k, v in x.items() if k not in ("words", "from")}
    if isinstance(x, list):
        return [unsaid(v) for v in x]
    return x


def spec_of(items: tuple[dict[str, Any], ...]) -> Any:
    spec, problems = read_draft(draft_of(items))
    assert spec is not None and not problems.faults, [str(p) for p in problems.faults]
    return spec


@functools.cache
def generated(seed: int) -> Case:
    return generate(seed)


@functools.cache
def case(seed: int) -> Case:
    """A part the reference-part and mutant tests build, by its seed: generated, or, one that once found a fault, from its kept plan."""
    if seed in REGRESSIONS:
        # As made when it was found: some were made before the generator kept round solids
        # crossing cleanly, and it holds them to no rule they weren't made by.
        return render(REGRESSIONS[seed][1], strict=False)
    return generated(seed)


@functools.cache
def judged(seed: int) -> tuple[CheckSuite, Oracle]:
    spec = spec_of(case(seed).items)
    placed = place(spec)
    part = oracle(spec, placed)
    return compile_checks(spec, placed, part), part


def view_of(c: Case) -> ViewProxy:
    """The generated part's mesh, each triangle said to be as far off the true surface as it may be (v2_truth.meshed)."""
    assert c.truth is not None
    soup, each = meshed(c.truth)
    return ViewProxy(
        MeshView(Mesh.from_triangles(soup), source="mesh-file", deflection=each)
    )


class AnOutlineFollowed(unittest.TestCase):
    def test_once_for_each_step_and_not_to_be_written_to(self) -> None:
        """The generator follows a profile face's outline for every footprint it tries there: made once a step."""
        square = Outline2((0.0, 0.0), (((2.0, 0.0), None, False), ((2.0, 2.0), None, False),
                                       ((0.0, 2.0), (1.0, 1.0), False), ((0.0, 0.0), None, False)))  # fmt: skip
        points = square.followed(0.5)
        self.assertIs(square.followed(0.5), points)
        self.assertIsNot(square.followed(0.25), points)
        self.assertFalse(points.flags.writeable)
        np.testing.assert_allclose(points[[0, -1]], [(0.0, 0.0), (0.0, 0.0)])


class RoundedEdgesThePartCovers(unittest.TestCase):
    """Generated part 9906: a post standing out from a block's side, flush with its foot, lies along the end of the body the block stands on. Its two lower vertical edges lie on that end: no edges of the part, and the definition rounds nothing there; the truth took the rounding's corner from both, and graded the part Forge rightly built 0.68 mm3 too full. It rounds only the edges the part made so far leaves bare, and refuses a plan where something lies against part of one."""

    @staticmethod
    def plan(body_length: float) -> tuple[Any, ...]:
        from forge_eval.generator import Feature, Position

        def item(id: str, kind: str, sizes: dict[str, float], **more: Any) -> Feature:
            fields: dict[str, Any] = {"on": None, "depth": None, "choices": {}, "recess": None, "place": {},
                                      "angle": None, "pattern": None, "outline": None, "words": None, "of": None,
                                      "faces": None}  # fmt: skip
            return Feature(id=id, kind=kind, sizes=sizes, **{**fields, **more})

        middle = Position(mode="none", distance=0.0, side="", to="centre")
        return (
            item("body", "block", {"length": body_length, "width": 30.0, "height": 10.0}),
            item("i1", "block", {"length": 4.0, "width": 6.0, "height": 11.0}, on=("body", "+z"),
                 place={"x": middle, "y": middle}),
            item("i2", "post", {"length": 3.0, "width": 3.0, "height": 7.0}, on=("i1", "-x"),
                 place={"y": Position(mode="offset", distance=0.0, side="", to="centre"),
                        "z": Position(mode="side", distance=0.0, side="-z", to="edge")}),
            item("round", "fillet", {"radius": 0.35}, choices={"which": "vertical"}, of="i2"),
        )  # fmt: skip

    def test_the_edges_lying_on_the_body_are_not_rounded(self) -> None:
        # The post runs from x = -2 to -9 on the body's top (z = 10); its upper edges are 3 mm up.
        case = render(self.plan(40.0))
        starts = [s.solid.start for s in case.truth.steps if s.item == "round"]
        self.assertEqual(sorted(starts), [(-2.0, -1.5, 13.0), (-2.0, 1.5, 13.0)])

    def test_one_lying_on_part_of_an_edge_is_refused(self) -> None:
        # The body 14 mm long: the post's lower edges lie on it from x = -2 to -7 only, and overhang past.
        with self.assertRaisesRegex(
            DoesNotFitError, "something lies against part of an edge of i2"
        ):
            render(self.plan(14.0))


class ARodOffAnotherItemsWall(unittest.TestCase):
    """Held-out part 10849: holes drilled down from a block's top, the last row's side exactly on a pocket's wall; the part touched itself along lines, no solid. A round rod and another item's flat wall it runs along are apart or cross, by 0.01 mm."""

    @staticmethod
    def plan(y: float, *, boss: bool = False) -> tuple[Any, ...]:
        from forge_eval.generator import Feature, Position

        def item(id: str, kind: str, sizes: dict[str, float], **more: Any) -> Feature:
            fields: dict[str, Any] = {"on": None, "depth": None, "choices": {}, "recess": None, "place": {},
                                      "angle": None, "pattern": None, "outline": None, "words": None, "of": None,
                                      "faces": None}  # fmt: skip
            return Feature(id=id, kind=kind, sizes=sizes, **{**fields, **more})

        middle = Position(mode="none", distance=0.0, side="", to="centre")
        body = item("body", "block", {"length": 40.0, "width": 30.0, "height": 20.0})
        if boss:  # a boss flush with its own host's +y side, along z: meant
            return (body, item("i0", "boss", {"diameter": 4.0, "height": 5.0}, on=("body", "+z"),
                               place={"x": middle, "y": Position(mode="side", distance=0.0, side="+y", to="edge")}))  # fmt: skip
        # A pocket 6 mm wide across y, 5 mm deep, in the top; a 4 mm hole along x, 3 mm under the top, at ``y``.
        return (
            body,
            item("i0", "pocket", {"length": 10.0, "width": 6.0}, on=("body", "+z"), depth=5.0,
                 choices={"shape": "rectangle"}, place={"x": middle, "y": middle}),
            item("i1", "hole", {"diameter": 4.0}, on=("body", "+x"), depth=30.0,
                 place={"y": Position(mode="offset", distance=y, side="", to="centre"),
                        "z": Position(mode="offset", distance=7.0, side="", to="centre")}),
        )  # fmt: skip

    def test_tangent_to_the_wall_is_refused(self) -> None:
        # Its side on the pocket's +y wall (y = 3), and 0.005 mm either way.
        touching = "i1 touches i0's wall along a line"
        for y in (5.0, 5.005, 4.995):
            with self.subTest(y=y), self.assertRaisesRegex(DoesNotFitError, touching):
                render(self.plan(y))

    def test_apart_or_across_it_stands(self) -> None:
        for y in (5.02, 4.98, 7.0, 3.0):
            with self.subTest(y=y):
                render(self.plan(y))
        render(self.plan(0.0, boss=True))


class PlansNowRefused(unittest.TestCase):
    """Plans the generator once made and now refuses (tests/v2_regressions.py's ``REFUSED``), each for what was wrong with it."""

    def test_each_is_refused(self) -> None:
        for seed, (what, why, plan) in REFUSED.items():
            with (
                self.subTest(seed=seed, what=what),
                self.assertRaisesRegex(DoesNotFitError, re.escape(why)),
            ):
                render(plan)

    def test_a_box_pressed_against_a_wall_after_a_hole_in_it(self) -> None:
        """319's, its block placed last: the wall's hole keeps it off where the hole is."""
        _, _, plan = REFUSED[319]
        later = (*(f for f in plan if f.id != "i0"), *(f for f in plan if f.id == "i0"))
        with self.assertRaisesRegex(DoesNotFitError, "i0 would be pressed against"):
            render(later)

    def test_what_is_sunk_under_its_face_fills_nothing(self) -> None:
        """2995's: a whole ball sunk in a block's top over a hole right through the block is refused; clear of the hole's air, it stands."""
        from forge_eval.generator import Feature, _ball, _stands_in_air
        from forge_eval.truth import Copy, Prism, Step, Turned

        x, y, z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
        block = Step("body", 0, True, Prism((0.0, 0.0, 0.0), x, y, z, (15.0, 10.0), 0.0, 0.0, 10.0))  # fmt: skip
        # A hole 2 mm across right through the block along y, 7 mm up.
        hole = Step("i1", 0, False, Prism((0.0, -10.0, 7.0), x, z, y, (1.0, 1.0), 1.0, -0.05, 20.05))  # fmt: skip
        ball = Feature(id="i2", kind="sphere", sizes={"diameter": 10.0}, on=("body", "+z"), depth=None,
                       choices={"portion": "whole"}, recess=None, place={}, angle=None, pattern=None,
                       outline=None, words=None, of=None, faces=None)  # fmt: skip

        def sunk_at(along: float) -> None:
            copy = Copy("i2", 0, ("body", 0, "+z"), (along, 0.0, 10.0), z, ("x", "y"))
            step = Step("i2", 0, True, Turned((along, 0.0, 10.0), z, _ball(ball)))
            _stands_in_air(ball, [copy], [step], [block, hole])

        # 3 mm off the hole's line, the ball's lower half (to 5 mm up) is across the hole: refused.
        with self.assertRaisesRegex(DoesNotFitError, "i2 would fill what is cut into"):
            sunk_at(3.0)
        # 9 mm off, its nearest is 9.5 mm from the hole's axis, past its 5 mm and the hole's 1: it stands.
        sunk_at(9.0)

    def test_under_a_flared_cone_s_top(self) -> None:
        """3375's: on a cone's top wider than its base, past the base's radius only the cone is under it, down to its flank."""
        from forge_eval.generator import _Flat, _Foot

        # A cone 8 mm across at its base and 12 at its top, 6 mm long, on 10 mm of material.
        top = _Flat(("i0", 0, "+end"), np.array([0.0, 0.0, 16.0]), np.array([0.0, 0.0, 1.0]), ("x", "y"), "disc",
                    (6.0, 6.0), 16.0, None, flare=(4.0, 6.0))  # fmt: skip
        # Within the base's radius (a 1 mm hole 2 mm out: 3 mm at most): the cone and what is under it.
        self.assertEqual(top.material_under(_Foot((2.0, 0.0), (1.0, 1.0), 1.0)), 16.0)
        # 5 mm out at most (a 1 mm hole 4 mm out along x, its box's corner hypot(5, 1)): the flank is under it.
        widest = float(np.hypot(5.0, 1.0))
        self.assertAlmostEqual(
            top.material_under(_Foot((4.0, 0.0), (1.0, 1.0), 1.0)), 6.0 * (6.0 - widest) / 2.0
        )

    def test_a_cut_through_a_turned_far_face_comes_out_where_it_is(self) -> None:
        """1436's: a footprint on a turned item's far face, as the face its cut comes out on reads it: at the same
        point along the cut, the box round it along that face's axes, a disc a disc."""
        from forge_eval.generator import _Flat, _Foot, _on_exit

        near = _Flat(("i0", 0, "-z"), np.array([0.0, 0.0, -8.0]), np.array([0.0, 0.0, -1.0]), ("x", "y"), "rect",
                     (6.0, 4.0), 18.0, ("body", 0, "+z"), turn=90.0)  # fmt: skip
        far = _Flat(("body", 0, "+z"), np.array([0.0, 0.0, 10.0]), np.array([0.0, 0.0, 1.0]), ("x", "y"), "rect",
                    (20.0, 20.0), 10.0, None)  # fmt: skip
        # Turned a quarter turn, its first axis is the part's y and its second the part's -x.
        moved = _on_exit(near, far, _Foot((3.0, 1.0), (2.0, 0.5), 0.0))
        self.assertEqual((moved.at, moved.half, moved.corner), ((-1.0, 3.0), (0.5, 2.0), 0.0))
        disc = _on_exit(near, far, _Foot((3.0, 1.0), (1.0, 1.0), 1.0))
        self.assertEqual((disc.at, disc.half, disc.corner), ((-1.0, 3.0), (1.0, 1.0), 1.0))
        self.assertIs(_on_exit(far, far, disc), disc)  # the same axes: as it is

    def test_a_cut_s_side_is_built(self) -> None:
        """3151's: a hole whose bore lies wholly in a pocket cut from another face is refused; partly in it, it stands."""
        from types import SimpleNamespace

        from forge_eval.generator import _cuts_sided
        from forge_eval.truth import Prism, Step

        x, y, z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
        block = Step("body", 0, True, Prism((0.0, 0.0, 0.0), x, y, z, (15.0, 10.0), 0.0, 0.0, 10.0))  # fmt: skip
        # A pocket 4 mm along x and 4 mm up, from the block's -y face 15 mm deep along y.
        pocket = Step("i1", 0, False, Prism((0.0, -10.0, 5.0), x, z, y, (2.0, 2.0), 0.5, 0.0, 15.0))  # fmt: skip
        plan: Any = [SimpleNamespace(id=i, kind=k) for i, k in (("body", "block"), ("i1", "pocket"), ("i2", "hole"))]  # fmt: skip

        def hole_at(along: float) -> Truth:
            # A hole 1 mm across and 3.5 mm deep down from the top at ``along`` on y, over the pocket's middle
            # in x; the pocket's top is 3 mm under the top, so over it the hole only breaks into it.
            hole = Step("i2", 0, False, Prism((0.0, along, 10.0), x, y, z, (0.5, 0.5), 0.5, -3.5, 0.0))  # fmt: skip
            return Truth({}, (block, pocket, hole))

        _cuts_sided(plan, hole_at(8.0))
        # Clear of the pocket, and over it: its bore past 3 mm down is the pocket's air, its top 3 mm built.
        _cuts_sided(plan, hole_at(-4.0))
        # A hole wholly in the pocket's room: from the pocket's top down, nothing of its side is built.
        inside = Step("i2", 0, False, Prism((0.0, -4.0, 6.5), x, y, z, (0.5, 0.5), 0.5, -1.0, 0.0))  # fmt: skip
        with self.assertRaisesRegex(
            DoesNotFitError, "i2's side is all but nowhere built"
        ):
            _cuts_sided(plan, Truth({}, (block, pocket, inside)))


class ThreePlacements(unittest.TestCase):
    def test_every_copy_is_where_all_three_put_it(self) -> None:
        for seed in range(150):
            c = generated(seed)
            assert c.truth is not None
            spec = spec_of(c.items)
            layout = solve(spec)
            self.assertEqual([str(i) for i in layout.issues], [], seed)
            placed = place(spec)
            for item, copies in c.truth.copies.items():
                with self.subTest(seed=seed, item=item):
                    judge = placed.copies[item]
                    solver = layout.instances[item]
                    self.assertEqual(len(judge), len(copies))
                    self.assertEqual(len(solver), len(copies))
                    for truth, mine, theirs in zip(copies, judge, solver, strict=True):
                        self.assertEqual(
                            (truth.host, truth.axes), (mine.host, mine.axes)
                        )
                        np.testing.assert_allclose(truth.point, mine.point, atol=1e-6)
                        np.testing.assert_allclose(
                            truth.direction, mine.direction, atol=1e-9
                        )
                        np.testing.assert_allclose(
                            truth.point, theirs.origin, atol=1e-6
                        )
                        np.testing.assert_allclose(
                            truth.direction, theirs.normal, atol=1e-9
                        )

    def test_every_draft_passes_the_spec_checks(self) -> None:
        """The first 150 generated drafts, checked on their briefs as an automatic run checks them (docs/V2-stage4.md, 12.1): the spec checks (every value follows from the words it cites, every word of the brief is used, a rounding no bigger than the edge it rounds, a thread on what takes one, ...) find nothing to say, and nothing is assumed but where the brief leaves an item (or a circle's first copy) unsaid, or letters it can't quote."""
        from forge_spec import number_words
        from forge_spec.checks import check_draft

        for seed in range(150):
            c = generated(seed)
            report = check_draft(number_words(c.brief), draft_of(c.items), strict=True)
            with self.subTest(seed=seed):
                self.assertEqual([str(p) for p in report.problems], [])
                self.assertEqual([str(p) for p in report.caveats], [])
                for a in report.assumptions:
                    unsaid_ = a.message.endswith("the brief doesn't say where")
                    first = (
                        a.at.endswith("/pattern/circle") and " starts at " in a.message
                    )
                    drawn = (
                        a.at.endswith("/text")
                        and "as drawn with the brief" in a.message
                    )
                    self.assertTrue(unsaid_ or first or drawn, a)

    def test_the_impossible_ones_end_cant(self) -> None:
        """Each is turned back, and to the person, as their brief's would be: every value it rests on is the brief's (12.1), so nothing routes back to the spec writer as its own fault."""
        from forge_spec import number_words
        from forge_spec.checks import check_draft

        # And 870's: deeper than its face's material, a boss's height round a tube's side, was not impossible.
        for seed in (*range(30), 870):
            c = impossible(seed)
            with self.subTest(seed=seed, why=c.cant):
                self.assertIsNone(c.truth)
                spec, problems = read_draft(draft_of(c.items))
                self.assertTrue(spec is None or problems.faults or solve(spec).issues)
                report = check_draft(number_words(c.brief), draft_of(c.items), strict=True)
                kinds = {p.kind for p in report.problems}
                self.assertNotIn("fault", kinds, report.problems)
                said = [
                    p.message for p in report.problems if p.kind in ("question", "cant")
                ]
                # The reason the generator gave, in the solver's words.
                reason = {"its copies overlap": " overlap", "it runs off its face": "runs past the edge",
                          "it is deeper than the material under it": "mm of material"}[c.cant or ""]  # fmt: skip
                self.assertTrue(any(reason in m for m in said), said)
                if c.cant == "it runs off its face":
                    assert spec is not None
                    with self.assertRaises(PlaceError):
                        place(spec)

    def test_every_mutant_is_a_part_the_solver_takes(self) -> None:
        """Every leaf's mutant of 60 parts: its draft reads, the solver places it with no issue, and it differs in that leaf alone."""
        found = 0
        for seed in range(60):
            c = generated(seed)
            for (item, leaf), mutant in mutants(c):
                with self.subTest(seed=seed, item=item, leaf=leaf):
                    spec, problems = read_draft(draft_of(mutant.items))
                    self.assertFalse(problems.faults, [str(p) for p in problems.faults])
                    assert spec is not None
                    self.assertEqual([str(i) for i in solve(spec).issues], [])
                    changed = [
                        a
                        for a, b in zip(c.items, mutant.items, strict=True)
                        if unsaid(a) != unsaid(b)
                    ]
                    self.assertEqual([d["id"] for d in changed], [item])
                    found += 1
        self.assertGreater(found, 1500)

    def test_the_oracle_and_the_truth_agree_on_every_side(self) -> None:
        for seed in range(10):
            c = generated(seed)
            assert c.truth is not None
            spec = spec_of(c.items)
            part = oracle(spec, place(spec))
            lo, hi = c.truth.box()
            points = np.random.default_rng(seed).uniform(
                lo - 2, hi + 2, size=(20000, 3)
            )
            truth = c.truth.inside(points)
            steady = ~c.truth.unsure(points)  # a thread's zone: the truth doesn't say
            for step in (
                np.vstack([np.eye(3), -np.eye(3)]) * 2e-3
            ):  # away from the surface
                steady &= c.truth.inside(points + step) == truth
            sides = part.classify(points)
            sure = steady & np.isin(sides, (Side.IN, Side.OUT))
            with self.subTest(seed=seed):
                self.assertGreater(int(sure.sum()), 19000)
                self.assertEqual(int(np.sum(sure & ((sides == Side.IN) != truth))), 0)


class TheBriefs(unittest.TestCase):
    """Each generated part's brief (docs/V2-stage4.md, 12.1): one sentence per item, every value of its draft citing the words that say it."""

    def test_the_names_say_nothing_but_whose_they_are(self) -> None:
        from forge_eval.generator import NAMES
        from forge_spec.accounting import FUNCTION_WORDS
        from forge_spec.citations import NUMBER_WORDS, is_numeric_word, unit_of_word
        from forge_spec.schema import KINDS

        options = {
            word.lower()
            for kind in KINDS.values()
            for f in kind.fields
            for words in (f.synonyms or {}).values()
            for word in words
        }
        self.assertEqual(len(set(NAMES)), len(NAMES))
        for name in NAMES:
            plain = name.lower()
            with self.subTest(name=name):
                self.assertNotIn(plain, FUNCTION_WORDS | NUMBER_WORDS | options)
                self.assertFalse(is_numeric_word(name))
                self.assertIsNone(unit_of_word(plain))

    def test_each_item_is_said_in_a_sentence_of_its_own(self) -> None:
        from forge_spec import number_words

        for seed in range(40):
            c = generated(seed)
            brief = number_words(c.brief)
            with self.subTest(seed=seed):
                self.assertEqual(len(brief.sentences), len(c.items))
                for n, item in enumerate(c.items):
                    self.assertEqual(
                        {brief.word(i).sentence for i in item["words"]}, {n}
                    )

    def test_a_brief_reads_as_a_person_s_would(self) -> None:
        first = generated(1).brief.split(". ")[:2]
        self.assertEqual(first, [
            "The body is a block 107.795 mm long, 75.826 mm wide and 11.377 mm tall",
            "Boss Alpha is a boss 3.598 mm across and 5.796 mm tall, on the -y face of the body, offset -30.505 mm "
            "along x, offset -0.459 mm along z",
        ])  # fmt: skip

    def test_a_value_its_words_don_t_say_is_a_fault(self) -> None:
        """The citations are the brief's own: a value changed in the draft alone no longer follows from its words."""
        from forge_spec import number_words
        from forge_spec.checks import check_draft

        c = generated(1)
        items = [dict(d) for d in c.items]
        items[0]["length"] = {**items[0]["length"], "value": 107.8}
        report = check_draft(number_words(c.brief), draft_of(items), strict=True)
        self.assertEqual(
            [(p.kind, p.at) for p in report.problems if p.kind == "fault"],
            [("fault", "/items/0/length")],
        )

    def test_letters_no_quotation_holds_are_drawn(self) -> None:
        """A line with a quote mark in it, or a full stop, can't be quoted whole: the brief points to a drawing, and the draft assumes it."""
        marks = set("\"'.!?;\u201c\u201d")
        lines = (f for s in range(400) for f in generated(s).plan if f.kind == "text")
        line = next(f for f in lines if set(f.words or "") & marks)
        c = next(generated(s) for s in range(400) if line in generated(s).plan)
        draft = next(d for d in c.items if d["id"] == line.id)
        said = {
            "text": line.words,
            "from": {"assumed": "the letters as drawn with the brief"},
        }
        self.assertEqual(draft["text"], said)
        self.assertIn("lettering as drawn with this brief", c.brief)


class LinesOfLetters(unittest.TestCase):
    """The generator's letters (forge_eval.truth.Letters, its own reading of the font) and its lettered parts (docs/V2-stage4.md, 12.2)."""

    def test_the_truth_s_letters_are_the_judge_s(self) -> None:
        from forge_checks.letters import Ink
        from forge_eval.truth import Letters, ink_box
        from forge_spec.font import text_width
        from forge_spec.letters import ink_box as solvers_box

        rng = np.random.default_rng(4)
        for words in (
            "FORGE \u00c7&j",
            "@%&\u00a9\u00ae",
            "gjpqy",
            "__--__",
            "\u00c7\u00c7\u00d88",
        ):
            with self.subTest(words=words):
                ink = Ink.of(words, 7.0)
                assert ink.box is not None
                self.assertEqual(ink_box(words, 7.0), ink.box)
                self.assertEqual(ink_box(words, 7.0), solvers_box(words, 7.0))
                (x0, y0), (x1, y1) = ink.box
                x, y = (
                    rng.uniform(x0 - 1, x1 + 1, 20000),
                    rng.uniform(y0 - 1, y1 + 1, 20000),
                )
                # Laid out about the line's box's centre, in a tilted plane, pushed 1 mm.
                right, up = np.array([0.6, 0.8, 0.0]), np.array([0.0, 0.0, 1.0])
                centre = np.array([5.0, -3.0, 2.0])
                letters = Letters(
                    tuple(centre), tuple(right), tuple(up), words, 7.0, -1.0, 0.0
                )
                normal = np.asarray(letters.normal)
                points = (centre + (x - text_width(words, 7.0) / 2)[:, None] * right
                          + (y - 3.5)[:, None] * up - 0.5 * normal)  # fmt: skip
                clear = ink.distance(x, y) > 1e-9
                self.assertTrue(
                    np.array_equal(
                        letters.contains(points)[clear], ink.inside(x, y)[clear]
                    )
                )
                self.assertFalse(letters.contains(points + 0.6 * normal).any())

    def test_a_line_is_drawn_now_and_then_and_its_leaves_are_mutated(self) -> None:
        lettered = [
            seed
            for seed in range(100)
            if any(f.kind == "text" for f in generated(seed).plan)
        ]
        self.assertTrue(20 <= len(lettered) <= 40, len(lettered))
        c = generated(lettered[0])
        line = next(f for f in c.plan if f.kind == "text")
        draft = next(d for d in c.items if d["id"] == line.id)
        self.assertEqual(draft["text"]["text"], line.words)
        self.assertEqual({"height", "depth", "mode", "on"} - set(draft), set())
        leaves = {leaf for (item, leaf), _ in mutants(c) if item == line.id}
        self.assertTrue({"text", "mode", "height", "depth"} <= leaves, leaves)

    def test_a_line_stands_on_material(self) -> None:
        """What is under a line (an engraving's floor, an embossed line's foot) is the part's, GAP deep, whatever cuts it from another face (2511, in REFUSED)."""
        from forge_eval.generator import GAP, _letters_stand
        from forge_eval.truth import Letters, Prism, Step

        x, y, z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
        block = Step("body", 0, True, Prism((0.0, 0.0, 0.0), x, y, z, (15.0, 6.0), 0.0, 0.0, 10.0))  # fmt: skip

        def side_pocket(crest: float) -> Step:
            # A round pocket 5 mm deep into the block's +y face, its crest ``crest`` under the top.
            r = 1.5
            return Step("i1", 0, False, Prism((0.0, 6.0, 10.0 - crest - r), x, z, y, (r, r), r, -5.0, 0.0))  # fmt: skip

        def line(mode: str, depth: float = 1.0) -> Step:
            low, high = (-depth, 0.0) if mode == "engrave" else (0.0, depth)
            return Step("i2", 0, mode == "emboss", Letters((0.0, 3.0, 10.0), x, y, "OD", 3.0, low, high))  # fmt: skip

        def stands(*steps: Step) -> bool:
            try:
                _letters_stand(Truth({}, steps))
            except DoesNotFitError as error:
                self.assertIn(
                    "i2: what is under its letters is cut into by i1", str(error)
                )
                return False
            return True

        # Engraved 1 mm: the floor is 1 mm down, so a crest 1 + GAP down or more leaves it whole.
        self.assertTrue(stands(block, line("engrave")))
        self.assertTrue(stands(block, side_pocket(1.0 + GAP + 0.05), line("engrave")))
        self.assertFalse(stands(block, side_pocket(1.0 + GAP - 0.05), line("engrave")))
        self.assertFalse(stands(block, side_pocket(0.6), line("engrave")))
        # Made after the line, the same.
        self.assertFalse(stands(block, line("engrave"), side_pocket(0.6)))
        # Embossed, its foot is the face: the crest must be GAP under the top.
        self.assertTrue(stands(block, side_pocket(GAP + 0.05), line("emboss")))
        self.assertFalse(stands(block, side_pocket(GAP - 0.05), line("emboss")))


@unittest.skipUnless(HAVE_MANIFOLD, "the generated parts are built with manifold3d")
class GeneratedReferenceParts(unittest.TestCase):
    def built(self, seed: int) -> None:
        suite, part = judged(seed)
        view = view_of(case(seed))
        if not view.topology().sound:
            self.skipTest("the mesh library made this part's mesh unsoundly")
        found = account_faces(part, view, 1.0)
        self.assertIs(found.verdict, Verdict.PASS, found.misses[:3])
        probe = Probe(view, part, suite.resolution)
        for check in suite.checks:
            with self.subTest(seed=seed, check=check.id):
                evidence = check.run(probe)
                self.assertIs(evidence.verdict, Verdict.PASS, evidence)

    def test_meshes_are_seldom_unsound(self) -> None:
        unsound = [
            seed for seed in range(40) if not view_of(generated(seed)).topology().sound
        ]
        self.assertLessEqual(len(unsound), 2, unsound)


@unittest.skipUnless(HAVE_MANIFOLD, "the generated parts are built with manifold3d")
class TheWidenedKinds(unittest.TestCase):
    """What stage 4 widened the generator to draw (docs/V2-stage4.md, 12.2): standing extrusions and revolutions, shells, roundings and bevels."""

    def test_each_is_drawn_now_and_then(self) -> None:
        counts = {
            sort: sum(test(generated(seed)) for seed in range(200))
            for sort, test in WIDENED.items()
        }
        for sort, count in counts.items():
            with self.subTest(sort=sort):
                if sort == "a block hollowed round its rounded corners":
                    self.assertLess(
                        first_of(sort), 1000
                    )  # rarer: a rounding, then a shell
                else:
                    self.assertGreater(count, 0)
        drawn = {
            name: sum(any(f.kind in kinds for f in generated(seed).plan) for seed in range(200))
            for name, kinds in (("profiles", ("extrusion", "revolution")), ("shells", ("shell",)),
                                ("roundings", ("fillet", "chamfer")))
        }  # fmt: skip
        self.assertTrue(25 <= drawn["profiles"] <= 70, drawn)
        self.assertTrue(15 <= drawn["shells"] <= 45, drawn)
        self.assertTrue(55 <= drawn["roundings"] <= 110, drawn)

    def test_their_meshes_are_their_truth(self) -> None:
        """Each sort's first part: its mesh sound, and on the truth's side at 20,000 points away from its surface and its zones."""
        for sort in WIDENED:
            seed = first_of(sort)
            with self.subTest(sort=sort, seed=seed):
                c = generated(seed)
                assert c.truth is not None
                view = view_of(c)
                self.assertTrue(view.topology().sound, view.topology())
                lo, hi = c.truth.box()
                points = np.random.default_rng(seed).uniform(lo - 2, hi + 2, (20000, 3))
                truth = c.truth.inside(points)
                steady = ~c.truth.unsure(points)
                away = 3 * deflection(c.truth) + 1e-3
                for step in np.vstack([np.eye(3), -np.eye(3)]) * away:
                    steady &= c.truth.inside(points + step) == truth
                sides = view.classify(points)
                self.assertGreater(int(steady.sum()), 19000)
                self.assertEqual(int(np.sum(steady & ((sides == Side.IN) != truth))), 0)


def _built_test(seed: int) -> Any:
    def test(self: GeneratedReferenceParts) -> None:
        self.built(seed)

    test.__doc__ = f"Generated part {seed}: accounted for, and every check passes."
    return test


for _seed in BUILT:
    setattr(GeneratedReferenceParts, f"test_part_{_seed}", _built_test(_seed))


@unittest.skipUnless(HAVE_MANIFOLD, "the generated parts are built with manifold3d")
class AMutantPerLeaf(unittest.TestCase):
    def mutated(self, seed: int, kinds: tuple[str, ...] = (), least: int = 6) -> None:
        """A spread of a part's mutants (every item's, a few of each), or every mutant of its items of these ``kinds`` (at least ``least`` of them)."""
        if not view_of(case(seed)).topology().sound:
            self.skipTest("the mesh library made this part's mesh unsoundly")
        suite, part = judged(seed)
        found = list(mutants(case(seed)))
        if kinds:
            kind = {f.id: f.kind for f in case(seed).plan}
            chosen = [(key, m) for key, m in found if kind[key[0]] in kinds]
        else:
            chosen = found[:: max(1, len(found) // LEAVES)][:LEAVES]
        self.assertGreaterEqual(len(chosen), least)
        for (item, leaf), mutant in chosen:
            with self.subTest(seed=seed, item=item, leaf=leaf):
                self.assertEqual(
                    sum(
                        unsaid(a) != unsaid(b)
                        for a, b in zip(case(seed).items, mutant.items, strict=True)
                    ),
                    1,
                )
                self.assertEqual(
                    [str(i) for i in solve(spec_of(mutant.items)).issues], []
                )
                if same_shape(case(seed), mutant, item):
                    continue  # the same shape (a hole through, from the far face): no mutant
                view = view_of(mutant)
                if not view.topology().sound:
                    continue
                probe = Probe(view, part, suite.resolution)
                mine = [c for c in suite.checks if c.item == item and c.field == leaf]
                held = {
                    u.held_by
                    for u in suite.unchecked
                    if u.item == item and u.field == leaf
                }
                verdicts = [c.run(probe).verdict for c in mine]
                if Verdict.FAIL not in verdicts and "face accounting" in held:
                    # Held by face accounting (a line's words, its letters' height; a choice whose other shape
                    # differs by less than the tolerances, which no point tells): it fails there.
                    accounted = account_faces(part, view, 1.0)
                    self.assertIs(accounted.verdict, Verdict.FAIL, (item, leaf))
                    continue
                self.assertIn(Verdict.FAIL, verdicts, (item, leaf, verdicts))

    def test_a_thread_s_and_a_line_s_leaves(self) -> None:
        """Generated part 6, a threaded stud and a line of letters on it: every leaf of the thread's and the line's, mutated, is rejected (by the thread's own checks; by face accounting for the words)."""
        self.mutated(6, ("thread", "text"))

    def test_a_shell_s_leaves(self) -> None:
        """The first hollowed block with things in it whose shell has two leaves to change: each, mutated, is rejected."""
        self.mutated(
            first_mutable("a block hollowed, things in it", ("shell",), 2),
            ("shell",),
            2,
        )

    def test_a_rounding_s_leaves(self) -> None:
        """The first part with a block's edges all rounded and five leaves of its roundings to change (three roundings: each has two at most): each, mutated, is rejected."""
        self.mutated(
            first_mutable("a block's edges all rounded", ("fillet", "chamfer"), 5),
            ("fillet", "chamfer"),
            5,
        )

    def test_standing_outlines_leaves(self) -> None:
        """The first part with a revolution standing and six leaves of its outlines to change: each, mutated, is rejected."""
        self.mutated(
            first_mutable("a revolution standing", ("extrusion", "revolution"), 6),
            ("extrusion", "revolution"),
        )


def _mutant_test(seed: int) -> Any:
    def test(self: AMutantPerLeaf) -> None:
        self.mutated(seed)

    test.__doc__ = (
        f"Generated part {seed}: each mutated leaf is rejected by its own checks."
    )
    return test


for _seed in MUTATED:
    setattr(AMutantPerLeaf, f"test_part_{_seed}", _mutant_test(_seed))


if __name__ == "__main__":
    unittest.main()
