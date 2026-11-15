"""V2 stage 4: each item's other constructions, and the build loop that tries them (docs/V2-stage4.md, sections 5 and 8).

- **The same solid:** every alternative whose proof holds, on every
  reference part and on generated parts, builds the very solid the first
  construction builds (their symmetric difference has no volume, and they
  have the same faces): one copy at a time (5.1), carried into the air
  (5.2), sunk into what it stands on (5.3), a dome cut (5.4), a block's
  vertical edges rounded early (5.5).
- **Roundings made otherwise** (5.5, 5.6): the same solid where nothing
  meets them; where roundings meet, judged (face accounting and every
  check) against the spec; a joint under an overhang, which OpenCascade's
  fillet can't make, made as its regions.
- **The proofs refuse** where they don't hold: the air past a cut's mouth
  taken by a tool added before, a foot over a cut, an edge another tool
  covers; past a hole into a round side, the host's own box left out but
  any other tool's in the way, a far end within the carry of the bore's
  axis, a hollow that doesn't hold the hole's span.
- **The build loop** tries the next construction where OpenCascade
  refuses one (or leaves the part in more than one solid), carried first
  for a hole into a round side, searches the earlier items that meet a refused one, records
  every refusal, ends with the refused item as the gap when every way is
  refused, and stops at its bound. The flush hole that OpenCascade 7.9.3
  left in two solids (seed 10517) is cut right by 8.0.1; the fault is put
  back by hand to keep the after-check held to it.
"""

from __future__ import annotations

import copy
import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forge_plan import plan
from forge_plan.tools import CARRY, Context, carried_ways, clear_of, early_applies
from forge_plan.write import Box, Chain
from test_v2_plan import LATER, confirmed, item
from v2_occ import needs_occ
from v2_reference import PARTS, on, side, through
from v2_specs import SAY, a, pick

try:
    from forge_occ.backend import OccBackend
    from forge_occ.errors import OperationError
    from forge_occ.occt import faces, volume
    from forge_occ.planned import build_plan
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
except ImportError:  # no OpenCascade here: the classes that build are skipped
    pass


_TUBE = item("t", "tube", outer_diameter=a(30), inner_diameter=a(20), length=a(40))
_ROD = item("r", "cylinder", diameter=a(20), length=a(40))
_CAN = item("c", "cylinder", diameter=a(30), length=a(40))
_HOLLOW = item(
    "hollow", "shell", of="c", thickness=a(2), open={"faces": [], "from": SAY}
)
_AT = {"angle": a(30, "deg")}


def _hole(face: tuple[str, str], **fields: Any) -> dict[str, Any]:
    return item(
        "h",
        "hole",
        on=on(*face),
        diameter=a(4),
        **{"depth": through(), "place": _AT, **fields},
    )


#: Holes into round sides, each carried into the air (5.2): every way the side's radius proves it.
ROUND_SIDE_HOLES: dict[str, list[dict[str, Any]]] = {
    "through a tube's wall": [_TUBE, _hole(("t", "side"))],
    "into a tube's wall, blind": [_TUBE, _hole(("t", "side"), depth=a(2))],
    "out of a tube's bore": [_TUBE, _hole(("t", "bore"))],
    "across a rod": [_ROD, _hole(("r", "side"))],
    "across a rod, counterbored": [_ROD, _hole(("r", "side"), counterbore={"diameter": a(7), "depth": a(3)})],
    "through a hollowed cylinder's wall": [_CAN, _HOLLOW, _hole(("c", "side"))],
    "out of a hollowed cylinder's hollow": [_CAN, _HOLLOW, _hole(("c", "inner side"))],
}  # fmt: skip


def apart(first: Any, other: Any) -> float:
    """The volume of the symmetric difference of two solids."""
    return float(
        volume(BRepAlgoAPI_Cut(first, other).Shape())
        + volume(BRepAlgoAPI_Cut(other, first).Shape())
    )


