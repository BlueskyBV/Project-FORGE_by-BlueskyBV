"""V2 stage 3's exit test: the hybrid kernel on everything Forge has (docs/V2-stage3.md, section 16).

1. **Both kernels.** Every V1 golden and zoo shape (the golden clevis and the
   34 zoo documents), then every other recorded document: converted to v2,
   built exactly by OpenCascade (every step after-checked), built again by
   V1's implicit kernel, and held to each other by the agreement test
   (13.4). Every not-applicable zone and every tolerance used is written to
   the report, ``runs/stage3_step/report.json``.
2. **STEP.** Each part built is exported, re-opened by OpenCascade (names,
   solids, volume, area, centre and box as built) and by FreeCAD where it
   can be run (valid, as many solids as built, volume and box as built). The
   files are written to ``runs/stage3_step/`` to be opened in Fusion.
3. **An assembly with mates.** The clevis and its pin, a coaxial mate and a
   contact mate: the document round-trips through JSON unchanged, is built,
   both mates hold, it is exported as one STEP assembly and re-opened, both
   parts, their names and placements come back and both mates hold on the
   geometry read back; FreeCAD opens it with both parts in place.
4. The traps of section 4 are tests/test_v2_occ_ops.py's.

One recorded design the exact kernel refuses, and must keep refusing until
it can build it truly: ``leg_shell_thinnest_wall_at_its_webs_claude``, an
8 mm shell inside four stacked lofts. OpenCascade can't offset the stack by
its joins (``BRepOffset_MixedConnectivity``: its faces meet partly tangent
along the lofts' joints), and its simple offset comes out 6.13 mm from the
surface at a corner, so the wall check refuses the step: a wrong part is
never handed on as V1's.
"""

from __future__ import annotations

import json
import time
import unittest
from typing import Any

import v2_freecad
from v2_occ import CLEVIS_PIN, ROOT, converted, corpus, needs_occ, v2, zoo

try:
    from forge_occ.agreement import agree
    from forge_occ.assembly import build_assembly, check_mates_read_back
    from forge_occ.backend import OccBackend
    from forge_occ.errors import AfterCheckError
    from forge_occ.export import StepPart, check_step, write_step
    from forge_occ.measure import properties
except ImportError:  # no OpenCascade here: every class below is skipped
    pass

OUT = ROOT / "runs" / "stage3_step"
#: The recorded designs the exact kernel refuses, and what its refusal must say.
REFUSED = {
    "leg_shell_thinnest_wall_at_its_webs_claude": "a shell's wall is 8 mm from the part's surface"
}
#: How closely FreeCAD's volume must match the part's (relative). FreeCAD integrates at OpenCascade's
#: default precision, which was found up to 2.4e-5 off the exact volume (a collar's bores; ours at that
#: precision is off alike) and differs between OpenCascade's versions: a misread part is off by far more.
FREECAD_VOLUME = 1e-4
#: How closely FreeCAD's box must match the part's (relative to its size).
FREECAD_BOX = 1e-6

_REPORT: dict[str, Any] = {}


def _write_report() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(_REPORT, indent=2, sort_keys=True, default=str) + "\n",
                                     encoding="utf-8")  # fmt: skip


def _freecad_agrees(
    case: unittest.TestCase, data: bytes, shape: Any, solids: int
) -> dict[str, Any] | None:
    if v2_freecad.missing() is not None:
        return None
    found = v2_freecad.opened(data)
    exact = properties(shape)
    case.assertTrue(found["valid"], "FreeCAD finds the part invalid")
    case.assertEqual(found["solids"], solids)
    case.assertAlmostEqual(
        found["volume"], exact.volume, delta=FREECAD_VOLUME * abs(exact.volume)
    )
    size = max(b - a for a, b in zip(exact.lo, exact.hi, strict=True))
    for k in range(3):
        case.assertAlmostEqual(
            found["bounds"][k], exact.lo[k], delta=FREECAD_BOX * size + 1e-9
        )
        case.assertAlmostEqual(
            found["bounds"][k + 3], exact.hi[k], delta=FREECAD_BOX * size + 1e-9
        )
    return found


