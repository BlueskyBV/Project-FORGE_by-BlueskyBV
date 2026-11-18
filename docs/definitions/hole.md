# hole

Status: **draft, for your approval.**

A round hole: a cut.

## The shape

A cylinder of the hole's diameter, its axis through the point `place` puts
it at, at right angles to the face; it goes in from the face, against the
face's outward direction, to its depth. It takes away every point of the
part inside it. A blind hole has a flat bottom.

- On a flat face, its depth is measured from the face.
- On a round side, its axis runs along the radius through its point
  ([place.md](place.md)), and its depth is measured along its axis from that
  point, where the axis meets the side's surface.
  - **Where it starts:** it takes away everything on its axis's open side:
    from outside a rod or tube (starting from the plane that touches the side
    at its point), or from the side's axis inside a bore or a hollow. So its
    mouth follows the curve.
  - **Blind:** its flat bottom is its depth in from its point. It must fit in
    the least material under its mouth: across a solid rod, the far side
    comes first at the hole's edge, radius + √(radius² − (hole's radius)²)
    from its point.
  - **Through a solid rod:** in, across the axis, and out of the far side all
    across its mouth.
  - **Through a tube's wall, or a hollowed cylinder's, from outside:** until
    it is in the bore all across its mouth, √(bore radius² − hole radius²)
    from the axis. A hole as wide as the bore is asked about: one wall, or
    both?
  - **Out through a wall from inside:** until it is out of the outside all
    across its mouth.
  - A counterbore's or countersink's depth is measured the same way, from
    the hole's point, and a countersink's diameter is its diameter in the
    plane that touches the side there.
  - Inside a bore or a hollow, its counterbore and countersink start at the
    side's axis too, as the hole does: a counterbore is its cylinder from
    there; a countersink is a cylinder of its diameter from there to the
    plane that touches the side at the hole's point, and its cone from that
    plane in. So no lip of the wall is left in front of either.

## Fields

### `on`

The face it is cut into ([frame.md](frame.md)).

### `place`

Where on the face ([place.md](place.md)).

### `diameter`

The hole's diameter: a size, or a standard fit ([sizes.md](sizes.md)):
`clearance` for a bolt, `tapped` for a thread (the tap drill), or a
`bearing_seat`.

### `depth`

How deep it goes, from the face: a size, or `through` (through the material
under the face, coming out of the far side all across its mouth,
[frame.md](frame.md)). A blind hole as deep as the material under it is a
hole through. Schema 1.7: also `through_all` (through everything made
before it, cavities and all) or `up_to` a face of an item made before it,
with an offset ([sizes.md](sizes.md)), on a flat face.

### `counterbore`

A wider recess at the hole's mouth: a cylinder of the counterbore's
`diameter`, on the hole's axis, from the face to the counterbore's `depth`,
with a flat bottom. Its diameter is more than the hole's, and its depth less
than the hole's.

### `countersink`

A cone-shaped recess at the hole's mouth, on the hole's axis: its
`diameter` at the face, narrowing in at its `angle` (the angle across the
cone's point, 90 degrees for most screws) until it meets the hole's diameter.
So it is (countersink diameter - hole diameter) / 2 / tan(angle / 2) deep.
A hole has a counterbore or a countersink, not both, for now.

### `tilt`

How far it leans from square to its flat face, towards `tilt_towards`
([place.md](place.md), "Leaning on the face"): more than 0, and at most 75
degrees for now; its `depth` is then along its lean. Schema 1.3.

### `tilt_towards`

Which way it leans: one of its face's two axes, + or -.

- `+u`, `-u`: towards the face's first axis, + or - (schema 1.4).
- `+v`, `-v`: towards the face's second axis, + or - (schema 1.4).
- `+x`, `-x`: towards +X or -X.
- `+y`, `-y`: towards +Y or -Y.
- `+z`, `-z`: towards +Z or -Z.

Only the face's two axes are ways it may lean (on a `+z` face, `x` or `y`).

### `count`

How many holes there are in the whole part ([place.md](place.md)).

## Faces

None: nothing stands on or is cut into a hole.

## Edges

- `top`: the rim of its mouth, where it meets the face; with a counterbore or
  a countersink, the rim of that, at the face.

## Checked as

Exact.
