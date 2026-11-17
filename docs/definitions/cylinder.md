# cylinder

Status: **draft, for your approval.**

A solid round rod, disc or puck: a body.

## The shape

Every point within `diameter`/2 of its axis, between its -end and its +end,
`length` apart along the axis.

- As the first body: its axis is the frame axis `axis` names (Z when the
  spec doesn't say, an assumption); its -end is centred on the origin, and it
  runs from 0 to +`length` along that axis.
- Standing on a face: its -end is centred where `place` puts it, and it runs
  out of the face along the face's outward direction. It may overhang the
  face, but must meet it.

## Fields

### `diameter`

Its outside diameter.

### `length`

Its length along its axis, from its -end to its +end.

### `axis`

The frame axis it runs along, as the first body. A cylinder standing on a
face runs out of the face, and gives no axis (or the one the face's
direction already fixes).

- `x`: along X.
- `y`: along Y.
- `z`: along Z, upright.

### `on`

The face of an earlier item it stands on: a body's, or a feature's (a boss's top, a pocket's floor). The first body has none.

### `place`

Where on that face it stands ([place.md](place.md)). The first body has
none.

### `tilt`

How far it leans from square to the flat face it stands on, towards
`tilt_towards` ([place.md](place.md), "Leaning on the face"): more than 0,
and at most 75 degrees for now; its `length` is then along its lean. Schema
1.5.

### `tilt_towards`

Which way it leans: one of its face's two axes, + or -.

- `+u`, `-u`: towards the face's first axis, + or - (schema 1.4).
- `+v`, `-v`: towards the face's second axis, + or - (schema 1.4).
- `+x`, `-x`: towards +X or -X.
- `+y`, `-y`: towards +Y or -Y.
- `+z`, `-z`: towards +Z or -Z.

## Faces

- `+end`: its flat end at the far end of its axis, a disc.
- `-end`: its flat end where it starts, a disc. Standing on a face, it is
  joined by this end, which can't be used.
- `side`: its round side.
- `inner +end`, `inner -end`, `inner side`: only when a shell hollows it:
  the inside faces of its +end wall, its -end wall (facing into the hollow
  along the axis) and its side wall (facing the axis). An end the shell
  leaves open has no inner face.

## Edges

- `top`: the rim of its +end.
- `bottom`: the rim of its -end, as an outside edge (see the block's
  `bottom`: standing on a face, the corner there is its `joint`).
- `both`: the rims of both ends.
- `joint`: see [edges.md](edges.md).

## Checked as

Exact.
