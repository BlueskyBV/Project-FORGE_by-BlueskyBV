"""Derived values: a formula, worked out from the brief's own numbers.

A value whose provenance is a formula ("the upright is 40 mm overall less the
5 mm base") is checked as hard as one read straight from the brief:

- the formula is arithmetic on quantities, written plainly: ``40 mm - 5 mm``,
  ``(30 mm - 16 mm) / 2``, ``hypot(30 mm, 40 mm)``. It is parsed and worked out
  by :mod:`forge_expr`, which never calls ``eval``;
- every number in it must be read from the words the value cites, unit and
  all, by the same rules as a cited value (:mod:`forge_spec.citations`), and
  each number the brief gives is used once (so ``20 mm - 20 mm - 20 mm``
  needs three twenties in the brief). A bare number must be a count the cited
  words give, or 2 multiplying, dividing or squaring (halving, doubling, a
  square under a root), at most one in a run of multiplications;
- nothing else may stand for a number: no unit on its own (``cm / mm``), no
  named constant (``pi``), and only the functions :data:`FUNCTIONS`;
- worked out, it must give the value, exactly, or rounded sensibly where it
  doesn't terminate.

So a derived value can't bring in a number the brief doesn't give. One that
depends on an assumption is an assumption, and is shown as one.

>>> from forge_spec.words import number_words
>>> from forge_units import Q
>>> brief = number_words("A collar 30 mm across with a 16 mm bore.")
>>> check = check_formula(Q(7, "mm"), "(30 mm - 16 mm) / 2", (2, 3, 7, 8), brief)
>>> check.ok, [r.describe() for r in check.readings]
(True, ['30 mm', '16 mm'])
>>> check_formula(Q(8, "mm"), "(30 mm - 16 mm) / 2", (2, 3, 7, 8), brief).message
'the formula gives 7 mm, not 8 mm'
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass

from forge_expr import Expression, ForgeExprError
from forge_units import Q, Quantity, parse_unit

from .citations import CitationCheck, Follows, Reading, check_count, check_quantity
from .citations import _matches as matches
from .words import NumberedBrief, WordRef

__all__ = ["CONSTANTS", "FUNCTIONS", "RIGHT_ANGLES", "FormulaCheck", "check_formula"]

#: Bare numbers a formula may use without the brief giving them, where they may go.
CONSTANTS = frozenset({2.0})
#: Angles a formula may use without the brief giving them: a right angle and a straight one, added to or taken from
#: an angle the brief gives ("65 degrees from the base" is a tilt of 90 deg - 65 deg from square to it).
RIGHT_ANGLES = frozenset({90.0, 180.0})
#: The functions a formula may call.
FUNCTIONS = frozenset(
    {"sqrt", "hypot", "sin", "cos", "tan", "asin", "acos", "atan", "atan2"}
)


@dataclass(frozen=True)
class FormulaCheck:
    """Whether a derived value follows from its formula and the cited words."""

    ok: bool
    message: str
    #: How each number of the formula was read from the brief.
    readings: tuple[Reading, ...] = ()
    #: Readings the person should see (a comma read as a decimal point...).
    caveats: tuple[str, ...] = ()
    #: Numbers whose unit the brief doesn't state.
    unit_assumed: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Literal:
    value: float
    unit: str | None
    constant: bool = False  # a bare 2, halving, doubling or squaring; or a right or straight angle


def _unit_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Name):
        return None
    try:
        parse_unit(node.id)
    except Exception:  # not a unit: a function or an unknown name
        return None
    return node.id


def _number(node: ast.AST) -> float | None:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return float(node.value)
    return None


def _literals(tree: ast.AST) -> list[_Literal] | str:
    """Every number in the formula, with the unit written next to it; or what is wrong."""
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    found: list[_Literal] = []
    taken: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
                and _number(node.left) is not None and _unit_name(node.right) is not None):  # fmt: skip
            figure, unit = _number(node.left) or 0.0, _unit_name(node.right)
            found.append(_Literal(figure, unit, _right_angle(node, figure, unit, parents)))
            taken.update((id(node.left), id(node.right)))
    for node in ast.walk(tree):
        if id(node) in taken:
            continue
        parent = parents.get(id(node))
        if isinstance(node, ast.Name):
            if isinstance(parent, ast.Call) and parent.func is node:
                if node.id not in FUNCTIONS:
                    return f"{node.id}() isn't one of the functions a formula may use ({', '.join(sorted(FUNCTIONS))})"
                continue
            return f"{node.id} isn't a number from the brief (write a unit right after its number: 40 mm)"
        if isinstance(node, ast.Constant):
            value = _number(node)
            if value is None:
                return f"{node.value!r} is not a number"
            found.append(
                _Literal(
                    value, None, value in CONSTANTS and _free_two(node, parents, taken)
                )
            )
    return found


def _right_angle(node: ast.AST, value: float, unit: str | None, parents: dict[int, ast.AST]) -> bool:
    """Whether ``90 deg`` or ``180 deg`` is added to or taken from an angle the brief gives: a complement or a supplement.

    Observed on blind set 1: "leans back at 65 degrees from the base" is a
    tilt of 25 degrees from square to it, which no formula could say while
    every number had to be the brief's; the writer assumed it, and 65 was
    asked about as unused. Only in a sum or a difference whose other side
    holds a number from the brief, and only in degrees: it brings in no size.
    """
    if value not in RIGHT_ANGLES or unit is None:
        return False
    try:
        if parse_unit(unit).symbol != "deg":
            return False
    except Exception:  # noqa: BLE001 - not a unit: not an angle
        return False
    parent = parents.get(id(node))
    if not isinstance(parent, ast.BinOp) or not isinstance(parent.op, (ast.Add, ast.Sub)):
        return False
    other = parent.right if parent.left is node else parent.left
    return _has_brief_number(other)


def _chain_root(node: ast.AST, parents: dict[int, ast.AST]) -> ast.AST:
    """The top of the run of multiplications and divisions a node is an operand of."""
    while True:
        parent = parents.get(id(node))
        if not (
            isinstance(parent, ast.BinOp) and isinstance(parent.op, (ast.Mult, ast.Div))
        ):
            return node
        node = parent


def _is_literal(node: ast.AST) -> bool:
    """A number with its unit: ``40 mm``."""
    return (
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
        and _number(node.left) is not None and _unit_name(node.right) is not None
    )  # fmt: skip


def _has_brief_number(node: ast.AST) -> bool:
    """Whether an expression holds a number that must come from the brief."""
    return any(
        _is_literal(n) or (isinstance(n, ast.Constant) and _number(n) is not None and _number(n) not in CONSTANTS)
        for n in ast.walk(node)
    )  # fmt: skip


def _free_two(node: ast.Constant, parents: dict[int, ast.AST], taken: set[int]) -> bool:
    """Whether a bare 2 halves, doubles or squares something worked out from the brief.

    It must multiply or divide (or be the power of) an expression that holds
    a number from the brief, and a run of multiplications holds at most one
    free 2: "x * 2 * 2" brings in a 4 the brief never gave.
    """
    parent = parents.get(id(node))
    if not isinstance(parent, ast.BinOp):
        return False
    if isinstance(parent.op, ast.Pow):
        return parent.right is node and _has_brief_number(parent.left)
    if not isinstance(parent.op, (ast.Mult, ast.Div)):
        return False
    other = parent.right if parent.left is node else parent.left
    if not _has_brief_number(other) and not _has_brief_number(
        _chain_root(parent, parents)
    ):
        return False
    root = _chain_root(node, parents)
    twos = [n for n in _chain_operands(root)
            if isinstance(n, ast.Constant) and id(n) not in taken and _number(n) in CONSTANTS]  # fmt: skip
    return len(twos) == 1


def _chain_operands(node: ast.AST) -> list[ast.AST]:
    """The operands of a run of multiplications and divisions, flattened."""
    if (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, (ast.Mult, ast.Div))
        and not _is_literal(node)
    ):
        return _chain_operands(node.left) + _chain_operands(node.right)
    return [node]


def _first_line(exc: ForgeExprError) -> str:
    return exc.message.splitlines()[0]


def _groups(cited: tuple[int, ...]) -> list[tuple[int, ...]]:
    """Runs of three and two consecutive cited words ("1 1/2 in"), then each cited word."""
    present = set(cited)
    groups: list[tuple[int, ...]] = []
    for size in (3, 2):  # the longest first: "1 1/2 in" before "1"
        groups += [
            tuple(range(i, i + size))
            for i in cited
            if all(j in present for j in range(i, i + size))
        ]
    return groups + [(i,) for i in cited]


def _read(literal: _Literal, cited: tuple[int, ...], brief: NumberedBrief,
          used: set[object]) -> CitationCheck | None:  # fmt: skip
    """The first cited words that give this number, as a cited value would, not used already."""
    for group in _groups(cited):
        if literal.unit is None:
            if not literal.value.is_integer():
                return None
            check = check_count(int(literal.value), brief, group)
        else:
            check = check_quantity(Q(literal.value, literal.unit), brief, group)
        if check.follows is Follows.NO or check.reading is None:
            continue
        slots: set[object] = set(check.reading.numbers)
        if not slots:  # "a" read as one has no number slot: the word itself is used
            slots = {("word", w) for w in check.reading.words}
        if slots & used:
            continue
        used.update(slots)
        return check
    return None


#: "in" after a number: inches. It is also a Python keyword, which the
#: parser would read as one ("2 in" doesn't parse), so it is given the unit's
#: other name first.
_INCHES = re.compile(r"(?<=[\d.])\s*in\b")


#: A fraction written against its unit, as a brief writes it: "1/2 in", "1 1/2 in".
#: Read as one number ("0.5 in"), not as 1 divided by 2 inches.
_FRACTIONS = re.compile(r"(?<![\w.)])(?:(\d+)\s+)?(\d+)/(\d+)(?=\s*[A-Za-z])")


def _decimal(match: re.Match[str]) -> str:
    whole, top, bottom = match.group(1), int(match.group(2)), int(match.group(3))
    if bottom == 0:
        return match.group(0)  # left for the parser to refuse
    return repr((int(whole) if whole else 0) + top / bottom)


def check_formula(
    target: Quantity | int, formula: str, words: WordRef, brief: NumberedBrief
) -> FormulaCheck:
    """Whether ``target`` is what ``formula`` gives, from the numbers ``words`` cite.

    ``target`` is a value's quantity, or a count's number.
    """
    try:
        expression = Expression.parse(
            _INCHES.sub(" inch", _FRACTIONS.sub(_decimal, formula))
        )
    except ForgeExprError as exc:
        return FormulaCheck(
            False, f"the formula {formula!r} doesn't read: {_first_line(exc)}"
        )
    literals = _literals(expression.tree)
    if isinstance(literals, str):
        return FormulaCheck(False, f"in the formula {formula!r}, {literals}")
    cited = tuple(sorted(set(words)))
    for index in cited:
        brief.word(index)  # a word number that doesn't exist raises LookupError
    readings: list[Reading] = []
    caveats: list[str] = []
    unit_assumed: list[str] = []
    used: set[object] = set()
    for literal in literals:
        if literal.constant:
            continue
        check = _read(literal, cited, brief, used)
        shown = f"{literal.value:g}" + (
            f" {parse_unit(literal.unit).symbol}" if literal.unit else ""
        )
        if check is None and literal.unit is None and not literal.value.is_integer():
            # A number with no unit is a count, and a count is whole (corpus: "-37.5 - (-50)" for a length).
            return FormulaCheck(
                False,
                f"{shown} in the formula {formula!r} has no unit: a number with none is a count of things; "
                "write a size with its unit (\"37.5 mm\")",
            )
        if check is None or check.reading is None:
            return FormulaCheck(
                False,
                f"{shown} in the formula {formula!r} is not in the words it cites "
                f"({brief.quote(cited)!r}), or is used twice",
            )
        readings.append(check.reading)
        if check.follows is Follows.YES_WITH_CAVEAT:
            caveats.append(check.message)
        elif check.follows is Follows.UNIT_NOT_STATED:
            unit_assumed.append(check.message)
    if not readings:
        return FormulaCheck(
            False,
            f"the formula {formula!r} uses none of the brief's numbers; "
            "a value worked out from nothing the brief says is an assumption",
        )
    try:
        result = expression.evaluate({})
    except ForgeExprError as exc:
        return FormulaCheck(
            False, f"the formula {formula!r} can't be worked out: {_first_line(exc)}"
        )
    if not isinstance(result, Quantity):
        return FormulaCheck(
            False, f"the formula {formula!r} is a comparison, not a size"
        )
    if isinstance(target, Quantity):
        unit = target.unit.symbol
        try:
            got = result.to(unit).magnitude.midpoint
        except Exception:  # a different dimension
            return FormulaCheck(
                False, f"the formula {formula!r} doesn't give a value in {unit}"
            )
        wanted = target.nominal
    else:
        unit = ""
        try:
            got = result.to("").magnitude.midpoint
        except Exception:
            return FormulaCheck(
                False, f"the formula {formula!r} doesn't give a plain number"
            )
        wanted = float(target)
    if not math.isfinite(got) or not matches(got, wanted, converted=True):
        gives = f"{got:g} {unit}".strip()
        return FormulaCheck(
            False, f"the formula gives {gives}, not {f'{wanted:g} {unit}'.strip()}"
        )
    return FormulaCheck(
        True, "follows", tuple(readings), tuple(caveats), tuple(unit_assumed)
    )
