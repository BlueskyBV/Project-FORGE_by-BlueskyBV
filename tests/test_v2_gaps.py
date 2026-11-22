"""Every open gap in V2's code is scheduled in the plan (docs/V2-gaps.md): none can be written without a stage, and
none closed can stay listed.

The code says where Forge can't do something yet: an issue, a problem or a
closed face of kind "unable"; a plan's gap; a depth the preview can't find;
a field the check compiler gives no check of its own and nothing else holds;
a count the oracle doesn't make. Each such place is found here by reading the
code, and each function holding any must be a row of the register, with how
many it holds and the stage that closes them. Forge V2 is released with the
register empty but for its stated design bounds (stage 9).
"""

from __future__ import annotations

import ast
import re
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "V2-gaps.md"
#: The packages whose gaps are listed: the spec, the judge, the planner, the kernel and the commands.
PACKAGES = ("forge_spec", "forge_checks", "forge_plan", "forge_occ", "forge_cli")
#: What raises or records a plan's gap, or a depth the preview can't find.
_GAPS = frozenset({"Gap", "GapError", "HollowGapError", "_UnresolvedError"})
#: A register row's place: `module:function` (n).
_ROW = re.compile(r"`(forge_\w+/[\w/]+\.py):(\w+)` \((\d+)\)")
#: A stage of the plan a row may name as closing it.
_STAGE = re.compile(r"4b\.0[cd]\d?|4b\.\d{1,2}|stage [5-9]|section 9|V2-stage4b\.md 3\.1|as each cause")


def _sites(tree: ast.AST) -> list[tuple[str, int]]:
    """Each place in a module that says Forge can't do something yet: (its function, its line)."""
    owner: dict[int, str] = {}
    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(function):
                owner[id(node)] = function.name  # walked outside in: the innermost function is the owner
    return [(owner.get(id(node), "-"), getattr(node, "lineno", 0)) for node in ast.walk(tree) if _is_gap(node)]


def _is_gap(node: ast.AST) -> bool:
    """Whether a node says Forge can't do something yet (see the module)."""
    if isinstance(node, ast.Call):
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        first = [a.value for a in node.args[:3] if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        unable = name in ("issue", "close", "add", "SpecProblem") and "unable" in first
        unheld = (name == "skip" and len(node.args) < 4 and not any(k.arg == "held_by" for k in node.keywords)
                  and "Buried" not in ast.dump(node))  # fmt: skip
        return unable or name in _GAPS or unheld
    if isinstance(node, ast.Return):
        value = node.value
        return (isinstance(value, ast.Tuple) and bool(value.elts) and isinstance(value.elts[0], ast.Constant)
                and value.elts[0].value == "unable")  # fmt: skip
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and "not counted yet" in node.value


def code_gaps() -> Counter[str]:
    """How many gap sites each function of V2's code holds, by `module:function`."""
    found: Counter[str] = Counter()
    for package in PACKAGES:
        for path in sorted((ROOT / "packages" / package).rglob("*.py")):
            module = path.relative_to(ROOT / "packages").as_posix()
            for function, _ in _sites(ast.parse(path.read_text(encoding="utf-8"))):
                found[f"{module}:{function}"] += 1
    return found


def register() -> dict[str, tuple[int, str]]:
    """The register's rows: each `module:function`, how many gaps it says it holds, and the row's text."""
    rows: dict[str, tuple[int, str]] = {}
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        for module, function, count in _ROW.findall(line):
            rows[f"{module}:{function}"] = (int(count), line)
    return rows


class EveryGapIsScheduled(unittest.TestCase):
    def test_every_gap_in_the_code_is_in_the_register(self) -> None:
        listed = register()
        for where, count in sorted(code_gaps().items()):
            with self.subTest(where=where):
                self.assertIn(where, listed, f"{where} says Forge can't do something yet: list it in "
                              "docs/V2-gaps.md with the stage that closes it")  # fmt: skip
                self.assertEqual(listed[where][0], count, f"{where} holds {count} gap site(s): say so in the register")

    def test_no_closed_gap_stays_listed(self) -> None:
        found = code_gaps()
        for where in register():
            with self.subTest(where=where):
                self.assertIn(where, found, f"{where} holds no gap now: take its row out of docs/V2-gaps.md")

    def test_each_row_names_the_stage_that_closes_it(self) -> None:
        for where, (_, line) in register().items():
            closed_in = line.rstrip(" |").rsplit("|", 1)[-1]
            with self.subTest(where=where):
                self.assertRegex(closed_in, _STAGE, f"{where}: name the stage of the plan that closes it")

    def test_the_scan_finds_what_it_is_meant_to(self) -> None:
        """A gap of each kind is found, and what isn't one (a pointer to the draft's own "unable" list, a field held
        by face accounting) isn't."""
        source = '''
def a(layout, at):
    layout.issue("unable", at, "Forge doesn't do this yet")
def b(layout, key):
    layout.close(key, "side", "unable", "nor this")
def c(c, item):
    c.skip(item, "length", "it has no flat ends")
    c.skip(item, "depth", "buried", "face accounting")
    c.skip(item, "depth", Buried("its top is nowhere on the part's surface"))
def d():
    raise GapError("a thing isn't compiled yet")
def e(n):
    return pointer("unable", n)
def f():
    return ("unable", "a pocket's edges")
'''
        self.assertEqual(Counter(f for f, _ in _sites(ast.parse(source))), Counter({"a": 1, "b": 1, "c": 1, "d": 1,
                                                                                    "f": 1}))  # fmt: skip


if __name__ == "__main__":
    unittest.main()
