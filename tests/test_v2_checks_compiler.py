"""V2 stage 2, step 6: the check compiler, on every reference part and on random specs.

Every reference part (tests/v2_reference.py), built by hand with
manifold3d, has its spec compiled to checks, and each check must pass on
the part as asked, measured at the part's honest deflection (its widest
circle's polygon's, with room) and fine enough for its tolerance. Rule R1:
every leaf field of every item has a check or says why it can't, the leaves
counted here from the items as drafted, independently of the compiler; and
random specs (tests/v2_specs.py) compile with every leaf accounted for too.
"""

from __future__ import annotations

import functools
import sys
import unittest
from pathlib import Path
from typing import Any

import numpy as np
from forge_checks.classes import Verdict, fine_enough
from forge_checks.compiler import LARGEST_RADIUS, CheckSuite, compile_checks, leaves
from forge_checks.measure import Probe
from forge_checks.mesh import Mesh, MeshView
from forge_checks.oracle import CannotMakeError, Oracle, oracle
from forge_checks.place import place
from forge_checks.view import ViewProxy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_meshes import HAVE_MANIFOLD, triangles
from v2_reference import PARTS, deflection, item, offset, on, through
from v2_specs import a, n, random_drafts, read

#: Fields named in a draft that are not themselves leaves: the item's name and kind, and the words it came from.
_NOT_FIELDS = ("id", "kind", "words")
#: An axis position's dict is one leaf: its side, distance and ``to`` together say where the item is.
_POSITION = frozenset({"offset", "side", "distance", "to", "centred"})


def drafted_leaves(found: dict[str, Any]) -> set[str]:
    """Every leaf field of an item as drafted, by dotted path: a value, a choice, a count, a text, a face, an edge set or a name.

    A value, a choice, a count, ``through``, a text and a fit each carry
    where they came from (``from``); an ``on`` and an edge set name a face
    or edges; a place's position along an axis is one leaf; anything else
    nested (a counterbore, a place, a pattern) is walked into, and an empty
    one gives nothing.
    """
    out: set[str] = set()

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict) and not value:
            return  # nothing given: a place left empty
        if (
            not isinstance(value, dict)
            or "from" in value
            or path in ("on", "edges")
            or set(value) <= _POSITION
        ):
            out.add(path)
            return
        for key, inner in value.items():
            walk(inner, f"{path}.{key}")

    for key, value in found.items():
        if key not in _NOT_FIELDS:
            walk(value, key)
    return out


def assumed(field: str) -> bool:
    """Whether a checked field the draft doesn't name is one the spec assumes or implies: a position or angle left out (centred, at 0 degrees), a thread's whole length and its pitch."""
    return (
        field.startswith("place.")
        and (field.count(".") == 1 or field.endswith(".start"))
    ) or field in ("length", "designation.pitch")


@functools.cache
def compiled(name: str) -> tuple[CheckSuite, Oracle]:
    """A reference part's checks, and its spec's shape."""
    items, _ = PARTS[name]()
    spec = read(items)
    placed = place(spec)
    part = oracle(spec, placed)
    return compile_checks(spec, placed, part), part


def built(name: str) -> Probe:
    """A reference part as built, at its honest deflection, as its checks probe it."""
    items, build = PARTS[name]()
    suite, part = compiled(name)
    view = ViewProxy(
        MeshView(
            Mesh.from_triangles(triangles(build())),
            source="mesh-file",
            deflection=deflection(items),
        )
    )
    return Probe(view, part, suite.resolution)


class Leaves(unittest.TestCase):
    """The compiler's own count of an item's leaves, against the one here."""

    def test_the_compiler_counts_every_leaf_as_drafted(self) -> None:
        for name, make in PARTS.items():
            items, _ = make()
            spec = read(items)
            for drafted in items:
                with self.subTest(part=name, item=drafted["id"]):
                    found = spec.item(drafted["id"])
                    assert found is not None
                    self.assertEqual(set(leaves(found)), drafted_leaves(drafted))

    def test_a_counterbore_a_pattern_and_a_position_are_walked_into(self) -> None:
        drafted = item(
            "h", "hole", on=on("p", "+z"), diameter=a(3), depth=a(2),
            counterbore={"diameter": a(6), "depth": a(1)},
            place={"x": {"side": "-x", "distance": a(5), "to": "edge"},
                   "pattern": {"row": {"axis": {"choose": "y", "from": {"assumed": "a test"}}, "count": n(3),
                                       "pitch": a(8)}}},
        )  # fmt: skip
        self.assertEqual(
            drafted_leaves(drafted),
            {"on", "diameter", "depth", "counterbore.diameter", "counterbore.depth", "place.x",
             "place.pattern.row.axis", "place.pattern.row.count", "place.pattern.row.pitch"},
        )  # fmt: skip


