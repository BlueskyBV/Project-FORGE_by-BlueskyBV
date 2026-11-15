"""The exact kernel's build: a ForgeIR v2 component, step by step, each validated, after-checked and named (docs/V2-stage3.md, 7.1).

1. The component's parameters, and each step's, are resolved by the same
   resolver the implicit kernel uses: lengths in mm, angles in radians.
2. In the graph's order, each step is looked up in the cache, or built,
   validated, after-checked and named, and stored.
3. The terminal step is the part; V1's published names are found on it.

The build fails closed: a step OpenCascade refuses, that is invalid, or that
fails its after-check stops the build with an :class:`~forge_occ.errors.OccError`
naming the component, the step, its operation, its pointer and the spec items
it builds. Nothing is skipped, retried, or repaired.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from forge_ir import Component, Feature
from forge_ir.v2 import DocumentV2, Step
from forge_kernel import compile_products, resolve_feature_parameters
from forge_units import Quantity

from .aftercheck import check_step, validate
from .cache import StepCache, step_key
from .errors import DesignError, OccError, RefError, UnsupportedOpError
from .names import Names
from .occt import OCCT_VERSION, boundary, faces, solids, volume
from .ops import BUILDERS
from .ops.sketch import BUILDERS as SKETCH_BUILDERS
from .products import Context, Product, SolidProduct

__all__ = ["BACKEND_IDENTITY", "BuildResult", "OccBackend", "Trace"]

BACKEND_IDENTITY = f"occt-{OCCT_VERSION}/forge-occ-2"


@dataclass(frozen=True)
class Trace:
    """What happened at one step."""

    step: str
    op: str
    reused: bool
    seconds: float
    volume: float | None = None
    solids: int | None = None
    faces: int | None = None
    notes: tuple[str, ...] = ()
    lost: tuple[str, ...] = ()
    tolerance: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"step": self.step, "op": self.op, "reused": self.reused,
                               "seconds": round(self.seconds, 6)}  # fmt: skip
        for name in ("volume", "solids", "faces"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name)
        if self.notes:
            out["notes"] = list(self.notes)
        if self.lost:
            out["lost"] = list(self.lost)
        if self.tolerance:
            out["tolerance"] = self.tolerance
        return out


@dataclass(frozen=True)
class BuildResult:
    """A built part: its solid, its faces' names, each step's trace, and every step's product."""

    component: str
    shape: Any
    names: Names
    traces: tuple[Trace, ...]
    products: Mapping[str, Product] = field(repr=False)
    backend: str = BACKEND_IDENTITY

    @property
    def solids(self) -> int:
        return len(solids(self.shape))

    def published(self, component: Component) -> dict[str, list[Any]]:
        """V1's published names (``role.suffix``) that name faces, and the faces they name on the part (the original copy)."""
        out: dict[str, list[Any]] = {}
        for feature in component.features:
            prefix = feature.role or feature.identifier
            for output in feature.spec.emits if feature.kind in _V1_KINDS else ():
                found = self.names.faces_named(
                    feature.identifier, output.suffix, copy=0
                )
                if found:
                    out[f"{prefix}.{output.suffix}"] = found
        return out


_V1_KINDS = frozenset(BUILDERS) - {"fillet", "chamfer"}


