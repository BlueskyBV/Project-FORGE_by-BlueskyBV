"""Forge's eyes: the part drawn, shown to the model, and followed live.

The model that designs a part never saw it. Six views of the built part --
three outside views with millimetre ticks, a 3D view, two sections -- are
now drawn after each build, handed to the failure analyst beside the
numbers when the model can look at pictures, and written into the run's
folder as a live page the person running it can watch.
"""

from __future__ import annotations

import copy
import pathlib
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from fixtures.bracket_responses import (  # noqa: E402
    BRIEF,
    DESIGNER_VALID,
    INTERPRETER,
    REQUIREMENTS,
)

from forge_models import ScriptedProvider  # noqa: E402
from forge_orchestrator import Orchestrator, OrchestratorConfig  # noqa: E402

FAST = OrchestratorConfig(measurement_depth=6, mesh_resolution=48)


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _the_bracket_report():
    from forge_ir import Document
    import json

    from forge_pipeline import verify_component

    document = Document.from_json(json.dumps(DESIGNER_VALID["document"]))
    return verify_component(document, document.components[0],
                            measurement_depth=6, mesh_resolution=48)


class TheSheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = _the_bracket_report()

    def test_six_views_in_one_picture(self) -> None:
        from forge_pipeline.render import render_report

        png = render_report(self.report, tile=300)
        self.assertEqual(_png_size(png), (900, 600))

    def test_the_same_part_is_drawn_the_same(self) -> None:
        from forge_pipeline.render import render_report

        self.assertEqual(render_report(self.report, tile=240),
                         render_report(self.report, tile=240))

    def test_the_png_is_well_formed(self) -> None:
        from forge_pipeline.render import render_report

        png = render_report(self.report, tile=200)
        # IHDR, IDAT, IEND, each with a CRC that checks.
        at, kinds = 8, []
        while at < len(png):
            length = struct.unpack(">I", png[at:at + 4])[0]
            kind = png[at + 4:at + 8]
            data = png[at + 8:at + 8 + length]
            crc = struct.unpack(">I", png[at + 8 + length:at + 12 + length])[0]
            self.assertEqual(crc, zlib.crc32(kind + data) & 0xFFFFFFFF)
            kinds.append(kind)
            at += 12 + length
        self.assertEqual(kinds, [b"IHDR", b"IDAT", b"IEND"])

    def test_a_section_shows_material_and_space(self) -> None:
        """The sections are cut from the solid itself: the bracket's middle
        section has material (orange) and paper both."""
        import numpy as np

        from forge_pipeline.render import _CUT, _Canvas, _section

        part = self.report.part
        canvas = _Canvas(200, -10.0, 80.0, -10.0, 80.0)
        _section(canvas, part.solid, 1, 25.0, 0, 2)
        cut = np.all(canvas.image == _CUT, axis=2)
        self.assertTrue(cut.any())
        self.assertFalse(cut.all())

    def test_a_mark_is_drawn_where_it_is(self) -> None:
        import numpy as np

        from forge_pipeline.render import Mark, _Canvas, _marks, _RED

        canvas = _Canvas(200, 0.0, 100.0, 0.0, 100.0)
        _marks(canvas, [Mark("HERE", (50.0, 0.0, 50.0))],
               np.array([1.0, 0, 0]), np.array([0, 0, 1.0]))
        x, y = canvas.px(50.0, 50.0)
        window = canvas.image[int(y) - 9:int(y) + 9, int(x) - 9:int(x) + 9]
        self.assertTrue(np.all(window == _RED, axis=2).any())

    def test_failing_holes_are_marked(self) -> None:
        from forge_pipeline.render import marks_from_report

        class _Gate:
            identifier = "GEOM_HOLES_ARE_HOLES"

        class _Status:
            value = "FAIL"

        class _Evidence:
            detail = {"notched": [{"feature": "pivot", "centre": [1, 2, 3]}]}

        class _Result:
            gate, status, evidence = _Gate(), _Status(), _Evidence()

        class _Report:
            part = self.report.part
            gate_results = (_Result(),)

        marks = marks_from_report(_Report())
        self.assertEqual([(m.label, m.point) for m in marks],
                         [("pivot NOTCH", (1.0, 2.0, 3.0))])


