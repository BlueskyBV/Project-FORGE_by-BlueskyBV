# Edges, and rounding or chamfering them

Status: **draft, for your approval.**

An **edge** is a line where two faces of the part meet at an angle. A
**fillet** rounds edges ([fillet.md](fillet.md)); a **chamfer** bevels them
([chamfer.md](chamfer.md)).

## Outside and inside edges

- An **outside** edge has the material on the narrow side of the angle: the
  edges of a block. Rounding or chamfering it takes material away.
- An **inside** edge, or inside corner, has the material on the wide side:
  where a post meets the plate it stands on, or round a pocket's floor.
  Rounding or chamfering it adds material into the corner.

## Edge sets

A fillet or chamfer names its edges by meaning: an item (`of`) and one of
that item's **edge sets** (`which`), as its kind's page lists them, such as
a block's `vertical` edges or a boss's `joint`. Edges are never picked by
position or by number.

- An edge set names edges of the item as its own fields make it: a post's
  `top` edges are the edges round its top face, not the rim of a hole cut
  into that face (which is the hole's own `top` edge set).
- An edge that another item cuts across is still one edge: every piece of
  it left is rounded.
- Roundings and chamfers are made one after another, in the order the
  part is made in ([frame.md](frame.md)). An edge set that
  runs round a face whose corners an earlier rounding has rounded (a
  block's `top` edges, after its `vertical` edges) follows the face's edge
  as that rounding left it: round each rounded corner too, so the two
  roundings meet smoothly. Where an earlier rounding has taken an edge's
  corner away and the edge runs on smoothly into that rounding's own edge,
  there is no corner left to round there.
- On a body a shell opens, an edge that borders an open face is the rim's:
  rounding it rounds the outside edge and the inside edge of the walls' ends
  alike, so each rounding is at most half the wall's thickness. At exactly
  half, the two meet in the middle, rounding the rim right over (or
  bevelling it to a ridge): Forge doesn't make that yet, and asks.
- A rounding (a bevel) is made after what is on the faces either side of
  its edges: a hole's mouth, or what stands there, within its size of an
  edge it rounds would be run into, and the round wouldn't be one (on a
  face square to a rounded edge, within the corner it rounds). You are
  asked: further from the edge, or a smaller rounding. (A block's faces; a
  cylinder's and a cone's ends and sides.)
- An edge set that names no edges at all is never skipped: a whole ball has
  no rim to round (the writer is asked again); a body standing wholly on a
  face has no outside edges round its base, only its `joint` (you are
  asked); where a cut has taken an edge away, that is found when the part's
  shape is worked out from the spec, before anything is built, and you are
  asked.

### A turned item's edges

A turned item's edge sets (place.md, "Turned in the face"), and those of
what is on a turned item's faces ("A turned item's faces"), are the edges
they are with it upright and unturned, turned with it: a turned post's
`vertical` edges are its four upright edges, each turned about the line
through its point; a hole's `top` edge on a turned post's side is its rim
there. Each is rounded or chamfered as it would be upright, every rule
above holding as it does there.

### A leaning item's edges

A leaning item's (place.md, "Leaning on the face") far end's edges (a
post's or a block's `top` edges, a boss's or a cylinder's `top` rim) and a
leaning box's `vertical` edges, those along its lean, are the edges they
are with it upright, leaned with it: each long edge runs from where it
meets the face's plane, which differs from one to the next. Each is
rounded or chamfered as it would be upright, the round running on down to
the face's plane and stopping there; a far end that dips into the face
has its edge where it is out of the face, its round stopping at the
face's plane alike. Its `joint`, where it meets
its face (round a leaning boss an ellipse whose angle to the face changes
all round it), is not rounded or chamfered yet.

### Round a side, and on a ball's surface or a cone's side

An item round a side (place.md, "Round a side"; a round-ended tab's end is
one over its half), on a ball's or a dome's
surface ("On a ball's surface") or on a cone's side ("On a cone's side")
has the edge sets it has upright, at the angle or the latitude it is
placed at: a boss's `top` rim, a post's `vertical` and `top` edges, each
rounded or chamfered as at the quarter turn below its angle, or at the
ball's pole, then moved with it. Its `joint`, where it meets the side, the
ball or the cone, and a hole's `top` edge there, its mouth, are curves on
the round surface, not in one plane: each is rounded or chamfered all
along it. The judge holds such a rounding to
the band round the curve, within four times its size of the surface, and
doesn't measure its size there yet.

### `joint`

The inside corner where the item meets the item named in `where_meets`. One
of the two must stand on the other. The joint runs all round the line where
the standing item's sides meet the face it stands on. Where the standing
item hangs over the face's edge, the corner is under the overhang, between
the overhang's underside and the host's side. Where a side of the standing
item is flush with an edge of the face, there is no corner along that side;
flush on every side, there is no joint to round, and the rounding can't be
made (a CAN'T).
