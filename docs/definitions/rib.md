# rib

Status: **draft, for your approval.**

A thin wall standing on a face, for stiffness: a standing feature.

## The shape

A box standing on the face where `place` puts it: its base is centred
there, `length` along `along` (one of the face's axes) and `thickness` along
the face's other axis, and it rises `height` out of the face along the face's
outward direction. It is joined to the face over its base, and must lie
wholly on the face.

On a round side, `along` is the side's axis or the direction round it
([place.md](place.md)), `height` from its point, and its foot follows the
curve with no gap under it. Formally, with `u` its direction, `w` its point and the side's axis the line
`A`: every point whose position across `u` lies in its cross-section, that is
no more than `height` beyond `w` along `u` (`(p − w)·u ≤ height`), and that lies
on the open side of the side's round surface: on an outside, further than the
side's radius from `A` and on the side of the plane through `A` at right
angles to `u` that `u` points to; inside a bore or a hollow, nearer `A` than
the side's radius. Its
cross-section is its `length` by `thickness` rectangle.

## Fields

### `on`

The face it stands on ([frame.md](frame.md)).

### `place`

Where on the face ([place.md](place.md)).

### `length`

Its length along `along`.

### `thickness`

Its thickness across.

### `height`

How far it rises out of the face.

### `along`

The axis of its face the rib runs along: one of the face's two axes, named by the
face's own (schema 1.4) or by the part's ([place.md](place.md), "Where on
the face").

- `u`: along the face's first axis.
- `v`: along the face's second axis.
- `x`: along X.
- `y`: along Y.
- `z`: along Z.

### `count`

How many ribs there are in the whole part ([place.md](place.md)).

## Faces

- `+x`, `-x`, `+y`, `-y`, `+z`, `-z`: its flat faces, by the direction each
  faces, except the one it is joined by.

## Edges

- `vertical`: the four edges that run out of the face it stands on.
- `top`: the four edges round its top.
- `joint`: the inside corner round its base, where it meets the face (see
  [edges.md](edges.md)).

## Checked as

Exact.
