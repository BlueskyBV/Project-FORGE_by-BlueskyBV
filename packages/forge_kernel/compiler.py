"""The incremental ForgeIR compiler.

Pipeline, in order:

1. Resolve the parameter graph, checking dimensions and bounds.
2. Resolve each feature's parameters against that resolution, converting to the
   backend's working units (millimetres and radians).
3. Hash each feature by kind, resolved parameters, input hashes and backend
   identity.
4. Build only the features whose hash is not already in the cache.
5. Collect the semantic entities every feature published.
6. Validate those entities against the finished solid, marking any that a later
   feature buried.
7. Emit a compile trace: what was built, what was reused, what broke.

Step 4 is what makes an optimisation campaign affordable, and step 6 is what
makes a semantic reference trustworthy. Both are covered in detail in
:mod:`forge_kernel.cache` and :mod:`forge_kernel.lineage` respectively.

Failure policy
--------------
Compilation fails closed. A feature that cannot be built stops the compile and
reports which feature, which parameter, and what the backend said -- it does not
skip the feature and carry on with a part that is missing a hole. The one thing
the compiler will never do is return a solid it is not confident is the solid the
document describes.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from forge_expr import ParameterGraph, Resolution
from forge_geom import SDF, GeometryError
from forge_ir import Component, Document, Feature, feature_spec
from forge_ir.values import (
    CountValue,
    EnumValue,
    FlagValue,
    PointListValue,
    VectorValue,
)
from forge_units import detail_besides
from forge_units import Quantity, parse_unit

from .cache import CacheStatistics, ContentCache, content_hash, feature_hash
from .implicit_backend import (
    BACKEND_IDENTITY,
    BackendError,
    BuildContext,
    builder_for,
    supported_kinds,
)
from .lineage import (
    EntityStatus,
    SemanticEntity,
    SemanticGeometryMap,
    validate_entities,
)
from .products import Product, SolidProduct

_MM = parse_unit("mm")
_RAD = parse_unit("rad")


class CompileError(Exception):
    """Compilation failed at a specific feature."""

    code = "KN1200_COMPILE"

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail = dict(detail)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}

    def __str__(self) -> str:
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.detail.items()))
        return f"[{self.code}] {self.message} ({rendered})" if rendered else (
            f"[{self.code}] {self.message}"
        )


@dataclass(frozen=True, slots=True)
class FeatureTrace:
    """What happened to one feature during a compile."""

    feature_id: str
    kind: str
    content_hash: str
    reused: bool
    duration_seconds: float
    published: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature_id,
            "kind": self.kind,
            "hash": self.content_hash,
            "reused": self.reused,
            "duration_s": round(self.duration_seconds, 6),
            "published": list(self.published),
        }


@dataclass(frozen=True, slots=True)
class CompiledPart:
    """A compiled component: geometry, named geometry, and how it was produced."""

    component_id: str
    solid: SDF
    geometry_map: SemanticGeometryMap
    resolution: Resolution
    traces: tuple[FeatureTrace, ...]
    part_hash: str
    backend: str
    cache_statistics: CacheStatistics
    duration_seconds: float

    @property
    def features_built(self) -> int:
        return sum(1 for trace in self.traces if not trace.reused)

    @property
    def features_reused(self) -> int:
        return sum(1 for trace in self.traces if trace.reused)

    def buried_entities(self) -> tuple[SemanticEntity, ...]:
        return self.geometry_map.buried()

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component_id,
            "part_hash": self.part_hash,
            "backend": self.backend,
            "features_built": self.features_built,
            "features_reused": self.features_reused,
            "duration_s": round(self.duration_seconds, 6),
            "cache": self.cache_statistics.as_dict(),
            "traces": [trace.as_dict() for trace in self.traces],
            "geometry": self.geometry_map.as_dict(),
            "parameters": self.resolution.as_dict(),
        }


def _cutting_tools(component: Component) -> frozenset[str]:
    """The features a `subtract` takes away: each tool it is handed, and
    everything that tool is built from -- the extrude that cuts an opening,
    and the profile it was drawn from. Not what the body it cuts from is also
    built from: a profile both the plate and its cutter read is the plate's.

    Their faces are on the part only where they met material, which is what
    `validate_entities` needs to know to judge them.
    """
    try:
        by_id = {f.identifier: f for f in component.features}
    except Exception:  # noqa: BLE001 - a graph that cannot be walked has none
        return frozenset()

    def upstream(names: Any) -> set[str]:
        seen: set[str] = set()
        stack = [str(n) for n in names]
        while stack:
            name = stack.pop()
            if name in seen or name not in by_id:
                continue
            seen.add(name)
            stack.extend(str(n) for n in (by_id[name].inputs or ()))
        return seen

    tools: set[str] = set()
    for feature in component.features:
        if feature.kind == "hole":
            # A hole is a cutter too: its bore is on the part only where it
            # passed through material -- both ears of a clevis and not the
            # gap between, the last millimetre under a deep counterbore.
            tools.add(feature.identifier)
            continue
        if feature.kind != "subtract" or len(feature.inputs or ()) < 2:
            continue
        inputs = list(feature.inputs)
        tools |= upstream(inputs[1:]) - upstream(inputs[:1])
    return frozenset(tools)


class Compiler:
    """Compiles components, reusing work across calls.

    A single instance is intended to be held for the life of an optimisation
    campaign or an interactive session, so that its cache spans every rebuild.
    """

    __slots__ = ("_cache", "_backend_identity")

    def __init__(
        self, *, cache_capacity: int = 8192, backend_identity: str = BACKEND_IDENTITY
    ) -> None:
        self._cache: ContentCache[Product] = ContentCache(capacity=cache_capacity)
        self._backend_identity = backend_identity

    @property
    def cache_statistics(self) -> CacheStatistics:
        return self._cache.statistics

    def reset_cache(self) -> None:
        self._cache.clear()

    # ------------------------------------------------------------------
    # Compilation
    # ------------------------------------------------------------------
    def compile_component(
        self,
        component: Component,
        *,
        overrides: Mapping[str, Quantity] | None = None,
        validate_geometry: bool = True,
    ) -> CompiledPart:
        started = time.perf_counter()

        try:
            resolution = component.parameters.resolve(overrides)
        except Exception as exc:
            raise CompileError(
                f"parameter resolution failed: {exc}",
                component=component.identifier,
            ) from exc

        out_of_bounds = resolution.out_of_bounds()
        if out_of_bounds:
            raise CompileError(
                "one or more parameters are outside their declared bounds",
                component=component.identifier,
                parameters=[p.identifier for p in out_of_bounds],
                values=[str(p.value) for p in out_of_bounds],
                hint="bounds are part of the design contract; widen them "
                "deliberately or change the value",
            )

        products: dict[str, Product] = {}
        hashes: dict[str, str] = {}
        traces: list[FeatureTrace] = []

        for feature in component.features:
            trace = self._compile_feature(
                feature, resolution, products, hashes, component.identifier
            )
            traces.append(trace)

        body_id = component.body_feature
        body = products[body_id]
        if not isinstance(body, SolidProduct):
            raise CompileError(
                "the terminal feature did not produce a solid",
                component=component.identifier,
                feature=body_id,
                got=body.kind,
            )

        entities = list(body.entities)
        if validate_geometry:
            entities = list(validate_entities(
                body.solid, entities, cutters=_cutting_tools(component)))

        geometry_map = SemanticGeometryMap(entities)

        part_hash = content_hash(
            "part", component.identifier, hashes[body_id], self._backend_identity
        )

        return CompiledPart(
            component_id=component.identifier,
            solid=body.solid,
            geometry_map=geometry_map,
            resolution=resolution,
            traces=tuple(traces),
            part_hash=part_hash,
            backend=self._backend_identity,
            cache_statistics=self._cache.statistics,
            duration_seconds=time.perf_counter() - started,
        )

    def compile_document(
        self,
        document: Document,
        *,
        overrides: Mapping[str, Mapping[str, Quantity]] | None = None,
    ) -> dict[str, CompiledPart]:
        overrides = overrides or {}
        return {
            component.identifier: self.compile_component(
                component, overrides=overrides.get(component.identifier)
            )
            for component in document.components
        }

    # ------------------------------------------------------------------
    # Per-feature
    # ------------------------------------------------------------------
    def _compile_feature(
        self,
        feature: Feature,
        resolution: Resolution,
        products: dict[str, Product],
        hashes: dict[str, str],
        component_id: str,
    ) -> FeatureTrace:
        started = time.perf_counter()

        resolved = _resolve_feature_parameters(feature, resolution, component_id)
        input_hashes = tuple(hashes[source] for source in feature.inputs)
        key = feature_hash(
            kind=feature.kind,
            resolved_parameters=resolved,
            input_hashes=input_hashes,
            backend_identity=self._backend_identity,
        )
        hashes[feature.identifier] = key

        # Looked up by content AND by the feature's own identity. A product
        # carries the entities it published -- named `role.suffix`, with
        # tokens derived from the feature id -- so a second feature with the
        # same kind, parameters and inputs (two XY datum planes, two
        # identical bosses) served from the first's entry published the
        # first's names, and `sketch_b.frame` resolved to nothing: a
        # SelectionError on a valid reference. The content hash still feeds
        # the part hash and every downstream input hash unchanged, so
        # nothing about a part's identity moves; only the cache stops
        # handing one feature another feature's geometry.
        cache_key = content_hash("product", key, feature.identifier,
                                 feature.role or "")
        cached = self._cache.get(cache_key)
        if cached is not None:
            products[feature.identifier] = cached
            return FeatureTrace(
                feature_id=feature.identifier,
                kind=feature.kind,
                content_hash=key,
                reused=True,
                duration_seconds=time.perf_counter() - started,
                published=tuple(e.name for e in cached.entities),
            )

        context = BuildContext(
            feature_id=feature.identifier,
            kind=feature.kind,
            role=feature.role,
            parameters=resolved,
            inputs=[products[source] for source in feature.inputs],
        )

        try:
            product = builder_for(feature.kind)(context)
        except (GeometryError, BackendError) as exc:
            raise CompileError(
                f"feature could not be built: {exc.message}",
                component=component_id,
                feature=feature.identifier,
                kind=feature.kind,
                pointer=feature.pointer,
                backend_code=exc.code,
                **detail_besides(
                    exc.detail, "backend_code", "component", "feature", "kind",
                    "pointer",
                ),
            ) from exc
        except Exception as exc:  # noqa: BLE001 - surface as a compile failure
            raise CompileError(
                f"feature could not be built: {exc}",
                component=component_id,
                feature=feature.identifier,
                kind=feature.kind,
                pointer=feature.pointer,
                error_type=type(exc).__name__,
            ) from exc

        self._cache.put(cache_key, product)
        products[feature.identifier] = product
        return FeatureTrace(
            feature_id=feature.identifier,
            kind=feature.kind,
            content_hash=key,
            reused=False,
            duration_seconds=time.perf_counter() - started,
            published=tuple(e.name for e in product.entities),
        )


# ----------------------------------------------------------------------
# Parameter resolution
# ----------------------------------------------------------------------
def _resolve_feature_parameters(
    feature: Feature, resolution: Resolution, component_id: str
) -> dict[str, Any]:
    """Evaluate a feature's parameters into plain backend values.

    Lengths arrive as millimetres and angles as radians, because those are the
    backend's working units. The conversion happens exactly once, here, at the
    boundary between the unit-typed world and the numeric one, so no builder
    ever has to wonder what units it was handed.
    """
    spec = feature.spec
    resolved: dict[str, Any] = {}

    for name, value in feature.parameters.items():
        parameter_spec = spec.parameter(name)
        if parameter_spec is None:  # pragma: no cover - decoder rejects these
            continue
        try:
            resolved[name] = _resolve_one(value, parameter_spec.sort, resolution)
        except Exception as exc:
            raise CompileError(
                f"could not resolve feature parameter: {exc}",
                component=component_id,
                feature=feature.identifier,
                kind=feature.kind,
                parameter=name,
                sort=parameter_spec.sort,
                pointer=feature.pointer,
            ) from exc

        if parameter_spec.minimum is not None:
            numeric = resolved[name]
            if isinstance(numeric, float) and numeric < parameter_spec.minimum:
                raise CompileError(
                    "feature parameter is below its permitted minimum",
                    component=component_id,
                    feature=feature.identifier,
                    parameter=name,
                    value=numeric,
                    minimum=parameter_spec.minimum,
                )
    return resolved


def _resolve_one(value: Any, sort: str, resolution: Resolution) -> Any:
    if isinstance(value, CountValue):
        # Passed the resolution, because a count may now be driven by a
        # parameter. A literal one ignores it.
        return value.resolve(resolution)
    if isinstance(value, FlagValue):
        return value.resolve()
    if isinstance(value, EnumValue):
        return value.resolve()
    if isinstance(value, PointListValue):
        return value.resolve_lengths(resolution, unit="mm")
    if isinstance(value, VectorValue):
        if sort == "direction":
            return value.resolve_direction(resolution)
        return value.resolve_displacement(resolution, unit="mm")

    quantity = value.resolve(resolution)
    if sort == "angle":
        return _to_radians(quantity)
    if sort == "length":
        return quantity.to(_MM).magnitude.midpoint
    if sort == "dimensionless":
        return quantity.to(parse_unit("")).magnitude.midpoint
    return quantity.magnitude.midpoint


def _to_radians(quantity: Quantity) -> float:
    """Convert an angle to radians.

    Angles are dimensionless in the SI base, so an angle parameter given without
    a unit is interpreted as radians -- the mathematically natural reading, and
    the one the trigonometric functions already use.
    """
    return quantity.to(_RAD).magnitude.midpoint


# ----------------------------------------------------------------------
# Convenience
# ----------------------------------------------------------------------
def compile_component(
    component: Component,
    *,
    overrides: Mapping[str, Quantity] | None = None,
) -> CompiledPart:
    """Compile once with a throwaway cache. Prefer holding a :class:`Compiler`."""
    return Compiler().compile_component(component, overrides=overrides)


def backend_capabilities() -> dict[str, Any]:
    """What this backend can and cannot do, for the truthful capability matrix."""
    from forge_ir import FEATURE_KINDS

    supported = set(supported_kinds())
    return {
        "identity": BACKEND_IDENTITY,
        "representation": "implicit signed distance field",
        "supported_features": sorted(supported),
        "unsupported_features": sorted(set(FEATURE_KINDS) - supported),
        "exports": ["stl", "obj"],
        "cannot": [
            "STEP export (requires B-Rep topology)",
            "Fusion feature-tree reconstruction",
            "exact analytic volume (measurements are rigorous enclosures, "
            "not closed-form values)",
            "named faces in the B-Rep sense (entities are analytic, not "
            "topological)",
        ],
    }


__all__ = [
    "Compiler",
    "CompiledPart",
    "FeatureTrace",
    "CompileError",
    "compile_component",
    "backend_capabilities",
]
