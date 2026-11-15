# chamfer

Status: **draft, for your approval.**

Bevels edges: a change to another item.

## The shape

Each edge of the edge set ([edges.md](edges.md)) is replaced by a flat
bevel whose two edges lie `size` back from where the edge was, measured
along each face at right angles to the edge (an equal-distance chamfer:
45 degrees between faces at right angles).

- On an outside edge it takes away the material between the bevel and the
  edge.
- On an inside edge (a `joint`, a pocket's floor) it fills the corner
  between the bevel and the edge.
- Where bevelled edges meet at a corner, the bevels meet in a flat corner
  face.

## Fields

### `edges`

Which edges: the item (`of`), its edge set (`which`), and for a `joint`
the item it meets (`where_meets`). See [edges.md](edges.md) and the item's
own page.

### `size`

How far the bevel cuts back along each face.

## Faces

None.

## Edges

None.

## Checked as

Bounded: exact along each edge, between limits where bevels meet.
