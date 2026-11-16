"""V2's dependency rules, checked on the source (V2-architecture.md, section 2).

The rules that keep Forge's judgement independent of the things it judges are
only as good as their enforcement, so they are enforced here, on every change:

- the trust core (L0) imports only the standard library, NumPy and other L0
  packages: no model, no CAD library (ADR-0002, rule R11);
- the checks never import the compiler, a kernel, the designer, the second
  kernel's shape code, the evaluation's shape model, or the solver's placement
  and geometry; the generator's shape model imports none of the other two
  placements; and the compiler never imports the checks, a kernel or the
  evaluation (rule R2). These
  rules are by dotted module, a name imported from a package counts as the
  module that defines it, and dynamic imports are refused where they apply;
- a package imports only from its own layer or below;
- nothing but the models layer reads the environment, where the key is.

A rule for a package that doesn't exist yet is checked as soon as it does.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from typing import ClassVar

PACKAGES = Path(__file__).resolve().parent.parent / "packages"

L0_STDLIB = {"forge_units", "forge_expr", "forge_ir", "forge_evidence",
             "forge_analysis", "forge_plan", "forge_registry"}  # fmt: skip
L0_NUMPY = {"forge_geom", "forge_kernel", "forge_spec", "forge_checks", "forge_numeric"}
L1 = {
    "forge_occ",
    "forge_print",
    "forge_fonts",
    "forge_sandbox",
    "forge_models",
    "forge_solvers",
}
L2 = {"forge_roles", "forge_designer"}
L3 = {"forge_orchestrator", "forge_cli", "forge_memory", "forge_eval"}
LAYER = {**dict.fromkeys(L0_STDLIB | L0_NUMPY, 0), **dict.fromkeys(L1, 1),
         **dict.fromkeys(L2, 2), **dict.fromkeys(L3, 3)}  # fmt: skip

#: V2 packages these rules apply to. V1's packages keep their own ADR-0002 test
#: and are brought under these rules as V2 replaces them.
V2_PACKAGES = {"forge_spec", "forge_checks", "forge_plan", "forge_occ", "forge_print",
               "forge_fonts", "forge_sandbox", "forge_designer", "forge_memory",
               "forge_eval", "forge_registry", "forge_solvers", "forge_numeric"}  # fmt: skip

FORBIDDEN = {
    "forge_checks": {"forge_plan", "forge_kernel", "forge_occ", "forge_designer"},
    # The spec is read by the other programs and reads none of them (V2-stage4b-0b.md, 2).
    "forge_spec": {"forge_plan", "forge_checks", "forge_eval"},
    # The one dispatch mechanism is a leaf: it knows no program (V2-stage4b-0b.md, 3).
    "forge_registry": {
        "forge_spec",
        "forge_plan",
        "forge_checks",
        "forge_eval",
        "forge_occ",
    },
    # The compiler writes from the spec alone: never the judge, a kernel or the evaluation's model (V2-stage4.md, 3).
    "forge_plan": {
        "forge_checks",
        "forge_eval",
        "forge_occ",
        "forge_kernel",
        "forge_geom",
    },
}

#: Rule R2 by dotted module (docs/V2-stage2.md, section 9): what each part of
#: the judge may never see. A key is a package, one module of it, or one of its
#: role subpackages (V2-stage4b-0b.md, 2: the fences follow the roles).
_SOLVER = ("forge_spec.placement", "forge_spec.geometry", "forge_spec.outline", "forge_spec.letters",
           "forge_spec.items.solve")  # fmt: skip
_JUDGE = {
    *_SOLVER,
    "forge_plan",
    "forge_kernel",
    "forge_occ",
    "forge_designer",
    "forge_geom",
    "forge_eval",
}
_TRUTH = {*_SOLVER, "forge_checks", "forge_geom", "forge_kernel"}
R2 = {
    "forge_checks": _JUDGE,
    # The judge's own roles keep today's directions: compile may use oracle, oracle may use place.
    "forge_checks/items/oracle": _JUDGE | {"forge_checks.items.compile", "forge_checks.compiler"},
    "forge_checks/items/place": _JUDGE | {"forge_checks.items.oracle", "forge_checks.oracle",
                                          "forge_checks.items.compile", "forge_checks.compiler"},
    "forge_eval/truth.py": _TRUTH,
    # The generator's shape model never sees its grading or the solver.
    "forge_eval/items/truth": _TRUTH | {"forge_eval.items.grade", "forge_eval.spec_grade"},
}  # fmt: skip


def imports_of(package: str) -> dict[str, set[str]]:
    """Top-level module names imported by each file of ``package``."""
    found: dict[str, set[str]] = {}
    for path in sorted((PACKAGES / package).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        found[str(path.relative_to(PACKAGES))] = names
    return found


def present(packages: set[str]) -> list[str]:
    return sorted(p for p in packages if (PACKAGES / p).is_dir())


class TheTrustCoreDependsOnNoModelAndNoCadLibrary(unittest.TestCase):
    def test_l0_imports(self) -> None:
        for package in present(V2_PACKAGES & (L0_STDLIB | L0_NUMPY)):
            allowed = set(sys.stdlib_module_names) | L0_STDLIB | L0_NUMPY
            if package in L0_NUMPY:
                allowed.add("numpy")
            for path, names in imports_of(package).items():
                self.assertEqual(names - allowed, set(), path)

    def test_stdlib_only_packages_import_no_numpy(self) -> None:
        for package in present(V2_PACKAGES & L0_STDLIB):
            for path, names in imports_of(package).items():
                self.assertNotIn("numpy", names, path)


class ChecksCantSeeTheDesign(unittest.TestCase):
    def test_forbidden_imports(self) -> None:
        for package, forbidden in FORBIDDEN.items():
            if not (PACKAGES / package).is_dir():
                continue
            for path, names in imports_of(package).items():
                self.assertEqual(names & forbidden, set(), path)


def _module_file(dotted: str) -> Path | None:
    """The file a dotted module name is: a module, or a package's ``__init__``."""
    base = PACKAGES.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _defining_module(
    package: str, name: str, seen: frozenset[str] = frozenset()
) -> str:
    """Where a name imported from ``package`` really comes from, following its ``__init__``."""
    init = PACKAGES.joinpath(*package.split(".")) / "__init__.py"
    if not init.is_file() or package in seen:
        return package
    tree = ast.parse(init.read_text(encoding="utf-8"), filename=str(init))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and any(
            (a.asname or a.name) == name for a in node.names
        ):
            source = _absolute(node, package, is_package=True)
            original = next(a.name for a in node.names if (a.asname or a.name) == name)
            if _module_file(f"{source}.{original}") is not None:
                return f"{source}.{original}"
            return _defining_module(source, original, seen | {package})
    return package


