"""Pointer resolution and the patch subset that repair is built on.

These are small tests for a small module, and they matter out of proportion to
their size: every repair the system makes goes through here, and a patch that
lands one position off does not raise -- it produces a document that compiles,
verifies, and is not the design anyone approved.
"""

from __future__ import annotations

import copy
import json
import unittest

from forge_roles.patch import (
    Patch,
    PatchError,
    PointerError,
    apply_patches,
    exists,
    extract_slice,
    parse_pointer,
    resolve,
    unescape_token,
)

DOCUMENT = {
    "name": "example",
    "components": [
        {
            "id": "part",
            "parameters": [
                {"id": "a", "value": 1},
                {"id": "b", "value": 2},
                {"id": "c", "value": 3},
                {"id": "d", "value": 4},
            ],
            "features": [{"id": "f0"}, {"id": "f1"}, {"id": "f2"}, {"id": "f3"}],
        }
    ],
    "odd/key": {"with~tilde": "here"},
}


class Pointers(unittest.TestCase):
    def test_the_empty_pointer_is_the_whole_document(self) -> None:
        self.assertEqual(parse_pointer(""), ())
        self.assertIs(resolve(DOCUMENT, ""), DOCUMENT)

    def test_a_pointer_must_start_with_a_slash(self) -> None:
        with self.assertRaises(PointerError):
            parse_pointer("components/0")

    def test_escapes_decode_in_the_order_rfc_6901_requires(self) -> None:
        """``~01`` is ``~1``, not ``/``. Decoding ``~0`` first would get this wrong."""
        self.assertEqual(unescape_token("~01"), "~1")
        self.assertEqual(unescape_token("~1"), "/")
        self.assertEqual(unescape_token("~0"), "~")
        self.assertEqual(resolve(DOCUMENT, "/odd~1key/with~0tilde"), "here")

    def test_resolving_reaches_into_arrays(self) -> None:
        self.assertEqual(resolve(DOCUMENT, "/components/0/features/2/id"), "f2")

    def test_a_missing_key_names_what_was_available(self) -> None:
        with self.assertRaises(PointerError) as caught:
            resolve(DOCUMENT, "/components/0/nope")
        self.assertIn("available", caught.exception.detail)

    def test_a_non_numeric_array_index_is_refused(self) -> None:
        with self.assertRaises(PointerError):
            resolve(DOCUMENT, "/components/first")

    def test_exists_answers_without_raising(self) -> None:
        self.assertTrue(exists(DOCUMENT, "/components/0/id"))
        self.assertFalse(exists(DOCUMENT, "/components/9"))


class Applying(unittest.TestCase):
    def setUp(self) -> None:
        self.original = copy.deepcopy(DOCUMENT)

    def test_the_input_document_is_never_mutated(self) -> None:
        apply_patches(
            self.original, [Patch("replace", "/components/0/parameters/0/value", 99)]
        )
        self.assertEqual(self.original, DOCUMENT)

    def test_replace_requires_the_key_to_exist(self) -> None:
        """Otherwise a typo silently becomes a new field the compiler rejects.

        The message used to end "use 'add'", and that advice is wrong more
        often than right. Observed live: an analyst invented a diagnosis that
        a `box` had been given `diameter` -- it had not -- and patched that
        key. Told to use `add`, the obedient next step is to put a `diameter`
        on a box, which the schema then refuses. An absent key is usually
        evidence the diagnosis is wrong, so the message now says what the
        object actually has and leaves the choice to the reader.
        """
        with self.assertRaises(PointerError) as caught:
            apply_patches(
                self.original, [Patch("replace", "/components/0/parametrs", [])]
            )
        self.assertIn("parametrs", caught.exception.message)
        detail = str(caught.exception)
        self.assertIn("parameters", detail, "it must name what is there")

    def test_add_appends_with_a_dash(self) -> None:
        result = apply_patches(
            self.original, [Patch("add", "/components/0/features/-", {"id": "f4"})]
        )
        self.assertEqual(result["components"][0]["features"][-1], {"id": "f4"})

    def test_the_whole_document_may_not_be_replaced(self) -> None:
        with self.assertRaises(PatchError) as caught:
            apply_patches(self.original, [Patch("replace", "", {})])
        self.assertIn("what patching exists to avoid", str(caught.exception))

    def test_a_failed_patch_leaves_nothing_half_applied(self) -> None:
        with self.assertRaises(PatchError):
            apply_patches(
                self.original,
                [
                    Patch("replace", "/components/0/parameters/0/value", 99),
                    Patch("replace", "/components/0/missing", 1),
                ],
            )
        self.assertEqual(self.original, DOCUMENT)


