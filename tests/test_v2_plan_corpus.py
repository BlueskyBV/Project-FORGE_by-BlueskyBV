"""V2 stage 4: V1's validation suite, drafted as V2 specs by hand, built and judged (docs/V2-stage4.md, 14.2).

Every brief of validation/SUITE.md is drafted (tests/v2_suite_specs.py) or
says why not. Every draft checks clean, nothing left but its assumptions,
and locks as a draft; the one V1 had to turn back as impossible ends CAN'T at
the spec checks, never built. Each drafted part is then built as ``forge
build`` builds it, with no model call: it ends BUILT TO DRAFT (no person
confirmed it), every check passing on the B-rep, the second kernel and the
STL; and it is the part V1's suite expects, measured independently of
both: its envelope, its volume and its open holes.

What the stage-4 schema can't hold (a load, a mass or size limit) each
draft lists as not modelled, checked from stage 6: never said to pass.

One test per part, so that each runs in its own call where calls are
timed (the laptop's): ``python -m unittest test_v2_plan_corpus.TheSuiteBuilt.test_R01``.
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from forge_spec import number_words
from forge_spec.checks import SpecReport, check_draft
from numpy.typing import NDArray

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_occ import needs_occ
from v2_suite_specs import CANT, DRAFTS, UNDRAFTED, SuitePart, suite

#: How near V1's volume a part's must be: a share of it (V1's are rounded to the cubic millimetre, some measured).
VOLUME_SHARE = 0.001
#: How near V1's envelope a part's must be (mm): the released mesh's, within its tolerance.
ENVELOPE_MM = 0.01
#: The briefs whose limit V1 had to report failing: each draft lists the limit as not modelled, for stage 6.
LIMITS = {"L02": "a strength requirement", "L05": "a mass limit", "X07": "a size limit"}
#: What V1's suite gives no figures for (it expected them turned back), worked out from their briefs: the
#: envelope, the volume (None: a thread's is only bounded) and the open holes.
OWN: dict[str, tuple[tuple[float, float, float], tuple[float, float] | None, int]] = {
    # An M8 hex head 13 mm across its flats and 5.3 mm high (assumed, ISO 4017), on a shank 40 mm long.
    "X03": ((13.0, 13.0 / math.cos(math.pi / 6), 45.3), None, 0),
    # A cone 40 mm across its base and 60 mm tall, to a point.
    "X04": ((40.0, 40.0, 60.0), (math.pi * 20.0**2 * 60.0 / 3,) * 2, 0),
    # A ball 50 mm across.
    "X07": ((50.0, 50.0, 50.0), (4 / 3 * math.pi * 25.0**3,) * 2, 0),
}
#: Where V1's count of open holes (its bores) isn't the surface's genus, which is measured here: the genus, and why.
GENUS = {
    "H07": (
        5,
        "three holes crossing at the centre open six ways from one hollow: one surface of genus 5",
    ),
    "P11": (1, "a doughnut's own hole, which V1 counted as none"),
}


def checked(part: SuitePart, *, strict: bool = False) -> SpecReport:
    b = number_words(part.brief)
    return check_draft(b, DRAFTS[part.id](b), strict=strict)


def _problems(report: SpecReport) -> list[tuple[str, str, str]]:
    return [(p.kind, p.at, p.message) for p in report.problems]


class TheDrafts(unittest.TestCase):
    def test_every_brief_is_drafted_or_says_why_not(self) -> None:
        ids = set(suite())
        self.assertEqual(len(ids), 92)
        self.assertEqual(set(DRAFTS) | set(UNDRAFTED), ids)
        self.assertEqual(set(DRAFTS) & set(UNDRAFTED), set())
        for why in UNDRAFTED.values():
            self.assertGreater(len(why), 20)

    def test_every_draft_checks_clean(self) -> None:
        for id_ in DRAFTS:
            if id_ in CANT:
                continue
            with self.subTest(id=id_):
                report = checked(suite()[id_])
                self.assertEqual(_problems(report), [])

    def test_every_draft_locks_as_a_draft(self) -> None:
        from forge_spec.lock import lock

        for id_ in DRAFTS:
            if id_ in CANT:
                continue
            with self.subTest(id=id_):
                part = suite()[id_]
                confirmed = lock(
                    checked(part), number_words(part.brief), by="draft", strict=False
                )
                self.assertEqual(confirmed.by, "draft")

    def test_the_impossible_ends_cant_never_built(self) -> None:
        from forge_spec.lock import LockError, lock

        for id_, why in CANT.items():
            with self.subTest(id=id_):
                part = suite()[id_]
                report = checked(part)
                self.assertEqual(
                    {p.kind for p in report.problems}, {"cant"}, _problems(report)
                )
                self.assertTrue(
                    any(why in p.message for p in report.problems), _problems(report)
                )
                with self.assertRaises(LockError):
                    lock(report, number_words(part.brief), by="draft", strict=False)

    def test_a_limit_is_listed_for_stage_6_never_passed(self) -> None:
        for id_, what in LIMITS.items():
            with self.subTest(id=id_):
                b = number_words(suite()[id_].brief)
                reasons = [n["reason"] for n in DRAFTS[id_](b)["not_modelled"]]
                self.assertIn(f"{what}: checked from stage 6", reasons)

    def test_under_auto_a_draft_asks_or_locks(self) -> None:
        """--auto's stricter checks find nothing wrong in any draft, only what a person must settle (a word nothing uses, an assumption); one with neither locks."""
        from forge_spec.lock import lock

        clean = set()
        for id_ in DRAFTS:
            if id_ in CANT:
                continue
            with self.subTest(id=id_):
                part = suite()[id_]
                report = checked(part, strict=True)
                self.assertLessEqual(
                    {p.kind for p in report.problems}, {"question"}, _problems(report)
                )
                if not report.problems and not report.assumptions:
                    lock(report, number_words(part.brief), by="draft", strict=True)
                    clean.add(id_)
        # P01, "A 30 mm cube in PLA": its "in" is the material's since 14.4 (a linking word before its words).
        self.assertEqual(
            clean, {"P01", "P02", "P04", "P10", "P13", "C08", "A05", "V06"}
        )


