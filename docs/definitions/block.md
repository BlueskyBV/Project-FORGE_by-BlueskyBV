# block

Status: **draft, for your approval.**

A rectangular block, plate or bar: a body.

## The shape

A box: every point within `length`/2 of its centre along its first axis,
within `width`/2 along its second, and between its base and `height` above
it along its up direction.

- As the first body: its first axis is x, its second y, and up is +z. Its
  bottom face is centred on the origin.
- Standing on a face: its base is centred where `place` puts it on that
  face, its first and second axes are the face's, and up is the face's
  outward direction. It may overhang the face, but must meet it.

## Fields

### `length`

Its size along its first axis: along x as the first body, along the face's
first axis when it stands on a face.

### `width`

Its size along its second axis.

### `height`

Its size along its up direction: up from the origin, or out of the face it
stands on.

### `on`

The face of an earlier item it stands on: a body's, or a feature's (a boss's top, a pocket's floor). The first body has none.

### `place`

Where on that face it stands ([place.md](place.md)). The
first body has none.

## Faces

- `+x`, `-x`, `+y`, `-y`, `+z`, `-z`: its six flat faces, by the direction
  each faces. The one it is joined by, standing on a face, can't be used.
- `inner +x`, `inner -x`, `inner +y`, `inner -y`, `inner +z`, `inner -z`:
  only when a shell hollows it: the inside face of each wall, facing into
  the hollow. `inner -z` is the inside of its -z wall, a tray's floor,
  facing up. A wall the shell leaves open has no inner face.

## Edges

- `vertical`: the four edges that run along its up direction.
- `top`: the four edges round the face it rises to.
- `bottom`: the four edges round its base, as outside edges. Where a block
  stands on a face its base is joined to the face, and the corner there is
  its `joint`; only where it overhangs the face does its base have outside
  edges.
- `all`: all twelve.
- `joint`: see [edges.md](edges.md).

## Checked as

Exact.
