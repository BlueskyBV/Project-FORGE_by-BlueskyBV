"""forge_geom - the implicit reference geometry backend.

Forge runs two geometry kernels behind one adapter interface. This one is
implicit: solids are signed distance fields, booleans are ``min``/``max``,
fillets fall out of a smooth minimum, and nothing depends on a CAD library being
installed. The other is OpenCascade, which carries true B-Rep topology and can
export STEP.

The implicit kernel earns its place three ways:

*It always runs.* No compiled CAD kernel, no licence, no install. The whole
pipeline -- compile, measure, gate, report -- is exercisable in a network-isolated
container, which is what makes the deterministic core testable everywhere.

*It is fast enough to search with.* Evaluating a candidate takes milliseconds,
so an optimiser can screen thousands of parameter combinations before the exact
kernel is asked to build anything.

*It measures rigorously.* :mod:`forge_geom.measure` returns enclosures, not
estimates: a volume comes back as an interval that provably contains the true
value, with the discretisation error reported rather than hidden. That feeds
straight into three-valued gate evaluation, so a measurement too coarse to decide
a requirement says so instead of guessing.

What it cannot do is equally important and equally documented: it has no B-Rep
topology, so it cannot write STEP, cannot drive a Fusion feature tree, and cannot
name a face. Those are the exact kernel's job. When both kernels have built the
same design, their measurements are compared -- two independent implementations
agreeing is real evidence, and disagreeing is a bug worth finding.
"""

from __future__ import annotations

from .ibounds import IArray, cell_box
from .measure import (
    DEFAULT_MAX_CELLS,
    DEFAULT_MAX_DEPTH,
    MassProperties,
    measure_mass_properties,
    refine_extents,
    minimum_separation,
    minimum_wall_thickness,
    solids_interfere,
    surface_samples,
)
from .mesh import (
    TriangleMesh,
    extract_manifold_surface,
    extract_print_surface,
    surface_deviation,
    PRINT_CELL,
    extract_surface,
    write_obj,
    write_stl,
)
from .sdf import (
    SDF,
    Box,
    Bend,
    BoxSDF,
    CircleProfile,
    ConeSDF,
    CylinderSDF,
    DegenerateGeometryError,
    Difference,
    EmptyResultError,
    ExtrusionSDF,
    GeometryError,
    HalfSpaceSDF,
    Intersection,
    Mirror,
    Offset,
    PolygonProfile,
    Profile2D,
    RectangleProfile,
    Repeat,
    Revolve,
    Shell,
    GearProfile,
    SketchProfile,
    SlotProfile,
    SphereSDF,
    SweepSDF,
    TorusSDF,
    Transform,
    TubeSDF,
    LoftSDF,
    LoftStackSDF,
    stack_lofts,
    Union,
    gear_outline,
    helix_points,
    round_the_path,
    sketch_outline,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "SDF",
    "Bend",
    "Box",
    "BoxSDF",
    "SphereSDF",
    "CylinderSDF",
    "ConeSDF",
    "TorusSDF",
    "HalfSpaceSDF",
    "ExtrusionSDF",
    "Revolve",
    "Profile2D",
    "RectangleProfile",
    "CircleProfile",
    "SlotProfile",
    "SketchProfile",
    "GearProfile",
    "SweepSDF",
    "TubeSDF",
    "LoftSDF",
    "LoftStackSDF",
    "stack_lofts",
    "gear_outline",
    "helix_points",
    "round_the_path",
    "sketch_outline",
    "PolygonProfile",
    "Union",
    "Intersection",
    "Difference",
    "Shell",
    "Offset",
    "Transform",
    "Repeat",
    "Mirror",
    "GeometryError",
    "DegenerateGeometryError",
    "EmptyResultError",
    "MassProperties",
    "measure_mass_properties",
    "refine_extents",
    "minimum_separation",
    "solids_interfere",
    "minimum_wall_thickness",
    "surface_samples",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_CELLS",
    "TriangleMesh",
    "extract_surface",
    "extract_manifold_surface",
    "extract_print_surface",
    "surface_deviation",
    "PRINT_CELL",
    "write_stl",
    "write_obj",
    "IArray",
    "cell_box",
]
