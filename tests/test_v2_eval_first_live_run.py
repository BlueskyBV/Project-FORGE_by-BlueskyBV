"""V2 stage 4: what the live half's first run changed (docs/V2-stage4.md, 14.4).

The owner ran ``forge eval-false-passes`` with Claude Sonnet 5 on
9 November 2026: 23 of 27 ended, every one caught, before ``--max-cost 5``
stopped it, at $5.76. What it found, each fixed at its root:

- **The cost ceiling holds:** a budget given a price refuses a call whose
  worst cost would take the run past it, checks each retry again, and the
  two drafts' shared budget holds each call in flight at its worst cost.
  Without a price, as before.
- **A stopped run** says its error by code and message, keeps the details
  on the ledger, and writes its report.
- **An automatic run's accounting:** "both" said of an item's copies; the
  part named again in a silent sentence; a linking word between one item's
  words, or before the material. And where none of these hold, as before:
  a negation of a shape, a feature named again, a list of what isn't
  modelled, a count word, a linking word between two items.
- **The owner's 23 drafts, replayed** with no model call: every ending as
  the new rules leave it, and all 23 still caught.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forge_cli.eval_corpus import Brief, false_pass_briefs, run_briefs
from forge_cli.spec import SharedBudget, priced, share_budget
from forge_models import (
    AnthropicProvider,
    Budget,
    BudgetExceededError,
    ModelRequest,
    ModelResponse,
    Provider,
    ProviderInfo,
    RetryPolicy,
    ScriptedProvider,
    TransientError,
    Usage,
)
from forge_models.types import StopReason, user
from forge_spec import number_words
from forge_spec.accounting import MATERIAL, account
from forge_spec.checks import check_draft
from v2_drafts import assumed, choose, cite, count, draft, made_of, mm, said
from v2_occ import needs_occ

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path(__file__).resolve().parent / "fixtures" / "false_passes_live"
REQUEST = ModelRequest(system="s", messages=(user("a brief"),), max_output_tokens=1000)


class _Priced(Provider):
    """Each call costs ``cost``; the first ``failures`` attempts fail after being paid for."""

    def __init__(self, cost: float, budget: Budget, failures: int = 0) -> None:
        super().__init__(
            retry=RetryPolicy(max_attempts=3, initial_delay=0.0, jitter=False),
            budget=budget,
        )
        self.cost, self.failures, self.sent = cost, failures, 0

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="priced",
            model="priced",
            supports_structured_output=True,
            is_remote=False,
        )

    def _send(self, request: ModelRequest) -> ModelResponse:
        self.sent += 1
        if self.failures:
            self.failures -= 1
            error = TransientError("dropped")
            error.usage = Usage(input_tokens=10, output_tokens=10, cost_usd=self.cost)
            raise error
        return ModelResponse(text="", structured={"ok": True},
                             usage=Usage(input_tokens=10, output_tokens=10, cost_usd=self.cost),
                             provider="priced", model="priced", stop_reason=StopReason.TOOL_USE,
                             latency_seconds=0.0, request_fingerprint=request.fingerprint())  # fmt: skip


class TheCostCeilingHolds(unittest.TestCase):
    def spent(self, budget: Budget) -> tuple[int, float]:
        provider = _Priced(0.3, budget)
        try:
            while True:
                provider.complete(REQUEST)
        except BudgetExceededError:
            pass
        return provider.sent, round(provider.budget.usage.cost_usd or 0.0, 6)

    def test_a_priced_budget_never_passes_its_ceiling(self) -> None:
        # 0.3 a call, at worst 0.4: the fourth call could take 0.9 past 1.0, and is refused.
        self.assertEqual(
            self.spent(Budget(max_cost_usd=1.0, price=lambda r: 0.4)), (3, 0.9)
        )
        # Unpriced, as before: the call after the one that reaches the ceiling is refused, past it.
        self.assertEqual(self.spent(Budget(max_cost_usd=1.0)), (4, 1.2))

    def test_a_retry_is_checked_again(self) -> None:
        provider = _Priced(
            0.5, Budget(max_cost_usd=1.0, price=lambda r: 0.6), failures=1
        )
        with self.assertRaises(BudgetExceededError) as stopped:
            provider.complete(REQUEST)
        self.assertEqual(
            provider.sent, 1
        )  # the paid-for failure, and no second attempt
        self.assertIn("could take the run past", stopped.exception.message)
        # Unpriced, the retry goes ahead, as before.
        again = _Priced(0.5, Budget(max_cost_usd=1.0), failures=1)
        again.complete(REQUEST)
        self.assertEqual(again.sent, 2)

    def test_the_two_drafts_hold_each_call_in_flight_at_its_worst(self) -> None:
        shared = SharedBudget(Budget(max_cost_usd=1.0, price=lambda r: 0.6))
        shared.check_before(REQUEST)  # this thread's call, in flight
        found: list[BaseException | None] = []

        def other() -> None:
            try:
                shared.check_before(REQUEST)
                found.append(None)
            except BudgetExceededError as error:
                found.append(error)

        thread = threading.Thread(target=other)
        thread.start()
        thread.join()
        self.assertIsInstance(found[0], BudgetExceededError)
        shared.release()  # this thread's call is over, unspent: the other's may go
        thread = threading.Thread(target=other)
        thread.start()
        thread.join()
        self.assertIsNone(found[1])

    def test_shared_the_dearer_price_and_the_command_s_own(self) -> None:
        first = ScriptedProvider(
            [], budget=Budget(max_cost_usd=5.0, price=lambda r: 0.2)
        )
        second = ScriptedProvider(
            [], budget=Budget(max_cost_usd=5.0, price=lambda r: 0.5)
        )
        share_budget(first, second)
        assert first.budget.price is not None
        self.assertEqual(first.budget.price(REQUEST), 0.5)
        self.assertIs(first.budget, second.budget)
        sonnet = priced(
            AnthropicProvider(
                model="claude-sonnet-5", api_key="not-a-key", thinking="off"
            )
        )
        self.assertIsNotNone(sonnet.budget.price)
        self.assertIsNone(priced(ScriptedProvider([])).budget.price)

    def test_the_worst_a_request_can_cost(self) -> None:
        sonnet = AnthropicProvider(
            model="claude-sonnet-5", api_key="not-a-key", thinking="off"
        )
        tokens_in = REQUEST.approximate_input_tokens() * 4 / 3
        self.assertAlmostEqual(sonnet.worst_cost_usd(REQUEST) or 0.0,
                               (tokens_in * 3.0 * 1.25 + 1000 * 15.0) / 1e6)  # fmt: skip
        # Where the model thinks, its thinking's room is output too.
        thinking = AnthropicProvider(
            model="claude-sonnet-5", api_key="not-a-key", thinking="adaptive"
        )
        asked = ModelRequest(system="s", messages=(user("a brief"),), schema={"type": "object"},
                             max_output_tokens=1000)  # fmt: skip
        self.assertGreater(thinking.worst_cost_usd(asked) or 0.0, 30_000 * 15.0 / 1e6)
        unknown = AnthropicProvider(
            model="claude-unpriced-9", api_key="not-a-key", thinking="off"
        )
        self.assertIsNone(unknown.worst_cost_usd(REQUEST))


BLOCK = "A 30 mm cube."


def _cube(id_: str = "cube") -> dict[str, Any]:
    b = number_words(BLOCK)
    return draft(id_, [{"id": "cube", "kind": "block", "words": cite(b, "cube"),
                        **{n: mm(b, 30, "30 mm cube") for n in ("length", "width", "height")}}])  # fmt: skip


class AStoppedRun(unittest.TestCase):
    def test_says_its_error_short_keeps_the_details_and_writes_its_report(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            briefs = [
                Brief("one", BLOCK, "a cube", None, False),
                Brief("two", BLOCK, "a cube", None, False),
            ]
            # The first is drafted; the second's answer is refused, and its repair would pass the call budget.
            provider = ScriptedProvider([_cube(), {}], budget=Budget(max_calls=2))
            said: list[str] = []
            ended, stopped = run_briefs(
                briefs, provider, out, strict=False, say=said.append
            )
            self.assertEqual([e.id for e in ended], ["one"])
            self.assertTrue(
                stopped.startswith(
                    "two: [MD1007_BUDGET_EXCEEDED] the run has reached its model-call"
                )
            )
            line = next(s for s in said if s.startswith("Stopped"))
            self.assertNotIn("refused_answers", line)
            ledger = [
                json.loads(x)
                for x in (out / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn("refused_answers", ledger[-1]["error"]["detail"])
            report = (out / "report.md").read_text(encoding="utf-8")
            self.assertIn("Stopped  : two: [MD1007_BUDGET_EXCEEDED]", report)
            self.assertIn("- one", report)


def _questions(text: str, *, items: tuple[Any, ...] = (), silent: int | None = None,
               not_modelled: str | None = None) -> list[str]:  # fmt: skip
    """An automatic run's questions on a 30 mm cube in PLA, with ``items`` beside it."""
    b = number_words(text)
    cube = {"id": "cube", "kind": "block", "words": cite(b, "cube"),
            **{n: mm(b, 30, "30 mm cube") for n in ("length", "width", "height")}}  # fmt: skip
    quiet = [] if silent is None else [{"sentence": silent, "reason": "its load case"}]
    left = (
        []
        if not_modelled is None
        else [{"words": cite(b, not_modelled), "reason": "its load case"}]
    )
    d = draft("cube", [cube, *(make(b) for make in items)], material=made_of(b, "PLA"),
              silent=quiet, not_modelled=left)  # fmt: skip
    return [
        p.message
        for p in check_draft(b, d, strict=True).problems
        if p.kind == "question"
    ]