class _SeeingProvider(ScriptedProvider):
    """A scripted model that says it can look at pictures."""

    @property
    def info(self):
        from dataclasses import replace

        return replace(super().info, supports_images=True)


def _a_design_one_figure_off() -> dict:
    """The bracket with its lever arm at 40 mm where the brief says 32: it
    compiles, and fails one requirement."""
    answer = copy.deepcopy(DESIGNER_VALID)
    for parameter in answer["document"]["components"][0]["parameters"]:
        if parameter["id"] == "lever_arm":
            parameter["value"]["magnitude"] = 40.0
    return answer


ANALYST_PUTS_IT_BACK = {
    "diagnosis": "`lever_arm` is 40 mm; the brief and REQ_SHAFT_HEIGHT say 32.",
    "strategy": "set lever_arm to 32 mm",
    "confidence": "high",
    "abandon": False,
    "patches": [{"op": "replace",
                 "pointer": "/components/0/parameters/lever_arm/value",
                 "value": {"magnitude": 32.0, "unit": "mm"},
                 "reason": "the brief's figure"}],
}


class TheModelSeesThePart(unittest.TestCase):
    def _run(self, provider_class):
        provider = provider_class([INTERPRETER, REQUIREMENTS,
                                   _a_design_one_figure_off(),
                                   ANALYST_PUTS_IT_BACK])
        seen: list[tuple[str, object]] = []
        run = Orchestrator(provider, config=FAST).design(
            BRIEF, watch=lambda kind, item: seen.append((kind, item)))
        analyst = [r for r in provider.requests
                   if r.purpose == "failure_analyst"]
        return run, analyst, seen

    def test_an_analyst_that_can_see_is_shown_the_part(self) -> None:
        run, analyst, _ = self._run(_SeeingProvider)
        self.assertTrue(analyst, f"no repair round: {run.render()}")
        message = analyst[0].messages[0]
        self.assertEqual(len(message.images), 1)
        self.assertEqual(_png_size(message.images[0])[0] % 3, 0)
        self.assertIn("<the_part_as_built>", message.content)
        self.assertIn("<brief>", message.content)

    def test_one_that_cannot_is_sent_no_picture(self) -> None:
        _, analyst, _ = self._run(ScriptedProvider)
        self.assertTrue(analyst)
        self.assertEqual(analyst[0].messages[0].images, ())
        self.assertNotIn("<the_part_as_built>", analyst[0].messages[0].content)

    def test_a_watcher_is_told_each_step_and_shown_each_build(self) -> None:
        run, _, seen = self._run(ScriptedProvider)
        kinds = [kind for kind, _ in seen]
        self.assertGreater(kinds.count("event"), 5)
        pictures = [item for kind, item in seen if kind == "picture"]
        self.assertGreaterEqual(len(pictures), 2)  # failing, then repaired
        self.assertEqual(len(run.pictures), len(pictures))

    def test_nobody_watching_and_no_eyes_draws_nothing(self) -> None:
        provider = ScriptedProvider([INTERPRETER, REQUIREMENTS,
                                     _a_design_one_figure_off(),
                                     ANALYST_PUTS_IT_BACK])
        run = Orchestrator(provider, config=FAST).design(BRIEF)
        self.assertEqual(run.pictures, [])

    def test_the_wire_carries_the_picture_as_an_image_block(self) -> None:
        from forge_models.anthropic import _wire_messages
        from forge_models.types import user

        wire = _wire_messages([user("look", (b"\x89PNG fake",))])
        blocks = wire[0]["content"]
        self.assertEqual(blocks[0]["type"], "image")
        self.assertEqual(blocks[0]["source"]["media_type"], "image/png")
        self.assertEqual(blocks[-1], {"type": "text", "text": "look"})

    def test_text_alone_goes_as_it_always_did(self) -> None:
        from forge_models.anthropic import _wire_messages
        from forge_models.types import user

        self.assertEqual(_wire_messages([user("hello")]),
                         [{"role": "user", "content": "hello"}])

    def test_a_fixture_fingerprint_without_pictures_is_unchanged(self) -> None:
        from forge_models.types import Message

        self.assertEqual(Message("user", "x").as_dict(),
                         {"role": "user", "content": "x"})