class OccBackend:
    """Builds ForgeIR v2 components with OpenCascade."""

    name = "occ"
    version = BACKEND_IDENTITY

    def build(
        self,
        document: DocumentV2,
        component: str,
        *,
        overrides: Mapping[str, Quantity] | None = None,
        cache: StepCache | None = None,
    ) -> BuildResult:
        part = document.component(component)
        where = {"component": component}
        try:
            resolution = part.parameters.resolve(overrides)
        except Exception as error:  # every resolution failure is the document's
            raise DesignError(
                f"the parameters can't be resolved: {error}", **where
            ) from error
        out_of_bounds = resolution.out_of_bounds()
        if out_of_bounds:
            raise DesignError("parameters are outside their declared bounds", **where,
                              parameters=[p.identifier for p in out_of_bounds])  # fmt: skip
        v1 = _V1Products(document, component, overrides)
        products: dict[str, Product] = {}
        keys: dict[str, str] = {}
        traces: list[Trace] = []
        for step in document.steps(component):
            started = time.perf_counter()
            detail: dict[str, Any] = {
                **where,
                "step": step.id,
                "op": step.op,
                "pointer": step.pointer,
            }
            if step.for_items:
                detail["for_items"] = list(step.for_items)
            try:
                product, keys[step.id], reused = self._step(
                    step, resolution, part, products, keys, v1, cache
                )
            except RefError as error:
                raise _buried(error, traces).where(**detail) from None
            except OccError as error:
                raise error.where(**detail) from None
            products[step.id] = product
            traces.append(_trace(step, product, time.perf_counter() - started, reused))
        body = products[part.body_feature]
        if not isinstance(body, SolidProduct):
            raise DesignError(
                "the terminal step made no solid", **where, step=part.body_feature
            )
        return BuildResult(component, body.shape, body.names, tuple(traces), products)

    def _step(self, step: Step, resolution: Any, part: Component, products: Mapping[str, Product],
              keys: Mapping[str, str], v1: _V1Products, cache: StepCache | None) -> tuple[Product, str, bool]:  # fmt: skip
        """The step's product, its key, and whether it came from the cache."""
        builder = BUILDERS.get(step.op)
        if builder is None:
            raise UnsupportedOpError(
                "the exact kernel has no builder for this operation", op=step.op
            )
        feature = step.feature if not step.v2_only else Feature(
            identifier=step.id, kind=step.op, inputs=step.inputs, parameters=step.params,
            role=step.role, pointer=step.pointer)  # fmt: skip
        try:
            params = resolve_feature_parameters(
                feature, resolution, part.identifier, spec=step.spec
            )
        except Exception as error:  # V1's resolver raises its own CompileError
            raise DesignError(f"a parameter can't be resolved: {error}") from error
        params = {**params, **step.strings}  # a line of letters' text, as written
        context = Context(
            step=step.id, op=step.op, role=step.publishes_as, params=params,
            inputs=tuple(products[i] for i in step.inputs),
            v1=v1.products if step.op in _FROM_V1 else None,
            input_ids=step.inputs, references=step.references,
        )  # fmt: skip
        key = step_key(
            identity=BACKEND_IDENTITY, op=step.op, step=step.id, role=step.publishes_as, params=params,
            references=step.references, inputs=[keys[i] for i in step.inputs], v1=_v1_envelopes(context),
        )  # fmt: skip
        if cache is not None and step.op not in _NOT_CACHED:
            found = cache.get(key)
            if found is not None:
                return found, key, True
        # OpenCascade raising anywhere in the step (not only where a builder expects it) fails the step
        # with what it said, rather than escaping as the bindings' own exception.
        with boundary(f"a {step.op}"):
            product = builder(context)
            if isinstance(product, SolidProduct):
                validate(product.shape)
                check_step(step.op, params, context.inputs, product)
        if isinstance(product, SolidProduct):
            if product.names.shape is not product.shape:
                product = replace(product, names=product.names.on(product.shape))
            if cache is not None:
                cache.put(key, product)
        return product, key, False


def _buried(error: RefError, traces: list[Trace]) -> RefError:
    """A reference's error, saying which earlier step buried the faces it names (section 9.2)."""
    named = error.detail.get("named") or ()
    buried = {name: t.step for name in named for t in traces if name in t.lost}
    if buried:
        error.detail["buried_by"] = buried
        error.message += "; " + "; ".join(
            f"{name} was buried by step {step}" for name, step in sorted(buried.items())
        )
    return error


#: The operations that take V1's envelopes (7.4).
_FROM_V1 = frozenset({"hole", "bend"})
#: The operations that make no solid (datums, profiles): nothing worth caching.
_NOT_CACHED = frozenset(SKETCH_BUILDERS)


def _v1_envelopes(context: Context) -> Any:
    """What a step takes from V1, for its key: the envelope of its input, and of each solid a bend chain unwraps to."""
    if context.op not in _FROM_V1:
        return None
    product = context.v1_input(0)
    solid = getattr(product, "solid", None)
    if solid is None:
        return "none"
    boxes = []
    while solid is not None:
        box = getattr(solid, "envelope", None)
        boxes.append(
            None if box is None else [*map(float, box.lo), *map(float, box.hi)]
        )
        solid = solid.solid if type(solid).__name__ == "Bend" else None
    return boxes


class _V1Products:
    """V1's products for the component, built once when a step needs V1's envelopes (7.4)."""

    def __init__(self, document: DocumentV2, component: str, overrides: Any) -> None:
        self._document, self._component, self._overrides = (
            document,
            component,
            overrides,
        )
        self._built: dict[str, Any] | None = None
        self._failed = False

    @property
    def products(self) -> Mapping[str, Any] | None:
        if self._built is None and not self._failed:
            try:
                part = self._document.down_converted().component(self._component)
                self._built = compile_products(part, overrides=self._overrides)
            except (
                Exception
            ):  # V1 can't build this; the exact box stands in, and the trace says so
                self._failed = True
        return self._built


def _trace(step: Step, product: Product, seconds: float, reused: bool) -> Trace:
    if not isinstance(product, SolidProduct):
        return Trace(step.id, step.op, reused, seconds)
    return Trace(
        step.id, step.op, reused, seconds,
        volume=volume(product.shape), solids=len(solids(product.shape)), faces=len(faces(product.shape)),
        notes=product.notes, lost=tuple(sorted(str(n) for n in product.lost)), tolerance=product.tolerance,
    )  # fmt: skip
