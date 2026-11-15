"""The copying cache: a step built once is built once, and every reuse is a fresh copy (docs/V2-stage3.md, section 10).

**The key** of a step is the SHA-256 of the canonical JSON of everything its
product depends on: its operation, its resolved parameters and references,
its inputs' keys, its id and role (which its faces' names carry), V1's
envelopes where the step takes them from V1 (holes and bends, 7.4), the
backend's identity with OpenCascade's version, the boolean fuzzy value, and
the cache scheme's version. Floats are written exactly (``float.hex``), so
two parameters that differ in the last bit are two keys. A value the key
can't write exactly is refused, never written as its ``str``.

**An entry** is the product's solid serialized with ``BinTools`` (no mesh),
its faces' names by face index, and what the trace says of it, behind a
header and a SHA-256 of the whole. Each hit is deserialized anew: no two
builds ever hold the same shape, so nothing a caller does to a part it was
given (meshing it, moving it, changing a tolerance) can reach the next.

**The store** is an in-memory LRU bounded by bytes (256 MB by default), with
an optional directory behind it. An entry that can't be read back exactly
(truncated, altered, from another scheme, its face count not its names'
count) is a miss, counted, and never an error.

This is what stops V1's "the cache served the wrong geometry".
"""

from __future__ import annotations

import builtins
import contextlib
import hashlib
import json
import math
import os
import struct
import tempfile
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .errors import OccError
from .make import FUZZY
from .names import Name, Names
from .occt import OCCT_VERSION, faces, from_bytes, to_bytes
from .products import SolidProduct

if TYPE_CHECKING:
    from .ops.bend import BendSpec

__all__ = ["SCHEME", "CacheStats", "StepCache", "canonical", "step_key"]

#: The cache's scheme: raised whenever what an entry holds, or what a key covers, changes.
SCHEME = 1
_MAGIC = b"FORGE-OCC-STEPS\x00"  # sixteen bytes, as the header packs it
_HEADER = struct.Struct("<16sIQQ")  # magic, scheme, JSON length, shape bytes length
_DIGEST = 32


def _number(value: float) -> Any:
    if not math.isfinite(value):
        raise TypeError(f"a cache key can't hold {value!r}")
    return {"f": float(value).hex()}


