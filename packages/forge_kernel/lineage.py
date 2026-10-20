"""Lineage-addressed topology: Forge's answer to the topological naming problem.

The problem
-----------
Parametric CAD systems have fought this for thirty years. A user selects a face
and puts a fillet on it. The system records the selection as "face 47", because
that is what the kernel offers. The user then changes an upstream dimension, the
kernel rebuilds, the faces are renumbered, and "face 47" is now a different face
-- or does not exist. The fillet lands somewhere else, or the rebuild fails, and
in the worst case the model looks fine and is wrong. FreeCAD calls this its
topological naming problem; every kernel has some version of it.

The usual mitigations are heuristic: remember the face's area, centroid and
normal, and after a rebuild find the face that looks most like the remembered
one. This works until it does not, and its failures are silent, because the
matcher always returns *something*.

The approach here
-----------------
Identity does not come from geometry at all. It comes from the *construction*.

When a feature publishes a piece of geometry, that geometry's identity is a hash
of the feature's stable identifier and the output's declared role::

    token = H(feature_id || output_suffix || ordinal)

The hash is over the feature graph, not over coordinates, areas or indices. So
when a parameter changes -- ``ear_thickness`` from 6 mm to 8 mm -- the feature
graph is structurally identical, every token is bit-for-bit identical, and every
selection still resolves. No matching, no tolerance, no heuristic. Stability
under parameter change is not something the system achieves; it is something the
representation cannot fail at.

Topology changes are a different matter, and this is where the design earns its
keep. If a feature change *buries* a face -- a boss grows until the pocket it sat
in disappears -- the token still exists, but the geometry it names no longer lies
on the boundary. :func:`validate_entities` detects exactly that, by sampling the
named surface against the finished solid, and marks the entity ``BURIED``. Any
interface, mate, load or mesh group that referenced it then fails with a precise
diagnostic naming the entity and the feature that consumed it.

That is the whole trade, and it is the right one: **stable by construction under
parameter change, loudly broken under topology change.** A heuristic matcher
gets the first case usually right and the second case silently wrong. This gets
the first case always right and the second case always caught.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

import numpy as np

from forge_geom import SDF

Array = np.ndarray

#: Bumping this invalidates every stored lineage token, which is a schema
#: migration and must be treated as one.
LINEAGE_SCHEME_VERSION = "1"


def lineage_token(feature_id: str, suffix: str, ordinal: int = 0) -> str:
    """Derive the stable identity of a published piece of geometry.

    Deliberately a function of the construction only. Nothing about the
    resulting coordinates enters the hash, which is precisely why the token
    survives a parameter change.
    """
    payload = f"{LINEAGE_SCHEME_VERSION}\x1f{feature_id}\x1f{suffix}\x1f{ordinal}"
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=16).hexdigest()


def derived_token(parent: str, feature_id: str, relation: str) -> str:
    """Identity of geometry produced by transforming or splitting existing geometry.

    A pattern that makes four copies of a face gives each copy a distinct token
    descending from the original, so a mate can name "the third instance's bore"
    without any index into a rebuilt topology.
    """
    payload = f"{LINEAGE_SCHEME_VERSION}\x1f{parent}\x1f{feature_id}\x1f{relation}"
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=16).hexdigest()


#: Surface samples are pulled in from the entity's own edges by this factor.
#: See :meth:`SemanticEntity.sample_points` for why a rim sample is misleading.
_SAMPLE_INSET = 0.94
#: The most samples a face gets along one side when sampled densely, and in
#: all: a cutter's face is resampled this finely only when the coarse look
#: found too little of it, so the cost is paid by cutters alone.
_DENSE_PER_SIDE = 400
_DENSE_POINTS = 24_000
#: How far apart a cutter's dense samples are, at most, in millimetres.
_DENSE_SPACING_MM = 1.0


class EntityStatus(Enum):
    """Whether a named piece of geometry still exists on the finished solid."""

    #: Present on the boundary of the final solid.
    LIVE = "live"
    #: The construction still names it, but it no longer lies on the boundary --
    #: a later feature added material over it or removed it entirely.
    BURIED = "buried"
    #: Named by the feature graph but never realised, e.g. an optional output the
    #: backend does not produce.
    ABSENT = "absent"
    #: Not yet checked.
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class Frame:
    """A right-handed coordinate frame in millimetres."""

    origin: tuple[float, float, float]
    x_axis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    y_axis: tuple[float, float, float] = (0.0, 1.0, 0.0)
    z_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)

    @classmethod
    def from_axis(
        cls, origin: Sequence[float], axis: Sequence[float]
    ) -> "Frame":
        """Build a frame whose z axis is ``axis``, choosing any stable x axis."""
        z = np.asarray(axis, dtype=float)
        length = float(np.linalg.norm(z))
        if length < 1e-12:
            raise ValueError("cannot build a frame from a zero-length axis")
        z = z / length
        # Pick the world axis least parallel to z, so the cross product is well
        # conditioned no matter which way the part is oriented.
        helper = np.zeros(3)
        helper[int(np.argmin(np.abs(z)))] = 1.0
        x = np.cross(helper, z)
        x = x / np.linalg.norm(x)
        y = np.cross(z, x)
        return cls(
            tuple(float(v) for v in origin),  # type: ignore[arg-type]
            tuple(x.tolist()),  # type: ignore[arg-type]
            tuple(y.tolist()),  # type: ignore[arg-type]
            tuple(z.tolist()),  # type: ignore[arg-type]
        )

    @property
    def matrix(self) -> Array:
        return np.array([self.x_axis, self.y_axis, self.z_axis], dtype=float).T

    def to_world(self, local: Array) -> Array:
        return np.asarray(local, dtype=float) @ self.matrix.T + np.asarray(
            self.origin, dtype=float
        )

    def as_dict(self) -> dict[str, list[float]]:
        return {
            "origin": list(self.origin),
            "x_axis": list(self.x_axis),
            "y_axis": list(self.y_axis),
            "z_axis": list(self.z_axis),
        }


class _RigidWarp:
    """A rigid motion as a point map, for an entity a bend has curved."""

    __slots__ = ("rotation", "translation")

    def __init__(self, rotation: Array, translation: Array) -> None:
        self.rotation = np.asarray(rotation, dtype=float)
        self.translation = np.asarray(translation, dtype=float)

    def __call__(self, points: Array) -> Array:
        return np.asarray(points, dtype=float) @ self.rotation.T + self.translation


@dataclass(frozen=True, slots=True)
class SemanticEntity:
    """A named, lineage-addressed piece of geometry.

    The geometry is described *analytically* -- a cylindrical face is an axis, a
    radius and an extent -- rather than as a reference into a topological data
    structure. That is what makes the same entity meaningful to the implicit
    backend, the B-Rep backend and the Fusion bridge, none of which share a
    notion of "face 47".
    """

    name: str
    token: str
    entity_type: str
    frame: Frame
    #: Analytic size parameters: ``radius`` and ``length`` for a cylinder,
    #: ``half_u``/``half_v`` for a planar face, and so on.
    dimensions: Mapping[str, float] = field(default_factory=dict)
    owning_feature: str = ""
    status: EntityStatus = EntityStatus.UNVERIFIED
    note: str = ""
    #: Maps carrying the entity's surface from where it was made to where it
    #: is, in order -- set when a bend has curved it, which no frame can say.
    #: ``frame`` is then the entity's frame where its origin went, turned as
    #: the solid turned there, and ``sample_frame`` the frame it was made in.
    warps: tuple[Any, ...] = ()
    sample_frame: Frame | None = None

    def with_status(self, status: EntityStatus, note: str = "") -> "SemanticEntity":
        return SemanticEntity(
            name=self.name,
            token=self.token,
            entity_type=self.entity_type,
            frame=self.frame,
            dimensions=self.dimensions,
            owning_feature=self.owning_feature,
            status=status,
            note=note,
            warps=self.warps,
            sample_frame=self.sample_frame,
        )

    def warped(self, warp: Any, frame: Frame) -> "SemanticEntity":
        """Carry the entity through a map that may curve it: a bend."""
        return SemanticEntity(
            name=self.name,
            token=self.token,
            entity_type=self.entity_type,
            frame=frame,
            dimensions=self.dimensions,
            owning_feature=self.owning_feature,
            status=self.status,
            note=self.note,
            warps=self.warps + (warp,),
            sample_frame=self.sample_frame or self.frame,
        )

    def transformed(self, rotation: Array, translation: Array) -> "SemanticEntity":
        """Carry the entity through a rigid motion, preserving its token."""
        origin = np.asarray(self.frame.origin, dtype=float) @ rotation.T + translation
        axes = [
            np.asarray(axis, dtype=float) @ rotation.T
            for axis in (self.frame.x_axis, self.frame.y_axis, self.frame.z_axis)
        ]
        return SemanticEntity(
            name=self.name,
            token=self.token,
            entity_type=self.entity_type,
            frame=Frame(
                tuple(origin.tolist()),  # type: ignore[arg-type]
                tuple(axes[0].tolist()),  # type: ignore[arg-type]
                tuple(axes[1].tolist()),  # type: ignore[arg-type]
                tuple(axes[2].tolist()),  # type: ignore[arg-type]
            ),
            dimensions=self.dimensions,
            owning_feature=self.owning_feature,
            status=self.status,
            note=self.note,
            warps=self.warps + ((_RigidWarp(rotation, translation),)
                                if self.warps else ()),
            sample_frame=self.sample_frame,
        )

    def sample_points(self, count: int = 64, spacing: float | None = None
                      ) -> Array:
        """Points on the entity's own surface, used to test whether it survives.

        A bent entity is sampled where it was made and carried through each
        map that has moved it since, so the samples lie on the curved surface
        it now is.

        With `spacing`, the points are about that far apart across the whole
        surface instead of `count` of them -- for a cutter's face, which is on
        the part only where the cutter met material: a strip a wall thick
        across a face many times longer, that a coarse grid steps over.
        """
        if not self.warps:
            return self._samples_in(self.frame, count, spacing)
        points = self._samples_in(self.sample_frame or self.frame, count,
                                  spacing)
        for warp in self.warps:
            points = warp(points)
        return points

    def _samples_in(self, frame: Frame, count: int = 64,
                    spacing: float | None = None) -> Array:
        """Points on the entity's own surface, used to test whether it survives.

        For a cylindrical bore these lie on the bore wall; for a planar face,
        across the face. Checking those points against the finished solid is how
        burial is detected.
        """
        if self.entity_type in ("cylindrical_face",):
            radius = float(self.dimensions.get("radius", 0.0))
            length = float(self.dimensions.get("length", 0.0))
            rings = max(2, int(math.sqrt(count)))
            around = max(4, count // rings)
            if spacing is not None and spacing > 0.0:
                rings = int(min(_DENSE_PER_SIDE, max(
                    rings, math.ceil(length / spacing) + 1)))
                around = int(min(96, max(around, math.ceil(
                    2.0 * math.pi * radius / spacing))))
                rings = max(2, min(rings, _DENSE_POINTS // max(around, 1)))
            angles = np.linspace(0.0, 2.0 * math.pi, around, endpoint=False)
            # Inset from the ends: a point exactly on the rim lies on the
            # adjoining face too, so it reads as "on the boundary" even when the
            # cylindrical surface itself has been buried.
            span = length / 2.0 * _SAMPLE_INSET
            heights = np.linspace(-span, span, rings)
            local = np.array(
                [
                    [radius * math.cos(a), radius * math.sin(a), h]
                    for h in heights
                    for a in angles
                ]
            )
            return frame.to_world(local)

        if self.entity_type in ("planar_face",):
            half_u = float(self.dimensions.get("half_u", 0.0))
            half_v = float(self.dimensions.get("half_v", 0.0))
            side = max(2, int(math.sqrt(count)))
            side_u = side_v = side
            if spacing is not None and spacing > 0.0:
                side_u = int(min(_DENSE_PER_SIDE, max(
                    side, math.ceil(2.0 * half_u / spacing) + 1)))
                side_v = int(min(_DENSE_PER_SIDE, max(
                    side, math.ceil(2.0 * half_v / spacing) + 1)))
                while side_u * side_v > _DENSE_POINTS:
                    side_u = max(side, int(side_u * 0.85))
                    side_v = max(side, int(side_v * 0.85))
            # Inset from the edges. A sample on the perimeter of a face lies on
            # the neighbouring face as well, so a fully buried face whose rim
            # still touches the boundary would report a large "surviving"
            # fraction and be wrongly called live. On an 8x8 grid the perimeter
            # is 44% of the samples, which is more than enough to do it.
            us = np.linspace(-half_u, half_u, side_u) * _SAMPLE_INSET
            vs = np.linspace(-half_v, half_v, side_v) * _SAMPLE_INSET
            local = np.array([[u, v, 0.0] for u in us for v in vs])
            return frame.to_world(local)

        if self.entity_type in ("swept_face",):
            ring = self.dimensions.get("ring")
            span = self.dimensions.get("span")
            if spacing is not None and spacing > 0.0 and ring and span:
                # Swept again at about `spacing` along its length: a long
                # cutter through a wall thinner than the stations were apart.
                offset, distance = (float(c) for c in span)
                stations = int(min(_DENSE_PER_SIDE * 2, max(
                    3, math.ceil(abs(distance) / spacing))))
                ws = offset + distance * (np.arange(stations) + 0.5) / stations
                uv = np.asarray(ring, dtype=float).reshape(-1, 2)
                local = np.column_stack([
                    np.tile(uv[:, 0], stations), np.tile(uv[:, 1], stations),
                    np.repeat(ws, uv.shape[0])])
                return frame.to_world(local)
            # Points the backend found on the face, in its own frame.
            local = np.asarray(self.dimensions.get("samples") or (),
                               dtype=float).reshape(-1, 3)
            return frame.to_world(local) if local.size else np.zeros((0, 3))

        if self.entity_type in ("spherical_face",):
            radius = float(self.dimensions.get("radius", 0.0))
            rng = np.random.default_rng(0xF0B9)
            directions = rng.normal(size=(count, 3))
            directions /= np.linalg.norm(directions, axis=1, keepdims=True)
            return frame.to_world(directions * radius)

        # Axes, points, frames and volumes have no surface to sample; they are
        # carried for reference and are never burial-checked.
        return np.zeros((0, 3))

    @property
    def is_checkable(self) -> bool:
        return self.entity_type in (
            "cylindrical_face",
            "planar_face",
            "spherical_face",
            "swept_face",
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "token": self.token,
            "type": self.entity_type,
            "frame": self.frame.as_dict(),
            "dimensions": dict(self.dimensions),
            "owning_feature": self.owning_feature,
            "status": self.status.value,
            **({"note": self.note} if self.note else {}),
        }


class SemanticGeometryMap:
    """Every named entity a compiled part publishes, keyed by name and by token."""

    __slots__ = ("_by_name", "_by_token")

    def __init__(self, entities: Sequence[SemanticEntity] = ()) -> None:
        self._by_name: dict[str, SemanticEntity] = {}
        self._by_token: dict[str, SemanticEntity] = {}
        for entity in entities:
            self.add(entity)

    def add(self, entity: SemanticEntity) -> None:
        self._by_name[entity.name] = entity
        self._by_token[entity.token] = entity

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __len__(self) -> int:
        return len(self._by_name)

    def __iter__(self) -> Iterator[SemanticEntity]:
        return iter(self._by_name[name] for name in sorted(self._by_name))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_name))

    def get(self, name: str) -> SemanticEntity | None:
        return self._by_name.get(name)

    def by_token(self, token: str) -> SemanticEntity | None:
        return self._by_token.get(token)

    def resolve(self, name: str) -> SemanticEntity:
        """Look up an entity, failing loudly when it is missing or buried.

        This is the single point where a stale selection is caught. It never
        falls back to a nearest match, because a wrong face chosen confidently
        is worse than a build that stops and says what broke.
        """
        entity = self._by_name.get(name)
        if entity is None:
            raise SelectionError(
                "no geometry is published under that name",
                name=name,
                # Closest matches first. An alphabetical head of the list is
                # almost useless on a part with forty published names: the one
                # the author meant is rarely in the first forty alphabetically,
                # and a typo is usually one edit away from the right answer.
                did_you_mean=_closest_names(name, self._by_name),
                available=sorted(self._by_name),
            )
        if entity.status is EntityStatus.BURIED:
            raise SelectionError(
                "the named geometry no longer lies on the solid's boundary; a "
                "later feature covered or removed it",
                name=name,
                token=entity.token,
                owning_feature=entity.owning_feature,
                note=entity.note,
                hint=(
                    "a profile's `region` is the outline where it was "
                    "sketched -- often a plane off the part -- not anything "
                    "on the part. An interface on an opening, slot or window "
                    "names the faces the cut leaves: `<the extrude that cuts "
                    "it>.side`."
                    if name.endswith(".region") else
                    "this is a topology change, not a parameter change. "
                    "Either revert the feature that buried it, or re-express "
                    "the reference against geometry that still exists."),
            )
        if entity.status is EntityStatus.ABSENT:
            raise SelectionError(
                "the named geometry was declared but never produced",
                name=name,
                token=entity.token,
                owning_feature=entity.owning_feature,
            )
        return entity

    def live(self) -> tuple[SemanticEntity, ...]:
        return tuple(e for e in self if e.status is EntityStatus.LIVE)

    def buried(self) -> tuple[SemanticEntity, ...]:
        return tuple(e for e in self if e.status is EntityStatus.BURIED)

    def as_dict(self) -> dict[str, object]:
        return {"entities": [entity.as_dict() for entity in self]}


def _closest_names(
    name: str, candidates: "Mapping[str, SemanticEntity]", limit: int = 5
) -> tuple[str, ...]:
    """Names most likely to be what the author meant."""
    import difflib

    matches = list(
        difflib.get_close_matches(name, list(candidates), n=limit, cutoff=0.5)
    )
    prefix = name.split(".", 1)[0]
    for candidate in sorted(candidates):
        if len(matches) >= limit:
            break
        if candidate.startswith(prefix + ".") and candidate not in matches:
            matches.append(candidate)
    return tuple(matches)


class SelectionError(Exception):
    """A semantic selection could not be resolved."""

    code = "KN1001_SELECTION"

    def __init__(self, message: str, **detail: object) -> None:
        super().__init__(message)
        self.message = message
        self.detail = dict(detail)

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}

    def __str__(self) -> str:
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.detail.items()))
        return f"[{self.code}] {self.message} ({rendered})" if rendered else (
            f"[{self.code}] {self.message}"
        )


#: The finer probe, in mm, for a surface the part-sized probe calls gone.
_FINE_PROBE_MM = 0.02


def validate_entities(
    solid: SDF,
    entities: Sequence[SemanticEntity],
    *,
    tolerance: float | None = None,
    cutters: frozenset[str] | set[str] = frozenset(),
) -> tuple[SemanticEntity, ...]:
    """Mark each entity ``LIVE`` or ``BURIED`` against the finished solid.

    An entity is live when a meaningful fraction of its own surface samples lie
    on the solid's boundary. It is buried when its samples are strictly inside
    -- material was added over it -- or strictly outside, meaning the feature
    that created it was later removed.

    A cutter is the exception to the fraction (`cutters`, the features a
    `subtract` takes away): its faces are on the part only where it met
    material. The side of a 200 mm cutter drawn through one 8 mm wall of a
    calf shell is 4% on the part and 96% in the air either side -- every bit
    of the opening's walls, and it was marked buried, so the interface
    naming the opening failed and three repair rounds chased it. A cutter's
    face is live when a real patch of it is on the boundary, sampled finely
    enough to find a strip one wall wide, and not filled in.

    The fraction is not required to be 1.0, because a face is routinely and
    legitimately *partly* consumed: drilling a hole through a plate leaves most
    of the plate's top face intact, and that face is still the face. The
    threshold below distinguishes "mostly still there" from "gone", and the
    surviving fraction is recorded in the note either way, so a face that has
    been eaten down to a sliver is visible in the report rather than passing
    quietly as live.
    """
    if tolerance is None:
        tolerance = max(solid.envelope.diagonal * 1e-3, 1e-6)

    # Probe offsets: the six axis directions at the tolerance radius.
    probes = np.array(
        [
            [1.0, 0.0, 0.0], [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0], [0.0, -1.0, 0.0],
            [0.0, 0.0, 1.0], [0.0, 0.0, -1.0],
        ]
    ) * tolerance

    validated: list[SemanticEntity] = []
    for entity in entities:
        if not entity.is_checkable:
            validated.append(entity.with_status(EntityStatus.LIVE))
            continue
        samples = entity.sample_points()
        if samples.shape[0] == 0:
            validated.append(entity.with_status(EntityStatus.LIVE))
            continue

        # A point lies on the boundary exactly when its immediate neighbourhood
        # contains both material and empty space. That is tested directly, by
        # probing around each sample, rather than by asking whether the field is
        # near zero.
        #
        # The distinction is not pedantic. ``min(f_a, f_b)`` is the exact
        # distance field of a union only *outside* it; inside, it is merely an
        # upper bound on the distance to the boundary. Where two operands share
        # a face -- a pad sitting flush under a plate -- both fields read exactly
        # zero along that face, so a near-zero test declares a thoroughly
        # interior surface to be on the boundary, and a buried reference passes
        # as live. The neighbourhood test cannot be fooled that way, and it needs
        # no surface normal, which matters because the outward direction differs
        # between a boss (material inside) and a bore (material outside).
        neighbourhood = samples[:, None, :] + probes[None, :, :]
        probe_field = solid(neighbourhood.reshape(-1, 3)).reshape(
            samples.shape[0], probes.shape[0]
        )
        has_material = np.any(probe_field < 0.0, axis=1)
        has_space = np.any(probe_field > 0.0, axis=1)
        on_boundary = has_material & has_space
        fine = min(tolerance, _FINE_PROBE_MM)
        if float(on_boundary.mean()) < 0.25 and fine < tolerance:
            # The probe is a thousandth of the part's diagonal: 1.2 mm on a
            # metre-long box, wider than a 1 mm wall it may be probing --
            # both sides of the wall in the air, the face called buried. A
            # face is on the boundary where material and space meet within
            # a probe of it, and a finer probe that finds them meeting is
            # the more exact of the two; the coarse one stands where the
            # fine one finds nothing more.
            close = solid((samples[:, None, :] + probes[None, :, :]
                           * (fine / tolerance)).reshape(-1, 3)).reshape(
                samples.shape[0], probes.shape[0])
            finely = np.any(close < 0.0, axis=1) & np.any(close > 0.0, axis=1)
            on_boundary = on_boundary | finely
            has_space = has_space | np.any(close > 0.0, axis=1)

        fraction = float(on_boundary.mean())
        inside = float((~has_space).mean())
        if fraction < 0.25 and inside <= 0.5 and \
                entity.owning_feature in cutters:
            found = _a_cutters_patch(solid, entity, probes)
            if found is not None:
                validated.append(entity.with_status(
                    EntityStatus.LIVE,
                    f"{found} points of the named surface lie on the boundary: "
                    "a cutter's face is on the part only where it cut "
                    "material, and the rest of it is in the air"))
                continue
        if fraction >= 0.25:
            validated.append(
                entity.with_status(
                    EntityStatus.LIVE,
                    f"{fraction:.0%} of the named surface lies on the boundary",
                )
            )
        elif inside > 0.5:
            validated.append(
                entity.with_status(
                    EntityStatus.BURIED,
                    f"only {fraction:.0%} of the named surface remains on the "
                    f"boundary; {inside:.0%} is now interior, so a later feature "
                    "added material over it",
                )
            )
        else:
            validated.append(
                entity.with_status(
                    EntityStatus.BURIED,
                    f"only {fraction:.0%} of the named surface remains on the "
                    "boundary; the material that carried it was removed",
                )
            )
    return tuple(validated)


def _a_cutters_patch(solid: SDF, entity: SemanticEntity,
                     probes: Array) -> int | None:
    """How many points of a cutter's face, sampled about a millimetre
    apart, lie on the finished part's boundary -- when that is a patch (six
    or more) and the face is not mostly filled in. Else None."""
    try:
        samples = np.asarray(entity.sample_points(
            spacing=_DENSE_SPACING_MM), dtype=float)
    except Exception:  # noqa: BLE001 - a face that cannot be resampled
        return None    # is judged as it was
    if samples.ndim != 2 or samples.shape[0] == 0:
        return None
    field = solid((samples[:, None, :] + probes[None, :, :]).reshape(
        -1, 3)).reshape(samples.shape[0], probes.shape[0])
    has_material = np.any(field < 0.0, axis=1)
    has_space = np.any(field > 0.0, axis=1)
    on = int((has_material & has_space).sum())
    if on < 6 or float((~has_space).mean()) > 0.5:
        return None
    return on


__all__ = [
    "LINEAGE_SCHEME_VERSION",
    "lineage_token",
    "derived_token",
    "EntityStatus",
    "Frame",
    "SemanticEntity",
    "SemanticGeometryMap",
    "SelectionError",
    "validate_entities",
]
