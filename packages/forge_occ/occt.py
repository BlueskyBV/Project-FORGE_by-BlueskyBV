"""The gate to OpenCascade: the version Forge was built for, and the helpers every operation uses.

``forge_occ`` runs only on the OpenCascade it was built and tested against
(docs/V2-stage3.md, 2.2): importing this module on any other raises
:class:`~forge_occ.errors.KernelMissingError`, and every other module of the
package imports this one first.

What else lives here, because every operation needs it:

- the messenger made quiet (OpenCascade's STEP writer prints statistics to
  standard output otherwise);
- :func:`boundary`, where any of OpenCascade's exceptions becomes an error
  naming what was being done (the bindings give each of OpenCascade's
  exception classes its own Python class, ``Standard_DomainError``,
  ``StdFail_NotDone`` and the rest, none a subclass of ``Standard_Failure``:
  they are told by coming from OCP);
- shapes listed in a fixed order (through ``TopTools`` maps, never ``==``,
  which compares Python objects rather than shapes);
- validity, mass properties, copying and serializing.
"""

from __future__ import annotations

import io
import math
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from importlib import metadata
from typing import Any

from . import PIN as _PACKAGE_PIN
from .errors import KernelMissingError, OperationError

__all__ = [
    "OCCT_VERSION",
    "PIN",
    "area_centroid",
    "boundary",
    "box_limits",
    "centroid",
    "copy",
    "edges",
    "faces",
    "from_bytes",
    "is_opencascades",
    "is_valid",
    "listed",
    "loosest_tolerance",
    "perimeter",
    "plane_of",
    "shape_list",
    "shells",
    "solids",
    "surface_area",
    "tightened",
    "to_bytes",
    "vertices",
    "volume",
    "widened_to_curves",
]

#: The OCP wheel Forge is built and tested against, and the OpenCascade it carries.
PIN = _PACKAGE_PIN
OCCT_VERSION = "8.0.1"
_DISTRIBUTION = "cadquery-ocp-novtk"


def _installed() -> str:
    try:
        return metadata.version(_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        raise KernelMissingError(
            'the exact kernel is not installed: pip install -e ".[exact]" in the Forge folder',
            needs=f"{_DISTRIBUTION}=={PIN}",
        ) from None


if _installed() != PIN:
    raise KernelMissingError(
        f"the exact kernel is {_DISTRIBUTION} {_installed()}, and Forge is built and "
        f'tested against {PIN} only: pip install -e ".[exact]" in the Forge folder',
        installed=_installed(),
        needs=PIN,
    )

from OCP.BinTools import BinTools, BinTools_FormatVersion  # noqa: E402
from OCP.BRep import BRep_Builder, BRep_Tool  # noqa: E402
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface  # noqa: E402
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.BRepLib import BRepLib, BRepLib_ValidateEdge  # noqa: E402
from OCP.collections import (  # noqa: E402
    IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as TopTools_IndexedMapOfShape,
)
from OCP.collections import List_TopoDS_Shape as TopTools_ListOfShape  # noqa: E402
from OCP.GeomAbs import GeomAbs_Plane  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.Message import Message, Message_Gravity  # noqa: E402
from OCP.Standard import Standard_Failure  # noqa: E402
from OCP.TopAbs import (  # noqa: E402
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_REVERSED,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_VERTEX,
)
from OCP.TopExp import TopExp, TopExp_Explorer  # noqa: E402
from OCP.TopoDS import TopoDS, TopoDS_Shape  # noqa: E402

#: How fine OpenCascade integrates a volume or an area (its adaptive Gauss integration's own measure).
#: At 1e-9 a sphere made a rational B-spline came out 2.1e-7 relative off; at 1e-12, 3e-9 (tested:
#: forge_occ.measure's interval of 1e-6 relative holds it with a margin of five and more). The parts
#: Forge builds converge at either, at no cost worth counting.
INTEGRATION = 1e-12


def _quiet() -> None:
    """OpenCascade's messenger reports failures only: nothing else reaches standard output."""
    printers = Message.DefaultMessenger_s().Printers()
    for index in range(1, printers.Size() + 1):
        printers.Value(index).SetTraceLevel(Message_Gravity.Message_Fail)


_quiet()


def is_opencascades(error: BaseException) -> bool:
    """Whether ``error`` is one of OpenCascade's exceptions (any class the OCP bindings define)."""
    return (
        isinstance(error, Standard_Failure)
        or type(error).__module__.split(".")[0] == "OCP"
    )


@contextmanager
def boundary(what: str, **detail: Any) -> Iterator[None]:
    """Turn OpenCascade's exception into an :class:`OperationError` saying what was being done."""
    try:
        yield
    except Exception as error:
        if not is_opencascades(error):
            raise
        said = str(error).strip() or type(error).__name__
        raise OperationError(
            f"{what}: OpenCascade refused it ({type(error).__name__}: {said})", **detail
        ) from error


# --- shapes in a fixed order ----------------------------------------------------------


def _mapped(shape: TopoDS_Shape, kind: Any) -> TopTools_IndexedMapOfShape:
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, found)
    return found