class RemovalOrdering(unittest.TestCase):
    """The trap: individually correct removals that combine into the wrong one."""

    def test_two_removals_delete_what_their_author_pointed_at(self) -> None:
        result = apply_patches(
            copy.deepcopy(DOCUMENT),
            [
                Patch("remove", "/components/0/features/1"),
                Patch("remove", "/components/0/features/3"),
            ],
        )
        kept = [f["id"] for f in result["components"][0]["features"]]
        self.assertEqual(
            kept,
            ["f0", "f2"],
            "removals were applied in the order given, so the second one "
            "deleted whatever had shifted into position 3",
        )

    def test_removals_in_different_arrays_do_not_interfere(self) -> None:
        result = apply_patches(
            copy.deepcopy(DOCUMENT),
            [
                Patch("remove", "/components/0/features/0"),
                Patch("remove", "/components/0/parameters/2"),
            ],
        )
        component = result["components"][0]
        self.assertEqual([f["id"] for f in component["features"]], ["f1", "f2", "f3"])
        self.assertEqual(
            [p["id"] for p in component["parameters"]], ["a", "b", "d"]
        )

    def test_mixing_a_removal_and_a_positional_edit_is_fine(self) -> None:
        """This was refused, and refusing it cost a run a repair round.

        Replacements are applied first, against the document exactly as the
        author saw it, so `/features/2` means the third element they were
        shown. The removal then runs last. Both pointers mean what they say
        and no convention is being assumed on the author's behalf.
        """
        result = apply_patches(
            copy.deepcopy(DOCUMENT),
            [
                Patch("remove", "/components/0/features/1"),
                Patch("replace", "/components/0/features/2", {"id": "new"}),
            ],
        )
        # Shown f0 f1 f2 f3; asked to drop f1 and replace f2.
        self.assertEqual(
            [f["id"] for f in result["components"][0]["features"]],
            ["f0", "new", "f3"],
        )

    def test_a_removal_beside_an_edit_in_another_array_is_fine(self) -> None:
        result = apply_patches(
            copy.deepcopy(DOCUMENT),
            [
                Patch("remove", "/components/0/features/1"),
                Patch("replace", "/components/0/parameters/0/value", 42),
            ],
        )
        component = result["components"][0]
        self.assertEqual([f["id"] for f in component["features"]], ["f0", "f2", "f3"])
        self.assertEqual(component["parameters"][0]["value"], 42)

    def test_an_edit_reached_through_a_shifted_array_is_fine_too(self) -> None:
        """``/features/2/id`` reaches a field *through* a slot, and that is
        still safe for a replacement: it is applied before any removal, so
        index 2 is the element the author was shown."""
        result = apply_patches(
            copy.deepcopy(DOCUMENT),
            [
                Patch("remove", "/components/0/features/0"),
                Patch("replace", "/components/0/features/2/id", "renamed"),
            ],
        )
        self.assertEqual(
            [f["id"] for f in result["components"][0]["features"]],
            ["f1", "renamed", "f3"],
        )

    def test_an_insert_beside_a_removal_is_still_refused(self) -> None:
        """The one combination the ordering cannot save. The insert runs
        first and shifts everything after it, so the removal would delete the
        wrong element."""
        with self.assertRaises(PatchError) as caught:
            apply_patches(
                copy.deepcopy(DOCUMENT),
                [
                    Patch("remove", "/components/0/features/3"),
                    Patch("add", "/components/0/features/1", {"id": "x"}),
                ],
            )
        self.assertIn("addresses by position", caught.exception.message)
        self.assertIn("hint", caught.exception.detail)

    def test_appending_beside_a_removal_is_fine(self) -> None:
        """`/-` inserts past the end, so it renumbers nothing."""
        result = apply_patches(
            copy.deepcopy(DOCUMENT),
            [
                Patch("remove", "/components/0/features/1"),
                Patch("add", "/components/0/features/-", {"id": "added"}),
            ],
        )
        self.assertEqual(
            [f["id"] for f in result["components"][0]["features"]],
            ["f0", "f2", "f3", "added"],
        )

    def test_a_removal_deep_inside_a_shifted_array_is_refused(self) -> None:
        """Removals get the descending convention only when they are siblings."""
        with self.assertRaises(PatchError):
            apply_patches(
                copy.deepcopy(DOCUMENT),
                [
                    Patch("remove", "/components/0/features/0"),
                    Patch("remove", "/components/0/features/2/id"),
                ],
            )


class Decoding(unittest.TestCase):
    def test_unsupported_operations_are_named(self) -> None:
        for op in ("move", "copy", "test"):
            with self.assertRaises(PatchError) as caught:
                Patch.from_dict({"op": op, "pointer": "/a"})
            self.assertIn("supported", caught.exception.detail)

    def test_path_is_accepted_as_a_synonym_for_pointer(self) -> None:
        patch = Patch.from_dict({"op": "replace", "path": "/a", "value": 1})
        self.assertEqual(patch.pointer, "/a")

    def test_a_patch_without_a_pointer_is_refused(self) -> None:
        with self.assertRaises(PatchError):
            Patch.from_dict({"op": "remove"})

    def test_a_removal_serialises_without_a_value(self) -> None:
        self.assertNotIn("value", Patch("remove", "/a").as_dict())

    def test_rendering_truncates_a_large_value(self) -> None:
        rendered = Patch("add", "/a", {"x": "y" * 200}).render()
        self.assertLess(len(rendered), 120)
        self.assertTrue(rendered.endswith("..."))


