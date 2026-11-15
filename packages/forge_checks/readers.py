"""Reading the mesh files Forge ships: STL, binary or text, and 3MF.

What is read is what the file says, nothing tidied: corners are kept to the
bit (a binary STL's 32-bit floats are exact in 64 bits), a NaN or an
infinite coordinate is kept and reported by the mesh's topology, a triangle
with a repeated corner is kept. A file that can't be read for sure is
refused with its reason (:class:`MeshFileError`), never guessed at: a number
must be written as one (ASCII digits, an optional sign, point and exponent),
and every way a package can fail to unpack is a refusal.

**STL.** A file whose length is exactly 84 bytes plus 50 per triangle its
header counts is binary, even if its header begins "solid" (many binary
exporters write that). Otherwise it must be text: ASCII, lines ended by a
line feed (a carriage return before it allowed), words parted by spaces or
tabs; ``solid``, then facets of exactly three vertices, then ``endsolid``;
keywords in any case; several solids in one file are read as one mesh, and
counted. ``nan`` and ``inf`` are read as what they say, and reported. An STL
has no units: it is read as millimetres, and the checks compare its size
with the spec's.

**3MF.** The model part the package's relationships name as its start part;
its ``unit``; its build item, and the objects and components it places, with
their transforms (a transform that mirrors turns its triangles over, so they
still face outwards; whether one mirrors or flattens is decided exactly).
The model is read as a stream, so a large one needs memory for its numbers
only. Refused:

- more than one build item: two objects where one part is expected;
- an object that isn't a model (a support, a surface, "other");
- a component in another model part (the production extension's ``path``),
  or a required extension that changes the geometry (beam lattices, slices),
  its prefix looked up where it is declared;
- a transform that flattens, a component cycle, components that multiply
  into more than :data:`MOST_TRIANGLES` triangles, place more than
  :data:`MOST_PLACEMENTS` meshes, or take more than :data:`MOST_STEPS`
  objects visited to place them;
- a document type or an entity declaration, refused by the XML parser itself
  whatever the encoding (nothing a 3MF needs; a way to make a reader do
  unbounded work);
- a part that unpacks to more than :data:`MOST_BYTES`, two parts with one
  name, an encrypted, corrupt or unknown-compressed part.

>>> import struct
>>> tri = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0)
>>> read_stl(b"solid but binary".ljust(80, b" ") + struct.pack("<I", 1) + tri).triangles.tolist()
[[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]]
"""

from __future__ import annotations

import array
import hashlib
import io
import posixpath
import re
import struct
import urllib.parse
import xml.parsers.expat
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np
from numpy.typing import NDArray

from .mesh import Mesh, MeshView

__all__ = [
    "MOST_BYTES",
    "MOST_PLACEMENTS",
    "MOST_STEPS",
    "MOST_TRIANGLES",
    "MeshFile",
    "MeshFileError",
    "read_3mf",
    "read_mesh_file",
    "read_stl",
]

#: The most a 3MF part may unpack to: far beyond any part Forge makes.
MOST_BYTES = 2 * 1024**3
#: The most triangles a 3MF's components may multiply into.
MOST_TRIANGLES = 50_000_000
#: The most meshes a 3MF's components may place: a part is a handful.
MOST_PLACEMENTS = 100_000
#: The most objects placing the part's meshes may visit, copies counted: so a
#: long chain of single components under a diamond can't take hours.
MOST_STEPS = 1_000_000

_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_START = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
_RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"
_PRODUCTION = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
#: Extensions that don't change the geometry: colours and materials, and
#: production's identifiers (its paths to other parts are refused one by one).
_HARMLESS = {
    "http://schemas.microsoft.com/3dmanufacturing/material/2015/02",
    _PRODUCTION,
}
_UNITS = {
    "micron": 0.001,
    "millimeter": 1.0,
    "centimeter": 10.0,
    "inch": 25.4,
    "foot": 304.8,
    "meter": 1000.0,
}
#: A 3MF number (ST_Number), after its surrounding white space is dropped.
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
#: A text STL's number: as above, a trailing point allowed ("1."), and nan or inf.
_STL_NUMBER = re.compile(
    r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[+-]?(?:nan|inf|infinity)",
    re.IGNORECASE,
)
#: An id or a vertex number: digits (leading zeros aside, at most eighteen).
_INDEX = re.compile(r"\+?([0-9]+)")
_XML_SPACE = " \t\r\n"
_CHUNK = 1 << 20


