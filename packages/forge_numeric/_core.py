"""The compiled twin's library, opened without NumPy (native/forge_numeric_native; ADR-0037), when this machine has it.

A library built for each platform from ``native/forge_numeric_native`` sits in
``_native/<platform>/``. It is opened only if its interface version is this
module's and its source digest is the digest of the source beside it (a
library built from other source is refused). :mod:`.scalar` takes the
library's one-number entry points from here, and :mod:`._native` its array
ones; each tests what it takes against its own long way at load, and uses
the long way if they differ. Nothing here needs NumPy, so the scalar side
stays free of it.
"""

from __future__ import annotations

import ctypes
import platform
import sys
from pathlib import Path
from typing import Any

__all__ = ["ABI", "LIB", "SOURCE", "WHY_NOT", "fnv1a", "library_path"]

ABI = 6
HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent.parent / "native" / "forge_numeric_native" / "src" / "lib.rs"

#: The library's file for this platform, under _native/.
_NAMES = {
    ("linux", "x86_64"): "linux-x86_64/libforge_numeric_native.so",
    ("linux", "aarch64"): "linux-aarch64/libforge_numeric_native.so",
    ("win32", "amd64"): "windows-x86_64/forge_numeric_native.dll",
    ("darwin", "arm64"): "macos-arm64/libforge_numeric_native.dylib",
    ("darwin", "x86_64"): "macos-x86_64/libforge_numeric_native.dylib",
}

_D = ctypes.c_double


def fnv1a(data: bytes) -> str:
    """FNV-1a, 64 bits, as hex, over ``data`` less carriage returns: the digest build.rs compiles in."""
    h = 0xCBF29CE484222325
    for b in data.replace(b"\r", b""):
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def library_path() -> Path | None:
    name = _NAMES.get((sys.platform, platform.machine().lower()))
    return HERE / "_native" / name if name else None


def _open() -> tuple[Any | None, str]:
    """(the library, or None; why not, where None)."""
    path = library_path()
    if path is None:
        return None, f"no library for {sys.platform} {platform.machine()}"
    if not path.exists():
        return None, f"not built for this platform ({path.parent.name})"
    try:
        lib = ctypes.CDLL(str(path))
    except OSError as error:
        return None, f"can't be loaded: {error}"
    lib.fnum_abi.restype = ctypes.c_uint64
    if lib.fnum_abi() != ABI:
        return None, f"interface {lib.fnum_abi()}, not {ABI}"
    digest = ctypes.create_string_buffer(16)
    lib.fnum_source(digest)
    built = digest.raw.decode("ascii")
    if SOURCE.exists():
        source = fnv1a(SOURCE.read_bytes())
        if source != built:
            return None, f"built from other source ({built}, the source is {source})"
    for name, arity in (("fnum_hypot2_one", 2), ("fnum_hypot3_one", 3)):
        f = getattr(lib, name)
        f.argtypes = [_D] * arity
        f.restype = _D
    return lib, ""


LIB: Any
WHY_NOT: str
LIB, WHY_NOT = _open()
