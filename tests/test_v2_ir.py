"""V2 stage 3: ForgeIR v2, the construction (forge_ir.v2; docs/V2-stage3.md, section 6).

Every recorded V1 document converts to v2 and back with identical JSON, and
its v2 JSON reads back identically; the v2 JSON Schema in ``schemas/`` is the
one the catalogue makes, names every operation, and holds a document as it
is written while refusing an unknown field or operation; v2's own steps
(fillet, chamfer) and references decode, and down-convert to V1 as identities
of their input; and each rule v2 adds to V1's refuses what it should: a
reference to a step its step doesn't build on, a v2 step with two inputs, an
instance of a missing component, two instances or mates with one id, a mate
of an instance with itself, or to an interface that isn't there or doesn't
suit the mate.
"""

from __future__ import annotations

import copy
import itertools
import json
import math
import unittest
from typing import Any

from forge_ir import Document, SchemaError
from forge_ir.v2 import (
    EXAMPLE,
    OPS,
    OUTLINE_CHORD,
    SCHEMA_VERSION_V2,
    V2_ONLY,
    DocumentV2,
    convert_v1,
    document_schema_v2,
)
from v2_occ import CLEVIS_PIN, ROOT, corpus, zoo

SCHEMA = ROOT / "schemas" / "forgeir-2.0.0.schema.json"

try:
    import jsonschema
except ImportError:  # the schema is still checked against the catalogue; documents against it only where it's installed
    jsonschema = None


def _example() -> dict[str, Any]:
    return json.loads(EXAMPLE)


def _decode(payload: dict[str, Any]) -> DocumentV2:
    return DocumentV2.from_json(json.dumps(payload))


def _errors(payload: dict[str, Any]) -> list[str]:
    """Every message the decoder gives for ``payload`` (it must refuse it)."""
    try:
        _decode(payload)
    except SchemaError as error:
        found = getattr(error, "errors", None) or [error]
        return [e.message for e in found]
    raise AssertionError("the document was accepted")


class EveryRecordedDocumentRoundTrips(unittest.TestCase):
    def test_to_v2_and_back_identically(self) -> None:
        documents = corpus()
        self.assertGreaterEqual(len(documents), 149)
        for name, text in documents.items():
            with self.subTest(name):
                v1 = Document.from_json(text)
                v2 = convert_v1(v1)
                self.assertEqual(v2.to_v1().to_json(), v1.to_json())
                again = DocumentV2.from_json(v2.to_json())
                self.assertEqual(again.to_json(), v2.to_json())
                self.assertEqual(again.to_v1().to_json(), v1.to_json())
                self.assertEqual(
                    json.loads(v2.to_json())["schema_version"], SCHEMA_VERSION_V2
                )

    def test_from_any_reads_both(self) -> None:
        text = zoo()["zoo_tray"]
        self.assertEqual(
            DocumentV2.from_any(text).to_json(),
            convert_v1(Document.from_json(text)).to_json(),
        )
        v2 = convert_v1(Document.from_json(text)).to_json()
        self.assertEqual(DocumentV2.from_any(v2).to_json(), v2)


class TheSchema(unittest.TestCase):
    def test_the_file_is_the_catalogues(self) -> None:
        self.assertEqual(json.loads(SCHEMA.read_text(encoding="utf-8")), document_schema_v2(),
                         "regenerate with forge_ir.v2.write_schema_v2('schemas/forgeir-2.0.0.schema.json')")  # fmt: skip

    def test_it_names_every_operation(self) -> None:
        steps = document_schema_v2()["properties"]["components"]["items"]["properties"][
            "steps"
        ]["items"]["oneOf"]
        named = {branch["properties"]["op"]["const"] for branch in steps}
        self.assertEqual(named, set(OPS))

    @unittest.skipIf(jsonschema is None, "jsonschema isn't installed")
    def test_a_document_as_a_model_writes_it_meets_it(self) -> None:
        # The schema is the form a document is written in (V1's authoring schema, the one its
        # designer fills in, with v2's steps, instances and mates), not every canonical form the
        # encoder writes back (V1's quantities in vectors, parameters' tags).
        validator = jsonschema.Draft202012Validator(document_schema_v2())
        self.assertEqual(list(validator.iter_errors(json.loads(EXAMPLE))), [])
        placed = _example()
        placed["instances"] = [{"id": "plate_1", "component": "plate",
                                "at": {"translate": {"vector": [0, 0, 5], "unit": "mm"}, "rotate_axis": [0, 0, 1],
                                       "rotate_angle": {"magnitude": 90, "unit": "deg"}}}]  # fmt: skip
        self.assertEqual(list(validator.iter_errors(placed)), [])
        _decode(placed)
        # A placement by bare numbers has no unit: the schema refuses it, as the decoder does.
        placed["instances"][0]["at"]["translate"] = [0, 0, 5]
        self.assertFalse(validator.is_valid(placed))
        self.assertTrue(
            any("placement can't be worked out" in m for m in _errors(placed))
        )

    @unittest.skipIf(jsonschema is None, "jsonschema isn't installed")
    def test_it_refuses_an_unknown_field_and_an_unknown_op(self) -> None:
        validator = jsonschema.Draft202012Validator(document_schema_v2())
        stray = _example()
        stray["components"][0]["steps"][0]["colour"] = "red"
        self.assertFalse(validator.is_valid(stray))
        odd = _example()
        odd["components"][0]["steps"][1]["op"] = "knurl"
        self.assertFalse(validator.is_valid(odd))


