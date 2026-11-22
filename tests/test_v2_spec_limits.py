"""V2, schema 1.11: the brief's limits on the whole part, checked on the built part; and four questions nobody needed
(docs/V2-stage4.md, 14.7).

- **Read and written:** ``requirements.limits``, each a mass or a size along
  an axis, at most and at least so much; below 1.11 a fault, and so is a
  mass in mm, a size in g, a bound with a tolerance, at least more than at
  most, a limit with no bound.
- **Two drafts compared:** a limit one reads and the other doesn't is a
  difference, asked about.
- **Cited as any value:** "no taller than 32 mm and weigh no more than
  30 g" (the corpus's R13) is used whole, and asks nothing; a limit's
  ``of`` cited by words that name another is a fault, by words that name
  none an assumption.
- **Checked on the built part:** a printed PLA plate's mass within the limit
  passes, past it as if solid can't be told (its infill); an aluminium
  one's past it fails; a size past its limit fails, one drawn to it passes;
  no material, or one Forge has no density for, can't be told. A build
  lists its limits, and what the spec leaves out, which nothing checks
  (the corpus's R01: "must weigh no more than 10 g", left out, the part
  released as if every requirement passed).
- **Questions nobody needed,** each still asked where the spec doesn't hold
  it: "fixed at one end by two bolt holes near that end" (R10); a tube
  "open at both ends" (P08); a screw's size its holes are drilled for
  (blind set 1, B1-11); a number in a name the spec repeats (B1-30).
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forge_spec import number_words
from forge_spec.checks import check_draft
from forge_spec.draft import read_draft
from forge_spec.render import render
from forge_spec.wire import to_wire
from v2_drafts import assumed, choose, cite, count, draft, made_of, mm, said
from v2_occ import needs_occ

MOUNT = ("A 3D-printed motor mount plate in PLA, 60 mm long, 40 mm wide and 6 mm thick. The finished part must stand no "
         "taller than 32 mm and weigh no more than 30 g.")  # fmt: skip


def _mount(brief: str = MOUNT, *, material: str = "PLA", height: float = 32, mass: float = 30, version: str = "1.11",
           made: str = "3D-printed", taller: str = "stand no taller", than: str = "no taller than"
           ) -> tuple[Any, dict[str, Any]]:  # fmt: skip
    b = number_words(brief)
    d = draft("motor mount plate", [
        {"id": "plate", "kind": "block", "words": cite(b, "plate"), "length": mm(b, 60, "60 mm long"),
         "width": mm(b, 40, "40 mm wide"), "height": mm(b, 6, "6 mm thick")},
    ], not_modelled=[{"words": cite(b, made), "reason": "how it is made"}],
        material=made_of(b, material))  # fmt: skip
    d["schema_version"] = version
    d["requirements"]["limits"] = [
        {"of": choose("z", said(b, taller)),
         "at_most": mm(b, height, f"{than} {height:g} mm")},
        {"of": choose("mass", said(b, "weigh")),
         "at_most": {"value": mass, "unit": "g", "from": {"words": cite(b, f"no more than {mass:g} g")}}},
    ]  # fmt: skip
    return b, d


def _dims(b: Any, phrase: str) -> dict[str, Any]:
    """A block's three sizes from "100 x 30 x 8 mm", each citing its number and the unit."""
    words = cite(b, phrase)
    numbers, unit = words[0::2], words[-1]
    return {name: {"value": float(b.word(i).text), "unit": "mm", "from": {"words": [i, unit]}}
            for name, i in zip(("length", "width", "height"), numbers, strict=True)}


def _problems(b: Any, d: dict[str, Any]) -> list[tuple[str, str]]:
    return [(p.kind, p.message) for p in check_draft(b, d).problems]