def _holes_and_envelope(
    triangles: NDArray[np.float64],
) -> tuple[int, tuple[float, ...]]:
    """A closed mesh's open holes (each surface's genus, summed: a sealed hollow's inner surface has none) and its sorted envelope."""
    corners = triangles.reshape(-1, 3)
    vertices, index = np.unique(corners, axis=0, return_inverse=True)
    faces = index.reshape(-1, 3)
    # Surfaces: the vertices joined by a triangle's edges, unioned.
    parent = np.arange(len(vertices))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = int(parent[i])
        return i

    for a, b, c in faces:
        for u, v in ((a, b), (b, c)):
            ru, rv = root(int(u)), root(int(v))
            if ru != rv:
                parent[ru] = rv
    roots = np.array([root(i) for i in range(len(vertices))])
    edges = np.unique(np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1),
                      axis=0)  # fmt: skip
    holes = 0
    for surface in np.unique(roots):
        v = int((roots == surface).sum())
        e = int((roots[edges[:, 0]] == surface).sum())
        f = int((roots[faces[:, 0]] == surface).sum())
        euler = v - e + f
        assert euler % 2 == 0, "a closed surface's Euler characteristic is even"
        holes += (2 - euler) // 2
    size = corners.max(axis=0) - corners.min(axis=0)
    return holes, tuple(sorted(float(s) for s in size))


def built(part: SuitePart) -> tuple[int, dict[str, Any], dict[str, Any], bytes]:
    """The part built as ``forge build`` builds it, locked as a draft: the exit code, the verdict, the B-rep's judgement and the released STL."""
    from forge_cli.build import run_build
    from forge_cli.seal import Sealer
    from forge_cli.spec import _write_confirmed
    from forge_spec.lock import lock

    report = checked(part)
    confirmed = lock(report, number_words(part.brief), by="draft", strict=False)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        sealer = Sealer.of_install(root / "home", create=True)
        _write_confirmed(root / "run", confirmed, None)
        said: list[str] = []
        code = run_build(
            root / "run", sealer=sealer, say=said.append, seed=1, formats=("stl",)
        )
        out = root / "run" / "build"
        verdict = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
        judged = json.loads((out / "record" / "judge.json").read_text(encoding="utf-8"))
        brep = next(v for v in judged["views"] if v["view"] == "B-rep")
        stl = next(
            (out / f["name"]).read_bytes()
            for f in verdict["files"]
            if f["name"].endswith(".stl")
        )
    return code, verdict, brep, stl


@needs_occ
class TheSuiteBuilt(unittest.TestCase):
    """One test per drafted part (made below): built, judged, and what V1's suite expects of it."""

    def built_as_expected(self, id_: str) -> None:
        from forge_checks.readers import read_stl

        part = suite()[id_]
        code, verdict, brep, stl = built(part)
        self.assertEqual(
            (code, verdict["ending"]), (0, "BUILT TO DRAFT"), verdict["held"][:3]
        )
        self.assertEqual(verdict["held"], [])
        self.assertEqual(verdict["unchecked"], [])
        holes, envelope = _holes_and_envelope(read_stl(stl).triangles)
        volume = brep["volume"]["built"]
        wanted_envelope, wanted_volume, wanted_holes = OWN.get(
            id_, (part.envelope, part.volume, part.open_holes)
        )
        if wanted_envelope is not None:
            for got, wanted in zip(envelope, sorted(wanted_envelope), strict=True):
                self.assertAlmostEqual(
                    got, wanted, delta=ENVELOPE_MM, msg=f"envelope {envelope}"
                )
        if wanted_volume is not None:
            lo, hi = wanted_volume
            self.assertLessEqual(lo * (1 - VOLUME_SHARE), volume[0], f"volume {volume}")
            self.assertGreaterEqual(
                hi * (1 + VOLUME_SHARE), volume[1], f"volume {volume}"
            )
        if id_ in GENUS:
            self.assertEqual(holes, GENUS[id_][0], GENUS[id_][1])
        elif wanted_holes is not None:
            self.assertEqual(holes, wanted_holes)


def _test(id_: str) -> Callable[[TheSuiteBuilt], None]:
    def test(self: TheSuiteBuilt) -> None:
        self.built_as_expected(id_)

    test.__doc__ = f"{id_}: {suite()[id_].title}"
    return test


for _id in DRAFTS:
    if _id not in CANT:
        setattr(TheSuiteBuilt, f"test_{_id}", _test(_id))


if __name__ == "__main__":
    unittest.main()
