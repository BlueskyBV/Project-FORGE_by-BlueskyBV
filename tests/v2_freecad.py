"""FreeCAD opening a STEP file, where FreeCAD can be run: for stage 3's exit test (docs/V2-stage3.md, 16).

FreeCAD is a second, independent reader of the files Forge hands over: a
file OpenCascade writes and reads back could still be one only OpenCascade
reads. Here FreeCAD 0.19 runs in a root of Ubuntu 22.04 (``/opt/roots/jammy``,
its ``freecadcmd``); where it isn't installed, :func:`missing` says why and
the tests needing it are skipped.

- :func:`opened`: one file read by ``Part.read``: valid, its solids, volume
  (FreeCAD's, at OpenCascade's default precision) and box (the faces'
  optimal one);
- :func:`inserted`: one file inserted as a document (``Import.insert``): each
  object's label, with its solids, volume and box.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

ROOT = Path("/opt/roots/jammy")
FREECAD = ROOT / "usr" / "bin" / "freecadcmd"
#: How long FreeCAD may take over one file (s).
TIMEOUT = 300

# The box from the faces' own geometry (FreeCAD's BoundBox is the loose one round their control points).
_SHAPE = """
def facts(shape):
    box = shape.optimalBoundingBox()  # (its arguments crash FreeCAD 0.19; a shape just read has no mesh to use)
    return {"valid": shape.isValid(), "solids": len(shape.Solids), "volume": shape.Volume,
            "bounds": [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax]}
"""

_OPEN = (
    _SHAPE
    + """
import json, Part
print("FORGE-FREECAD " + json.dumps(facts(Part.read(PATH))))
"""
)

# FreeCAD 0.19 without its interface crashes inserting an assembly as a group of links: plain objects.
_INSERT = (
    _SHAPE
    + """
import json, FreeCAD, Import
settings = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Import")
settings.SetBool("UseLinkGroup", False)
settings.SetInt("ImportMode", 0)
settings.SetBool("UseBaseName", True)
document = FreeCAD.newDocument("forge")
Import.insert(PATH, document.Name)
found = [dict(facts(o.Shape), label=o.Label) for o in document.Objects
         if hasattr(o, "Shape") and not o.Shape.isNull() and o.Shape.Solids]
print("FORGE-FREECAD " + json.dumps(found))
"""
)


def missing() -> str | None:
    """Why FreeCAD can't be run here, or None if it can."""
    if not (
        FREECAD.is_file() or FREECAD.is_symlink()
    ):  # a link inside the root, to a file only the root sees
        return f"FreeCAD isn't installed here ({FREECAD} is missing)"
    if (
        not hasattr(os, "geteuid")
        or os.geteuid() != 0
        or shutil.which("chroot") is None
    ):
        return "FreeCAD's root can be entered only as root, with chroot"
    if not (ROOT / "proc" / "self").exists():
        # FreeCAD finds itself through /proc/self/exe: a root whose /proc isn't mounted can't start it.
        return (
            f"FreeCAD's root has no /proc mounted (mount -t proc proc {ROOT / 'proc'})"
        )
    return None


def _run(data: bytes, script: str) -> Any:
    name = f"forge-{uuid.uuid4().hex}"
    step_path, script_path = ROOT / "tmp" / f"{name}.step", ROOT / "tmp" / f"{name}.py"
    step_path.write_bytes(data)
    script_path.write_text(
        f"PATH = {json.dumps(f'/tmp/{name}.step')}\n{script}", encoding="utf-8"
    )
    try:
        done = subprocess.run(["chroot", str(ROOT), "/usr/bin/freecadcmd", f"/tmp/{name}.py"],
                              capture_output=True, text=True, timeout=TIMEOUT, check=False)  # fmt: skip
    finally:
        step_path.unlink(missing_ok=True)
        script_path.unlink(missing_ok=True)
    for line in reversed(done.stdout.splitlines()):
        if line.startswith("FORGE-FREECAD "):
            return json.loads(line[len("FORGE-FREECAD ") :])
    raise RuntimeError(
        f"FreeCAD said nothing of the file: {(done.stdout + done.stderr)[-2000:]}"
    )


def opened(data: bytes) -> dict[str, Any]:
    """The file as FreeCAD's ``Part.read`` reads it: valid, solids, volume, box."""
    found: dict[str, Any] = _run(data, _OPEN)
    return found


def inserted(data: bytes) -> list[dict[str, Any]]:
    """Each object FreeCAD makes of the file inserted as a document: its label and its shape's facts."""
    found: list[dict[str, Any]] = _run(data, _INSERT)
    return found