def canonical(value: Any) -> Any:
    """``value`` as JSON that says exactly what it is: floats by their bits, mappings by sorted key."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return {"i": str(value)}
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, Mapping):
        keys = list(value)
        if not all(isinstance(k, str) for k in keys):
            raise TypeError("a cache key's mappings are keyed by strings")
        return {"m": [[k, canonical(value[k])] for k in sorted(keys)]}
    if isinstance(value, Sequence):
        return {"s": [canonical(v) for v in value]}
    as_json = getattr(value, "as_json", None)
    if callable(as_json):
        return {"j": canonical(as_json())}
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "d": type(value).__name__,
            "v": canonical({f.name: getattr(value, f.name) for f in fields(value)}),
        }
    if hasattr(value, "item") and callable(value.item):  # a NumPy scalar
        return canonical(value.item())
    raise TypeError(f"a cache key can't hold a {type(value).__name__} exactly")


def step_key(*, identity: str, op: str, step: str, role: str, params: Mapping[str, Any],
             references: Mapping[str, Any], inputs: Sequence[str], v1: Any) -> str:  # fmt: skip
    """The key of a step's product."""
    document = {
        "scheme": SCHEME, "backend": identity, "occt": OCCT_VERSION, "fuzzy": FUZZY,
        "op": op, "step": step, "role": role, "params": params, "references": references,
        "inputs": list(inputs), "v1": v1,
    }  # fmt: skip
    text = json.dumps(canonical(document), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


# --- entries -------------------------------------------------------------------------


def _names_json(names: Names) -> list[list[list[Any]]]:
    return [sorted([n.step, n.role, n.copy] for n in held) for held in names.table]


def _names_from(shape: Any, table: Any) -> Names:
    return Names(
        shape,
        tuple(
            frozenset(Name(str(s), str(r), int(c)) for s, r, c in held)
            for held in table
        ),
    )


def _encode(product: SolidProduct) -> bytes:
    from .ops.bend import BendSpec

    flat = product.flat
    if flat is not None and not isinstance(flat, SolidProduct):
        raise TypeError("a bend's flat part is a solid")
    if not all(isinstance(spec, BendSpec) for spec in product.chain):
        raise TypeError("a bend's chain is its BendSpecs")
    shapes = [to_bytes(product.shape)] + (
        [to_bytes(flat.shape)] if flat is not None else []
    )
    header = {
        "names": _names_json(product.names),
        "faces": len(product.names.table),
        "notes": list(product.notes),
        "tolerance": float(product.tolerance).hex(),
        "lost": sorted([n.step, n.role, n.copy] for n in product.lost),
        "expect": None if product.expect is None else [float(product.expect[0]).hex(), float(product.expect[1]).hex(),
                                                        str(product.expect[2])],
        "chain": [asdict(spec) for spec in product.chain],
        "flat": None if flat is None else {
            "names": _names_json(flat.names), "faces": len(flat.names.table), "bytes": len(shapes[1]),
        },
    }  # fmt: skip
    text = json.dumps(header, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    body = (
        _HEADER.pack(_MAGIC, SCHEME, len(text), len(shapes[0]))
        + text
        + b"".join(shapes)
    )
    return body + hashlib.sha256(body).digest()


def _bend_spec(fields_: Mapping[str, Any]) -> BendSpec:
    """A bend of a chain from its JSON form (lists back to the tuples it holds)."""
    from .ops.bend import BendSpec

    return BendSpec(
        position=_vec3(fields_["position"]), along=_vec3(fields_["along"]), toward=_vec3(fields_["toward"]),
        angle=float(fields_["angle"]), radius=float(fields_["radius"]), face=float(fields_["face"]),
        thickness=float(fields_["thickness"]), hold=float(fields_["hold"]),
    )  # fmt: skip


def _vec3(value: Any) -> tuple[float, float, float]:
    x, y, z = (float(c) for c in value)
    return x, y, z


def _decode(data: bytes) -> SolidProduct:
    if len(data) < _HEADER.size + _DIGEST:
        raise ValueError("too short")
    body, digest = data[:-_DIGEST], data[-_DIGEST:]
    if hashlib.sha256(body).digest() != digest:
        raise ValueError("altered")
    magic, scheme, size, shape_size = _HEADER.unpack_from(body)
    if magic != _MAGIC or scheme != SCHEME:
        raise ValueError("another scheme")
    start = _HEADER.size
    header = json.loads(body[start : start + size].decode("ascii"))
    start += size
    shape = from_bytes(body[start : start + shape_size])
    start += shape_size
    if len(faces(shape)) != header["faces"]:
        raise ValueError("its faces aren't its names'")
    flat = None
    if header["flat"] is not None:
        flat_shape = from_bytes(body[start : start + header["flat"]["bytes"]])
        start += header["flat"]["bytes"]
        if len(faces(flat_shape)) != header["flat"]["faces"]:
            raise ValueError("its flat part's faces aren't its names'")
        flat = SolidProduct(
            flat_shape, _names_from(flat_shape, header["flat"]["names"])
        )
    if start != len(body):
        raise ValueError("trailing bytes")
    expect = header["expect"]
    return SolidProduct(
        shape, _names_from(shape, header["names"]), notes=tuple(header["notes"]),
        tolerance=float.fromhex(header["tolerance"]),
        lost=frozenset(Name(s, r, int(c)) for s, r, c in header["lost"]),
        expect=None if expect is None else (float.fromhex(expect[0]), float.fromhex(expect[1]), expect[2]),
        chain=tuple(_bend_spec(spec) for spec in header["chain"]),
        flat=flat,
    )  # fmt: skip


# --- the store -----------------------------------------------------------------------


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    stored: int = 0
    unreadable: int = 0
    evicted: int = 0


class StepCache:
    """Steps' products by key: in memory, bounded by bytes, and optionally in a directory."""

    def __init__(
        self,
        *,
        max_bytes: int = 256 * 1024 * 1024,
        directory: str | os.PathLike[str] | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("a cache needs room for something")
        self.max_bytes = int(max_bytes)
        self.directory = Path(directory) if directory is not None else None
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._bytes = 0
        self.stats = CacheStats()

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def bytes(self) -> int:
        return self._bytes

    def get(self, key: str) -> SolidProduct | None:
        """A fresh copy of the product stored under ``key``, or None."""
        data = self._entries.get(key)
        if data is not None:
            self._entries.move_to_end(key)
        elif self.directory is not None:
            data = self._read(key)
        if data is None:
            self.stats.misses += 1
            return None
        try:
            product = _decode(data)
        except (
            ValueError,
            KeyError,
            TypeError,
            OccError,
            UnicodeDecodeError,
            struct.error,
            json.JSONDecodeError,
        ):
            self._forget(key)
            self.stats.unreadable += 1
            self.stats.misses += 1
            return None
        if key not in self._entries:
            self._remember(key, data)
        self.stats.hits += 1
        return product

    def put(self, key: str, product: SolidProduct) -> None:
        """Store ``product`` under ``key`` (serialized now: nothing done to it later reaches the cache)."""
        data = _encode(product)
        self._remember(key, data)
        self.stats.stored += 1
        if self.directory is not None:
            self._write(key, data)

    # --- memory ------------------------------------------------------------------------
    def _remember(self, key: str, data: builtins.bytes) -> None:
        if len(data) > self.max_bytes:
            return
        old = self._entries.pop(key, None)
        if old is not None:
            self._bytes -= len(old)
        self._entries[key] = data
        self._bytes += len(data)
        while self._bytes > self.max_bytes:
            _, dropped = self._entries.popitem(last=False)
            self._bytes -= len(dropped)
            self.stats.evicted += 1

    def _forget(self, key: str) -> None:
        old = self._entries.pop(key, None)
        if old is not None:
            self._bytes -= len(old)
        if self.directory is not None:
            with contextlib.suppress(OSError):
                self._path(key).unlink()

    # --- the directory -----------------------------------------------------------------
    def _path(self, key: str) -> Path:
        assert self.directory is not None
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("a cache key is a SHA-256 in hex")
        return self.directory / key[:2] / f"{key}.step-cache"

    def _read(self, key: str) -> builtins.bytes | None:
        try:
            return self._path(key).read_bytes()
        except OSError:
            return None

    def _write(self, key: str, data: builtins.bytes) -> None:
        """Written whole or not at all (a temporary file renamed into place); a directory that can't be written is no cache, not a failed build."""
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".writing-")
        except OSError:
            return
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(data)
            os.replace(temporary, path)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
