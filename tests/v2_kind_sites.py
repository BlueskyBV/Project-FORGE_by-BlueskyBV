"""Where V2's code dispatches on an item's kind: the sites stage 4b.0b moves behind registries (V2-stage4b-0b.md, 5).

A site is one place that chooses what to do by an item's kind, a pattern's
mode or an item's category, outside the registries, the ``items/`` role
modules (a kind's own module, its role's protocol and registry; a role's
shared helpers are held to the rule) and the draft and wire layer:

- a comparison (``==``, ``!=``, ``is``, ``is not``, ``in``, ``not in``) with a
  kind or mode literal, with a collection holding one, with a name bound to
  such a collection anywhere in scope, or with a ``Category`` member (a
  non-item kind that shares a kind's name, as the edit kind "text", counts
  until it is compared through its own enum);
- a lookup keyed by a kind (``table[x.kind]``, ``table.get(x.kind)``) in a
  table keyed by kind or mode literals, other than a registry;
- a ``match`` with a kind or mode literal among its cases;
- a dict, set, list or tuple display holding two or more kind or mode
  literals (a family tuple or a dispatch table), or ``dict.fromkeys`` of one;
- a ``startswith`` or ``endswith`` with a kind or mode literal;
- a ``getattr`` whose name is built from a kind;
- a module constant bound to a kind or mode literal;
- a ``Category`` member read anywhere but in a registry's key.

Packages that can't see items (``forge_occ``, ``forge_kernel``,
``forge_geom``) are outside by package. The count per file is the ratchet
(``test_v2_architecture``): it may fall, never rise, and reaches zero at
4b.0b's step 7.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "packages"

#: The packages whose modules can see items, and V2's modules in V1 packages.
SCOPE_PACKAGES = ("forge_spec", "forge_plan", "forge_checks", "forge_eval", "forge_designer",
                  "forge_memory", "forge_print", "forge_fonts", "forge_sandbox", "forge_solvers")  # fmt: skip
SCOPE_FILES = ("forge_cli/spec.py", "forge_roles/spec_writer.py")
#: The draft and wire layer: where a kind is read to parse or write an item.
EXEMPT = ("forge_spec/schema.py", "forge_spec/draft.py", "forge_spec/wire.py")
#: Lookups that are registries: a kind's own entry.
REGISTRIES = frozenset({"KINDS"})


def _literals() -> frozenset[str]:
    from forge_spec.draft import PATTERN_FIELDS
    from forge_spec.schema import KINDS

    return frozenset(KINDS) | frozenset(PATTERN_FIELDS)


@dataclass(frozen=True)
class Site:
    path: str
    line: int
    function: str
    what: str


def _is_kind_read(node: ast.AST) -> bool:
    """``x.kind``, ``x.category``, ``x["kind"]``, ``x.get("kind")``."""
    if isinstance(node, ast.Attribute) and node.attr in ("kind", "category"):
        return True
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value == "kind"
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "kind"
    )


def _is_category(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Category"
    )


class _Scan(ast.NodeVisitor):
    def __init__(
        self, path: str, literals: frozenset[str], families: frozenset[str]
    ) -> None:
        self.path = path
        self.literals = literals
        self.families = families  # module names bound to collections of literals
        self.sites: list[Site] = []
        self.function = "<module>"
        self.counted: set[int] = set()

    def _site(self, node: ast.AST, what: str) -> None:
        self.sites.append(
            Site(self.path, getattr(node, "lineno", 0), self.function, what)
        )
        for sub in ast.walk(node):
            self.counted.add(id(sub))

    def _literal(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in self.literals
        )

    def _family(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name) and node.id in self.families:
            return True
        if isinstance(node, ast.Attribute) and node.attr in self.families:
            return True
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return any(self._literal(e) for e in node.elts)
        return False

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        outer, self.function = (
            self.function,
            (
                node.name
                if self.function == "<module>"
                else f"{self.function}.{node.name}"
            ),
        )
        self.generic_visit(node)
        self.function = outer

    visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        outer, self.function = (
            self.function,
            (
                node.name
                if self.function == "<module>"
                else f"{self.function}.{node.name}"
            ),
        )
        self.generic_visit(node)
        self.function = outer

    def visit_Compare(self, node: ast.Compare) -> None:
        if id(node) not in self.counted:
            operands = [node.left, *node.comparators]
            if any(
                self._literal(o) or self._family(o) or _is_category(o) for o in operands
            ):
                self._site(node, "comparison")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if id(node) not in self.counted and _is_kind_read(node.slice):
            table = node.value
            name = (
                table.id if isinstance(table, ast.Name) else getattr(table, "attr", "")
            )
            if name not in REGISTRIES and name in self.families:
                self._site(node, "lookup by kind")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if id(node) not in self.counted and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr == "get" and node.args and _is_kind_read(node.args[0]):
                table = node.func.value
                name = (
                    table.id
                    if isinstance(table, ast.Name)
                    else getattr(table, "attr", "")
                )
                if name not in REGISTRIES and name in self.families:
                    self._site(node, "lookup by kind")
            elif attr in ("startswith", "endswith") and any(
                self._literal(a) for a in node.args
            ):
                self._site(node, "prefix or suffix")
            elif (
                attr == "fromkeys"
                and node.args
                and self._display_count(node.args[0]) >= 2
            ):
                self._site(node, "family")
        if (
            id(node) not in self.counted
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.JoinedStr)
            and any(_is_kind_read(v) for v in ast.walk(node.args[1]))
        ):
            self._site(node, "getattr by kind")
        self.generic_visit(node)

    def _display_count(self, node: ast.AST) -> int:
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return sum(1 for e in node.elts if self._literal(e))
        if isinstance(node, ast.Dict):
            return sum(1 for k in node.keys if k is not None and self._literal(k))
        return 0

    def _display(self, node: ast.AST) -> None:
        if id(node) not in self.counted and self._display_count(node) >= 2:
            self._site(node, "family")

    def visit_Tuple(self, node: ast.Tuple) -> None:
        self._display(node)
        self.generic_visit(node)

    visit_List = visit_Tuple  # noqa: N815
    visit_Set = visit_Tuple  # noqa: N815
    visit_Dict = visit_Tuple  # noqa: N815

    def visit_Match(self, node: ast.Match) -> None:
        if id(node) not in self.counted and any(
            self._literal(sub.value)
            for case in node.cases
            for sub in ast.walk(case.pattern)
            if isinstance(sub, ast.MatchValue)
        ):
            self._site(node, "match")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if id(node) not in self.counted and _is_category(node):
            self._site(node, "category")
        self.generic_visit(node)


def _families(tree: ast.Module, literals: frozenset[str]) -> set[str]:
    """Module-level names bound to a tuple, list, set, frozenset or dict of kind or mode literals."""
    found: set[str] = set()
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None:
            continue
        # frozenset({...}), set((...)), tuple([...])
        if isinstance(value, ast.Call) and value.args:
            value = value.args[0]
        elements: list[ast.expr] = []
        if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            elements = list(value.elts)
        elif isinstance(value, ast.Dict):
            elements = [k for k in value.keys if k is not None]
        if any(isinstance(e, ast.Constant) and e.value in literals for e in elements):
            found.update(t.id for t in targets if isinstance(t, ast.Name))
    return found


def _constants(tree: ast.Module, literals: frozenset[str], path: str) -> list[Site]:
    """Module constants bound to one kind or mode literal."""
    out = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value in literals
            ):
                out.append(Site(path, node.lineno, "<module>", "constant"))
    return out


def files() -> list[Path]:
    found = []
    for package in SCOPE_PACKAGES:
        found.extend(sorted((PACKAGES / package).rglob("*.py")))
    found.extend(PACKAGES / f for f in SCOPE_FILES)
    rel = lambda p: p.relative_to(PACKAGES).as_posix()  # noqa: E731
    return [
        p for p in found if p.exists() and rel(p) not in EXEMPT and not _registered(p)
    ]


def _registered(path: Path) -> bool:
    """A role's kind module, protocol, registry or pattern modes' module: where a kind (a mode) is its own entry's (V2-stage4b-0b.md, 5).

    A role's other modules (its shared helpers) are held to the rule as any
    program is: a helper that chose by kind would be dispatch out of sight.
    """
    from forge_spec.schema import KINDS

    if "items" not in path.parts:
        return False
    return path.stem in KINDS or path.name in ("protocol.py", "__init__.py", "pattern.py")


def sites(paths: list[Path] | None = None) -> list[Site]:
    literals = _literals()
    trees = {
        path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in paths or files()
    }
    # A family name bound in one module is one in every module that imports it.
    families = frozenset().union(
        *(_families(tree, literals) for tree in trees.values())
    )
    out: list[Site] = []
    for path, tree in trees.items():
        rel = (
            path.relative_to(PACKAGES).as_posix()
            if path.is_relative_to(PACKAGES)
            else path.name
        )
        scan = _Scan(rel, literals, families)
        scan.visit(tree)
        out.extend(scan.sites)
        out.extend(_constants(tree, literals, rel))
    return out


def item_modules() -> list[Path]:
    """Every module of the ``items/`` role subpackages."""
    found = []
    for package in SCOPE_PACKAGES:
        found.extend(sorted((PACKAGES / package / "items").rglob("*.py")))
    return found


def strangers(paths: list[Path] | None = None) -> list[Site]:
    """Inside ``items/``, every kind a module names but its own (V2-stage4b-0b.md, 2).

    A kind's module (``items/<role>/<kind>.py``) names only its own kind; the
    role's other modules (its protocol, registry and shared helpers) name
    none. What another kind needs from it, the kind publishes through its
    role's protocol.
    """
    from forge_spec.schema import KINDS

    out: list[Site] = []
    for path in paths if paths is not None else item_modules():
        own = path.stem if path.stem in KINDS else None
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = (
            path.relative_to(PACKAGES).as_posix()
            if path.is_relative_to(PACKAGES)
            else path.name
        )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in KINDS
                and node.value != own
            ):
                out.append(
                    Site(rel, node.lineno, own or "<role>", f"names {node.value}")
                )
    return out


def role_sites(paths: list[Path] | None = None) -> list[Site]:
    """Inside ``items/``, the sites in a role's protocol or pattern modes' module (V2-stage4b-0b.md, 5).

    Those modules are exempt from the ratchet's count, as a kind's own module
    is, but they hold no kind's code: a protocol's default may read its own
    kind's entry (a property returning a test of ``KINDS[self.key].category``)
    and nothing else; a pattern mode's module chooses by no mode (each mode
    is its own class).
    """
    paths = paths if paths is not None else [
        p for p in item_modules() if p.name in ("protocol.py", "pattern.py")
    ]
    by_rel = {
        (p.relative_to(PACKAGES).as_posix() if p.is_relative_to(PACKAGES) else p.name): p
        for p in paths
    }
    trees: dict[str, ast.Module] = {}
    out: list[Site] = []
    for site in sites(paths):
        path = by_rel[site.path]
        if path.name == "protocol.py":
            tree = trees.setdefault(site.path, ast.parse(path.read_text(encoding="utf-8")))
            around = [
                n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.lineno <= site.line <= (n.end_lineno or n.lineno)
            ]  # fmt: skip
            fn = min(around, key=lambda n: (n.end_lineno or n.lineno) - n.lineno) if around else None
            body = [b for b in fn.body if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))] if fn else []
            if (len(body) == 1 and isinstance(body[0], ast.Return)
                    and "KINDS[self.key].category" in ast.unparse(body[0])):  # fmt: skip
                continue
        out.append(site)
    return out


def counts() -> dict[str, int]:
    """Sites per file, the files with none left out."""
    return dict(sorted(Counter(site.path for site in sites()).items()))


def named(site: Site) -> list[str]:
    """The kinds, modes and categories a site's line names."""
    import re

    line = (
        (PACKAGES / site.path).read_text(encoding="utf-8").splitlines()[site.line - 1]
    )
    literals = _literals()
    words = [w for w in re.findall(r"['\"]([a-z_]+)['\"]", line) if w in literals]
    return words + [f"Category.{c}" for c in re.findall(r"Category\.([A-Z]+)", line)]


