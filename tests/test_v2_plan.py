"""V2 stage 4: the compiler, from a confirmed spec to a ForgeIR v2 document (forge_plan; docs/V2-stage4.md, 4).

- **Every reference part** locks and plans with no gap, into a valid
  document, the same every time, each step owned by the item it is written for, and every face
  of every body and standing item named on each copy.
- **Built by OpenCascade** through the build loop (section 8), each is its
  hand-made reference part: every point farther from the mesh than its
  facets can be, and known exactly to the spec's own shape, is on the same
  side of both.
- **Generated parts** compile and build into their generator's own shape.
- **What it refuses:** a confirmed spec changed after locking; a region is a
  gap for the construction agent; in a draft's preview, an item with an
  issue is a gap, and so is everything that depends on it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forge_checks.oracle import oracle
from forge_checks.place import place
from forge_checks.view import Side
from forge_ir.v2 import DocumentV2
from forge_plan import GapError, PlanError, plan, preview_plan
from forge_spec.checks import check_draft
from forge_spec.lock import ConfirmedSpec, LockError, lock
from forge_spec.schema import KINDS, Category
from forge_spec.words import number_words
from v2_meshes import HAVE_MANIFOLD, triangles, view
from v2_occ import needs_occ
from v2_reference import MARGIN, PARTS, mesh_box
from v2_specs import SAY, WORDS, a, draft, pick

BRIEF = number_words("a random spec")
#: Built by another construction than the first (section 5): OpenCascade refuses its chamfer on the part.
NEEDS_AN_ALTERNATIVE = {"rounded block"}
#: Reference parts compiled in a later step of the stage, and what isn't yet: none now.
LATER: dict[str, str] = {}


def confirmed(items: list[dict[str, Any]]) -> ConfirmedSpec:
    report = check_draft(BRIEF, draft(items), strict=False)
    return lock(report, BRIEF, by="draft", strict=False)


def item(item_id: str, kind: str, **fields: object) -> dict[str, object]:
    return {"id": item_id, "kind": kind, "words": WORDS, **fields}


PLATE = item("plate", "block", length=a(80), width=a(50), height=a(5))


class EveryReferencePart(unittest.TestCase):
    def test_plans_into_one_valid_document(self) -> None:
        for name, make in PARTS.items():
            items, _ = make()
            with self.subTest(part=name):
                if name in LATER:
                    # Not compiled yet: a gap, and the run ends UNABLE for it (4.9).
                    gaps = plan(confirmed(items)).gaps
                    self.assertTrue(gaps)
                    self.assertIn(LATER[name], gaps[0].reason)
                    continue
                found = plan(confirmed(items))
                self.assertEqual(found.gaps, ())
                written = found.written()
                text = written.document.to_json()
                self.assertEqual(DocumentV2.from_json(text).to_json(), text)
                self.assertEqual(plan(confirmed(items)).document().to_json(), text)
                steps = [step.id for step in written.document.steps("part")]
                self.assertEqual(len(steps), len(set(steps)))
                keys = {planned.key for planned in found.items}
                self.assertEqual(set(written.owners), set(steps))
                self.assertLessEqual(set(written.owners.values()), keys)

    def test_the_same_document_whatever_the_process_hashes_with(self) -> None:
        # A set's order changes with PYTHONHASHSEED; a document's never may.
        script = (
            "import hashlib, sys; sys.path.insert(0, 'tests')\n"
            "from forge_plan import plan\nfrom test_v2_plan import LATER, confirmed\n"
            "from v2_reference import PARTS\n"
            "for name, make in PARTS.items():\n"
            "    if name not in LATER:\n"
            "        text = plan(confirmed(make()[0])).document().to_json()\n"
            "        print(name, hashlib.sha256(text.encode()).hexdigest())\n"
        )
        root = Path(__file__).resolve().parent.parent
        found = []
        for seed in ("1", "2"):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            done = subprocess.run([sys.executable, "-c", script], cwd=root, env=env, capture_output=True,
                                  text=True, timeout=600, check=True)  # fmt: skip
            found.append(done.stdout)
        self.assertEqual(found[0], found[1])
        self.assertEqual(len(found[0].splitlines()), len(PARTS) - len(LATER))

    def test_names_every_face_of_every_body_and_standing_item(self) -> None:
        for name, make in PARTS.items():
            if name in LATER:
                continue
            items, _ = make()
            spec = confirmed(items)
            chain = plan(spec).written().chain
            layout = spec.layout
            for found in spec.spec.items:
                if KINDS[found.kind].category not in (Category.BODY, Category.ADD):
                    continue
                for copy in layout.instances.get(found.id, []):
                    names = chain.names_of(found.id, copy.index)
                    with self.subTest(part=name, item=found.id, copy=copy.index):
                        self.assertTrue(names)
                        for face, refs in names.items():
                            self.assertTrue(refs, face)


@needs_occ
@unittest.skipUnless(HAVE_MANIFOLD, "the reference parts are made with manifold3d")
class BuiltTheyAreTheReferenceParts(unittest.TestCase):
    def test_every_reference_part(self) -> None:
        from forge_occ.planned import build_plan
        from forge_occ.view import BrepView

        rng = np.random.default_rng(12)
        for name, make in PARTS.items():
            if name in LATER:
                continue
            items, build = make()
            with self.subTest(part=name):
                spec = confirmed(items)
                made = build_plan(plan(spec))
                self.assertIsNone(made.gap)
                built = made.result
                assert built is not None
                reference = view(triangles(build()))
                part = oracle(spec.spec, place(spec.spec))
                lo, hi = mesh_box(build())
                points = rng.uniform(lo - 3, hi + 3, size=(6000, 3))
                points = points[reference.distance(points) > MARGIN]
                known = part.classify(points) != Side.UNKNOWN
                points = points[known]
                found = BrepView(built.shape).classify(points)
                expected = reference.classify(points)
                wrong = np.flatnonzero(found != expected)
                self.assertEqual(
                    len(wrong),
                    0,
                    (points[wrong[:5]].tolist(), found[wrong[:5]].tolist()),
                )
                self.assertGreater(int((expected == Side.IN).sum()), 100)


@needs_occ
class GeneratedPartsAreTheirGeneratorsShape(unittest.TestCase):
    def test_parts_0_to_7(self) -> None:
        from forge_eval.generator import generate
        from forge_occ.backend import OccBackend
        from forge_occ.view import BrepView
        from forge_plan.planner import _plan
        from forge_spec.placement import solve
        from v2_detection import _spec
        from v2_truth_occ import build

        for seed in range(8):
            case = generate(seed)
            assert case.truth is not None
            spec = _spec(case.items)
            layout = solve(spec)
            with self.subTest(seed=seed):
                self.assertEqual(layout.issues, [])
                built = OccBackend().build(
                    _plan(spec, layout, digest=None).document(), "part"
                )
                lo, hi = case.truth.box()
                points = np.random.default_rng(seed).uniform(
                    np.asarray(lo) - 2, np.asarray(hi) + 2, (4000, 3)
                )
                sides = BrepView(built.shape).classify(points)
                truth = case.truth.inside(points)
                exact = BrepView(build(case.truth)).classify(points)
                settled = (
                    (sides != Side.ON) & (exact != Side.ON) & ~case.truth.unsure(points)
                )
                self.assertEqual(int(((sides == Side.IN) != truth)[settled].sum()), 0)


def _value(raw: Any) -> Any:
    """A step's parameter as plain numbers: a length in mm, a vector's components, an option's name."""
    if hasattr(raw, "components"):
        return tuple(_value(c) for c in raw.components)
    if hasattr(raw, "quantity"):
        return round(float(raw.quantity.magnitude.lo), 9)
    return getattr(raw, "option", raw)


