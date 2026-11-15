"""V2 stage 4: the references roundings are written with, and what they find (docs/V2-stage4.md, 2.4 and 4.7).

- **In ForgeIR v2:** several edge queries made at once (``queries``,
  ``at_least``), a query held by a circle's ``centre`` and by the stretch
  it may find (``within``), each query's count from 0; read back as
  written, and what is malformed refused.
- **In the kernel:** each query finds its edges and is held to its own
  count; the queries together to ``at_least``; an edge that runs past the
  stretch its query means (onto what is joined to it) is refused, never
  dropped; an edge that meets the chosen ones smoothly and that no query
  names is refused, never rounded unasked.
- **The compiler's queries** on the reference parts: every rounding is
  written as queries between named faces, each held to its stretch, and
  builds its round or bevel faces; and in the harder cases (after an
  earlier rounding of the corners, a joint flush with the face's edge or
  under an overhang, a hollowed body's rim) the part built is accounted
  for against the spec: every edge the definitions round, and no other.
"""

from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forge_ir import SchemaError
from forge_ir.v2 import DocumentV2, EdgeQueries, document_schema_v2
from test_v2_occ_ops import box, built, mm, step
from test_v2_plan import PLATE, confirmed, item
from v2_occ import needs_occ
from v2_specs import SAY, a

try:
    import jsonschema
except (
    ImportError
):  # documents are checked against the schema only where it is installed
    jsonschema = None

try:
    from forge_occ.errors import RefError
    from forge_occ.occt import volume
except ImportError:  # no OpenCascade here: the kernel's classes are skipped
    pass

BODY = box("body", (40, 30, 10))


def between(a: str, b: str, count: tuple[int, int], **where: Any) -> dict[str, Any]:
    query: dict[str, Any] = {
        "between": [
            {"created_by": "body", "role": a},
            {"created_by": "body", "role": b},
        ],
        "match": {"count": list(count)},
    }
    if where:
        query["where"] = where
    return query


def document(edges: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0", "document_id": "t", "project_id": "t", "revision": 1, "name": "t",
        "components": [{"id": "part", "steps": [BODY, step("part", "fillet", ("body",), radius=mm(2), edges=edges)]}],
    }  # fmt: skip


def reference(edges: dict[str, Any]) -> Any:
    return (
        DocumentV2.from_json(json.dumps(document(edges)))
        .step("part", "part")
        .references["edges"]
    )


def errors(edges: dict[str, Any]) -> list[str]:
    try:
        DocumentV2.from_json(json.dumps(document(edges)))
    except SchemaError as error:
        found = getattr(error, "errors", None) or [error]
        return [e.message for e in found]
    raise AssertionError("the decoder took it")


TOP_FRONT = between(
    "z_max",
    "y_min",
    (0, 1),
    kind="line",
    axis=[1, 0, 0],
    within=[[-1, -1, 9], [41, 1, 11]],
)
TOP_RIGHT = between("z_max", "x_max", (0, 1), kind="line", through=[40, 0, 10])


class InForgeIR(unittest.TestCase):
    def test_several_queries_read_back_as_written(self) -> None:
        edges = {"queries": [TOP_FRONT, TOP_RIGHT], "at_least": 2}
        found = reference(edges)
        self.assertIsInstance(found, EdgeQueries)
        self.assertEqual(found.at_least, 2)
        self.assertEqual(found.queries[0].match.count, (0, 1))
        self.assertEqual(
            found.queries[0].where.within, ((-1.0, -1.0, 9.0), (41.0, 1.0, 11.0))
        )
        self.assertEqual(found.as_json()["at_least"], 2)
        again = reference(found.as_json())
        self.assertEqual(again.as_json(), found.as_json())

    def test_a_circle_by_its_centre(self) -> None:
        query = between(
            "z_max", "x_max", (1, 1), kind="circle", centre=[1, 2, 3], radius_mm=4
        )
        self.assertEqual(reference(query).where.centre, (1.0, 2.0, 3.0))

    def test_what_is_malformed(self) -> None:
        self.assertTrue(errors({"queries": []}))
        self.assertTrue(errors({"queries": [TOP_FRONT], "at_least": 0}))
        backwards = between("z_max", "y_min", (1, 1), within=[[41, 1, 11], [-1, -1, 9]])
        self.assertTrue(any("least corner" in m for m in errors(backwards)))
        # A lone query finds at least one edge; one of several may find none.
        self.assertTrue(errors(between("z_max", "y_min", (0, 1))))

    @unittest.skipIf(jsonschema is None, "jsonschema isn't installed")
    def test_the_schema_takes_them(self) -> None:
        validator = jsonschema.Draft202012Validator(document_schema_v2())
        self.assertEqual(
            list(
                validator.iter_errors(
                    document({"queries": [TOP_FRONT, TOP_RIGHT], "at_least": 1})
                )
            ),
            [],
        )
        self.assertFalse(
            validator.is_valid(document({"queries": [TOP_FRONT], "at_least": 0}))
        )