class V2sOwnSteps(unittest.TestCase):
    def test_a_fillet_decodes_with_its_reference(self) -> None:
        document = _decode(_example())
        step = document.step("plate", "round")
        self.assertEqual(step.op, "fillet")
        self.assertTrue(step.v2_only)
        self.assertEqual(step.for_items, ("top_edges",))
        edges = step.references["edges"]
        self.assertIsNotNone(edges.of)
        self.assertEqual((edges.of[0].created_by, edges.of[0].role), ("body", "z_max"))
        self.assertEqual(edges.match.count, (4, 4))
        self.assertEqual(document.v2_only("plate"), ("round",))

    def test_it_reads_back_identically(self) -> None:
        document = _decode(_example())
        self.assertEqual(
            DocumentV2.from_json(document.to_json()).to_json(), document.to_json()
        )

    def test_down_converted_a_fillet_is_its_input_unchanged(self) -> None:
        document = _decode(_example())
        down = document.down_converted()
        feature = down.component("plate").features["round"]
        self.assertEqual(feature.kind, "transform")
        self.assertEqual(feature.inputs, ("body",))
        with self.assertRaises(ValueError):
            document.to_v1()

    def test_every_v2_op_has_its_parameters_and_references(self) -> None:
        self.assertEqual(
            set(V2_ONLY), {"fillet", "chamfer", "profile_outline", "text", "thread"}
        )
        chamfer = _example()
        step = chamfer["components"][0]["steps"][1]
        step["op"] = "chamfer"
        step["params"] = {
            "distance": {"magnitude": 1, "unit": "mm"},
            "edges": step["params"]["edges"],
        }
        self.assertEqual(_decode(chamfer).step("plate", "round").op, "chamfer")

    def test_a_fillet_without_its_edges_is_refused(self) -> None:
        payload = _example()
        del payload["components"][0]["steps"][1]["params"]["edges"]
        self.assertTrue(
            any("needs its `edges` reference" in m for m in _errors(payload))
        )

    def test_references_by_between_where_and_covers(self) -> None:
        payload = _example()
        payload["components"][0]["steps"][1]["params"]["edges"] = {
            "between": [
                {"created_by": "body", "role": "z_max"},
                {"created_by": "body", "role": "x_min"},
            ],
            "where": {"kind": "line", "axis": [0, 1, 0]},
            "match": {"count": [1, 1], "covers": "whole"},
        }
        edges = _decode(payload).step("plate", "round").references["edges"]
        self.assertIsNotNone(edges.between)
        self.assertEqual(edges.where.kind, "line")
        self.assertEqual(edges.match.covers, "whole")


