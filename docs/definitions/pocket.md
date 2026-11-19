# pocket

Status: **draft, for your approval.**

A recess: a rectangular, round or hexagonal cut, or one of any outline, with
a flat floor.

## The shape

Its outline on the face is centred where `place` puts it:

- a rectangle, `length` along the face's first axis and `width` along its
  second, its four corners rounded to `corner_radius` (seen from above the
  face) when it has one;
- or a circle of `diameter`;
- or (schema 1.9) a regular hexagon `across_flats` between each two
  opposite sides (a nut trap: the nut's spanner size), two of its corners on
  the face's first axis, `across_flats / √3` from its centre, its other
  four at 60° steps round it (two of its sides run along the face's first
  axis, `across_flats / 2` from its centre either way along its second);
- or (schema 1.9) its own `profile`: a closed outline of lines and arcs, as
  an extrusion's is ([extrusion.md](extrusion.md)), its two coordinates
  along the face's axes from the point `place` puts it at (its point
  `(0, 0)`), which may lie off it (a D-shaped hole for a shaft's flat, a
  window of any outline).

The outline goes in from the face, at right angles to it, to its depth, and
takes away every point of the part inside it. A blind pocket's floor is flat
and parallel to the face. A pocket is cut into flat faces only, for now.

## Fields

### `on`

The face it is cut into ([frame.md](frame.md)).

### `place`

Where on the face ([place.md](place.md)).

### `shape`

- `rectangle`: a rectangle, `length` by `width`.
- `circle`: a circle of `diameter`.
- `hexagon`: a regular hexagon, `across_flats` (schema 1.9).
- `profile`: its own outline, `profile` (schema 1.9).

### `length`

A rectangular pocket's size along the face's first axis.

### `width`

A rectangular pocket's size along the face's second axis.

### `diameter`

A round pocket's diameter.

### `across_flats`

A hexagonal pocket's size between two opposite sides (its flats), the same
across each pair. Placed as any outline is ([place.md](place.md)): by its
centre, or by its edge, its farthest point along that axis (along the
face's first axis, a corner; along its second, a flat); turned in the face
by `place.turn` about its centre, as a rectangle is. A ring of them, a row
or a grid, as of any pocket.

### `profile`

A pocket's own outline (schema 1.9), written as an extrusion's is. Placed
as an extrusion standing on a face is ([place.md](place.md)): its point
`(0, 0)` where `place` puts it, centred by that point, measured to its edge
by the box round its outline; turned in the face by `place.turn` about that
point. Its edges are not rounded or bevelled yet.

### `corner_radius`

A rectangular pocket's corners, rounded to this radius seen from above the
face: its four sides that run into the face meet in quarter-circles. At most
half its length and half its width. None: square corners.

### `depth`

How deep it goes, from the face: a size, or `through` ([sizes.md](sizes.md)).
Schema 1.7: also `through_all` or `up_to` a face, with an offset
([sizes.md](sizes.md)): a pocket up to a face has its floor in that face's
plane, less the offset; schema 1.8, `through_next`.

### `count`

How many pockets there are in the whole part ([place.md](place.md)).

## Faces

- `bottom`: its flat floor, facing out of the pocket the way the face it is
  cut into faces. A pocket that goes through, or as deep as the material, has
  none; nor, for now, does one that covers a ring's central opening, whose
  floor has the bore through it.

## Edges

- `top`: the rim of its mouth, where it meets the face.
- `bottom`: the edge round its floor, an inside edge.

## Checked as

Exact. A hexagon's size across its flats is measured between each pair of
opposite sides, its place along the face's second axis from the middle of
its two sides there, and along its first from the middle of its two corners
there, each where its two sides meet. A pocket of its own outline: its
depth from the face round its mouth to its floor, or right through, open
round a point well within it; its outline, and where it is, held by face
accounting, as an extrusion's outline is.