@needs_occ
class InTheKernel(unittest.TestCase):
    def fillet(
        self, edges: dict[str, Any], *steps: dict[str, Any], on: str = "body"
    ) -> Any:
        return built(
            BODY, *steps, step("part", "fillet", (on,), radius=mm(2), edges=edges)
        )

    def test_each_query_finds_its_edges(self) -> None:
        # The front and back top edges: parallel, meeting at no corner, so each takes its own section away.
        back = between("z_max", "y_max", (0, 1), kind="line", through=[0, 30, 10])
        result = self.fillet({"queries": [TOP_FRONT, back], "at_least": 2})
        self.assertAlmostEqual(
            12000 - volume(result.shape), 2 * 40 * 4 * (1 - math.pi / 4), delta=1e-6
        )

    def test_a_query_may_find_none_but_all_together_at_least(self) -> None:
        gone = between(
            "z_max", "y_min", (0, 1), kind="line", axis=[0, 1, 0]
        )  # none runs that way
        result = self.fillet({"queries": [gone, TOP_RIGHT], "at_least": 1})
        self.assertAlmostEqual(
            12000 - volume(result.shape), 30 * 4 * (1 - math.pi / 4), delta=1e-6
        )
        with self.assertRaisesRegex(RefError, "at least 2"):
            self.fillet({"queries": [gone, TOP_RIGHT], "at_least": 2})

    def test_each_query_is_held_to_its_own_count(self) -> None:
        two = between("z_max", "y_min", (2, 2))
        with self.assertRaisesRegex(RefError, "found 1, the reference allows 2 to 2"):
            self.fillet({"queries": [two, TOP_RIGHT], "at_least": 1})

    def test_an_edge_past_its_stretch_is_refused_never_dropped(self) -> None:
        # A second block joined flush on the right: the union carries the front top edge on past x = 40.
        more = box("more", (20, 30, 10), (40, 0, 0))
        joined = step("joined", "union", ("body", "more"))
        front = between(
            "z_max", "y_min", (1, 1), kind="line", within=[[-1, -1, 9], [41, 1, 11]]
        )
        with self.assertRaisesRegex(RefError, "past the stretch"):
            built(
                BODY,
                more,
                joined,
                step(
                    "part",
                    "fillet",
                    ("joined",),
                    radius=mm(2),
                    edges={"queries": [front]},
                ),
            )

    def test_an_edge_met_smoothly_and_unnamed_is_refused(self) -> None:
        # The top edges rounded first; then one vertical edge, which runs on smoothly into the rounding's mitre.
        tops = {
            "of": {"created_by": "body", "role": "z_max"},
            "match": {"count": [4, 4]},
        }
        rounded = step("rounded", "fillet", ("body",), radius=mm(3), edges=tops)
        corner = {"between": [{"created_by": "body", "role": "x_max"}, {"created_by": "body", "role": "y_max"}],
                  "match": {"count": [1, 1]}}  # fmt: skip
        with self.assertRaisesRegex(
            RefError, "meet the chosen ones smoothly and no query names them"
        ):
            built(
                BODY,
                rounded,
                step(
                    "part",
                    "chamfer",
                    ("rounded",),
                    distance=mm(2),
                    edges={"queries": [corner]},
                ),
            )


