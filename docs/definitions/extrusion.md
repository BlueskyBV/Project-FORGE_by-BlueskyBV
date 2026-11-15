# extrusion

Status: **draft, for your approval.**

A flat outline pushed straight along an axis: a body.

## The shape

The outline, a closed curve of straight lines and circular arcs, swept
straight along the axis from its -end to its +end, `length` apart: every
point whose position across the axis lies inside the outline, between the
two ends.

- As the first body: its axis is the frame axis `axis` names (Z when the
  spec doesn't say, an assumption), and its -end lies in the plane through
  the origin across that axis. The outline's two coordinates are measured
  along the axes of the face its +end faces (for Z, x then y), from the
  origin.
- Standing on a face: its -end on the face, its axis out of the face, the
  outline's two coordinates along the face's own axes from the point
  `place` puts it at (its point `(0, 0)`). Its -end lies wholly on the face.

## Fields

### `profile`

The outline, in millimetres: a start point, then segments, each a straight
line to a point or an arc about a centre to a point, clockwise or
anticlockwise (anticlockwise when not said) in the outline's own plane,
drawn with its first coordinate to the right and its second up. An arc's end
is on its circle: as far from its centre as its start, within 0.001 mm. The
arc is read as the circle through both its ends whose centre is nearest the
centre written (the written centre moved square to the chord, onto the line
through the chord's middle square to it), so it starts and ends exactly
where it is written to. The outline must close, no segment may end where it
starts (a whole circle is two arcs), and it may not cross or touch itself:
nor may it turn straight back where one segment meets the next.

A position on an end is measured as on a rectangle: from the box round the
outline (its edges where the outline ends along each axis, its centre the
box's centre).

### `length`

How far the outline is pushed, along the axis.

### `axis`

The frame axis it runs along, as the first body.

- `x`: along X.
- `y`: along Y.
- `z`: along Z.

### `on`

The face of an earlier item it stands on: a body's, or a feature's (a boss's top, a pocket's floor). The first body has none.

### `place`

Where on that face it stands ([place.md](place.md)). The first body has
none.

## Faces

- `+end`: the flat outline at its far end.
- `-end`: the flat outline where it starts (standing on a face, joined to
  it).
- `side`: what the outline sweeps: nothing is placed on it, for now.

## Edges

- `vertical`: the edges that run along its axis, where the outline has a
  corner: two segments meeting at an angle, not one running on smoothly
  into the next. An outline with no corners has none.
- `top`: the edges round its +end.
- `bottom`: the edges round its -end.
- `all`: every edge.

## Checked as

Exact.
