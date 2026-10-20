"""forge_expr - safe, dimension-checked expressions and the parameter graph.

Design expressions come from two untrusted sources: language models, and files
that users import. This package is the boundary that makes them safe to evaluate
and meaningful to check.

Safety is structural rather than heuristic. The expression is parsed with
:mod:`ast`, walked once against a closed allowlist of node types, and only then
interpreted. ``eval`` is never called, so there is no sandbox to escape: the
interpreter simply has no implementation for attribute access, imports,
subscripting or calls to anything outside a vetted table of nineteen
dimensionally aware functions.

Meaning comes from :mod:`forge_units`. Every value is a quantity with a unit and
an interval, so an expression over tolerance-bearing parameters produces a
tolerance-bearing result without anyone writing propagation code, and a
dimensional slip fails at the token that caused it.

>>> from forge_units import Q
>>> from forge_expr import Parameter, ParameterGraph
>>> graph = ParameterGraph([
...     Parameter.literal("ear_thickness", Q(6.0, "mm")),
...     Parameter.literal("ear_gap", Q(12.0, "mm")),
...     Parameter.derived("outer_width", "ear_gap + 2 * ear_thickness", "mm"),
... ])
>>> graph.resolve()["outer_width"].to("mm").magnitude.midpoint
24.0
"""

from __future__ import annotations

from .errors import (
    ArityError,
    DisallowedConstructError,
    EvaluationError,
    ExpressionComplexityError,
    ExpressionSyntaxError,
    ExpressionTypeError,
    ForgeExprError,
    ParameterCycleError,
    ParameterResolutionError,
    ReservedNameError,
    UnknownFunctionError,
    UnknownNameError,
)
from .expression import (
    MAX_DEPTH,
    MAX_NODES,
    Expression,
    Value,
    evaluate,
    free_names,
    iter_expressions,
)
from .parameters import (
    RESERVED_NAMES,
    Parameter,
    ParameterBounds,
    ParameterGraph,
    Resolution,
    ResolvedParameter,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Expression",
    "Value",
    "evaluate",
    "free_names",
    "iter_expressions",
    "MAX_NODES",
    "MAX_DEPTH",
    "Parameter",
    "ParameterBounds",
    "ParameterGraph",
    "Resolution",
    "ResolvedParameter",
    "RESERVED_NAMES",
    "ForgeExprError",
    "ExpressionSyntaxError",
    "DisallowedConstructError",
    "UnknownNameError",
    "UnknownFunctionError",
    "ArityError",
    "ExpressionTypeError",
    "ExpressionComplexityError",
    "ParameterCycleError",
    "ParameterResolutionError",
    "ReservedNameError",
    "EvaluationError",
]