@unittest.skipUnless(HAVE_MANIFOLD, "the reference parts are made with manifold3d")
class ReferenceParts(unittest.TestCase):
    def test_every_leaf_has_a_check_or_a_reason(self) -> None:
        for name, make in PARTS.items():
            items, _ = make()
            suite, _ = compiled(name)
            for drafted in items:
                with self.subTest(part=name, item=drafted["id"]):
                    mine = {c.field for c in suite.checks if c.item == drafted["id"]}
                    told = {u.field for u in suite.unchecked if u.item == drafted["id"]}
                    self.assertLessEqual(drafted_leaves(drafted), mine | told)
                    for field in (mine | told) - drafted_leaves(drafted):
                        self.assertTrue(assumed(field), field)
                    for u in suite.unchecked:
                        self.assertTrue(u.why, u)

    def test_every_check_passes_on_the_part_as_asked(self) -> None:
        for name in PARTS:
            suite, _ = compiled(name)
            probe = built(name)
            self.assertEqual(len({c.id for c in suite.checks}), len(suite.checks), name)
            self.assertLessEqual(suite.radius, LARGEST_RADIUS)
            for check in suite.checks:
                with self.subTest(part=name, check=check.id):
                    found = check.run(probe)
                    self.assertIs(found.verdict, Verdict.PASS, found)
                    if check.tolerance is not None:
                        assert found.measured is not None
                        self.assertTrue(
                            fine_enough(found.measured.width / 2, check.tolerance),
                            found,
                        )


@unittest.skipUnless(HAVE_MANIFOLD, "the reference parts are made with manifold3d")
class RoundingsLaterOnesCut(unittest.TestCase):
    def test_a_stretch_is_checked_where_its_rounding_is_left(self) -> None:
        """Generated part 868: a block's vertical edges rounded, then its bottom edges bevelled 5.528 of its 6.805 height. The fillets are checked where the bevel left them, not all along."""
        from forge_eval.generator import render
        from v2_regressions import REGRESSIONS

        spec = read(list(render(REGRESSIONS[868][1]).items))
        suite = compile_checks(spec, place(spec), oracle(spec, place(spec)))
        spans = [(c.target.start, c.target.end) for c in suite.checks
                 if c.id.startswith("round_body/radius")]  # fmt: skip
        self.assertEqual(len(spans), 4)
        for start, end in spans:
            self.assertAlmostEqual(start, 5.528, delta=6.805 / 64)
            self.assertAlmostEqual(end, 6.805, delta=1e-9)

    def test_a_stretch_is_kept_whole_where_the_oracle_can_t_tell(self) -> None:
        """A post's joint filleted: where its sides' fillets meet at its corners the oracle can't tell (its zones), which says nothing was taken away; each side's fillet is checked all along it, 12 and 8 mm."""
        suite, _ = compiled("post and its joint")
        spans = sorted(c.target.end - c.target.start for c in suite.checks
                       if c.id.startswith("foot/radius"))  # fmt: skip
        self.assertEqual(len(spans), 4)
        for span, side in zip(spans, (8, 8, 12, 12), strict=True):
            self.assertAlmostEqual(span, side, delta=1e-9)


