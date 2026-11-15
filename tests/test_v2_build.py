"""V2 stage 4: ``forge build`` end to end (docs/V2-stage4.md, section 9).

A confirmed spec to a judged part and its files, with no model call: the
confirmed spec read and refused; the seal on a person's confirmation; the
build's own folder; the files' names and the meshes' tolerance; and each
ending with its exit code, its verdict, its record and the files it
releases or keeps: VERIFIED, VERIFIED EXCEPT, BUILT TO DRAFT, HELD (by a
check, and before building), CAN'T, UNABLE, and Forge's own error.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forge_cli.build import (
    EXIT_CANT,
    EXIT_ERROR,
    EXIT_HELD,
    EXIT_RELEASED,
    EXIT_UNABLE,
    RefusedError,
    build_folder,
    export_tolerance,
    file_stem,
    read_confirmed,
    run_build,
)
from forge_cli.cli import build_parser
from forge_cli.seal import KEY_FILE, Sealer, SealError
from forge_cli.spec import _write_confirmed
from forge_spec.checks import check_draft
from forge_spec.lock import lock
from test_v2_plan import BRIEF
from v2_occ import needs_occ
from v2_reference import item, on, through
from v2_specs import SAY, a, draft, n, pick

#: A plate with a hole through it: built, judged and exported in seconds.
PLATE = [
    item("plate", "block", length=a(40), width=a(30), height=a(5)),
    item("h", "hole", on=on("plate", "+z"), diameter=a(6), depth=through()),
]
#: The same plate with its hole 7 mm across: a wrong part for PLATE's spec.
WIDER = [
    PLATE[0],
    item("h", "hole", on=on("plate", "+z"), diameter=a(7), depth=through()),
]
#: Three holes in a row, written as a grid one copy deep: its pitch across the row is no check's to hold.
ROW = [PLATE[0], item("h", "hole", on=on("plate", "+z"), diameter=a(4), depth=through(), place={"pattern": {
    "grid": {"pitch_x": a(12), "pitch_y": a(10), "count_x": n(3), "count_y": n(1)}}})]  # fmt: skip


def locked(items: list[dict[str, Any]], by: str = "person") -> Any:
    report = check_draft(BRIEF, draft(items), strict=False)
    return lock(report, BRIEF, by=by, strict=False)  # type: ignore[arg-type]


class Folder(unittest.TestCase):
    """A temporary folder for each test: a run's folder, and this installation's Forge folder (its key)."""

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.root = Path(self._folder.name)
        sealer = Sealer.of_install(self.root / "home", create=True)
        assert sealer is not None
        self.sealer: Sealer = sealer
        self.said: list[str] = []

    def tearDown(self) -> None:
        self._folder.cleanup()

    def run_folder(self, items: list[dict[str, Any]], *, by: str = "person", sealed: bool = True,
                   name: str = "run") -> Path:  # fmt: skip
        confirmed = locked(items, by)
        folder = self.root / name
        seal = self.sealer.seal(confirmed.digest) if sealed and by == "person" else None
        _write_confirmed(folder, confirmed, seal)
        return folder

    def build(
        self, folder: Path, **options: Any
    ) -> tuple[int, dict[str, Any] | None, Path]:
        code = run_build(
            folder, sealer=self.sealer, say=self.said.append, seed=11, **options
        )
        built = sorted(p for p in folder.iterdir() if p.name.startswith("build"))
        out = options.get("out") or (built[-1] if built else folder / "build")
        path = out / "verdict.json"
        verdict = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        )
        return code, verdict, out


class TheSeal(unittest.TestCase):
    def test_made_once_read_back_and_held(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            self.assertIsNone(Sealer.of_install(home, create=False))
            made = Sealer.of_install(home, create=True)
            again = Sealer.of_install(home, create=False)
            assert made is not None and again is not None
            self.assertEqual(made.key, again.key)
            seal = made.seal("a" * 64)
            self.assertTrue(again.holds("a" * 64, seal))
            self.assertFalse(again.holds("b" * 64, seal))
            self.assertFalse(
                again.holds("a" * 64, seal[:-1] + ("0" if seal[-1] != "0" else "1"))
            )
            self.assertFalse(again.holds("a" * 64, None))
            other = Sealer(bytes(32))
            self.assertFalse(other.holds("a" * 64, seal))
            self.assertNotIn(made.key.hex(), repr(made))
            if os.name == "posix":
                self.assertEqual((home / KEY_FILE).stat().st_mode & 0o777, 0o600)

    def test_a_key_that_isn_t_one_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / KEY_FILE).write_text("not a key", encoding="ascii")
            with self.assertRaises(SealError):
                Sealer.of_install(Path(folder), create=False)
            with self.assertRaises(SealError):
                Sealer(b"short")


class TheConfirmedSpec(Folder):
    def test_a_person_s_sealed_confirmation(self) -> None:
        found = read_confirmed(self.run_folder(PLATE), self.sealer)
        self.assertTrue(found.by_person)
        self.assertEqual(found.why_draft, "")

    def test_without_a_seal_or_with_another_s_it_builds_as_a_draft(self) -> None:
        unsealed = read_confirmed(self.run_folder(PLATE, sealed=False), self.sealer)
        self.assertFalse(unsealed.by_person)
        self.assertIn("no seal", unsealed.why_draft)
        elsewhere = read_confirmed(
            self.run_folder(PLATE, name="other"), Sealer(bytes(32))
        )
        self.assertFalse(elsewhere.by_person)
        self.assertIn("isn't this installation's", elsewhere.why_draft)
        nokey = read_confirmed(self.run_folder(PLATE, name="third"), None)
        self.assertFalse(nokey.by_person)

    def test_a_draft(self) -> None:
        found = read_confirmed(self.run_folder(PLATE, by="draft"), self.sealer)
        self.assertFalse(found.by_person)
        self.assertIn("locked as a draft", found.why_draft)

    def test_a_person_written_in_by_hand_is_no_person(self) -> None:
        # "by" changed to person and the digest hashed again: the seal can't be made without the key.
        folder = self.run_folder(PLATE, by="draft")
        record = json.loads((folder / "confirmed.json").read_text(encoding="utf-8"))
        from forge_spec import number_words
        from forge_spec.lock import spec_digest, unlock

        spec = unlock(
            record["spec"],
            number_words(record["brief"]),
            record["digest"],
            by="draft",
            strict=record["strict"],
        )
        record.update(by="person", strict=False, seal="0" * 64,
                      digest=spec_digest(spec.spec, number_words(record["brief"]), "person", strict=False))  # fmt: skip
        (folder / "confirmed.json").write_text(json.dumps(record), encoding="utf-8")
        found = read_confirmed(folder, self.sealer)
        self.assertFalse(found.by_person)

    def test_one_changed_or_unreadable_is_refused(self) -> None:
        folder = self.run_folder(PLATE)
        path = folder / "confirmed.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["spec"]["items"][1]["diameter"]["value"] = 7
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(RefusedError, "changed"):
            read_confirmed(folder, self.sealer)
        for text in ("{", "[]", json.dumps({**record, "digest": 3})):
            path.write_text(text, encoding="utf-8")
            with self.subTest(text=text[:20]), self.assertRaises(RefusedError):
                read_confirmed(folder, self.sealer)
        with self.assertRaises(RefusedError):
            read_confirmed(self.root / "nowhere", self.sealer)

    def test_refused_nothing_is_written(self) -> None:
        folder = self.run_folder(PLATE)
        (folder / "confirmed.json").write_text("{}", encoding="utf-8")
        code = run_build(folder, sealer=self.sealer, say=self.said.append)
        self.assertEqual(code, EXIT_ERROR)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["confirmed.json"])
        self.assertTrue(any(line.startswith("Refused") for line in self.said))


class TheBuildsFolder(Folder):
    def test_a_fresh_one_each_build(self) -> None:
        run = self.root / "run"
        run.mkdir()
        self.assertEqual(build_folder(run, None).name, "build")
        self.assertEqual(build_folder(run, None).name, "build-2")
        self.assertEqual(build_folder(run, None).name, "build-3")

    def test_out_new_or_empty_only(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        self.assertEqual(build_folder(self.root, empty), empty)
        self.assertEqual(
            build_folder(self.root, self.root / "new" / "deep"),
            self.root / "new" / "deep",
        )
        (empty / "mine.step").write_text("yours", encoding="utf-8")
        with self.assertRaisesRegex(RefusedError, "new or empty"):
            build_folder(self.root, empty)
        with self.assertRaises(RefusedError):
            build_folder(self.root, empty / "mine.step")


class FilesNamesAndTolerances(unittest.TestCase):
    def test_a_file_s_name(self) -> None:
        cases = {
            "L-bracket, Rev. 2": "l-bracket-rev-2",
            "../../etc/passwd": "etc-passwd",
            "Ünïcode plate": "n-code-plate",
            "con": "part",
            "COM1": "part",
            "   ": "part",
            "x" * 100: "x" * 64,
            "a" * 63 + "-b": "a" * 63,
        }
        for name, stem in cases.items():
            with self.subTest(name=name):
                self.assertEqual(file_stem(name), stem)

    def test_the_meshes_tolerance(self) -> None:
        from forge_checks.classes import Tolerance

        def suite(*checks: tuple[str, float | None]) -> Any:
            return SimpleNamespace(checks=[SimpleNamespace(kind=k, tolerance=None if t is None else Tolerance(t, t),
                                                           target=None) for k, t in checks])  # fmt: skip

        self.assertEqual(export_tolerance(suite()).linear, 0.01)
        self.assertEqual(export_tolerance(suite(("size", 0.3))).linear, 0.01)
        self.assertAlmostEqual(
            export_tolerance(suite(("size", 0.3), ("diameter", 0.1))).linear, 0.005
        )
        # An angle's tolerance, in degrees, is no size; a count holds none.
        self.assertEqual(
            export_tolerance(suite(("angle", 0.01), ("count", None))).linear, 0.01
        )
        self.assertEqual(export_tolerance(suite(("size", 0.003))).linear, 0.0005)
        self.assertEqual(export_tolerance(suite()).angular, 0.1)
        # A cone's angle as fine as its fit on the mesh's points needs: finer for a shorter cone.
        from forge_checks.kinds.angle import mesh_deflection
        from forge_checks.kinds.surfaces import Cone

        def countersink(depth: float) -> Any:
            cone = Cone(
                (0.0, 0.0, 5.0),
                (0.0, 0.0, -1.0),
                (3.0 + depth, 3.0),
                (0.0, depth),
                True,
            )
            return SimpleNamespace(kind="angle", tolerance=Tolerance(1.0, 1.0), target=cone)  # fmt: skip

        short, long = (
            mesh_deflection(countersink(0.5).target, Tolerance(1.0, 1.0)),
            mesh_deflection(countersink(2.0).target, Tolerance(1.0, 1.0)),
        )
        self.assertLess(short, long)
        # Asked round the cone alone (docs/V2-stage4.md, 13.10): its box grown by a millimetre.
        found = export_tolerance(SimpleNamespace(checks=[countersink(2.0)]))
        self.assertEqual(found.linear, 0.01)
        ((box, need),) = found.finer
        self.assertAlmostEqual(need, max(min(long, 0.01), 0.0005))
        self.assertEqual((box.lo, box.hi), ((-6.0, -6.0, 2.0), (6.0, 6.0, 6.0)))
        # A size between two faces asks everywhere; a finer one asked round a cone's own surface is moot there.
        both = export_tolerance(
            SimpleNamespace(checks=[countersink(2.0), *suite(("size", 0.003)).checks])
        )
        self.assertEqual((both.linear, both.finer), (0.0005, ()))
        # A cone with no length along its axis asks nothing of a mesh.
        flat = Cone((0.0, 0.0, 5.0), (0.0, 0.0, -1.0), (3.0, 4.0), (1.0, 1.0), True)
        self.assertEqual(mesh_deflection(flat, Tolerance(1.0, 1.0)), math.inf)


class TheCommand(unittest.TestCase):
    def test_wired(self) -> None:
        args = build_parser().parse_args(
            ["build", "runs/x", "--formats", "stl, STEP", "--seed", "4"]
        )
        self.assertEqual((args.handler.__name__, args.source, args.formats, args.seed),
                         ("command_build", "runs/x", ("step", "stl"), 4))  # fmt: skip
        self.assertEqual(
            build_parser().parse_args(["build", "x"]).formats, ("step", "stl", "3mf")
        )
        for bad in ("obj", "", "stl,obj"):
            with (
                self.subTest(bad=bad),
                self.assertRaises(SystemExit),
                mock.patch("sys.stderr"),
            ):
                build_parser().parse_args(["build", "x", "--formats", bad])


@needs_occ
class TheEndings(Folder):
    def test_verified(self) -> None:
        code, verdict, out = self.build(self.run_folder(PLATE))
        assert verdict is not None
        self.assertEqual(
            (code, verdict["ending"], verdict["exit"]), (EXIT_RELEASED, "VERIFIED", 0)
        )
        self.assertEqual(verdict["held"], [])
        self.assertEqual(verdict["unchecked"], [])
        self.assertEqual(verdict["probe_seed"], 11)
        self.assertTrue(verdict["spec"]["sealed"])
        self.assertEqual({i["item"] for i in verdict["items"]}, {"plate", "h"})
        views = {"B-rep", "random.step", "random.stl", "random.3mf"}
        for entry in verdict["items"]:
            self.assertEqual(entry["views"], dict.fromkeys(views, True))
            self.assertEqual(entry["class"], "exact")
        self.assertAlmostEqual(verdict["surface"]["exact"], 1.0)
        for f in verdict["files"]:
            data = (out / f["name"]).read_bytes()
            self.assertTrue(f["released"])
            self.assertEqual(
                (len(data), hashlib.sha256(data).hexdigest()), (f["bytes"], f["sha256"])
            )
        self.assertEqual(
            sorted(f["name"] for f in verdict["files"]),
            ["random.3mf", "random.step", "random.stl"],
        )
        for name in ("document.json", "build.json", "judge.json"):
            self.assertTrue((out / "record" / name).is_file(), name)
        self.assertFalse((out / "record" / "files").exists())
        written = (out / "verdict.md").read_text(encoding="utf-8")
        self.assertIn("# VERIFIED: random", written)
        # Each item on each view passed, in those words: HELD is an ending, not an item's.
        self.assertIn(
            "| plate | block | exact | passed | passed | passed | passed |", written
        )
        judged = json.loads((out / "record" / "judge.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [v["view"] for v in judged["views"]],
            ["B-rep", "random.step", "random.stl", "random.3mf"],
        )
        self.assertTrue(judged["agreement"]["holds"])
        # Each build gets a folder of its own; a second leaves the first as it was.
        again, second, out2 = self.build(
            self.run_folder(PLATE, name="run"), formats=("stl",)
        )
        self.assertEqual((again, out2.name), (EXIT_RELEASED, "build-2"))
        assert second is not None
        self.assertEqual([f["name"] for f in second["files"]], ["random.stl"])

    def test_a_countersink_verified_on_its_meshes(self) -> None:
        """Its 90 degrees measured on the STL fine enough to judge (the exit test's pilot held parts 20 and 40 on theirs)."""
        sunk = [PLATE[0], item("h", "hole", on=on("plate", "+z"), diameter=a(3.714), depth=through(),
                               countersink={"diameter": a(5.671), "angle": a(90, "deg")})]  # fmt: skip
        code, verdict, _ = self.build(self.run_folder(sunk), formats=("stl",))
        assert verdict is not None
        self.assertEqual(
            (code, verdict["ending"], verdict["held"]), (EXIT_RELEASED, "VERIFIED", [])
        )

    def test_a_chamfer_round_a_cylinder_s_far_end_verified_on_its_meshes(self) -> None:
        """Its size measured on the STL about its own corner, fine enough to judge (the exit test held part 140 on its meshes: the cone fitted about the cylinder's other end, ±2 mm)."""
        chamfered = [item("body", "cylinder", diameter=a(35.701), length=a(20.675), axis=pick("z")),
                     item("round_body", "chamfer", edges={"of": "body", "which": "both"}, size=a(0.969))]  # fmt: skip
        code, verdict, _ = self.build(self.run_folder(chamfered), formats=("stl",))
        assert verdict is not None
        self.assertEqual(
            (code, verdict["ending"], verdict["held"]), (EXIT_RELEASED, "VERIFIED", [])
        )

    def test_verified_except(self) -> None:
        code, verdict, _ = self.build(self.run_folder(ROW), formats=("stl",))
        assert verdict is not None
        self.assertEqual((code, verdict["ending"]), (EXIT_RELEASED, "VERIFIED EXCEPT"))
        self.assertEqual([(u["item"], u["field"]) for u in verdict["unchecked"]],
                         [("h", "place.pattern.grid.pitch_y")])  # fmt: skip
        self.assertTrue(
            any("unchecked: h.place.pattern.grid.pitch_y" in line for line in self.said)
        )

    def test_built_to_draft(self) -> None:
        code, verdict, _ = self.build(
            self.run_folder(PLATE, by="draft"), formats=("stl",)
        )
        assert verdict is not None
        self.assertEqual((code, verdict["ending"]), (EXIT_RELEASED, "BUILT TO DRAFT"))
        self.assertIn("locked as a draft", verdict["spec"]["why_draft"])
        unsealed, verdict2, _ = self.build(
            self.run_folder(PLATE, sealed=False, name="other"), formats=("stl",)
        )
        assert verdict2 is not None
        self.assertEqual(
            (unsealed, verdict2["ending"]), (EXIT_RELEASED, "BUILT TO DRAFT")
        )

    def test_held_by_a_check(self) -> None:
        from forge_plan import plan

        def wrong(_: Any) -> Any:
            return plan(locked(WIDER))

        with mock.patch("forge_plan.plan", side_effect=wrong):
            code, verdict, out = self.build(self.run_folder(PLATE), formats=("stl",))
        assert verdict is not None
        self.assertEqual((code, verdict["ending"]), (EXIT_HELD, "HELD"))
        held = {(h["view"], h["what"]) for h in verdict["held"]}
        self.assertIn(("B-rep", "h/diameter/0"), held)
        self.assertIn(("random.stl", "h/diameter/0"), held)
        self.assertTrue(
            any(h["detector"] == "face accounting" for h in verdict["held"])
        )
        # Kept to look at, never released.
        self.assertFalse((out / "random.stl").exists())
        self.assertTrue((out / "record" / "files" / "random.stl").is_file())
        self.assertEqual([f["released"] for f in verdict["files"]], [False])
        self.assertTrue(any("HELD" in line for line in self.said))

    def test_held_and_can_t_before_building(self) -> None:
        from forge_checks.oracle import CannotMakeError, OracleError

        cases = (
            (CannotMakeError("r: none of its edges is left"), EXIT_CANT, "CAN'T"),
            (OracleError("no shape for it"), EXIT_HELD, "HELD"),
        )
        for k, (error, exit_code, ending) in enumerate(cases):
            with (
                self.subTest(ending=ending),
                mock.patch("forge_checks.judge.Judge.of", side_effect=error),
            ):
                code, verdict, out = self.build(self.run_folder(PLATE, name=f"run{k}"))
            assert verdict is not None
            self.assertEqual((code, verdict["ending"]), (exit_code, ending))
            self.assertEqual(verdict["files"], [])
            self.assertFalse((out / "record" / "build.json").exists())
            said = verdict["cant"] if ending == "CAN'T" else verdict["held"][0]["why"]
            self.assertIn(str(error), said)

    def test_unable_for_a_gap(self) -> None:
        # A region is designed later, by the construction agent: a gap, and the run ends UNABLE for it (4.9).
        region = item("grip", "region", on=on("plate", "-z"), length=a(20), width=a(20), height=a(3),
                      describe={"text": "a grip", "from": SAY}, place={"x": {"offset": a(10)}})  # fmt: skip
        code, verdict, out = self.build(self.run_folder([PLATE[0], region]))
        assert verdict is not None
        self.assertEqual((code, verdict["ending"]), (EXIT_UNABLE, "UNABLE"))
        self.assertEqual(verdict["gap"]["item"], "grip")
        self.assertIn("designed later", verdict["gap"]["why"])
        built = json.loads((out / "record" / "build.json").read_text(encoding="utf-8"))
        self.assertEqual(built["gap"]["item"], "grip")
        self.assertEqual(verdict["files"], [])

    def test_forge_s_own_error(self) -> None:
        with mock.patch(
            "forge_occ.planned.build_plan",
            side_effect=RuntimeError("a fault of Forge's"),
        ):
            code, verdict, out = self.build(self.run_folder(PLATE))
        self.assertEqual((code, verdict), (EXIT_ERROR, None))
        error = json.loads((out / "record" / "error.json").read_text(encoding="utf-8"))
        self.assertEqual(
            (error["error"], error["message"]), ("RuntimeError", "a fault of Forge's")
        )


if __name__ == "__main__":
    unittest.main()
