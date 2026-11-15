"""V2 stage 4: the reference parts planned, built and judged (docs/V2-stage4.md, sections 8, 9.2 and 15).

Each of the reference parts' specs (tests/v2_reference.py) is locked,
planned, built through the build loop, and judged as a run judges it: face
accounting both ways, and every check the spec compiles to. Every one must
pass: a compiled part is the spec's part, every face of it accounted for,
every size, place and count measured right.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_plan import LATER, confirmed
from v2_occ import needs_occ
from v2_reference import PARTS


def judged(items: list[dict[str, Any]]) -> tuple[Any, Any, list[str]]:
    """A spec locked, planned, built through the build loop and judged: (the build, the accounting, the checks that didn't pass)."""
    from forge_plan import plan

    spec = confirmed(items)
    return judged_plan(spec.spec, plan(spec))


def judged_plan(spec: Any, found: Any) -> tuple[Any, Any, list[str]]:
    """A plan of a spec, built through the build loop and judged as a run judges it."""
    from forge_checks.accounting import account_faces
    from forge_checks.classes import Verdict
    from forge_checks.compiler import compile_checks
    from forge_checks.measure import Probe
    from forge_checks.oracle import oracle
    from forge_checks.place import place
    from forge_checks.view import ViewProxy
    from forge_occ.planned import build_plan
    from forge_occ.view import BrepView

    built = build_plan(found)
    if built.result is None:
        return built, None, []
    placed = place(spec)
    part = oracle(spec, placed)
    view = ViewProxy(BrepView(built.result.shape))
    accounting = account_faces(part, view, 1.0)
    suite = compile_checks(spec, placed, part)
    probe = Probe(view, part, suite.resolution)
    failed = []
    for check in suite.checks:
        evidence = check.run(probe)
        if evidence.verdict is not Verdict.PASS:
            failed.append(
                f"{check.id}: {evidence.verdict.value}: {evidence.reason[:200]}"
            )
    return built, accounting, failed


@needs_occ
class EveryReferencePartIsItsSpec(unittest.TestCase):
    def test_built_and_judged(self) -> None:
        from forge_checks.classes import Verdict

        for name, make in PARTS.items():
            if name in LATER:
                continue
            items, _ = make()
            with self.subTest(part=name):
                built, accounting, failed = judged(items)
                self.assertIsNone(built.gap, built.refusals)
                self.assertIs(accounting.verdict, Verdict.PASS, accounting.misses[:3])
                self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
