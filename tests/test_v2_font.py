"""V2: the pinned font and the metrics the spec layer reads from it (forge_spec.font).

Text's size and place come from the one font Forge ships
(docs/definitions/text.md). The table in forge_spec/font.py is written from
the font file by scripts/font_metrics.py; these tests check that the file
shipped is the file pinned, and, where fontTools is installed, that the table
is the file's. They also pin how a line's length is worked out.
"""

from __future__ import annotations

import hashlib
import importlib.util
import unittest
from pathlib import Path

from forge_spec import font

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "packages" / "forge_fonts" / "fonts" / font.FILE


class TheFileShippedIsTheFilePinned(unittest.TestCase):
    def test_its_digest(self) -> None:
        self.assertEqual(hashlib.sha256(FILE.read_bytes()).hexdigest(), font.SHA256)

    def test_its_licence_goes_with_it(self) -> None:
        licence = (FILE.parent / "LICENSE-DejaVu.txt").read_text(encoding="utf-8")
        self.assertIn("Bitstream Vera", licence)
        self.assertIn(font.VERSION, licence)

    @unittest.skipUnless(
        importlib.util.find_spec("fontTools"), "fontTools reads the font file itself"
    )
    def test_the_table_is_the_files(self) -> None:
        found = importlib.util.spec_from_file_location(
            "font_metrics", ROOT / "scripts" / "font_metrics.py"
        )
        assert found is not None and found.loader is not None
        script = importlib.util.module_from_spec(found)
        found.loader.exec_module(script)
        name, version, upm, cap, advances = script.metrics()
        self.assertEqual(
            (name, version, upm, cap),
            (font.FONT, font.VERSION, font.UNITS_PER_EM, font.CAP_HEIGHT),
        )
        self.assertEqual(advances, dict(font.ADVANCES))


class ALinesLength(unittest.TestCase):
    def test_its_letters_advances_added_up_a_capital_tall(self) -> None:
        h, i = font.ADVANCES["H"], font.ADVANCES["i"]
        self.assertAlmostEqual(
            font.text_width("Hi", 7.0), (h + i) * 7.0 / font.CAP_HEIGHT
        )
        self.assertAlmostEqual(
            font.text_width("H H", 1.0), (2 * h + font.ADVANCES[" "]) / font.CAP_HEIGHT
        )
        self.assertEqual(font.text_width("", 5.0), 0.0)

    def test_letters_it_lacks_each_once(self) -> None:
        self.assertEqual(font.missing_letters("A中 b中\n"), ["中", "\n"])
        self.assertEqual(font.missing_letters("Ø 8 mm ±0.1 ⌀"), [])


if __name__ == "__main__":
    unittest.main()
