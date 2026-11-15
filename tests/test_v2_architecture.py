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

PACKAGES = Path(__file__).resolve().parent.parent / "packages"

L0_STDLIB = {"forge_units", "forge_expr", "forge_ir", "forge_evidence",
             "forge_analysis", "forge_plan"}  # fmt: skip
L0_NUMPY = {"forge_geom", "forge_kernel", "forge_spec", "forge_checks"}
L1 = {"forge_occ", "forge_print", "forge_fonts", "forge_sandbox", "forge_models"}
L2 = {"forge_roles", "forge_designer"}
L3 = {"forge_orchestrator", "forge_cli", "forge_memory", "forge_eval"}
LAYER = {**dict.fromkeys(L0_STDLIB | L0_NUMPY, 0), **dict.fromkeys(L1, 1),
         **dict.fromkeys(L2, 2), **dict.fromkeys(L3, 3)}  # fmt: skip

#: V2 packages these rules apply to. V1's packages keep their own ADR-0002 test
#: and are brought under these rules as V2 replaces them.
V2_PACKAGES = {"forge_spec", "forge_checks", "forge_plan", "forge_occ", "forge_print",
               "forge_fonts", "forge_sandbox", "forge_designer", "forge_memory",
               "forge_eval"}  # fmt: skip

FORBIDDEN = {
    "forge_checks": {"forge_plan", "forge_kernel", "forge_occ", "forge_designer"},
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
#: the judge may never see. A key is a package or one module of it.
R2 = {
    "forge_checks": {
        "forge_spec.placement", "forge_spec.geometry", "forge_spec.outline", "forge_spec.letters", "forge_plan",
        "forge_kernel", "forge_occ", "forge_designer", "forge_geom", "forge_eval",
    },
    "forge_eval/truth.py": {
        "forge_spec.placement", "forge_spec.geometry", "forge_spec.outline", "forge_spec.letters", "forge_checks",
        "forge_geom", "forge_kernel",
    },
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


if __name__ == "__main__":
    unittest.main()
