# boss

Status: **draft, for your approval.**

A round post standing on a face: a standing feature.

## The shape

A cylinder of `diameter`, standing on the face where `place` puts it: its
foot is centred there, and it rises `height` out of the face along the face's
outward direction. It is joined to the face over its foot, and must lie
wholly on the face.

On a round side, it stands out along the radius ([place.md](place.md)),
`height` from its point, and its foot follows the curve with no gap under
it. Formally, with `u` its direction, `w` its point and the side's axis the line
`A`: every point whose position across `u` lies in its cross-section, that is
no more than `height` beyond `w` along `u` (`(p − w)·u ≤ height`), and that lies
on the open side of the side's round surface: on an outside, further than the
side's radius from `A` and on the side of the plane through `A` at right
angles to `u` that `u` points to; inside a bore or a hollow, nearer `A` than
the side's radius. Its cross-section is a disc of
`diameter`.

## Fields

### `on`

The face it stands on ([frame.md](frame.md)).

### `place`

Where on the face ([place.md](place.md)).

### `diameter`

Its outside diameter.

### `height`

How far it rises out of the face.

### `count`

How many bosses there are in the whole part ([place.md](place.md)).

## Faces

- `+end`: its flat top, a disc.
- `side`: its round side.

Its foot is joined to the face, and is no face of its own.

## Edges

- `top`: the rim of its top.
- `joint`: the inside corner round its foot, where it meets the face (see
  [edges.md](edges.md)).

## Checked as

Exact.