class ReadAndWritten(unittest.TestCase):
    def test_read_written_back_and_shown(self) -> None:
        b, d = _mount()
        report = check_draft(b, d)
        self.assertEqual(report.problems, ())
        self.assertEqual(report.assumptions, ())
        assert report.spec is not None
        wired = to_wire(report.spec)
        self.assertEqual(to_wire(check_draft(b, wired).spec), wired)  # type: ignore[arg-type]
        self.assertEqual([limit["of"]["choose"] for limit in wired["requirements"]["limits"]], ["z", "mass"])
        shown = render(report, b).text()
        self.assertIn("Height (along Z): at most 32 mm, checked on the built part", shown)
        self.assertIn("Mass: at most 30 g, checked on the built part (by the material's density, as if solid)", shown)

    def test_what_is_a_fault(self) -> None:
        _, d = _mount(version="1.10")
        self.assertIn('limits are schema 1.11\'s: give the draft\'s "schema_version": "1.11"',
                      [p.message for p in read_draft(d)[1].faults])  # fmt: skip

        def faults(change: Any) -> list[str]:
            changed = copy.deepcopy(d)
            changed["schema_version"] = "1.11"
            change(changed["requirements"]["limits"])
            return [p.message for p in read_draft(changed)[1].faults]

        def in_mm(limits: list[Any]) -> None:
            limits[1]["at_most"]["unit"] = "mm"

        def in_g(limits: list[Any]) -> None:
            limits[0]["at_most"]["unit"] = "g"

        def toleranced(limits: list[Any]) -> None:
            limits[0]["at_most"]["tolerance"] = {"plus": 0.1, "minus": 0.1}

        def crossed(limits: list[Any]) -> None:
            limits[0]["at_least"] = {**limits[0]["at_most"], "value": 40}

        def unbounded(limits: list[Any]) -> None:
            del limits[0]["at_most"]

        def assumed_bound(limits: list[Any]) -> None:
            limits[0]["at_most"] = assumed("a guess", 30)

        self.assertIn("a limit on the mass is a mass (g, kg), got 'mm'", faults(in_mm))
        self.assertIn("a limit on a size is a length, got 'g'", faults(in_g))
        self.assertIn("a limit is a bound already: it takes no tolerance", faults(toleranced))
        self.assertIn("at least more than at most: no part is both", faults(crossed))
        self.assertIn("a limit says at most or at least how much: give at_most, at_least or both", faults(unbounded))
        self.assertTrue(faults(assumed_bound))  # a limit nobody set is none


class TwoDraftsCompared(unittest.TestCase):
    def test_a_limit_read_otherwise_is_a_difference(self) -> None:
        from forge_spec.compare import differences

        b, d = _mount()
        other = copy.deepcopy(d)
        other["requirements"]["limits"] = other["requirements"]["limits"][1:]
        other["not_modelled"].append({"words": cite(b, "stand no taller than 32 mm"), "reason": "a limit"})
        found = differences(check_draft(b, d), check_draft(b, other))
        self.assertIn(("/requirements/limits", "the limits on the part are mass at most 30 g, z at most 32 mm here, "
                       "mass at most 30 g in the second draft"), [(x.at, x.message) for x in found])  # fmt: skip
        self.assertEqual(differences(check_draft(b, d), check_draft(b, copy.deepcopy(d))), ())


class CitedAsAnyValue(unittest.TestCase):
    def test_every_number_used(self) -> None:
        b, d = _mount()
        self.assertEqual(_problems(b, d), [])

    def test_what_it_holds_against_its_words(self) -> None:
        b, d = _mount()
        d["requirements"]["limits"][0]["of"] = choose("z", said(b, "weigh"))
        self.assertIn(("fault", "the cited words ('weigh') say mass, not z"), _problems(b, d))
        b2, d2 = _mount(MOUNT.replace("stand no taller than", "not exceed"), taller="not exceed", than="not exceed")
        report = check_draft(b2, d2)
        self.assertEqual(report.problems, ())
        self.assertIn("requirements.limits.0.of: z (read from 'not exceed', which doesn't name it)",
                      [a.message for a in report.assumptions])  # fmt: skip


def _judged(b: Any, d: dict[str, Any]) -> list[tuple[str, str]]:
    from forge_checks.judge import Judge
    from forge_checks.view import ViewProxy
    from forge_occ.planned import build_plan
    from forge_occ.view import BrepView
    from forge_plan import plan
    from forge_spec.lock import lock

    report = check_draft(b, d)
    assert not report.problems, report.problems
    confirmed = lock(report, b, by="draft", strict=False)
    built = build_plan(plan(confirmed))
    assert built.result is not None
    judged = Judge.of(confirmed.spec).view(ViewProxy(BrepView(built.result.shape)), "B-rep", 1)
    return [(e.verdict.value, e.reason) for e in judged.limits]