class AWallsThickness(unittest.TestCase):
    def test_is_measured_where_both_its_faces_are_the_part_s(self) -> None:
        """Generated part 4050: a round pocket on a shell's inner wall, 2 mm off its middle, left a sliver of a disc there; the wall is measured nearest its middle where both discs are the part's surface whole. Where nothing covers the middle, it is measured there."""
        from forge_checks.compiler import _WALL_REACH
        from forge_checks.view import Side
        from v2_reference import SAY

        def walls(pocketed: bool) -> list[Any]:
            items = [
                item("box", "block", length=a(60), width=a(30), height=a(20)),
                item(
                    "hollow",
                    "shell",
                    of="box",
                    thickness=a(2),
                    open={"faces": ["+z", "-z"], "from": SAY},
                ),
            ]
            if pocketed:  # 8 mm across, 1.3 deep, its centre 2 mm above the inner +y wall's middle
                items.append(item("dent", "pocket", on=on("box", "inner +y"), shape={"choose": "circle", "from": SAY},
                                  diameter=a(8), depth=a(1.3), place={"z": offset(2)}))  # fmt: skip
            spec = read(items)
            placed = place(spec)
            part = oracle(spec, placed)
            suite = compile_checks(spec, placed, part)
            found = []
            for check in suite.checks:
                if check.item == "hollow" and check.field == "thickness":
                    found.append((check.target, part))
            return found

        for pocketed in (False, True):
            with self.subTest(pocketed=pocketed):
                found = walls(pocketed)
                self.assertEqual(
                    len(found), 4
                )  # the +x, -x, +y and -y walls; +z and -z are open
                for target, part in found:
                    for plane in (target.a, target.b):
                        self.assertEqual(plane.reach, _WALL_REACH)
                        # Its whole disc on the part's surface.
                        n = np.asarray(plane.normal, dtype=float)
                        e1 = (
                            np.cross(n, (0.0, 0.0, 1.0))
                            if abs(n[2]) < 0.9
                            else np.array([1.0, 0.0, 0.0])
                        )
                        e1 /= np.linalg.norm(e1)
                        e2 = np.cross(n, e1)
                        t = np.linspace(0, 2 * np.pi, 24, endpoint=False)
                        disc = np.asarray(plane.point) + 0.95 * _WALL_REACH * (
                            np.cos(t)[:, None] * e1 + np.sin(t)[:, None] * e2
                        )
                        self.assertTrue(np.all(part.classify(disc) == Side.ON), plane)
                y_wall = next(t for t, _ in found if t.a.normal[1] > 0.5)
                # The +y wall's middle is 10 mm up; the pocket (4 mm round 12 mm up) moves the measurement off it, its
                # disc clear of the pocket.
                if pocketed:
                    self.assertGreaterEqual(
                        abs(y_wall.a.point[2] - 12.0), 4.0 + 0.95 * _WALL_REACH
                    )
                else:
                    self.assertAlmostEqual(y_wall.a.point[2], 10.0)


class Outlines(unittest.TestCase):
    """An extrusion's length and what is placed on outline faces are checked; an outline is held by face accounting (docs/V2-stage4.md, 6.6)."""

    def test_their_sizes_and_places_are_checked(self) -> None:
        expected = {
            "outline plate": {("plate", "length"), ("hole", "place.x"), ("hole", "place.y"), ("pocket", "place.x"),
                              ("pocket", "place.y")},
            "knob": {("grip", "place.x")},
            "outlines standing": {("angle", "length"), ("angle", "place.x"), ("pulley", "place.x"), ("eye", "place.x"),
                                  ("eye", "place.y")},
            "rounded angle": {("angle", "length"), ("round", "radius")},
            "rounded ring": {("round", "radius")},
        }  # fmt: skip
        # A rounding a millimetre or less across on other edges differs from the spec's by less than the
        # part's tolerances: no point tells the edges apart, and face accounting holds them (telling.py).
        untold = {
            "rounded angle": {("round", "edges")},
            "rounded ring": {("round", "edges")},
        }
        for name, fields in expected.items():
            with self.subTest(part=name):
                suite, _ = compiled(name)
                self.assertLessEqual(fields, {(c.item, c.field) for c in suite.checks})
                held = {(u.item, u.field): u.held_by for u in suite.unchecked}
                outlines = {
                    (i["id"], "profile")
                    for i in PARTS[name]()[0]
                    if i["kind"] in ("extrusion", "revolution")
                }
                told_not = untold.get(name, set())
                self.assertEqual(
                    {k: v for k, v in held.items() if k in outlines | told_not},
                    dict.fromkeys(outlines | told_not, "face accounting"),
                )
                self.assertTrue(all("no point tells them apart" in u.why for u in suite.unchecked
                                    if (u.item, u.field) in told_not))  # fmt: skip
                self.assertEqual(
                    set(held)
                    - outlines
                    - told_not
                    - {k for k in held if assumed(k[1])},
                    set(),
                )


