"""Safe, dimension-checked expression evaluation.

Design constraints, in priority order:

1. **No arbitrary execution.** Expressions arrive from language models and from
   imported documents, both of which are untrusted. ``eval`` is never called.
   The expression is parsed with :mod:`ast` and then walked by an interpreter
   that understands a closed set of node types; anything else is refused by name
   at validation time, before any evaluation happens.

2. **Dimensional correctness.** Every value is a
   :class:`~forge_units.quantity.Quantity`, so ``bore_diameter + wall_force``
   fails with a dimensional error rather than producing a number.

3. **Uncertainty propagation.** Because quantities carry intervals, an
   expression written over tolerance-bearing parameters yields a
   tolerance-bearing result for free. A stack-up is just arithmetic.

4. **Honest conditionals.** ``a if cond else b`` where ``cond`` is
   ``INDETERMINATE`` does not pick a branch. It returns the *hull* of both
   branches, which is the only sound answer when you do not know which applies,
   and it keeps the uncertainty visible in the result rather than resolving it
   by coin flip.

Two sorts of value
------------------
Expressions evaluate to either a ``Quantity`` (arithmetic) or a ``Trivalent``
(comparisons and boolean logic). The sorts do not mix implicitly; a comparison
cannot be added to a length.

Grammar
-------
Supported: numeric literals, names, ``+ - * / // % **`` (integer division and
modulo restricted to dimensionless operands), unary ``+ -``, comparisons
``< <= > >= == !=``, ``and`` / ``or`` / ``not``, conditional expressions,
parenthesisation, and calls to the vetted function table.

Refused, by name: attribute access, subscripting, slices, calls to anything not
in the table, lambdas, comprehensions, generators, starred arguments, keyword
arguments, assignment expressions, f-strings, string and byte literals,
containers, ``await``, and every statement form.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from forge_units import (
    detail_besides,
    CONSTANT_TABLE,
    FUNCTION_TABLE,
    DimensionalityError,
    ForgeUnitsError,
    Interval,
    Quantity,
    Trivalent,
    known_units,
    parse_unit,
)

from .errors import (
    ArityError,
    DisallowedConstructError,
    EvaluationError,
    ExpressionComplexityError,
    ExpressionSyntaxError,
    ExpressionTypeError,
    UnknownFunctionError,
    UnknownNameError,
)

#: An evaluated expression is one of these two sorts.
Value = Quantity | Trivalent

#: Budget limits. These exist because expressions are untrusted input: a
#: deeply nested or enormous expression is a denial-of-service vector against
#: the compiler, and no legitimate design parameter needs to exceed them.
MAX_NODES = 512
MAX_DEPTH = 32
MAX_SOURCE_CHARACTERS = 4096

_ALLOWED_NODES: frozenset[type[ast.AST]] = frozenset(
    {
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.Call,
        ast.Compare,
        ast.BoolOp,
        ast.IfExp,
        # operators
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Not,
        ast.And,
        ast.Or,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.Eq,
        ast.NotEq,
    }
)

_NODE_DESCRIPTIONS: dict[str, str] = {
    "Attribute": "attribute access",
    "Subscript": "subscripting",
    "Lambda": "a lambda",
    "ListComp": "a comprehension",
    "SetComp": "a comprehension",
    "DictComp": "a comprehension",
    "GeneratorExp": "a generator expression",
    "Starred": "argument unpacking",
    "JoinedStr": "an f-string",
    "NamedExpr": "an assignment expression",
    "Await": "await",
    "List": "a list literal",
    "Tuple": "a tuple literal",
    "Dict": "a dict literal",
    "Set": "a set literal",
    "Import": "an import",
    "ImportFrom": "an import",
}

#: Function arities, checked before dispatch so that a wrong-arity call gives a
#: clear message instead of a Python ``TypeError`` from deep inside the table.
_FUNCTION_ARITY: dict[str, tuple[int, ...]] = {
    "sin": (1,),
    "cos": (1,),
    "tan": (1,),
    "asin": (1,),
    "acos": (1,),
    "atan": (1,),
    "atan2": (2,),
    "sqrt": (1,),
    "hypot": (2,),
    "abs": (1,),
    "exp": (1,),
    "ln": (1,),
    "log10": (1,),
    "min": (2,),
    "max": (2,),
    "clamp": (3,),
    "round_to": (2,),
    "deg": (1,),
    "rad": (1,),
}


def _canonicalise(source: str) -> str:
    """Rewrite ``^`` as ``**`` before parsing.

    Engineers write ``mm^2``, not ``mm**2``. Python reads ``^`` as bitwise XOR,
    which this language does not have, so the character is free to mean
    exponentiation.

    The rewrite is *lexical*, done on the source text before parsing, rather
    than by mapping the ``BitXor`` node to a power operation afterwards. That
    distinction matters and is not cosmetic: ``^`` binds *more loosely* than
    ``*`` in Python, so ``2 * mm^2`` would parse as ``(2 * mm) ^ 2`` and an
    AST-level rewrite would silently compute ``(2 mm)**2 = 4 mm^2`` where the
    author meant ``2 mm^2``. Substituting the text first makes Python's
    ``**`` precedence apply, which is the precedence engineers expect.

    Because string literals are refused by the allowlist and XOR does not exist
    in this language, no legitimate expression can contain a ``^`` that means
    anything else, so the substitution is unambiguous.
    """
    text = source.replace("^", "**")
    return _A_FIGURE_WITH_ITS_UNIT.sub(_written_as_a_product, text)


#: "60 deg", "2.5mm", "4 mm**2": a figure with its unit written after it, as
#: an engineer writes it. Python has no reading of a number followed by a
#: name, so the only meaning it can have is the product -- and a stepper
#: plate's designer spent two of its three attempts on `cos(60 deg)`.
_A_FIGURE_WITH_ITS_UNIT = re.compile(
    r"(?<![\w.])((?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*"
    r"([A-Za-z_]\w*(?:\s*\*\*\s*\d+)?)(?![\w(])")


def _written_as_a_product(match: "re.Match[str]") -> str:
    figure, unit = match.group(1), match.group(2)
    name = re.match(r"[A-Za-z_]\w*", unit).group(0)  # type: ignore[union-attr]
    if name in ("if", "else", "and", "or", "not", "in", "is", "for"):
        return match.group(0)
    try:
        parse_unit(name)
    except Exception:  # noqa: BLE001 - not a unit: left for the parser to name
        return match.group(0)
    return f"({figure} * {unit})"


def _span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "col_offset", 0)
    end = getattr(node, "end_col_offset", None)
    return (start, end if end is not None else start + 1)


@dataclass(frozen=True, slots=True)
class Expression:
    """A parsed, validated expression, ready to evaluate against a context.

    Parsing and validation happen once at construction; evaluation is then a
    pure walk with no further syntax checking. That matters for the optimiser,
    which evaluates the same expression thousands of times with different
    parameter values.

    Examples
    --------
    >>> from forge_units import Q
    >>> expr = Expression.parse("base_width - 2 * wall")
    >>> ctx = {"base_width": Q(60, "mm"), "wall": Q(6, "mm")}
    >>> expr.evaluate(ctx).to("mm").magnitude.midpoint
    48.0
    """

    source: str
    tree: ast.Expression
    names: frozenset[str]
    functions: frozenset[str]

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def parse(cls, source: str) -> "Expression":
        if not isinstance(source, str):
            raise ExpressionSyntaxError(
                "expression must be a string", got=type(source).__name__
            )
        text = _canonicalise(source.strip())
        if not text:
            raise ExpressionSyntaxError("expression is empty", source=source)
        if len(text) > MAX_SOURCE_CHARACTERS:
            # The node budget is enforced after a successful parse, and the
            # parser itself is what a long enough source breaks: five
            # thousand unary minuses reached the recursion limit, five
            # thousand `**` overflowed the parser's stack. No design
            # expression is this long.
            raise ExpressionComplexityError(
                "expression is too long",
                source=text[:80] + "...",
                length=len(text),
                limit=MAX_SOURCE_CHARACTERS,
            )
        try:
            tree = ast.parse(text, mode="eval")
        except SyntaxError as exc:
            raise ExpressionSyntaxError(
                f"expression is not valid syntax: {exc.msg}",
                source=text,
                span=(
                    (exc.offset - 1) if exc.offset else 0,
                    (exc.offset) if exc.offset else 1,
                ),
            ) from exc
        except (RecursionError, MemoryError, ValueError) as exc:
            raise ExpressionComplexityError(
                f"expression is too deeply nested to parse: {exc}",
                source=text[:80] + ("..." if len(text) > 80 else ""),
            ) from exc

        names, functions = _validate(tree, text)
        return cls(
            source=text,
            tree=tree,
            names=frozenset(names),
            functions=frozenset(functions),
        )

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    def evaluate(
        self,
        context: Mapping[str, Quantity],
        *,
        allow_units_as_names: bool = True,
    ) -> Value:
        """Evaluate against a mapping of parameter name to quantity.

        Name resolution order is: named constants (``pi``, ``e``, ``g0``), then
        the supplied context, then unit symbols. Unit symbols resolve to a
        quantity of magnitude one, which is what makes ``2 * mm`` read naturally.
        """
        evaluator = _Evaluator(
            source=self.source,
            context=context,
            allow_units_as_names=allow_units_as_names,
        )
        return evaluator.visit(self.tree.body)

    def evaluate_quantity(
        self, context: Mapping[str, Quantity], **kwargs: Any
    ) -> Quantity:
        """Evaluate and require the result to be a quantity."""
        result = self.evaluate(context, **kwargs)
        if isinstance(result, Trivalent):
            raise ExpressionTypeError(
                "expression evaluates to a truth value where a quantity was "
                "required",
                source=self.source,
                result=str(result),
            )
        return result

    def evaluate_condition(
        self, context: Mapping[str, Quantity], **kwargs: Any
    ) -> Trivalent:
        """Evaluate and require the result to be a three-valued condition."""
        result = self.evaluate(context, **kwargs)
        if isinstance(result, Quantity):
            raise ExpressionTypeError(
                "expression evaluates to a quantity where a condition was "
                "required; write an explicit comparison",
                source=self.source,
                result=str(result),
            )
        return result

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def free_names(self, *, exclude_units: bool = False) -> frozenset[str]:
        """Names the expression references, excluding named constants.

        Unit symbols are *retained* by default, and that default is deliberate.
        Many excellent parameter names are also unit symbols -- ``t`` for
        thickness collides with the tonne, ``L`` with the litre, ``h`` with the
        hour -- and since a declared parameter shadows a unit during evaluation,
        dropping unit-shaped names here would lose a real dependency edge and
        let the topological sort evaluate a parameter before the value it needs.

        :class:`~forge_expr.parameters.ParameterGraph` resolves the remaining
        ambiguity with the information this class does not have: which names are
        actually declared as parameters.
        """
        without_constants = frozenset(
            name for name in self.names if name not in CONSTANT_TABLE
        )
        if not exclude_units:
            return without_constants
        unit_symbols = set(known_units())
        return frozenset(
            name for name in without_constants if name not in unit_symbols
        )

    def resolves_as_unit(self, name: str) -> bool:
        """Whether ``name`` would resolve to a unit if no parameter declares it."""
        if name not in self.names:
            return False
        try:
            parse_unit(name)
        except ForgeUnitsError:
            return False
        return True

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.source


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
def _validate(tree: ast.Expression, source: str) -> tuple[set[str], set[str]]:
    """Walk the tree once, refusing disallowed constructs and collecting names."""
    names: set[str] = set()
    functions: set[str] = set()
    node_count = 0

    def walk(node: ast.AST, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > MAX_NODES:
            raise ExpressionComplexityError(
                "expression exceeds the node budget",
                source=source,
                limit=MAX_NODES,
            )
        if depth > MAX_DEPTH:
            raise ExpressionComplexityError(
                "expression exceeds the nesting-depth budget",
                source=source,
                limit=MAX_DEPTH,
            )

        node_type = type(node)
        if node_type not in _ALLOWED_NODES:
            name = node_type.__name__
            description = _NODE_DESCRIPTIONS.get(name, f"a {name} node")
            raise DisallowedConstructError(
                f"{description} is not permitted in a design expression",
                source=source,
                span=_span(node),
                construct=name,
                hint="design expressions are restricted to arithmetic, "
                "comparison, boolean logic and the vetted function table",
            )

        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(
                node.value, bool
            ):
                raise DisallowedConstructError(
                    "only numeric literals are permitted",
                    source=source,
                    span=_span(node),
                    literal=repr(node.value),
                )

        if isinstance(node, ast.Call):
            if node.keywords:
                raise DisallowedConstructError(
                    "keyword arguments are not permitted in a design expression",
                    source=source,
                    span=_span(node),
                )
            if not isinstance(node.func, ast.Name):
                raise DisallowedConstructError(
                    "only direct calls to named functions are permitted",
                    source=source,
                    span=_span(node),
                )
            function_name = node.func.id
            if function_name not in FUNCTION_TABLE:
                raise UnknownFunctionError(
                    "function is not in the vetted function table",
                    source=source,
                    span=_span(node),
                    function=function_name,
                    available=sorted(FUNCTION_TABLE),
                )
            arities = _FUNCTION_ARITY.get(function_name, ())
            if arities and len(node.args) not in arities:
                raise ArityError(
                    "function called with the wrong number of arguments",
                    source=source,
                    span=_span(node),
                    function=function_name,
                    expected=list(arities),
                    got=len(node.args),
                )
            functions.add(function_name)
            for argument in node.args:
                walk(argument, depth + 1)
            return  # func Name is not a free variable

        if isinstance(node, ast.Name):
            names.add(node.id)

        for child in ast.iter_child_nodes(node):
            walk(child, depth + 1)

    walk(tree.body, 0)
    return names, functions


# ----------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------
class _Evaluator:
    """Recursive interpreter over the validated node set."""

    __slots__ = ("source", "context", "allow_units_as_names")

    def __init__(
        self,
        *,
        source: str,
        context: Mapping[str, Quantity],
        allow_units_as_names: bool,
    ) -> None:
        self.source = source
        self.context = context
        self.allow_units_as_names = allow_units_as_names

    # -- dispatch ------------------------------------------------------
    def visit(self, node: ast.AST) -> Value:
        method = getattr(self, f"_visit_{type(node).__name__}", None)
        if method is None:  # pragma: no cover - validation precludes this
            raise DisallowedConstructError(
                "unsupported node reached the evaluator",
                source=self.source,
                span=_span(node),
                construct=type(node).__name__,
            )
        return method(node)

    # -- leaves --------------------------------------------------------
    def _visit_Constant(self, node: ast.Constant) -> Quantity:  # noqa: N802
        try:
            number = float(node.value)
        except OverflowError as exc:
            raise EvaluationError(
                "a literal in the expression is too large to represent",
                source=self.source,
                span=_span(node),
            ) from exc
        if not math.isfinite(number):
            raise EvaluationError(
                "a literal in the expression is not a finite number",
                source=self.source,
                span=_span(node),
            )
        return Quantity(Interval.exact(number), parse_unit(""))

    def _visit_Name(self, node: ast.Name) -> Quantity:  # noqa: N802
        name = node.id
        constant = CONSTANT_TABLE.get(name)
        if constant is not None:
            return constant
        value = self.context.get(name)
        if value is not None:
            if not isinstance(value, Quantity):
                raise ExpressionTypeError(
                    "context values must be Quantity instances",
                    source=self.source,
                    span=_span(node),
                    name=name,
                    got=type(value).__name__,
                )
            return value
        if self.allow_units_as_names:
            try:
                unit = parse_unit(name)
            except ForgeUnitsError:
                unit = None
            if unit is not None:
                if unit.is_affine:
                    raise ExpressionTypeError(
                        "an affine temperature unit cannot be used as a "
                        "multiplicative literal; write a temperature parameter "
                        "instead",
                        source=self.source,
                        span=_span(node),
                        unit=name,
                    )
                return Quantity(Interval.exact(1.0), unit)
        raise UnknownNameError(
            "name does not resolve to a parameter, constant or unit",
            source=self.source,
            span=_span(node),
            name=name,
            available=sorted(self.context)[:40],
        )

    # -- arithmetic ----------------------------------------------------
    def _visit_BinOp(self, node: ast.BinOp) -> Quantity:  # noqa: N802
        left = self._as_quantity(node.left, "arithmetic operand")
        right = self._as_quantity(node.right, "arithmetic operand")
        operator = type(node.op)
        if operator in (ast.Add, ast.Sub):
            left, right = self._plain_numbers_beside_an_angle(
                left, right, node.left, node.right)
        try:
            if operator is ast.Add:
                return left + right
            if operator is ast.Sub:
                return left - right
            if operator is ast.Mult:
                return left * right
            if operator is ast.Div:
                return left / right
            if operator is ast.Pow:
                return self._power(left, right, node)
            if operator is ast.FloorDiv:
                return self._floor_div(left, right, node)
            if operator is ast.Mod:
                return self._modulo(left, right, node)
        except ForgeUnitsError as exc:
            raise EvaluationError(
                exc.message,
                source=self.source,
                span=_span(node),
                cause=exc.code,
                **detail_besides(exc.detail, "cause", "source", "span"),
            ) from exc
        except (OverflowError, ZeroDivisionError, ValueError) as exc:
            # Float arithmetic's own refusals -- `2 ** 1000000`, `inf // 1`,
            # `inf % 3` -- said as an evaluation error with the span, not
            # as a Python message a compile error quotes verbatim.
            raise EvaluationError(
                f"the arithmetic cannot be carried out: {exc}",
                source=self.source,
                span=_span(node),
            ) from exc
        raise DisallowedConstructError(  # pragma: no cover - validation precludes
            "unsupported binary operator",
            source=self.source,
            span=_span(node),
            operator=operator.__name__,
        )

    def _plain_numbers_beside_an_angle(
        self, left: Quantity, right: Quantity, left_node: ast.AST,
        right_node: ast.AST,
    ) -> tuple[Quantity, Quantity]:
        """A plain number added to or taken from an angle in degrees is that
        many degrees. An angle is dimensionless, so `alpha + 10` with alpha
        30 degrees read the 10 as radians and came to 603 degrees, and
        `180 - 2 * alpha` came to 178.95 of nothing in particular. Not when
        the number is worked in radians -- it mentions `pi` or an inverse
        trigonometric function."""
        from forge_units import a_plain_number_in

        segment = ast.get_source_segment
        for plain, plain_node, angle in ((left, left_node, right),
                                         (right, right_node, left)):
            text = segment(self.source, plain_node) or ""
            if not text:
                text = " ".join(
                    n.id for n in ast.walk(plain_node) if isinstance(n, ast.Name))
                text += " " + " ".join(
                    n.func.id for n in ast.walk(plain_node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name))
            read = a_plain_number_in(plain, angle.unit, text or " ")
            if read is not None:
                if plain is left:
                    return read, right
                return left, read
        return left, right

    def _power(self, left: Quantity, right: Quantity, node: ast.AST) -> Quantity:
        if not right.is_dimensionless:
            raise ExpressionTypeError(
                "an exponent must be dimensionless",
                source=self.source,
                span=_span(node),
                exponent_unit=right.unit.symbol,
            )
        if not right.is_exact:
            raise ExpressionTypeError(
                "an exponent must be exactly known; raising to an uncertain "
                "power would make the result's dimension uncertain, which the "
                "type system cannot represent",
                source=self.source,
                span=_span(node),
                exponent=str(right),
            )
        return left ** right.magnitude.lo

    def _floor_div(self, left: Quantity, right: Quantity, node: ast.AST) -> Quantity:
        quotient = left / right
        if not quotient.is_dimensionless:
            raise ExpressionTypeError(
                "floor division requires the quotient to be dimensionless",
                source=self.source,
                span=_span(node),
                quotient_unit=quotient.unit.symbol,
            )
        import math

        magnitude = quotient.to("").magnitude
        return Quantity(
            Interval(math.floor(magnitude.lo), math.floor(magnitude.hi)),
            parse_unit(""),
        )

    def _modulo(self, left: Quantity, right: Quantity, node: ast.AST) -> Quantity:
        if left.dimension != right.dimension:
            raise ExpressionTypeError(
                "modulo requires both operands to share a dimension",
                source=self.source,
                span=_span(node),
                left_unit=left.unit.symbol,
                right_unit=right.unit.symbol,
            )
        divisor = right.to(left.unit).magnitude
        if not divisor.is_exact or divisor.lo <= 0.0:
            raise ExpressionTypeError(
                "modulo requires an exact, strictly positive divisor",
                source=self.source,
                span=_span(node),
                divisor=str(right),
            )
        value = left.magnitude
        step = divisor.lo
        if value.width >= step:
            # The remainder can take any value in [0, step) once the input
            # spans a full period; reporting a narrower interval would be
            # unsound.
            return Quantity(Interval(0.0, step), left.unit)
        import math

        lo = math.fmod(value.lo, step)
        hi = math.fmod(value.hi, step)
        if lo < 0:
            lo += step
        if hi < 0:
            hi += step
        if lo > hi:  # the interval wrapped past a multiple of the divisor
            return Quantity(Interval(0.0, step), left.unit)
        return Quantity(Interval(lo, hi), left.unit)

    def _visit_UnaryOp(self, node: ast.UnaryOp) -> Value:  # noqa: N802
        operator = type(node.op)
        if operator is ast.Not:
            return ~self._as_condition(node.operand, "operand of 'not'")
        operand = self._as_quantity(node.operand, "operand of unary sign")
        if operator is ast.USub:
            return -operand
        return operand

    # -- comparison and logic -------------------------------------------
    def _visit_Compare(self, node: ast.Compare) -> Trivalent:  # noqa: N802
        from forge_units import all_true

        results: list[Trivalent] = []
        left = self._as_quantity(node.left, "comparison operand")
        for operator_node, comparator_node in zip(node.ops, node.comparators):
            right = self._as_quantity(comparator_node, "comparison operand")
            operator = type(operator_node)
            try:
                if operator is ast.Lt:
                    results.append(left.less_than(right))
                elif operator is ast.LtE:
                    results.append(left.at_most(right))
                elif operator is ast.Gt:
                    results.append(left.greater_than(right))
                elif operator is ast.GtE:
                    results.append(left.at_least(right))
                elif operator is ast.Eq:
                    results.append(self._equality(left, right))
                elif operator is ast.NotEq:
                    results.append(~self._equality(left, right))
                else:  # pragma: no cover - validation precludes
                    raise DisallowedConstructError(
                        "unsupported comparison operator",
                        source=self.source,
                        span=_span(node),
                    )
            except DimensionalityError as exc:
                raise EvaluationError(
                    exc.message,
                    source=self.source,
                    span=_span(node),
                    cause=exc.code,
                    **detail_besides(exc.detail, "cause", "source", "span"),
                ) from exc
            left = right
        return all_true(results)

    @staticmethod
    def _equality(left: Quantity, right: Quantity) -> Trivalent:
        """Equality of two intervals.

        ``TRUE`` only when both are exact and equal; ``FALSE`` when the intervals
        are disjoint; ``INDETERMINATE`` when they overlap but are not both exact,
        because two values drawn from overlapping intervals may or may not be
        equal. Exact floating-point equality on uncertain values is meaningless,
        and pretending otherwise is how tolerance bugs are born.
        """
        converted = right.to(left.unit).magnitude
        own = left.magnitude
        if own.is_exact and converted.is_exact:
            return Trivalent.of(own.lo == converted.lo)
        if not own.overlaps(converted):
            return Trivalent.FALSE
        return Trivalent.INDETERMINATE

    def _visit_BoolOp(self, node: ast.BoolOp) -> Trivalent:  # noqa: N802
        from forge_units import all_true, any_true

        values = [
            self._as_condition(operand, "operand of a boolean operator")
            for operand in node.values
        ]
        if isinstance(node.op, ast.And):
            return all_true(values)
        return any_true(values)

    def _visit_IfExp(self, node: ast.IfExp) -> Value:  # noqa: N802
        """Conditional expression with an honest treatment of the unknown case.

        When the condition is ``INDETERMINATE`` neither branch can be selected,
        so the result is the hull of both. This keeps the uncertainty in the
        value rather than silently resolving it, which is what lets a downstream
        gate report ``INCONCLUSIVE`` instead of a fabricated ``PASS``.
        """
        condition = self._as_condition(node.test, "condition of a conditional")
        if condition.is_true:
            return self.visit(node.body)
        if condition.is_false:
            return self.visit(node.orelse)

        then_value = self.visit(node.body)
        else_value = self.visit(node.orelse)
        if isinstance(then_value, Trivalent) and isinstance(else_value, Trivalent):
            return (
                then_value
                if then_value is else_value
                else Trivalent.INDETERMINATE
            )
        if isinstance(then_value, Quantity) and isinstance(else_value, Quantity):
            if then_value.dimension != else_value.dimension:
                raise ExpressionTypeError(
                    "the branches of a conditional must share a dimension when "
                    "the condition cannot be decided",
                    source=self.source,
                    span=_span(node),
                    then_unit=then_value.unit.symbol,
                    else_unit=else_value.unit.symbol,
                )
            converted = else_value.to(then_value.unit)
            return Quantity(
                then_value.magnitude.hull(converted.magnitude), then_value.unit
            )
        raise ExpressionTypeError(
            "the branches of a conditional must be of the same sort",
            source=self.source,
            span=_span(node),
        )

    # -- calls ---------------------------------------------------------
    def _visit_Call(self, node: ast.Call) -> Quantity:  # noqa: N802
        assert isinstance(node.func, ast.Name)  # guaranteed by validation
        function_name = node.func.id
        function = FUNCTION_TABLE[function_name]
        arguments = [
            self._as_quantity(argument, f"argument to {function_name}()")
            for argument in node.args
        ]
        if function_name in ("sin", "cos", "tan") and len(arguments) == 1:
            arguments = [self._an_angle_written_as_a_bare_figure(
                arguments[0], node.args[0], function_name)]
        try:
            return function(*arguments)
        except ForgeUnitsError as exc:
            raise EvaluationError(
                exc.message,
                source=self.source,
                span=_span(node),
                function=function_name,
                cause=exc.code,
                **detail_besides(
                    exc.detail, "cause", "source", "span", "function"
                ),
            ) from exc
        except (OverflowError, ZeroDivisionError, ValueError) as exc:
            raise EvaluationError(
                f"{function_name}() cannot be evaluated here: {exc}",
                source=self.source,
                span=_span(node),
                function=function_name,
            ) from exc

    def _an_angle_written_as_a_bare_figure(
        self, value: Quantity, node: ast.AST, function_name: str,
    ) -> Quantity:
        """`cos(30)`: thirty degrees, as everyone who writes it means.

        A plain number is an angle in radians, so an M8 bolt's head drawn
        `head_across_flats / cos(30)` came out 84 mm across its corners, not
        15: cos(30 radians) is 0.154. Every claim passed -- none was about
        the head -- and the bolt was released with a head the size of a
        saucer.

        Only a figure written out, with no name in it: `cos(i * step)` with
        `step = 2 * pi / n` is radians, and a name says nothing about which.
        A figure of a full turn or more is degrees -- no one writes cos(30)
        meaning thirty radians. One under a full turn could be either --
        `cos(0.5236)` is pi / 6 worked out -- and is refused, to be written
        with its unit."""
        from forge_units import is_a_plain_number

        if not is_a_plain_number(value) or any(
                isinstance(n, ast.Name) for n in ast.walk(node)):
            return value
        figure = value.magnitude
        if figure.lo == 0.0 and figure.hi == 0.0:
            return value
        if min(abs(figure.lo), abs(figure.hi)) >= 2.0 * math.pi:
            return Quantity(figure, parse_unit("deg"))
        raise EvaluationError(
            f"{function_name}() of a bare {figure.midpoint:g} could be "
            "degrees or radians. Write the unit: "
            f"`{function_name}({figure.midpoint:g} deg)`, or "
            f"`{function_name}(pi / 6)` for an angle worked in radians",
            source=self.source,
            span=_span(node),
            function=function_name,
        )

    # -- helpers -------------------------------------------------------
    def _as_quantity(self, node: ast.AST, role: str) -> Quantity:
        value = self.visit(node)
        if isinstance(value, Trivalent):
            raise ExpressionTypeError(
                f"{role} must be a quantity, not a truth value",
                source=self.source,
                span=_span(node),
            )
        return value

    def _as_condition(self, node: ast.AST, role: str) -> Trivalent:
        value = self.visit(node)
        if isinstance(value, Quantity):
            raise ExpressionTypeError(
                f"{role} must be a condition; write an explicit comparison "
                "rather than relying on a quantity being truthy",
                source=self.source,
                span=_span(node),
            )
        return value


def evaluate(
    source: str, context: Mapping[str, Quantity] | None = None
) -> Value:
    """Parse and evaluate in one step. Convenient for tests and one-off checks."""
    return Expression.parse(source).evaluate(context or {})


def free_names(source: str) -> frozenset[str]:
    """Parameter names an expression depends on, excluding units and constants."""
    return Expression.parse(source).free_names()


def iter_expressions(sources: Iterable[str]) -> list[Expression]:
    return [Expression.parse(source) for source in sources]


__all__ = [
    "Expression",
    "Value",
    "evaluate",
    "free_names",
    "iter_expressions",
    "MAX_NODES",
    "MAX_DEPTH",
]