class TheRulesV2Adds(unittest.TestCase):
    def test_a_reference_to_a_step_this_one_doesnt_build_on(self) -> None:
        payload = _example()
        steps = payload["components"][0]["steps"]
        steps.insert(1, {"id": "other", "op": "box", "role": "other",
                         "params": {"size": {"vector": [5, 5, 5], "unit": "mm"}}})  # fmt: skip
        steps[2]["params"]["edges"]["of"]["created_by"] = "other"
        steps.append({"id": "joined", "op": "union", "inputs": ["round", "other"]})
        self.assertTrue(any("doesn't build on" in m for m in _errors(payload)))

    def test_a_v2_step_takes_one_solid(self) -> None:
        payload = _example()
        steps = payload["components"][0]["steps"]
        steps.insert(1, {"id": "other", "op": "box", "role": "other",
                         "params": {"size": {"vector": [5, 5, 5], "unit": "mm"}}})  # fmt: skip
        steps[2]["inputs"] = ["body", "other"]
        self.assertTrue(
            any(
                "wrong number of inputs" in m or "takes one solid" in m
                for m in _errors(payload)
            )
        )

    def test_instances_and_mates(self) -> None:
        base = json.loads(CLEVIS_PIN.read_text(encoding="utf-8"))
        cases: list[tuple[str, Any]] = [
            (
                "an instance of a component the document hasn't",
                lambda p: p["instances"].append(
                    {"id": "ghost", "component": "nothing"}
                ),
            ),
            (
                "two instances share an id",
                lambda p: p["instances"].append(copy.deepcopy(p["instances"][0])),
            ),
            (
                "two mates share an id",
                lambda p: p["mates"].append(copy.deepcopy(p["mates"][0])),
            ),
            (
                "not one to itself",
                lambda p: p["mates"][0]["b"].update(
                    instance=p["mates"][0]["a"]["instance"]
                ),
            ),
            (
                "an interface the instance's component hasn't",
                lambda p: p["mates"][0]["a"].update(interface="nowhere"),
            ),
            (
                "a mate names an instance the document hasn't",
                lambda p: p["mates"][0]["a"].update(instance="ghost"),
            ),
            (
                "a contact mate relates planar_mount interfaces",
                lambda p: p["mates"][1].update(kind="contact", a=p["mates"][0]["a"]),
            ),
            (
                "mates relate instances; the document places none",
                lambda p: p.pop("instances"),
            ),
        ]
        for expected, change in cases:
            with self.subTest(expected):
                payload = copy.deepcopy(base)
                change(payload)
                self.assertTrue(
                    any(expected in m for m in _errors(payload)),
                    (expected, _errors(payload)),
                )

    def test_a_document_with_no_instances_places_each_component_once(self) -> None:
        payload = json.loads(CLEVIS_PIN.read_text(encoding="utf-8"))
        payload.pop("instances")
        payload.pop("mates")
        document = _decode(payload)
        self.assertEqual(
            [(i.id, i.component) for i in document.placed()],
            [("clevis", "clevis"), ("pin", "pin")],
        )

    def test_v1_cant_hold_instances(self) -> None:
        with self.assertRaises(ValueError):
            DocumentV2.from_json(CLEVIS_PIN.read_text(encoding="utf-8")).to_v1()

    def test_a_v1_document_isnt_read_as_v2(self) -> None:
        text = zoo()["zoo_tray"]
        with self.assertRaises(SchemaError):
            DocumentV2.from_json(text)


def _outline(points: list[list[float]]) -> dict[str, Any]:
    """A part made of one outline, extruded."""
    return {"schema_version": SCHEMA_VERSION_V2, "document_id": "outline", "project_id": "forge", "revision": 1,
            "name": "outline", "components": [{"id": "part", "name": "outline", "steps": [
                {"id": "plane", "op": "datum_plane", "params": {"base": "XY", "offset": {"magnitude": 0, "unit": "mm"}}},
                {"id": "outline", "op": "profile_outline", "inputs": ["plane"],
                 "params": {"points": {"points": points, "unit": "mm"}}},
                {"id": "body", "op": "extrude", "inputs": ["outline"],
                 "params": {"distance": {"magnitude": 5, "unit": "mm"}, "mode": "normal"}}]}]}  # fmt: skip


#: A plate 30 x 20 with a bite of radius 9 out of its top edge: the arc to (6, 20) through (15, 11).
BITTEN = [[0, 0], [30, 0], [30, 20], [24, 20], [6, 20, 15, 11], [0, 20], [0, 0]]


