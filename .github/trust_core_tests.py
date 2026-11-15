"""The test files that exercise the trust core alone (ADR-0023, ADR-0034): python .github/trust_core_tests.py

A test file is the trust core's when everything Forge it imports, itself or
through the helper modules in tests/ it imports, is an L0 package (the layers
are tests/test_v2_architecture.py's), and nothing else it imports is outside
the standard library but NumPy and the test tools. They run where OCP has no
wheels yet (CPython 3.15, the free-threaded 3.14t), so the move is ready the
day it does. Prints the files, one per line, as paths from the repository.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
#: Besides the standard library and the trust core: what CI installs for it.
TOOLS = {"numpy", "pytest", "hypothesis"}


def _layer_zero() -> set[str]:
    """L0_STDLIB and L0_NUMPY, read from the architecture test (its constants, not a copy)."""
    tree = ast.parse((TESTS / "test_v2_architecture.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in ("L0_STDLIB", "L0_NUMPY") for t in node.targets
        ):
            found |= set(ast.literal_eval(node.value))
    assert found, "no L0 sets in test_v2_architecture.py"
    return found


def _imports(path: Path, local: set[str], seen: set[Path]) -> tuple[set[str], set[str]]:
    """(Forge's packages, other third-party modules) the file imports, through the tests' helpers too."""
    if path in seen:
        return set(), set()
    seen.add(path)
    forge: set[str] = set()
    other: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top.startswith("forge"):
                forge.add(top)
            elif top in local:
                more = _imports(TESTS / f"{top}.py", local, seen)
                forge |= more[0]
                other |= more[1]
            elif top not in sys.stdlib_module_names:
                other.add(top)
    return forge, other


def trust_core_tests() -> list[str]:
    zero = _layer_zero()
    local = {p.stem for p in TESTS.glob("*.py")}
    found = []
    for path in sorted(TESTS.glob("test_*.py")):
        forge, other = _imports(path, local, set())
        if forge and forge <= zero and other <= TOOLS:
            found.append(path.relative_to(ROOT).as_posix())
    return found


if __name__ == "__main__":
    print("\n".join(trust_core_tests()))