class MeshFileError(ValueError):
    """The file can't be read for sure: why."""


@dataclass(frozen=True, eq=False)
class MeshFile:
    """A mesh file's triangles ``(n, 3, 3)`` in millimetres, as the file has them.

    ``unit`` is the 3MF's unit, or "none" for an STL (read as millimetres);
    ``solids`` counts a text STL's solid blocks (1 otherwise); ``digest`` is
    the SHA-256 of the file's bytes.
    """

    triangles: NDArray[np.float64]
    kind: str
    unit: str
    solids: int
    digest: str

    def view(self, deflection: float) -> MeshView:
        """The file as a view (a ``mesh-file`` view, as the capability table knows it), its mesh said to be within ``deflection`` of the true surface."""
        mesh = Mesh.from_triangles(self.triangles)
        return MeshView(mesh, source="mesh-file", deflection=deflection)


def read_mesh_file(data: bytes) -> MeshFile:
    """An STL or a 3MF, told apart by content (a 3MF is a zip package)."""
    if data[:4] == b"PK\x03\x04":
        return read_3mf(data)
    return read_stl(data)


def _number(text: str, where: str) -> float:
    """A 3MF number as written: sign, digits, point and digits, exponent; white space round it."""
    if _NUMBER.fullmatch(text.strip(_XML_SPACE)):
        return float(text)
    raise MeshFileError(f"{where}: {text!r} isn't a number")


def _stl_number(text: str, where: str) -> float:
    if _STL_NUMBER.fullmatch(text):
        return float(text)
    raise MeshFileError(f"{where}: {text!r} isn't a number")


def _index(text: str, where: str, *, positive: bool = False) -> int:
    """An id (``positive``: 1 or more) or a vertex number (0 or more), as 3MF writes them."""
    found = _INDEX.fullmatch(text.strip(_XML_SPACE))
    digits = (found.group(1).lstrip("0") or "0") if found else ""
    if not found or len(digits) > 18 or (positive and digits == "0"):
        raise MeshFileError(f"{where}: {text!r} isn't a whole number Forge can take")
    return int(digits)


# --- STL --------------------------------------------------------------------------


def read_stl(data: bytes) -> MeshFile:
    digest = hashlib.sha256(data).hexdigest()
    if len(data) >= 84:
        (count,) = struct.unpack_from("<I", data, 80)
        if len(data) == 84 + 50 * count:
            if not count:
                raise MeshFileError("the STL has no triangles")
            record = np.dtype(
                [("normal", "<f4", (3,)), ("corners", "<f4", (3, 3)), ("extra", "<u2")]
            )
            facets = np.frombuffer(data, dtype=record, count=count, offset=84)
            return MeshFile(
                facets["corners"].astype(np.float64), "stl", "none", 1, digest
            )
    if data.lstrip(b" \t\r\n")[:5].lower() != b"solid":
        raise MeshFileError(
            "not an STL: its length doesn't match a binary STL's count, and it doesn't begin 'solid'"
        )
    triangles, solids = _read_stl_text(data)
    return MeshFile(triangles, "stl", "none", solids, digest)


def _lines(data: bytes) -> Iterator[tuple[int, list[str]]]:
    """Each line's number and words: ASCII, ended by a line feed, words parted by spaces or tabs."""
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise MeshFileError(
            f"a text STL must be plain ASCII (byte {error.start} isn't)"
        ) from None
    for number, line in enumerate(text.split("\n"), start=1):
        line = line[:-1] if line.endswith("\r") else line
        odd = next(
            (ch for ch in line if (ch < " " and ch != "\t") or ch == "\x7f"), None
        )
        if odd is not None:
            raise MeshFileError(f"text STL, line {number}: control character {odd!r}")
        words = [w for w in re.split(r"[ \t]+", line) if w]
        if words:
            yield number, words


