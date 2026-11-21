"""Whether a part as drafted comes apart: a cut that takes a standing item, or a piece of a body, off the part.

The build makes the part one step at a time and refuses a step after which
it is more than one solid (:func:`~forge_occ.planned._one_solid`): either
OpenCascade misread the step, or the step cut the part apart, which the
spec's own checks don't find (they read each item on its face, not what all
of them leave). Generated part 5468: two holes 10.9 mm across through
everything from a dome's surface, through its middle and out of its flat
face round a boss 6.2 mm across standing there, cut the boss off the part;
every way to build it was two solids, and the run ended UNABLE, as if Forge
couldn't make what can't be made.

So where every way to make the refused item was refused so, the part is
built once more, all of its steps and none refused, and judged as any build
is (:class:`~forge_checks.judge.Judge`): where the finished part is more
than one solid, a point well inside each lies in the part's material as the
spec defines it (its oracle, :mod:`forge_checks.oracle`), and the judge
holds the pieces for nothing but their count (every check passed, every
face accounted for on the spec's surfaces, the volume the spec's), the
pieces are the spec's own shape: the part as drafted comes apart. That is the brief's: a CAN'T, as no other way to
build it makes it one piece. Where any of that isn't so (the finished part one solid, a
later item joining the pieces again; a piece the spec has no material in,
OpenCascade's misreading) it is not said, and the build's own refusal
stands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from forge_checks.view import Side, ViewProxy
from forge_numeric import vector as fv
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_IN
from OCP.TopoDS import TopoDS_Compound

from .backend import OccBackend
from .errors import OccError
from .occt import faces, shells, solids, volume
from .view import BrepView, _box_of

__all__ = ["Apart", "comes_apart", "split_refusal"]

#: Points a side of the grid in a piece's box asked for one well inside it.
_GRID = 7


@dataclass(frozen=True)
class Apart:
    """A part as drafted that comes apart: the item whose cut first left it in pieces, how many pieces, the items only
    the smaller pieces hold (cut off whole), and those a smaller piece shares with the largest (a piece of each cut
    off): each by its faces' owners, the cutting item left out."""

    item: str
    pieces: int
    off: tuple[str, ...]
    piece_of: tuple[str, ...] = ()

    def message(self) -> str:
        """The CAN'T, in the person's terms."""
        what = [*self.off, *(f"a piece of {owner}" for owner in self.piece_of)]
        cut = f"cut {_listed(what)} off the part" if what else "cut the part apart"
        return (f"{self.item} would {cut}: as drafted it comes apart into {self.pieces} pieces, and a part is one "
                "piece")  # fmt: skip


def _listed(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def split_refusal(error: dict[str, Any]) -> bool:
    """Whether a refusal (an error's record) was the build's: the part more than one solid after the step."""
    detail = error.get("detail") or {}
    solids_found = detail.get("solids")
    return isinstance(solids_found, int) and solids_found > 1


def comes_apart(planned: Any, built: Any, judge: Any, seed: int = 1, *, backend: Any = None) -> Apart | None:
    """Whether the spec's part comes apart (see the module): ``planned`` the plan, ``built`` what building it came to
    (a :class:`~forge_occ.planned.PlannedBuild` with a gap), ``judge`` the spec's
    (:class:`~forge_checks.judge.Judge`), ``seed`` its fresh probes', ``backend`` what builds it (OpenCascade's);
    None where that isn't so, or can't be told."""
    gap = built.gap
    if gap is None:
        return None
    mine = [r for r in built.refusals if r.item == gap.item]
    if not mine or not all(split_refusal(r.error) for r in mine):
        return None
    try:
        written = planned.written(built.choice)
        result = (backend or OccBackend()).build(written.document, "part")
    except OccError:
        return None
    pieces = solids(result.shape)
    if len(pieces) < 2:
        return None
    inside = [_well_inside(piece) for piece in pieces]
    if any(point is None for point in inside):
        return None
    sides = judge.part.classify(np.array(inside, dtype=np.float64))
    if not all(int(side) == Side.IN for side in sides):
        return None  # a piece where the spec has no material: OpenCascade's misreading, not the spec's part
    if not _only_its_pieces(judge.view(ViewProxy(BrepView(result.shape)), "B-rep", seed)):
        return None
    cutter = gap.item
    by_size = sorted(range(len(pieces)), key=lambda k: -volume(pieces[k]))
    largest = set(_owners(result.names, written.owners, pieces[by_size[0]], cutter))
    smaller = {owner for k in by_size[1:] for owner in _owners(result.names, written.owners, pieces[k], cutter)}
    return Apart(cutter, len(pieces), tuple(sorted(smaller - largest)), tuple(sorted(smaller & largest)))


def _only_its_pieces(view: Any) -> bool:
    """Whether the judge holds the part in pieces for nothing but how many solids it is (and so how many through-holes
    each has, where they add up to the spec's): every check, its faces accounted for, its volume and fresh probes
    passed. The pieces are then the spec's own shape."""
    if any(found.detector != "topology" for found in view.held):
        return False
    topology = view.topology
    for difference in topology.findings:
        if difference.what == "solids":
            continue
        if difference.what == "through-holes" and sum(topology.built.genus) == sum(topology.expected.genus or ()):
            continue
        return False
    return True


def _owners(names: Any, owners: Any, piece: Any, cutter: str) -> tuple[str, ...]:
    """The items whose steps a piece's faces are named for (``owners``, step to item), but the cutting item."""
    found: set[str] = set()
    for face in faces(piece):
        try:
            held = names.of(face)
        except KeyError:
            continue
        for name in held:
            owner = owners.get(name.step)
            if owner is not None and owner != cutter:
                found.add(str(owner))
    return tuple(sorted(found))


def _well_inside(piece: Any) -> tuple[float, float, float] | None:
    """A point inside a solid, the farthest from its surface of a grid's in its box; None if none is inside."""
    box = _box_of(piece, held=False)
    lo, hi = np.asarray(box.lo, dtype=np.float64), np.asarray(box.hi, dtype=np.float64)
    steps = (np.arange(_GRID) + 0.5) / _GRID
    best: tuple[float, tuple[float, float, float]] | None = None
    surface = TopoDS_Compound()  # its shells: from a solid itself a point inside is 0 away
    builder = BRep_Builder()
    builder.MakeCompound(surface)
    for shell in shells(piece):
        builder.Add(surface, shell)
    meter = BRepExtrema_DistShapeShape()
    meter.LoadS2(surface)
    for a in steps:
        for b in steps:
            for c in steps:
                p = lo + (hi - lo) * np.array([a, b, c])
                at = gp_Pnt(float(p[0]), float(p[1]), float(p[2]))
                if BRepClass3d_SolidClassifier(piece, at, 1e-7).State() != TopAbs_IN:
                    continue
                meter.LoadS1(BRepBuilderAPI_MakeVertex(at).Vertex())
                meter.Perform()
                if not meter.IsDone():
                    continue
                gap = float(meter.Value())
                if best is None or gap > best[0]:
                    best = (gap, (float(p[0]), float(p[1]), float(p[2])))
    if best is None or not best[0] > 1e-6 * float(fv.norm(hi - lo)):
        return None
    return best[1]
