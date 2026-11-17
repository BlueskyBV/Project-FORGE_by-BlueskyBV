"""Spec schema versions (forge_spec.versions; ADR-0026; V2-stage4b-0c.md, 3.2).

- **Versions are read, written and refused** as the draft says them:
  ``schema_version`` "major.minor", or the legacy ``spec_format`` 1 (1.0);
  never both, never a newer one than this Forge reads.
- **Every version reads as the current one**, and is written in it, or in
  an earlier version's form when asked.
- **A spec confirmed before versions stays confirmed:** its lock unlocks
  and checks in the form it was confirmed in (1.0), to the digest the code
  before versions gave it; a new lock is of the current version. A draft's
  digest, which a person's marks are tied to, is as it was.
- **Migrations chain in order**, each once, from the draft's major version
  to the current one.
"""

from __future__ import annotations

import copy
import dataclasses
import unittest
from typing import Any
from unittest import mock

from forge_eval.spec_grade import draft_digest
from forge_spec import versions
from forge_spec.checks import check_draft
from forge_spec.draft import read_draft
from forge_spec.lock import LockError, lock, unlock
from forge_spec.versions import CURRENT, VersionError, migrate, version_of, written
from forge_spec.wire import to_wire
from forge_spec.words import number_words

BRIEF = number_words(
    "A plate 80 mm long, 50 mm wide and 5 mm thick, with a 6 mm hole through its middle."
)


def _v(x: float, words: list[int]) -> dict[str, Any]:
    return {"value": x, "unit": "mm", "from": {"words": words}}


#: Written as specs were before versions (1.0).
OLD: dict[str, Any] = {
    "spec_format": 1,
    "name": "plate",
    "items": [
        {"id": "plate", "kind": "block", "words": [0, 1], "length": _v(80, [2, 3]),
         "width": _v(50, [5, 6]), "height": _v(5, [9, 10])},
        {"id": "hole", "kind": "hole", "words": [16], "on": {"item": "plate", "face": "+z"},
         "diameter": _v(6, [14, 15]), "depth": {"through": True, "from": {"words": [17]}}},
    ],
}  # fmt: skip
#: Its digest, locked by a draft under the person's rules, as the code before versions computed it.
OLD_DIGEST = "75ac667428eebf20d301bbceb1391fda13196346fbc307465790af973a79c35a"
#: Its draft digest, which a person's marks are tied to (forge_eval.spec_grade), as the code before versions computed it.
OLD_DRAFT_DIGEST = "2afcdea7392e1ae9d6bffbf66874f5ae1b75c393fa2df54d787654742b81840e"


def _new() -> dict[str, Any]:
    draft = copy.deepcopy(OLD)
    del draft["spec_format"]
    return {"schema_version": written(CURRENT), **draft}


class VersionsAreReadWrittenAndRefused(unittest.TestCase):
    def test_the_two_spellings(self) -> None:
        self.assertEqual(version_of({"schema_version": "1.1"}), (1, 1))
        self.assertEqual(version_of({"schema_version": "12.0"}), (12, 0))
        self.assertEqual(version_of({"spec_format": 1}), (1, 0))
        self.assertEqual(written((2, 0)), "2.0")

    def test_what_is_refused(self) -> None:
        for raw in ({}, {"schema_version": "1"}, {"schema_version": 1.1}, {"schema_version": "01.1"},
                    {"schema_version": "1.1.0"}, {"spec_format": 2}, {"spec_format": True},
                    {"spec_format": 1, "schema_version": "1.1"}):  # fmt: skip
            with self.subTest(raw=raw), self.assertRaises(VersionError):
                version_of(raw)
        newer = (CURRENT[0], CURRENT[1] + 1)
        for later in (newer, (CURRENT[0] + 1, 0)):
            with self.subTest(later=later), self.assertRaises(VersionError) as caught:
                migrate({"schema_version": written(later)})
            self.assertIn("newer Forge", str(caught.exception))

    def test_every_version_reads_as_the_current_one(self) -> None:
        old, problems = read_draft(OLD)
        self.assertFalse(problems.faults)
        new, problems = read_draft(_new())
        self.assertFalse(problems.faults)
        self.assertEqual(old, new)
        assert new is not None
        self.assertEqual(to_wire(new)["schema_version"], written(CURRENT))
        self.assertNotIn("spec_format", to_wire(new))
        self.assertEqual(to_wire(new, (1, 0))["spec_format"], 1)
        self.assertNotIn("schema_version", to_wire(new, (1, 0)))
        for version in ((1, 0), CURRENT):
            again, _ = read_draft(to_wire(new, version))
            self.assertEqual(again, new)


