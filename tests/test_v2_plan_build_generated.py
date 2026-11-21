"""V2 stage 4: generated parts planned, built, judged and graded (docs/V2-stage4.md, sections 8, 12.3 and 15).

Generated specs (forge_eval.generator, the exit test's own), planned,
built through the build loop and judged as a run judges them: face
accounting and every check pass; and graded against the generator's own
model of it both ways (forge_eval.grade): the built part's surface where the
model's is, the model's where the built part's is, every copy's box the same
inside, and the volume that of the model made exactly by OpenCascade.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_plan_build import judged_plan
from v2_occ import needs_occ

if TYPE_CHECKING:
    from forge_eval.generator import Plan

#: The generated parts built here (the exit test builds 10,000).
SEEDS = range(8)


@needs_occ
class GeneratedPartsAreTheirSpecs(unittest.TestCase):
    def graded(self, seed: int, plan: Plan | None = None, strict: bool = True) -> None:
        """A generated part planned, built, judged and graded: no gap, face accounting and every check pass, and the built part is the generator's own shape, graded against it both ways (12.3; its volume against the shape made exactly). ``strict``: a kept plan rendered as the generator now would (else as made when it was found, held to no rule it wasn't made by)."""
        from forge_checks.classes import Verdict
        from forge_checks.view import ViewProxy
        from forge_eval.generator import generate, render
        from forge_eval.grade import grade
        from forge_occ.view import BrepView
        from forge_plan.planner import _plan
        from forge_spec.placement import solve
        from v2_exit4 import (
            _spec,  # as a run reads it: a cut through the next face resolved by the preview first
        )
        from v2_truth_occ import build

        case = generate(seed) if plan is None else render(plan, strict=strict)
        assert case.truth is not None
        spec = _spec(case.items)
        built, accounting, failed = judged_plan(
            spec, _plan(spec, solve(spec), digest=None)
        )
        self.assertIsNone(built.gap, built.refusals)
        self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
        self.assertEqual(failed, [])
        made = ViewProxy(BrepView(built.result.shape))
        g = grade(
            case.truth, made, exact=ViewProxy(BrepView(build(case.truth))), seed=seed
        )
        self.assertTrue(g.passed, g.problems())

    def test_built_judged_and_graded(self) -> None:
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.graded(seed)

    def test_the_parts_that_found_faults_built_judged_and_graded(self) -> None:
        """Kept plans that found faults in building, judging or grading (tests/v2_regressions.py): a box's side pressed against a hollow's wall, a point OpenCascade's classifier put inside, posts in a circle round a rod; and the exit test's pilot's: a hole breaking into a pocket's ceiling, a pulley's axis, a letter's tip; and its run's: two letters touching at a corner, a radial hole through a hollowed cylinder's wall, a rounded pocket's exact model, a grid of posts near a block's bottom, a needle's apex, a dome's rim, a needle's tip in the exact model, a countersink's points in one ring; and the held-out run's: a hole through a tube's wall that OpenCascade refused flush, carried into the air (10890); a blind hole into a tube's wall whose plug OpenCascade kept beside the part (10517); a hole through a tube's wall again (11384); and the kernel replay's: a hole through a tube hung in a closed hollow, its carrying not holding (4935)."""
        from v2_regressions import REGRESSIONS

        found = (50, 76, 77, 53, 61, 93, 108, 168, 219, 233, 244, 492, 1101, 1159)
        held_out, replay = (10890, 10517, 11384), (4935,)
        for seed in (*found, *held_out, *replay):
            with self.subTest(seed=seed, found=REGRESSIONS[seed][0]):
                self.graded(seed, REGRESSIONS[seed][1])

    def test_the_exit_pairs_finds_built_judged_and_graded(self) -> None:
        """Kept plans the exit pair on the fp fix and on 2b's first step found faults with (tests/v2_regressions.py): a leaning post's long edges rounded, and a leaning boss's far rim rounded where it dips into its face, where the truth's rounding didn't stop at the face's plane (3640, 1038, 3551); letters whose ink lies all below their point, asked about as twice as tall (2361); holes through everything from a hollow box's thin floor, measured past it (4217)."""
        from v2_regressions import REGRESSIONS

        for seed in (3640, 1038, 3551, 2361, 4217):
            with self.subTest(seed=seed, found=REGRESSIONS[seed][0]):
                self.graded(seed, REGRESSIONS[seed][1])

    def test_through_the_next_faces_finds_built_judged_and_graded(self) -> None:
        """Kept plans that found faults with a cut through the next face (item 2b's third step; tests/v2_regressions.py): a hole down each of a row of leaning bosses and out of the block's floor at a slant, its end's rim touching the floor where it comes out all across its mouth, carried on past it where that is proven where it is moved to (184)."""
        from v2_regressions import REGRESSIONS

        for seed in (184,):
            with self.subTest(seed=seed, found=REGRESSIONS[seed][0]):
                self.graded(seed, REGRESSIONS[seed][1])

    def test_the_holes_opencascade_refused_built_judged_and_graded(self) -> None:
        """Kept plans whose hole through the next face OpenCascade refused flush, and carried at its mouth only
        (tests/v2_regressions.py): one from the far face of a post standing round a rod's side, out into a bore (2231);
        one from a dome's surface, out of its flat face at its middle (4599). Each built with its round tools turned
        about their axes (V2-stage4.md, 5.7) and, now, carried past its end first (5.2)."""
        from v2_regressions import REGRESSIONS

        for seed in (2231, 4599):
            with self.subTest(seed=seed, found=REGRESSIONS[seed][0]):
                self.graded(seed, REGRESSIONS[seed][1])

    def test_a_cut_carried_past_where_it_comes_out_built_judged_and_graded(self) -> None:
        """A kept plan whose hole through the next face OpenCascade made wrong without a flag, its end touching a
        flange's underside at a point (4944; tests/v2_regressions.py): carried past its end into the air the preview
        shows there (V2-stage4.md, 5.2)."""
        from v2_regressions import REGRESSIONS

        self.graded(4944, REGRESSIONS[4944][1])

    def test_insets_from_a_footed_side_built_judged_and_graded(self) -> None:
        """A kept plan whose corners pattern on a post's flat side, the post standing round a tube, had its inset
        measured from where the post's foot follows the tube's curve (1911; tests/v2_regressions.py): no edge of the
        side's own there, so its place there is held by face accounting."""
        from v2_regressions import REGRESSIONS

        self.graded(1911, REGRESSIONS[1911][1])

    def test_the_judges_misses_at_small_angles_and_short_walls_built_judged_and_graded(self) -> None:
        """Kept plans the exit harness found the judge failing (tests/v2_regressions.py): a hole grazing a tube's side, judged on its files (1880); and on seeds 5,000 on, a leaning hole's window in a pocket's floor, its tip's built point a hair inside the hole (5035), and round pockets whose walls another pocket leaves only their first millimetre, measured as a pattern from past it (5162). Their truths' meshes stray where surfaces meet at small angles (test_v2_eval_truth.STRAYING_MESHES): their B-reps are judged here."""
        from v2_regressions import REGRESSIONS

        for seed in (1880, 5035, 5162):
            with self.subTest(seed=seed, found=REGRESSIONS[seed][0]):
                # 1880 as made when it was found: its hole through everything comes out of the dome's flat face
                # through the tube's wall standing there, which the generator draws no longer (generated part 5468).
                self.graded(seed, REGRESSIONS[seed][1], strict=seed != 1880)

    def test_a_leaning_rim_dipping_to_its_face_built_judged_and_graded(self) -> None:
        """A kept plan graded wrong where a leaning boss's rounded rim dips under its face (6872; tests/v2_regressions.py): the rounding, kept on the face's open side, ends against the face there, a zone in the truth as where roundings meet (fillet.md)."""
        from v2_regressions import REGRESSIONS

        self.graded(6872, REGRESSIONS[6872][1])

    def test_a_block_turned_on_a_tubes_end_built_judged_and_graded(self) -> None:
        """A kept plan the judge's placement stopped on, asking whether a tube's ring of an end face lay over its host, a block turned on it (9126; tests/v2_regressions.py)."""
        from v2_regressions import REGRESSIONS

        self.graded(9126, REGRESSIONS[9126][1])

    def test_the_parts_that_found_faults_on_their_files_judged_there(self) -> None:
        """Kept plans whose STL found faults in the judge (tests/v2_regressions.py), each built, exported at the tolerance its checks ask and judged on the file read back: nothing held. A rounded pocket's length between its corners' edges (950), a shell's wall all but covered where it is measured (2010)."""
        from forge_checks.judge import Judge
        from forge_checks.mesh import Mesh, MeshView
        from forge_checks.readers import read_stl
        from forge_checks.view import ViewProxy
        from forge_cli.build import export_tolerance
        from forge_eval.generator import render
        from forge_occ.export import mesh_part, stl_bytes
        from v2_exit4 import PROBE_SEED, _built, _held, _spec
        from v2_regressions import REGRESSIONS

        for seed in (950, 2010):
            with self.subTest(seed=seed, found=REGRESSIONS[seed][0]):
                spec = _spec(render(REGRESSIONS[seed][1]).items)
                judge = Judge.of(spec)
                _, built = _built(spec)
                tolerance = export_tolerance(judge.suite)
                made = mesh_part(built.result.shape, tolerance)
                read = read_stl(stl_bytes(made.mesh, "part")).triangles
                view = MeshView(Mesh.from_triangles(read), source="mesh-file",
                                deflection=tolerance.linear)  # fmt: skip
                judgement = judge.view(ViewProxy(view), "STL", PROBE_SEED)
                self.assertEqual(_held(judgement), [])

    def test_the_widened_kinds_built_judged_and_graded(self) -> None:
        """The first part of each sort stage 4 widened the generator to draw (tests/test_v2_eval_truth.py's ``WIDENED``)."""
        from test_v2_eval_truth import WIDENED, first_of

        for sort in WIDENED:
            seed = first_of(sort)
            with self.subTest(sort=sort, seed=seed):
                self.graded(seed)


if __name__ == "__main__":
    unittest.main()
