# slot

Status: **draft, for your approval.**

An elongated cut, with round or square ends.

## The shape

Its outline on the face is centred where `place` puts it: `length` long
along `along`, `width` wide across it.

- With round ends: a stadium, two half-circles of diameter `width` joined by
  straight sides; the ends' outermost points are `length` apart. A slot as
  long as it is wide is a circle.
- With square ends: a rectangle `length` by `width`.

The outline goes in from the face, at right angles to it, to its depth, with
a flat bottom, and takes away every point of the part inside it. A slot is
cut into flat faces only, for now.

## Fields

### `on`

The face it is cut into ([frame.md](frame.md)).

### `place`

Where on the face ([place.md](place.md)).

### `width`

Its width across, from one long side to the other.

### `length`

Its overall length, from end to end, the round ends included. It can't be
less than the width.

### `along`

The frame axis the slot runs along; it must be one of the face's two axes.

- `x`: along X.
- `y`: along Y.
- `z`: along Z.

### `ends`

- `round`: each end a half-circle of diameter `width`.
- `square`: square ends.

### `depth`

How deep it goes, from the face: a size, or `through` ([sizes.md](sizes.md)).

### `count`

How many slots there are in the whole part ([place.md](place.md)).

## Faces

None: nothing stands on or is cut into a slot.

## Edges

- `top`: the rim of its mouth, where it meets the face.

## Checked as

Exact.
