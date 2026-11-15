"""What a step makes, and what a builder is handed (docs/V2-stage3.md, section 7)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import DesignError, OccError
from .geom import Frame, Vec3
from .names import Name, Names
from .profiles import Profile

__all__ = [
    "Context",
    "DatumAxis",
    "DatumPlane",
    "DatumPoint",
    "Product",
    "ProfileProduct",
    "SolidProduct",
]


@dataclass(frozen=True)
class SolidProduct:
    """A solid (or a compound of solids) and the names of its faces."""

    shape: Any
    names: Names
    #: What the trace should say about this step: "removed nothing", tangent edges added, …
    notes: tuple[str, ...] = ()
    #: How far this step's surface may be from its definition (mm): 0 where exact.
    tolerance: float = 0.0
    #: Names the step's operation removed from the part.
    lost: frozenset[Name] = frozenset()
    #: What the builder knows the volume must be, (least, most, why), for the after-check.
    expect: tuple[float, float, str] | None = None
    #: For a bend's result: the chain of bends (forge_occ.ops.bend.BendSpec) and the flat part they bend.
    chain: tuple[Any, ...] = ()
    flat: Any = None

    kind = "solid"


@dataclass(frozen=True)
class ProfileProduct:
    """An outline in a plane."""

    profile: Profile
    frame: Frame

    kind = "profile"


@dataclass(frozen=True)
class DatumPlane:
    frame: Frame

    kind = "datum_plane"


@dataclass(frozen=True)
class DatumAxis:
    origin: Vec3
    direction: Vec3

    kind = "datum_axis"


@dataclass(frozen=True)
class DatumPoint:
    position: Vec3

    kind = "datum_point"


Product = SolidProduct | ProfileProduct | DatumPlane | DatumAxis | DatumPoint


@dataclass
class Context:
    """Everything a builder is handed: the step, its resolved parameters (mm, radians), its inputs."""

    step: str
    op: str
    role: str
    params: Mapping[str, Any]
    inputs: tuple[Product, ...]
    #: V1's products for this component, for the parameters V1 defines by its envelopes (7.4); None where V1 can't build it.
    v1: Mapping[str, Any] | None = None
    #: The step's V1 inputs' ids, to find their V1 products.
    input_ids: tuple[str, ...] = ()
    references: Mapping[str, Any] = field(default_factory=dict)

    # -- parameters ---------------------------------------------------------------------
    def length(self, name: str, default: float | None = None) -> float:
        value = self.params.get(name)
        if value is None:
            if default is None:
                raise DesignError("a required length is missing", parameter=name)
            return float(default)
        return float(value)

    def angle(self, name: str, default: float | None = None) -> float:
        return self.length(name, default)

    def vector(self, name: str, default: Vec3 | None = None) -> Vec3:
        value = self.params.get(name)
        if value is None:
            if default is None:
                raise DesignError("a required vector is missing", parameter=name)
            return default
        x, y, z = (float(c) for c in value)
        return x, y, z

    def option(self, name: str, default: str = "") -> str:
        value = self.params.get(name)
        return default if value is None else str(value)

    def flag(self, name: str, default: bool = False) -> bool:
        value = self.params.get(name)
        return default if value is None else bool(value)

    def count(self, name: str, default: int | None = None) -> int:
        value = self.params.get(name)
        if value is None:
            if default is None:
                raise DesignError("a required count is missing", parameter=name)
            return default
        return int(value)

    # -- inputs -------------------------------------------------------------------------
    def solid(self, index: int = 0) -> SolidProduct:
        product = self.inputs[index]
        if not isinstance(product, SolidProduct):
            raise DesignError("expected a solid input", index=index, got=product.kind)
        return product

    def solids(self) -> tuple[SolidProduct, ...]:
        return tuple(self.solid(i) for i in range(len(self.inputs)))

    def profile(self, index: int = 0) -> ProfileProduct:
        product = self.inputs[index]
        if not isinstance(product, ProfileProduct):
            raise DesignError("expected a profile input", index=index, got=product.kind)
        return product

    def plane(self, index: int = 0) -> DatumPlane:
        product = self.inputs[index]
        if not isinstance(product, DatumPlane):
            raise DesignError(
                "expected a datum plane input", index=index, got=product.kind
            )
        return product

    def axis(self, index: int) -> DatumAxis:
        product = self.inputs[index]
        if not isinstance(product, DatumAxis):
            raise DesignError(
                "expected a datum axis input", index=index, got=product.kind
            )
        return product

    def v1_input(self, index: int = 0) -> Any | None:
        """V1's product for this step's input ``index``, or None where V1 can't build it."""
        if self.v1 is None or index >= len(self.input_ids):
            return None
        return self.v1.get(self.input_ids[index])

    def name(self, role: str, copy: int = 0) -> Name:
        return Name(self.step, role, copy)

    def fail(self, error: OccError) -> OccError:
        return error.where(step=self.step, op=self.op)