@needs_occ
class CheckedOnTheBuiltPart(unittest.TestCase):
    def test_a_printed_plate(self) -> None:
        # 60 x 40 x 6 mm: 14,400 mm³, 17.4 to 18.1 g of solid PLA, 6 mm tall.
        (height, mass) = _judged(*_mount())
        self.assertEqual(height, ("pass", "its size along z: 6 mm (to within 2e-06 mm), the brief's at most 32 mm"))
        self.assertEqual(mass[0], "pass")
        self.assertIn("solid in PLA (1.21 to 1.26 g/cm³) it weighs 17.42 to 18.14 g; printed, less", mass[1])
        # Past 10 g solid, printed it may be under: its infill decides, which the spec doesn't give.
        brief = MOUNT.replace("30 g", "10 g")
        self.assertEqual(_judged(*_mount(brief, mass=10))[1][0], "inconclusive")

    def test_an_aluminium_plate_past_its_mass_and_sizes_past_and_at_their_limit(self) -> None:
        brief = MOUNT.replace("PLA", "aluminium").replace("3D-printed", "machined")
        verdicts = _judged(*_mount(brief, material="aluminium", made="machined"))
        self.assertEqual(verdicts[1][0], "fail")
        self.assertIn("37.87 to 41.04 g; the brief's at most 30 g", verdicts[1][1])
        self.assertEqual(_judged(*_mount(MOUNT.replace("32 mm", "5 mm"), height=5))[0][0], "fail")
        self.assertEqual(_judged(*_mount(MOUNT.replace("32 mm", "6 mm"), height=6))[0][0], "pass")  # drawn to it

    def test_a_mass_that_cant_be_weighed(self) -> None:
        self.assertEqual(_judged(*_mount(MOUNT.replace("PLA", "PETG-CF"), material="PETG-CF"))[1],
                         ("inconclusive", "its mass: Forge has no density for 'PETG-CF' to weigh it by"))  # fmt: skip
        # No material at all: the brief names none, and the spec weighs it by nothing.
        b, d = _mount(MOUNT.replace(" in PLA", ""), material="plate")
        del d["requirements"]["material"]
        self.assertEqual(_judged(b, d)[1], ("inconclusive", "its mass: the spec names no material to weigh it by"))

    def test_a_build_lists_its_limits_and_what_nothing_checks(self) -> None:
        from forge_cli.build import run_build
        from forge_cli.spec import _write_confirmed
        from forge_spec.lock import lock

        b, d = _mount()
        confirmed = lock(check_draft(b, d), b, by="draft", strict=False)
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / "run"
            _write_confirmed(run, confirmed, None)
            heard: list[str] = []
            out = Path(folder) / "build"
            run_build(run, out=out, sealer=None, say=heard.append, seed=1, formats=("stl",))
            verdict = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
            shown = (out / "verdict.md").read_text(encoding="utf-8")
        self.assertEqual(verdict["ending"], "BUILT TO DRAFT", heard)
        self.assertEqual([limit["verdict"] for limit in verdict["limits"]], ["pass", "pass"])
        self.assertEqual(verdict["not_modelled"], [{"what": "3D-printed", "why": "how it is made"}])
        self.assertIn("## The brief's limits on the part", shown)
        self.assertIn("## Not modelled (the spec leaves these out, so nothing checks them)", shown)
        self.assertIn("  not modelled, so not checked: '3D-printed' (how it is made)", heard)
        # Past its limit, the part is held, on every view: the B-rep and the file made of it.
        b, d = _mount(MOUNT.replace("32 mm", "5 mm"), height=5)
        confirmed = lock(check_draft(b, d), b, by="draft", strict=False)
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / "run"
            _write_confirmed(run, confirmed, None)
            out = Path(folder) / "build"
            run_build(run, out=out, sealer=None, say=lambda _: None, seed=1, formats=("stl",))
            verdict = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["ending"], "HELD")
        self.assertEqual({(h["view"], h["detector"]) for h in verdict["held"]},
                         {("B-rep", "requirements"), ("motor-mount-plate.stl", "requirements")})  # fmt: skip


CANTILEVER = ("An aluminium cantilever bracket: a 60 mm long, 20 mm wide, 6 mm thick bar fixed at one end by two 5 mm "
              "bolt holes 15 mm apart near that end.")  # fmt: skip


def _cantilever(edge: bool = True) -> tuple[Any, dict[str, Any]]:
    b = number_words(CANTILEVER)
    x = ({"side": "-x", "distance": assumed("near that end, clear of the edge", 10), "to": "centre"} if edge
         else {"centred": {"assumed": "the middle"}})  # fmt: skip
    return b, draft("cantilever bracket", [
        {"id": "bar", "kind": "block", "words": cite(b, "bar"), "length": mm(b, 60, "60 mm long"),
         "width": mm(b, 20, "20 mm wide"), "height": mm(b, 6, "6 mm thick")},
        {"id": "holes", "kind": "hole", "words": cite(b, "fixed at one end by two 5 mm bolt holes"),
         "on": {"item": "bar", "face": "+z"}, "diameter": mm(b, 5, "5 mm"),
         "depth": {"through": True, "from": {"assumed": "bolt holes go through"}},
         "place": {"x": x, "y": {"centred": {"assumed": "the middle"}},
                   "pattern": {"row": {"pitch": mm(b, 15, "15 mm apart"), "count": count(b, 2, "two"),
                                       "axis": choose("x", {"assumed": "along the bar"})}}}},
    ], material=made_of(b, "aluminium"))  # fmt: skip


