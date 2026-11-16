"""The compiled twin of :mod:`forge_numeric.vector` (native/forge_numeric_native; ADR-0037), when this machine has it.

A library built for each platform from ``native/forge_numeric_native`` sits in
``_native/<platform>/``. It is used only if its interface version is this
module's, its source digest is the digest of the source beside it (a library
built from other source is refused), and it reproduces the NumPy twin on a
fixed set of inputs at load (:mod:`.vector`). Otherwise :mod:`.vector`
computes everything with NumPy: the same bits, more slowly. (V2 code reads
no environment variable, so nothing turns it off from outside; the tests set
``forge_numeric.vector._use`` to None to run the NumPy twin.)
"""

from __future__ import annotations

import ctypes
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np

ABI = 3
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

_P = ctypes.c_void_p
_N = ctypes.c_size_t


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
    if SOURCE.exists() and fnv1a(SOURCE.read_bytes()) != built:
        return (
            None,
            f"built from other source ({built}, the source is {fnv1a(SOURCE.read_bytes())})",
        )
    for name in (
        "fnum_atan",
        "fnum_asin",
        "fnum_acos",
        "fnum_exp",
        "fnum_log",
        "fnum_cbrt",
    ):
        f = getattr(lib, name)
        f.argtypes = [_P, _P, _N]
        f.restype = None
    lib.fnum_sincos.argtypes = [_P, _P, _P, _N]
    lib.fnum_sincos.restype = _N
    lib.fnum_atan2.argtypes = [_P, _P, _P, _N]
    lib.fnum_atan2.restype = None
    lib.fnum_hypot.argtypes = [_P, _P, _P, _N]
    lib.fnum_hypot.restype = _N
    lib.fnum_matmul.argtypes = [_P, _P, _P, _N, _N, _N]
    lib.fnum_matmul.restype = None
    return lib, ""


LIB: Any
WHY_NOT: str
LIB, WHY_NOT = _open()


def unary(name: str, x: np.ndarray) -> np.ndarray:
    """``x`` (contiguous float64) through the library's elementwise ``fnum_<name>``."""
    out = np.empty_like(x)
    getattr(LIB, "fnum_" + name)(x.ctypes.data, out.ctypes.data, x.size)
    return out


def sincos(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """(sin, cos, how many elements were deferred: written NaN, for the caller to compute)."""
    s = np.empty_like(x)
    c = np.empty_like(x)
    return s, c, LIB.fnum_sincos(x.ctypes.data, s.ctypes.data, c.ctypes.data, x.size)


def atan2(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    out = np.empty_like(x)
    LIB.fnum_atan2(y.ctypes.data, x.ctypes.data, out.ctypes.data, x.size)
    return out


def hypot(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, int]:
    """(the lengths, how many elements were deferred: written NaN, for the caller)."""
    out = np.empty_like(x)
    return out, LIB.fnum_hypot(x.ctypes.data, y.ctypes.data, out.ctypes.data, x.size)


def matmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """``a`` (rows by k, contiguous float64) times ``b`` (k by cols, the same), sums left to right."""
    out = np.empty((a.shape[0], b.shape[1]))
    LIB.fnum_matmul(
        a.ctypes.data,
        b.ctypes.data,
        out.ctypes.data,
        a.shape[0],
        a.shape[1],
        b.shape[1],
    )
    return out