@needs_occ
class TheCompilersQueries(unittest.TestCase):
    """Every rounding of the reference parts is written as queries between named faces, each held to its stretch, and builds: its round or bevel faces made."""

    def test_the_reference_parts(self) -> None:
        from forge_occ.backend import OccBackend
        from forge_plan import plan
        from test_v2_plan import LATER, NEEDS_AN_ALTERNATIVE, confirmed
        from v2_reference import PARTS

        for name, make in PARTS.items():
            if name in LATER or name in NEEDS_AN_ALTERNATIVE:
                continue
            items, _ = make()
            document = plan(confirmed(items)).document()
            rounding = [
                s for s in document.steps("part") if s.op in ("fillet", "chamfer")
            ]
            if not rounding:
                continue
            with self.subTest(part=name):
                result = OccBackend().build(document, "part")
                for found in rounding:
                    edges = found.references["edges"]
                    self.assertIsInstance(edges, EdgeQueries)
                    self.assertGreaterEqual(edges.at_least, 1)
                    for query in edges.queries:
                        self.assertIsNotNone(query.between, found.id)
                        self.assertIsNotNone(query.where.within, found.id)
                    made = {n.role for n in result.names.every() if n.step == found.id}
                    self.assertIn(
                        "round" if found.op == "fillet" else "bevel", made, found.id
                    )


@needs_occ
class EdgeSetsInTheirHarderCases(unittest.TestCase):
    """Built through the build loop and accounted for against the spec: every edge the definitions round, and no other."""

    def account(self, items: list[dict[str, Any]]) -> dict[str, str]:
        from forge_checks.accounting import account_faces
        from forge_checks.classes import Verdict
        from forge_checks.oracle import oracle
        from forge_checks.place import place
        from forge_checks.view import ViewProxy
        from forge_occ.planned import build_plan
        from forge_occ.view import BrepView
        from forge_plan import plan

        spec = confirmed(items)
        built = build_plan(plan(spec))
        self.assertIsNone(built.gap)
        assert built.result is not None
        part = oracle(spec.spec, place(spec.spec))
        found = account_faces(part, ViewProxy(BrepView(built.result.shape)), 1.0)
        self.assertIs(found.verdict, Verdict.PASS, found.misses[:3])
        return dict(built.made_by)

    def test_after_an_earlier_rounding_of_the_corners(self) -> None:

        block = item("box", "block", length=a(40), width=a(30), height=a(20))
        self.account([block, item("v", "fillet", edges={"of": "box", "which": "vertical"}, radius=a(4)),
                      item("t", "fillet", edges={"of": "box", "which": "top"}, radius=a(2))])  # fmt: skip
        self.account([block, item("v", "chamfer", edges={"of": "box", "which": "vertical"}, size=a(3)),
                      item("t", "chamfer", edges={"of": "box", "which": "top"}, size=a(1))])  # fmt: skip

    def test_a_joint_flush_to_the_face_s_edge(self) -> None:

        for place in (
            {"x": {"offset": a(35)}},
            {"x": {"offset": a(35)}, "y": {"offset": a(20)}},
        ):
            post = item("post", "post", on={"item": "plate", "face": "+z"}, length=a(10), width=a(10),
                        height=a(10), place=place)  # fmt: skip
            joint = item(
                "f",
                "fillet",
                edges={"of": "post", "which": "joint", "where_meets": "plate"},
                radius=a(2),
            )
            with self.subTest(place=place):
                self.assertEqual(self.account([PLATE, post, joint])["f"], "on_the_part")

    def test_a_joint_under_an_overhang(self) -> None:
        over = item("b", "block", on={"item": "plate", "face": "+z"}, length=a(20), width=a(20), height=a(10),
                    place={"x": {"offset": a(35)}})  # fmt: skip
        joint = item(
            "f",
            "fillet",
            edges={"of": "b", "which": "joint", "where_meets": "plate"},
            radius=a(2),
        )
        self.assertEqual(self.account([PLATE, over, joint])["f"], "regions")

    def test_a_hollowed_body_s_rim(self) -> None:

        block = item("box", "block", length=a(40), width=a(30), height=a(20))
        shell = item(
            "s", "shell", of="box", thickness=a(3), open={"faces": ["+z"], "from": SAY}
        )
        self.account(
            [
                block,
                shell,
                item("r", "fillet", edges={"of": "box", "which": "top"}, radius=a(1)),
            ]
        )


if __name__ == "__main__":
    unittest.main()
