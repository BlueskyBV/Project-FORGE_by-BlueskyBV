"""V2 stage 4: the pinned font's letters, and each program's reading of them (docs/V2-stage4.md, 7.1).

The table in forge_spec/glyphs.py is written from the font file by
scripts/font_glyphs.py. Where fontTools is installed, these tests check that
the table is the file's, that the script writes it byte for byte, and that
the solver's and the judge's own readings of the contours give every
letter's area and box as fontTools' own pens do (an independent path), and
the judge's inside test agrees with fontTools' nonzero-winding test. Without
fontTools, the two readings are held to each other, and the judge's
distances to dense samples of its own curves.
"""

from __future__ import annotations

import importlib.util
import math
import random
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
from forge_checks import letters as judge
from forge_checks.place import PlaceError, place
from forge_spec import font, glyphs
from forge_spec import letters as solver
from forge_spec.placement import solve

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_specs import a, pick, read

ROOT = Path(__file__).resolve().parent.parent
HAVE_FONTTOOLS = importlib.util.find_spec("fontTools") is not None


def script(name: str) -> ModuleType:
    found = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / f"{name}.py"
    )
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


def glyph_set() -> tuple[Any, Any, dict[int, str]]:
    from fontTools.ttLib import TTFont

    file = ROOT / "packages" / "forge_fonts" / "fonts" / font.FILE
    found = TTFont(str(file))
    return found, found.getGlyphSet(), found.getBestCmap()