@needs_occ
class EveryAlternativeMakesTheSameSolid(unittest.TestCase):
    def check(self, name: str, found: Any) -> int:
        first = OccBackend().build(found.document(), "part").shape
        tried = 0
        for planned in found.items:
            for index in found.applying({}, planned.key)[1:]:
                construction = planned.constructions[index].name
                if construction in (
                    "early",
                    "regions",
                ):  # a rounding made otherwise: judged below
                    continue
                other = (
                    OccBackend()
                    .build(found.document({planned.key: index}), "part")
                    .shape
                )
                with self.subTest(
                    part=name, item=planned.key, construction=construction
                ):
                    self.assertLessEqual(apart(first, other), 1e-6)
                    self.assertEqual(len(faces(first)), len(faces(other)))
                tried += 1
        return tried

    def test_the_reference_parts(self) -> None:
        tried = 0
        for name, make in PARTS.items():
            if name in LATER or name == "rounded block":
                continue
            items, _ = make()
            tried += self.check(name, plan(confirmed(items)))
        self.assertGreater(tried, 25)

    def test_generated_parts(self) -> None:
        from forge_eval.generator import generate
        from forge_plan.planner import _plan
        from forge_spec.placement import solve
        from v2_detection import _spec

        tried = 0
        for seed in range(6):
            case = generate(seed)
            spec = _spec(case.items)
            tried += self.check(
                f"generated {seed}", _plan(spec, solve(spec), digest=None)
            )
        self.assertGreater(tried, 10)

    def test_holes_into_round_sides(self) -> None:
        """Carried into the air from a round side (5.2), the same solid: through a tube's wall from outside and out of its bore, blind into it, across a rod (counterbored too), through a hollowed cylinder's wall from outside and out of its hollow."""
        for name, items in ROUND_SIDE_HOLES.items():
            found = plan(confirmed(items))
            with self.subTest(part=name):
                self.assertEqual(found.applying({}, "h"), [0, 1])
            self.assertGreaterEqual(self.check(name, found), 1)

    def test_vertical_edges_rounded_early(self) -> None:
        block = item("box", "block", length=a(40), width=a(10), height=a(8))
        for kind, size in (
            ("fillet", 2.0),
            ("chamfer", 1.5),
            ("fillet", 5.0),
        ):  # 5: to half the width, a strap
            rounding = item("r", kind, edges={"of": "box", "which": "vertical"},
                            **{"radius" if kind == "fillet" else "size": a(size)})  # fmt: skip
            found = plan(confirmed([block, rounding]))
            self.assertEqual(
                [c.name for c in found.planned("r").constructions],
                ["on_the_part", "early", "regions"],
            )
            self.assertEqual(found.applying({}, "r"), [0, 1, 2])
            early = OccBackend().build(found.document({"r": 1}), "part").shape
            if size < 5.0:
                late = OccBackend().build(found.document(), "part").shape
                self.assertLessEqual(apart(late, early), 1e-6)
            # As the definition takes it: the corners' squares less their quarter discs, or their triangles.
            corner = (
                size * size * ((1 - 3.141592653589793 / 4) if kind == "fillet" else 0.5)
            )
            self.assertAlmostEqual(
                volume(early), 40 * 10 * 8 - 4 * corner * 8, delta=1e-6
            )