def _hole(where: str) -> Any:
    def make(b: Any) -> dict[str, Any]:
        return {"id": "hole", "kind": "hole", "words": cite(b, where), "on": {"item": "cube", "face": "+z"},
                "diameter": mm(b, 6, "6 mm"), "depth": {"through": True, "from": said(b, "through")},
                "place": {"x": {"centred": assumed("t")}, "y": {"centred": assumed("t")}}}  # fmt: skip

    return make


class AnAutomaticRunsAccounting(unittest.TestCase):
    CLOSING = "It carries no load - it is a cube, so there is no load case."

    def test_the_part_named_again_in_a_silent_sentence(self) -> None:
        self.assertEqual(
            _questions(f"A 30 mm cube in PLA. {self.CLOSING}", silent=1), []
        )

    def test_a_negation_of_a_shape_or_a_feature_named_again_still_asks(self) -> None:
        for closing in ("It is a cube with no holes.", "It is not a cube."):
            with self.subTest(closing=closing):
                found = _questions(f"A 30 mm cube in PLA. {closing}", silent=1)
                self.assertTrue(any("can't take as silent" in m for m in found), found)
        # The hole is a feature: named again, it may say more of it.
        found = _questions("A 30 mm cube in PLA with a 6 mm hole through it. It is a hole.",
                           items=(_hole("hole"),), silent=1)  # fmt: skip
        self.assertTrue(any("can't take as silent" in m for m in found), found)

    def test_a_list_of_what_isn_t_modelled_keeps_the_old_rule(self) -> None:
        found = _questions(
            f"A 30 mm cube in PLA. {self.CLOSING}", not_modelled="it is a cube"
        )
        self.assertTrue(
            any("can't leave out" in m and "'cube'" in m for m in found), found
        )

    def test_a_linking_word_between_one_item_s_words_or_before_the_material(
        self,
    ) -> None:
        on_top = _questions("A 30 mm cube in PLA with a 6 mm hole through it on the top face.",
                            items=(_hole("hole through it on the top face"),))  # fmt: skip
        self.assertEqual(on_top, [])
        # Between two items' words: "a 6 mm hole from the cube" joins the hole to the cube.
        found = _questions("A 30 mm cube in PLA with a 6 mm hole through it from the cube.",
                           items=(_hole("hole through it"),))  # fmt: skip
        self.assertIn("nothing in the spec uses the word 'from'", found)

    def test_a_count_word_or_a_negation_is_never_linked(self) -> None:
        b = number_words("A slot at each end, a hole on no face, in PLA.")
        slot, hole = frozenset({"slot"}), frozenset({"hole"})
        owners = {1: slot, 4: slot, 6: hole, 9: hole, 11: frozenset({MATERIAL})}
        found = account(b, mentions=[[1, 4], [6, 9], [11]], owners=owners)
        self.assertEqual(
            sorted(w.text for w in found.uncited_words), ["at", "each", "no", "on"]
        )

    def test_both_said_of_an_item_s_copies(self) -> None:
        def plate(text: str, holes: str, n: int) -> list[str]:
            b = number_words(text)
            items = [{"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60 mm long"),
                      "width": mm(b, 40, "40 mm wide"), "height": mm(b, 5, "5 mm thick")},
                     {"id": "holes", "kind": "hole", "words": cite(b, holes), "on": {"item": "plate", "face": "+z"},
                      "diameter": mm(b, 4, "4 mm"), "depth": {"through": True, "from": said(b, "through it")},
                      "place": {"x": {"centred": assumed("t")},
                                "y": {"centred": said(b, "both centred across the width")}}}]  # fmt: skip
            if n > 1:
                items[1]["count"] = count(b, n, "Two")
                items[1]["place"]["pattern"] = {"row": {"axis": choose("x", said(b, "along the length")),
                                                        "pitch": mm(b, 20, "20 mm apart"), "count": count(b, n, "Two")}}  # fmt: skip
            return [p.message for p in check_draft(b, draft("plate", items)).problems]

        self.assertEqual(plate("A plate 60 mm long, 40 mm wide and 5 mm thick. Two 4 mm holes 20 mm apart along the "
                               "length go through it, both centred across the width.", "holes", 2), [])  # fmt: skip
        # One hole: "both" is no count of its copies.
        self.assertEqual(plate("A plate 60 mm long, 40 mm wide and 5 mm thick. A 4 mm hole goes through it, both "
                               "centred across the width.", "hole", 1),
                         ["the brief says 'both' (sentence 2); nothing in the spec uses it"])  # fmt: skip