def _steps(
    items: list[dict[str, Any]],
) -> dict[str, tuple[str, dict[str, Any], tuple[str, ...]]]:
    document = plan(confirmed(items)).document()
    return {s.id: (s.op, {k: _value(v) for k, v in s.params.items() if k != "edges"}, tuple(s.inputs))
            for s in document.steps("part")}  # fmt: skip


class ToolsAgainstHandWorkedNumbers(unittest.TestCase):
    """Each tool's steps, at the copy's place, with the numbers worked out by hand from the definitions."""

    def test_a_blind_hole_a_hole_through_and_a_counterbore(self) -> None:
        blind = item("h", "hole", on={"item": "plate", "face": "+z"}, diameter=a(6), depth=a(3),
                     place={"x": {"offset": a(10)}, "y": {"offset": a(-5)}})  # fmt: skip
        through = item("t", "hole", on={"item": "plate", "face": "+z"}, diameter=a(4),
                       depth={"through": True, "from": SAY}, place={"x": {"offset": a(-10)}})  # fmt: skip
        sunk = item("c", "hole", on={"item": "plate", "face": "-z"}, diameter=a(4), depth={"through": True, "from": SAY},
                    counterbore={"diameter": a(8), "depth": a(2)}, place={"x": {"offset": a(25)}})  # fmt: skip
        steps = _steps([PLATE, blind, through, sunk])
        self.assertEqual(steps["h.0.bore"], ("cylinder", {"diameter": 6.0, "height": 3.0, "origin": (10.0, -5.0, 5.0),
                                                          "axis": (0.0, 0.0, -1.0)}, ()))  # fmt: skip
        self.assertEqual(steps["t.0.bore"][1]["height"], 5.0)
        # From the bottom face up: the counterbore 2 deep at the mouth, the bore through.
        self.assertEqual(steps["c.0.bore"][1], {"diameter": 4.0, "height": 5.0, "origin": (25.0, 0.0, 0.0),
                                                "axis": (0.0, 0.0, 1.0)})  # fmt: skip
        self.assertEqual(steps["c.0.counterbore"][1], {"diameter": 8.0, "height": 2.0, "origin": (25.0, 0.0, 0.0),
                                                       "axis": (0.0, 0.0, 1.0)})  # fmt: skip
        self.assertEqual(
            steps["c.cut"], ("subtract", {}, ("t.cut", "c.0.bore", "c.0.counterbore"))
        )

    def test_a_boss_and_a_pocket_from_below(self) -> None:
        boss = item("b", "boss", on={"item": "plate", "face": "+z"}, diameter=a(8), height=a(6),
                    place={"x": {"offset": a(-20)}})  # fmt: skip
        pocket = item("p", "pocket", on={"item": "plate", "face": "-z"}, shape=pick("rectangle"), length=a(12),
                      width=a(6), depth=a(2), corner_radius=a(1))  # fmt: skip
        steps = _steps([PLATE, boss, pocket])
        self.assertEqual(steps["b.0.rod"][1], {"diameter": 8.0, "height": 6.0, "origin": (-20.0, 0.0, 5.0),
                                               "axis": (0.0, 0.0, 1.0)})  # fmt: skip
        self.assertEqual(steps["p.0.plane"][1], {"base": "XY", "offset": 0.0})
        self.assertEqual(steps["p.0.outline"][1], {"width": 12.0, "height": 6.0, "center_u": 0.0, "center_v": 0.0,
                                                   "corner_radius": 1.0})  # fmt: skip
        # Into the plate from its bottom face, along +z: the datum's own normal.
        self.assertEqual(steps["p.0.cut"][1], {"distance": 2.0, "mode": "normal"})
        self.assertEqual(steps["b.join"], ("union", {}, ("plate.0.box", "b.0.rod")))

    def test_a_post_and_a_slot_along_the_other_axis(self) -> None:
        post = item("post", "post", on={"item": "plate", "face": "+z"}, length=a(10), width=a(6), height=a(12),
                    place={"x": {"offset": a(20)}, "y": {"offset": a(5)}})  # fmt: skip
        slot = item("s", "slot", on={"item": "plate", "face": "+z"}, length=a(16), width=a(4), depth=a(2),
                    along=pick("y"), ends=pick("round"), place={"x": {"offset": a(-25)}})  # fmt: skip
        steps = _steps([PLATE, post, slot])
        self.assertEqual(
            steps["post.0.box"][1],
            {"size": (10.0, 6.0, 12.0), "origin": (15.0, 2.0, 5.0)},
        )
        self.assertEqual(steps["s.0.outline"][0], "profile_slot")
        self.assertEqual(steps["s.0.outline"][1], {"length": 16.0, "width": 4.0, "rotation": 90.0,
                                                   "center_u": -25.0, "center_v": 0.0})  # fmt: skip
        self.assertEqual(steps["s.0.plane"][1], {"base": "XY", "offset": 5.0})
        # Down from the top face, against the datum's normal.
        self.assertEqual(steps["s.0.cut"][1], {"distance": 2.0, "mode": "reverse"})


