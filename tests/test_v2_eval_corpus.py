"""V2 stage 4: ``forge eval-corpus`` and ``forge eval-false-passes`` (docs/V2-stage4.md, 14.2 and 14.3).

No model is called: a scripted one answers with drafts, as the spec writer
would. Each brief's records are written, a recorded brief is replayed at no
cost (and never drafted twice), each determinate draft is built as ``forge
build`` builds one, and each ends as the module says; a false pass is
caught unless a wrong part is released, and one released wrong is said,
and sets the exit code. The keys the command reads are tests/v2_false_passes.py's.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from forge_cli.eval_corpus import (
    EXIT_NOT_CAUGHT,
    Brief,
    command_eval_false_passes,
    corpus_briefs,
    false_pass_briefs,
    report_lines,
    run_briefs,
)
from forge_models import ScriptedProvider
from forge_spec import number_words

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_occ import needs_occ
from v2_suite_specs import DRAFTS, SUITE, suite

BLOCK = suite()["P02"].brief


def drafted(id_: str) -> dict[str, Any]:
    return DRAFTS[id_](number_words(suite()[id_].brief))


def turned(answer: dict[str, Any]) -> dict[str, Any]:
    """The block's draft with its length and width swapped: each still cites its own words, and the part is turned."""
    wrong = copy.deepcopy(answer)
    block = wrong["items"][0]
    block["length"], block["width"] = block["width"], block["length"]
    return wrong