class TheLivePage(unittest.TestCase):
    def test_it_follows_the_run_and_ends_with_the_part_in_3d(self) -> None:
        from forge_cli.live import LiveView

        with tempfile.TemporaryDirectory() as folder:
            live = LiveView(pathlib.Path(folder), "a bracket", "scripted",
                            open_browser=False)
            provider = ScriptedProvider([INTERPRETER, REQUIREMENTS,
                                         _a_design_one_figure_off(),
                                         ANALYST_PUTS_IT_BACK])
            run = Orchestrator(provider, config=FAST).design(
                BRIEF, watch=live)
            running = live.page.read_text(encoding="utf-8")
            self.assertIn("location.reload", running)
            self.assertIn("views-01.png", running)
            self.assertTrue((pathlib.Path(folder) / "views-01.png").exists())
            live.finish(run)
            done = live.page.read_text(encoding="utf-8")
            self.assertNotIn("location.reload", done)
            self.assertIn("live-mesh.js", done)
            self.assertTrue((pathlib.Path(folder) / "live-mesh.js").exists())
            # The viewer travels with the run: it opens from disk, offline.
            for name in ("three.min.js", "OrbitControls.js"):
                self.assertTrue((pathlib.Path(folder) / name).exists(), name)
                self.assertIn(f'src="{name}"', done)
            self.assertNotIn("cdn.", done)
            self.assertIn("could not load here", done)

    def test_a_broken_watcher_never_stops_the_run(self) -> None:
        def broken(kind, item):
            raise RuntimeError("the screen fell off")

        provider = ScriptedProvider([INTERPRETER, REQUIREMENTS,
                                     DESIGNER_VALID])
        run = Orchestrator(provider, config=FAST).design(BRIEF, watch=broken)
        self.assertIsNotNone(run.report)


if __name__ == "__main__":
    unittest.main()


MATCHES = {"diagnosis": "The part matches the brief.", "strategy": "none",
           "confidence": "high", "abandon": True,
           "abandon_reason": "matches the brief", "patches": []}


class TheLastLook(unittest.TestCase):
    """Every check passed: a model that can see looks once more, against the
    brief, before the part is released."""

    def _run(self, *analyst, provider_class=_SeeingProvider):
        provider = provider_class([INTERPRETER, REQUIREMENTS, DESIGNER_VALID,
                                   *analyst])
        run = Orchestrator(provider, config=FAST).design(BRIEF)
        looks = [r for r in provider.requests
                 if r.purpose == "failure_analyst"]
        return run, looks

    def test_a_part_that_matches_is_released_as_it_was(self) -> None:
        plain, _ = self._run(provider_class=ScriptedProvider)
        run, looks = self._run(MATCHES)
        self.assertEqual(len(looks), 1)
        self.assertIn("last look", looks[0].messages[0].content)
        self.assertEqual(len(looks[0].messages[0].images), 1)
        self.assertIs(run.state, plain.state)
        self.assertIsNone(run.failure)
        self.assertEqual(run.repairs[-1].outcome, "looked: nothing to change")
        said = [e.summary for e in run.events]
        self.assertFalse(any("repair abandoned" in s for s in said), said)
        self.assertIn("Repairs   : 0 (and a last look", run.render())

    def test_a_change_that_breaks_a_check_is_not_kept(self) -> None:
        breaks = {"diagnosis": "The bore looks small.", "strategy": "widen it",
                  "confidence": "low", "abandon": False,
                  "patches": [{"op": "replace",
                               "pointer": "/components/0/parameters/"
                                          "bore_diameter/value",
                               "value": {"magnitude": 26.0, "unit": "mm"}}]}
        plain, _ = self._run(provider_class=ScriptedProvider)
        run, _ = self._run(breaks)
        self.assertIs(run.state, plain.state)
        self.assertEqual(run.repairs[-1].outcome, "reverted")
        bore = next(p for p in run.document_payload["components"][0][
            "parameters"] if p["id"] == "bore_diameter")
        self.assertEqual(bore["value"]["magnitude"], 20.0)

    def test_a_look_that_undoes_a_repair_holds_the_part(self) -> None:
        """The validation suite's counterbored plate: a check the first
        design failed, a repair that changed the part to pass it, and a last
        look that saw the part did not match the brief and put it back. The
        look was reverted and a wrong part released as passing. When the
        look's change fails only checks a repair was made for, the part is
        held for a person with what the look saw."""
        undoes = {"diagnosis": "The brief puts the shaft 40 mm up; the repair "
                               "moved it to 32.",
                  "strategy": "put lever_arm back to 40 mm",
                  "confidence": "high", "abandon": False,
                  "patches": [{"op": "replace",
                               "pointer": "/components/0/parameters/"
                                          "lever_arm/value",
                               "value": {"magnitude": 40.0, "unit": "mm"}}]}
        provider = _SeeingProvider([INTERPRETER, REQUIREMENTS,
                                    _a_design_one_figure_off(),
                                    ANALYST_PUTS_IT_BACK, undoes])
        run = Orchestrator(provider, config=FAST).design(BRIEF)
        self.assertEqual(run.state.value, "blocked")
        held = [a for a in run.document_payload["assumptions"]
                if a["id"] == "ASM_LAST_LOOK_DISAGREES"]
        self.assertEqual(len(held), 1)
        self.assertIn("shaft 40 mm up", held[0]["statement"])
        self.assertFalse(held[0]["approved"])
        self.assertTrue(run.repairs[-1].outcome.startswith("held"))
        # The part held is the part as it passed: lever arm at 32.
        arm = next(p for p in run.document_payload["components"][0][
            "parameters"] if p["id"] == "lever_arm")
        self.assertEqual(arm["value"]["magnitude"], 32.0)
        self.assertIn("assumption ASM_LAST_LOOK_DISAGREES has not been "
                      "accepted", list(run.report.release_reasons))
        self.assertFalse([g for g in run.report.gate_results
                          if g.status.value == "FAIL"])

    def test_a_model_that_cannot_see_is_not_asked(self) -> None:
        _, looks = self._run(provider_class=ScriptedProvider)
        self.assertEqual(looks, [])