@needs_occ
class RoundingsMadeOtherwise(unittest.TestCase):
    """A rounding made early (5.5) or as its regions (5.6): the same where nothing meets it, and where roundings meet, within the oracle's zones: judged."""

    def judge(self, items: list[dict[str, Any]], choice: dict[str, int]) -> None:
        from forge_checks.accounting import account_faces
        from forge_checks.classes import Verdict
        from forge_checks.compiler import compile_checks
        from forge_checks.measure import Probe
        from forge_checks.oracle import oracle
        from forge_checks.place import place
        from forge_checks.view import ViewProxy
        from forge_occ.view import BrepView

        spec = confirmed(items)
        built = OccBackend().build(plan(spec).document(choice), "part")
        placed = place(spec.spec)
        part = oracle(spec.spec, placed)
        view = ViewProxy(BrepView(built.shape))
        self.assertIs(account_faces(part, view, 1.0).verdict, Verdict.PASS)
        suite = compile_checks(spec.spec, placed, part)
        probe = Probe(view, part, suite.resolution)
        failed = [
            check.id
            for check in suite.checks
            if check.run(probe).verdict is not Verdict.PASS
        ]
        self.assertEqual(failed, [])

    def test_a_lone_block_s_edges_as_regions(self) -> None:
        block = item("box", "block", length=a(40), width=a(10), height=a(8))
        for kind, which, size in (
            ("chamfer", "vertical", 1.5),
            ("chamfer", "all", 1.0),
            ("fillet", "bottom", 1.0),
        ):
            rounding = item("r", kind, edges={"of": "box", "which": which},
                            **{"radius" if kind == "fillet" else "size": a(size)})  # fmt: skip
            found = plan(confirmed([block, rounding]))
            regions = [c.name for c in found.planned("r").constructions].index(
                "regions"
            )
            with self.subTest(kind=kind, which=which):
                self.assertIn(regions, found.applying({}, "r"))
                late = OccBackend().build(found.document(), "part").shape
                made = OccBackend().build(found.document({"r": regions}), "part").shape
                if which != "all":  # the same, but where three bevels meet at a corner
                    self.assertLessEqual(apart(late, made), 1e-6)
                self.judge([block, rounding], {"r": regions})

    def test_where_roundings_meet(self) -> None:
        items, _ = PARTS["rounded block"]()
        self.judge(items, {"bevel": 1})  # early
        self.judge(items, {"bevel": 2})  # as its regions
        items, _ = PARTS["post and its joint"]()
        self.judge(items, {"foot": 1, "crown": 1})

    def test_a_joint_under_an_overhang(self) -> None:
        # OpenCascade's fillet can't run from the post's sides on round under its overhang: the regions can.
        plate = item("plate", "block", length=a(80), width=a(50), height=a(5))
        over = item("b", "block", on={"item": "plate", "face": "+z"}, length=a(20), width=a(20), height=a(10),
                    place={"x": {"offset": a(35)}})  # fmt: skip
        joint = item(
            "f",
            "fillet",
            edges={"of": "b", "which": "joint", "where_meets": "plate"},
            radius=a(2),
        )
        built = build_plan(plan(confirmed([plate, over, joint])))
        self.assertIsNone(built.gap)
        self.assertEqual(built.made_by["f"], "regions")
        self.judge([plate, over, joint], dict(built.choice))