class Folder(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.out = Path(self._folder.name)
        self.said: list[str] = []

    def tearDown(self) -> None:
        self._folder.cleanup()


class TheBriefs(Folder):
    def test_from_the_suite_a_run_and_a_list_each_once(self) -> None:
        run = self.out / "a_run.json"
        run.write_text(json.dumps({"brief": BLOCK, "answer": {}}), encoding="utf-8")
        listed = self.out / "more.txt"
        listed.write_text(
            "A PLA cube 10 mm on each side.\n\n" + BLOCK + "\n", encoding="utf-8"
        )
        found = corpus_briefs([SUITE, run, listed])
        self.assertEqual(len(found), 93)
        self.assertEqual((found[0].id, found[0].title), ("R01", suite()["R01"].title))
        self.assertEqual(found[-1].text, "A PLA cube 10 mm on each side.")
        self.assertEqual(len({b.id for b in found}), 93)

    def test_the_smoke_check_takes_its_few_briefs_afresh_within_a_ceiling(self) -> None:
        import contextlib
        import io

        from forge_cli.cli import build_parser
        from forge_cli.eval_corpus import SMOKE, SMOKE_COST, corpus_briefs

        ids = {b.id for b in corpus_briefs([SUITE])}
        self.assertTrue(set(SMOKE) <= ids, set(SMOKE) - ids)
        args = build_parser().parse_args(["eval-corpus", "--smoke", "--replay", "--out", str(self.out)])
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            args.handler(args)
        self.assertIn(f"Briefs   : {len(SMOKE)}", said.getvalue())
        self.assertEqual(args.max_cost, SMOKE_COST)

    def test_the_false_passes_keys_are_the_tests(self) -> None:
        from v2_false_passes import KEYS, keys

        self.assertEqual(
            json.loads(KEYS.read_text(encoding="utf-8")), json.loads(json.dumps(keys()))
        )
        briefs = false_pass_briefs(KEYS)
        self.assertEqual([b.id for b in briefs], [f"fp{n:02d}" for n in range(1, 28)])
        self.assertTrue(all(b.false_pass for b in briefs))
        # No right part: the poem and the washer; none V2 can make as given yet, the dome on its side (V2-stage4.md, 14.8).
        self.assertEqual([b.id for b in briefs if b.key is None], ["fp16", "fp21", "fp22", "fp23"])


@needs_occ
class ARun(Folder):
    def test_drafted_built_and_replayed_at_no_cost(self) -> None:
        briefs = [Brief("P02", BLOCK), Brief("odd", "A plate. Print 3 of them.")]
        plate = {"spec_format": 1, "name": "plate", "items": [{"id": "plate", "kind": "block", "words": [1],
                 "length": {"value": 10, "unit": "mm", "from": {"assumed": "for the test"}},
                 "width": {"value": 10, "unit": "mm", "from": {"assumed": "for the test"}},
                 "height": {"value": 1, "unit": "mm", "from": {"assumed": "for the test"}}}],
                 "not_modelled": [], "silent": []}  # fmt: skip
        provider = ScriptedProvider([drafted("P02"), plate])
        ended, stopped = run_briefs(
            briefs, provider, self.out, strict=False, say=self.said.append
        )
        self.assertFalse(stopped)
        self.assertEqual([(e.id, e.ending, e.drafted) for e in ended],
                         [("P02", "BUILT TO DRAFT", True), ("odd", "questions", True)])  # fmt: skip
        self.assertIn("'3'", ended[1].why)
        for name in ("answer.json", "draft.json", "problems.json", "spec.txt", "calls.json", "record.json",
                     "build/verdict.json"):  # fmt: skip
            self.assertTrue((self.out / "P02" / name).is_file(), name)
        self.assertIn(
            "BUILT TO DRAFT: 1", (self.out / "report.md").read_text(encoding="utf-8")
        )
        # Again, with no model: what is recorded is read, checked and built again; nothing is drafted.
        again, _ = run_briefs(
            briefs, None, self.out, strict=False, say=self.said.append
        )
        self.assertEqual([(e.id, e.ending, e.drafted) for e in again],
                         [("P02", "BUILT TO DRAFT", False), ("odd", "questions", False)])  # fmt: skip
        self.assertEqual(len(provider.requests), 2)
        ledger = [
            json.loads(line)
            for line in (self.out / "ledger.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual([line["key"] for line in ledger], ["P02", "odd", "P02", "odd"])

    def test_a_version_handed_over_as_a_number_builds_live_and_replayed(self) -> None:
        # Blind set 1's drafts arrived with "schema_version" the number 1.9; the corpus read its records raw.
        answer = dict(drafted("P02"))
        answer.pop("spec_format", None)
        answer["schema_version"] = 1.9
        briefs = [Brief("P02", BLOCK)]
        ended, _ = run_briefs(briefs, ScriptedProvider([answer]), self.out, strict=False, say=self.said.append)
        again, _ = run_briefs(briefs, None, self.out, strict=False, say=self.said.append)
        self.assertEqual([(e.ending, e.drafted) for e in ended + again],
                         [("BUILT TO DRAFT", True), ("BUILT TO DRAFT", False)])  # fmt: skip

    def test_a_false_pass_caught_or_not(self) -> None:
        right = drafted("P02")
        briefs = [Brief("right", BLOCK, "the right block", right, True),
                  Brief("wrong", BLOCK, "the block turned", right, True),
                  Brief("poem", "Write me a poem about bridges.", "no part", None, True)]  # fmt: skip
        poem = {"spec_format": 1, "name": "x", "items": [{"id": "cube", "kind": "block", "words": [3],
                **{n: {"value": 1, "unit": "mm", "from": {"assumed": "a placeholder"}}
                   for n in ("length", "width", "height")}}], "not_modelled": [], "silent": []}  # fmt: skip
        provider = ScriptedProvider([copy.deepcopy(right), turned(right), poem])
        ended, _ = run_briefs(
            briefs, provider, self.out, strict=True, say=self.said.append
        )
        self.assertEqual([(e.id, e.ending, e.caught) for e in ended],
                         [("right", "BUILT TO DRAFT", True), ("wrong", "BUILT TO DRAFT", False),
                          ("poem", "questions", True)])  # fmt: skip
        self.assertIn("its key fails it", ended[1].why)
        lines = report_lines(briefs, ended, True)
        self.assertIn("False passes: 2 of 3 caught; NOT CAUGHT: wrong", lines)

    def test_the_command_says_a_false_pass_released(self) -> None:
        keys = self.out / "keys.json"
        keys.write_text(json.dumps([{"number": 1, "case": "a block", "brief": BLOCK, "key": drafted("P02")}]),
                        encoding="utf-8")  # fmt: skip
        args = _args(keys=str(keys), out=str(self.out / "run"), only=None, replay=True)
        # Recorded first, so the command replays it with no model.
        run_briefs([Brief("fp01", BLOCK, "a block", drafted("P02"), True)], ScriptedProvider([turned(drafted("P02"))]),
                   self.out / "run", strict=True, say=self.said.append)  # fmt: skip
        self.assertEqual(command_eval_false_passes(args), EXIT_NOT_CAUGHT)


def _args(**values: Any) -> Any:
    import argparse

    return argparse.Namespace(**values)


if __name__ == "__main__":
    unittest.main()
