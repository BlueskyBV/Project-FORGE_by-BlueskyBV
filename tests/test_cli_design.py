"""The ``forge design`` command, end to end, offline.

Everything below runs the real CLI entry point -- argument parsing, provider
construction, the orchestrator, the compiler, the verifier, artefact writing and
the exit code -- against a fixture library recorded from the hand-written
responses. No network, no key, no wall-clock dependence.

What these tests are actually protecting is the part of the system a user meets
first. A loop that works when driven from Python and falls over when driven from
a shell is not a working loop, and the failures that hide there are unglamorous:
an exit code that says success when a run stopped to ask a question, a run whose
artefacts are written only on the happy path, a key that leaks into a report.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fixtures.bracket_responses import (
    BRIEF,
    BRIEF_UNDERSPECIFIED,
    INTERPRETER,
    QUESTIONS,
    REQUIREMENTS_UNDERSPECIFIED,
)
from fixtures.library import build_library
from forge_cli import main
from forge_cli.design import EXIT_QUESTIONS


#: The clarification path: interpret, gather, then ask rather than design.
_ASKING_SCRIPT = (INTERPRETER, REQUIREMENTS_UNDERSPECIFIED, QUESTIONS)


class _Case(unittest.TestCase):
    """A recorded library, built once for the whole module."""

    library: Path
    _temporary: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        root = Path(cls._temporary.name)
        cls.library = build_library(root / "fixtures")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def run_cli(self, *argv: str) -> tuple[int, str, Path]:
        out = Path(tempfile.mkdtemp(dir=self._temporary.name))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(
                [
                    "design",
                    BRIEF,
                    "--provider",
                    "fixture",
                    "--fixtures",
                    str(self.library),
                    "--assume",
                    "--depth",
                    "6",
                    "--mesh-resolution",
                    "48",
                    "--out",
                    str(out),
                    *argv,
                ]
            )
        return code, buffer.getvalue(), out


class TheCommandRuns(_Case):
    def test_a_replayed_run_produces_a_document_and_its_evidence(self) -> None:
        code, output, out = self.run_cli()

        self.assertIn(code, (0, 2), output)
        document = out / "document.forgeir.json"
        self.assertTrue(document.is_file(), output)

        payload = json.loads(document.read_text(encoding="utf-8"))
        self.assertEqual(payload["components"][0]["id"], "bracket")

        evidence = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
        gates = evidence["evidence"]["evidence"]
        self.assertTrue(gates, "a report with no gates proves nothing")
        self.assertIn(evidence["overall_status"], {"PASS", "FAIL", "BLOCKED"})
        for gate in gates:
            self.assertIn("status", gate)
            self.assertIn("input_hashes", gate, "a claim with no provenance")

    def test_the_run_log_records_the_repair_that_happened(self) -> None:
        """The recorded script fails its bounds once, so a repair must appear."""
        _, _, out = self.run_cli()
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(len(run["repairs"]), 1, run["repairs"])
        self.assertEqual(run["repairs"][0]["outcome"], "applied")
        states = [event["state"] for event in run["events"]]
        self.assertIn("repairing", states)
        self.assertIn("verifying", states)

    def test_the_exit_code_is_the_verdict_not_the_absence_of_a_crash(self) -> None:
        code, output, out = self.run_cli()
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        expected = {"completed": 0, "failed": 1}.get(run["state"], 2)
        self.assertEqual(code, expected, output)



class TheRunWritesThePartItself(_Case):
    """The end goal is a file you can open, and the command was not writing one.

    `forge design` wrote five files *describing* a part -- the document, the
    evidence, the log -- and not the part. Getting a mesh meant knowing to run
    `forge export` afterwards against the document the run had just produced,
    which is a step nobody should have to be told about.

    It is written whatever the verdict, deliberately. The first live run to
    reach verification produced a design whose bolt pattern repeated the entire
    bracket four times up the Z axis; that is one glance in a viewer and a
    careful read of a gate report. A BLOCKED part is exactly the one worth
    looking at.
    """

    def test_the_run_directory_contains_a_mesh(self) -> None:
        _, output, out = self.run_cli()
        meshes = list(out.glob("*.stl"))
        self.assertEqual(len(meshes), 1, f"files: {[p.name for p in out.iterdir()]}")

    def test_it_is_named_for_the_component(self) -> None:
        _, _, out = self.run_cli()
        self.assertTrue((out / "bracket.stl").is_file())

    def test_it_is_a_real_solid_and_not_an_empty_file(self) -> None:
        """Binary STL: an 80-byte header, a triangle count, then the facets."""
        import struct

        data = (out := self.run_cli()[2], (out / "bracket.stl").read_bytes())[1]
        self.assertTrue(data[:5].startswith(b"Forge"), data[:20])
        triangles = struct.unpack("<I", data[80:84])[0]
        self.assertGreater(triangles, 100, "a handful of facets is not a part")
        self.assertEqual(len(data), 84 + 50 * triangles, "truncated STL")

    def test_the_output_points_at_it(self) -> None:
        """A file nobody is told about might as well not be written."""
        _, output, _ = self.run_cli()
        self.assertIn("bracket.stl", output)
        self.assertIn("open this", output)

    def test_a_blocked_verdict_still_gets_its_part(self) -> None:
        code, _, out = self.run_cli()
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        self.assertIn(run["state"], {"blocked", "completed"})
        self.assertTrue((out / "bracket.stl").is_file())


class TheCommandRefusesToInvent(_Case):
    def test_an_underspecified_brief_exits_three_with_its_questions(self) -> None:
        """Exit 3 is the whole point: neither success nor breakage."""
        library = build_library(
            Path(self._temporary.name) / "asking",
            brief=BRIEF_UNDERSPECIFIED,
            assume=False,
            script=_ASKING_SCRIPT,
        )
        out = Path(tempfile.mkdtemp(dir=self._temporary.name))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(
                [
                    "design",
                    BRIEF_UNDERSPECIFIED,
                    "--provider",
                    "fixture",
                    "--fixtures",
                    str(library),
                    "--out",
                    str(out),
                ]
            )
        output = buffer.getvalue()

        self.assertEqual(code, EXIT_QUESTIONS, output)
        self.assertFalse(
            (out / "document.forgeir.json").exists(),
            "a document was produced for a brief the loop said it could not "
            "honestly design",
        )
        questions = json.loads((out / "questions.json").read_text(encoding="utf-8"))
        self.assertTrue(questions)
        self.assertIn("--answer", output)
        self.assertIn(questions[0]["id"], output)


class TheCommandIsSafeToDriveFromAScript(_Case):
    def test_there_is_no_way_to_pass_a_key_on_the_command_line(self) -> None:
        """A key in argv is a key in shell history and in `ps`."""
        parser_help = io.StringIO()
        with redirect_stdout(parser_help):
            with self.assertRaises(SystemExit):
                main(["design", "--help"])
        self.assertNotIn("--api-key ", parser_help.getvalue())
        self.assertIn("--api-key-env", parser_help.getvalue())

    def test_a_missing_key_is_refused_before_anything_is_spent(self) -> None:
        previous = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with self.assertRaises(SystemExit) as caught:
                main(["design", BRIEF, "--provider", "anthropic", "--no-write"])
        finally:
            if previous is not None:
                os.environ["ANTHROPIC_API_KEY"] = previous
        self.assertIn("ANTHROPIC_API_KEY", str(caught.exception))

    def test_nothing_written_contains_anything_key_shaped(self) -> None:
        _, output, out = self.run_cli()
        # Decoded leniently rather than as UTF-8: the run now writes a binary
        # STL, and a scan that skipped it would be a scan with a hole in it.
        text = output + "\n".join(
            path.read_bytes().decode("utf-8", errors="ignore")
            for path in out.iterdir()
        )
        self.assertNotIn("sk-ant", text)
        self.assertNotIn("api_key", text)
        self.assertNotIn("ANTHROPIC_API_KEY", text)

    def test_no_write_leaves_the_directory_alone(self) -> None:
        out = Path(tempfile.mkdtemp(dir=self._temporary.name))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(
                [
                    "design",
                    BRIEF,
                    "--provider",
                    "fixture",
                    "--fixtures",
                    str(self.library),
                    "--assume",
                    "--depth",
                    "6",
                    "--no-write",
                    "--out",
                    str(out),
                ]
            )
        self.assertEqual(list(out.iterdir()), [])

    def test_a_fixture_miss_names_the_prompt_that_moved(self) -> None:
        """Replaying a different brief must fail loudly, not answer anyway."""
        out = Path(tempfile.mkdtemp(dir=self._temporary.name))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(
                [
                    "design",
                    "A completely different part nobody recorded.",
                    "--provider",
                    "fixture",
                    "--fixtures",
                    str(self.library),
                    "--assume",
                    "--out",
                    str(out),
                ]
            )
        output = buffer.getvalue()
        self.assertEqual(code, 1, output)
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["state"], "failed")
        self.assertIn("fixture", json.dumps(run["failure"]).lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TheWayOutOfBlocked(unittest.TestCase):
    """``forge accept``: the exit from a verdict that had none.

    BLOCKED is the verdict this system is proudest of -- every gate passed and
    the design still rests on a load nobody agreed to -- and nothing in the tool
    could clear it. A verdict with no exit is one people learn to route around,
    which is the one outcome worse than not having the check at all.

    Acceptance is a separate command on purpose. It is a human act, it shows
    what is being accepted and what happens if it is wrong, and it is recorded
    in the document rather than passed as a flag nobody sees again.
    """

    EXAMPLE = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "clevis"
        / "clevis.forgeir.json"
    )

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.document = Path(self._temporary.name) / "part.forgeir.json"
        self.document.write_text(self.EXAMPLE.read_text(), encoding="utf-8")

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _run(self, *argv: str) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["accept", str(self.document), *argv])
        return code, buffer.getvalue()

    def _payload(self) -> dict:
        return json.loads(self.document.read_text())

    def test_asking_with_no_arguments_shows_what_is_blocking(self) -> None:
        code, output = self._run()
        self.assertEqual(code, 2, "listing what blocks is not a pass")
        self.assertIn("ASM_DESIGN_LOAD", output)
        self.assertIn("--all", output)

    def test_it_shows_what_goes_wrong_if_the_assumption_is_wrong(self) -> None:
        """Accepting without reading the consequence is rubber-stamping."""
        _, output = self._run()
        self.assertIn("if wrong:", output)

    def test_accepting_one_leaves_the_others_blocking(self) -> None:
        code, output = self._run("--assumption", "ASM_DESIGN_LOAD")
        self.assertEqual(code, 2)
        self.assertIn("still waiting", output)
        approved = {a["id"]: a["approved"] for a in self._payload()["assumptions"]}
        self.assertTrue(approved["ASM_DESIGN_LOAD"])
        self.assertFalse(approved["ASM_MATERIAL"])

    def test_accepting_all_clears_the_block(self) -> None:
        code, _ = self._run("--all")
        self.assertEqual(code, 0)
        self.assertTrue(
            all(a["approved"] for a in self._payload()["assumptions"])
        )

    def test_the_accepted_document_verifies_without_being_blocked(self) -> None:
        """The point of the command, stated as the property it must have."""
        from forge_evidence import Status
        from forge_ir import Document
        from forge_pipeline import LoadCase, verify_component
        from forge_units import Q

        self._run("--all")
        document = Document.from_json(self.document.read_text())
        report = verify_component(
            document,
            document.component("clevis"),
            load_case=LoadCase(
                "bench_worst_case",
                Q(500, "N"),
                Q(35, "mm"),
                assumption_id="ASM_DESIGN_LOAD",
            ),
        )
        self.assertIsNot(report.overall_status, Status.BLOCKED)
        self.assertEqual(report.release_reasons, ())

    def test_acceptance_makes_it_a_new_revision(self) -> None:
        """Whoever accepted revision 1 did not accept whatever came after."""
        before = self._payload()["revision"]
        self._run("--all")
        self.assertEqual(self._payload()["revision"], before + 1)

    def test_an_unknown_assumption_is_refused_by_name(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self._run("--assumption", "ASM_NOPE")
        self.assertIn("ASM_NOPE", str(caught.exception))
        self.assertIn("ASM_DESIGN_LOAD", str(caught.exception))

    def test_accepting_twice_is_harmless(self) -> None:
        self._run("--all")
        code, output = self._run("--all")
        self.assertEqual(code, 0)
        self.assertIn("Nothing is waiting", output)

    def test_the_original_can_be_kept(self) -> None:
        target = Path(self._temporary.name) / "accepted.json"
        code, _ = self._run("--all", "--out", str(target))
        self.assertEqual(code, 0)
        self.assertTrue(target.exists())
        self.assertFalse(
            any(a["approved"] for a in self._payload()["assumptions"]),
            "the document named on the command line was modified anyway",
        )

    def test_the_result_is_still_a_valid_document(self) -> None:
        from forge_ir import Document

        self._run("--all")
        Document.from_json(self.document.read_text())


class ABlockedRunSaysWhatToDoNext(unittest.TestCase):
    """The word "blocked" arrives next to a part that is perfectly fine.

    After half an hour of generation on a local model, a verdict that reads
    like a failure and offers no next step is how people learn to stop reading
    verdicts. The run already knows which assumptions are waiting and where it
    wrote the document; saying both is the whole fix.
    """

    class _Report:
        def __init__(self, reasons):
            self.release_reasons = tuple(reasons)

    class _Run:
        def __init__(self, state, report):
            self.state = state
            self.report = report

    def _output(self, state, reasons, path=Path("runs/x/document.forgeir.json")):
        from forge_cli.design import _explain_the_block

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _explain_the_block(self._Run(state, self._Report(reasons)), path)
        return buffer.getvalue()

    def test_it_names_the_assumptions_and_the_command(self) -> None:
        from forge_orchestrator import State

        output = self._output(
            State.BLOCKED, ["assumption ASM_DESIGN_LOAD has not been accepted"]
        )
        self.assertIn("ASM_DESIGN_LOAD", output)
        self.assertIn("forge accept", output)
        self.assertIn("document.forgeir.json", output)

    def test_it_says_what_each_assumption_assumes(self) -> None:
        """The cantilever run listed `ASM_DESIGN_LOAD` alone, and read as
        Forge asking for the 150 N the brief gave. Its statement says what
        is actually assumed, so it is printed with it."""
        from forge_cli.design import _explain_the_block
        from forge_orchestrator import State

        run = self._Run(State.BLOCKED, self._Report(
            ["assumption ASM_DESIGN_LOAD has not been accepted"]))
        run.brief = "A load of 150 N pushes straight down on the free end."
        run.document_payload = {"assumptions": [{
            "id": "ASM_DESIGN_LOAD", "statement": "It acts statically.",
            "value": {"magnitude": 150.0, "unit": "N"}}]}
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _explain_the_block(run, Path("runs/x/document.forgeir.json"))
        output = buffer.getvalue()
        self.assertIn("It acts statically. [150 N]", output)
        self.assertIn("150 N and where it acts are your brief's own", output)
        self.assertIn("steady", output)

    def test_it_says_blocked_is_not_failed(self) -> None:
        from forge_orchestrator import State

        output = self._output(
            State.BLOCKED, ["assumption ASM_MATERIAL has not been accepted"]
        )
        self.assertIn("not failed", output)

    def test_a_completed_run_is_not_lectured(self) -> None:
        from forge_orchestrator import State

        self.assertEqual(self._output(State.COMPLETED, []), "")

    def test_a_block_that_is_not_about_assumptions_says_nothing(self) -> None:
        """A failed critical gate is a different problem with a different fix."""
        from forge_orchestrator import State

        output = self._output(State.BLOCKED, ["REQ_MASS: failed - too heavy"])
        self.assertEqual(output, "")

    def test_without_a_written_document_it_does_not_invent_a_path(self) -> None:
        from forge_orchestrator import State

        output = self._output(
            State.BLOCKED,
            ["assumption ASM_MATERIAL has not been accepted"],
            path=None,
        )
        self.assertIn("ASM_MATERIAL", output)
        self.assertNotIn("forge accept", output)
