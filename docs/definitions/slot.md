# slot

Status: **draft, for your approval.**

An elongated cut, with round or square ends.

## The shape

Its outline on the face is centred where `place` puts it: `length` long
along `along`, `width` wide across it.

- With round ends: a stadium, two half-circles of diameter `width` joined by
  straight sides; the ends' outermost points are `length` apart. A slot as
  long as it is wide is a circle.
- With square ends: a rectangle `length` by `width`.

The outline goes in from the face, at right angles to it, to its depth, with
a flat bottom, and takes away every point of the part inside it.

## Round a side

A slot is also cut into a rod's, a boss's or a tube's round side from
outside, as a keyway: it runs `along` the side's axis, and its outline lies
in the plane that touches the side along the line through its point (`place`
puts that point, by its position along the axis and its `angle` round it, as
it does a hole's: [place.md](place.md), "Round a side"): `width` round the
side, `length` along it. It goes in square to that plane, towards the axis,
to its `depth` from that plane, with a flat bottom, and takes away every
point of the part inside it: its walls run down from where they leave the
side to its floor. A keyway is so deep that the material under it is the
least under its outline: into a solid rod, the far side comes first along
its long edges, `R + √(R² − (width/2)²)` in; into a tube's wall, the bore.
`through`, it goes on until it is out of the part all across its outline:
a tube's wall until it is in the bore all across (`R − √(r² − (width/2)²)`,
`r` the bore's radius), a solid rod right across it, out of its far side
(a slotted rod). One `through` a tube's wall as wide as its bore, or
wider, would open its far wall too: Forge asks whether through one wall
only or right across through both. Copies go round the side in a circle, as
holes do.

Not yet: one running round the side, or from inside a bore, on a round-ended
tab's end or round what stands on a turned item's face; through the next
face, through everything or up to a face. Its `top` edge, where its walls
and ends meet the side, is rounded or chamfered as any edge is.

## Fields

### `on`

The face it is cut into ([frame.md](frame.md)).

### `place`

Where on the face ([place.md](place.md)).

### `width`

Its width across, from one long side to the other.

### `length`

Its overall length, from end to end, the round ends included. It can't be
less than the width.

### `along`

The axis of its face the slot runs along: one of the face's two axes, named by the
face's own (schema 1.4) or by the part's ([place.md](place.md), "Where on
the face").

- `u`: along the face's first axis.
- `v`: along the face's second axis.
- `x`: along X.
- `y`: along Y.
- `z`: along Z.

### `ends`

- `round`: each end a half-circle of diameter `width`.
- `square`: square ends.

### `depth`

How deep it goes, from the face: a size, or `through` ([sizes.md](sizes.md)).
Schema 1.7: also `through_all` or `up_to` a face, with an offset
([sizes.md](sizes.md)); schema 1.8, `through_next`.

### `count`

How many slots there are in the whole part ([place.md](place.md)).

## Faces

None: nothing stands on or is cut into a slot.

## Edges

- `top`: the rim of its mouth, where it meets the face.

## Checked as

Exact.