class TheTable(unittest.TestCase):
    def test_it_is_the_pinned_font_s(self) -> None:
        self.assertEqual(glyphs.SHA256, font.SHA256)
        self.assertEqual(set(glyphs.CONTOURS), set(font.ADVANCES))

    def test_a_capital_h_is_a_capital_tall(self) -> None:
        box = solver.glyph_box("H")
        assert box is not None
        self.assertEqual((box[0][1], box[1][1]), (0.0, float(font.CAP_HEIGHT)))

    @unittest.skipUnless(HAVE_FONTTOOLS, "fontTools reads the font file itself")
    def test_it_is_the_file_s_and_the_script_writes_it(self) -> None:
        made = script("font_glyphs")
        self.assertEqual(made.contours(), dict(glyphs.CONTOURS))
        written = (ROOT / "packages" / "forge_spec" / "glyphs.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(made.source(), written)


class EachProgramReadsTheCurves(unittest.TestCase):
    @unittest.skipUnless(HAVE_FONTTOOLS, "fontTools' pens are the independent path")
    def test_every_letter_s_area_and_box_are_the_font_s(self) -> None:
        from fontTools.pens.areaPen import AreaPen
        from fontTools.pens.boundsPen import BoundsPen

        _, shapes, cmap = glyph_set()
        for letter in font.ADVANCES:
            with self.subTest(letter=letter):
                drawn = shapes[cmap[ord(letter)]]
                area, bounds = AreaPen(shapes), BoundsPen(shapes)
                drawn.draw(area)
                drawn.draw(bounds)
                self.assertAlmostEqual(
                    solver.signed_area(letter), area.value, delta=1e-6
                )
                box = solver.glyph_box(letter)
                ink = judge.ink_box(letter, float(font.CAP_HEIGHT))
                if bounds.bounds is None:
                    self.assertIsNone(box)
                    self.assertIsNone(ink)
                    continue
                assert box is not None and ink is not None
                self.assertEqual(
                    (*box[0], *box[1]), tuple(float(v) for v in bounds.bounds)
                )
                self.assertEqual(ink, box)

    @unittest.skipUnless(
        HAVE_FONTTOOLS, "fontTools' nonzero-winding test is the independent path"
    )
    def test_the_judge_s_inside_is_nonzero_winding(self) -> None:
        from fontTools.pens.pointInsidePen import PointInsidePen

        _, shapes, cmap = glyph_set()
        rng = random.Random(7)
        for letter in font.ADVANCES:
            box = solver.glyph_box(letter)
            if box is None:
                continue
            ink = judge.Ink.of(letter, float(font.CAP_HEIGHT))
            (x0, y0), (x1, y1) = box
            x = np.array([rng.uniform(x0 - 40, x1 + 40) for _ in range(40)])
            y = np.array([rng.uniform(y0 - 40, y1 + 40) for _ in range(40)])
            found = ink.inside(x, y)
            for k in range(len(x)):
                pen = PointInsidePen(shapes, (float(x[k]), float(y[k])), evenOdd=False)
                shapes[cmap[ord(letter)]].draw(pen)
                self.assertEqual(bool(found[k]), pen.getResult(), (letter, x[k], y[k]))

    def test_the_two_readings_agree(self) -> None:
        for text in ("Forge V2", "jÉ_ÇQ@%&", "©®", "  "):
            for height in (1.0, 7.5):
                self.assertEqual(
                    solver.ink_box(text, height), judge.ink_box(text, height)
                )

    def test_the_judge_s_distance_is_the_nearest_point_of_the_edge(self) -> None:
        rng = random.Random(3)
        for text in ("Sg", "@", "°8", "Hello", "ç", "©", "%&"):
            ink = judge.Ink.of(text, 10.0)
            assert ink.box is not None
            (x0, y0), (x1, y1) = ink.box
            x = np.array([rng.uniform(x0 - 2, x1 + 2) for _ in range(300)])
            y = np.array([rng.uniform(y0 - 2, y1 + 2) for _ in range(300)])
            found = ink.distance(x, y)
            t = np.linspace(0.0, 1.0, 4001)
            edges = [edge.q for edge in ink.edges]

            def at(q: Any, t: Any) -> Any:
                (p, c, r) = q
                return np.stack([(1 - t) ** 2 * p[0] + 2 * (1 - t) * t * c[0] + t * t * r[0],
                                 (1 - t) ** 2 * p[1] + 2 * (1 - t) * t * c[1] + t * t * r[1]], axis=1)  # fmt: skip

            samples = np.stack([at(q, t) for q in edges])  # (edges, samples, 2)
            for k in range(len(x)):
                gaps = np.hypot(samples[:, :, 0] - x[k], samples[:, :, 1] - y[k])
                e, i = np.unravel_index(int(np.argmin(gaps)), gaps.shape)
                # The nearest sample, then the stretch of its edge round it, finely.
                fine = np.linspace(
                    max(t[i] - 1 / 4000, 0.0), min(t[i] + 1 / 4000, 1.0), 4001
                )
                near = at(edges[e], fine)
                nearest = float(np.min(np.hypot(near[:, 0] - x[k], near[:, 1] - y[k])))
                # Never farther than a sample; nearer only by what lies between two fine samples.
                self.assertLessEqual(found[k], nearest + 1e-12, text)
                self.assertGreaterEqual(found[k], nearest - 1e-7, text)

    @unittest.skipUnless(
        importlib.util.find_spec("manifold3d"),
        "manifold3d makes the region independently",
    )
    def test_the_judge_s_edge_is_the_nonzero_region_s(self) -> None:
        """Overlapping parts of one letter (Ç's cedilla) and of two (a run of underscores) are one region: their edge is its."""
        import manifold3d

        rng = random.Random(5)
        for text in ("Ç", "ç", "__", "fT", "Ø8", "©"):
            ink = judge.Ink.of(text, 10.0)
            contours, current, start = [], [], None
            t = np.linspace(0.0, 1.0, 400, endpoint=False)
            for p, c, q in ink.pieces:
                start = p if start is None else start
                current.append(np.stack([(1 - t) ** 2 * p[0] + 2 * (1 - t) * t * c[0] + t * t * q[0],
                                         (1 - t) ** 2 * p[1] + 2 * (1 - t) * t * c[1] + t * t * q[1]], axis=1))  # fmt: skip
                if math.dist(q, start) < 1e-12:
                    contours.append(np.concatenate(current))
                    current, start = [], None
            region = manifold3d.CrossSection(
                contours, fillrule=manifold3d.FillRule.NonZero
            )
            rings = [np.asarray(r) for r in region.to_polygons()]
            a = np.concatenate(rings)
            b = np.concatenate([np.roll(r, -1, axis=0) for r in rings])
            assert ink.box is not None
            (x0, y0), (x1, y1) = ink.box
            points = np.array(
                [
                    [rng.uniform(x0 - 1, x1 + 1), rng.uniform(y0 - 1, y1 + 1)]
                    for _ in range(300)
                ]
            )
            found = ink.distance(points[:, 0], points[:, 1])
            for k, p in enumerate(points):
                along = np.clip(
                    np.sum((p - a) * (b - a), axis=1) / np.sum((b - a) ** 2, axis=1),
                    0.0,
                    1.0,
                )
                expected = float(
                    np.min(np.linalg.norm(a + along[:, None] * (b - a) - p, axis=1))
                )
                self.assertAlmostEqual(float(found[k]), expected, delta=1e-4, msg=text)


class TheInkIsHeldToTheFace(unittest.TestCase):
    """The solver and the judge hold a line's ink, not its box, to the face (docs/V2-stage4.md, 7.1)."""

    def letters(self, text: str, **place_: Any) -> list[dict[str, Any]]:
        return [
            {"id": "plate", "kind": "block", "words": [1], "length": a(40), "width": a(20), "height": a(5)},
            {"id": "t", "kind": "text", "words": [1], "on": {"item": "plate", "face": "+z"},
             "text": {"text": text, "from": {"assumed": "for the test"}}, "height": a(5), "depth": a(0.5),
             "mode": pick("engrave"), "place": place_},
        ]  # fmt: skip

    def both(self, items: list[dict[str, Any]]) -> tuple[list[str], bool]:
        spec = read(items)
        layout = solve(spec)
        try:
            place(spec)
        except PlaceError:
            return [i.message for i in layout.issues], False
        return [i.message for i in layout.issues], True

    def test_a_tail_below_the_line(self) -> None:
        # Its box's foot 0.5 above the face's edge; the j's tail reaches ~1.4 below its baseline.
        side = {"side": "-y", "distance": a(0.5), "to": "edge"}
        found, judged = self.both(self.letters("Hj", y=side))
        self.assertTrue(
            any("runs past" in m or "doesn't fit" in m or "edge" in m for m in found),
            found,
        )
        self.assertFalse(judged)
        found, judged = self.both(self.letters("HH", y=side))
        self.assertEqual(found, [])
        self.assertTrue(judged)

    def test_a_full_stop_s_advance_isn_t_ink(self) -> None:
        # The line's box runs 0.2 past the face's +x edge, the full stop's own ink well inside it.
        length = font.text_width("AB.", 5.0)
        place_ = {"x": {"offset": a(20 - length / 2 + 0.2)}}
        found, judged = self.both(self.letters("AB.", **place_))
        self.assertEqual(found, [])
        self.assertTrue(judged)


if __name__ == "__main__":
    unittest.main()
