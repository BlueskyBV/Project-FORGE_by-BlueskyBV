"""Forge's eyes: the built part drawn the way an engineer looks at it in CAD.

The model that designs a part never sees it. It writes coordinates for a
45-feature calf shell and is told, afterwards, in numbers, what came out --
and a hinge tab drawn 15 mm short, obvious at a glance, took three rounds of
numbers to find. So the part is drawn: one sheet of six views, every one
with millimetre ticks on its edges and its axes named, sent to the model as
an image beside the numbers, and written into the run for the person
watching.

    +-------------+-------------+-------------+
    | 3D view     | from -Y     | from +X     |
    |             | X right,Z up| Y right,Z up|
    +-------------+-------------+-------------+
    | from +Z     | section     | section     |
    | X right,Y up| at Y = mid  | at X = mid  |
    +-------------+-------------+-------------+

The three outside views are the finished mesh, shaded and outlined; the two
sections are cut straight through the solid's own field, so a hollow part
shows its walls, its floor and whatever is wrongly inside it. Marks -- a hole
that cut nothing, a hole in the wrong place, where the brief wanted one --
are drawn on every view where they fall, in red, with their names.

Nothing here needs a graphics card, a display, or any package Forge does not
already use: numpy draws, zlib packs the PNG, and the lettering is a 5x7
bitmap font defined below. Deterministic: the same part gives the same bytes.
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

Array = np.ndarray

# ----------------------------------------------------------------------
# Colours
# ----------------------------------------------------------------------
_PAPER = np.array([255, 255, 255], dtype=np.uint8)
_GRID = np.array([226, 230, 236], dtype=np.uint8)
_INK = np.array([40, 44, 52], dtype=np.uint8)
_FAINT_INK = np.array([110, 118, 130], dtype=np.uint8)
_PART = np.array([150, 176, 205], dtype=float)
_EDGE = np.array([30, 38, 52], dtype=np.uint8)
_CUT = np.array([222, 138, 52], dtype=np.uint8)
_CUT_EDGE = np.array([120, 60, 10], dtype=np.uint8)
_RED = np.array([214, 32, 28], dtype=np.uint8)
_GREEN = np.array([20, 150, 60], dtype=np.uint8)

# ----------------------------------------------------------------------
# A 5x7 bitmap font: each glyph is seven rows of five bits, high bit left.
# ----------------------------------------------------------------------
_FONT: dict[str, tuple[int, ...]] = {
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F),
    "3": (0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    "D": (0x1C, 0x12, 0x11, 0x11, 0x11, 0x12, 0x1C),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "J": (0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x11, 0x19, 0x15, 0x13, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "Q": (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A),
    "X": (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    "Y": (0x11, 0x11, 0x11, 0x0A, 0x04, 0x04, 0x04),
    "Z": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    "+": (0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    ",": (0x00, 0x00, 0x00, 0x00, 0x0C, 0x04, 0x08),
    ":": (0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00),
    "=": (0x00, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x00),
    "(": (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),
    ")": (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    "/": (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x00),
    "_": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F),
    "<": (0x02, 0x04, 0x08, 0x10, 0x08, 0x04, 0x02),
    ">": (0x08, 0x04, 0x02, 0x01, 0x02, 0x04, 0x08),
    "*": (0x00, 0x04, 0x15, 0x0E, 0x15, 0x04, 0x00),
    "[": (0x0E, 0x08, 0x08, 0x08, 0x08, 0x08, 0x0E),
    "]": (0x0E, 0x02, 0x02, 0x02, 0x02, 0x02, 0x0E),
    "'": (0x04, 0x04, 0x08, 0x00, 0x00, 0x00, 0x00),
    "%": (0x18, 0x19, 0x02, 0x04, 0x08, 0x13, 0x03),
    "#": (0x0A, 0x0A, 0x1F, 0x0A, 0x1F, 0x0A, 0x0A),
    "?": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04),
    "!": (0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04),
    " ": (0x00,) * 7,
}


def _text_width(text: str, scale: int) -> int:
    return len(text) * 6 * scale


def _draw_text(image: Array, x: int, y: int, text: str, colour: Array,
               scale: int = 2, background: Array | None = None) -> None:
    """Write `text` with its top-left corner at (x, y), clipped to the image."""
    height, width = image.shape[:2]
    if background is not None:
        x0, y0 = max(0, x - scale), max(0, y - scale)
        x1 = min(width, x + _text_width(text, scale) + scale)
        y1 = min(height, y + 8 * scale)
        if x1 > x0 and y1 > y0:
            image[y0:y1, x0:x1] = background
    for index, character in enumerate(text.upper()):
        rows = _FONT.get(character, _FONT["?"])
        left = x + index * 6 * scale
        for row, bits in enumerate(rows):
            for column in range(5):
                if bits & (0x10 >> column):
                    top = y + row * scale
                    col = left + column * scale
                    if 0 <= top < height and 0 <= col < width:
                        image[top:min(top + scale, height),
                              col:min(col + scale, width)] = colour


def _line(image: Array, x0: float, y0: float, x1: float, y1: float,
          colour: Array, thickness: int = 1) -> None:
    height, width = image.shape[:2]
    steps = int(max(abs(x1 - x0), abs(y1 - y0), 1.0)) + 1
    xs = np.round(np.linspace(x0, x1, steps)).astype(int)
    ys = np.round(np.linspace(y0, y1, steps)).astype(int)
    half = thickness // 2
    for dx in range(-half, thickness - half):
        for dy in range(-half, thickness - half):
            xx, yy = xs + dx, ys + dy
            ok = (xx >= 0) & (xx < width) & (yy >= 0) & (yy < height)
            image[yy[ok], xx[ok]] = colour


def _circle(image: Array, cx: float, cy: float, radius: float, colour: Array,
            thickness: int = 2) -> None:
    angles = np.linspace(0.0, 2.0 * math.pi, max(24, int(radius * 6)))
    xs, ys = cx + radius * np.cos(angles), cy + radius * np.sin(angles)
    for i in range(len(xs) - 1):
        _line(image, xs[i], ys[i], xs[i + 1], ys[i + 1], colour, thickness)


# ----------------------------------------------------------------------
# PNG
# ----------------------------------------------------------------------
def encode_png(image: Array) -> bytes:
    """An (H, W, 3) uint8 image as PNG bytes."""
    image = np.ascontiguousarray(image, dtype=np.uint8)
    height, width = image.shape[:2]
    raw = np.zeros((height, width * 3 + 1), dtype=np.uint8)
    raw[:, 1:] = image.reshape(height, width * 3)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw.tobytes(), 6))
            + chunk(b"IEND", b""))


# ----------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Mark:
    """A point to show on every view: a hole that cut nothing, where the
    brief wanted one. `colour` is "red" or "green"."""

    label: str
    point: tuple[float, float, float]
    colour: str = "red"


@dataclass(frozen=True, slots=True)
class _View:
    title: str
    right: tuple[float, float, float]
    up: tuple[float, float, float]
    #: The axis letters of `right` and `up` for an outside view along an
    #: axis; empty for the 3D view, which has no millimetre scale.
    right_name: str = ""
    up_name: str = ""


_ISO = _View(
    "3D VIEW",
    right=tuple((np.array([1.0, 1.0, 0.0]) / math.sqrt(2)).tolist()),
    up=tuple((np.array([-1.0, 1.0, 2.0]) / math.sqrt(6)).tolist()),
)
_FROM_MINUS_Y = _View("FROM -Y", (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), "X", "Z")
_FROM_PLUS_X = _View("FROM +X", (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), "Y", "Z")
_FROM_PLUS_Z = _View("FROM +Z", (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), "X", "Y")


def _nice_step(span: float, pixels: int) -> float:
    """A round tick spacing that puts a labelled tick every ~70 pixels."""
    target = span * 70.0 / max(pixels, 1)
    for step in (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 25,
                 50, 100, 200, 250, 500, 1000, 2000):
        if step >= target:
            return float(step)
    return float(10 ** math.ceil(math.log10(max(target, 1e-9))))


class _Canvas:
    """One tile: an image with a millimetre frame mapped onto it."""

    def __init__(self, size: int, lo_u: float, hi_u: float, lo_v: float,
                 hi_v: float, *, margin: int = 46, header: int = 30) -> None:
        self.size = size
        self.image = np.empty((size, size, 3), dtype=np.uint8)
        self.image[:] = _PAPER
        self.margin, self.header = margin, header
        span_u, span_v = max(hi_u - lo_u, 1e-6), max(hi_v - lo_v, 1e-6)
        room_u = size - 2 * margin
        room_v = size - margin - header - 10
        self.scale = min(room_u / span_u, room_v / span_v)
        mid_u, mid_v = (lo_u + hi_u) / 2.0, (lo_v + hi_v) / 2.0
        self.cx = margin + room_u / 2.0 - mid_u * self.scale
        self.cy = header + 10 + room_v / 2.0 + mid_v * self.scale

    def px(self, u: Array | float, v: Array | float) -> tuple[Any, Any]:
        return (np.asarray(u) * self.scale + self.cx,
                self.cy - np.asarray(v) * self.scale)

    def mm(self, x: Array, y: Array) -> tuple[Array, Array]:
        return (x - self.cx) / self.scale, (self.cy - y) / self.scale

    def grid_and_ticks(self, right: str, up: str) -> None:
        """Faint millimetre grid on the paper, labelled ticks on two edges."""
        size, image = self.size, self.image
        u_lo, v_hi = self.mm(np.array(0.0), np.array(float(self.header)))
        u_hi, v_lo = self.mm(np.array(float(size)), np.array(float(size)))
        step = _nice_step(float(u_hi - u_lo), size)
        for u in np.arange(math.ceil(u_lo / step) * step, u_hi, step):
            x, _ = self.px(u, 0.0)
            xi = int(round(float(x)))
            if 0 <= xi < size:
                column = image[self.header:, xi]
                paper = np.all(column == _PAPER, axis=1)
                column[paper] = _GRID
                label = f"{round(float(u), 6) + 0.0:g}"
                left = xi - _text_width(label, 1) // 2
                if left >= 0 and left + _text_width(label, 1) <= size - 40:
                    _draw_text(image, left, size - 12, label, _FAINT_INK,
                               scale=1)
        for v in np.arange(math.ceil(v_lo / step) * step, v_hi, step):
            _, y = self.px(0.0, v)
            yi = int(round(float(y)))
            if self.header <= yi < size - 14:
                row = image[yi, :]
                paper = np.all(row == _PAPER, axis=1)
                row[paper] = _GRID
                _draw_text(image, 2, yi - 3, f"{round(float(v), 6) + 0.0:g}",
                           _FAINT_INK, scale=1)
        # The axis names, on paper of their own so no tick runs through them.
        _draw_text(image, size - 34, size - 28, right + ">", _INK, scale=2,
                   background=_PAPER)
        _draw_text(image, 30, self.header + 6, up, _INK, scale=2,
                   background=_PAPER)
        _line(image, 50, self.header + 8, 50, self.header + 24, _INK, 2)
        _line(image, 46, self.header + 12, 50, self.header + 6, _INK, 2)
        _line(image, 54, self.header + 12, 50, self.header + 6, _INK, 2)

    def title(self, text: str) -> None:
        self.image[:self.header] = np.array([240, 243, 247], dtype=np.uint8)
        _draw_text(self.image, 8, 8, text[: (self.size - 16) // 12], _INK,
                   scale=2)


def _shade_mesh(canvas: _Canvas, vertices: Array, faces: Array,
                right: Array, up: Array) -> None:
    """Draw the mesh seen along -(right x up): z-buffered, Lambert-shaded,
    outlined where the depth jumps."""
    toward = np.cross(right, up)  # points at the viewer
    u = vertices @ right
    v = vertices @ up
    depth = vertices @ toward  # larger is nearer
    xs, ys = canvas.px(u, v)
    tri_x, tri_y, tri_d = xs[faces], ys[faces], depth[faces]

    a = vertices[faces[:, 0]]
    normals = np.cross(vertices[faces[:, 1]] - a, vertices[faces[:, 2]] - a)
    length = np.linalg.norm(normals, axis=1)
    length[length < 1e-15] = 1.0
    normals = normals / length[:, None]
    light_a = np.array(toward) * 0.8 + np.array(up) * 0.45 + np.array(right) * 0.2
    light_a /= np.linalg.norm(light_a)
    light_b = -np.array(right) * 0.6 + np.array(toward) * 0.4
    light_b /= np.linalg.norm(light_b)
    shade = (0.30 + 0.55 * np.abs(normals @ light_a)
             + 0.20 * np.abs(normals @ light_b))
    colour = np.clip(_PART[None, :] * shade[:, None], 0, 255)

    # Each triangle sampled finely enough to cover its pixels: barycentric
    # grids of a few densities, chosen by the triangle's size on screen.
    extent = np.maximum(tri_x.max(1) - tri_x.min(1), tri_y.max(1) - tri_y.min(1))
    size = canvas.size
    best = np.full(size * size, -np.inf)
    owner = np.full(size * size, -1, dtype=np.int64)
    levels = np.clip(np.ceil(extent * 1.5), 1, 64).astype(int)
    # Faces seen exactly edge-on cover no pixels of their own -- the faces
    # either side of them do -- and sampling a sliver as long as the part
    # cost a rod seen end-on five seconds.
    levels[np.abs(normals @ np.asarray(toward, dtype=float)) < 0.02] = 0
    # A triangle bigger on screen than sampling covers is filled pixel by
    # pixel instead: a small part drawn large, or one big flat face, left
    # stripes of paper between the samples.
    big = np.nonzero((extent * 1.5 > 64) & (levels > 0))[0]
    levels[big] = 0
    for t in big:
        xs_, ys_ = tri_x[t], tri_y[t]
        x0 = max(int(np.floor(xs_.min())), 0)
        x1 = min(int(np.ceil(xs_.max())), size - 1)
        y0 = max(int(np.floor(ys_.min())), canvas.header)
        y1 = min(int(np.ceil(ys_.max())), size - 1)
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1, dtype=float),
                             np.arange(y0, y1 + 1, dtype=float))
        denominator = ((ys_[1] - ys_[2]) * (xs_[0] - xs_[2])
                       + (xs_[2] - xs_[1]) * (ys_[0] - ys_[2]))
        if abs(denominator) < 1e-12:
            continue
        w0 = ((ys_[1] - ys_[2]) * (gx - xs_[2])
              + (xs_[2] - xs_[1]) * (gy - ys_[2])) / denominator
        w1 = ((ys_[2] - ys_[0]) * (gx - xs_[2])
              + (xs_[0] - xs_[2]) * (gy - ys_[2])) / denominator
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        depth = (w0 * tri_d[t, 0] + w1 * tri_d[t, 1] + w2 * tri_d[t, 2])[inside]
        index = (gy[inside].astype(np.int64) * size
                 + gx[inside].astype(np.int64))
        nearer = depth > best[index]
        best[index[nearer]] = depth[nearer]
        owner[index[nearer]] = t
    for level in np.unique(levels):
        if level == 0:
            continue
        chosen = np.nonzero(levels == level)[0]
        i, j = np.meshgrid(np.arange(level + 1), np.arange(level + 1),
                           indexing="ij")
        keep = (i + j) <= level
        wa = (i[keep] / level)[None, :]
        wb = (j[keep] / level)[None, :]
        wc = 1.0 - wa - wb
        for start in range(0, chosen.size, max(1, 400_000 // wa.size)):
            part = chosen[start:start + max(1, 400_000 // wa.size)]
            px = (tri_x[part, 0, None] * wa + tri_x[part, 1, None] * wb
                  + tri_x[part, 2, None] * wc)
            py = (tri_y[part, 0, None] * wa + tri_y[part, 1, None] * wb
                  + tri_y[part, 2, None] * wc)
            pd = (tri_d[part, 0, None] * wa + tri_d[part, 1, None] * wb
                  + tri_d[part, 2, None] * wc)
            pxi = np.round(px).astype(np.int64).ravel()
            pyi = np.round(py).astype(np.int64).ravel()
            pdf = pd.ravel()
            who = np.repeat(part, wa.size)
            ok = ((pxi >= 0) & (pxi < size) & (pyi >= canvas.header)
                  & (pyi < size))
            index = pyi[ok] * size + pxi[ok]
            pdf, who = pdf[ok], who[ok]
            order = np.lexsort((-pdf, index))
            index, pdf, who = index[order], pdf[order], who[order]
            first = np.ones(index.size, dtype=bool)
            first[1:] = index[1:] != index[:-1]
            index, pdf, who = index[first], pdf[first], who[first]
            nearer = pdf > best[index]
            best[index[nearer]] = pdf[nearer]
            owner[index[nearer]] = who[nearer]
    drawn = owner >= 0
    flat = canvas.image.reshape(-1, 3)
    flat[drawn] = colour[owner[drawn]].astype(np.uint8)
    # Outline: where the nearest surface jumps in depth, or the part ends.
    grid = best.reshape(size, size)
    covered = drawn.reshape(size, size)
    jump = max(1.5 / canvas.scale, 0.0) * 4.0 + 0.8
    edge = np.zeros((size, size), dtype=bool)
    for dy, dx in ((0, 1), (1, 0)):
        a_ = grid[: size - dy, : size - dx]
        b_ = grid[dy:, dx:]
        ca, cb = covered[: size - dy, : size - dx], covered[dy:, dx:]
        with np.errstate(invalid="ignore"):
            apart = np.abs(a_ - b_) > jump  # inf - inf where neither covered
        boundary = (ca != cb) | (ca & cb & apart)
        edge[: size - dy, : size - dx] |= boundary & ca
        edge[dy:, dx:] |= boundary & cb
    canvas.image[edge] = _EDGE


def _section(canvas: _Canvas, solid: Any, axis: int, at: float,
             right: int, up: int) -> None:
    """The solid cut by the plane `axis` = `at`, material in orange."""
    size = canvas.size
    ys, xs = np.mgrid[canvas.header:size, 0:size]
    u, v = canvas.mm(xs.astype(float) + 0.5, ys.astype(float) + 0.5)
    points = np.zeros((u.size, 3))
    points[:, right] = u.ravel()
    points[:, up] = v.ravel()
    points[:, axis] = at
    values = np.asarray(solid(points), dtype=float).reshape(u.shape)
    inside = values < 0.0
    region = canvas.image[canvas.header:]
    region[inside] = _CUT
    # Hatching every 8 px on the cut, as a drawing would.
    hatch = ((xs + ys) % 8 == 0) & inside
    region[hatch] = (_CUT.astype(int) * 0.8).astype(np.uint8)
    edge = np.zeros_like(inside)
    edge[:, 1:] |= inside[:, 1:] != inside[:, :-1]
    edge[1:, :] |= inside[1:, :] != inside[:-1, :]
    region[edge] = _CUT_EDGE


def _marks(canvas: _Canvas, marks: Sequence[Mark], right: Array,
           up: Array) -> None:
    placed: list[tuple[int, int]] = []
    for mark in marks:
        point = np.asarray(mark.point, dtype=float)
        x, y = canvas.px(float(point @ right), float(point @ up))
        if not (0 <= x < canvas.size and canvas.header <= y < canvas.size):
            continue
        colour = _GREEN if mark.colour == "green" else _RED
        _circle(canvas.image, float(x), float(y), 7.0, colour, 2)
        _line(canvas.image, x - 11, y, x - 5, y, colour, 2)
        _line(canvas.image, x + 5, y, x + 11, y, colour, 2)
        label = mark.label[:16]
        lx, ly = int(x) + 12, int(y) - 18
        # Step labels that would land on one already written.
        while any(abs(lx - px_) < 60 and abs(ly - py_) < 12
                  for px_, py_ in placed):
            ly += 13
        placed.append((lx, ly))
        _draw_text(canvas.image, lx, ly, label, colour, scale=1,
                   background=_PAPER)


def render_sheet(
    solid: Any,
    mesh: Any,
    *,
    marks: Iterable[Mark] = (),
    tile: int = 420,
    sections: Sequence[tuple[str, float]] | None = None,
) -> bytes:
    """Six views of a part as one PNG: a 3D view, the three views along the
    axes, and two sections through the middle (or at `sections`, each an
    axis letter and a coordinate). `mesh` is the finished surface, with
    `vertices` and `faces`; `solid` the field the sections are cut from."""
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    marks = list(marks)
    lo = vertices.min(axis=0)
    hi = vertices.max(axis=0)
    middle = (lo + hi) / 2.0
    tiles: list[Array] = []

    for view in (_ISO, _FROM_MINUS_Y, _FROM_PLUS_X, _FROM_PLUS_Z):
        right, up = np.asarray(view.right), np.asarray(view.up)
        us, vs = vertices @ right, vertices @ up
        # A margin of this view's own size: a rod seen end on is a small
        # square, not a speck in a frame sized for its length.
        here = 0.05 * max(float(np.ptp(us)), float(np.ptp(vs)), 1e-3)
        canvas = _Canvas(tile, float(us.min()) - here, float(us.max()) + here,
                         float(vs.min()) - here, float(vs.max()) + here)
        canvas.title(view.title + (f"  {view.right_name} RIGHT, {view.up_name} UP"
                                   if view.right_name else ""))
        if view.right_name:
            # Ticks first, under the part: the grid is drawn on paper only.
            _shade_mesh(canvas, vertices, faces, right, up)
            canvas.grid_and_ticks(view.right_name, view.up_name)
        else:
            _shade_mesh(canvas, vertices, faces, right, up)
            _axes_triad(canvas, right, up)
        _marks(canvas, marks, right, up)
        tiles.append(canvas.image)

    cuts = list(sections or [("y", float(middle[1])), ("x", float(middle[0]))])
    for letter, at in cuts[:2]:
        axis = "xyz".index(letter)
        others = [i for i in range(3) if i != axis]
        # Z up whenever Z is in the plane; otherwise Y up.
        up_axis = 2 if 2 in others else others[1]
        right_axis = [i for i in others if i != up_axis][0]
        here = 0.05 * max(float(hi[right_axis] - lo[right_axis]),
                          float(hi[up_axis] - lo[up_axis]), 1e-3)
        canvas = _Canvas(tile, float(lo[right_axis]) - here,
                         float(hi[right_axis]) + here,
                         float(lo[up_axis]) - here, float(hi[up_axis]) + here)
        shown = round(float(at), 3) + 0.0
        canvas.title(f"SECTION AT {letter.upper()}={shown:g}")
        _section(canvas, solid, axis, at, right_axis, up_axis)
        canvas.grid_and_ticks("XYZ"[right_axis], "XYZ"[up_axis])
        unit = np.eye(3)
        near = [m for m in marks
                if abs(float(m.point[axis]) - at) <= max(6.0, 0.05 * float(
                    hi[axis] - lo[axis]))]
        _marks(canvas, near, unit[right_axis], unit[up_axis])
        tiles.append(canvas.image)

    while len(tiles) < 6:
        blank = np.empty((tile, tile, 3), dtype=np.uint8)
        blank[:] = _PAPER
        tiles.append(blank)
    rows = [np.concatenate(tiles[i:i + 3], axis=1) for i in (0, 3)]
    sheet = np.concatenate(rows, axis=0)
    # Hairlines between the tiles.
    sheet[tile - 1:tile + 1, :] = _GRID
    sheet[:, tile - 1:tile + 1] = _GRID
    sheet[:, 2 * tile - 1:2 * tile + 1] = _GRID
    return encode_png(sheet)


def _axes_triad(canvas: _Canvas, right: Array, up: Array) -> None:
    """X, Y and Z drawn from one corner of the 3D view, as CAD shows them."""
    ox, oy = 34.0, canvas.size - 34.0
    for index, letter in enumerate("XYZ"):
        direction = np.eye(3)[index]
        dx, dy = float(direction @ right) * 24, -float(direction @ up) * 24
        _line(canvas.image, ox, oy, ox + dx, oy + dy, _INK, 2)
        _draw_text(canvas.image, int(ox + dx * 1.35) - 5,
                   int(oy + dy * 1.35) - 7, letter, _INK, scale=2)


# ----------------------------------------------------------------------
# What to mark
# ----------------------------------------------------------------------
def marks_from_report(report: Any) -> list[Mark]:
    """The places a verification report says are wrong, as marks: a feature
    that left nothing on the part, a hole with no wall round it, a hole the
    brief puts at a point where there is none (in green, where it should
    be)."""
    marks: list[Mark] = []
    part = getattr(report, "part", None)
    if part is None:
        return marks
    envelope = part.solid.envelope
    middle = [(float(a) + float(b)) / 2.0 for a, b in zip(envelope.lo,
                                                          envelope.hi)]
    seen: set[str] = set()

    def place_of(feature: str) -> tuple[float, float, float] | None:
        for surface in ("bore", "body", "axis"):
            entity = part.geometry_map.get(f"{feature}.{surface}")
            if entity is not None:
                try:
                    return tuple(float(c) for c in entity.frame.origin)  # type: ignore[return-value]
                except Exception:  # noqa: BLE001
                    continue
        return None

    for result in getattr(report, "gate_results", ()):
        if result.status.value not in ("FAIL", "BLOCKED"):
            continue
        detail = dict(result.evidence.detail or {})
        gate = result.gate.identifier
        if gate == "GEOM_FEATURES_CONTRIBUTE":
            for entry in detail.get("absent", []) or []:
                name = str(entry.get("feature", ""))
                where = place_of(name)
                if where is not None and name not in seen:
                    seen.add(name)
                    marks.append(Mark(name + " NONE", where))
        elif gate == "GEOM_HOLES_ARE_HOLES":
            for entry in detail.get("notched", []) or []:
                name = str(entry.get("feature", ""))
                centre = entry.get("centre")
                if centre and name not in seen:
                    seen.add(name)
                    marks.append(Mark(name + " NOTCH",
                                      tuple(float(c) for c in centre)))  # type: ignore[arg-type]
        elif gate == "GEOM_THROUGH_HOLES_OPEN":
            # Where material stands on a through hole's centre line.
            for entry in detail.get("blocked", []) or []:
                name = str(entry.get("feature", ""))
                start = entry.get("from")
                if start and name not in seen:
                    seen.add(name)
                    marks.append(Mark(name + " BLOCKED",
                                      tuple(float(c) for c in start)))  # type: ignore[arg-type]
        elif str(detail.get("measurement", "")).startswith("hole_at:"):
            places = str(detail["measurement"]).split(":")[-1].split(",")
            try:
                point = tuple(middle[i] if w == "*" else float(w)
                              for i, w in enumerate(places))
            except ValueError:
                continue
            marks.append(Mark("WANT HOLE", point, "green"))  # type: ignore[arg-type]
    return marks[:24]


def render_report(report: Any, *, tile: int = 420) -> bytes | None:
    """The sheet for a verification report's part, marked with what failed,
    or None when the report has no surface to draw."""
    mesh = getattr(report, "mesh", None)
    part = getattr(report, "part", None)
    if mesh is None or part is None:
        return None
    try:
        return render_sheet(part.solid, mesh, marks=marks_from_report(report),
                            tile=tile)
    except Exception:  # noqa: BLE001 - a drawing that fails is no drawing;
        return None    # the numbers still go to the model


__all__ = ["Mark", "encode_png", "marks_from_report", "render_report",
           "render_sheet"]
