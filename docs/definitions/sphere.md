# sphere

Status: **draft, for your approval.**

A ball, or half of one (a dome) with its flat side down: a body.

## The shape

- A whole ball: every point within `diameter`/2 of its centre. As the first
  body it rests on the origin, its centre at (0, 0, `diameter`/2). Standing
  on a face, its centre is on the face, where `place` puts it: its lower half
  is joined with whatever it overlaps, and comes out of the far side of a
  host thinner than its radius.
- A dome: every point within `diameter`/2 of the centre of its flat face,
  on the side its flat face faces away from. As the first body its flat face
  is centred on the origin and it rises along +Z. Standing on a face, its
  flat face lies on the face, centred where `place` puts it, and it rises out
  of the face.

## Fields

### `diameter`

The ball's diameter; a dome's is the diameter of the ball it is half of.

### `portion`

- `whole`: the whole ball.
- `upper_half`: a dome: the half of the ball above its flat face.

### `on`

The face of an earlier item it stands on: a body's, or a feature's (a boss's top, a pocket's floor). The first body has none.

### `place`

Where on that face it stands ([place.md](place.md)). The first body has
none.

## Faces

- `-end`: a dome's flat face, a disc. A whole ball has none. Standing on a
  face, a dome is joined by it, and it can't be used.
- `surface`: its curved surface. Nothing is placed on it, for now.

## Edges

- `bottom`: a dome's rim, where its curved surface meets its flat face, as
  an outside edge. A whole ball has none.
- `joint`: see [edges.md](edges.md).

## Checked as

Exact.
