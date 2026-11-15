# revolution

Status: **draft, for your approval.**

An outline turned a full turn about an axis (knobs, pulleys): a body.

## The shape

The half outline turned once round the axis: every point whose distance
from the axis and height along it lie inside the outline.

- As the first body: its axis is the frame axis `axis` names (Z when the
  spec doesn't say, an assumption), through the origin; heights are measured
  along it from the origin.
- Standing on a face: it turns about the line out of the face through the
  point `place` puts it at, heights measured from the face along that line.
  It must meet the face: its outline runs straight across the axis at
  height 0, and nowhere lower (nothing reaches behind the face); that end,
  to its outer circle, lies wholly on the face, and the rest may overhang it.

## Fields

### `profile`

The half outline, in millimetres: the first coordinate is the distance from
the axis (never less than 0, arcs included), the second the height along it.
Its segments are as an extrusion's ([extrusion.md](extrusion.md)): it must
close, and may not cross or touch itself. Where it lies on the axis, the
solid closes there.

### `axis`

The frame axis it turns about, as the first body.

- `x`: about X.
- `y`: about Y.
- `z`: about Z.

### `on`

The face of an earlier item it stands on: a body's, or a feature's (a boss's top, a pocket's floor). The first body has none.

### `place`

Where on that face it stands ([place.md](place.md)). The first body has
none.

## Faces

- `+end`: the flat face at its greatest height, if the outline runs
  straight across the axis there, in one segment and nothing else of it at
  that height: a disc if that segment reaches the axis, else a ring.
- `-end`: the flat face at its least height, likewise (standing on a face,
  joined to it).
- `side`: the rest: nothing is placed on it, for now.

The material under an end, at each distance from the axis, is from the end
along the line there to where it first leaves the outline (and, under the
far end of one standing on a face, where that line runs right through and
is over the face, the material under the face there too: frame.md).

## Edges

- `top`: the edges round its +end: each circle where the end meets the side
  next to it at an angle, off the axis. Where the side runs on smoothly
  into the end there is no edge; with no flat +end, none at all.
- `bottom`: the edges round its -end, the same way.

## Checked as

Exact.
