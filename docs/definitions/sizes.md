# Sizes, tolerances and standard tables

Status: **draft, for your approval.**

## Units and nominal sizes

- Every size carries its unit, and every angle its unit (degrees,
  radians, revolutions, arc minutes or arc seconds); a number with no unit is
  never read as millimetres or degrees. A count of things has no unit.
- A size is **nominal**: the size the part is designed to (made at the
  middle of its tolerance, below, where that is not the nominal). The printer's
  own offsets are added later, in the print spec, by one declared transform
  (plan, section 4.8); they never change the confirmed spec.
- Where a value came from (the brief's words, a table, a formula from the
  brief's numbers, or an assumption) is recorded with it, and changes
  nothing about the shape.

## Tolerances

A value may carry its own tolerance, `+plus / -minus` in its unit: the part
is right when the built size lies within it.

**A size is made at the middle of its tolerance.** Where a value's own
tolerance is not the same both ways, the part is made to the middle of its
band, and held to the limits as written: 10 mm +0.1/-0 is made 10.05 mm
across, and passes from 10 to 10.1 mm. Made at the nominal it would lie on
a limit, which no measurement can show it within. Every program that makes
geometry from the spec (the placement solver, the compiler, the judge's own
placement and shape, the generator's model) reads this made size; the
spec's text keeps the nominal and the tolerance as written. A tolerance the
same both ways, and the general tolerance below, leave the made size at the
nominal. A size made at or below 0 can't be made, and is refused as
written.

A value without one takes the **general tolerance**, ISO 2768-1 class m
(medium):

| Nominal size | Linear sizes | Radii and chamfer heights |
|---|---|---|
| 0.5 up to 3 mm | ±0.1 mm | ±0.2 mm |
| over 3 up to 6 mm | ±0.1 mm | ±0.5 mm |
| over 6 up to 30 mm | ±0.2 mm | ±1 mm |
| over 30 up to 120 mm | ±0.3 mm | ±1 mm |
| over 120 up to 400 mm | ±0.5 mm | ±1 mm |
| over 400 up to 1000 mm | ±0.8 mm | ±1 mm |
| over 1000 up to 2000 mm | ±1.2 mm | ±1 mm |
| over 2000 up to 4000 mm | ±2 mm | ±1 mm |

Angles, by the length of the shorter side of the angle: up to 10 mm ±1°;
over 10 up to 50 mm ±30'; over 50 up to 120 mm ±20'; over 120 up to 400 mm
±10'; over 400 mm ±5'.

The standard gives nothing under 0.5 mm; Forge uses ±0.05 mm there.

These are **design** tolerances: how far the made part may be from the
spec. They are not how closely Forge checks its own geometry. The views of
the part are checked at their own build tolerance (about 0.001 mm on the
exact model, the export's deviation on a mesh), so an unasked-for 0.3 mm
chamfer is found even where 0.3 mm is within the design tolerance (plan,
section 4.5).

## Through

A depth of `through` goes through the material under the face (see
[frame.md](frame.md)): the cut comes out of the far side of that material
everywhere across its mouth.

## Through everything, and up to a face

Schema 1.7 (item 2b's first step). Two more ends for a cut square to a
flat face:

- `{"through_all": true, "from": ...}`: **through everything** made before
  it along its axis, cavities and all: a pin hole through a hollow
  housing's two walls, or through a plate and the block it stands on. It
  goes on until it has passed everything the part reaches behind its
  mouth, so it comes out of the last of it, cutting through whatever was
  made before it on the way. Where there is nothing but the material under
  the face, it is the same cut as `through`. A body made after it in its
  way would close it, and Forge asks: should that body be cut through too
  (made first), or the cut stop short of it?
- `{"up_to": {"item": ..., "face": ...}, "offset": size, "from": ...}`:
  **up to a face**: its floor is in the plane of that flat face of an item
  made before it, the `offset` (none: 0) back from it towards the mouth. A
  pocket down to a ledge's height follows the ledge when its height
  changes. The face is an item's with one copy, flat, and parallel to the
  face the cut goes into; its plane, less the offset, must be behind the
  mouth (else Forge asks). The depth it comes to is held as a blind cut's
  is: it must fit in the material under the mouth, a counterbore must
  leave some of the hole below it, and it is checked as that depth, within
  the general tolerance for it.

## Through the next face

Schema 1.8 (item 2b's second step). `{"through_next": true, "from": ...}`:
on until the cut is out of the part all across its mouth for the first
time, as the shape says, not as the material under the face is modelled
(frame.md): out of a plate and on through a boss made before it under the
plate; out into a pocket cut before it from the far side; out of a hollow
box's wall into the hollow.

How deep that is, the **preview finds** before the spec is confirmed: what
is made before the cut is built, and the cut's mouth carried along its axis
through it; where the material it meets first ends all across the mouth is
how deep it goes. Forge writes that into the draft as the cut's `"reaches"`
(mm), shows it, and the person confirms it with the rest; a writer leaves
it out. Every copy must come out at the same depth. The judge finds the
depth again on its own model of the part, and the two must agree within
the general tolerance for that depth; a spec whose depth the preview hasn't
found can't be confirmed. A body made after the cut and standing where it
comes out would close it, and Forge asks.

For now these three are cut square to a flat face, not leaning, and not
into a round side, a ball's or a cone's surface, a tab's end or a turned
item's face: Forge says it can't, and why.

## Sizes from standard tables

A hole's diameter may be a standard fit, and any size may be read from a
table (`"from": {"table": ...}`). The entry is recorded, so you see where a
size came from ("4.5 mm (ISO 273 normal clearance for M4)").

### `clearance`

A hole a bolt or screw passes through freely: the ISO 273 clearance hole for
that metric size, in its fine, normal (medium) or coarse series; normal when
the brief doesn't say. In millimetres:

| Size | Fine | Normal | Coarse |
|---|---|---|---|
| M1.6 | 1.7 | 1.8 | 2 |
| M2 | 2.2 | 2.4 | 2.6 |
| M2.5 | 2.7 | 2.9 | 3.1 |
| M3 | 3.2 | 3.4 | 3.6 |
| M4 | 4.3 | 4.5 | 4.8 |
| M5 | 5.3 | 5.5 | 5.8 |
| M6 | 6.4 | 6.6 | 7 |
| M8 | 8.4 | 9 | 10 |
| M10 | 10.5 | 11 | 12 |
| M12 | 13 | 13.5 | 14.5 |
| M16 | 17 | 17.5 | 18.5 |
| M20 | 21 | 22 | 24 |
| M24 | 25 | 26 | 28 |

### `tapped`

A hole a thread is tapped into, or that a screw cuts its own thread in: the
hole is the tap drill. For a coarse thread (M4, or M4x0.7) it is the usual
drill from the table below; for a fine pitch (M8x1) it is the diameter less
the pitch (7 mm), and the pitch must be less than a quarter of the diameter.
Sizes the table doesn't have aren't read. The thread itself is not part of
the modelled shape: it is cut by a tap or formed by the screw. In
millimetres:

| Size | Coarse pitch | Tap drill |
|---|---|---|
| M2 | 0.4 | 1.6 |
| M2.5 | 0.45 | 2.05 |
| M3 | 0.5 | 2.5 |
| M4 | 0.7 | 3.3 |
| M5 | 0.8 | 4.2 |
| M6 | 1 | 5 |
| M8 | 1.25 | 6.8 |
| M10 | 1.5 | 8.5 |
| M12 | 1.75 | 10.2 |
| M16 | 2 | 14 |
| M20 | 2.5 | 17.5 |
| M24 | 3 | 21 |

### `bearing_seat`

A seat a deep-groove ball bearing is pressed into: the hole is the
bearing's outside diameter (22 mm for a 608). A table reference can also
give the bearing's width or bore (`bearing:608:width`). In millimetres:

| Bearing | Outside diameter | Width | Bore |
|---|---|---|---|
| 623 | 10 | 4 | 3 |
| 624 | 13 | 5 | 4 |
| 625 | 16 | 5 | 5 |
| 626 | 19 | 6 | 6 |
| 608 | 22 | 7 | 8 |
| 688 | 16 | 5 | 8 |
| 693 | 8 | 4 | 3 |
| 6000 | 26 | 8 | 10 |
| 6001 | 28 | 8 | 12 |
| 6002 | 32 | 9 | 15 |
| 6200 | 30 | 9 | 10 |
| 6201 | 32 | 10 | 12 |
| 6202 | 35 | 11 | 15 |
| 6203 | 40 | 12 | 17 |
| 6204 | 47 | 14 | 20 |
| 6800 | 19 | 5 | 10 |
| 6900 | 22 | 6 | 10 |

## Counts

A count is a whole number of things, 1 or more, with no unit. It is never a
size: "6" in "6 holes" and "6 mm" can't be mistaken for each other.