class Outlines(unittest.TestCase):
    """``profile_outline``, v2's outline of straight sides and true arcs (docs/V2-stage4.md, 6.5)."""

    def test_v1s_form_is_the_polygon_within_the_chord_of_its_arcs(self) -> None:
        document = _decode(_outline(BITTEN))
        self.assertEqual(document.v2_only("part"), ("outline",))
        feature = document.down_converted().component("part").features["outline"]
        self.assertEqual(feature.kind, "profile_sketch")
        points = [
            tuple(c.quantity.magnitude.lo for c in row)
            for row in feature.parameters["points"].points
        ]
        self.assertEqual(points[:4], [(0, 0), (30, 0), (30, 20), (24, 20)])
        self.assertEqual(points[-2:], [(0, 20), (0, 0)])
        arc = points[3:-2]  # from (24, 20) round the bite to (6, 20)
        for a, b in itertools.pairwise(arc):
            self.assertAlmostEqual(math.dist(a, (15, 20)), 9, places=9)  # on the circle
            middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            self.assertLessEqual(
                9 - math.dist(middle, (15, 20)), OUTLINE_CHORD + 1e-12
            )  # no further off it
        self.assertGreater(len(arc), 20)

    def test_it_reads_back_identically(self) -> None:
        document = _decode(_outline(BITTEN))
        self.assertEqual(
            DocumentV2.from_json(document.to_json()).to_json(), document.to_json()
        )

    @unittest.skipIf(jsonschema is None, "jsonschema isn't installed")
    def test_the_schema_holds_it(self) -> None:
        validator = jsonschema.Draft202012Validator(document_schema_v2())
        self.assertEqual(list(validator.iter_errors(_outline(BITTEN))), [])

    def test_what_is_refused(self) -> None:
        cases = {
            "each side ends at [u, v]": [[0, 0], [30, 0, 1], [30, 20], [0, 0]],
            "an outline starts at [u, v]": [[0, 0, 1, 1], [30, 0], [30, 20], [0, 0]],
            "ends where it starts": [[0, 0], [30, 0], [30, 20], [0, 20]],
            "three points lie on a line": [[0, 0], [30, 0, 15, 0], [30, 20], [0, 0]],
        }
        for expected, points in cases.items():
            with self.subTest(expected):
                self.assertTrue(
                    any(expected in m for m in _errors(_outline(points))),
                    _errors(_outline(points)),
                )
        written = _outline(BITTEN)
        written["components"][0]["steps"][1]["params"]["points"]["points"][1] = [
            {"expression": "2 * 15", "unit": "mm"},
            0,
        ]
        self.assertTrue(any("not expressions" in m for m in _errors(written)))


def _letters(text: str = "FORGE", **params: Any) -> dict[str, Any]:
    """A plate with a line of letters engraved on its top, as v2 writes it."""
    payload = _example()
    steps = payload["components"][0]["steps"]
    steps[1] = {"id": "words", "op": "text", "inputs": ["body"], "for_items": ["label"],
                "params": {"text": text, "height": {"magnitude": 5, "unit": "mm"},
                           "origin": {"vector": [20, 15, 6], "unit": "mm"}, "up": {"vector": [0, 1, 0]},
                           "right": {"vector": [1, 0, 0]}, "depth": {"magnitude": 0.5, "unit": "mm"},
                           "mode": "engrave", **params}}  # fmt: skip
    return payload


class Letters(unittest.TestCase):
    """``text``, v2's line of letters in the pinned font (docs/V2-stage4.md, 7.1): its words as written."""

    def test_its_words_are_kept_as_written(self) -> None:
        document = _decode(_letters("Ø8 — Ç&ç"))
        step = document.step("plate", "words")
        self.assertEqual((step.op, step.strings), ("text", {"text": "Ø8 — Ç&ç"}))
        self.assertEqual(step.params["mode"].as_json(), "engrave")
        self.assertEqual(
            DocumentV2.from_json(document.to_json()).to_json(), document.to_json()
        )
        self.assertEqual(
            document.down_converted().component("plate").features["words"].kind,
            "transform",
        )

    @unittest.skipIf(jsonschema is None, "jsonschema isn't installed")
    def test_the_schema_holds_it(self) -> None:
        validator = jsonschema.Draft202012Validator(document_schema_v2())
        self.assertEqual(list(validator.iter_errors(_letters())), [])
        self.assertNotEqual(list(validator.iter_errors(_letters(mode="stamp"))), [])

    def test_what_is_refused(self) -> None:
        for words, expected in (
            ("", "at least one letter"),
            ("ONE\nTWO", "one line"),
            ("A\tB", "one line"),
        ):
            with self.subTest(words=words):
                self.assertTrue(
                    any(expected in m for m in _errors(_letters(words))),
                    _errors(_letters(words)),
                )
        self.assertTrue(_errors(_letters(mode="stamp")))


if __name__ == "__main__":
    unittest.main()
