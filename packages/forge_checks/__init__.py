"""forge_checks - the judge: views of a built part, the spec's own shape, and the checks.

Nothing in this package can see how a part was made. It reads the confirmed
spec through its fields, places every item itself from the written
definitions (never from the solver's coordinates), and looks at the built
part only through a :class:`~forge_checks.view.GeometryView`, behind a
:class:`~forge_checks.view.ViewProxy` (rule R2, enforced by
tests/test_v2_architecture.py).

This package is part of the trust core: it imports only the standard library,
NumPy and other trust-core packages, and no model or CAD library (ADR-0002).

Built so far (stage 2, docs/V2-stage2.md):

- :mod:`~forge_checks.view`: what every view answers, and the proxy;
- :mod:`~forge_checks.predicates`: orientation signs, exactly;
- :mod:`~forge_checks.triangles`: nearest points and watertight ray crossings;
- :mod:`~forge_checks.tree`: the box tree every search walks;
- :mod:`~forge_checks.intersect`: do two triangles meet where they aren't joined;
- :mod:`~forge_checks.mesh`: the mesh view, for STL and 3MF;
- :mod:`~forge_checks.readers`: reading STL and 3MF files;
- :mod:`~forge_checks.outlines`: outlines in a face's plane, exactly;
- :mod:`~forge_checks.place`: where the definitions put every item, and how
  that compares with the solver's layout;
- :mod:`~forge_checks.shapes`: exact solids: signed distance, nearest
  point, normal, and the facets at a point;
- :mod:`~forge_checks.oracle`: the spec's own shape, made in order, and
  which side of it any point is;
- :mod:`~forge_checks.classes`: verification classes, design tolerances and
  the verdict a measurement gives;
- :mod:`~forge_checks.capabilities`: what each kind of view must answer,
  and how it holds each item kind;
- :mod:`~forge_checks.accounting`: face accounting, both ways;
- :mod:`~forge_checks.topology`: the built topology and volume against the
  spec's;
- :mod:`~forge_checks.measure`: windows of built points near the spec's
  surfaces, and fits with worst-case uncertainties;
- :mod:`~forge_checks.kinds`: each check kind's targets, measurement,
  tolerance policy, mutants and near-misses;
- :mod:`~forge_checks.checks`: a check, and the evidence it gives;
- :mod:`~forge_checks.telling`: points that tell one choice's shape from
  another's;
- :mod:`~forge_checks.compiler`: every leaf of the spec, as checks or with
  the reason it can't be checked (rule R1).
"""

from __future__ import annotations

from .mesh import ON_BAND, Mesh, MeshShape, MeshView
from .readers import MeshFile, MeshFileError, read_3mf, read_mesh_file, read_stl
from .view import (
    Box,
    Capability,
    Coverage,
    Crossings,
    EdgeFacts,
    FaceFacts,
    GeometryView,
    NotAnswerableError,
    Resolution,
    Side,
    Topology,
    ViewError,
    ViewProxy,
)

__all__ = [
    "ON_BAND",
    "Box",
    "Capability",
    "Coverage",
    "Crossings",
    "EdgeFacts",
    "FaceFacts",
    "GeometryView",
    "Mesh",
    "MeshFile",
    "MeshFileError",
    "MeshShape",
    "MeshView",
    "NotAnswerableError",
    "Resolution",
    "Side",
    "Topology",
    "ViewError",
    "ViewProxy",
    "read_3mf",
    "read_mesh_file",
    "read_stl",
]
