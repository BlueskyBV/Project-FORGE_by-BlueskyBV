"""What a compiled feature produces.

A feature does not always produce a solid. Datums produce frames, profiles
produce a 2D region together with the plane it lives on, and only the solid
features produce geometry you can measure. Keeping these as distinct types --
rather than a single "shape" that might be any of them -- is what lets the
compiler check, before it builds anything, that an extrude was handed a profile
and a boolean was handed solids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from forge_geom import SDF, Profile2D

from .lineage import Frame, SemanticEntity


@dataclass(frozen=True, slots=True)
class SolidProduct:
    """A three-dimensional body."""

    solid: SDF
    entities: tuple[SemanticEntity, ...] = ()

    kind: str = "solid"


@dataclass(frozen=True, slots=True)
class ProfileProduct:
    """A closed 2D region together with the plane it was drawn on."""

    profile: Profile2D
    frame: Frame
    entities: tuple[SemanticEntity, ...] = ()

    kind: str = "profile"


@dataclass(frozen=True, slots=True)
class DatumPlaneProduct:
    frame: Frame
    entities: tuple[SemanticEntity, ...] = ()

    kind: str = "datum_plane"


@dataclass(frozen=True, slots=True)
class DatumAxisProduct:
    origin: tuple[float, float, float]
    direction: tuple[float, float, float]
    entities: tuple[SemanticEntity, ...] = ()

    kind: str = "datum_axis"


@dataclass(frozen=True, slots=True)
class DatumPointProduct:
    position: tuple[float, float, float]
    entities: tuple[SemanticEntity, ...] = ()

    kind: str = "datum_point"


Product = Union[
    SolidProduct,
    ProfileProduct,
    DatumPlaneProduct,
    DatumAxisProduct,
    DatumPointProduct,
]


__all__ = [
    "Product",
    "SolidProduct",
    "ProfileProduct",
    "DatumPlaneProduct",
    "DatumAxisProduct",
    "DatumPointProduct",
]
