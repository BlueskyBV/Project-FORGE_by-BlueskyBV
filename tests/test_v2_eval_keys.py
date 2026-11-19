"""V2: answer keys, written and locked before Forge runs (forge_eval.keys)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from forge_eval.keys import (
    AnswerKey,
    AnswerKeyError,
    HoleFact,
    lock_set,
    verify_manifest,
)

SET1 = Path(__file__).resolve().parent.parent / "eval" / "blind" / "set1"


def plate() -> AnswerKey:
    return AnswerKey(
        id="T-01", brief="A plate.", written_by="test", independent=False, expect="verified",
        note="", envelope_mm=(5, 50, 80), volume_mm3=(19000, 20000),
        through_holes=(HoleFact((4.4, 4.6), 4),),
    )  # fmt: skip


class KeysAreWellFormed(unittest.TestCase):
    def test_a_good_key(self) -> None:
        self.assertEqual(plate().through_holes[0].count, 4)

    def test_bad_keys(self) -> None:
        good = plate().as_dict()
        for change in ({"expect": "maybe"}, {"envelope_mm": [80, 50, 5]},
                       {"volume_mm3": [20, 10]}, {"envelope_mm": None},
                       {"expect": "question", "questions": []}):  # fmt: skip
            raw = {**good, **change}
            with self.assertRaises(AnswerKeyError, msg=change):
                from forge_eval.keys import key_from_dict

                key_from_dict(raw)

    def test_a_bad_hole_fact(self) -> None:
        with self.assertRaises(AnswerKeyError):
            HoleFact((5.0, 4.0), 1)
        with self.assertRaises(AnswerKeyError):
            HoleFact((4.0, 5.0), 0)


class SetsAreLocked(unittest.TestCase):
    def test_lock_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_set(Path(tmp), [plate()], "test")
            self.assertEqual(set(verify_manifest(Path(tmp))), {"T-01"})

    def test_a_changed_key_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_set(Path(tmp), [plate()], "test")
            path = Path(tmp) / "T-01.json"
            raw = json.loads(path.read_text())
            raw["volume_mm3"] = [1, 2]
            path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(AnswerKeyError, "changed after"):
                verify_manifest(Path(tmp))

    def test_an_unlisted_key_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_set(Path(tmp), [plate()], "test")
            (Path(tmp) / "T-02.json").write_text("{}")
            with self.assertRaisesRegex(AnswerKeyError, "not in the manifest"):
                verify_manifest(Path(tmp))


@unittest.skipUnless(SET1.is_dir(), "the blind set stays on the owner's machine: eval/ is never pushed")
class BlindSetOne(unittest.TestCase):
    def test_it_is_locked_and_intact(self) -> None:
        keys = verify_manifest(SET1)
        self.assertEqual(len(keys), 30)
        expects = [k.expect for k in keys.values()]
        self.assertEqual(expects.count("cant"), 1)
        self.assertEqual(expects.count("question"), 3)
        self.assertTrue(all(not k.independent for k in keys.values()))


if __name__ == "__main__":
    unittest.main()
