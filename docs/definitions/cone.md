# cone

Status: **draft, for your approval.**

A cone or truncated cone: a body.

## The shape

Every point between its -end and its +end, `length` apart along its axis,
within a radius of its axis that changes in a straight line from
`base_diameter`/2 at the -end to `top_diameter`/2 at the +end. Either end
may be the wider one; a `top_diameter` of 0 makes a point.

- As the first body: its axis is the frame axis `axis` names (Z when the
  spec doesn't say, an assumption); its -end is centred on the origin, and it
  runs from 0 to +`length` along that axis.
- Standing on a face: its -end is centred where `place` puts it, and it runs
  out of the face along the face's outward direction.

## Fields

### `base_diameter`

Its diameter at its -end, where it starts or stands.

### `top_diameter`

Its diameter at its +end; 0 for a point.

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

- `+end`: its flat +end, a disc. A cone that comes to a point has none.
- `-end`: its flat -end, a disc. Standing on a face, it is joined by this
  end, which can't be used.
- `side`: its tapered side. A hole, a boss or a post goes on it, along its
  axis and round it ([place.md](place.md), "On a cone's side").

## Edges

- `top`: the rim of its +end.
- `bottom`: the rim of its -end, as an outside edge.
- `both`: the rims of both ends.
- `joint`: see [edges.md](edges.md).

## Checked as

Exact.