#: The owner's live runs (9 and 10 November 2026), as today's rules leave each draft: replayed, no model called.
ENDINGS = {
    "fp01": "questions", "fp02": "questions", "fp03": "questions", "fp04": "questions", "fp05": "questions",
    "fp06": "stops for a person", "fp07": "stops for a person", "fp08": "stops for a person", "fp09": "questions",
    "fp10": "stops for a person", "fp11": "BUILT TO DRAFT", "fp12": "stops for a person", "fp13": "BUILT TO DRAFT",
    "fp14": "BUILT TO DRAFT", "fp15": "stops for a person", "fp16": "questions", "fp17": "questions",
    "fp18": "questions", "fp19": "questions", "fp20": "stops for a person", "fp21": "stops for a person",
    "fp22": "stops for a person", "fp23": "questions",
    # Its second run (10 November): the last four, drafted within --max-cost 20 (docs/V2-stage4.md, 14.4).
    "fp24": "refused", "fp25": "questions", "fp26": "questions", "fp27": "questions",
}  # fmt: skip


@needs_occ
class TheOwnersFirstLiveRunReplayed(unittest.TestCase):
    def test_every_ending_and_every_false_pass_caught(self) -> None:
        briefs = [
            b
            for b in false_pass_briefs(ROOT / "validation" / "false_passes.json")
            if b.id in ENDINGS
        ]
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "run"
            shutil.copytree(LIVE, out)
            ended, stopped = run_briefs(
                briefs, None, out, strict=True, say=lambda line: None
            )
        self.assertEqual(stopped, "")
        self.assertEqual({e.id: e.ending for e in ended}, ENDINGS)
        self.assertTrue(
            all(e.caught for e in ended), [e.id for e in ended if not e.caught]
        )
        self.assertTrue(all(not e.drafted for e in ended))


if __name__ == "__main__":
    unittest.main()
