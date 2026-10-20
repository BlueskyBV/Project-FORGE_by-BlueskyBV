"""Malformed documents must produce repairable errors, never crashes.

The distinction this file protects is the difference between a run that costs
one repair round and a run that costs everything. A ``SchemaError`` carries a
pointer and a message: the repair loop reads it, patches the document and
carries on. Any other exception travels up through the role, the orchestrator
and the CLI, and takes the run's artefacts with it -- which on a local model is
an hour of generation and nothing on disk.

Every case below is a shape a weak model actually produces. They are asserted
as a class, not individually, because the property that matters is "nothing a
model can write crashes this", and a list of the particular mistakes seen so
far is a weaker claim than it looks.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Callable

from forge_ir import Document, SchemaError, SchemaErrorGroup
from forge_kernel import CompileError, Compiler

BASE: dict[str, Any] = {
    "schema_version": "1.0.0",
    "document_id": "00000000-0000-4000-8000-00000000c001",
    "project_id": "00000000-0000-4000-8000-00000000c0ff",
    "revision": 1,
    "units": {"length": "mm", "mass": "g", "angle": "deg"},
    "risk_class": "low",
    "requirements": [],
    "assumptions": [],
    "components": [{
        "id": "p", "name": "P",
        "parameters": [{"id": "t", "value": {"magnitude": 6, "unit": "mm"}}],
        "features": [{"id": "body", "kind": "box", "parameters": {
            "size": {"vector": [20, 20, "t"], "unit": "mm"}}}],
        "interfaces": [],
    }],
}


def _mutated(mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    payload = json.loads(json.dumps(BASE))
    mutate(payload)
    return payload


def _feature(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["components"][0]["features"][0]


def _value(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["components"][0]["parameters"][0]


#: Documents a model can write that must not decode into a crash. The value is
#: what to do to the base document.
MALFORMED: dict[str, Callable[[dict[str, Any]], None]] = {
    "magnitude is a unit spelled in words":
        lambda d: _value(d).__setitem__("value", {"magnitude": 6, "unit": "millimeters"}),
    "unit is null":
        lambda d: _value(d).__setitem__("value", {"magnitude": 6, "unit": None}),
    "bare number as a component parameter value":
        lambda d: _value(d).__setitem__("value", 6),
    "bare number as a feature parameter":
        lambda d: _feature(d)["parameters"].__setitem__("size", 20),
    "inputs given as a string":
        lambda d: d["components"][0]["features"].append(
            {"id": "u", "kind": "union", "inputs": "body"}),
    "duplicate feature ids":
        lambda d: d["components"][0]["features"].append(dict(_feature(d))),
    "component parameters as an object":
        lambda d: d["components"][0].__setitem__(
            "parameters", {"t": {"magnitude": 6, "unit": "mm"}}),
    "features as an object":
        lambda d: d["components"][0].__setitem__(
            "features", {"body": {"kind": "box"}}),
    "unknown feature kind":
        lambda d: _feature(d).__setitem__("kind", "fillet"),
    "vector with two components":
        lambda d: _feature(d)["parameters"].__setitem__(
            "size", {"vector": [20, 20], "unit": "mm"}),
    "vector holding nulls":
        lambda d: _feature(d)["parameters"].__setitem__(
            "size", {"vector": [20, None, 6], "unit": "mm"}),
    "expression referencing an undeclared name":
        lambda d: _feature(d)["parameters"].__setitem__(
            "size", {"vector": ["nope", 20, 6], "unit": "mm"}),
    "expression with a syntax error":
        lambda d: _value(d).__setitem__("value", {"expression": "6 +", "unit": "mm"}),
    "threshold magnitude is a word":
        lambda d: d.__setitem__("requirements", [{
            "id": "R", "statement": "s", "type": "geometric", "strength": "hard",
            "verification": "exact_geometry",
            "threshold": {"magnitude": "sixty", "unit": "mm"},
            "comparison": "at_most", "measurement": "bounding_box_x",
            "source": "user", "state": "accepted"}]),
    "assumption value is a string":
        lambda d: d.__setitem__("assumptions", [{
            "id": "A", "statement": "s", "risk": "high", "reversible": False,
            "approved": False, "value": {"magnitude": "500", "unit": "N"}}]),
    "interface names geometry no feature publishes":
        lambda d: d["components"][0].__setitem__("interfaces", [
            {"id": "i", "type": "bore", "geometry": "nope.bore"}]),
    "feature id with a space":
        lambda d: _feature(d).__setitem__("id", "base plate"),
    "null feature":
        lambda d: d["components"][0]["features"].append(None),
    "parameters is null":
        lambda d: _feature(d).__setitem__("parameters", None),
    "a nested object where the magnitude goes":
        lambda d: _value(d).__setitem__(
            "value", {"magnitude": {"value": 6}, "unit": "mm"}),
}


class NothingAModelWritesEndsTheRun(unittest.TestCase):
    """Every malformed document decodes into a pointed, repairable error."""

    def test_each_one_is_a_schema_error(self) -> None:
        for name, mutate in MALFORMED.items():
            with self.subTest(name):
                try:
                    Document.from_json(json.dumps(_mutated(mutate)))
                except (SchemaError, SchemaErrorGroup):
                    continue
                except Exception as error:  # noqa: BLE001 - the thing under test
                    self.fail(
                        f"{name} raised {type(error).__name__}, which the "
                        f"repair loop cannot act on: {error}"
                    )

    def test_each_error_says_where(self) -> None:
        """A message with no pointer cannot be turned into a patch."""
        for name, mutate in MALFORMED.items():
            with self.subTest(name):
                try:
                    Document.from_json(json.dumps(_mutated(mutate)))
                except SchemaErrorGroup as group:
                    self.assertTrue(
                        any(error.pointer for error in group.errors)
                        or group.message,
                        f"{name} reported nothing to act on",
                    )
                except SchemaError as error:
                    self.assertTrue(error.pointer or error.message)
                except Exception:  # noqa: BLE001 - covered by the test above
                    pass


#: Documents that decode cleanly and describe impossible geometry. These must
#: reach the compiler and be refused *by* it, which is a repairable outcome --
#: the orchestrator patches and recompiles.
IMPOSSIBLE: dict[str, list[dict[str, Any]]] = {
    "negative box size": [{"id": "body", "kind": "box", "parameters": {
        "size": {"vector": [-20, 20, 6], "unit": "mm"}}}],
    "zero box size": [{"id": "body", "kind": "box", "parameters": {
        "size": {"vector": [0, 20, 6], "unit": "mm"}}}],
    "zero-diameter cylinder": [{"id": "body", "kind": "cylinder", "parameters": {
        "diameter": {"magnitude": 0, "unit": "mm"},
        "height": {"magnitude": 5, "unit": "mm"}}}],
    "hole axis of zero length": [
        {"id": "body", "kind": "box", "parameters": {
            "size": {"vector": [20, 20, 6], "unit": "mm"}}},
        {"id": "h", "kind": "hole", "inputs": ["body"], "parameters": {
            "diameter": {"magnitude": 4, "unit": "mm"},
            "position": {"vector": [0, 0, 0], "unit": "mm"},
            "axis": {"vector": [0, 0, 0], "unit": ""}}}],
}


class ImpossibleGeometryIsRefusedNotCrashedOn(unittest.TestCase):
    def test_the_compiler_says_no_in_its_own_words(self) -> None:
        for name, features in IMPOSSIBLE.items():
            with self.subTest(name):
                payload = json.loads(json.dumps(BASE))
                payload["components"][0]["features"] = features
                document = Document.from_json(json.dumps(payload))
                with self.assertRaises(CompileError):
                    Compiler().compile_component(document.components[0])


class AnErrorWrappedTwiceStillNamesTheFailure(unittest.TestCase):
    """`could not resolve feature parameter: 'cause'`.

    Wrapping a Forge error in another is written `cause=exc.code,
    **exc.detail`, which breaks the moment the inner error has already been
    wrapped once and carries a `cause` of its own: Python raises for the
    duplicate keyword, inside the `except` block, and what escapes is that
    bookkeeping error instead of the failure being reported.

    A parameter dividing by zero travels through three layers, so it hit this
    on the way out and arrived as a message about a dictionary key.
    """

    def test_a_division_by_zero_says_so(self) -> None:
        payload = json.loads(json.dumps(BASE))
        payload["components"][0]["parameters"].append(
            {"id": "zero", "value": {"magnitude": 0, "unit": ""}}
        )
        _feature(payload)["parameters"]["size"] = {
            "vector": [20, 20, "t / zero"], "unit": "mm"
        }
        document = Document.from_json(json.dumps(payload))
        with self.assertRaises(CompileError) as caught:
            Compiler().compile_component(document.components[0])
        message = str(caught.exception)
        self.assertIn("division", message)
        self.assertNotIn("'cause'", message)

    def test_the_helper_drops_only_what_the_caller_sets(self) -> None:
        from forge_units import detail_besides

        kept = detail_besides(
            {"cause": "X", "divisor": 0, "numerator": 6}, "cause"
        )
        self.assertEqual(kept, {"divisor": 0, "numerator": 6})


class AnErrorWorthTheQuarterHourItCosts(unittest.TestCase):
    """On this hardware a repair round is thirteen minutes of generation.

    That is the real budget an error message is spending. "a vector must have
    exactly three components (got_length: 2)" states the rule correctly and
    leaves the author to work out which axis went missing -- and it is always
    the same answer, so writing it out costs nothing and saves the round.

    Both messages here were observed failing a live run, twice each, in the
    same document.
    """

    def _errors(self, payload: dict[str, Any]) -> str:
        try:
            Document.from_json(json.dumps(payload))
        except (SchemaError, SchemaErrorGroup) as error:
            return str(error)
        raise AssertionError("the document was accepted")

    def test_a_short_vector_is_shown_the_vector_that_works(self) -> None:
        payload = json.loads(json.dumps(BASE))
        payload["components"][0]["features"].append({
            "id": "pat", "kind": "pattern_linear", "inputs": ["body"],
            "parameters": {"count": 2,
                           "spacing": {"vector": [10, 0], "unit": "mm"}},
        })
        message = self._errors(payload)
        self.assertIn("[10, 0, 0]", message)
        self.assertIn("x, y, z", message)

    def test_a_profile_without_a_plane_is_shown_the_plane(self) -> None:
        payload = json.loads(json.dumps(BASE))
        payload["components"][0]["features"] = [{
            "id": "plate_profile", "kind": "profile_rectangle",
            "parameters": {"width": {"magnitude": 60, "unit": "mm"},
                           "height": {"magnitude": 40, "unit": "mm"}},
        }]
        message = self._errors(payload)
        self.assertIn('"kind": "datum_plane"', message)
        self.assertIn("plate_profile_plane", message)

    def test_it_also_says_the_plate_did_not_need_a_profile(self) -> None:
        """The fix that removes the feature beats the fix that repairs it."""
        payload = json.loads(json.dumps(BASE))
        payload["components"][0]["features"] = [{
            "id": "plate_profile", "kind": "profile_rectangle",
            "parameters": {"width": {"magnitude": 60, "unit": "mm"},
                           "height": {"magnitude": 40, "unit": "mm"}},
        }]
        self.assertIn("is a `box`", self._errors(payload))

    def test_a_primitive_given_inputs_still_says_add_a_boolean(self) -> None:
        """The older hint must survive the new branch beside it."""
        payload = json.loads(json.dumps(BASE))
        payload["components"][0]["features"].append(
            {"id": "c", "kind": "cylinder", "inputs": ["body"], "parameters": {
                "diameter": {"magnitude": 8, "unit": "mm"},
                "height": {"magnitude": 5, "unit": "mm"}}}
        )
        message = self._errors(payload)
        self.assertIn("union", message)
        self.assertIn("takes no", message)


class ABooleanThatUndoesItsOwnInputs(unittest.TestCase):
    """Three holes unioned together is a body with no holes.

    Each `hole` feature takes the finished body and returns a copy with one
    hole in it. Union the three copies and every hole is filled back in,
    because each copy still carries the material the other two removed. The
    result compiles, meshes and measures perfectly, and it is the original
    body.

    Observed live. It is why a run reported PASS on a spacer block with no
    holes in it at all::

        {"id": "body_2", "kind": "union",
         "inputs": ["hole", "mounting_hole_1", "mounting_hole_2"]}

    No geometry is needed to see it: the operands share an ancestor.
    """

    def _document(self, features: list[dict[str, Any]]) -> str:
        payload = json.loads(json.dumps(BASE))
        payload["components"][0]["features"] = features
        return json.dumps(payload)

    def _plate_and_two_holes(self) -> list[dict[str, Any]]:
        return [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"},
                "centered": True}},
            {"id": "hole_a", "kind": "hole", "inputs": ["base"], "parameters": {
                "diameter": {"magnitude": 3.0, "unit": "mm"},
                "position": {"vector": [-10, 0, 0], "unit": "mm"}}},
            {"id": "hole_b", "kind": "hole", "inputs": ["base"], "parameters": {
                "diameter": {"magnitude": 3.0, "unit": "mm"},
                "position": {"vector": [10, 0, 0], "unit": "mm"}}},
        ]

    def test_the_union_of_two_cut_copies_is_refused(self) -> None:
        features = self._plate_and_two_holes() + [
            {"id": "body", "kind": "union", "inputs": ["hole_a", "hole_b"]}
        ]
        with self.assertRaises((SchemaError, SchemaErrorGroup)) as caught:
            Document.from_json(self._document(features))
        self.assertIn("undoes the work", str(caught.exception))

    def test_the_message_names_the_shared_ancestor_and_the_chain(self) -> None:
        features = self._plate_and_two_holes() + [
            {"id": "body", "kind": "union", "inputs": ["hole_a", "hole_b"]}
        ]
        try:
            Document.from_json(self._document(features))
        except (SchemaError, SchemaErrorGroup) as error:
            message = str(error)
        self.assertIn("base", message)
        self.assertIn("hole_a -> hole_b", message)

    def test_chaining_them_is_accepted(self) -> None:
        """The fix the message recommends must actually work."""
        features = self._plate_and_two_holes()
        features[2]["inputs"] = ["hole_a"]
        document = Document.from_json(self._document(features))
        part = Compiler().compile_component(document.components[0])
        self.assertTrue(part.part_hash)

    def test_a_union_of_genuinely_separate_solids_is_fine(self) -> None:
        """The check must not refuse the composition pattern it teaches."""
        features = [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"}, "centered": True}},
            {"id": "post", "kind": "cylinder", "parameters": {
                "diameter": {"magnitude": 12.0, "unit": "mm"},
                "height": {"magnitude": 10.0, "unit": "mm"}}},
            {"id": "body", "kind": "union", "inputs": ["plate", "post"]},
        ]
        document = Document.from_json(self._document(features))
        self.assertEqual(len(document.components[0].features), 3)

    def test_cutters_sketched_on_one_plane_share_no_material(self) -> None:
        """Two slot cutters drawn on one datum plane, unioned into one
        cutter: they share the plane, and a plane has nothing to restore.
        Refused on Claude's first flight-controller plate as if it were
        holes unioned back into the plate."""
        features = [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [80, 60, 4], "unit": "mm"},
                "centered": True}},
            {"id": "sketch", "kind": "datum_plane", "parameters": {
                "base": "XY", "offset": {"magnitude": 2.0, "unit": "mm"}}},
        ]
        for name, u in (("a", -26.0), ("b", 26.0)):
            features += [
                {"id": f"slot_{name}", "kind": "profile_slot",
                 "inputs": ["sketch"], "parameters": {
                     "length": {"magnitude": 16.0, "unit": "mm"},
                     "width": {"magnitude": 4.0, "unit": "mm"},
                     "center_u": {"magnitude": u, "unit": "mm"},
                     "center_v": {"magnitude": 0.0, "unit": "mm"}}},
                {"id": f"cut_{name}", "kind": "extrude",
                 "inputs": [f"slot_{name}"], "parameters": {
                     "distance": {"magnitude": 4.0, "unit": "mm"},
                     "mode": "reverse"}},
            ]
        features += [
            {"id": "cutters", "kind": "union", "inputs": ["cut_a", "cut_b"]},
            {"id": "body", "kind": "subtract", "inputs": ["plate", "cutters"]},
        ]
        document = Document.from_json(self._document(features))
        part = Compiler().compile_component(document.components[0])
        self.assertTrue(part.part_hash)

    def test_an_intersect_of_siblings_is_refused_too(self) -> None:
        """Same arithmetic, opposite sign: it keeps only what both removed."""
        features = self._plate_and_two_holes() + [
            {"id": "body", "kind": "intersect", "inputs": ["hole_a", "hole_b"]}
        ]
        with self.assertRaises((SchemaError, SchemaErrorGroup)):
            Document.from_json(self._document(features))


class TwoFeaturesPublishingTheSameNames(unittest.TestCase):
    """Three holes, all `"role": "shaft"`, one bore in the geometry map.

    A feature's `role` is the handle its geometry is addressed by: a hole with
    `"role": "shaft"` publishes `shaft.bore` and `shaft.axis`. Give two
    features the same role and the map keeps one of them; the other's bore,
    axis and entry face do not exist as far as anything downstream can tell.

    Observed live, and entirely silent -- nothing was wrong with any feature on
    its own. Every check that resolves geometry by name was describing one hole
    and calling it three, including the part's own fact sheet, which reported
    all three at the same coordinates.
    """

    def _document(self, roles: list[str | None]) -> str:
        payload = json.loads(json.dumps(BASE))
        features: list[dict[str, Any]] = [
            {"id": "plate", "kind": "box", "parameters": {
                "size": {"vector": [40, 40, 6], "unit": "mm"}, "centered": True}},
        ]
        previous = "plate"
        for index, role in enumerate(roles):
            feature: dict[str, Any] = {
                "id": f"h{index}", "kind": "hole", "inputs": [previous],
                "parameters": {
                    "diameter": {"magnitude": 3.0, "unit": "mm"},
                    "position": {"vector": [index * 8 - 8, 0, 0], "unit": "mm"}},
            }
            if role:
                feature["role"] = role
            features.append(feature)
            previous = feature["id"]
        payload["components"][0]["features"] = features
        return json.dumps(payload)

    def test_a_shared_role_is_refused(self) -> None:
        with self.assertRaises((SchemaError, SchemaErrorGroup)) as caught:
            Document.from_json(self._document(["shaft", "shaft", "shaft"]))
        message = str(caught.exception)
        self.assertIn("same geometry names", message)
        self.assertIn("shaft", message)

    def test_it_names_every_feature_in_the_collision(self) -> None:
        try:
            Document.from_json(self._document(["shaft", "shaft"]))
        except (SchemaError, SchemaErrorGroup) as error:
            message = str(error)
        self.assertIn("h0", message)
        self.assertIn("h1", message)

    def test_it_gives_one_fix_and_warns_off_the_other(self) -> None:
        """It used to offer two fixes and lead with the destructive one.

        "Give each feature its own `role`" was listed first, a model took it,
        and renaming the roles renamed every published geometry name -- which
        broke every interface that referred to the old ones and cost the run
        two more thirteen-minute rounds before it failed. A role is a
        published name, so the only safe fix is to delete it and fall back to
        the id, and the hint must say so without offering the alternative.
        """
        try:
            Document.from_json(self._document(["shaft", "shaft"]))
        except (SchemaError, SchemaErrorGroup) as error:
            message = str(error)
        self.assertIn("Delete `role`", message)
        self.assertIn("`id` is used", message)
        self.assertIn("Do NOT rename", message)
        self.assertNotIn("own `role`", message)

    def test_distinct_roles_are_accepted(self) -> None:
        document = Document.from_json(self._document(["shaft", "bolt_a"]))
        self.assertEqual(len(document.components[0].features), 3)

    def test_no_roles_at_all_is_accepted(self) -> None:
        """Without a role the id is used, and ids are unique already."""
        document = Document.from_json(self._document([None, None, None]))
        self.assertEqual(len(document.components[0].features), 4)

    def test_one_error_per_group_not_one_per_name(self) -> None:
        """A hole publishes four names; three colliding holes is one problem."""
        try:
            Document.from_json(self._document(["shaft", "shaft", "shaft"]))
        except SchemaErrorGroup as group:
            collisions = [
                e for e in group.errors if "same geometry names" in e.message
            ]
            self.assertEqual(len(collisions), 1)


class TheSpacerRunThatFailedThreeTimes(unittest.TestCase):
    """The three attempts of run 20260915T161611, each now settled in code.

    A 64-minute design failed three times on three problems. Forge caused two
    of them and could have resolved all three without asking:

    1. three holes sharing ``role: "shaft"``;
    2. roles renamed in response to Forge's own hint, which silently broke
       every interface that named a feature by its id;
    3. the union Forge told it to paste, named ``body_2`` by a collision
       avoider, referred to afterwards as ``body``.

    Each attempt is reproduced here as the model actually wrote it. The claim
    is not that these particular three are fixed -- it is that a repair Forge
    is certain of costs nothing, because a repair round against a local model
    costs thirteen minutes and may not converge at all.
    """

    def normalise(self, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        from forge_roles.library import _normalise_document

        return _normalise_document(payload)

    def test_attempt_one_colliding_roles_are_dropped_not_renamed(self) -> None:
        payload = {
            "components": [
                {
                    "id": "spacer_block",
                    "features": [
                        {"id": "base", "kind": "box"},
                        {"id": "post", "kind": "cylinder"},
                        {"id": "body", "kind": "union",
                         "inputs": ["base", "post"]},
                        {"id": "hole", "kind": "hole", "role": "shaft",
                         "inputs": ["body"]},
                        {"id": "mounting_hole_1", "kind": "hole",
                         "role": "shaft", "inputs": ["hole"]},
                        {"id": "mounting_hole_2", "kind": "hole",
                         "role": "shaft", "inputs": ["mounting_hole_1"]},
                    ],
                }
            ]
        }
        result, notes = self.normalise(payload)
        features = result["components"][0]["features"]
        self.assertFalse(
            any("role" in f for f in features),
            "a colliding role must be dropped so the unique id is used",
        )
        # And the ids -- the thing everything else refers to -- are untouched.
        self.assertEqual(
            [f["id"] for f in features],
            ["base", "post", "body", "hole", "mounting_hole_1",
             "mounting_hole_2"],
            "dropping a role must not disturb the ids everything refers to",
        )
        self.assertTrue(any("role" in note for note in notes))

    def test_attempt_two_interfaces_follow_the_rename(self) -> None:
        payload = {
            "components": [
                {
                    "id": "spacer_block",
                    "features": [
                        {"id": "base", "kind": "box"},
                        {"id": "mounting_hole_1", "kind": "hole",
                         "role": "shaft_mounting_hole_1", "inputs": ["base"]},
                    ],
                    "interfaces": [
                        {"id": "shaft_port_1",
                         "geometry": "mounting_hole_1.bore"},
                    ],
                }
            ]
        }
        result, notes = self.normalise(payload)
        self.assertEqual(
            result["components"][0]["interfaces"][0]["geometry"],
            "shaft_mounting_hole_1.bore",
            "an interface naming the feature id must follow it to the role",
        )
        self.assertTrue(notes)

    def test_attempt_three_body_resolves_to_the_only_candidate(self) -> None:
        payload = {
            "components": [
                {
                    "id": "spacer_block",
                    "features": [
                        {"id": "base", "kind": "box"},
                        {"id": "post", "kind": "cylinder"},
                        {"id": "body_2", "kind": "union",
                         "inputs": ["base", "post"]},
                        {"id": "hole", "kind": "hole", "inputs": ["body"]},
                        {"id": "mounting_hole_1", "kind": "hole",
                         "inputs": ["hole"]},
                        {"id": "mounting_hole_2", "kind": "hole",
                         "inputs": ["mounting_hole_1"]},
                    ],
                }
            ]
        }
        result, notes = self.normalise(payload)
        features = {f["id"]: f for f in result["components"][0]["features"]}
        self.assertEqual(
            features["hole"]["inputs"], ["body_2"],
            "`body` had exactly one candidate it could mean",
        )
        self.assertTrue(any("body" in note for note in notes))

    def test_an_ambiguous_near_miss_is_left_alone(self) -> None:
        """Two candidates is a guess, and a wrong guess rewires the part."""
        payload = {
            "components": [
                {
                    "id": "c",
                    "features": [
                        {"id": "body_1", "kind": "box"},
                        {"id": "body_2", "kind": "box"},
                        {"id": "hole", "kind": "hole", "inputs": ["body"]},
                    ],
                }
            ]
        }
        result, _ = self.normalise(payload)
        features = {f["id"]: f for f in result["components"][0]["features"]}
        self.assertEqual(
            features["hole"]["inputs"], ["body"],
            "an ambiguous name must stay an error, not become a coin flip",
        )

    def test_loose_cutters_are_chained_never_unioned(self) -> None:
        """The bug that reported PASS on a part with no holes in it.

        Three holes each fed the same body are three copies of that body with
        one hole each. Unioning them restores every hole. They must be chained.
        """
        payload = {
            "components": [
                {
                    "id": "c",
                    "features": [
                        {"id": "body", "kind": "box"},
                        {"id": "h1", "kind": "hole", "inputs": ["body"]},
                        {"id": "h2", "kind": "hole", "inputs": ["body"]},
                        {"id": "h3", "kind": "hole", "inputs": ["body"]},
                    ],
                }
            ]
        }
        result, notes = self.normalise(payload)
        features = {f["id"]: f for f in result["components"][0]["features"]}
        self.assertNotIn(
            "union", [f["kind"] for f in features.values()],
            "welding cutters back together refills every hole",
        )
        self.assertEqual(features["h2"]["inputs"], ["h1"])
        self.assertEqual(features["h3"]["inputs"], ["h2"])
        self.assertTrue(any("chained" in note for note in notes))

    def test_two_loose_solids_are_welded(self) -> None:
        """Two starts with no shared ancestor really are two solids."""
        payload = {
            "components": [
                {
                    "id": "spacer",
                    "features": [
                        {"id": "base", "kind": "box"},
                        {"id": "post", "kind": "cylinder"},
                    ],
                }
            ]
        }
        result, notes = self.normalise(payload)
        features = result["components"][0]["features"]
        self.assertEqual(features[-1]["kind"], "union")
        self.assertEqual(sorted(features[-1]["inputs"]), ["base", "post"])
        self.assertNotIn(
            "_2", features[-1]["id"],
            "a collision-suffixed name goes stale the moment the graph changes",
        )
        self.assertTrue(notes)

    def test_a_clean_document_is_returned_unchanged(self) -> None:
        payload = {
            "components": [
                {
                    "id": "c",
                    "features": [
                        {"id": "base", "kind": "box"},
                        {"id": "post", "kind": "cylinder", "role": "boss"},
                        {"id": "body", "kind": "union",
                         "inputs": ["base", "post"]},
                    ],
                    "interfaces": [{"id": "p", "geometry": "boss.top"}],
                }
            ]
        }
        result, notes = self.normalise(payload)
        self.assertEqual(result, payload)
        self.assertEqual(notes, [])


class AParameterThatDrivesNothing(unittest.TestCase):
    """The run that reported PASS on thirteen claims and a wrong part.

    Run 20260915T172355 completed, gated green, and wrote an STL whose
    mounting holes were 30 mm apart and centred on the plate's edges, each
    cutting a half-moon out of the side. `The mounting hole spacing shall be
    20 mm` passed, because it read `parameter:mounting_hole_spacing`, and that
    parameter said 20. Nothing else in the document mentioned it: the holes
    sat at a hard-coded 15.0.

    A requirement bound to a parameter no geometry reads is not a weak check,
    it is the absence of one wearing a check's clothes.
    """

    def check(self, document: dict[str, Any], measured: list[str]) -> None:
        """Raises `RoleOutputError` when the design leaves an orphan.

        The check itself returns its problems now rather than raising, so
        that one round can report every fault instead of the first one. This
        helper keeps these tests reading as they did -- what they are about
        is which designs are refused, not how the refusal travels.
        """
        from forge_roles.base import RoleOutputError
        from forge_roles.library import ForgeIRDesigner

        _, problems = ForgeIRDesigner._require_the_parameters_drive_the_geometry(
            document,
            requirements=type(
                "R", (), {"requirements": [{"measurement": m} for m in measured]}
            )(),
        )
        if problems:
            raise RoleOutputError("a parameter drives no geometry", problems)

    def _document(self, x_position: Any) -> dict[str, Any]:
        return {
            "components": [
                {
                    "id": "spacer",
                    "parameters": [
                        {"id": "plate_width",
                         "value": {"magnitude": 30.0, "unit": "mm"}},
                        {"id": "mounting_hole_spacing",
                         "value": {"magnitude": 20.0, "unit": "mm"}},
                    ],
                    "features": [
                        {"id": "base", "kind": "box", "parameters": {
                            "size": {"vector": ["plate_width", "plate_width",
                                                4.0], "unit": "mm"}}},
                        {"id": "mh1", "kind": "hole", "inputs": ["base"],
                         "parameters": {
                            "position": {"vector": [x_position, 0, 0],
                                         "unit": "mm"}}},
                    ],
                }
            ]
        }

    def test_the_orphaned_parameter_is_refused(self) -> None:
        from forge_roles.base import RoleOutputError

        with self.assertRaises(RoleOutputError) as caught:
            self.check(
                self._document(15.0),
                ["parameter:plate_width", "parameter:mounting_hole_spacing"],
            )
        problem = caught.exception.problems[0]
        self.assertIn("mounting_hole_spacing", problem)
        self.assertNotIn(
            "plate_width", problem.split("no feature reads them:")[1][:60],
            "a parameter the geometry does read must not be named as an orphan",
        )

    def test_driving_the_geometry_from_it_is_accepted(self) -> None:
        self.check(
            self._document("mounting_hole_spacing / 2"),
            ["parameter:plate_width", "parameter:mounting_hole_spacing"],
        )

    def test_one_parameter_defined_from_another_keeps_it_alive(self) -> None:
        """`hole_radius = hole_diameter / 2`, read by a feature, counts."""
        document = {
            "components": [
                {
                    "id": "c",
                    "parameters": [
                        {"id": "hole_diameter",
                         "value": {"magnitude": 5.0, "unit": "mm"}},
                        {"id": "hole_radius",
                         "value": {"expression": "hole_diameter / 2"}},
                    ],
                    "features": [
                        {"id": "h", "kind": "hole", "parameters": {
                            "radius": {"expression": "hole_radius"}}},
                    ],
                }
            ]
        }
        self.check(document, ["parameter:hole_diameter"])

    def test_a_unit_is_never_read_as_a_parameter_reference(self) -> None:
        """Otherwise a parameter called `mm` would look alive forever."""
        from forge_roles.library import _identifiers_in

        self.assertEqual(
            _identifiers_in({"magnitude": 4.0, "unit": "mm"}), set()
        )

    def test_a_feature_id_does_not_keep_a_parameter_alive(self) -> None:
        """A parameter and a feature may share a name; only reads count.

        The name collision is still not a read -- what changed is what
        happens next. The cylinder's height is the literal 10 mm and `post`
        is declared as 10 mm, so Forge wires the two together instead of
        asking, and the requirement bound to `post` ends up measuring the
        cylinder it was always meant to measure.
        """
        from forge_roles.library import ForgeIRDesigner

        document = {
            "components": [
                {
                    "id": "c",
                    "parameters": [
                        {"id": "post", "value": {"magnitude": 10.0,
                                                 "unit": "mm"}},
                    ],
                    "features": [
                        {"id": "post", "kind": "cylinder", "parameters": {
                            "height": {"magnitude": 10.0, "unit": "mm"}}},
                    ],
                }
            ]
        }
        notes, problems = ForgeIRDesigner._require_the_parameters_drive_the_geometry(
            document, requirements=type("R", (), {"requirements": [
                {"measurement": "parameter:post"}]})())
        self.assertEqual(
            document["components"][0]["features"][0]["parameters"]["height"],
            {"expression": "post"},
        )
        self.assertTrue(notes)

    def test_sharing_a_name_alone_does_not_save_an_orphan(self) -> None:
        """No literal matches, so there is nothing to wire and the collision
        buys the parameter nothing -- which is the original point."""
        from forge_roles.base import RoleOutputError

        document = {
            "components": [
                {
                    "id": "c",
                    "parameters": [
                        {"id": "post", "value": {"magnitude": 10.0,
                                                 "unit": "mm"}},
                    ],
                    "features": [
                        {"id": "post", "kind": "cylinder", "parameters": {
                            "height": {"magnitude": 7.0, "unit": "mm"}}},
                    ],
                }
            ]
        }
        with self.assertRaises(RoleOutputError):
            self.check(document, ["parameter:post"])

    def test_nothing_measured_means_nothing_to_check(self) -> None:
        self.check(self._document(15.0), ["mass"])

    def test_a_parameter_alive_only_through_a_chain_is_not_an_orphan(self) -> None:
        """The bracket fixture, which caught an over-strict first draft.

        `lever_arm` appears in no feature. It reaches the geometry through
        two hops of parameter expressions, and changing it moves the bore --
        so it drives the part and the requirement measuring it is real. An
        earlier version of this check looked one step deep and only under a
        `value` key, and called the hand-written correct bracket broken.
        """
        document = {
            "components": [
                {
                    "id": "bracket",
                    "parameters": [
                        {"id": "base_thickness",
                         "value": {"magnitude": 10.0, "unit": "mm"}},
                        {"id": "lever_arm",
                         "value": {"magnitude": 32.0, "unit": "mm"}},
                        # expression at the TOP level, not under `value`
                        {"id": "bore_z",
                         "expression": "base_thickness + lever_arm",
                         "unit": "mm"},
                        {"id": "upright_height",
                         "expression": "bore_z - base_thickness",
                         "unit": "mm"},
                    ],
                    "features": [
                        {"id": "upright", "kind": "box", "parameters": {
                            "size": {"vector": [10, 10, "upright_height"],
                                     "unit": "mm"}}},
                    ],
                }
            ]
        }
        self.check(document, ["parameter:lever_arm"])


class APromisedProcedureIsPartOfTheClaim(unittest.TestCase):
    """A requirement asking for a physical test is not answered by a ruler.

    Found by an external audit and reproduced: a requirement declaring
    `verification: "physical_test"` was answered with `Method.EXACT_GEOMETRY`,
    marked PASS, and carried into an overall PASS. Nothing in the report said
    that no test had been performed.

    The method a requirement names is a promise about *how* the claim will be
    established, and it is part of the claim. Measuring the mesh instead is
    not a weaker check of the same thing -- it is a different check, filed
    under the first one's name.
    """

    def _requirement(self, verification: str) -> dict[str, Any]:
        return {
            "id": "R_STRENGTH",
            "statement": "The bracket shall survive the rated load.",
            "type": "safety",
            "strength": "hard",
            "verification": verification,
            "threshold": {"magnitude": 8.0, "unit": "mm"},
            "comparison": "at_most",
            "measurement": "bounding_box_z",
            "source": "user",
            "state": "accepted",
        }

    def _verdict(self, verification: str):
        from forge_pipeline import verify_component

        payload = _mutated(lambda d: d.__setitem__(
            "requirements", [self._requirement(verification)]))
        document = Document.from_json(json.dumps(payload))
        return verify_component(document, document.components[0])

    def test_a_physical_test_is_never_satisfied_by_geometry(self) -> None:
        report = self._verdict("physical_test")
        node = next(
            n for n in report.evidence if "R_STRENGTH" in n.identifier
        )
        self.assertNotEqual(
            node.status.value, "PASS",
            "a measurement reported a physical test as performed",
        )
        self.assertIn("physical_test", str(node.detail))

    def test_the_untested_node_is_filed_under_the_method_asked_for(self) -> None:
        report = self._verdict("physical_test")
        node = next(
            n for n in report.evidence if "R_STRENGTH" in n.identifier
        )
        self.assertEqual(node.method.value, "physical_test")

    def test_every_method_forge_cannot_perform_is_covered(self) -> None:
        from forge_pipeline.verify import _METHODS_FORGE_CANNOT_PERFORM

        for method in sorted(_METHODS_FORGE_CANNOT_PERFORM):
            with self.subTest(method):
                report = self._verdict(method)
                node = next(
                    n for n in report.evidence
                    if "R_STRENGTH" in n.identifier
                )
                self.assertNotEqual(node.status.value, "PASS")

    def test_the_measurement_is_still_recorded_for_whoever_runs_the_test(self) -> None:
        """Refusing to call it evidence is not a reason to throw it away."""
        report = self._verdict("physical_test")
        node = next(
            n for n in report.evidence if "R_STRENGTH" in n.identifier
        )
        self.assertIn("measured_anyway", node.detail)

    def test_a_geometric_requirement_is_unaffected(self) -> None:
        """The guard must not stop Forge checking what it genuinely can."""
        report = self._verdict("exact_geometry")
        node = next(
            n for n in report.evidence if "R_STRENGTH" in n.identifier
        )
        self.assertIn(node.status.value, ("PASS", "FAIL"))


class HolesDrilledDownTheSameLine(unittest.TestCase):
    """A hole is a line. Sliding it along its own axis moves it nowhere.

    Reproduced from run 20260915T212005, which spent 42 minutes building and
    measuring a part whose three holes were one hole:

        bore            position [0,          0, post_height/2]  axis [1,0,0]
        mounting_hole_1 position [spacing/2,  0, post_height/2]  axis [1,0,0]
        mounting_hole_2 position [-spacing/2, 0, post_height/2]  axis [1,0,0]

    The spacing was applied along x, which is the direction being drilled, so
    every one of them is the line y=0, z=post_height/2. The 5 mm bore cut the
    channel; both 3 mm mounting holes then cut inside it and left no surface
    on the part. `GEOM_BORES_SURVIVE` and `GEOM_FEATURES_CONTRIBUTE` caught
    it -- correctly, but only after the whole compile-and-measure pass.
    """

    def _document(self, holes: list[dict[str, Any]]) -> str:
        payload = _mutated(lambda d: None)
        payload["components"][0]["features"] = [
            {"id": "body", "kind": "box", "parameters": {
                "size": {"vector": [30, 30, 4], "unit": "mm"}}},
            *holes,
        ]
        return json.dumps(payload)

    def _hole(self, identifier: str, position: list[Any], axis: list[float],
              previous: str) -> dict[str, Any]:
        return {
            "id": identifier, "kind": "hole", "inputs": [previous],
            "parameters": {
                "diameter": {"magnitude": 3.0, "unit": "mm"},
                "position": {"vector": position, "unit": "mm"},
                "axis": axis,
            },
        }

    def test_the_run_that_found_it_is_refused(self) -> None:
        document = self._document([
            self._hole("bore", [0, 0, 5], [1, 0, 0], "body"),
            self._hole("mh1", [10, 0, 5], [1, 0, 0], "bore"),
            self._hole("mh2", [-10, 0, 5], [1, 0, 0], "mh1"),
        ])
        with self.assertRaises((SchemaError, SchemaErrorGroup)) as caught:
            Document.from_json(document)
        message = str(caught.exception)
        self.assertIn("same hole", message)
        for name in ("bore", "mh1", "mh2"):
            self.assertIn(name, message)

    def test_the_hint_says_to_offset_across_the_axis(self) -> None:
        document = self._document([
            self._hole("a", [0, 0, 5], [1, 0, 0], "body"),
            self._hole("b", [10, 0, 5], [1, 0, 0], "a"),
        ])
        try:
            Document.from_json(document)
        except (SchemaError, SchemaErrorGroup) as error:
            self.assertIn("ACROSS", str(error))

    def test_holes_offset_across_the_axis_are_accepted(self) -> None:
        """The correct part: spread over the directions the axis is not."""
        document = self._document([
            self._hole("a", [0, -10, 5], [1, 0, 0], "body"),
            self._hole("b", [0, 10, 5], [1, 0, 0], "a"),
        ])
        Document.from_json(document)

    def test_a_counterbore_drawn_as_two_holes_is_accepted(self) -> None:
        """A 5.5 mm hole right through and a 10 mm one 2 mm deep over it:
        a stepped hole, each cutting what the other does not."""
        through = self._hole("hole", [0, 0, 2], [0, 0, 1], "body")
        through["parameters"]["diameter"] = {"magnitude": 5.5, "unit": "mm"}
        recess = self._hole("recess", [0, 0, 4], [0, 0, -1], "hole")
        recess["parameters"]["diameter"] = {"magnitude": 10.0, "unit": "mm"}
        recess["parameters"]["depth"] = {"magnitude": 2.0, "unit": "mm"}
        Document.from_json(self._document([through, recess]))

    def test_through_holes_of_two_sizes_on_one_line_are_refused(self) -> None:
        bore = self._hole("bore", [0, 0, 5], [1, 0, 0], "body")
        bore["parameters"]["diameter"] = {"magnitude": 5.0, "unit": "mm"}
        with self.assertRaises((SchemaError, SchemaErrorGroup)):
            Document.from_json(self._document([
                bore, self._hole("mh1", [10, 0, 5], [1, 0, 0], "bore")]))

    def test_the_intended_plate_pattern_is_accepted(self) -> None:
        """Two holes down Z, 20 mm apart in x -- what the brief asked for."""
        document = self._document([
            self._hole("a", [-10, 0, 0], [0, 0, 1], "body"),
            self._hole("b", [10, 0, 0], [0, 0, 1], "a"),
        ])
        Document.from_json(document)

    def test_different_axes_are_not_the_same_hole(self) -> None:
        document = self._document([
            self._hole("a", [0, 0, 5], [1, 0, 0], "body"),
            self._hole("b", [0, 0, 5], [0, 0, 1], "a"),
        ])
        Document.from_json(document)

    def test_a_diagonal_axis_is_left_alone(self) -> None:
        """The check claims only what it can prove from the written form."""
        document = self._document([
            self._hole("a", [0, 0, 5], [1, 1, 0], "body"),
            self._hole("b", [5, 5, 5], [1, 1, 0], "a"),
        ])
        Document.from_json(document)

    def test_a_single_hole_is_never_reported(self) -> None:
        document = self._document([
            self._hole("only", [0, 0, 0], [0, 0, 1], "body"),
        ])
        Document.from_json(document)


class TheHintMustNameTheThingThatIsWrong(unittest.TestCase):
    """A hint about the wrong field is worse than no hint at all.

    Reproduced from run 20260917T135205. The orphaned parameter was
    `fillet_radius`; the message said::

        Drive the geometry from them: write
        `{"expression": "mounting_hole_spacing / 2"}` where the position
        would otherwise be a bare number, so moving the parameter moves
        the hole.

    One fixed example, about hole spacing, shown for a fillet. The designer
    spent three attempts and twenty minutes and returned the same answer
    twice, because the advice pointed somewhere there was nothing to fix.

    The number was already in the document: `body.blend_radius` held a bare
    2.0, and `fillet_radius` was 2 mm. One edit away, and nothing said so.
    """

    COMPONENT = {
        "id": "spacer",
        "parameters": [
            {"id": "fillet_radius", "value": {"magnitude": 2.0, "unit": "mm"}},
            {"id": "plate_width", "value": {"magnitude": 30.0, "unit": "mm"}},
        ],
        "features": [
            {"id": "base", "kind": "box", "parameters": {
                "size": {"vector": ["plate_width", "plate_width", 4],
                         "unit": "mm"}}},
            {"id": "body", "kind": "union", "inputs": ["base", "post"],
             "parameters": {"blend_radius": {"magnitude": 2.0, "unit": "mm"}}},
        ],
    }

    def test_it_names_the_feature_field_holding_the_orphan(self) -> None:
        from forge_roles.library import _where_the_orphan_belongs

        hint = _where_the_orphan_belongs(self.COMPONENT, ["fillet_radius"])
        self.assertIn("body.blend_radius", hint)
        self.assertIn("fillet_radius", hint)
        self.assertIn('{"expression": "fillet_radius"}', hint)

    def test_it_never_mentions_an_unrelated_example(self) -> None:
        """The old message talked about hole spacing whatever was wrong."""
        from forge_roles.library import _where_the_orphan_belongs

        hint = _where_the_orphan_belongs(self.COMPONENT, ["fillet_radius"])
        self.assertNotIn("mounting_hole_spacing", hint)

    def test_it_falls_back_honestly_when_no_literal_matches(self) -> None:
        from forge_roles.library import _where_the_orphan_belongs

        hint = _where_the_orphan_belongs(self.COMPONENT, ["lever_arm"])
        self.assertIn("<parameter id>", hint)
        self.assertNotIn("is the literal", hint)

    def test_the_unambiguous_one_is_wired_rather_than_described(self) -> None:
        """This used to assert that the hint reached the error. It reaches a
        repair instead: one literal, one match, so Forge makes the edit it
        had already worked out rather than spending a designer round asking
        for it. The hint still covers the ambiguous case below."""
        import copy

        from forge_roles.library import ForgeIRDesigner

        document = {"components": [copy.deepcopy(self.COMPONENT)]}
        requirements = type("R", (), {"requirements": [
            {"measurement": "parameter:fillet_radius"}]})()
        notes, problems = ForgeIRDesigner._require_the_parameters_drive_the_geometry(
            document, requirements=requirements)
        union = document["components"][0]["features"][-1]["parameters"]
        self.assertEqual(
            union["blend_radius"], {"expression": "fillet_radius"})
        self.assertTrue(any("fillet_radius" in note for note in notes), notes)

    def test_the_error_carries_the_hint_when_it_is_a_judgement(self) -> None:
        import copy

        from forge_roles.base import RoleOutputError
        from forge_roles.library import ForgeIRDesigner

        component = copy.deepcopy(self.COMPONENT)
        # A second 2 mm somewhere else: now which 2 the parameter means is a
        # question only the author can answer, so the hint has to do its job.
        component["features"].append(
            {"id": "rib", "kind": "box", "parameters": {
                "size": {"vector": [2.0, 2.0, 2.0], "unit": "mm"},
                "wall": {"magnitude": 2.0, "unit": "mm"}}})
        requirements = type("R", (), {"requirements": [
            {"measurement": "parameter:fillet_radius"}]})()
        _, problems = ForgeIRDesigner._require_the_parameters_drive_the_geometry(
            {"components": [component]}, requirements=requirements)
        self.assertTrue(problems)
        self.assertIn("body.blend_radius", problems[0])


class WhichWayTheHoleDisappeared(unittest.TestCase):
    """The absent-feature gate must name the cause it actually found.

    Earned on the shaft collar. Two set screw holes were placed at
    `outer_diameter / 2` -- on the skin of a round body, so the axis ran
    along the outside and cut nothing. The gate caught them, correctly, and
    then explained them with the only cause it knew: "a `union` that adds a
    solid the hole was never cut through... chain them so each takes the
    previous feature as its input." The holes were already chained and there
    was no union in the document. The analyst did as it was told, rewrote the
    feature list into the same graph in a new order, and two rounds and four
    minutes later the run ended worse than it started.

    Forge could tell the difference the whole time and for free: the backend
    publishes `bearing_length`, which is exactly zero when no point on the
    axis is inside the solid. A hole that cut nothing and a hole that was
    filled back in are different faults with different fixes, and the gate
    now says which one it is.
    """

    @staticmethod
    def _collar(x_position):
        from forge_ir import SCHEMA_VERSION

        def mm(v):
            return {"magnitude": float(v), "unit": "mm"}

        return {
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "name": "Shaft collar", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "requirements": [], "assumptions": [],
            "components": [{
                "id": "collar", "name": "Shaft collar",
                "material": "aluminium_6061_t6",
                "parameters": [
                    {"id": "outer_diameter", "value": mm(25)},
                    {"id": "length", "value": mm(15)},
                    {"id": "bore_diameter", "value": mm(12)},
                ],
                "features": [
                    {"id": "body", "kind": "cylinder", "parameters": {
                        "diameter": {"expression": "outer_diameter",
                                     "unit": "mm"},
                        "height": {"expression": "length", "unit": "mm"},
                        "origin": {"vector": [0, 0, 0], "unit": "mm"}}},
                    {"id": "bore", "kind": "hole", "inputs": ["body"],
                     "parameters": {
                        "diameter": {"expression": "bore_diameter",
                                     "unit": "mm"},
                        "position": {"vector": [0, 0, "length / 2"],
                                     "unit": "mm"},
                        "axis": [0.0, 0.0, 1.0]}},
                    {"id": "set_screw_hole_1", "kind": "hole",
                     "inputs": ["bore"], "parameters": {
                        "diameter": mm(4),
                        "position": {"vector": [x_position, 0, "length / 2"],
                                     "unit": "mm"},
                        "axis": [0.0, 1.0, 0.0]}},
                ],
            }],
        }

    def _compile(self, x_position):
        import json

        from forge_ir import Document
        from forge_kernel import Compiler

        document = Document.from_json(json.dumps(self._collar(x_position)))
        component = document.components[0]
        # Burial is worked out during geometry validation, so the gate sees
        # nothing without it: `buried_entities()` is empty on a compile that
        # skipped the check, and a test built that way would assert on an
        # empty list and pass for the wrong reason.
        return component, Compiler().compile_component(
            component, validate_geometry=True)

    def test_a_hole_on_the_skin_reports_that_it_cut_nothing(self) -> None:
        from forge_pipeline.verify import the_bore_found_material

        component, part = self._compile("outer_diameter / 2")
        screw = [f for f in component.features
                 if f.identifier == "set_screw_hole_1"][0]
        self.assertFalse(the_bore_found_material(part, screw))

    def test_a_hole_on_the_centre_line_cuts_material(self) -> None:
        """The same hole, placed where it belongs, does its job."""
        from forge_pipeline.verify import the_bore_found_material

        component, part = self._compile(0)
        screw = [f for f in component.features
                 if f.identifier == "set_screw_hole_1"][0]
        self.assertTrue(the_bore_found_material(part, screw))

    def test_the_hint_blames_placement_and_not_the_graph(self) -> None:
        # Off the part altogether: on the skin, the hole cuts a channel --
        # its bore is on the part, a patch of it -- and is failed as a
        # channel, not a hole (`GEOM_HOLES_ARE_HOLES`, below).
        from forge_evidence import EvidenceGraph
        from forge_pipeline.verify import _check_features_contribute

        component, part = self._compile("outer_diameter")
        results = _check_features_contribute(
            component, part, EvidenceGraph(), part.part_hash)
        hint = results[0].evidence.detail["hint"]
        self.assertIn("never cut anything", hint)
        self.assertIn("AXIS PASSES THROUGH", hint)
        self.assertIn("inside the material", hint)
        self.assertIn("placement fault", hint)
        self.assertIn("centre line", hint)
        self.assertNotIn("filled the bore back in", hint)

    def test_a_hole_on_the_skin_is_failed_as_a_channel(self) -> None:
        import json

        from forge_ir import Document
        from forge_pipeline import verify_component

        document = Document.from_json(json.dumps(
            self._collar("outer_diameter / 2")))
        report = verify_component(document, document.components[0],
                                  measurement_depth=6)
        found = {r.gate.identifier: r for r in report.gate_results}
        self.assertEqual(found["GEOM_HOLES_ARE_HOLES"].status.value, "FAIL")
        self.assertIn("set_screw_hole_1",
                      found["GEOM_HOLES_ARE_HOLES"].evidence.detail["hint"])

    def test_the_refilled_wording_is_still_there_for_that_case(self) -> None:
        """The other cause did not stop existing; it stopped being the only
        one offered."""
        import inspect

        from forge_pipeline import verify

        # The gate's wording lives where the gate is assembled, beside the
        # check that finds the absent features.
        source = inspect.getsource(verify._check_features_contribute) + \
            inspect.getsource(verify._the_contribution_gate)
        self.assertIn("filled the bore back in", source)
        self.assertIn("did cut material, and then lost it", source)


class ATolerancetFinerThanTheInstrument(unittest.TestCase):
    """An equality gate must not ask a question its measurement cannot answer.

    Earned on a shaft collar built to exactly 25 mm across. The octree
    measured `24.8145 +/- 0.205078 mm` -- a rigorous enclosure, correct, and
    0.41 mm wide -- and the gate compared it against `== 25 mm` with the
    default tolerance of 0.05 mm. INCONCLUSIVE. It would have been
    INCONCLUSIVE at any diameter whatsoever, because an interval 0.41 mm wide
    cannot sit inside a band 0.1 mm wide. A perfect part could not be shown
    to be perfect.

    0.05 mm is the right tolerance for a number the document *declares*:
    those resolve exactly, their interval has zero width, and nothing here
    touches them. It is the wrong tolerance for a number that was *measured*.

    Both halves are tested, because a tolerance widened until everything
    passes is worse than one too tight to ever pass.
    """

    def _widen(self, declared_mm, lo, hi):
        from forge_pipeline.verify import _tolerance_you_can_actually_measure
        from forge_units import Interval, Q, Quantity, parse_unit

        return _tolerance_you_can_actually_measure(
            Q(declared_mm, "mm"),
            Quantity(Interval(lo, hi), parse_unit("mm")),
        )

    def test_it_widens_to_the_measurement(self) -> None:
        tolerance, why = self._widen(0.05, 24.6094, 25.0195)
        self.assertAlmostEqual(tolerance.magnitude.midpoint, 0.4101, places=3)
        self.assertIn("finer than this measurement resolves", why)

    def test_an_exact_measurement_is_untouched(self) -> None:
        """A declared parameter resolves to a point, not an interval."""
        tolerance, why = self._widen(0.05, 25.0, 25.0)
        self.assertAlmostEqual(tolerance.magnitude.midpoint, 0.05)
        self.assertEqual(why, "")

    def test_a_tolerance_already_wide_enough_is_untouched(self) -> None:
        tolerance, why = self._widen(1.0, 24.9, 25.1)
        self.assertAlmostEqual(tolerance.magnitude.midpoint, 1.0)
        self.assertEqual(why, "")

    def test_it_never_narrows(self) -> None:
        for declared, lo, hi in ((0.5, 24.99, 25.01), (2.0, 20.0, 30.0)):
            tolerance, _ = self._widen(declared, lo, hi)
            self.assertGreaterEqual(
                tolerance.magnitude.midpoint, min(declared, hi - lo) - 1e-9)

    # -- and the property that matters: a wrong part still fails -----------

    @staticmethod
    def _collar(claims):
        from forge_ir import SCHEMA_VERSION

        def mm(v):
            return {"magnitude": float(v), "unit": "mm"}

        return {
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "name": "Shaft collar", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "assumptions": [],
            "requirements": [
                {"id": f"REQ_{binding.upper()}", "statement": binding,
                 "measurement": binding, "comparison": "equals",
                 "threshold": mm(value), "type": "geometric",
                 "verification": "exact_geometry", "strength": "hard",
                 "source": "user", "state": "accepted"}
                for binding, value in claims
            ],
            "components": [{
                "id": "collar", "name": "Shaft collar",
                "material": "aluminium_6061_t6",
                "parameters": [
                    {"id": "outer_diameter", "value": mm(25)},
                    {"id": "length", "value": mm(15)},
                ],
                "features": [
                    {"id": "body", "kind": "cylinder", "parameters": {
                        "diameter": {"expression": "outer_diameter",
                                     "unit": "mm"},
                        "height": {"expression": "length", "unit": "mm"},
                        "origin": {"vector": [0, 0, 0], "unit": "mm"}}},
                ],
            }],
        }

    def _statuses(self, claims):
        import json

        from forge_ir import Document
        from forge_pipeline import verify_component

        document = Document.from_json(json.dumps(self._collar(claims)))
        report = verify_component(
            document, document.components[0], measurement_depth=8)
        return {
            result.gate.identifier: result.evidence.status.value
            for result in report.gate_results
            if result.gate.identifier.startswith("REQ_")
        }

    def test_a_correct_envelope_can_now_be_shown_correct(self) -> None:
        """A round part is its diameter in BOTH x and y, its length in z."""
        statuses = self._statuses([
            ("bounding_box_x", 25), ("bounding_box_y", 25),
            ("bounding_box_z", 15)])
        self.assertEqual(set(statuses.values()), {"PASS"}, statuses)

    def test_a_size_the_part_does_not_have_still_fails(self) -> None:
        """The claims a live run actually produced, by pouring the brief's
        numbers into the slots in order. Widening must not rescue them.

        `bounding_box_y = 15` passes here, and that is not the tolerance
        doing it: the collar really is 15 mm in a direction, and an equality
        claim about size is resolved against the object rather than against
        an axis nobody had chosen when it was written. See `SizeIsNotAnAxis`.
        `bounding_box_z = 12` is a figure the part does not have in any
        direction, and nothing else in this set checks it, so it fails --
        which is the property this test is really here to hold."""
        statuses = self._statuses([
            ("bounding_box_x", 25), ("bounding_box_y", 15),
            ("bounding_box_z", 12)])
        self.assertEqual(statuses["REQ_BOUNDING_BOX_X"], "PASS")
        self.assertEqual(statuses["REQ_BOUNDING_BOX_Y"], "PASS")
        self.assertEqual(statuses["REQ_BOUNDING_BOX_Z"], "FAIL")

    def test_a_wildly_wrong_claim_still_fails(self) -> None:
        statuses = self._statuses([("bounding_box_z", 150)])
        self.assertEqual(statuses["REQ_BOUNDING_BOX_Z"], "FAIL")


class SizeIsNotAnAxis(unittest.TestCase):
    """An equality claim about size is checked against the part, not an axis.

    The requirements engineer writes its requirements before the design
    exists; the designer chooses the orientation afterwards. So
    `bounding_box_x equals 25 mm`, written at that stage, is a claim about a
    coordinate frame nobody has fixed yet, and the axis in it is not a
    statement -- it is the only way the transport let the claim be written.

    Forge is not in that position. By the time the gate runs the part is
    built and measured, and binding a figure to an axis has stopped being a
    guess and become a lookup.

    Five runs of one brief produced the same three claims every time:

        bounding_box_x = 25   bounding_box_y = 15   bounding_box_z = 12

    against a collar measuring 24.81 x 24.81 x 14.89. Only the first was
    right as written. All three are now resolved against the object.

    The tests below are half about what this passes and half about what it
    must still refuse, because a check that cannot fail is not a check.
    """

    @staticmethod
    def _document(claims, diameter=25, length=15):
        from forge_ir import SCHEMA_VERSION

        def mm(v):
            return {"magnitude": float(v), "unit": "mm"}

        return {
            "schema_version": SCHEMA_VERSION, "revision": 1,
            "document_id": "00000000-0000-4000-8000-000000000001",
            "project_id": "00000000-0000-4000-8000-0000000000ff",
            "name": "Shaft collar", "risk_class": "low",
            "units": {"length": "mm", "mass": "kg", "angle": "deg",
                      "force": "N"},
            "assumptions": [],
            "requirements": [
                {"id": identifier, "statement": identifier,
                 "measurement": binding, "comparison": comparison,
                 "threshold": mm(value), "type": "geometric",
                 "verification": "exact_geometry", "strength": "hard",
                 "source": "user", "state": "accepted"}
                for identifier, binding, comparison, value in claims
            ],
            "components": [{
                "id": "collar", "name": "Shaft collar",
                "material": "aluminium_6061_t6",
                "parameters": [
                    {"id": "outer_diameter", "value": mm(diameter)},
                    {"id": "length", "value": mm(length)},
                    # Declared so `parameter:bore_diameter` resolves. The
                    # bore itself is deliberately not cut: the point of these
                    # cases is a claim about the OUTSIDE carrying a figure
                    # that belongs to a hole.
                    {"id": "bore_diameter", "value": mm(12)},
                ],
                "features": [
                    {"id": "body", "kind": "cylinder", "parameters": {
                        "diameter": {"expression": "outer_diameter",
                                     "unit": "mm"},
                        "height": {"expression": "length", "unit": "mm"},
                        "origin": {"vector": [0, 0, 0], "unit": "mm"}}},
                    # The bore is cut, not merely declared: a dimension that
                    # changes nothing about the part is now a gate of its
                    # own, and it is right to object to a fixture that
                    # names a hole it never makes.
                    {"id": "bore", "kind": "hole", "inputs": ["body"],
                     "parameters": {
                        "diameter": {"expression": "bore_diameter",
                                     "unit": "mm"},
                        "position": {"vector": [0, 0, 0], "unit": "mm"},
                        "axis": [0, 0, 1]}},
                ],
            }],
        }

    def _statuses(self, claims, **shape):
        import json

        from forge_ir import Document
        from forge_pipeline import verify_component

        document = Document.from_json(json.dumps(self._document(claims, **shape)))
        report = verify_component(
            document, document.components[0], measurement_depth=8)
        return {
            result.gate.identifier: result.evidence.status.value
            for result in report.gate_results
            if result.gate.identifier.startswith("REQ_")
        }

    # -- what it now gets right -------------------------------------------

    def test_a_size_claimed_on_the_wrong_axis_still_passes(self) -> None:
        """The collar IS 15 mm in a direction. It is z, not y."""
        statuses = self._statuses([
            ("REQ_Y", "bounding_box_y", "equals", 15.0)])
        self.assertEqual(statuses["REQ_Y"], "PASS")

    def test_a_size_claimed_on_the_right_axis_still_passes(self) -> None:
        statuses = self._statuses([
            ("REQ_X", "bounding_box_x", "equals", 25.0)])
        self.assertEqual(statuses["REQ_X"], "PASS")

    def test_the_report_says_which_extent_answered(self) -> None:
        import json

        from forge_ir import Document
        from forge_pipeline import verify_component

        document = Document.from_json(json.dumps(self._document([
            ("REQ_Y", "bounding_box_y", "equals", 15.0)])))
        report = verify_component(
            document, document.components[0], measurement_depth=8)
        said = " ".join(
            " ".join(r.evidence.limitations) for r in report.gate_results
            if r.gate.identifier == "REQ_Y")
        self.assertIn("measured to drive it: z", said)

    # -- what it must still refuse ----------------------------------------

    def test_a_size_the_part_does_not_have_still_fails(self) -> None:
        """Nothing else checks 40 mm, so this is a real claim and it is
        false: the collar is 25, 25 and 15."""
        statuses = self._statuses([
            ("REQ_BIG", "bounding_box_x", "equals", 40.0)])
        self.assertEqual(statuses["REQ_BIG"], "FAIL")

    def test_a_part_at_the_wrong_scale_still_fails(self) -> None:
        statuses = self._statuses(
            [("REQ_X", "bounding_box_x", "equals", 25.0)],
            diameter=250, length=150)
        self.assertEqual(statuses["REQ_X"], "FAIL")

    def test_a_bound_keeps_its_axis(self) -> None:
        """"No taller than 32 mm" is about height. Z is up, the author knew
        it and meant it, and read axis-free the same sentence would be
        satisfied by the part's thinnest direction."""
        statuses = self._statuses(
            [("REQ_TALL", "bounding_box_z", "at_most", 20.0)],
            diameter=60, length=40)
        self.assertEqual(statuses["REQ_TALL"], "FAIL",
                         "a 40 mm tall part must fail a 20 mm height limit")

    def test_a_bound_that_holds_still_passes(self) -> None:
        statuses = self._statuses(
            [("REQ_TALL", "bounding_box_z", "at_most", 50.0)],
            diameter=60, length=40)
        self.assertEqual(statuses["REQ_TALL"], "PASS")

    # -- the restatement, set aside rather than failed ---------------------

    def test_a_wrong_extent_that_restates_a_checked_figure_is_set_aside(self) -> None:
        """The bore is 12 mm. The part is not 12 mm in any direction, and
        `REQ_BORE` checks that same 12 mm and passes."""
        statuses = self._statuses([
            ("REQ_Z", "bounding_box_z", "equals", 12.0),
            ("REQ_BORE", "parameter:bore_diameter", "equals", 12.0),
        ])
        self.assertEqual(statuses["REQ_Z"], "NOT_APPLICABLE")
        self.assertEqual(statuses["REQ_BORE"], "PASS")

    def test_a_wrong_extent_nothing_else_checks_is_a_failure(self) -> None:
        """Same claim, no duplicate. Now it is the only thing saying 12 mm,
        so it is a real requirement and it is false."""
        statuses = self._statuses([
            ("REQ_Z", "bounding_box_z", "equals", 12.0)])
        self.assertEqual(statuses["REQ_Z"], "FAIL")

    def test_a_claim_cannot_excuse_itself(self) -> None:
        """A requirement is not its own corroboration."""
        statuses = self._statuses([
            ("REQ_Z", "bounding_box_z", "equals", 12.0),
            ("REQ_OTHER", "parameter:outer_diameter", "equals", 25.0),
        ])
        self.assertEqual(statuses["REQ_Z"], "FAIL")

    def test_being_set_aside_does_not_block_release(self) -> None:
        import json

        from forge_ir import Document
        from forge_pipeline import verify_component

        document = Document.from_json(json.dumps(self._document([
            ("REQ_Z", "bounding_box_z", "equals", 12.0),
            ("REQ_BORE", "parameter:bore_diameter", "equals", 12.0),
        ])))
        report = verify_component(
            document, document.components[0], measurement_depth=8)
        self.assertEqual(report.overall_status.value, "PASS")
        self.assertEqual(list(report.release_reasons), [])

    def test_a_real_failure_still_blocks_release(self) -> None:
        import json

        from forge_ir import Document
        from forge_pipeline import verify_component

        document = Document.from_json(json.dumps(self._document([
            ("REQ_BIG", "bounding_box_x", "equals", 40.0)])))
        report = verify_component(
            document, document.components[0], measurement_depth=8)
        self.assertNotEqual(report.overall_status.value, "PASS")
        self.assertTrue(report.release_reasons)