class ARevolutionsAxis(unittest.TestCase):
    """Generated part 8032: a pulley turned from 0.016 mm off its axis, its longest round side the 0.032 mm bore down its middle, which no circle can be fitted to at the judge's resolution: its place checks held the part as asked. Its axis is fitted to its round side with the most surface, its rim."""

    def test_is_fitted_to_its_side_with_the_most_surface(self) -> None:
        from forge_checks.judge import Judge
        from forge_eval.generator import render
        from v2_exit4 import _spec
        from v2_regressions import REGRESSIONS

        judge = Judge.of(_spec(render(REGRESSIONS[8032][1]).items))
        placed = [
            c
            for c in judge.suite.checks
            if c.item == "i3" and c.field.startswith("place.")
        ]
        self.assertEqual({c.field for c in placed}, {"place.x", "place.z"})
        for check in placed:
            with self.subTest(check.id):
                round_side = check.target.item.round  # type: ignore[attr-defined]
                self.assertAlmostEqual(round_side.radius, 3.138)
                self.assertFalse(round_side.inside)


class FinerWhereSmall(unittest.TestCase):
    """The coverage radius is half the smallest size where its item is, 0.5 mm elsewhere (docs/V2-stage4.md, 13.10)."""

    def test_a_small_hole_asks_for_a_finer_radius_round_itself_alone(self) -> None:
        items = [
            item("plate", "block", length=a(80), width=a(50), height=a(5)),
            item("pin", "hole", on=on("plate", "+z"), diameter=a(0.6), depth=a(0.8), place={"x": offset(20)}),
            item("bore", "hole", on=on("plate", "+z"), diameter=a(6), depth=through(), place={"x": offset(-20)}),
        ]  # fmt: skip
        spec = read(items)
        placed = place(spec)
        suite = compile_checks(spec, placed, oracle(spec, placed))
        self.assertEqual(suite.radius, LARGEST_RADIUS)
        self.assertEqual({f.item for f in suite.finer}, {"pin"})
        (finer,) = suite.finer
        self.assertEqual(finer.radius, 0.15)  # half its radius, the size a hole notes
        # Round the pin's own solid, grown by the largest radius and its size: a few millimetres, not the plate.
        lo, hi = np.array(finer.box.lo), np.array(finer.box.hi)
        self.assertTrue(np.all(hi - lo < 4.0), (lo, hi))
        self.assertTrue(
            np.all(lo <= (20.0, 0.0, 4.2)) and np.all(hi >= (20.0, 0.0, 5.0))
        )
        self.assertEqual(
            suite.resolution.at(
                np.array([[20.0, 0.0, 5.0], [-20.0, 0.0, 5.0]])
            ).tolist(),
            [0.15, 0.5],
        )

    def test_with_no_small_size_no_finer_box(self) -> None:
        for name in PARTS:
            suite, _ = compiled(name)
            if suite.radius == LARGEST_RADIUS:
                self.assertTrue(
                    all(f.radius < LARGEST_RADIUS for f in suite.finer), name
                )


class RandomSpecs(unittest.TestCase):
    """Rule R1 on specs no one picked: each compiles, every leaf of every item accounted for."""

    def account(self, seed: int) -> None:
        for k, items in enumerate(random_drafts(seed, 3, 6)):
            spec = read(items)
            placed = place(spec)
            try:
                part = oracle(spec, placed)
            except CannotMakeError:
                continue  # a spec the judge can't make is held before anything is built
            suite = compile_checks(spec, placed, part)
            self.assertEqual(len({c.id for c in suite.checks}), len(suite.checks))
            covered = {(c.item, c.field) for c in suite.checks}
            covered |= {(u.item, u.field) for u in suite.unchecked}
            for drafted in items:
                with self.subTest(seed=seed, spec=k, item=drafted["id"]):
                    want = {(drafted["id"], f) for f in drafted_leaves(drafted)}
                    self.assertLessEqual(want, covered)

    def test_seed_1(self) -> None:
        self.account(1)

    def test_seed_2(self) -> None:
        self.account(2)

    def test_seed_3(self) -> None:
        self.account(3)


if __name__ == "__main__":
    unittest.main()
