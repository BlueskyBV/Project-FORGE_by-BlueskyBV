"""The reserved methods and slots (V2-stage4b-0b.md, 3 and 4): each named, owned and reserved for the step that fills it.

The design's two tables are the record: each kind's reserved methods, by
role (section 3), and item 6's slots, each with its owner, judge and the
name it is reserved as (section 4). The code is held to them both ways:
every row is reserved where it says, for the step it says, and nothing is
reserved that no row names. A step that fills a method removes its row.
"""

from __future__ import annotations

import ast
import importlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "docs" / "V2-stage4b-0b.md"
PACKAGES = ROOT / "packages"

#: A role named in section 3's table: its registry's module, the registry and its protocol.
ROLES = {
    "solve": ("forge_spec.items.solve", "SOLVE", "SolveKind"),
    "views": ("forge_spec.items.views", "VIEWS", "ViewKind"),
    "checks": ("forge_spec.items.checks", "SPEC_CHECKS", "SpecCheckKind"),
    "words": ("forge_spec.items.words", "WORDS", "WordsKind"),
    "plan": ("forge_plan.items.plan", "PLAN", "PlanKind"),
    "oracle": ("forge_checks.items.oracle", "ORACLE", "OracleKind"),
    "draw": ("forge_eval.items.draw", "DRAW", "DrawKind"),
    "truth": ("forge_eval.items.truth", "TRUTH", "TruthKind"),
}

#: The steps that fill what is reserved: 4b.0's and the stages after it.
STEPS = re.compile(r"^(4b\.0c|4b\.0d[1-4]|4b\.1[0-8]|4b\.[1-9]|stage [5-9])$")


def _table(heading: str) -> list[list[str]]:
    """The rows of the first table after ``heading`` in the design, each cell's text."""
    text = DESIGN.read_text(encoding="utf-8")
    at = text.index(heading)
    rows: list[list[str]] = []
    started = False
    for line in text[at:].splitlines():
        if line.startswith("|"):
            started = True
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif started:
            break
    return rows[2:]  # past the header and its rule


def _names(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def methods() -> list[tuple[str, str, str]]:
    """Section 3's table: (method, the step that fills it, role) for each role a row names."""
    found = []
    for method, _item, step, roles in _table("**The reserved methods, named at step 6"):
        (name,) = _names(method)
        found += [(name, step, role) for role in _names(roles)]
    return found


def slots() -> list[tuple[str, str, str, str]]:
    """Section 4's table: (slot, module, Class.method, the step that fills it)."""
    found = []
    for slot, _owner, _judge, reserved_as, step in _table("| Slot | Owner (layer) |"):
        (name,) = _names(reserved_as)
        module, member = name.split(":")
        found.append((slot, module, member, step))
    return found


def reserved_in_source() -> set[tuple[str, str, str, str]]:
    """Every ``@reserved(step)`` in the packages: (module, class, method, step)."""
    found = set()
    for path in sorted(PACKAGES.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = ".".join(path.relative_to(PACKAGES).with_suffix("").parts)
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for fn in cls.body:
                if not isinstance(fn, ast.FunctionDef):
                    continue
                for d in fn.decorator_list:
                    if (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "reserved"
                            and d.args and isinstance(d.args[0], ast.Constant)):  # fmt: skip
                        found.add((module, cls.name, fn.name, str(d.args[0].value)))
    return found


def expected() -> set[tuple[str, str, str, str]]:
    """What the two tables say is reserved, as :func:`reserved_in_source` finds it."""
    want = set()
    for method, step, role in methods():
        module, _, protocol = ROLES[role]
        want.add((f"{module}.protocol", protocol, method, step))
    for _slot, module, member, step in slots():
        cls, method = member.split(".")
        want.add((module, cls, method, step))
    return want


class TheTablesAreTheDesigns(unittest.TestCase):
    def test_both_tables_are_read(self) -> None:
        self.assertEqual(len(slots()), 8)  # item 6's eight slots
        self.assertEqual(len({m for m, _, _ in methods()}), 13)
        for method, step, role in methods():
            with self.subTest(method=method, role=role):
                self.assertIn(role, ROLES)
                self.assertRegex(step, STEPS)
        for slot, _, _, step in slots():
            with self.subTest(slot=slot):
                self.assertRegex(step, STEPS)

    def test_a_method_is_reserved_once_per_role(self) -> None:
        pairs = [(m, r) for m, _, r in methods()]
        self.assertEqual(len(pairs), len(set(pairs)))


class WhatIsReservedIsWhatTheTablesName(unittest.TestCase):
    def test_both_ways(self) -> None:
        found, want = reserved_in_source(), expected()
        self.assertEqual(
            sorted(want - found), [], "named in the design, not reserved in the code"
        )
        self.assertEqual(
            sorted(found - want), [], "reserved in the code, named in no table"
        )

    def test_every_kind_s_entry_has_its_role_s_reserved_methods_unfilled(self) -> None:
        from forge_spec.schema import KINDS

        per_role: dict[str, set[tuple[str, str]]] = {role: set() for role in ROLES}
        for method, step, role in methods():
            per_role[role].add((method, step))
        for _slot, module, member, step in slots():
            for role, (where, _, protocol) in ROLES.items():
                if module == f"{where}.protocol" and member.split(".")[0] == protocol:
                    per_role[role].add((member.split(".")[1], step))
        for role, (module, name, _) in ROLES.items():
            registry = getattr(importlib.import_module(module), name)
            with self.subTest(role=role):
                self.assertEqual(
                    sorted(registry.reserved()),
                    sorted(
                        (kind, method, step)
                        for kind in KINDS
                        for method, step in per_role[role]
                    ),
                )

    def test_each_slot_is_its_owner_s_and_says_what_fills_it(self) -> None:
        from forge_registry import NotYetError, reserved_in

        for slot, module, member, step in slots():
            cls_name, method = member.split(".")
            with self.subTest(slot=slot):
                cls = getattr(importlib.import_module(module), cls_name)
                self.assertIn((method, step), reserved_in(cls))
                with self.assertRaisesRegex(NotYetError, re.escape(step)):
                    getattr(cls(), method)(*([None] * _arity(cls, method)))


def _arity(cls: type, method: str) -> int:
    import inspect

    return len(inspect.signature(getattr(cls, method)).parameters) - 1


class ReservedMethodsRefuseToRun(unittest.TestCase):
    def test_a_role_s_reserved_method_names_the_step(self) -> None:
        from forge_registry import NotYetError
        from forge_spec.items.solve import SOLVE

        with self.assertRaisesRegex(
            NotYetError, r"\.acts_on is reserved, not yet filled: 4b\.0d2"
        ):
            SOLVE["block"].acts_on(None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
