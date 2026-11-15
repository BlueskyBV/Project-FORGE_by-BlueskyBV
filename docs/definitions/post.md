# post

Status: **draft, for your approval.**

A square or rectangular post standing on a face: a standing feature.

## The shape

A box standing on the face where `place` puts it: its base is centred
there, `length` along the face's first axis and `width` along its second,
and it rises `height` out of the face along the face's outward direction. It
is joined to the face over its base, and must lie wholly on the face.

On a round side its length runs round the side and its width along the
side's axis ([place.md](place.md)), `height` from its point, and its foot
follows the curve with no gap under it. Formally, with `u` its direction, `w` its point and the side's axis the line
`A`: every point whose position across `u` lies in its cross-section, that is
no more than `height` beyond `w` along `u` (`(p − w)·u ≤ height`), and that lies
on the open side of the side's round surface: on an outside, further than the
side's radius from `A` and on the side of the plane through `A` at right
angles to `u` that `u` points to; inside a bore or a hollow, nearer `A` than
the side's radius. Its
cross-section is its `length` by `width` rectangle.

## Fields

### `on`

The face it stands on ([frame.md](frame.md)).

### `place`

Where on the face ([place.md](place.md)).

### `length`

Its size along the face's first axis.

### `width`

Its size along the face's second axis.

### `height`

How far it rises out of the face.

### `count`

How many posts there are in the whole part ([place.md](place.md)).

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
