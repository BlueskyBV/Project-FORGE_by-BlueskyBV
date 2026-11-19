"""``forge doctor``: whether the exact kernel works here, one line a check (docs/V2-stage3.md, section 15).

The checks, in order, each printed as it is done (``ok`` or ``FAIL``, and
what was found):

1. Python is 3.14 or later.
2. The exact kernel's pins: the OCP wheel Forge is built and tested against
   (``cadquery-ocp-novtk``, OpenCascade 8.0.1) and lib3mf.
3. A probe part built by the exact kernel, every step after-checked: a plate
   with a counterbored hole, an edge rounded and a bend. Its volume against
   the one worked out by hand (the bend keeps a flat plate's volume, a
   rounded straight edge loses its section times its length), and the names
   its steps give its faces.
4. The probe exported as STEP, STL and 3MF, each read back and held to the
   part (section 12).

The exit code is 0 when every check passes, 1 otherwise. Nothing here reads
the environment or needs a key.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable
from importlib import metadata
from typing import Any

__all__ = ["LIB3MF", "PROBE", "add_doctor_parser", "probe_volume", "run_doctor"]

#: The lib3mf release Forge writes 3MF with.
LIB3MF = "2.5.0"
#: The oldest Python Forge runs on (pyproject's requires-python).
MINIMUM_PYTHON = (3, 14)


def _mm(value: float) -> dict[str, Any]:
    return {"magnitude": value, "unit": "mm"}


def _at(*value: float) -> dict[str, Any]:
    return {"vector": list(value), "unit": "mm"}


#: The probe part: a 60 x 40 x 6 mm plate; a 6 mm hole through it at (15, 20), counterbored 11 mm
#: across and 3 deep; the edge between its top and its x_min face rounded 1 mm; bent 90 degrees about a
#: line along y at x = 40, inside radius 4 mm.
PROBE = {
    "schema_version": "2.0.0",
    "document_id": "forge-doctor",
    "project_id": "forge-doctor",
    "revision": 1,
    "name": "forge doctor's probe",
    "components": [
        {
            "id": "probe",
            "steps": [
                {
                    "id": "plate",
                    "op": "box",
                    "role": "plate",
                    "params": {"size": _at(60, 40, 6)},
                },
                {
                    "id": "mount",
                    "op": "hole",
                    "inputs": ["plate"],
                    "role": "mount",
                    "params": {
                        "diameter": _mm(6),
                        "position": _at(15, 20, 3),
                        "through": "all",
                        "counterbore_diameter": _mm(11),
                        "counterbore_depth": _mm(3),
                    },
                },
                {
                    "id": "edge",
                    "op": "fillet",
                    "inputs": ["mount"],
                    "params": {
                        "radius": _mm(1),
                        "edges": {
                            "between": [
                                {"created_by": "plate", "role": "z_max"},
                                {"created_by": "plate", "role": "x_min"},
                            ],
                            "match": {"count": [1, 1]},
                        },
                    },
                },
                {
                    "id": "fold",
                    "op": "bend",
                    "inputs": ["edge"],
                    "params": {
                        "angle": {"magnitude": 90, "unit": "deg"},
                        "position": _at(40, 20, 3),
                        "along": [1, 0, 0],
                        "toward": [0, 0, 1],
                        "radius": _mm(4),
                    },
                },
            ],
        }
    ],
}

#: The names the probe's faces must carry.
PROBE_NAMES = ("plate.z_max", "plate.x_min", "mount.bore", "mount.counterbore_wall", "mount.counterbore_floor",
               "edge.round")  # fmt: skip


def probe_volume() -> float:
    """The probe's volume worked out by hand (mm³)."""
    plate = 60.0 * 40.0 * 6.0
    hole = math.pi * (3.0 * 3.0) * 3.0 + math.pi * (5.5 * 5.5) * 3.0
    rounded = 40.0 * (1.0 * 1.0) * (1.0 - math.pi / 4.0)
    return plate - hole - rounded


Check = Callable[[], str]


def _python() -> str:
    found = sys.version_info[:2]
    if found < MINIMUM_PYTHON:
        raise RuntimeError(
            f"Python {sys.version.split()[0]}; Forge needs {'.'.join(map(str, MINIMUM_PYTHON))} or later"
        )
    return f"Python {sys.version.split()[0]}"