def _listed(shape: TopoDS_Shape, kind: Any, cast: Any) -> list[Any]:
    found = _mapped(shape, kind)
    return [cast(found.FindKey(i)) for i in range(1, found.Extent() + 1)]


def plane_of(
    face: Any,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """A planar face's plane: a point of it, and the face's outward unit normal; None for any other face.

    The outward normal is the surface's (its u direction crossed with its v
    direction), reversed where the face is: a plane's frame may be
    left-handed (a revolve's flat ends are), when that is the opposite of the
    frame's own main direction.
    """
    surface = BRepAdaptor_Surface(TopoDS.Face(face))
    if surface.GetType() != GeomAbs_Plane:
        return None
    position = surface.Plane().Position()
    d, o = position.Direction(), position.Location()
    sign = 1.0 if position.Direct() else -1.0
    if TopoDS.Face(face).Orientation() == TopAbs_REVERSED:
        sign = -sign
    return (o.X(), o.Y(), o.Z()), (
        sign * d.X() + 0.0,
        sign * d.Y() + 0.0,
        sign * d.Z() + 0.0,
    )


def faces(shape: TopoDS_Shape) -> list[Any]:
    """Every face of the shape once, in OpenCascade's own fixed order."""
    return _listed(shape, TopAbs_FACE, TopoDS.Face)


def edges(shape: TopoDS_Shape) -> list[Any]:
    return _listed(shape, TopAbs_EDGE, TopoDS.Edge)


def vertices(shape: TopoDS_Shape) -> list[Any]:
    return _listed(shape, TopAbs_VERTEX, TopoDS.Vertex)


def shells(shape: TopoDS_Shape) -> list[Any]:
    return _listed(shape, TopAbs_SHELL, TopoDS.Shell)


def solids(shape: TopoDS_Shape) -> list[Any]:
    return _listed(shape, TopAbs_SOLID, TopoDS.Solid)


def box_limits(box: Any) -> tuple[float, float, float, float, float, float]:
    """A ``Bnd_Box``'s limits, its gap included: ``(xmin, ymin, zmin, xmax, ymax, zmax)``.

    OpenCascade 8 returns ``Bnd_Box::Get`` as a struct the bindings can't
    convert; its corners, gap included, are what ``Get`` gave on 7.9.3.
    """
    low, high = box.CornerMin(), box.CornerMax()
    return (low.X(), low.Y(), low.Z(), high.X(), high.Y(), high.Z())


def listed(shapes: TopTools_ListOfShape) -> list[TopoDS_Shape]:
    """A ``TopTools`` list as a Python list, in its order."""
    return list(shapes)


def shape_list(shapes: Iterable[TopoDS_Shape]) -> TopTools_ListOfShape:
    out = TopTools_ListOfShape()
    for shape in shapes:
        out.Append(shape)
    return out


# --- what a shape is ------------------------------------------------------------------


def is_valid(shape: TopoDS_Shape) -> bool:
    """OpenCascade's own validity check (geometry, topology, orientation, tolerances)."""
    with boundary("checking a shape"):
        return bool(BRepCheck_Analyzer(shape).IsValid())


def loosest_tolerance(shape: TopoDS_Shape) -> float:
    """The largest tolerance on any face, edge or vertex of the shape (mm)."""
    found = 0.0
    for kind, cast in (
        (TopAbs_FACE, TopoDS.Face),
        (TopAbs_EDGE, TopoDS.Edge),
        (TopAbs_VERTEX, TopoDS.Vertex),
    ):
        explorer = TopExp_Explorer(shape, kind)
        while explorer.More():
            found = max(found, float(BRep_Tool.Tolerance_s(cast(explorer.Current()))))
            explorer.Next()
    return found


#: Above this a shape's tolerances are worked out again from its geometry (mm).
TIGHTEN = 1e-5


def tightened(shape: TopoDS_Shape) -> TopoDS_Shape:
    """The shape with each edge's and vertex's tolerance worked out again from its geometry, where any is loose.

    OpenCascade gives the vertices and edges a boolean makes where curved
    faces meet tolerances wider than their curves need (seen: 1.5e-4 mm on a
    vertex between two holes round a rod, whose curves meet within 7.6e-6 mm).
    ``BRepLib::UpdateTolerances`` sets each to what its own edges and faces
    need, no more and no less: a real gap keeps a tolerance as wide as the
    gap, which the after-check still refuses. The shape is tightened in
    place, and only where that makes its loosest tolerance smaller and
    leaves it valid (tried first on a copy); otherwise it is left as it was.
    """
    loosest = loosest_tolerance(shape)
    if loosest <= TIGHTEN:
        return shape
    with boundary("working out tolerances again"):
        trial = BRepBuilderAPI_Copy(shape, True, False).Shape()
        BRepLib.UpdateTolerances_s(trial, True)
        if (
            loosest_tolerance(trial) >= loosest
            or not BRepCheck_Analyzer(trial).IsValid()
        ):
            return shape
        BRepLib.UpdateTolerances_s(shape, True)
    return shape


#: What a curve's greatest distance from another is taken a little over: the exact measure finds it by optimisation, from below.
_MEASURED_MARGIN = 0.05


def widened_to_curves(shape: TopoDS_Shape) -> TopoDS_Shape:
    """The shape with each edge's tolerance raised to cover how far its curve on each of its faces strays from its own curve, measured exactly; in place.

    An edge's tolerance says its curve and its curve on each of its faces are
    nowhere farther apart, at the same parameter, than it. What sets it from
    the curves (``BRepLib::SameParameter``, and through it OpenCascade's STEP
    reader) and what checks it (``BRepCheck_Analyzer``) compare them at a few
    dozen points along the edge, and a curve on a face made again to follow
    the edge's parameter strays most between them. Generated part 6950,
    read back from STEP: a small bore's curve on its face, where it meets a
    big hole, 3.9e-5 mm off the edge near one end (2.7e-6 mm off the edge's
    curve anywhere), the edge stating 1e-7 mm and the checker passing it; a
    point of the face 1.3e-6 mm from that edge fell outside the face as read.
    ``BRepLib_ValidateEdge``'s exact method finds the greatest distance along
    the whole edge (where it can't, a thousand points are compared); each
    edge is raised to it and a twentieth more, and each vertex to its edges.
    Nothing is lowered, and where every edge holds, nothing changes.
    """
    builder = BRep_Builder()
    with boundary("measuring edges against their faces"):
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            face = TopoDS.Face(explorer.Current())
            explorer.Next()
            around = TopExp_Explorer(face, TopAbs_EDGE)
            while around.More():
                edge = TopoDS.Edge(around.Current())
                around.Next()
                if BRep_Tool.Degenerated_s(edge):
                    continue
                stray = _stray(edge, face)
                if stray <= BRep_Tool.Tolerance_s(edge):
                    continue
                wider = stray * (1.0 + _MEASURED_MARGIN)
                builder.UpdateEdge(edge, wider)
                for vertex in (TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge)):
                    if not vertex.IsNull():
                        builder.UpdateVertex(vertex, wider)
    return shape


