"""The kinds' facts each role keeps, held to the written definitions (V2-stage4b-0b.md, 8): a wrong copy can't pass unseen.

A role's own facts that copy what a kind's definition says (its faces, its
edges, its category, its options' words) are checked against the schema
here; the generator, the third implementation, keeps its own copies, each
checked so.
"""

from __future__ import annotations

import unittest

from forge_spec.schema import KINDS, Category

SIX = frozenset({"+x", "-x", "+y", "-y", "+z", "-z"})


class TheRolesFactsAgreeWithTheDefinitions(unittest.TestCase):
    def test_the_hollowable_bodies_are_the_same_in_every_role(self) -> None:
        from forge_checks.items.place import PLACE
        from forge_eval.items.draw import DRAW
        from forge_spec.items.solve import SOLVE

        solve = {k for k, e in SOLVE.items() if e.hollowable}
        self.assertEqual(solve, {"block", "cylinder", "cone", "sphere"})  # shell.md
        self.assertEqual({k for k, v in KINDS.items() if v.hollowable}, solve)
        self.assertEqual({k for k, e in PLACE.items() if e.hollowable}, solve)
        self.assertEqual({k for k, e in DRAW.items() if e.openable}, solve)

    def test_the_generator_opens_only_faces_a_body_has(self) -> None:
        from forge_eval.items.draw import DRAW

        for kind, entry in DRAW.items():
            with self.subTest(kind=kind):
                self.assertLessEqual(set(entry.openable), set(KINDS[kind].faces))
                self.assertEqual(len(set(entry.openable)), len(entry.openable))

    def test_the_generator_rounds_only_edge_sets_a_kind_has(self) -> None:
        from forge_eval.items.draw import DRAW

        for kind, entry in DRAW.items():
            for first in (True, False):
                with self.subTest(kind=kind, first=first):
                    self.assertLessEqual(
                        set(entry.roundable(first)), set(KINDS[kind].edges)
                    )

    def test_the_judge_s_rims_are_edge_sets_of_their_kind(self) -> None:
        from forge_checks.items.place import PLACE

        for kind, entry in PLACE.items():
            with self.subTest(kind=kind):
                self.assertLessEqual(set(entry.rims), set(KINDS[kind].edges))
                if entry.both_ends:
                    self.assertIn("both", KINDS[kind].edges)

    def test_the_compiler_s_boxes_are_the_kinds_with_all_six_faces(self) -> None:
        from forge_checks.items.compile import COMPILE

        self.assertEqual(
            {k for k, e in COMPILE.items() if e.boxed},
            {k for k, v in KINDS.items() if set(v.faces) >= SIX},
        )

    def test_the_planner_s_families_are_the_categories_letters_aside(self) -> None:
        from forge_plan.items.plan import PLAN
        from forge_plan.items.plan._families import BodyPlan, CutPlan, StandingPlan

        def kinds(family: type) -> set[str]:
            return {k for k, e in PLAN.items() if isinstance(e, family)}

        def category(c: Category) -> set[str]:
            return {k for k, v in KINDS.items() if v.category is c}

        self.assertEqual(kinds(BodyPlan), category(Category.BODY))
        self.assertEqual(kinds(StandingPlan), category(Category.ADD))
        self.assertEqual(kinds(CutPlan), category(Category.CUT) - {"text"})

    def test_a_cut_out_is_a_cut_but_letters(self) -> None:
        from forge_eval.items.brief import BRIEF
        from forge_eval.items.draw import DRAW
        from forge_eval.items.grade import GRADE

        cuts = {k for k, v in KINDS.items() if v.category is Category.CUT} - {"text"}
        for name, registry in (("draw", DRAW), ("brief", BRIEF), ("grade", GRADE)):
            with self.subTest(role=name):
                self.assertEqual({k for k, e in registry.items() if e.cut_out}, cuts)

    def test_every_word_the_brief_says_for_an_option_is_one_of_its_synonyms(
        self,
    ) -> None:
        from forge_eval.items.brief import BRIEF

        checked = 0
        for kind, entry in BRIEF.items():
            fields = {f.name: f for f in KINDS[kind].fields}
            for choice, words in entry.option_words.items():
                spec = fields[choice]
                self.assertEqual(set(words), set(spec.choices), (kind, choice))
                for option, word in words.items():
                    checked += 1
                    with self.subTest(kind=kind, choice=choice, option=option):
                        self.assertIn(word, (spec.synonyms or {}).get(option, ()))
        self.assertGreater(checked, 0)

    def test_the_threadable_rods_agree_in_every_role(self) -> None:
        from forge_checks.items.compile import COMPILE
        from forge_checks.items.oracle import ORACLE
        from forge_eval.items.draw import DRAW
        from forge_plan.items.plan import PLAN

        for name, registry in (
            ("plan", PLAN),
            ("compile", COMPILE),
            ("oracle", ORACLE),
            ("draw", DRAW),
        ):
            with self.subTest(role=name):
                rods = {k: e.rod_length for k, e in registry.items() if e.threadable}
                self.assertEqual(rods, {"cylinder": "length", "boss": "height"})
                for kind, length in rods.items():
                    self.assertIn(length, {f.name for f in KINDS[kind].fields})


class TheDrawsListsAreFixed(unittest.TestCase):
    """Every seed draws as it did (V2-stage4b-0b.md, 3): the generator's weighted lists are 4b.0b's, kind for kind.

    A kind added later is drawn from its own named random stream (as
    ``_decorate``'s letters and studs are), never by joining these lists, so
    no old seed draws differently and 2.4's replays stay valid.
    """

    def test_they_are_today_s(self) -> None:
        from forge_eval.generator import _weighted

        self.assertEqual(
            _weighted("flat_weight", "flat_rank"),
            ["hole"] * 4 + ["pocket"] * 2 + ["slot", "boss", "post", "block", "tab"],
        )
        self.assertEqual(
            _weighted("flat_weight", "flat_rank", lambda e: e.cut_out),
            ["hole"] * 4 + ["pocket"] * 2 + ["slot"],
        )
        self.assertEqual(
            _weighted("new_weight", "new_rank"),
            ["rib", "rib", "cone", "tube", "sphere"],
        )


if __name__ == "__main__":
    unittest.main()