def inventory() -> str:
    """The sites by file and function, as the inventory's table (V2-stage4b-0b.md, step 0)."""
    from collections import defaultdict

    by: dict[tuple[str, str], list[Site]] = defaultdict(list)
    for site in sites():
        by[(site.path, site.function)].append(site)
    out = []
    for path in sorted({p for p, _ in by}):
        functions = [(fn, ss) for (p, fn), ss in by.items() if p == path]
        out.append(f"\n### `{path}`: {sum(len(ss) for _, ss in functions)} sites\n")
        out.append("| Function | Sites | Lines | Names |")
        out.append("|---|---|---|---|")
        for fn, ss in sorted(functions, key=lambda f: f[1][0].line):
            names = sorted({w for s in ss for w in named(s)})
            lines = ", ".join(str(s.line) for s in ss[:6]) + (
                ", ..." if len(ss) > 6 else ""
            )
            out.append(f"| `{fn}` | {len(ss)} | {lines} | {', '.join(names)} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--inventory"]:
        print(inventory(), end="")
        raise SystemExit
    found = sites()
    by_file = Counter(s.path for s in found)
    for path, n in sorted(by_file.items(), key=lambda kv: -kv[1]):
        print(f"{n:5d}  {path}")
    print(
        f"{len(found)} sites in {len(by_file)} files, {len({(s.path, s.function) for s in found})} functions"
    )
    print(Counter(s.what for s in found))
