"""forge_occ - the exact kernel: OpenCascade builds every part (docs/V2-stage3.md).

Importing this package needs nothing but the standard library: whether the
exact kernel can run here is :func:`status`. Its modules import OpenCascade
through :mod:`forge_occ.occt`, which refuses any version but the one Forge is
built and tested against.
"""

from __future__ import annotations

from importlib import metadata

__all__ = ["PIN", "status"]

#: The OCP wheel the exact kernel is built and tested against.
PIN = "8.0.1.1.0"


def status() -> str | None:
    """Why the exact kernel can't run here, or None when it can."""
    try:
        installed = metadata.version("cadquery-ocp-novtk")
    except metadata.PackageNotFoundError:
        return 'the exact kernel is not installed: pip install -e ".[exact]" in the Forge folder'
    if installed != PIN:
        return (
            f"the exact kernel is cadquery-ocp-novtk {installed}; Forge is built and "
            f'tested against {PIN} only: pip install -e ".[exact]" in the Forge folder'
        )
    return None
