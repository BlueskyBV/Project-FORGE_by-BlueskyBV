# tab

Status: **draft, for your approval.**

A flat lug sticking out of a face, with a square or fully round end: a
standing feature.

## The shape

The tab stands on the face where `place` puts it. Its base is centred
there: `thickness` along `thickness_along` (one of the face's axes) and
`width` along the face's other axis. It sticks out `length` from the face
along the face's outward direction. It is joined to the face over its base,
and must lie wholly on the face.

- With a square end: a box, `thickness` by `width` by `length`.
- With a round end: seen along its thickness, its far end is a half-circle
  of diameter `width` whose outermost point is `length` from the face. It is
  a box `length` - `width`/2 long, and a half-cylinder of radius `width`/2,
  its axis along `thickness_along`, on the box's far end. The length must be
  at least half the width; a tab exactly that long is all half-disc.

On a round side its width runs round the side or along the side's axis, as
`thickness_along` says ([place.md](place.md)), `length` from its point, and
its foot follows the curve with no gap under it. Formally, with `u` its direction, `w` its point and the side's axis the line
`A`: every point whose position across `u` lies in its cross-section, that is
no more than `length` beyond `w` along `u` (`(p − w)·u ≤ length`), and that lies
on the open side of the side's round surface: on an outside, further than the
side's radius from `A` and on the side of the plane through `A` at right
angles to `u` that `u` points to; inside a bore or a hollow, nearer `A` than
the side's radius.
Its cross-section is its `thickness` by `width` rectangle, and its far end
is shaped as above.

## Fields

### `on`

The face it stands on ([frame.md](frame.md)).

### `place`

Where on the face ([place.md](place.md)).

### `length`

How far it sticks out of the face, to the far end of its rounding when its
end is round.

### `width`

Its width across, along the face's axis that its thickness doesn't run
along.

### `thickness`

Its thickness.

### `thickness_along`

The frame axis its thickness runs along; it must be one of the face's two
axes.

- `x`: along X.
- `y`: along Y.
- `z`: along Z.

### `end`

- `square`: a square end.
- `round`: a fully round end, a half-circle of diameter `width`.

### `count`

How many tabs there are in the whole part ([place.md](place.md)).

## Faces

Positions on its faces are measured as on the rectangles round them: a broad
face's centre is halfway out, at `length`/2, and its far edge is the top of
the rounding.

- `+x`, `-x`, `+y`, `-y`, `+z`, `-z`: its flat faces, by the direction each
  faces, except the one it is joined by. With a round end, its two broad
  faces (across its thickness) have the half-circle's outline; its two
  narrow sides stop where the rounding starts, and are none at all when it is
  all half-disc; its far end is curved, and nothing is placed on it, for now.

## Edges

- `vertical`: the four edges that run out of the face it stands on (with a
  round end, along its straight part).
- `top`: the edges round its far end: the end face's four, or, with a round
  end, the two half-circles where its rounding meets its broad faces.
- `joint`: the inside corner round its base, where it meets the face (see
  [edges.md](edges.md)).

## Checked as

Exact.