class Slicing(unittest.TestCase):
    def test_a_slice_carries_its_pointers_as_keys(self) -> None:
        sliced = extract_slice(
            DOCUMENT, ("/components/0/features/1",), context=0
        )
        self.assertEqual(sliced, {"/components/0/features/1": {"id": "f1"}})

    def test_context_lifts_to_the_enclosing_object(self) -> None:
        sliced = extract_slice(
            DOCUMENT, ("/components/0/features/1/id",), context=1
        )
        self.assertEqual(list(sliced), ["/components/0/features/1"])

    def test_an_unresolvable_pointer_is_skipped_rather_than_faked(self) -> None:
        sliced = extract_slice(DOCUMENT, ("/components/9/nope",), context=0)
        self.assertEqual(sliced, {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class ARepairMayNotEditWhatItIsJudgedBy(unittest.TestCase):
    """The accepted record is out of reach of every repair.

    Found by an external audit and reproduced exactly: five patches, all of
    which applied cleanly against the then-current source.

        replace /requirements/0/threshold/magnitude -> 999.0
        replace /assumptions/0/approved            -> true
        remove  /requirements/0
        replace /requirements/0/comparison         -> "at_least"
        replace /risk_class                        -> "low"

    The second is the worst of them. An unapproved high-risk assumption
    blocking release is the one place where Forge insists on a human, and a
    repair round could grant that approval to itself.

    The separation these tests defend is the premise of the whole system: a
    deterministic verifier compares geometry against a record the model cannot
    reach. Without it, "every gate passed" says only that the model found the
    gates inconvenient, and the report still reads PASS -- which is worse than
    no verification, because it looks checked.
    """

    DOCUMENT = {
        "requirements": [
            {
                "id": "R1",
                "threshold": {"magnitude": 8.0, "unit": "g"},
                "comparison": "at_most",
                "state": "accepted",
            }
        ],
        "assumptions": [{"id": "A1", "risk": "high", "approved": False}],
        "risk_class": "high",
        "components": [
            {
                "id": "c",
                "parameters": [{"id": "t", "value": {"magnitude": 4.0, "unit": "mm"}}],
                "features": [],
            }
        ],
    }

    #: Each of the audit's five probes, plus the `state` field, which is how a
    #: requirement got into the record in the first place.
    FORBIDDEN = {
        "relax a threshold": Patch(
            op="replace", pointer="/requirements/0/threshold/magnitude", value=999.0
        ),
        "approve its own assumption": Patch(
            op="replace", pointer="/assumptions/0/approved", value=True
        ),
        "delete a requirement": Patch(op="remove", pointer="/requirements/0"),
        "flip the comparison": Patch(
            op="replace", pointer="/requirements/0/comparison", value="at_least"
        ),
        "lower the risk class": Patch(
            op="replace", pointer="/risk_class", value="low"
        ),
        "mark a requirement accepted": Patch(
            op="replace", pointer="/requirements/0/state", value="accepted"
        ),
        "add a requirement of its own": Patch(
            op="add", pointer="/requirements/1", value={"id": "R2"}
        ),
    }

    def _document(self) -> dict:
        return json.loads(json.dumps(self.DOCUMENT))

    def test_every_one_of_them_is_refused(self) -> None:
        for name, patch in self.FORBIDDEN.items():
            with self.subTest(name):
                with self.assertRaises(PatchError):
                    apply_patches(self._document(), [patch])

    def test_the_refusal_says_what_to_do_instead(self) -> None:
        """A repair that reached for a requirement misread the problem."""
        for name, patch in self.FORBIDDEN.items():
            with self.subTest(name):
                try:
                    apply_patches(self._document(), [patch])
                except PatchError as error:
                    message = str(error)
                    self.assertTrue(
                        "geometry" in message or "design" in message,
                        f"{name} was refused without saying what to fix: {message}",
                    )

    def test_a_legitimate_geometry_repair_still_applies(self) -> None:
        """The guard must not cost the repair loop its actual job."""
        patched = apply_patches(
            self._document(),
            [
                Patch(
                    op="replace",
                    pointer="/components/0/parameters/0/value/magnitude",
                    value=6.0,
                )
            ],
        )
        self.assertEqual(
            patched["components"][0]["parameters"][0]["value"]["magnitude"], 6.0
        )

    def test_a_mixed_batch_changes_nothing_at_all(self) -> None:
        """All-or-nothing, or a repair could smuggle one edit past the guard."""
        document = self._document()
        with self.assertRaises(PatchError):
            apply_patches(
                document,
                [
                    Patch(
                        op="replace",
                        pointer="/components/0/parameters/0/value/magnitude",
                        value=6.0,
                    ),
                    Patch(
                        op="replace",
                        pointer="/requirements/0/threshold/magnitude",
                        value=999.0,
                    ),
                ],
            )
        self.assertEqual(
            document["requirements"][0]["threshold"]["magnitude"], 8.0
        )
        self.assertEqual(
            document["components"][0]["parameters"][0]["value"]["magnitude"], 4.0
        )