class AConfirmedSpecStaysConfirmed(unittest.TestCase):
    def test_a_lock_from_before_versions_unlocks(self) -> None:
        confirmed = unlock(copy.deepcopy(OLD), BRIEF, OLD_DIGEST, by="draft")
        self.assertEqual((confirmed.digest, confirmed.version), (OLD_DIGEST, (1, 0)))
        confirmed.check()
        self.assertEqual(to_wire(confirmed.spec, confirmed.version)["spec_format"], 1)

    def test_a_new_lock_is_of_the_current_version(self) -> None:
        report = check_draft(BRIEF, OLD, strict=False)
        self.assertEqual(report.problems, ())
        confirmed = lock(report, BRIEF, by="draft", strict=False)
        self.assertEqual(confirmed.version, CURRENT)
        self.assertNotEqual(confirmed.digest, OLD_DIGEST)
        confirmed.check()
        again = unlock(to_wire(confirmed.spec), BRIEF, confirmed.digest, by="draft")
        self.assertEqual((again.spec, again.version), (confirmed.spec, CURRENT))

    def test_a_drafts_marks_still_grade_it(self) -> None:
        for raw in (OLD, _new()):
            spec, _ = read_draft(raw)
            assert spec is not None
            self.assertEqual(draft_digest(spec), OLD_DRAFT_DIGEST)

    def test_a_changed_one_is_refused(self) -> None:
        changed = copy.deepcopy(OLD)
        changed["items"][0]["length"]["value"] = 81
        with self.assertRaises(LockError):
            unlock(changed, BRIEF, OLD_DIGEST, by="draft")
        with self.assertRaises(
            LockError
        ):  # the same spec relabelled as a newer version
            unlock(_new(), BRIEF, OLD_DIGEST, by="draft")
        confirmed = unlock(copy.deepcopy(OLD), BRIEF, OLD_DIGEST, by="draft")
        with self.assertRaises(LockError):  # its version changed by hand
            dataclasses.replace(confirmed, version=CURRENT).check()


class MigrationsChainInOrder(unittest.TestCase):
    def test_each_major_step_once_from_the_drafts_own(self) -> None:
        def to_two(draft: dict[str, Any]) -> dict[str, Any]:
            """Rename the part."""
            return {**draft, "schema_version": "2.0", "name": draft["name"] + " 2"}

        def to_three(draft: dict[str, Any]) -> dict[str, Any]:
            """Rename it again."""
            return {**draft, "schema_version": "3.0", "name": draft["name"] + " 3"}

        steps = ((1, 2, to_two), (2, 3, to_three))
        with (
            mock.patch.object(versions, "MIGRATIONS", steps),
            mock.patch.object(versions, "CURRENT", (3, 0)),
        ):
            draft, was, made = versions.migrate({"spec_format": 1, "name": "p"})
            self.assertEqual(
                (draft["name"], draft["schema_version"], was), ("p 2 3", "3.0", (1, 0))
            )
            self.assertEqual(
                made, ("1.x to 2.0: Rename the part.", "2.x to 3.0: Rename it again.")
            )
            draft, was, made = versions.migrate({"schema_version": "2.4", "name": "q"})
            self.assertEqual((draft["name"], was, len(made)), ("q 3", (2, 4), 1))
            draft, _, made = versions.migrate({"schema_version": "3.0", "name": "r"})
            self.assertEqual((draft["name"], made), ("r", ()))

    def test_none_yet_and_the_current_version(self) -> None:
        self.assertEqual(versions.MIGRATIONS, ())
        self.assertEqual(CURRENT, (1, 3))


if __name__ == "__main__":
    unittest.main()