def _absolute(node: ast.ImportFrom, module: str, *, is_package: bool) -> str:
    """The absolute module an import-from names, relative ones resolved."""
    if not node.level:
        return node.module or ""
    parts = module.split(".")
    keep = len(parts) - node.level + (1 if is_package else 0)
    base = ".".join(parts[:keep])
    return f"{base}.{node.module}" if node.module else base


def dotted_imports(path: Path) -> set[str]:
    """Every module ``path`` imports, by dotted name, names from packages traced to their modules."""
    relative = path.relative_to(PACKAGES).with_suffix("")
    is_package = relative.name == "__init__"
    module = ".".join(relative.parent.parts if is_package else relative.parts)
    return imports_in(path.read_text(encoding="utf-8"), module, is_package=is_package)


def imports_in(source: str, module: str, *, is_package: bool = False) -> set[str]:
    """:func:`dotted_imports` for source text said to be ``module``."""
    tree = ast.parse(source, filename=module)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(node, module, is_package=is_package)
            found.add(base)
            for alias in node.names:
                sub = f"{base}.{alias.name}"
                found.add(
                    sub if _module_file(sub) else _defining_module(base, alias.name)
                )
    return found


def dynamic_imports(path: Path) -> list[str]:
    """Every use of ``importlib`` or ``__import__``: a way round any import rule."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        elif isinstance(node, ast.Name):
            names = [node.id]
        if any(n.split(".")[0] in ("importlib", "__import__") for n in names):
            found.append(f"{path.name}:{getattr(node, 'lineno', 0)}")
    return found


def _files_of(key: str) -> list[Path]:
    target = PACKAGES / key
    if target.is_file():
        return [target]
    return sorted(target.rglob("*.py")) if target.is_dir() else []


def _breaks(module: str, forbidden: set[str]) -> bool:
    return any(module == f or module.startswith(f + ".") for f in forbidden)


class TheJudgeCantSeeWhatItJudges(unittest.TestCase):
    """Rule R2, by dotted module and by symbol, with no way round it."""

    def test_r2_by_dotted_module(self) -> None:
        for key, forbidden in R2.items():
            for path in _files_of(key):
                broken = sorted(
                    m for m in dotted_imports(path) if _breaks(m, forbidden)
                )
                self.assertEqual(broken, [], path)

    def test_no_dynamic_imports_where_r2_applies(self) -> None:
        for key in R2:
            for path in _files_of(key):
                self.assertEqual(dynamic_imports(path), [], path)

    def test_a_name_from_a_package_counts_as_its_module(self) -> None:
        # forge_spec re-exports placement's solve(); importing it from forge_spec
        # is importing forge_spec.placement.
        self.assertEqual(
            _defining_module("forge_spec", "solve"), "forge_spec.placement"
        )
        found = imports_in(
            "from forge_spec import solve\nfrom . import mesh\n", "forge_checks.probe"
        )
        self.assertIn("forge_spec.placement", found)
        self.assertIn("forge_checks.mesh", found)
        self.assertTrue(_breaks("forge_spec.placement", R2["forge_checks"]))

    def test_the_rules_watch_packages_that_exist(self) -> None:
        self.assertTrue(
            _files_of("forge_checks"), "forge_checks is there to be checked"
        )


class LayersImportOnlyDownwards(unittest.TestCase):
    def test_layers(self) -> None:
        for package in present(V2_PACKAGES):
            own = LAYER[package]
            for path, names in imports_of(package).items():
                upward = {n for n in names if n in LAYER and LAYER[n] > own}
                self.assertEqual(upward, set(), path)

    def test_every_v2_package_has_a_layer(self) -> None:
        for package in present(V2_PACKAGES):
            self.assertIn(package, LAYER)


#: V2's modules in packages V1 still owns: held to the same rule on secrets.
V2_MODULES = ("forge_cli/spec.py", "forge_cli/spec_page.py", "forge_cli/eval_spec.py", "forge_cli/build.py",
              "forge_cli/seal.py",
              "forge_roles/spec_writer.py", "forge_cli/doctor.py", "forge_ir/v2.py", "forge_kernel/agreement.py",
              "forge_kernel/implicit_view.py")  # fmt: skip


class V2ModulesInTheTrustCoreKeepItsRules(unittest.TestCase):
    """ForgeIR v2 and the second kernel's agreement entries and view live in V1's L0 packages: held to L0's imports."""

    def test_their_imports(self) -> None:
        for module in V2_MODULES:
            package = module.split("/")[0]
            if package not in L0_STDLIB | L0_NUMPY:
                continue
            path = PACKAGES / module
            self.assertTrue(path.is_file(), module)
            allowed = set(sys.stdlib_module_names) | L0_STDLIB | L0_NUMPY
            if package in L0_NUMPY:
                allowed.add("numpy")
            names = {m.split(".")[0] for m in dotted_imports(path)}
            self.assertEqual(names - allowed, set(), module)
            self.assertEqual(dynamic_imports(path), [], module)


