"""The restructure's fingerprint (tests/v2_fingerprint.py): its canonical form tells outputs apart, and its runs compare."""

from __future__ import annotations

import dataclasses
import enum
import functools
import json
import math
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import v2_fingerprint as fp


class _Colour(enum.Enum):
    RED = 1


@dataclasses.dataclass
class _Kept:
    shown: float
    _memo: float = 0.0


class _Plain:
    def __init__(self, shown: int) -> None:
        self.shown = shown
        self._memo = shown + 1

    @functools.cached_property
    def later(self) -> int:
        return self.shown * 2


class TheCanonicalForm(unittest.TestCase):
    def test_floats_are_told_apart_to_the_last_bit(self) -> None:
        self.assertNotEqual(fp.digest(1.0), fp.digest(1.0 + 2**-52))
        self.assertNotEqual(fp.digest(0.0), fp.digest(-0.0))
        self.assertNotEqual(fp.digest(1), fp.digest(1.0))
        self.assertEqual(fp.canonical(math.inf), "inf")

    def test_order_is_kept_where_it_is_behaviour_and_sets_are_sorted(self) -> None:
        self.assertNotEqual(fp.digest([1, 2]), fp.digest([2, 1]))
        self.assertNotEqual(fp.digest({"a": 1, "b": 2}), fp.digest({"b": 2, "a": 1}))
        self.assertEqual(fp.digest({"a", "b", "c"}), fp.digest({"c", "b", "a"}))
        self.assertNotEqual(fp.digest({"a"}), fp.digest(["a"]))

    def test_types_enums_and_fractions_are_named(self) -> None:
        self.assertEqual(fp.canonical(_Colour.RED), "_Colour.RED")
        self.assertEqual(fp.canonical(Fraction(1, 3)), {"fraction": [1, 3]})
        self.assertNotEqual(fp.digest(Fraction(1, 3)), fp.digest(1 / 3))

    def test_memos_and_callables_are_left_out(self) -> None:
        self.assertEqual(fp.digest(_Kept(1.0, 5.0)), fp.digest(_Kept(1.0, 6.0)))
        self.assertNotEqual(fp.digest(_Kept(1.0)), fp.digest(_Kept(2.0)))
        plain = _Plain(3)
        before = fp.digest(plain)
        _ = plain.later
        self.assertEqual(fp.digest(plain), before)
        self.assertEqual(fp.canonical(len), "<callable>")
        self.assertEqual(fp.canonical(lambda: 1), "<callable>")

    def test_arrays_by_their_bytes_type_and_shape(self) -> None:
        a = np.arange(6, dtype=float)
        self.assertEqual(fp.digest(a), fp.digest(np.arange(6, dtype=float)))
        self.assertNotEqual(fp.digest(a), fp.digest(a.reshape(2, 3)))
        self.assertNotEqual(fp.digest(a), fp.digest(a.astype(np.float32)))
        self.assertEqual(fp.canonical(np.float64(0.5)), "0x1.0000000000000p-1")

    def test_a_cycle_ends_and_an_unknown_value_is_refused(self) -> None:
        loop: list[object] = []
        loop.append(loop)
        self.assertEqual(fp.canonical(loop), ["<cycle>"])
        with self.assertRaises(TypeError):
            fp.canonical(complex(1, 2))

    def test_what_a_program_raises_is_digested(self) -> None:
        out = fp._Sections()

        def fails() -> None:
            raise ValueError("no")

        self.assertIsNone(out("x", fails))
        self.assertEqual(
            out.digests["x"], fp.digest({"raised": "ValueError", "message": "no"})
        )
        with self.assertRaises(ValueError):
            out("x", lambda: 1)


class TheSample(unittest.TestCase):
    def test_the_sample_is_fixed(self) -> None:
        seeds = fp.sample()
        self.assertEqual(len(set(seeds)), 1000)
        self.assertEqual(seeds[:5], [2, 9, 14, 15, 17])
        self.assertEqual(seeds, sorted(seeds))
        self.assertTrue(all(0 <= s < 10_000 for s in seeds))


class Comparing(unittest.TestCase):
    def _run(
        self, root: Path, name: str, records: dict[int, dict[str, str]], **head: object
    ) -> Path:
        out = root / name
        out.mkdir()
        header = {"harness": "h", "code": "c", "python": "3", "numpy": "2", "machine": "m",
                  "hash_seed": "0", "verdicts": False, "once": {"guide": "g"}, **head}  # fmt: skip
        (out / "header.json").write_text(json.dumps(header), encoding="utf-8")
        lines = [json.dumps({"seed": s, "digests": d}) for s, d in records.items()]
        (out / "records.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out

    def test_equal_runs_have_no_differences_and_their_environments_are_told(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = self._run(root, "a", {1: {"x": "1", "y": "2"}})
            b = self._run(root, "b", {1: {"x": "1", "y": "2"}}, hash_seed="1")
            found, told = fp.compare(a, b)
            self.assertEqual(found, [])
            self.assertEqual(told, ["hash_seed: 0 | 1"])

    def test_every_difference_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = self._run(root, "a", {1: {"x": "1", "y": "2"}, 2: {"x": "1"}})
            b = self._run(root, "b", {1: {"x": "1", "y": "3"}, 3: {"x": "1"}},
                          once={"guide": "other"})  # fmt: skip
            found, _ = fp.compare(a, b)
            self.assertEqual(
                found, ["once guide", "seed 1 y", "2 seeds in one run only: [2, 3]"]
            )

    def test_a_section_one_run_lacks_is_a_difference_but_for_the_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = self._run(root, "a", {1: {"x": "1"}})
            b = self._run(root, "b", {1: {"x": "1", "y": "2"}})
            self.assertEqual(fp.compare(a, b)[0], ["seed 1: sections [] | ['y']"])
            c = self._run(root, "c", {1: {"x": "1", "verdict": "v"}}, verdicts=True)
            self.assertEqual(fp.compare(a, c)[0], [])

    def test_seed_lists(self) -> None:
        self.assertEqual(fp._seeds("3-6"), [3, 4, 5])
        self.assertEqual(fp._seeds("7,2"), [7, 2])
        self.assertEqual(fp._seeds("sample:3"), [2, 9, 14])


if __name__ == "__main__":
    unittest.main()