@needs_occ
class BothKernelsAgreeAndEveryPartReopens(unittest.TestCase):
    """Items 1 and 2: built both ways, agreeing, exported and re-opened."""

    @classmethod
    def tearDownClass(cls) -> None:
        _write_report()

    def check(self, name: str, text: str) -> None:
        document = converted(text)
        for component in document.components:
            started = time.perf_counter()
            if name in REFUSED:
                with self.assertRaises(AfterCheckError) as caught:
                    OccBackend().build(document, component.identifier)
                self.assertIn(REFUSED[name], caught.exception.message)
                _REPORT[name] = {"refused": str(caught.exception)}
                continue
            exact = OccBackend().build(document, component.identifier)
            report = agree(document, component.identifier, exact=exact)
            self.assertTrue(
                report.holds, json.dumps(report.as_dict(), default=str)[:3000]
            )
            part = (
                f"{name}.{component.identifier}"
                if len(document.components) > 1
                else name
            )
            data = write_step([StepPart(part, exact.shape)])
            _, reopened = check_step(data, [StepPart(part, exact.shape)])
            freecad = _freecad_agrees(self, data, exact.shape, exact.solids)
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f"{part}.step").write_bytes(data)
            _REPORT[part] = {
                "agreement": report.as_dict(), "seconds": round(time.perf_counter() - started, 1),
                "tolerances": {t.step: t.tolerance for t in exact.traces if t.tolerance},
                "step_read_back": reopened.parts[part], "freecad": freecad,
            }  # fmt: skip

    def test_the_golden_clevis_and_the_zoo(self) -> None:
        shapes = zoo()
        self.assertEqual(len(shapes), 35)
        for name, text in sorted(shapes.items()):
            with self.subTest(name):
                self.check(name, text)

    def test_every_other_recorded_document(self) -> None:
        shapes = zoo()
        rest = {name: text for name, text in corpus().items() if name not in shapes}
        self.assertGreaterEqual(len(rest) + len(shapes), 149)
        for name, text in sorted(rest.items()):
            with self.subTest(name):
                self.check(name, text)


@needs_occ
class TheClevisAndItsPin(unittest.TestCase):
    """Item 3: a two-part document with a coaxial and a contact mate."""

    def test_round_tripped_built_exported_and_reopened_with_its_mates(self) -> None:
        text = CLEVIS_PIN.read_text(encoding="utf-8")
        document = v2(text)
        self.assertEqual(json.loads(document.to_json()), json.loads(text))
        assembly = build_assembly(document)
        self.assertEqual(
            [(m.mate, m.holds) for m in assembly.mates],
            [("pin_in_bore", True), ("head_on_ear", True)],
        )
        data = write_step(
            assembly.step_parts(), assembly.step_instances(), assembly=assembly.name
        )
        found, report = check_step(
            data,
            assembly.step_parts(),
            assembly.step_instances(),
            assembly=assembly.name,
        )
        self.assertEqual(sorted(found.parts), ["clevis", "pin"])
        self.assertEqual([i.name for i in found.instances], ["clevis_1", "pin_1"])
        self.assertEqual(report.instances, 2)
        self.assertTrue(
            all(m.holds for m in check_mates_read_back(document, assembly, found))
        )
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "clevis_pin.step").write_bytes(data)
        if v2_freecad.missing() is None:
            objects = {o["label"]: o for o in v2_freecad.inserted(data)}
            for part in ("clevis", "pin"):
                self.assertIn(part, objects)
                self.assertTrue(objects[part]["valid"])
                self.assertEqual(objects[part]["solids"], 1)
            placed = {i.id: i for i in assembly.instances}
            pin = properties(placed["pin_1"].motion.apply(assembly.parts["pin"].shape))
            for k in range(3):
                self.assertAlmostEqual(
                    objects["pin"]["bounds"][k], pin.lo[k], delta=1e-3
                )
                self.assertAlmostEqual(
                    objects["pin"]["bounds"][k + 3], pin.hi[k], delta=1e-3
                )

    @unittest.skipIf(v2_freecad.missing() is not None, v2_freecad.missing() or "")
    def test_freecad_is_a_second_reader_here(self) -> None:
        # Where FreeCAD can run, the exit test uses it: this says so in the run's results.
        self.assertIsNone(v2_freecad.missing())


if __name__ == "__main__":
    unittest.main()