class QuestionsNobodyNeeded(unittest.TestCase):
    def test_one_end_the_holes_are_measured_from(self) -> None:
        b, d = _cantilever()
        self.assertEqual(_problems(b, d), [])
        b, d = _cantilever(edge=False)  # placed from no end: which end is "one"?
        self.assertIn(("question", "the brief says 'one' (sentence 1); nothing in the spec uses it"), _problems(b, d))

    def test_a_tube_open_at_both_ends(self) -> None:
        text = "An aluminium tube with a 30 mm outside diameter and a 24 mm inside diameter, 80 mm long, open at both ends."
        b = number_words(text)
        tube = {"id": "tube", "kind": "tube", "words": cite(b, "tube") + cite(b, "open at both ends"),
                "outer_diameter": mm(b, 30, "30 mm outside diameter"), "inner_diameter": mm(b, 24, "24 mm inside diameter"),
                "length": mm(b, 80, "80 mm long"), "axis": choose("x", {"assumed": "lying down"})}  # fmt: skip
        self.assertEqual(_problems(b, draft("tube", [tube], material=made_of(b, "aluminium"))), [])
        # A rod has no bore to open its ends: "both" is still asked about where nothing holds it.
        rod_text = "An aluminium rod 12 mm across and 80 mm long, open at both ends."
        rb = number_words(rod_text)
        rod = {"id": "rod", "kind": "cylinder", "words": cite(rb, "rod") + cite(rb, "open at both ends"),
               "diameter": mm(rb, 12, "12 mm across"), "length": mm(rb, 80, "80 mm long"),
               "axis": choose("x", {"assumed": "lying down"})}  # fmt: skip
        self.assertIn(("question", "the brief says 'both' (sentence 1); nothing in the spec uses it"),
                      _problems(rb, draft("rod", [rod], material=made_of(rb, "aluminium"))))  # fmt: skip

    def test_the_screw_a_hole_is_drilled_for(self) -> None:
        def bar(hole: float) -> tuple[Any, dict[str, Any]]:
            text = (f"A 100 x 30 x 8 mm aluminium bar with three holes for M5 screws along its middle, 20 mm apart, "
                    f"each {hole:g} mm across.")  # fmt: skip
            b = number_words(text)
            return b, draft("bar", [
                {"id": "bar", "kind": "block", "words": cite(b, "bar"), **_dims(b, "100 x 30 x 8 mm")},
                {"id": "holes", "kind": "hole", "words": cite(b, "three holes for M5 screws"),
                 "on": {"item": "bar", "face": "+z"}, "diameter": mm(b, hole, f"{hole:g} mm across"),
                 "depth": {"through": True, "from": {"assumed": "screw holes go through"}},
                 "place": {"x": {"centred": {"assumed": "the middle"}}, "y": {"centred": said(b, "along its middle")},
                           "pattern": {"row": {"pitch": mm(b, 20, "20 mm apart"), "count": count(b, 3, "three"),
                                               "axis": choose("x", {"assumed": "along the bar"})}}}},
            ], material=made_of(b, "aluminium"))  # fmt: skip

        for clearance in (5.3, 5.5, 5.8, 4.2):  # ISO 273 fine, normal, coarse; the tap drill
            with self.subTest(clearance=clearance):
                self.assertNotIn("M5", " ".join(m for _, m in _problems(*bar(clearance))))
        # A hole no M5 has: the brief's size and its screw disagree, and it is asked.
        self.assertIn(("question", "the brief says 'M5' (sentence 1); nothing in the spec uses it"), _problems(*bar(4.5)))

    def test_a_number_in_a_name_the_spec_repeats(self) -> None:
        def plate(name: str, text: str = "A Raspberry Pi 4 mounting plate, 100 x 75 x 3 mm.") -> list[tuple[str, str]]:
            b = number_words(text)
            return _problems(b, draft(name, [
                {"id": "plate", "kind": "block", "words": cite(b, "plate"), **_dims(b, "100 x 75 x 3 mm")},
            ], not_modelled=[{"words": cite(b, "Raspberry Pi"), "reason": "the board it carries"}] if "Pi" in text
                else []))  # fmt: skip

        self.assertEqual(plate("Raspberry Pi 4 mounting plate"), [])
        self.assertIn(("question", "the brief says '4' (sentence 1); nothing in the spec uses it"),
                      plate("Raspberry Pi mounting plate"))  # fmt: skip
        # A count after a lowercase word is no name's: "a plate with 4 holes", named so, still asks.
        self.assertIn(("question", "the brief says '4' (sentence 1); nothing in the spec uses it"),
                      plate("plate with 4 holes", "A plate with 4 holes, 100 x 75 x 3 mm."))  # fmt: skip


if __name__ == "__main__":
    unittest.main()