def _stray(edge: Any, face: Any) -> float:
    """The greatest distance, at the same parameter, between an edge's curve and its curve on the face (mm)."""
    curve = BRepAdaptor_Curve(edge)
    on_face = BRepAdaptor_Curve(edge, face).CurveOnSurface()
    same = BRep_Tool.SameParameter_s(edge)
    for exact in (True, False):
        check = BRepLib_ValidateEdge(curve, on_face, same)
        check.SetExactMethod(exact)
        if not exact:
            check.SetControlPointsNumber(1000)
        check.Process()
        if check.IsDone():
            return float(check.GetMaxDistance())
    raise OperationError(
        "an edge's curve could not be measured against its curve on a face"
    )


def _volume_properties(shape: TopoDS_Shape) -> GProp_GProps:
    props = GProp_GProps()
    with boundary("measuring a volume"):
        BRepGProp.VolumeProperties_s(shape, props, INTEGRATION, False)
    return props


#: Volumes already integrated, by the shape they are of (the same shape: its topology, place
#: and orientation); a few hundred, the oldest forgotten first.
_VOLUMES: OrderedDict[int, list[tuple[TopoDS_Shape, float]]] = OrderedDict()
_REMEMBERED = 512


def volume(shape: TopoDS_Shape) -> float:
    """The shape's volume in mm³ (integrated at :data:`INTEGRATION`; see :mod:`~forge_occ.measure` for the interval).

    Integrating a B-spline part's volume takes a good part of a second, and a
    build asks for the same shape's more than once (validation, the
    after-check, the trace), so each is remembered for the shape it is of.
    """
    key = hash(shape)
    for known, value in _VOLUMES.get(key, ()):
        if known.IsEqual(shape):
            _VOLUMES.move_to_end(key)
            return value
    value = float(_volume_properties(shape).Mass())
    if not math.isfinite(value):
        raise OperationError("a shape's volume came back as no number")
    _VOLUMES.setdefault(key, []).append((shape, value))
    _VOLUMES.move_to_end(key)
    while len(_VOLUMES) > _REMEMBERED:
        _VOLUMES.popitem(last=False)
    return value


