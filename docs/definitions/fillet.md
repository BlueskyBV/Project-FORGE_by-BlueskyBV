# fillet

Status: **draft, for your approval.**

Rounds edges: a change to another item.

## The shape

Each edge of the edge set ([edges.md](edges.md)) is replaced by a round
of `radius`: the surface a ball of that radius sweeps as it rolls along
the edge touching both faces. The round meets both faces tangentially,
`radius` back from where the edge was (for faces at right angles; further
back for faces at a narrower angle).

- On an outside edge it takes away the material between the round and the
  edge.
- On an inside edge (a `joint`, a pocket's floor) it fills the corner
  between the round and the edge.
- Where rounded edges meet at a corner, the rounds run into each other
  smoothly.

## Fields

### `edges`

Which edges: the item (`of`), its edge set (`which`), and for a `joint`
the item it meets (`where_meets`). See [edges.md](edges.md) and the item's
own page.

### `radius`

The radius of the round.

## Faces

None.

## Edges

None.

## Checked as

Bounded. Along an edge between two flat faces, or a flat face and a
cylinder, the round's surface is known exactly. Where rounds meet at a
corner or run out into a face, the made surface must lie between an inner
and an outer limit (an outside round lies between its chamfer and the sharp
corner), and the exact model's radius is measured.
