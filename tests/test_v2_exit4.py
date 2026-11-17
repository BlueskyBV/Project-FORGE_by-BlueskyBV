"""V2 stage 4: the exit test's script on three seeds (docs/V2-stage4.md, 14.1; tests/v2_exit4.py).

Seeds 9 to 11, the tenth among them: each part as asked passes the judge
and is graded the generator's own shape both ways; its mutant is caught, or
leaves the shape as it was; seed 10's impossible part is turned back, and
its second kernel and three files pass. The records are kept, a second run
runs none again, and the report sums them.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_occ import needs_occ


@needs_occ
class TheExitTestOnThreeSeeds(unittest.TestCase):
    def test_run_resumed_and_reported(self) -> None:
        import v2_exit4

        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            args = ["--from", "9", "--to", "12", "--out", str(out)]
            v2_exit4.main(args)
            records = {
                r["seed"]: r
                for r in map(
                    json.loads,
                    (out / "records.jsonl").read_text(encoding="utf-8").splitlines(),
                )
            }
            self.assertEqual(sorted(records), [9, 10, 11])
            for seed, record in records.items():
                with self.subTest(seed=seed):
                    self.assertEqual(
                        record["outcome"],
                        "passed",
                        record.get("why") or record.get("held"),
                    )
                    self.assertEqual(record["graded"], [])
                    self.assertGreater(record["memory MB"], 0)
                    mutant = record["mutant"]
                    self.assertIn(
                        mutant and mutant["outcome"], ("caught", "same shape", None)
                    )
            self.assertEqual(
                records[10]["impossible"]["ended"],
                "turned back",
                records[10]["impossible"],
            )
            self.assertTrue(records[10]["views"]["passed"], records[10]["views"])
            # Run again: every seed is recorded, so none runs, and the report is the same three.
            self.assertEqual(v2_exit4.main(args), 0)
            lines = (out / "records.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            report = (out / "report.md").read_text(encoding="utf-8")
            self.assertIn("The exit passes: yes.", report)
            self.assertIn("- passed: 3 of 3", report)
            self.assertIn("turned back (CAN'T or a question): 1 of 1", report)
            self.assertIn("## By pair of kinds", report)
            self.assertIn("## Memory per part", report)


@needs_occ
class AMutantThatLeavesTheShape(unittest.TestCase):
    """Whether a mutant changes the shape: shown cheaply where it can be, by the symmetric difference only where it can't.

    Generated part 7858: an M3 thread's hand mutated, left to right. The two
    have one volume, and the boolean between them ran 15 minutes and more;
    the worker died of a segfault. A point of either's surface far from the
    other's shows them different, with no boolean made.
    """

    @staticmethod
    def _threaded(hand: str) -> Any:
        from forge_eval.generator import Feature, Position, render

        centred = Position(mode="centred", distance=0.0, side="", to="centre")
        plain: dict[str, Any] = {"depth": None, "recess": None, "angle": None, "pattern": None, "outline": None,
                                 "faces": None}  # fmt: skip
        return render(
            (
                Feature(
                    id="body",
                    kind="block",
                    sizes={"length": 20.0, "width": 20.0, "height": 10.0},
                    on=None,
                    choices={},
                    place={},
                    words=None,
                    of=None,
                    **plain,
                ),
                Feature(
                    id="i0",
                    kind="boss",
                    sizes={"diameter": 3.0, "height": 4.0},
                    on=("body", "+z"),
                    choices={},
                    place={"x": centred, "y": centred},
                    words=None,
                    of=None,
                    **plain,
                ),
                Feature(
                    id="i1",
                    kind="thread",
                    sizes={},
                    on=None,
                    choices={"hand": hand},
                    place={},
                    words="M3",
                    of="i0",
                    **plain,
                ),
            )
        ).truth

    def test_threads_of_opposite_hands_differ_with_no_boolean(self) -> None:
        import v2_exit4

        with mock.patch(
            "OCP.BRepAlgoAPI.BRepAlgoAPI_Cut",
            side_effect=AssertionError("a boolean was made"),
        ):
            self.assertTrue(
                v2_exit4._changes_shape(self._threaded("left"), self._threaded("right"))
            )

    def test_the_same_truth_leaves_the_shape(self) -> None:
        import v2_exit4

        truth = self._threaded("left")
        self.assertFalse(v2_exit4._changes_shape(truth, truth))

    def test_a_hole_through_moved_to_the_face_across_leaves_the_shape(self) -> None:
        """Generated part 477: a slot turned 120 degrees in a block's side, crossed by a slot through the block. Its
        truth's faces merged came out invalid (and the merging left the solid it was given invalid too), so its mutant,
        a row of holes through the block moved to the face across, made no exact boolean with it and was taken for
        another shape, which survived. Merged on a copy, and kept unmerged where the merged one isn't valid, the two
        are one shape."""
        from dataclasses import replace

        import v2_exit4
        from forge_eval.generator import render
        from OCP.BRepCheck import BRepCheck_Analyzer
        from v2_regressions import REGRESSIONS
        from v2_truth_occ import build

        plan = REGRESSIONS[477][1]
        moved = tuple(replace(f, on=("body", "+z")) if f.id == "i4" else f for f in plan)
        one, other = render(plan).truth, render(moved, strict=False).truth
        self.assertTrue(BRepCheck_Analyzer(build(one)).IsValid())
        self.assertFalse(v2_exit4._changes_shape(one, other))


class WorkersThatDieOrHang(unittest.TestCase):
    """A worker killed on a seed, or silent past the limit, is recorded against that seed, and its other seeds run; one that runs out of memory ends, and a fresh one runs the rest."""

    #: A stand-in worker: seed 3 kills it, seed 5 hangs it, seed 6 runs out of memory, and it says other things on
    #: its output besides.
    FAKE = textwrap.dedent(
        """
        import json, os, signal, sys, time
        for seed in map(int, sys.argv[1].split(",")):
            if seed == 3:
                os.kill(os.getpid(), signal.SIGKILL)
            if seed == 5:
                time.sleep(60)
            if seed == 6:
                lost = {"seed": 6, "seconds": {}, "outcome": "error", "why": "MemoryError: it ran out"}
                print("v2_exit4 record: " + json.dumps(lost), flush=True)
                sys.exit(75)
            print("a library's own line", flush=True)
            record = {"seed": seed, "seconds": {"all": 0.0}, "outcome": "passed"}
            print("a half line, then v2_exit4 record: " + json.dumps(record), flush=True)
        """
    )

    def test_each_seed_recorded_once(self) -> None:
        import v2_exit4

        out = io.StringIO()
        with (
            mock.patch.object(v2_exit4, "BATCH", 4),
            mock.patch.object(v2_exit4, "SEED_LIMIT", 3.0),
            mock.patch("builtins.print"),
        ):
            v2_exit4.run(range(10), 2, out, (sys.executable, "-c", self.FAKE))
        records = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(sorted(r["seed"] for r in records), list(range(10)))
        by_seed = {r["seed"]: r for r in records}
        self.assertIn("killed by signal 9", by_seed[3]["why"])
        self.assertIn("made no record in 3 s", by_seed[5]["why"])
        self.assertEqual(by_seed[6]["why"], "MemoryError: it ran out")
        self.assertEqual(
            [s for s, r in sorted(by_seed.items()) if r["outcome"] == "passed"],
            [0, 1, 2, 4, 7, 8, 9],
        )
        self.assertEqual(len(v2_exit4.failures(by_seed[3])), 1)


class RunAgain(unittest.TestCase):
    def test_only_the_seeds_that_fail_run_again_and_their_records_are_replaced(
        self,
    ) -> None:
        import v2_exit4

        def record(seed: int, outcome: str) -> dict[str, object]:
            return {
                "seed": seed,
                "seconds": {"all": 1.0},
                "outcome": outcome,
                "why": "MemoryError: out",
            }

        given: list[tuple[list[int], list[str]]] = []

        def run(
            seeds: list[int], workers: int, out: io.TextIOBase, command: list[str]
        ) -> None:
            given.append((list(seeds), list(command)))
            for seed in seeds:
                out.write(json.dumps(record(seed, "passed")) + "\n")

        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(v2_exit4, "run", run),
            mock.patch("builtins.print"),
        ):
            path = Path(folder) / "records.jsonl"
            path.write_text(
                "".join(
                    json.dumps(record(s, "error" if s in (2, 7) else "passed")) + "\n"
                    for s in range(8)
                ),
                encoding="utf-8",
            )
            args = ["--from", "0", "--to", "5", "--out", folder, "--memory", "2800"]
            self.assertEqual(v2_exit4.main(args), 1)  # seed 2 fails the exit
            self.assertEqual(given[-1][0], [])
            self.assertEqual(v2_exit4.main([*args, "--again"]), 0)
            seeds, command = given[-1]
            self.assertEqual(seeds, [2])
            self.assertEqual(command[-3:], ["--memory", "2800", "--worker"])
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(sorted(r["seed"] for r in records), list(range(8)))
            self.assertEqual(
                [r["seed"] for r in records if r["outcome"] == "error"], [7]
            )


class TheViewSeedsFirst(unittest.TestCase):
    def test_they_run_first_and_the_rest_after_each_in_order(self) -> None:
        """With --views-first, the seeds left to run that also run the second kernel and the files come first, then the rest, each in order; a seed recorded already runs neither way."""
        import v2_exit4

        given: list[list[int]] = []

        def run(
            seeds: list[int], workers: int, out: io.TextIOBase, command: list[str]
        ) -> None:
            given.append(list(seeds))
            for seed in seeds:
                out.write(json.dumps({"seed": seed, "seconds": {"all": 1.0}, "outcome": "passed"}) + "\n")  # fmt: skip

        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(v2_exit4, "run", run),
            mock.patch("builtins.print"),
        ):
            done = {"seed": 20, "seconds": {"all": 1.0}, "outcome": "passed"}
            (Path(folder) / "records.jsonl").write_text(json.dumps(done) + "\n", encoding="utf-8")  # fmt: skip
            args = ["--from", "8", "--to", "33", "--out", folder]
            self.assertEqual(v2_exit4.main([*args, "--views-first"]), 0)
            self.assertEqual(given[-1], [10, 30, 8, 9, *range(11, 20), *range(21, 30), 31, 32])  # fmt: skip
            # Run again in order, every seed is recorded already.
            self.assertEqual(v2_exit4.main(args), 0)
            self.assertEqual(given[-1], [])
        self.assertEqual(v2_exit4.order_views_first([3, 0, 10, 7]), [0, 10, 3, 7])


class EveryWayASeedFailsTheExit(unittest.TestCase):
    """A seed fails the exit by its part, its mutant, its impossible part or its views; the report and the exit code both say so."""

    PASSED: ClassVar[dict[str, Any]] = {
        "seed": 10,
        "seconds": {"all": 60.0},
        "outcome": "passed",
        "kinds": ["block", "hole"],
        "made_by": {"body": "flush"},
        "held": [],
        "graded": [],
        "mutant": {"item": "i0", "leaf": "diameter", "outcome": "caught", "by": ["diameter"]},
        "impossible": {"why": "too deep", "ended": "turned back", "said": ["question: ..."]},
        "views": {"agreement": {"holds": True, "disagreements": 0, "names_missing": []},
                  "step": [], "stl": [], "3mf": [], "passed": True},
    }  # fmt: skip

    def test_each_way(self) -> None:
        import v2_exit4

        self.assertEqual(v2_exit4.failures(self.PASSED), [])
        self.assertEqual(v2_exit4.failures({**self.PASSED, "mutant": None}), [])
        self.assertEqual(
            v2_exit4.failures({**self.PASSED, "mutant": {"item": "i0", "leaf": "x", "outcome": "same shape"}}), []
        )  # fmt: skip
        ways = {
            "held": {"outcome": "held", "held": ["B-rep: checks: diameter: INCONCLUSIVE: ..."]},
            "unable": {"outcome": "unable", "why": "i2: no construction"},
            "survived": {"mutant": {"item": "i0", "leaf": "depth", "outcome": "survived", "by": []}},
            "not built": {"mutant": {"item": "i0", "leaf": "depth", "outcome": "not built", "why": "refused"}},
            "ended built": {"impossible": {"why": "too deep", "ended": "built", "said": []}},
            "ended fault": {"impossible": {"why": "too deep", "ended": "fault", "said": ["fault: ..."]}},
            "the second kernel": {"views": {**self.PASSED["views"], "passed": False,
                                            "agreement": {"holds": False, "disagreements": 2}}},
            "stl": {"views": {**self.PASSED["views"], "passed": False, "stl": ["STL: checks: angle"]}},
        }  # fmt: skip
        for said, change in ways.items():
            with self.subTest(said):
                record = {**self.PASSED, **change}
                found = v2_exit4.failures(record)
                self.assertEqual(len(found), 1, found)
                self.assertIn(said.split(":")[0], found[0])
                text = v2_exit4.report([self.PASSED, {**record, "seed": 11}], 1.0)
                self.assertIn("The exit passes: no, 1 of 2 seeds fail it", text)
                self.assertIn(f"- seed 11: {found[0]}", text)
        self.assertIn("The exit passes: yes.", v2_exit4.report([self.PASSED], 1.0))


if __name__ == "__main__":
    unittest.main()
