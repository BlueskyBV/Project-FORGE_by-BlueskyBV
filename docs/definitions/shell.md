# shell

Status: **draft, for your approval.**

Hollows a body, leaving walls: a change to another item.

## The shape

The body (`of`) is hollowed out, leaving each of its faces as a wall made
inward from it. The body is first made with the roundings and chamfers of
its own edges that border no open face ([frame.md](frame.md)), and the walls
follow them; the edges of the open faces' rims are rounded after.

The **hollow** is every point of the body that is at least its wall's
thickness from each of the body's closed faces:

- each face's wall is `thickness` thick, a rounding's or a chamfer's face
  included;
- the **floor**, the wall opposite an open face, is `floor` thick when the
  shell gives one;
- a face left `open` has no wall: it is not one of the closed faces, so the
  hollow runs out through it.

So, by kind:

- **block:** the hollow is a box, each of its six sides in from the block's
  side by that wall's thickness. An open box with its `+z` open is a tray,
  its `-z` wall the floor. Where the block's edges are rounded, the hollow's
  corners are rounded by the rounding's radius less the wall's thickness, and
  are sharp where that is nothing or less; where they are chamfered, the
  hollow's corners are bevelled to keep the wall's thickness. (So it is with
  one thickness all round. Where the floor is thicker or thinner than the
  walls, a rounded floor edge's corner is what the distances above leave:
  the floor ends where the rounding meets it.)
- **cylinder:** the hollow is a cylinder `thickness` in from the side, its
  ends in from the +end and -end by their walls' thickness (none where
  open; `floor` opposite an open end).
- **sphere**, whole: the hollow is a ball `thickness` smaller in radius,
  with the same centre, sealed.
- **sphere**, dome: the hollow is every point within `thickness` less than
  the dome's radius of its flat face's centre, and more than its floor above
  the flat face. The floor, its flat face's wall, is `floor` thick
  (`thickness` when no floor is given), or none when the flat face is left
  open.

The shell hollows its body alone, never what stands on it. Tubes are hollow
already, and other kinds can't be hollowed, for now.

## Fields

### `of`

The body to hollow: a block, a cylinder or a sphere.

### `thickness`

The thickness of its walls.

### `open`

The faces left open, with no wall; none for a sealed hollow. A block may
leave open any of its six faces, a cylinder its ends, a dome its flat face;
a whole ball none.

### `floor`

A different thickness for the floor, the wall opposite an open face; for a
dome, its flat face's wall. A block or cylinder with no open face opposite
a wall has no floor.

## Faces

None of its own: the body it hollows gains its inner faces (see the body's
page).

## Edges

None.

## Checked as

Exact.