def _read_stl_text(data: bytes) -> tuple[NDArray[np.float64], int]:
    corners: list[float] = []
    solids = 0
    state = "between"  # between, solid, facet, loop, endloop
    in_loop = 0
    for number, words in _lines(data):
        key = words[0].lower()
        where = f"text STL, line {number}"

        def wrong(why: str, where: str = where) -> MeshFileError:
            return MeshFileError(f"{where}: {why}")

        if state == "between":
            if key != "solid":
                raise wrong(f"expected 'solid', found {words[0]!r}")
            solids += 1
            state = "solid"
        elif state == "solid":
            if key == "endsolid":
                state = "between"
            elif key == "facet":
                if len(words) != 5 or words[1].lower() != "normal":
                    raise wrong("a facet line is 'facet normal x y z'")
                for w in words[2:]:
                    _stl_number(w, where)
                state = "facet"
            else:
                raise wrong(f"expected 'facet' or 'endsolid', found {words[0]!r}")
        elif state == "facet":
            if key == "outer" and len(words) == 2 and words[1].lower() == "loop":
                state, in_loop = "loop", 0
            else:
                raise wrong(f"expected 'outer loop', found {' '.join(words)!r}")
        elif state == "loop":
            if key == "vertex":
                if len(words) != 4:
                    raise wrong("a vertex line is 'vertex x y z'")
                corners += [_stl_number(w, where) for w in words[1:]]
                in_loop += 1
            elif key == "endloop":
                if in_loop != 3:
                    raise wrong(f"a facet has {in_loop} vertices, not 3")
                state = "endloop"
            else:
                raise wrong(f"expected 'vertex' or 'endloop', found {words[0]!r}")
        elif state == "endloop":
            if key != "endfacet" or len(words) != 1:
                raise wrong(f"expected 'endfacet', found {' '.join(words)!r}")
            state = "solid"
    if state != "between":
        raise MeshFileError("text STL: the file ends inside a solid")
    if not corners:
        raise MeshFileError("the STL has no triangles")
    return np.array(corners, dtype=np.float64).reshape(-1, 3, 3), solids


# --- 3MF: the package -------------------------------------------------------------


def _chunks(package: zipfile.ZipFile, info: zipfile.ZipInfo) -> Iterator[bytes]:
    """A part's bytes, unpacked a chunk at a time, refused past :data:`MOST_BYTES`."""
    if info.file_size > MOST_BYTES:
        raise MeshFileError(
            f"the 3MF part {info.filename!r} unpacks to {info.file_size} bytes: refused"
        )
    total = 0
    try:
        with package.open(info) as handle:
            while chunk := handle.read(_CHUNK):
                total += len(chunk)
                if total > MOST_BYTES:
                    raise MeshFileError(
                        f"the 3MF part {info.filename!r} unpacks to more than it says"
                    )
                yield chunk
    except MeshFileError:
        raise
    except Exception as error:  # every way a member can fail to unpack is a refusal
        raise MeshFileError(
            f"the 3MF part {info.filename!r} can't be unpacked: {error!r}"
        ) from None


class _RefusedError(Exception):
    """Raised inside the XML parser's handlers; turned into a MeshFileError."""