def reads_the_environment(path: Path) -> list[str]:
    """Every place a file reads the process's environment: os.environ, os.getenv, os.environb."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        name = (
            node.attr
            if isinstance(node, ast.Attribute)
            else node.id
            if isinstance(node, ast.Name)
            else ""
        )
        if name in ("environ", "environb", "getenv", "getenvb"):
            found.append(f"{path.name}:{getattr(node, 'lineno', 0)}")
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            found += [
                f"{path.name}:{node.lineno}"
                for a in node.names
                if a.name in ("environ", "getenv")
            ]
    return found


class NothingButTheModelsLayerReadsAKey(unittest.TestCase):
    def test_no_v2_code_reads_the_environment(self) -> None:
        # The key comes from ANTHROPIC_API_KEY, read by forge_models alone:
        # no secret can reach a run's records through anything else.
        files = [
            f
            for p in present(V2_PACKAGES)
            for f in sorted((PACKAGES / p).rglob("*.py"))
        ]
        files += [PACKAGES / m for m in V2_MODULES if (PACKAGES / m).exists()]
        self.assertTrue(files)
        for path in files:
            self.assertEqual(reads_the_environment(path), [], path)


#: What turns a spec's values into geometry: the solver, the compiler, the judge and the generator's model.
MAKERS = (
    "forge_spec/placement.py",
    "forge_spec/items/solve",
    "forge_spec/geometry.py",
    "forge_plan",
    "forge_checks",
    "forge_eval",
)


def nominal_reads(path: Path) -> list[str]:
    """Every place a file reads a value's nominal: ``.nominal`` (but a check's own, ``self.nominal``), ``.nominal_in``, or ``.quantity`` other than its unit."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        own = (
            node.attr == "nominal"
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        )
        parent = parents.get(node)
        unit = (
            node.attr == "quantity"
            and isinstance(parent, ast.Attribute)
            and parent.attr == "unit"
        )
        if (node.attr in ("nominal", "nominal_in") and not own) or (
            node.attr == "quantity" and not unit
        ):
            found.append((node.lineno, f"{path.name}:{node.lineno}"))
    return [where for _, where in sorted(found)]


