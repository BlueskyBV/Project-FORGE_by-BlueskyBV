"""Face names, carried through every operation's history (docs/V2-stage3.md, section 9).

Every face of a built part carries the names of the faces it came from: each
name is ``(step, role, copy)`` — the step that made the face, the role that
step gave it (``bore``, ``z_max``, ``round``…), and which copy of a pattern or
mirror it is on (0 the original). After each operation the table is rebuilt
from the operation's history:

- a modified face passes its names to every face it became (a face split in
  two is two faces with one name);
- a face the operation removed drops its names, and the operation is told
  which names were lost;
- a face the operation generated takes the name the operation gives it, and
  only that;
- a face the operation didn't touch keeps its names.

Edges carry no names of their own: an edge is known by the faces either side
of it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from OCP.collections import (
    IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape,
)

from .occt import faces

__all__ = ["History", "Name", "Names", "carry", "named_by"]


@dataclass(frozen=True, order=True)
class Name:
    """What made a face: a step, the role it gave the face, and which copy."""

    step: str
    role: str
    copy: int = 0

    def __str__(self) -> str:
        return f"{self.step}.{self.role}" + (f"#{self.copy}" if self.copy else "")


@dataclass(frozen=True)
class Names:
    """The names of each face of one shape, in :func:`~forge_occ.occt.faces` order."""

    shape: Any
    table: tuple[frozenset[Name], ...]

    def __post_init__(self) -> None:
        if len(self.table) != len(faces(self.shape)):
            raise ValueError("a names table must have one entry per face")

    @cached_property
    def _faces(self) -> list[Any]:
        return faces(self.shape)

    @cached_property
    def _index(self) -> TopTools_IndexedMapOfShape:
        found = TopTools_IndexedMapOfShape()
        for face in self._faces:
            found.Add(face)
        return found

    @cached_property
    def _by_role(self) -> dict[tuple[str, str], list[int]]:
        """Each (step, role) named, and the faces (by position) that carry it: built once."""
        found: dict[tuple[str, str], list[int]] = {}
        for k, names in enumerate(self.table):
            for n in names:
                found.setdefault((n.step, n.role), []).append(k)
        return found

    def of(self, face: Any) -> frozenset[Name]:
        """The names of ``face`` (a face of this shape, matched with ``IsSame``)."""
        index = self._index.FindIndex(face)
        if index < 1:
            raise KeyError("not a face of this shape")
        found: frozenset[Name] = self.table[index - 1]
        return found

    def faces_named(self, step: str, role: str, copy: int | None = None) -> list[Any]:
        """The faces carrying ``(step, role)`` (of one copy, or of any)."""
        shape_faces = self._faces
        return [
            shape_faces[k]
            for k in self._by_role.get((step, role), [])
            if copy is None
            or any(
                n.step == step and n.role == role and n.copy == copy
                for n in self.table[k]
            )
        ]

    def every(self) -> frozenset[Name]:
        return frozenset(n for names in self.table for n in names)

    def items(self) -> list[tuple[Any, frozenset[Name]]]:
        return list(zip(self._faces, self.table, strict=True))

    def with_copy(self, copy: int) -> Names:
        """The same names, said to be on copy ``copy`` of what they name."""
        return Names(
            self.shape,
            tuple(
                frozenset(Name(n.step, n.role, copy) for n in names)
                for names in self.table
            ),
        )

    def on(self, shape: Any) -> Names:
        """The same table for a shape with the same faces in the same order (a serialized copy, a moved copy)."""
        return Names(shape, self.table)


def named_by(shape: Any, name: Callable[[Any], Iterable[Name]]) -> Names:
    """A new shape's table, each face named by ``name(face)``."""
    return Names(shape, tuple(frozenset(name(face)) for face in faces(shape)))


class History:
    """What an operation did to each input face: modified into some faces, removed, or untouched.

    Wraps OpenCascade's ``BRepTools_History`` or a builder's own
    ``Modified``/``IsDeleted``/``Generated``.
    """

    def __init__(self, source: Any) -> None:
        self._source = source

    def modified(self, face: Any) -> list[Any]:
        return list(self._source.Modified(face))

    def removed(self, face: Any) -> bool:
        if hasattr(self._source, "IsRemoved"):
            return bool(self._source.IsRemoved(face))
        return bool(self._source.IsDeleted(face))

    def generated(self, shape: Any) -> list[Any]:
        return list(self._source.Generated(shape))


@dataclass(frozen=True)
class Carried:
    names: Names
    lost: frozenset[Name]
    unnamed: int


def carry(
    inputs: Sequence[Names],
    result: Any,
    history: History | None,
    generated: Mapping[int, Iterable[Name]]
    | Callable[[Any], Iterable[Name]]
    | None = None,
    *,
    fallback: Iterable[Name] = (),
) -> Carried:
    """The result's names, carried from the inputs' through ``history``.

    ``generated`` names the faces the operation made: by the result face's
    index, or by a function of the face (asked only of faces with no history).
    A face that came from no input and that ``generated`` doesn't name takes
    ``fallback``; how many did is returned, so the caller can refuse it.
    """
    result_faces = faces(result)
    index = TopTools_IndexedMapOfShape()
    for face in result_faces:
        index.Add(face)
    table: list[set[Name]] = [set() for _ in result_faces]
    lost: set[Name] = set()
    for names in inputs:
        for face, held in names.items():
            if history is not None:
                became = history.modified(face)
                if became:
                    for other in became:
                        k = index.FindIndex(other)
                        if k >= 1:
                            table[k - 1] |= held
                    continue
                if history.removed(face):
                    lost |= held
                    continue
            k = index.FindIndex(face)
            if k >= 1:
                table[k - 1] |= held
            elif history is None:
                lost |= held
    unnamed = 0
    for k, face in enumerate(result_faces):
        if table[k]:
            continue
        given: Iterable[Name] = ()
        if callable(generated):
            given = generated(face)
        elif generated is not None:
            given = generated.get(k, ())
        table[k] = set(given)
        if not table[k]:
            table[k] = set(fallback)
            unnamed += 1
    still = {n for names in table for n in names}
    return Carried(
        Names(result, tuple(frozenset(t) for t in table)),
        frozenset(lost - still),
        unnamed,
    )