def _parse(chunks: Iterator[bytes], name: str, handler: _Handler) -> None:
    """Parse a part's XML as a stream, refusing a document type or entities whatever its encoding."""
    parser = xml.parsers.expat.ParserCreate(namespace_separator=" ")
    parser.SetParamEntityParsing(xml.parsers.expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def refuse(*_: object) -> None:
        raise _RefusedError("declares a document type or entities")

    def refuse_external(*_: object) -> int:
        raise _RefusedError("refers to an external entity")

    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.ExternalEntityRefHandler = refuse_external
    parser.StartNamespaceDeclHandler = handler.declare
    parser.EndNamespaceDeclHandler = handler.undeclare
    parser.StartElementHandler = handler.start
    parser.EndElementHandler = handler.end
    try:
        for chunk in chunks:
            parser.Parse(chunk, False)
        parser.Parse(b"", True)
    except _RefusedError as why:
        raise MeshFileError(f"the 3MF part {name!r} {why}") from None
    except xml.parsers.expat.ExpatError as error:
        raise MeshFileError(
            f"the 3MF part {name!r} isn't well-formed XML: {error}"
        ) from None


class _Handler:
    """Namespace prefixes in scope, and what to do at each element."""

    def __init__(self) -> None:
        self.prefixes: dict[str, list[str]] = {}

    def declare(self, prefix: str | None, uri: str) -> None:
        self.prefixes.setdefault(prefix or "", []).append(uri)

    def undeclare(self, prefix: str | None) -> None:
        self.prefixes[prefix or ""].pop()

    def namespace(self, prefix: str) -> str | None:
        stack = self.prefixes.get(prefix)
        return stack[-1] if stack else None

    def start(self, name: str, attributes: dict[str, str]) -> None:
        raise NotImplementedError

    def end(self, name: str) -> None:
        raise NotImplementedError


class _Relationships(_Handler):
    def __init__(self) -> None:
        super().__init__()
        self.starts: list[str] = []

    def start(self, name: str, attributes: dict[str, str]) -> None:
        if (
            name == f"{_RELATIONSHIPS} Relationship"
            and attributes.get("Type") == _START
        ):
            self.starts.append(attributes.get("Target", ""))

    def end(self, name: str) -> None:
        return


def read_3mf(data: bytes) -> MeshFile:
    digest = hashlib.sha256(data).hexdigest()
    try:
        package = zipfile.ZipFile(io.BytesIO(data))
        members = package.infolist()
    except Exception as error:  # every way a package can fail to open is a refusal
        raise MeshFileError(
            f"the 3MF isn't a readable zip package: {error!r}"
        ) from None
    with package:
        # Part names are compared without case (Open Packaging Conventions).
        by_name: dict[str, zipfile.ZipInfo] = {}
        for info in members:
            key = info.filename.lower()
            if key in by_name:
                raise MeshFileError(f"the 3MF has two parts named {info.filename!r}")
            by_name[key] = info

        def part(name: str) -> zipfile.ZipInfo:
            found = by_name.get(name.lower())
            if found is None:
                raise MeshFileError(f"the 3MF has no part {name!r}")
            return found

        relationships = _Relationships()
        rels = part("_rels/.rels")
        _parse(_chunks(package, rels), rels.filename, relationships)
        if len(relationships.starts) != 1 or not relationships.starts[0]:
            raise MeshFileError(
                "the 3MF must name exactly one start part (its 3D model)"
            )
        # The target is a URI, relative to the package's root. Its zip item may
        # be named as written (percent-escapes kept) or unescaped.
        written = relationships.starts[0]
        names = {
            posixpath.normpath("/" + name.lstrip("/")).lstrip("/")
            for name in (written, urllib.parse.unquote(written))
        }
        present = {by_name[n.lower()].filename for n in names if n.lower() in by_name}
        if len(present) != 1:
            raise MeshFileError(
                f"the 3MF's start part {written!r} is missing or ambiguous"
            )
        start = part(present.pop())
        model = _Model()
        _parse(_chunks(package, start), start.filename, model)
    if not model.seen:
        raise MeshFileError(f"the 3MF part {start.filename!r} isn't a 3MF model")
    if len(model.items) != 1:
        raise MeshFileError(
            f"the 3MF builds {len(model.items)} objects: one part is expected"
        )
    ident, transform = model.items[0]
    counts = _count(model.objects, ident)
    count, meshes, steps = counts[ident]
    if count > MOST_TRIANGLES or meshes > MOST_PLACEMENTS or steps > MOST_STEPS:
        raise MeshFileError(
            f"the 3MF's part multiplies into {count} triangles in {meshes} meshes: refused"
        )
    if not count:
        raise MeshFileError("the 3MF's part has no triangles")
    triangles = _place(model.objects, counts, ident, transform)
    return MeshFile(triangles * _UNITS[model.unit], "3mf", model.unit, 1, digest)


# --- 3MF: the model -----------------------------------------------------------------

#: A transform: points are rows, ``p' = p @ m + t``; and whether it mirrors.
_Transform = tuple[NDArray[np.float64], NDArray[np.float64], bool]
_IDENTITY: _Transform = (np.eye(3), np.zeros(3), False)


def _transform(text: str | None, where: str) -> _Transform:
    """A 3MF transform's twelve numbers; whether it flattens or mirrors decided exactly."""
    if text is None:
        return _IDENTITY
    words = [w for w in re.split(f"[{_XML_SPACE}]+", text) if w]
    if len(words) != 12:
        raise MeshFileError(f"{where}: a transform is 12 numbers")
    values = [_number(w, where) for w in words]
    if not all(np.isfinite(values)):
        raise MeshFileError(f"{where}: a transform's numbers must be finite")
    e = [Fraction(v) for v in values[:9]]
    det = (
        e[0] * (e[4] * e[8] - e[5] * e[7])
        - e[1] * (e[3] * e[8] - e[5] * e[6])
        + e[2] * (e[3] * e[7] - e[4] * e[6])
    )
    if det == 0:
        raise MeshFileError(f"{where}: its transform flattens the part")
    m = np.array(values[:9], dtype=np.float64).reshape(3, 3)
    return m, np.array(values[9:], dtype=np.float64), det < 0


@dataclass
class _Object:
    kind: str
    vertices: array.array[float] | None = None
    triangles: array.array[int] | None = None
    components: list[tuple[int, _Transform]] | None = None
    parts: set[str] = field(
        default_factory=set
    )  # a mesh's <vertices> and <triangles>, seen


@dataclass
class _Model(_Handler):
    """The model part, read element by element: objects, their meshes or components, the build."""

    unit: str = "millimeter"
    seen: bool = False
    objects: dict[int, _Object] = field(default_factory=dict)
    items: list[tuple[int, _Transform]] = field(default_factory=list)
    path: list[str] = field(default_factory=list)
    current: _Object | None = None

    def __post_init__(self) -> None:
        _Handler.__init__(self)

    def _here(self) -> str:
        return "/".join(self.path)

    def start(self, name: str, attributes: dict[str, str]) -> None:
        uri, _, local = name.rpartition(" ")
        parent = self.path[-1] if self.path else ""
        self.path.append(local if uri == _CORE else f"{{{uri}}}{local}")
        if uri != _CORE:
            if not self.path[:-1]:
                raise _RefusedError("isn't a 3MF model")
            return  # an extension's element: nothing that changes the geometry
        where = f"<{local}> in {self._here()}"
        expected = {
            "model": "",
            "resources": "model",
            "build": "model",
            "object": "resources",
            "mesh": "object",
            "components": "object",
            "vertices": "mesh",
            "triangles": "mesh",
            "vertex": "vertices",
            "triangle": "triangles",
            "component": "components",
            "item": "build",
        }
        if local in ("basematerials", "base", "metadatagroup") or (
            local == "metadata" and parent in ("model", "metadatagroup")
        ):
            return  # colours, materials and notes: nothing that changes the geometry
        if local not in expected:
            raise _RefusedError(f"has an element 3MF doesn't define: {where}")
        if expected[local] != parent:
            raise _RefusedError(f"has {where}, out of place")
        if local in ("vertices", "triangles"):
            assert self.current is not None
            seen = self.current.parts
            if local in seen:
                raise _RefusedError(f"has a mesh with two <{local}>")
            seen.add(local)
        if local == "model":
            self.seen = True
            self.unit = attributes.get("unit", "millimeter")
            if self.unit not in _UNITS:
                raise _RefusedError(f"has a unit 3MF doesn't define: {self.unit!r}")
            for prefix in attributes.get("requiredextensions", "").split():
                if self.namespace(prefix) not in _HARMLESS:
                    raise _RefusedError(
                        f"requires an extension Forge doesn't read: {prefix!r}"
                    )
        elif local == "object":
            ident = _index(attributes.get("id", ""), where, positive=True)
            if ident in self.objects:
                raise _RefusedError(f"has two objects numbered {ident}")
            self.current = _Object(kind=attributes.get("type", "model"))
            self.objects[ident] = self.current
        elif local == "mesh":
            if (
                self.current is None
                or self.current.components is not None
                or (self.current.vertices is not None)
            ):
                raise _RefusedError(
                    f"has {where}: an object is a mesh or components, one of the two"
                )
            self.current.vertices, self.current.triangles = (
                array.array("d"),
                array.array("q"),
            )
        elif local == "components":
            if (
                self.current is None
                or self.current.vertices is not None
                or (self.current.components is not None)
            ):
                raise _RefusedError(
                    f"has {where}: an object is a mesh or components, one of the two"
                )
            self.current.components = []
        elif local == "vertex":
            assert self.current is not None and self.current.vertices is not None
            self.current.vertices.extend(
                _attribute_number(attributes, axis, where) for axis in ("x", "y", "z")
            )
        elif local == "triangle":
            assert self.current is not None and self.current.triangles is not None
            self.current.triangles.extend(
                _index(attributes.get(k, ""), where) for k in ("v1", "v2", "v3")
            )
        elif local == "component":
            assert self.current is not None and self.current.components is not None
            if f"{_PRODUCTION} path" in attributes:
                raise _RefusedError("has a component in another model part: refused")
            self.current.components.append(
                (
                    _index(attributes.get("objectid", ""), where, positive=True),
                    _transform(attributes.get("transform"), where),
                )
            )
        elif local == "item":
            if f"{_PRODUCTION} path" in attributes:
                raise _RefusedError("has a build item in another model part: refused")
            self.items.append(
                (
                    _index(attributes.get("objectid", ""), where, positive=True),
                    _transform(attributes.get("transform"), where),
                )
            )

    def end(self, name: str) -> None:
        local = self.path.pop()
        if local == "object":
            found = self.current
            if found is None or (found.vertices is None and found.components is None):
                raise _RefusedError("has an object with neither a mesh nor components")
            self.current = None


def _attribute_number(attributes: dict[str, str], axis: str, where: str) -> float:
    try:
        return _number(attributes[axis], where)
    except KeyError:
        raise MeshFileError(f"{where}: a vertex needs x, y and z") from None


def _count(objects: dict[int, _Object], ident: int) -> dict[int, tuple[int, int, int]]:
    """For each object under ``ident``: how many triangles it makes, how many meshes it
    places, and how many objects placing them visits, copies counted (objects
    that make no triangles aren't visited).

    Each object is worked out once, so components that multiply (a diamond of
    references, twenty deep) are counted, not walked; and without recursion,
    so a chain of thousands is no deeper than one.
    """
    known: dict[int, tuple[int, int, int]] = {}
    visiting: set[int] = set()
    stack: list[tuple[int, str, bool]] = [(ident, "the build item", False)]
    while stack:
        here, where, children_done = stack.pop()
        if here in known and not children_done:
            continue
        if here not in objects:
            raise MeshFileError(f"{where} names object {here}, which isn't there")
        found = objects[here]
        if found.kind != "model":
            raise MeshFileError(
                f"object {here} is a {found.kind!r}, not a model: refused"
            )
        if found.triangles is not None:
            assert found.vertices is not None
            corners, vertices = len(found.triangles), len(found.vertices) // 3
            if corners and (
                min(found.triangles) < 0 or max(found.triangles) >= vertices
            ):
                raise MeshFileError(
                    f"object {here}: a triangle names a vertex that isn't there"
                )
            known[here] = (corners // 3, 1, 1)
            continue
        children = [child for child, _ in found.components or []]
        if not children_done:
            if here in visiting:
                raise MeshFileError(
                    f"object {here}: its components go round in a circle"
                )
            visiting.add(here)
            stack.append((here, where, True))
            for child in children:
                if child in visiting:
                    raise MeshFileError(
                        f"object {child}: its components go round in a circle"
                    )
                if child not in known:
                    stack.append((child, f"object {here}", False))
            continue
        visiting.discard(here)
        triangles = sum(known[child][0] for child in children)
        meshes = sum(known[child][1] for child in children)
        steps = 1 + sum(known[child][2] for child in children if known[child][0])
        known[here] = (triangles, meshes, steps)
    return known


def _place(objects: dict[int, _Object], counts: dict[int, tuple[int, int, int]], ident: int,
           transform: _Transform) -> NDArray[np.float64]:  # fmt: skip
    """The triangles of object ``ident`` (already counted), placed by its transform.

    Objects that make no triangles are passed over, so the walk visits the
    objects :func:`_count` counted, no more.
    """
    pieces: list[NDArray[np.float64]] = []
    stack: list[tuple[int, _Transform]] = [(ident, transform)]
    while stack:
        here, (m, t, mirrored) = stack.pop()
        found = objects[here]
        if found.triangles is not None:
            assert found.vertices is not None
            points = np.frombuffer(found.vertices, dtype=np.float64).reshape(-1, 3)
            corners = np.frombuffer(found.triangles, dtype=np.int64).reshape(-1, 3)
            with np.errstate(
                invalid="ignore", over="ignore"
            ):  # inf and nan are kept, and reported
                placed = points[corners] @ m + t
            if mirrored:
                placed = placed[
                    :, [0, 2, 1]
                ]  # a mirror turns triangles over; turn them back
            pieces.append(np.asarray(placed, dtype=np.float64))
            continue
        for child, (cm, ct, flip) in reversed(found.components or []):
            if counts[child][0]:
                stack.append((child, (cm @ m, ct @ m + t, mirrored != flip)))
    return np.concatenate(pieces) if pieces else np.zeros((0, 3, 3))