class TheProofsRefuse(unittest.TestCase):
    def test_air_taken_by_a_tool_added_before(self) -> None:
        chain = Chain()
        chain.add_box(Box((-20, -20, 0), (20, 20, 5), "plate", 0))
        mouth = ((-3.0, -3.0, 5.0), (3.0, 3.0, 5.0 + CARRY))
        self.assertTrue(clear_of(chain, mouth))
        chain.add_box(Box((-5, -5, 5), (5, 5, 15), "post", 0))
        self.assertFalse(clear_of(chain, mouth))

    def test_air_past_a_hole_into_a_round_side(self) -> None:
        def ways(
            items: list[dict[str, Any]], *boxes: Box, wide: float | None = None
        ) -> tuple[bool, bool]:
            spec = confirmed(items)
            layout = copy.deepcopy(spec.layout)
            if wide is not None:
                layout.diameters["h"] = wide
            chain = Chain()
            for box in boxes:
                chain.add_box(box)
            target = next(i for i in spec.spec.items if i.id == "h")
            (at,) = layout.instances["h"]
            return carried_ways(chain, Context(spec.spec, layout), target, at)

        tube, wall = (
            ROUND_SIDE_HOLES["through a tube's wall"],
            Box((-15, -15, 0), (15, 15, 40), "t", 0),
        )
        # The host's own box holds the hole's air both ends: it is left out, the side's radius standing for it.
        self.assertEqual(ways(tube, wall), (True, True))
        # Another tool in the bore, past the far end: that end isn't carried; one over the mouth too: neither.
        core = Box((5, 0, 15), (11, 10, 25), "core", 0)
        self.assertEqual(ways(tube, wall, core), (True, False))
        self.assertEqual(
            ways(tube, wall, core, Box((12, 5, 15), (16, 12, 25), "lug", 0)),
            (False, False),
        )
        # A hole all but as wide as the bore: its far end's centre within the carry of the axis.
        self.assertEqual(
            ways(tube, wall, wide=2 * math.sqrt(100 - (CARRY / 2) ** 2)), (True, False)
        )
        # Through a hollowed cylinder's wall by its cap: the hollow doesn't hold the hole's span.
        cap = [_CAN, _HOLLOW, _hole(("c", "side"), place={**_AT, "z": side("-z", 2.5)})]
        self.assertEqual(ways(cap), (True, False))
        # Out of a bore: it starts at the axis, its mouth in air already, and only its far end is carried.
        self.assertEqual(
            ways(ROUND_SIDE_HOLES["out of a tube's bore"], wall), (False, True)
        )
        self.assertEqual(
            ways(ROUND_SIDE_HOLES["into a tube's wall, blind"], wall), (True, False)
        )

    def test_an_edge_another_tool_covers(self) -> None:
        block = item("box", "block", length=a(40), width=a(30), height=a(20))
        rounding = item(
            "r", "fillet", edges={"of": "box", "which": "vertical"}, radius=a(2)
        )
        spec = confirmed([block, rounding])
        copies = spec.layout.instances["box"]
        target = spec.spec.items[0]
        chain = Chain()
        chain.add_box(Box((-20, -15, 0), (20, 15, 20), "box", 0))
        self.assertTrue(early_applies(chain, target, copies, 2.0, "r"))
        # A body stacked flush on top touches the edges only at their ends: the rounding stops there either way.
        chain.add_box(Box((-20, -15, 20), (20, 15, 30), "lid", 0))
        self.assertTrue(early_applies(chain, target, copies, 2.0, "r"))
        # A wall flush against a side covers two of the edges.
        chain.add_box(Box((20, -15, 0), (25, 15, 20), "wall", 0))
        self.assertFalse(early_applies(chain, target, copies, 2.0, "r"))

    def test_a_foot_over_a_cut_isnt_sunk(self) -> None:
        plate = item("plate", "block", length=a(60), width=a(40), height=a(5))
        post = item(
            "post",
            "post",
            on={"item": "plate", "face": "+z"},
            length=a(10),
            width=a(10),
            height=a(10),
        )
        # A pocket from below leaving 0.02 mm under the post's foot: less than the carry.
        under = item("pocket", "pocket", on={"item": "plate", "face": "-z"}, shape=pick("rectangle"),
                     length=a(8), width=a(8), depth=a(4.98))  # fmt: skip
        self.assertEqual(plan(confirmed([plate, post])).applying({}, "post"), [0, 1])
        self.assertEqual(
            plan(confirmed([plate, under, post])).applying({}, "post"), [0]
        )


def _refusing(steps: set[str]) -> Any:
    """A backend whose build refuses any document with one of these steps."""
    real = OccBackend.build

    def build(self: Any, document: Any, component: str, **options: Any) -> Any:
        for step in document.steps(component):
            if step.id in steps:
                raise OperationError("refused here, for the test", step=step.id)
        return real(self, document, component, **options)

    return mock.patch.object(OccBackend, "build", build)