class GeometryIsMadeAtTheMiddleOfEachTolerance(unittest.TestCase):
    """A part is made to each value's middle (sizes.md; V2-stage4.md, 9.6): what makes geometry never reads the nominal."""

    def test_no_maker_reads_a_nominal(self) -> None:
        files = []
        for maker in MAKERS:
            path = PACKAGES / maker
            files += sorted(path.rglob("*.py")) if path.is_dir() else [path]
        self.assertGreater(len(files), 20)
        for path in files:
            self.assertEqual(nominal_reads(path), [], path)

    def test_the_rule_finds_a_nominal_read(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.py"
            path.write_text("a = v.quantity.value_in('mm')\nb = v.nominal\nc = v.nominal_in('mm')\n"
                            "d = v.quantity.unit\ne = self.nominal\n", encoding="utf-8")  # fmt: skip
            self.assertEqual(nominal_reads(path), ["bad.py:1", "bad.py:2", "bad.py:3"])


class KindsAreDispatchedThroughRegistries(unittest.TestCase):
    """The ratchet of stage 4b.0b (V2-stage4b-0b.md, 5): the sites that dispatch on a kind outside the registries only fall."""

    def test_no_file_has_more_sites_than_recorded(self) -> None:
        import json

        from v2_kind_sites import counts

        recorded = json.loads(
            (Path(__file__).parent / "v2_kind_sites.json").read_text(encoding="utf-8")
        )["counts"]
        for path, found in counts().items():
            with self.subTest(path=path):
                self.assertLessEqual(
                    found,
                    recorded.get(path, 0),
                    f"{path}: more kind dispatch than recorded",
                )

    def test_the_sites_left_only_fall_in_all(self) -> None:
        # A move may take a site from one file to a role's shared helper (a pattern's mode, until step 5): never more in all.
        import json

        from v2_kind_sites import counts

        recorded = json.loads(
            (Path(__file__).parent / "v2_kind_sites.json").read_text(encoding="utf-8")
        )["counts"]
        self.assertLessEqual(sum(counts().values()), sum(recorded.values()))
        self.assertLessEqual(
            sum(recorded.values()), 734
        )  # step 0's count, 14 November 2026

    def test_the_rule_finds_each_form(self) -> None:
        import tempfile

        from v2_kind_sites import sites

        source = (
            "from x import Category\n"
            "_CUTS = ('hole', 'slot')\n"  # 2: a family
            "MODE = 'grid'\n"  # 3: a constant
            "def f(item, pattern):\n"
            "    if item.kind == 'hole': pass\n"  # 5: a comparison with a literal
            "    if item.kind in _CUTS: pass\n"  # 6: with a family name
            "    if pattern.kind in ('circle', 'arc'): pass\n"  # 7: a pattern mode
            "    if KINDS[item.kind].category is Category.CUT: pass\n"  # 8: a category
            "    if item.kind == other.kind: pass\n"  # not a site: no kind named
            "    if option.kind == 'note': pass\n"  # not a site: not a kind
            "    match item.kind:\n"
            "        case 'tube': pass\n"  # 11: a match
            "    return {'block': 1, 'tube': 2}[item.kind]\n"  # 13: a dispatch table
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "probe.py"
            path.write_text(source, encoding="utf-8")
            found = sorted((s.line, s.what) for s in sites([path]))
        self.assertEqual(
            found,
            [(2, "family"), (3, "constant"), (5, "comparison"), (6, "comparison"), (7, "comparison"),
             (8, "comparison"), (11, "match"), (13, "family")],
        )  # fmt: skip

    def test_a_role_s_protocol_and_modes_hold_no_kind_s_code(self) -> None:
        # Exempt from the count as a kind's module is, a protocol reads only its own kind's entry, and a pattern
        # mode's module chooses by no mode (step 7: two such tests were left in the judge's round modes).
        from v2_kind_sites import role_sites

        self.assertEqual([f"{s.path}:{s.line}: {s.what}" for s in role_sites()], [])

    def test_the_role_rule_finds_a_kind_s_code(self) -> None:
        import tempfile

        from v2_kind_sites import role_sites

        with tempfile.TemporaryDirectory() as folder:
            protocol, pattern = (
                Path(folder) / "protocol.py",
                Path(folder) / "pattern.py",
            )
            protocol.write_text(
                "class P:\n"
                "    @property\n"
                "    def cut(self):\n"
                "        return KINDS[self.key].category is Category.CUT\n"  # its own entry: allowed
                "    def tool(self, item):\n"
                "        if KINDS[item.kind].category is Category.CUT:\n"  # 6: another item's
                "            return 1\n"
                "        return item.kind == 'hole'\n",  # 8: a kind
                encoding="utf-8",
            )
            pattern.write_text(
                "def f(self, pattern):\n    return pattern.kind == 'arc'\n",
                encoding="utf-8",
            )
            found = [(s.path, s.line) for s in role_sites([protocol, pattern])]
        self.assertEqual(
            found, [("protocol.py", 6), ("protocol.py", 8), ("pattern.py", 2)]
        )

    def test_a_kind_module_names_only_its_own_kind(self) -> None:
        from v2_kind_sites import item_modules, strangers

        self.assertGreater(len(item_modules()), 200)
        self.assertEqual([f"{s.path}:{s.line}: {s.what}" for s in strangers()], [])

    def test_the_own_kind_rule_finds_a_stranger(self) -> None:
        import tempfile

        from v2_kind_sites import strangers

        with tempfile.TemporaryDirectory() as folder:
            hole, protocol = Path(folder) / "hole.py", Path(folder) / "protocol.py"
            hole.write_text(
                "KEY = 'hole'\nif target.kind == 'tube': pass\n", encoding="utf-8"
            )
            protocol.write_text("WORDS = {'grid': 1}\nX = 'block'\n", encoding="utf-8")
            found = [(s.path, s.line, s.what) for s in strangers([hole, protocol])]
        self.assertEqual(
            found, [("hole.py", 2, "names tube"), ("protocol.py", 2, "names block")]
        )


class EveryRoleHasAnEntryForEveryKind(unittest.TestCase):
    """The registries of stage 4b.0b (V2-stage4b-0b.md, 3): one per program and role, total, in KINDS' order."""

    ROLES = (
        ("forge_plan.items.plan", "PLAN", "PlanKind"),
        ("forge_checks.items.oracle", "ORACLE", "OracleKind"),
        ("forge_checks.items.place", "PLACE", "PlaceKind"),
        ("forge_checks.items.compile", "COMPILE", "CompileKind"),
        ("forge_spec.items.solve", "SOLVE", "SolveKind"),
        ("forge_spec.items.views", "VIEWS", "ViewKind"),
        ("forge_spec.items.compare", "COMPARE", "CompareKind"),
        ("forge_spec.items.checks", "SPEC_CHECKS", "SpecCheckKind"),
        ("forge_spec.items.words", "WORDS", "WordsKind"),
        ("forge_eval.items.draw", "DRAW", "DrawKind"),
        ("forge_eval.items.brief", "BRIEF", "BriefKind"),
        ("forge_eval.items.truth", "TRUTH", "TruthKind"),
        ("forge_eval.items.grade", "GRADE", "GradeKind"),
    )

    def test_each_registry_is_total_and_in_the_kinds_order(self) -> None:
        import importlib

        from forge_spec.schema import KINDS

        for module, name, protocol in self.ROLES:
            with self.subTest(role=module):
                found = importlib.import_module(module)
                registry = getattr(found, name)
                self.assertEqual(registry.keys(), tuple(KINDS))
                for key, entry in registry.items():
                    self.assertIsInstance(entry, getattr(found, protocol))
                    self.assertEqual(entry.key, key)
                    self.assertEqual(type(entry).__module__, f"{module}.{key}")

    def test_every_role_has_its_own_module_per_kind(self) -> None:
        from forge_spec.schema import KINDS

        for module, _, _ in self.ROLES:
            folder = PACKAGES.joinpath(*module.split("."))
            with self.subTest(role=module):
                # Besides its kinds: its protocol, its pattern modes, and its shared helpers (``_common`` and
                # the like, each a leaf: a name starting with an underscore).
                have = {
                    p.stem for p in folder.glob("*.py") if not p.stem.startswith("_")
                } - {"protocol", "pattern"}
                self.assertEqual(have, set(KINDS))

    def test_a_role_s_shared_helpers_are_leaves(self) -> None:
        # A role's shared helpers (``_common`` and the like) are imported by its kinds and its program, and
        # import neither them nor its registry when imported (a function may ask the registry when called).
        import ast

        from forge_spec.schema import KINDS

        checked = 0
        for module, _, _ in self.ROLES:
            folder = PACKAGES.joinpath(*module.split("."))
            others = {module, self.PROGRAMS[module]} | {
                f"{module}.{kind}" for kind in KINDS
            }
            for path in sorted(folder.glob("_*.py")):
                if path.stem == "__init__":
                    continue
                checked += 1
                for node in ast.parse(path.read_text(encoding="utf-8")).body:
                    names = (
                        [node.module or ""]
                        if isinstance(node, ast.ImportFrom)
                        else [a.name for a in node.names]
                        if isinstance(node, ast.Import)
                        else []
                    )
                    if isinstance(node, ast.ImportFrom):
                        names += [f"{node.module}.{a.name}" for a in node.names]
                    with self.subTest(leaf=f"{module}.{path.stem}", line=node.lineno):
                        self.assertFalse(set(names) & others, names)
        self.assertGreater(checked, 0)

    #: Each role's registry, and the program that asks it.
    PROGRAMS: ClassVar[dict[str, str]] = {
        "forge_plan.items.plan": "forge_plan.planner",
        "forge_checks.items.oracle": "forge_checks.oracle",
        "forge_checks.items.place": "forge_checks.place",
        "forge_checks.items.compile": "forge_checks.compiler",
        "forge_spec.items.solve": "forge_spec.placement",
        "forge_spec.items.views": "forge_spec.render_views",
        "forge_spec.items.compare": "forge_spec.compare",
        "forge_spec.items.checks": "forge_spec.checks",
        "forge_spec.items.words": "forge_spec.render",
        "forge_eval.items.draw": "forge_eval.generator",
        "forge_eval.items.brief": "forge_eval.generator",
        "forge_eval.items.truth": "forge_eval.generator",
        "forge_eval.items.grade": "forge_eval.spec_grade",
    }

    def test_a_registry_and_its_program_import_either_way_round(self) -> None:
        import subprocess

        for registry, program in self.PROGRAMS.items():
            for first, then in ((registry, program), (program, registry)):
                with self.subTest(first=first, then=then):
                    done = subprocess.run([sys.executable, "-c", f"import {first}, {then}"],
                                          cwd=PACKAGES, capture_output=True, text=True)  # fmt: skip
                    self.assertEqual(done.returncode, 0, done.stderr[-2000:])


# ----------------------------------------------------------------------
# The same numbers on every machine (ADR-0037)
# ----------------------------------------------------------------------
#: math's functions the C library computes, each rounding its own way, and CPython's own hypot, dist and
#: sumprod, whose multiply-adds in C Clang and Microsoft's ARM compiler fuse (found on a Mac and an ARM PC).
_MATH_FUNCTIONS = frozenset({
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "exp", "exp2", "expm1", "log", "log1p",
    "log2", "log10", "pow", "cbrt", "sinh", "cosh", "tanh", "asinh", "acosh", "atanh", "erf",
    "erfc", "gamma", "lgamma", "hypot", "dist", "sumprod",
})  # fmt: skip
#: NumPy's: its SIMD paths and C library (elementary functions), BLAS and LAPACK (products and
#: linear algebra), and C a compiler may fuse into multiply-adds (einsum, interp, complex numbers).
_NUMPY_FUNCTIONS = frozenset({
    "sin", "cos", "tan", "arcsin", "arccos", "arctan", "arctan2", "sinh", "cosh", "tanh",
    "arcsinh", "arccosh", "arctanh", "exp", "exp2", "expm1", "log", "log2", "log10", "log1p",
    "logaddexp", "logaddexp2", "power", "float_power", "cbrt", "hypot", "sinc", "i0", "angle",
    "dot", "vdot", "inner", "matmul", "vecdot", "matvec", "vecmat", "einsum", "tensordot",
    "convolve", "correlate", "cov", "corrcoef", "polyfit", "polyval", "roots", "interp",
    "linalg", "fft", "polynomial",
})  # fmt: skip
#: Random draws by a law other than the uniform one (which take logarithms and exponentials). NumPy's
#: generators are reached only through ``fv.Draws`` (their uniform draws fuse a multiply-add in C).
_RANDOM_LAWS = frozenset({
    "normal", "standard_normal", "gauss", "normalvariate", "lognormvariate", "lognormal",
    "expovariate", "exponential", "standard_exponential", "vonmisesvariate", "vonmises",
    "gammavariate", "gamma", "standard_gamma", "betavariate", "beta", "paretovariate", "pareto",
    "weibullvariate", "weibull", "binomialvariate", "binomial", "poisson", "laplace", "logistic",
    "rayleigh", "triangular", "chisquare", "standard_t", "standard_cauchy", "wald",
})  # fmt: skip


def _int_literal(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _int_literal(node.operand)
        return None if inner is None else -inner
    return None


def _exact_power(node: ast.BinOp) -> bool:
    """``**`` the machine can't round: whole numbers to a power 0 or more, or 2 to a whole power (exact)."""
    base, power = _int_literal(node.left), _int_literal(node.right)
    if power is None:
        return False
    if base is not None and power >= 0:
        return True
    return (
        isinstance(node.left, ast.Constant)
        and node.left.value in (2, 2.0)
        and type(node.left.value) in (int, float)
    )


def numeric_sites(source: str) -> list[str]:
    """Where ``source`` computes a number another machine may round otherwise ("line: what"), forge_numeric's to compute instead."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "math" and node.attr in _MATH_FUNCTIONS:
                found.append(f"{line}: math.{node.attr}")
            if node.value.id in ("np", "numpy") and node.attr in _NUMPY_FUNCTIONS:
                found.append(f"{line}: np.{node.attr}")
            if node.value.id in ("np", "numpy") and node.attr == "random":
                found.append(f"{line}: np.random (fv.Draws instead)")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top, _, rest = alias.name.partition(".")
                if top in ("cmath", "statistics") or (
                    top == "numpy"
                    and rest.split(".")[0] in {*_NUMPY_FUNCTIONS, "random"}
                ):
                    found.append(f"{line}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            top, _, rest = node.module.partition(".")
            names = {alias.name for alias in node.names}
            if (
                top in ("cmath", "statistics")
                or (top == "math" and names & _MATH_FUNCTIONS)
                or (
                    top == "numpy"
                    and (
                        rest.split(".")[0] in _NUMPY_FUNCTIONS
                        or (not rest and names & {*_NUMPY_FUNCTIONS, "random"})
                    )
                )
            ):
                found.append(f"{line}: from {node.module} import ...")
        elif isinstance(node, ast.BinOp | ast.AugAssign) and isinstance(
            node.op, ast.MatMult
        ):
            found.append(f"{line}: @")
        elif (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Pow)
            and not _exact_power(node)
        ):
            found.append(f"{line}: **")
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Pow):
            found.append(f"{line}: **=")
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == "pow":
                found.append(f"{line}: pow()")
            ours = (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id in ("fs", "fv")
            )
            if (
                isinstance(f, ast.Attribute)
                and not ours
                and (f.attr == "dot" or f.attr in _RANDOM_LAWS)
            ):
                found.append(f"{line}: .{f.attr}()")
        elif isinstance(node, ast.Constant) and isinstance(node.value, complex):
            found.append(f"{line}: a complex number")
    return found


def _numeric_scope() -> list[Path]:
    files = [path for package in present(V2_PACKAGES - {"forge_numeric"})
             for path in sorted((PACKAGES / package).rglob("*.py"))]  # fmt: skip
    return files + [PACKAGES / module for module in V2_MODULES]


class EveryNumberIsTheSameOnEveryMachine(unittest.TestCase):
    """V2 computes nothing a machine may round its own way: elementary functions, products and linear algebra through forge_numeric (ADR-0037)."""

    def test_no_v2_code_computes_what_forge_numeric_computes(self) -> None:
        for path in _numeric_scope():
            with self.subTest(path=str(path.relative_to(PACKAGES))):
                self.assertEqual(numeric_sites(path.read_text(encoding="utf-8")), [])

    def test_the_rule_finds_each_form(self) -> None:
        caught = """
import cmath
from math import atan2
from numpy.linalg import solve
x = math.sin(a) + np.arctan2(b, c) + np.linalg.norm(d) + np.einsum("ij,ij->i", e, e)
y = a @ b
y @= b
z = w ** 0.5 + w ** 2 + 10 ** -3 + w ** n
q = pow(w, 3) + v.dot(u) + rng.normal(size=3) + random.gauss(0, 1) + 1j
f = math.log10
g = math.hypot(a, b) + math.dist(p, q)
r = np.random.default_rng(1).uniform(0, 1)
"""
        self.assertEqual(len(numeric_sites(caught)), 22, numeric_sites(caught))
        fine = """
from numpy.typing import NDArray
x = math.sqrt(a) + fs.hypot(a, b) + math.fsum(c) + np.sqrt(d) + np.sum(e) + np.cross(f, g)
y = fs.sin(a) + fv.dot(b, c) + fv.matmul(b, c) + fv.normal(rng, size=3) + fv.Draws(1).uniform(0, 1)
z = 2 ** 10 + 2.0 ** -53 + 3 ** 2 + w * w
"""
        self.assertEqual(numeric_sites(fine), [])

    def test_the_scalar_side_needs_no_numpy(self) -> None:
        """Packages of the standard library alone may use ``forge_numeric.scalar``: it (and what it imports) imports no NumPy."""
        for module in ("__init__.py", "scalar.py", "_bits.py"):
            names = {
                m.split(".")[0]
                for m in dotted_imports(PACKAGES / "forge_numeric" / module)
            }
            self.assertEqual(
                names - set(sys.stdlib_module_names) - {"forge_numeric"}, set(), module
            )
        for package in present(V2_PACKAGES & L0_STDLIB):
            for path in sorted((PACKAGES / package).rglob("*.py")):
                for name in dotted_imports(path):
                    if name.split(".")[0] == "forge_numeric":
                        self.assertIn(
                            name, {"forge_numeric", "forge_numeric.scalar"}, path
                        )


if __name__ == "__main__":
    unittest.main()
