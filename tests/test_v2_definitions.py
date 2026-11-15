"""V2 stage 2: every field of every kind has a written definition (docs/definitions).

The compiler, the oracle and the random-spec generator are each written from
these pages, and share nothing else (plan, section 4.6). So the schema can't
grow a kind, a field, a choice, a face, an edge set, a pattern or a fit that
the pages don't define, and the pages can't keep defining one the schema has
dropped. Every page keeps its layout, says what it is checked as, and links
only to pages that exist.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from forge_spec.draft import FITS, PATTERN_FIELDS
from forge_spec.schema import KINDS, FieldType

PAGES = Path(__file__).resolve().parent.parent / "docs" / "definitions"
SECTIONS = ("## The shape", "## Fields", "## Faces", "## Edges", "## Checked as")
#: The shared pages, besides one per kind.
SHARED = ("README.md", "frame.md", "place.md", "sizes.md", "edges.md")


def page(name: str) -> str:
    return (PAGES / name).read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """The text under a ``##`` heading, up to the next one."""
    start = text.index(heading + "\n") + len(heading) + 1
    following = text.find("\n## ", start)
    return text[start:] if following < 0 else text[start:following]


def subsections(text: str) -> dict[str, str]:
    """Each ``### `name` `` heading's name, and the text under it."""
    found: dict[str, str] = {}
    parts = re.split(r"^### `([^`]+)`\n", text, flags=re.M)
    for name, body in zip(parts[1::2], parts[2::2], strict=True):
        found[name] = body
    return found


def bullet_names(text: str) -> set[str]:
    """The names a list defines: the code spans before the colon of each bullet."""
    names: set[str] = set()
    for line in text.splitlines():
        if line.startswith("- "):
            head = line[2:].split(":", 1)[0]
            names |= set(re.findall(r"`([^`]+)`", head))
    return names


class EveryKindHasItsPage(unittest.TestCase):
    def test_each_kind_one_page_laid_out_alike(self) -> None:
        for kind in KINDS:
            with self.subTest(kind=kind):
                text = page(f"{kind}.md")
                self.assertTrue(text.startswith(f"# {kind}\n"), kind)
                self.assertIn("Status: ", text)
                positions = [text.index(s + "\n") for s in SECTIONS]
                self.assertEqual(positions, sorted(positions), kind)

    def test_no_page_for_a_kind_the_schema_doesnt_have(self) -> None:
        pages = {p.name for p in PAGES.glob("*.md")} - set(SHARED)
        self.assertEqual(pages, {f"{kind}.md" for kind in KINDS})


class EveryFieldIsDefined(unittest.TestCase):
    def test_each_field_and_nothing_else(self) -> None:
        for kind, spec in KINDS.items():
            with self.subTest(kind=kind):
                defined = subsections(section(page(f"{kind}.md"), "## Fields"))
                self.assertEqual(list(defined), list(spec.field_names), kind)
                for name, body in defined.items():
                    self.assertTrue(body.strip(), (kind, name))

    def test_each_choice_of_each_choice_field(self) -> None:
        for kind, spec in KINDS.items():
            defined = subsections(section(page(f"{kind}.md"), "## Fields"))
            for field in spec.fields:
                if field.type is FieldType.CHOICE:
                    with self.subTest(kind=kind, field=field.name):
                        self.assertEqual(
                            bullet_names(defined[field.name]), set(field.choices)
                        )


class EveryFaceAndEdgeSetIsDefined(unittest.TestCase):
    def test_faces(self) -> None:
        for kind, spec in KINDS.items():
            with self.subTest(kind=kind):
                text = section(page(f"{kind}.md"), "## Faces")
                self.assertEqual(bullet_names(text), set(spec.faces))
                if not spec.faces:
                    self.assertTrue(text.strip().startswith("None"), kind)

    def test_edge_sets(self) -> None:
        for kind, spec in KINDS.items():
            with self.subTest(kind=kind):
                text = section(page(f"{kind}.md"), "## Edges")
                self.assertEqual(bullet_names(text), set(spec.edges))
                if not spec.edges:
                    self.assertTrue(text.strip().startswith("None"), kind)

    def test_a_joint_is_defined_once_for_every_kind_that_has_one(self) -> None:
        self.assertIn("joint", subsections(page("edges.md")))


class TheSharedDefinitions(unittest.TestCase):
    def test_every_pattern(self) -> None:
        self.assertEqual(
            set(subsections(section(page("place.md"), "## Patterns"))),
            set(PATTERN_FIELDS),
        )

    def test_every_fit(self) -> None:
        defined = subsections(
            section(page("sizes.md"), "## Sizes from standard tables")
        )
        self.assertEqual(set(defined), set(FITS))


class WhatEachIsCheckedAs(unittest.TestCase):
    def test_its_verification_class(self) -> None:
        for kind, spec in KINDS.items():
            with self.subTest(kind=kind):
                said = section(page(f"{kind}.md"), "## Checked as").split()[0]
                self.assertEqual(said.rstrip(".:").lower(), spec.verification)


class TheLinks(unittest.TestCase):
    def test_every_link_is_to_a_page_that_exists(self) -> None:
        for path in sorted(PAGES.glob("*.md")):
            for target in re.findall(
                r"\]\(([^)#]+)(?:#[^)]*)?\)", path.read_text(encoding="utf-8")
            ):
                if "://" in target:
                    continue
                with self.subTest(page=path.name, link=target):
                    self.assertTrue((path.parent / target).is_file())


if __name__ == "__main__":
    unittest.main()


def table_rows(text: str, header: str) -> list[list[str]]:
    """The rows of the markdown table whose header line starts with ``header``."""
    lines = text.splitlines()
    start = next(n for n, line in enumerate(lines) if line.startswith(header))
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


class TheTablesAreTheCodesTables(unittest.TestCase):
    def test_clearance_tapped_and_bearings(self) -> None:
        from forge_spec.tables import BEARINGS, CLEARANCE, TAPPED

        text = page("sizes.md")
        self.assertEqual(
            {
                r[0]: tuple(float(x) for x in r[1:])
                for r in table_rows(text, "| Size | Fine")
            },
            dict(CLEARANCE),
        )
        self.assertEqual(
            {
                r[0]: tuple(float(x) for x in r[1:])
                for r in table_rows(text, "| Size | Coarse pitch")
            },
            dict(TAPPED),
        )
        self.assertEqual({r[0]: tuple(float(x) for x in r[1:]) for r in table_rows(text, "| Bearing")},
                         {k: (b.outer, b.width, b.bore) for k, b in BEARINGS.items()})  # fmt: skip

    def test_the_font_named_is_the_font_read(self) -> None:
        from forge_spec import font

        text = page("text.md")
        self.assertIn(f"{font.FONT}, version {font.VERSION}", text)
        self.assertIn(font.SHA256, text)
        self.assertIn(font.FILE, text)