def centroid(shape: TopoDS_Shape) -> tuple[float, float, float]:
    point = _volume_properties(shape).CentreOfMass()
    return float(point.X()), float(point.Y()), float(point.Z())


def surface_area(shape: TopoDS_Shape) -> float:
    props = GProp_GProps()
    with boundary("measuring an area"):
        BRepGProp.SurfaceProperties_s(shape, props, INTEGRATION, False)
    return float(props.Mass())


def area_centroid(shape: TopoDS_Shape) -> tuple[float, float, float]:
    """The centre of the shape's faces' area (of a planar face: its section's centroid, for Pappus)."""
    props = GProp_GProps()
    with boundary("measuring an area"):
        BRepGProp.SurfaceProperties_s(shape, props, INTEGRATION, False)
    point = props.CentreOfMass()
    return float(point.X()), float(point.Y()), float(point.Z())


def perimeter(shape: TopoDS_Shape) -> float:
    """The total length of the shape's edges."""
    props = GProp_GProps()
    with boundary("measuring a length"):
        BRepGProp.LinearProperties_s(shape, props, False, False)
    return float(props.Mass())


# --- copies ---------------------------------------------------------------------------


def copy(shape: TopoDS_Shape) -> TopoDS_Shape:
    """A deep copy: new topology and geometry, no mesh, sharing nothing with ``shape``."""
    with boundary("copying a shape"):
        return BRepBuilderAPI_Copy(shape, True, False).Shape()


def to_bytes(shape: TopoDS_Shape) -> bytes:
    """The shape in OpenCascade's binary format, without any mesh (deterministic)."""
    stream = io.BytesIO()
    with boundary("serializing a shape"):
        BinTools.Write_s(
            shape,
            stream,
            False,
            False,
            BinTools_FormatVersion.BinTools_FormatVersion_CURRENT,
        )
    return stream.getvalue()


def from_bytes(data: bytes) -> TopoDS_Shape:
    """A new shape read from :func:`to_bytes`'s bytes."""
    shape = TopoDS_Shape()
    with boundary("reading a serialized shape"):
        BinTools.Read_s(shape, io.BytesIO(data))
    if shape.IsNull():
        raise OperationError("a serialized shape read back as nothing")
    return shape