class AnyPartIsDrawn(unittest.TestCase):
    """A 1 mm part, a 3 m part, a rod seen end on: each drawn whole, with
    millimetre ticks it can be read by, and quickly."""

    def _sheet(self, solid):
        import time

        import numpy as np

        from forge_geom import extract_manifold_surface
        from forge_pipeline.render import Mark, render_sheet

        mesh = extract_manifold_surface(solid, resolution=64)
        started = time.perf_counter()
        png = render_sheet(solid, mesh, tile=300, marks=[
            Mark("far", (1e6, 0, 0)), Mark("nan", (float("nan"), 0, 0))])
        self.assertLess(time.perf_counter() - started, 4.0)
        return png

    def test_tiny_huge_and_end_on(self) -> None:
        from forge_geom.sdf import BoxSDF

        for solid in (BoxSDF((0, 0, 0), (0.5, 0.3, 0.2)),
                      BoxSDF((1000, -500, 3000), (1500, 800, 200)),
                      BoxSDF((0, 0, 0), (100, 0.5, 0.5))):
            self.assertEqual(_png_size(self._sheet(solid)), (900, 600))

    def test_a_face_bigger_than_sampling_is_filled_solid(self) -> None:
        import numpy as np

        from forge_geom import extract_manifold_surface
        from forge_geom.sdf import BoxSDF
        from forge_pipeline.render import _Canvas, _PAPER, _shade_mesh

        solid = BoxSDF((0, 0, 0), (100, 0.5, 0.5))
        mesh = extract_manifold_surface(solid, resolution=64)
        canvas = _Canvas(300, -0.6, 0.6, -0.6, 0.6)
        _shade_mesh(canvas, np.asarray(mesh.vertices),
                    np.asarray(mesh.faces), np.array([0.0, 1.0, 0.0]),
                    np.array([0.0, 0.0, 1.0]))
        x0, y0 = canvas.px(-0.3, 0.3)
        x1, y1 = canvas.px(0.3, -0.3)
        middle = canvas.image[int(y0):int(y1), int(x0):int(x1)]
        self.assertFalse(np.all(middle == _PAPER, axis=2).any())