class WhatItRefuses(unittest.TestCase):
    def test_a_confirmed_spec_changed_after_locking(self) -> None:
        spec = confirmed([PLATE])
        changed = ConfirmedSpec(
            spec.spec, spec.layout, spec.brief, "0" * 64, spec.by, spec.assumptions
        )
        with self.assertRaises(LockError):
            plan(changed)

    def test_a_region_is_left_to_the_construction_agent(self) -> None:
        region = item("r", "region", on={"item": "plate", "face": "-z"}, length=a(20), width=a(20), height=a(3),
                      describe={"text": "a grip", "from": SAY}, place={"x": {"offset": a(25)}})  # fmt: skip
        found = plan(confirmed([PLATE, region]))
        self.assertEqual([gap.item for gap in found.gaps], ["r"])
        self.assertEqual([planned.item for planned in found.items], ["plate"])

    def test_a_preview_leaves_an_item_with_an_issue_and_what_depends_on_it(
        self,
    ) -> None:
        # The hole is wider than the plate: an issue. Its rounding depends on it.
        hole = item("h", "hole", on={"item": "plate", "face": "+z"}, diameter=a(90),
                    depth={"through": True, "from": SAY})  # fmt: skip
        rim = item("rim", "chamfer", edges={"of": "h", "which": "top"}, size=a(1))
        report = check_draft(BRIEF, draft([PLATE, hole, rim]), strict=False)
        found = preview_plan(report)
        self.assertEqual({gap.item for gap in found.gaps}, {"h", "rim"})
        self.assertEqual([planned.item for planned in found.items], ["plate"])

    def test_a_preview_names_the_same_dependency_under_any_hash_seed(self) -> None:
        """A rounding of a post's joint with the post under it, both left out: its reason names one of them, the same one in every run (V2-stage4b-0b.md, 6.1)."""
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from test_v2_plan import PLATE, BRIEF, item, draft, a, check_draft, preview_plan; "
            "low = item('b1', 'post', on={'item': 'plate', 'face': '+z'}, length=a(200), width=a(10), height=a(10)); "
            "high = item('b2', 'post', on={'item': 'b1', 'face': '+z'}, length=a(5), width=a(5), height=a(5)); "
            "rim = item('rim', 'fillet', edges={'of': 'b2', 'which': 'joint', 'where_meets': 'b1'}, radius=a(1)); "
            "found = preview_plan(check_draft(BRIEF, draft([PLATE, low, high, rim]), strict=False)); "
            "print(dict((gap.item, gap.reason) for gap in found.gaps)['rim'])"
        )
        here = str(Path(__file__).resolve().parent)
        reasons = set()
        # Before the fix, seeds 1 and 5 named b1 and seeds 0 and 3 named b2.
        for seed in ("0", "1", "3", "5"):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            done = subprocess.run([sys.executable, "-c", script, here], env=env,
                                  capture_output=True, text=True, check=True)  # fmt: skip
            reasons.add(done.stdout.strip())
        self.assertEqual(reasons, {"it depends on b1, which can't be previewed"})

    def test_a_gap_is_a_plan_error(self) -> None:
        self.assertTrue(issubclass(GapError, PlanError))


if __name__ == "__main__":
    unittest.main()
