# tube

Status: **draft, for your approval.**

A hollow round tube, ring or bushing: a body.

## The shape

Every point between `inner_diameter`/2 and `outer_diameter`/2 from its axis,
between its -end and its +end, `length` apart along the axis. The bore goes
all the way through.

- As the first body: its axis is the frame axis `axis` names (Z when the
  spec doesn't say, an assumption); its -end is centred on the origin, and it
  runs from 0 to +`length` along that axis.
- Standing on a face: its -end is centred where `place` puts it, and it runs
  out of the face along the face's outward direction.

## Fields

### `outer_diameter`

Its outside diameter.

### `inner_diameter`

The diameter of its bore. It must be less than the outside diameter.

### `length`

Its length along its axis.

### `axis`

The frame axis it runs along, as the first body; standing on a face it runs
out of the face.

- `x`: along X.
- `y`: along Y.
- `z`: along Z, upright.

### `on`

The face of an earlier item it stands on: a body's, or a feature's (a boss's top, a pocket's floor). The first body has none.

### `place`

Where on that face it stands ([place.md](place.md)). The first body has
none.

## Faces

- `+end`: its far end, a ring.
- `-end`: the end it starts from, a ring. Standing on a face, it is joined
  by this end, which can't be used.
- `side`: its round outside.
- `bore`: the round inside of its bore, facing the axis.

## Edges

- `top`: both rims of its +end, the outside one and the bore's.
- `bottom`: both rims of its -end, as outside edges.
- `both`: all four rims.
- `outer`: the outside rims, at both ends.
- `bore`: the bore's rims, at both ends.
- `joint`: see [edges.md](edges.md).

## Checked as

Exact.
