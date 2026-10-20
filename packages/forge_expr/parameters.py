"""The parameter dependency graph.

A design's parameters form a directed acyclic graph: some are free values the
engineer sets, others are expressions over the free ones. Resolving the graph
means evaluating every parameter in dependency order, checking as it goes that
each result has the dimension its declaration promised and lies inside its
declared bounds.

Three properties are load-bearing for the rest of Forge:

**Cycles are reported as paths, not as recursion errors.** ``a = b + 1``,
``b = a * 2`` produces a diagnostic naming the cycle ``a -> b -> a``, which is
what a repair strategy needs in order to act.

**Resolution order is deterministic.** Ties in the topological sort are broken
alphabetically, so the same document always resolves in the same order. This
matters because the resolution order participates in the compiler's cache key,
and a nondeterministic order would defeat caching.

**Bounds are checked three-valuedly.** A parameter whose uncertainty straddles
its own bound is neither in nor out of range; the resolution records that as an
indeterminate bound check rather than silently accepting or rejecting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, Mapping, Sequence

from forge_units import (
    CONSTANT_TABLE,
    Dimension,
    Interval,
    Quantity,
    Trivalent,
    Unit,
    known_units,
    parse_unit,
)

from .errors import (
    ParameterCycleError,
    ParameterResolutionError,
    ReservedNameError,
)
from .expression import Expression

#: Names that cannot be used as parameter identifiers.
#:
#: Only the named mathematical and physical constants are reserved. Unit symbols
#: are deliberately *not* reserved: ``t`` for thickness, ``L`` for length and
#: ``h`` for height are the natural names for those quantities, and forbidding
#: them because the registry also knows a tonne, a litre and an hour would make
#: the language unpleasant to write for no safety gain. A declared parameter
#: shadows a unit of the same name during evaluation, which is the behaviour an
#: engineer who wrote ``t = 6 mm`` expects.
#:
#: The residual hazard -- an author writing ``5 * t`` intending tonnes in a
#: document that declares a thickness ``t`` -- is surfaced rather than
#: prevented: :meth:`ParameterGraph.shadowed_units` reports every such collision
#: so the UI and the assurance report can show it.
RESERVED_NAMES: frozenset[str] = frozenset(CONSTANT_TABLE)


@dataclass(frozen=True, slots=True)
class ParameterBounds:
    """Optimisation and validity bounds on a parameter."""

    minimum: Quantity | None = None
    maximum: Quantity | None = None

    def check(self, value: Quantity) -> Trivalent:
        from forge_units import all_true

        checks: list[Trivalent] = []
        if self.minimum is not None:
            checks.append(value.at_least(self.minimum))
        if self.maximum is not None:
            checks.append(value.at_most(self.maximum))
        return all_true(checks)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.minimum is not None:
            payload["min"] = self.minimum.as_dict()
        if self.maximum is not None:
            payload["max"] = self.maximum.as_dict()
        return payload


@dataclass(frozen=True, slots=True)
class Parameter:
    """A named design parameter: either a literal quantity or an expression.

    Attributes
    ----------
    identifier:
        Stable name, referenced from expressions and from feature parameters.
    value:
        A literal quantity. Mutually exclusive with ``expression``.
    expression:
        A dimension-checked expression over other parameters. Mutually exclusive
        with ``value``.
    unit:
        The unit the resolved value is converted into. For an expression this is
        also a *check*: if the expression's natural dimension does not match, the
        parameter fails to resolve. Declaring it is how a design states its
        dimensional intent, so that a unit slip is caught at the declaration
        rather than three features later.
    bounds:
        Optional validity / optimisation range.
    optimizable:
        Whether the optimiser may vary this parameter. Only free parameters
        (those with a literal ``value``) can be optimisable; varying a derived
        parameter would contradict its own expression.
    description:
        Human-readable intent, carried into reports.
    """

    identifier: str
    value: Quantity | None = None
    expression: Expression | None = None
    unit: Unit | None = None
    bounds: ParameterBounds | None = None
    optimizable: bool = False
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if (self.value is None) == (self.expression is None):
            raise ParameterResolutionError(
                "a parameter must have exactly one of a literal value or an "
                "expression",
                parameter=self.identifier,
                has_value=self.value is not None,
                has_expression=self.expression is not None,
            )
        if self.identifier in RESERVED_NAMES:
            raise ReservedNameError(
                "parameter name shadows a named constant",
                parameter=self.identifier,
                reserved=sorted(RESERVED_NAMES),
                hint="rename the parameter; shadowing 'pi' or 'g0' would make "
                "every expression using that constant mean something else",
            )
        if not self.identifier.isidentifier():
            raise ParameterResolutionError(
                "parameter name is not a valid identifier",
                parameter=self.identifier,
            )
        if self.optimizable and self.expression is not None:
            raise ParameterResolutionError(
                "a derived parameter cannot be optimisable; the optimiser would "
                "have to contradict its defining expression",
                parameter=self.identifier,
                expression=str(self.expression),
            )

    @property
    def is_free(self) -> bool:
        return self.value is not None

    @property
    def is_derived(self) -> bool:
        return self.expression is not None

    def referenced_names(self) -> frozenset[str]:
        """Every name the defining expression mentions, constants excluded.

        This is a superset of the true dependencies, because a name here may
        turn out to be a unit symbol rather than a parameter. Only
        :class:`ParameterGraph` knows which, so only it can narrow the set.
        """
        if self.expression is None:
            return frozenset()
        return self.expression.free_names()

    # -- convenience constructors --------------------------------------
    @classmethod
    def literal(
        cls,
        identifier: str,
        value: Quantity,
        *,
        minimum: Quantity | None = None,
        maximum: Quantity | None = None,
        optimizable: bool = False,
        description: str = "",
        tags: Sequence[str] = (),
    ) -> "Parameter":
        bounds = (
            ParameterBounds(minimum, maximum)
            if (minimum is not None or maximum is not None)
            else None
        )
        return cls(
            identifier=identifier,
            value=value,
            unit=value.unit,
            bounds=bounds,
            optimizable=optimizable,
            description=description,
            tags=tuple(tags),
        )

    @classmethod
    def derived(
        cls,
        identifier: str,
        expression: str,
        unit: str | Unit | None = None,
        *,
        minimum: Quantity | None = None,
        maximum: Quantity | None = None,
        description: str = "",
        tags: Sequence[str] = (),
    ) -> "Parameter":
        bounds = (
            ParameterBounds(minimum, maximum)
            if (minimum is not None or maximum is not None)
            else None
        )
        resolved_unit = (
            parse_unit(unit) if isinstance(unit, str) else unit
        )
        return cls(
            identifier=identifier,
            expression=Expression.parse(expression),
            unit=resolved_unit,
            bounds=bounds,
            description=description,
            tags=tuple(tags),
        )


@dataclass(frozen=True, slots=True)
class ResolvedParameter:
    """The outcome of resolving one parameter."""

    identifier: str
    value: Quantity
    within_bounds: Trivalent
    is_free: bool
    source_expression: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.identifier,
            "value": self.value.as_dict(),
            "within_bounds": str(self.within_bounds),
            "is_free": self.is_free,
            "expression": self.source_expression,
        }


@dataclass(frozen=True, slots=True)
class Resolution:
    """The full result of resolving a parameter graph."""

    values: Mapping[str, Quantity]
    parameters: Mapping[str, ResolvedParameter]
    order: tuple[str, ...]

    def __getitem__(self, identifier: str) -> Quantity:
        try:
            return self.values[identifier]
        except KeyError:
            raise ParameterResolutionError(
                "parameter is not present in this resolution",
                parameter=identifier,
                available=sorted(self.values)[:40],
            ) from None

    def __contains__(self, identifier: str) -> bool:
        return identifier in self.values

    def __iter__(self) -> Iterator[str]:
        return iter(self.order)

    def out_of_bounds(self) -> tuple[ResolvedParameter, ...]:
        return tuple(
            parameter
            for parameter in self.parameters.values()
            if parameter.within_bounds.is_false
        )

    def indeterminate_bounds(self) -> tuple[ResolvedParameter, ...]:
        return tuple(
            parameter
            for parameter in self.parameters.values()
            if not parameter.within_bounds.is_known
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "order": list(self.order),
            "parameters": [
                self.parameters[identifier].as_dict() for identifier in self.order
            ],
        }


class ParameterGraph:
    """An ordered collection of parameters that resolves in dependency order."""

    __slots__ = ("_parameters",)

    def __init__(self, parameters: Iterable[Parameter] = ()) -> None:
        self._parameters: dict[str, Parameter] = {}
        for parameter in parameters:
            self.add(parameter)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def add(self, parameter: Parameter) -> "ParameterGraph":
        if parameter.identifier in self._parameters:
            raise ParameterResolutionError(
                "duplicate parameter identifier",
                parameter=parameter.identifier,
            )
        self._parameters[parameter.identifier] = parameter
        return self

    def __contains__(self, identifier: str) -> bool:
        return identifier in self._parameters

    def __len__(self) -> int:
        return len(self._parameters)

    def __getitem__(self, identifier: str) -> Parameter:
        return self._parameters[identifier]

    def identifiers(self) -> tuple[str, ...]:
        return tuple(sorted(self._parameters))

    def free_parameters(self) -> tuple[Parameter, ...]:
        return tuple(
            self._parameters[identifier]
            for identifier in sorted(self._parameters)
            if self._parameters[identifier].is_free
        )

    def optimizable_parameters(self) -> tuple[Parameter, ...]:
        return tuple(p for p in self.free_parameters() if p.optimizable)

    # ------------------------------------------------------------------
    # Dependency analysis
    # ------------------------------------------------------------------
    def dependencies_of(self, identifier: str) -> frozenset[str]:
        """The declared parameters ``identifier`` actually depends on.

        A name mentioned by the expression is a dependency exactly when it is a
        declared parameter. Anything else must be a unit symbol, and that is
        checked by :meth:`validate_names` rather than assumed.
        """
        referenced = self._parameters[identifier].referenced_names()
        return frozenset(name for name in referenced if name in self._parameters)

    def validate_names(self) -> None:
        """Confirm every referenced name is a parameter or a resolvable unit.

        Called before ordering so that a typo is reported as a missing
        dependency with the offending name, rather than surfacing later as an
        unknown-name failure midway through evaluation.
        """
        for identifier in sorted(self._parameters):
            parameter = self._parameters[identifier]
            if parameter.expression is None:
                continue
            for name in sorted(parameter.referenced_names()):
                if name in self._parameters:
                    continue
                try:
                    parse_unit(name)
                except Exception:  # noqa: BLE001 - any unit failure means unknown
                    raise ParameterResolutionError(
                        "expression references a name that is neither a declared "
                        "parameter nor a known unit",
                        parameter=identifier,
                        missing=name,
                        expression=str(parameter.expression),
                        available=sorted(self._parameters)[:40],
                    ) from None

    def shadowed_units(self) -> Mapping[str, str]:
        """Parameters whose name also names a unit, mapped to that unit symbol.

        Shadowing is permitted and usually intended -- ``t`` almost always means
        thickness, not tonnes -- but it is reported so that the design workspace
        and the assurance report can show it, and so a reviewer can notice when
        a document really did mean the unit.
        """
        registry = known_units()
        return {
            identifier: identifier
            for identifier in sorted(self._parameters)
            if identifier in registry
        }

    # ------------------------------------------------------------------
    # Ordering
    # ------------------------------------------------------------------
    def topological_order(self) -> tuple[str, ...]:
        """Dependency order, with alphabetical tie-breaking for determinism.

        Uses an explicit stack rather than recursion so that a pathological
        graph produces a cycle diagnostic instead of a ``RecursionError``.
        """
        self.validate_names()
        white, grey, black = 0, 1, 2
        colour: dict[str, int] = {name: white for name in self._parameters}
        order: list[str] = []
        # Path stack carries the current DFS chain so a detected cycle can be
        # reported as the actual sequence of parameters involved.
        for root in sorted(self._parameters):
            if colour[root] != white:
                continue
            stack: list[tuple[str, Iterator[str]]] = [
                (root, iter(self._sorted_dependencies(root)))
            ]
            colour[root] = grey
            path: list[str] = [root]
            while stack:
                node, dependencies = stack[-1]
                advanced = False
                for dependency in dependencies:
                    state = colour[dependency]
                    if state == grey:
                        cycle_start = path.index(dependency)
                        cycle = path[cycle_start:] + [dependency]
                        raise ParameterCycleError(
                            "parameter definitions form a cycle",
                            cycle=cycle,
                            rendered=" -> ".join(cycle),
                        )
                    if state == white:
                        colour[dependency] = grey
                        path.append(dependency)
                        stack.append(
                            (dependency, iter(self._sorted_dependencies(dependency)))
                        )
                        advanced = True
                        break
                if advanced:
                    continue
                stack.pop()
                colour[node] = black
                order.append(node)
                if path and path[-1] == node:
                    path.pop()
        return tuple(order)

    def _sorted_dependencies(self, identifier: str) -> list[str]:
        return sorted(self.dependencies_of(identifier))

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def resolve(
        self, overrides: Mapping[str, Quantity] | None = None
    ) -> Resolution:
        """Evaluate every parameter in dependency order.

        ``overrides`` replaces the literal value of free parameters, which is how
        the optimiser explores a design space without rewriting the document.
        Overriding a derived parameter is refused, because doing so would make
        the document inconsistent with itself.
        """
        overrides = dict(overrides or {})
        for identifier in overrides:
            parameter = self._parameters.get(identifier)
            if parameter is None:
                raise ParameterResolutionError(
                    "override names a parameter that does not exist",
                    parameter=identifier,
                    available=sorted(self._parameters)[:40],
                )
            if parameter.is_derived:
                raise ParameterResolutionError(
                    "cannot override a derived parameter; it is defined by its "
                    "expression",
                    parameter=identifier,
                    expression=str(parameter.expression),
                )

        order = self.topological_order()
        values: dict[str, Quantity] = {}
        resolved: dict[str, ResolvedParameter] = {}

        for identifier in order:
            parameter = self._parameters[identifier]
            if parameter.is_free:
                value = overrides.get(identifier, parameter.value)
                assert value is not None
                if parameter.unit is not None:
                    value = _convert_checked(value, parameter.unit, parameter)
            else:
                assert parameter.expression is not None
                try:
                    value = parameter.expression.evaluate_quantity(values)
                except Exception as exc:
                    raise ParameterResolutionError(
                        f"failed to evaluate parameter '{identifier}': {exc}",
                        parameter=identifier,
                        expression=str(parameter.expression),
                    ) from exc
                if parameter.unit is not None:
                    value = _convert_checked(value, parameter.unit, parameter)

            within = (
                parameter.bounds.check(value)
                if parameter.bounds is not None
                else Trivalent.TRUE
            )
            values[identifier] = value
            resolved[identifier] = ResolvedParameter(
                identifier=identifier,
                value=value,
                within_bounds=within,
                is_free=parameter.is_free,
                source_expression=(
                    str(parameter.expression) if parameter.expression else None
                ),
            )

        return Resolution(values=values, parameters=resolved, order=order)

    # ------------------------------------------------------------------
    # Impact analysis
    # ------------------------------------------------------------------
    def dependents_of(self, identifier: str) -> frozenset[str]:
        """Every parameter whose value depends, transitively, on ``identifier``.

        This is what tells the incremental compiler which part of the feature
        graph a parameter change actually dirties, and it is what the UI uses to
        show which evidence a proposed edit would invalidate.
        """
        if identifier not in self._parameters:
            raise ParameterResolutionError(
                "unknown parameter", parameter=identifier
            )
        reverse: dict[str, set[str]] = {name: set() for name in self._parameters}
        for name in self._parameters:
            for dependency in self.dependencies_of(name):
                reverse[dependency].add(name)

        seen: set[str] = set()
        frontier = [identifier]
        while frontier:
            current = frontier.pop()
            for dependent in reverse.get(current, ()):
                if dependent not in seen:
                    seen.add(dependent)
                    frontier.append(dependent)
        return frozenset(seen)

    def as_dict(self) -> dict[str, object]:
        return {
            "parameters": [
                {
                    "id": parameter.identifier,
                    "value": parameter.value.as_dict() if parameter.value else None,
                    "expression": (
                        str(parameter.expression) if parameter.expression else None
                    ),
                    "unit": parameter.unit.symbol if parameter.unit else None,
                    "bounds": parameter.bounds.as_dict() if parameter.bounds else {},
                    "optimizable": parameter.optimizable,
                    "description": parameter.description,
                    "tags": list(parameter.tags),
                }
                for parameter in (
                    self._parameters[name] for name in sorted(self._parameters)
                )
            ]
        }


def _convert_checked(
    value: Quantity, unit: Unit, parameter: Parameter
) -> Quantity:
    from forge_units import a_plain_number_in

    # A plain number in a slot declared in degrees is that many degrees, not
    # that many radians converted: see `a_plain_number_in`.
    read = a_plain_number_in(
        value, unit, str(parameter.expression) if parameter.expression else "")
    if read is not None:
        return read
    if value.dimension != unit.dimension:
        raise ParameterResolutionError(
            "parameter value does not have the dimension its declaration promises",
            parameter=parameter.identifier,
            declared_unit=unit.symbol,
            declared_measures=unit.dimension.describe(),
            actual_unit=value.unit.symbol,
            actual_measures=value.dimension.describe(),
            expression=(
                str(parameter.expression) if parameter.expression else None
            ),
        )
    return value.to(unit)


__all__ = [
    "Parameter",
    "ParameterBounds",
    "ParameterGraph",
    "ResolvedParameter",
    "Resolution",
    "RESERVED_NAMES",
]