@needs_occ
class TheBuildLoop(unittest.TestCase):
    def test_the_rounded_block_is_built_early_and_judged(self) -> None:
        from forge_checks.accounting import account_faces
        from forge_checks.classes import Verdict
        from forge_checks.oracle import oracle
        from forge_checks.place import place
        from forge_checks.view import ViewProxy
        from forge_occ.view import BrepView

        items, _ = PARTS["rounded block"]()
        spec = confirmed(items)
        built = build_plan(plan(spec))
        self.assertIsNone(built.gap)
        self.assertEqual(built.made_by["bevel"], "early")
        self.assertEqual(
            [(r.item, r.construction) for r in built.refusals],
            [("bevel", "on_the_part")],
        )
        self.assertIn("smoothly", built.refusals[0].error["message"])
        assert built.result is not None
        part = oracle(spec.spec, place(spec.spec))
        self.assertIs(
            account_faces(part, ViewProxy(BrepView(built.result.shape)), 1.0).verdict,
            Verdict.PASS,
        )

    def test_the_next_construction_then_the_gap(self) -> None:
        items, _ = PARTS["plate with holes"]()
        found = plan(confirmed(items))
        with _refusing({"corners.cut"}):
            built = build_plan(found)
        self.assertIsNone(built.gap)
        self.assertEqual(built.made_by["corners"], "flush one by one")
        self.assertEqual([r.construction for r in built.refusals], ["flush", "carried"])
        # Every way refused: the plate has no other way to be made, and the holes are the gap.
        everything = {"corners.cut", *(f"corners.cut.{k}" for k in range(4))}
        with _refusing(everything):
            built = build_plan(found)
        self.assertIsNone(built.result)
        assert built.gap is not None
        self.assertEqual(built.gap.item, "corners")
        self.assertEqual(len(built.refusals), 4)

    def test_a_hole_into_a_round_side_is_carried_first(self) -> None:
        """5.2: from outside a round side, the definition's tool touches it along a line; carried goes first there."""
        for name, items in ROUND_SIDE_HOLES.items():
            names = [c.name for c in plan(confirmed(items)).planned("h").constructions]
            outside = "out of" not in name
            with self.subTest(part=name):
                self.assertEqual(
                    names, ["carried", "flush"] if outside else ["flush", "carried"]
                )
        items, _ = PARTS["plate with holes"]()
        self.assertEqual([c.name for c in plan(confirmed(items)).planned("corners").constructions][:2],
                         ["flush", "carried"])  # fmt: skip

    def test_a_cut_that_leaves_the_part_in_two_solids_is_refused(self) -> None:
        """Held-out seed 10517: a blind hole into a tube's wall cut flush, its plug kept beside the part as a second solid with no flag raised. Refused (section 8, step 2); carried, it is built right.

        OpenCascade 7.9.3 kept that plug; 8.0.1 cuts the hole right (the
        next test). The fault is put back here as 7.9.3 made it, the plug
        (what the tool held of the part) beside the cut part, so the
        after-check and the search are still held to it on any kernel.
        """
        import dataclasses

        from forge_occ.cache import StepCache
        from forge_occ.make import compound
        from forge_occ.planned import _Search
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

        class KeepsThePlug:
            def __init__(self, real: Any) -> None:
                self.real = real

            def build(self, document: Any, component: str, **options: Any) -> Any:
                result = self.real.build(document, component, **options)
                made = result.products
                plug = BRepAlgoAPI_Common(
                    made["i4.cut"].shape, made["i5.0.bore"].shape
                ).Shape()
                cut = dataclasses.replace(
                    made["i5.cut"], shape=compound([made["i5.cut"].shape, plug])
                )
                return dataclasses.replace(result, products={**made, "i5.cut": cut})  # fmt: skip

        found = _plan_10517()
        search = _Search(found, StepCache(), 64)
        search.backend = KeepsThePlug(search.backend)
        flush = dict.fromkeys(("i0", "i1", "i2", "i4", "i5"), 1)
        result, refused = search.build(flush)
        self.assertIsNone(result)
        self.assertEqual(refused, "i5")
        first = search.refusals[0]
        self.assertEqual((first.construction, first.step), ("flush", "i5.cut"))
        self.assertIn("2 solids after it", first.error["message"])
        built = build_plan(found)
        self.assertIsNone(built.gap)
        self.assertEqual((built.made_by["i5"], built.refusals), ("carried", ()))

    def test_opencascade_8_cuts_that_flush_hole_right(self) -> None:
        """Held-out seed 10517 on OpenCascade 8.0.1: the flush cut that 7.9.3 left in two solids is one solid, and right.

        The hole (4.552 mm, 1.845 mm deep) is drilled radially into the
        tube's side, its flat mouth touching the side along a line, so the
        cut removes the tool less the sliver of it outside the side, the
        integral of (R - sqrt(R^2 - y^2)) over the mouth. Forge's own
        engine agrees with the part. Carried still goes first (5.2).
        """
        from forge_occ.agreement import agree
        from forge_occ.cache import StepCache
        from forge_occ.planned import _Search

        found = _plan_10517()
        flush = dict.fromkeys(("i0", "i1", "i2", "i4", "i5"), 1)
        self.assertEqual({found.chosen(flush, key).name for key in flush}, {"flush"})
        result, refused = _Search(found, StepCache(), 64).build(flush)
        self.assertIsNone(refused)
        assert result is not None
        self.assertEqual(result.solids, 1)
        volume = {trace.step: trace.volume for trace in result.traces}
        r, big = 4.552 / 2, 88.881 / 2
        steps = 20000  # the midpoint rule over the mouth, y = r sin(t)
        outside = sum(
            (big - math.sqrt(big**2 - (r * math.sin(t)) ** 2)) * 2 * r * math.cos(t) * r * math.cos(t) * (math.pi / steps)
            for t in (-math.pi / 2 + (k + 0.5) * math.pi / steps for k in range(steps))
        )  # fmt: skip
        self.assertAlmostEqual(volume["i5.0.bore"], math.pi * r * r * 1.845, places=6)
        self.assertAlmostEqual(
            volume["i4.cut"] - volume["i5.cut"], volume["i5.0.bore"] - outside, places=5
        )
        self.assertTrue(
            agree(found.written(flush).document, "part", exact=result).holds
        )
        self.assertEqual(build_plan(found).made_by["i5"], "carried")

    def test_a_hole_whose_carrying_doesnt_hold_is_made_by_its_definition(self) -> None:
        """Generated part 4935: a hole through a tube hung from a closed hollow's ceiling, no air past it proven clear.

        Carried goes first for a hole into a round side only where its proof
        holds (5.2). Here it doesn't: the plan writes the definition's, the
        part is built by it, and a refusal of it is the definition's.
        """
        from forge_plan.errors import PlanError

        found = _kept_plan(4935)
        names = [c.name for c in found.planned("i4").constructions]
        self.assertEqual(names, ["carried", "flush"])
        self.assertEqual(found.applying({}, "i4"), [1])
        written = found.written()
        self.assertEqual((written.made["i4"], written.made_by["i4"]), (1, "flush"))
        self.assertIsNone(found.next_choice({}, "i4"))
        with self.assertRaisesRegex(PlanError, "'carried' doesn't apply here"):
            found.written({"i4": 0})
        built = build_plan(found)
        self.assertIsNone(built.gap)
        self.assertEqual((built.made_by["i4"], built.refusals), ("flush", ()))
        with _refusing({"i4.cut"}):
            built = build_plan(found)
        assert built.gap is not None
        self.assertEqual(built.gap.item, "i4")
        first = built.refusals[0]
        self.assertEqual((first.item, first.construction), ("i4", "flush"))

    def test_the_search_tries_the_earlier_items_that_meet_it(self) -> None:
        # The joint's fillet refused, however it is made, until the post under it is made another way (sunk).
        items, _ = PARTS["post and its joint"]()
        found = plan(confirmed(items))
        real = OccBackend.build

        def build(self: Any, document: Any, component: str, **options: Any) -> Any:
            foot = [
                step.id
                for step in document.steps(component)
                if step.id.startswith("foot.")
            ]
            if foot and not _sunk(
                document
            ):  # every way of making the joint, until the post is sunk
                raise OperationError("refused here, for the test", step=foot[-1])
            return real(self, document, component, **options)

        with mock.patch.object(OccBackend, "build", build):
            built = build_plan(found)
        self.assertIsNone(built.gap)
        self.assertEqual(built.made_by["post"], "sunk")
        self.assertEqual(built.refusals[0].item, "foot")

    def test_the_builds_are_bounded(self) -> None:
        items, _ = PARTS["plate with holes"]()
        with _refusing({"corners.cut", *(f"corners.cut.{k}" for k in range(4))}):
            built = build_plan(plan(confirmed(items)), most=2)
        self.assertEqual(built.builds, 2)
        assert built.gap is not None
        self.assertIn("within 2 builds", built.gap.reason)
        with self.assertRaises(ValueError):
            build_plan(plan(confirmed(items)), most=0)


def _plan_10517() -> Any:
    """Held-out seed 10517's plan: a tube with holes and bosses in its side (tests/v2_regressions.py)."""
    return _kept_plan(10517)


def _kept_plan(seed: int) -> Any:
    """A kept generated part's plan (tests/v2_regressions.py)."""
    from forge_eval.generator import render
    from forge_plan.planner import _plan
    from forge_spec.placement import solve
    from v2_detection import _spec
    from v2_regressions import REGRESSIONS

    spec = _spec(render(REGRESSIONS[seed][1]).items)
    return _plan(spec, solve(spec), digest=None)


def _sunk(document: Any) -> bool:
    """Whether the post's box reaches below the plate's top (sunk into it)."""
    post = next(step for step in document.steps("part") if step.id == "post.0.box")
    return (
        float(post.params["origin"].components[2].quantity.value_in("mm")) < 5.0 - 1e-9
    )


if __name__ == "__main__":
    unittest.main()