def _pins() -> str:
    import forge_occ

    missing = forge_occ.status()
    if missing is not None:
        raise RuntimeError(missing)
    try:
        found = metadata.version("lib3mf")
    except metadata.PackageNotFoundError as error:
        raise RuntimeError(
            'lib3mf is not installed: pip install -e ".[exact]" in the Forge folder'
        ) from error
    if found != LIB3MF:
        raise RuntimeError(
            f'lib3mf {found}; Forge writes 3MF with {LIB3MF}: pip install -e ".[exact]" in the Forge folder'
        )
    from forge_occ.occt import OCCT_VERSION

    return f"OpenCascade {OCCT_VERSION} (cadquery-ocp-novtk {forge_occ.PIN}), lib3mf {found}"


class _Probe:
    """The probe part, built once, for the checks that need it."""

    def __init__(self) -> None:
        self.result: Any = None

    def build(self) -> str:
        from forge_ir.v2 import DocumentV2
        from forge_occ.backend import OccBackend
        from forge_occ.occt import volume

        document = DocumentV2.from_json(json.dumps(PROBE))
        self.result = OccBackend().build(document, "probe")
        found, expected = volume(self.result.shape), probe_volume()
        if abs(found - expected) > 1e-6 * expected:
            raise RuntimeError(
                f"its volume is {found:.6f} mm³, where {expected:.6f} mm³ is worked out"
            )
        named = {str(n) for n in self.result.names.every()}
        missing = [n for n in PROBE_NAMES if n not in named]
        if missing:
            raise RuntimeError(f"faces aren't named {', '.join(missing)}")
        return f"probe built in {len(self.result.traces)} steps, every one after-checked; {found:.3f} mm³ as worked out; its faces named"

    def step(self) -> str:
        from forge_occ.export import StepPart, check_step, write_step

        shape = self._shape()
        data = write_step([StepPart("probe", shape)])
        _, report = check_step(data, [StepPart("probe", shape)])
        worst = max(report.parts["probe"].values())
        return f"STEP written ({len(data):,} bytes) and read back: within {worst:.1e} of the part"

    def meshes(self) -> str:
        from forge_occ.export import (
            ExportTolerance,
            check_mesh_file,
            mesh_part,
            plate_shift,
            stl_bytes,
            threemf_bytes,
        )

        shape = self._shape()
        tolerance = ExportTolerance()
        part = mesh_part(shape, tolerance)
        check_mesh_file(stl_bytes(part.mesh, "probe"), shape, part, tolerance)
        shift = plate_shift(part.mesh)
        check_mesh_file(
            threemf_bytes(part.mesh, "probe", shift),
            shape,
            part,
            tolerance,
            shift=shift,
        )
        return (f"STL and 3MF written and read back: {len(part.mesh.faces):,} triangles, "
                f"within {part.deviation:.4f} mm of the surface (tolerance {tolerance.linear:g} mm)")  # fmt: skip

    def _shape(self) -> Any:
        if self.result is None:
            raise RuntimeError("the probe wasn't built")
        return self.result.shape


def run_doctor(out: Any = None) -> int:
    """Run every check, printing a line for each; 0 if every one passed."""
    stream = out if out is not None else sys.stdout
    probe = _Probe()
    checks: list[tuple[str, Check]] = [
        ("python", _python), ("pins", _pins), ("probe", probe.build), ("step", probe.step),
        ("meshes", probe.meshes),
    ]  # fmt: skip
    failed = 0
    for name, check in checks:
        try:
            said = check()
        except (
            Exception
        ) as error:  # every failure is reported as the check's, and the rest still run
            failed += 1
            message = (
                getattr(error, "message", None) or str(error) or type(error).__name__
            )
            print(f"FAIL  {name:7s} {message}", file=stream)
        else:
            print(f"ok    {name:7s} {said}", file=stream)
    print(
        f"{'all checks passed' if not failed else f'{failed} of {len(checks)} checks failed'}",
        file=stream,
    )
    return 0 if not failed else 1


def _command(_args: argparse.Namespace) -> int:
    return run_doctor()


def add_doctor_parser(subparsers: Any) -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "doctor",
        help="check the exact kernel works here: its pins, a probe part built, STEP, STL and 3MF (V2)",
        description=(
            "Check that the exact kernel works here: the Python version and the pins, a probe "
            "part built and held to its volume and names, and STEP, STL and 3MF written and read "
            "back. One line a check; exit code 0 when all pass."
        ),
    )
    parser.set_defaults(handler=_command)
    return parser
