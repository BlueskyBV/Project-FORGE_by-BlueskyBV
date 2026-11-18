# The frame, faces, and how the part is made

Status: **draft, for your approval.**

## The frame

- The frame is right-handed. X is the part's length, Y its width and Z its
  height; Z is up. Positions are in millimetres.
- **The first body** sits on the origin, and nothing places it:
  - a block has the centre of its bottom face at the origin: it fills
    x from -length/2 to +length/2, y from -width/2 to +width/2, z from 0 to
    height;
  - a cylinder, tube or cone runs along its `axis` (Z when the spec doesn't
    say, an assumption). The centre of its -end is at the origin, and it
    runs from 0 to +length along that axis;
  - a whole ball rests on the origin: its centre is at (0, 0, diameter/2);
  - a dome has the centre of its flat face at the origin and rises along +Z.
- Every other item stands on, or cuts into, a face of an item made before
  it. Nothing is placed by coordinates.

## Faces

- A face is named by the direction it faces: a block's top is `+z`. A round
  item's faces are its `+end`, its `-end` and its `side`; a tube also has its
  `bore`; a pocket's floor is its `bottom`; a hollowed body has the inside
  faces of its walls (`inner -z`, `inner side`). Each kind's page lists its
  faces. One name means one face, and one face has one name.
- A face faces **outward**, out of the material. The inside face of a wall
  faces into the hollow; a bore faces its own axis.
- A flat face has a centre, its outward direction, and two axes of its own:

  | face | first axis | second axis |
  |---|---|---|
  | +z, -z | x | y |
  | +x, -x | y | z |
  | +y, -y | x | z |

  A round item's end has the axes of the direction it faces: the +end of a
  cylinder along Z has x and y.
- A flat face is a rectangle (a round-ended tab's flat sides have two
  rounded corners), a disc, or a ring. Its **edge on a side** (its `-x`
  edge, say) is where it ends along that axis: for a rectangle, its side;
  for a disc or a ring, the line along which its rim reaches furthest that
  way.
- A **round side** has an axis, a radius, and a length between its two ends.
- Some faces can't take anything, and an item put on one is turned back
  with the reason: the face a standing item is joined by; a face a shell
  leaves open but for its rim (a ring round a cylinder's mouth, a frame
  round a block's: shell.md, "The rim"); and, for now, curved faces other than a round body's side
  (a cone's side, a ball's surface, a round-ended tab's end), and the faces
  of an item standing round a side other than its far face (where its foot
  follows the curve, their edges do too).

## Standing on a face

An item that stands on a face at a point on it (a body, a boss, a post, a
tab, a rib, a region):

- has its base in the face's plane, centred on the point;
- rises out of the face along the face's outward direction, by its height;
- has its length along the face's first axis and its width along its second,
  unless its kind says otherwise (a rib's `along`, a tab's
  `thickness_along`);
- is joined to the face over its base: the two become one solid, and the face
  it is joined by can't be used.

A body may overhang the face it stands on, as a bolt's head overhangs its
shank, but it must meet the face. A standing feature must lie wholly on the
face. A whole ball standing on a face is centred on the point, half sunk into
what it stands on.

## Cutting into a face

A cut on a face at a point on it (a hole, a slot, a pocket, engraved letters)
has its mouth in the face's plane, centred on the point, and goes into the
material, against the face's outward direction, by its depth. Embossed
letters stand out of the face instead.

## The material under a face

How deep "through" goes, and whether a blind cut fits, are measured in the
material under a face: from the face, straight in against its outward
direction.

- A body's outer face: the body's own thickness to its opposite face. A
  block's face: the block's size across it. A cylinder's or tube's end: its
  length.
- A cone's end: its length out to the radius of its smaller end; from there
  the cone's own material falls in a straight line to nothing at the radius
  of its larger end. What the cone stands on is under it only within its
  smaller end.
- A dome's flat face: the dome's height above the point,
  √(radius² - distance from the centre²).
- A round side: the material a cut along the radius meets. A solid rod's is
  its whole diameter: a cut goes in, across the axis, and out of the far
  side. A tube's, or a hollowed cylinder's, is its wall.
- A hollowed body's face: its wall's thickness there.
- A leaning item's far face: its own, from each point back along its axis to
  the face it leans on: its height on the axis, less by tan(tilt) for each
  millimetre towards the way it leans (place.md, "A leaning item's far
  face").
- A pocket's floor: what is left under it (the material under the face it
  was cut into, less its depth).
- The far face of an item standing on a host (the top of a post on a
  plate): the item's own height, and, at a point over the host's face, the
  material under the host's face there too. Where the item overhangs its
  host, a point over the overhang has only the item's own height under it.

Under a cut's mouth the material may vary (on a cone, a dome, a round side,
an overhang). A blind cut must fit in the **least** material under its mouth.
A cut **through** goes through the **most**: it comes out of the far side
everywhere across its mouth. A cut **through everything** (schema 1.7) isn't
measured in the material under its face: it goes on past everything made
before it, as far as the part reaches behind its mouth ([sizes.md](sizes.md)).
A cut **up to a face** goes to that face's plane, less its offset, and must
fit in the least material under its mouth as a blind cut does. A cut
**through the next face** (schema 1.8) goes as the shape says: until it is
out of the part all across its mouth for the first time, which the preview
finds and the spec records ([sizes.md](sizes.md)).

The material under a face is what its own items make it. Cuts made before
don't change it: a blind hole that reaches a pocket cut from the far side
breaks into the pocket, as the shapes say.

## The order the part is made in

The part is made one item at a time.

1. Each time, the next item made is the earliest in the spec of those whose
   dependencies are all made. An item depends on what it stands on or cuts
   into, what it is concentric with, what it hollows, rounds or threads, and
   the item whose face it is cut up to.
2. A body or a standing feature adds its points to the part.
3. A cut takes its points away from what has been made so far. What is made
   after it is not cut by it: a post standing on a pocket's floor stands in
   the pocket.
4. A hollowed body is made whole, before anything stands on it or cuts
   into it: the body; the roundings and chamfers of those of its own edges
   that don't border a face its shell leaves open, in the spec's order, so
   its walls follow them; its hollow; then the roundings and chamfers of its
   edges that do border an open face, which round the rim's outside and
   inside edges alike. A rounding with edges of both sorts is made in both
   places. The shell hollows that body alone, never what stands on it.
5. Every other rounding and chamfer, and every thread, is made last, in the
   spec's order, on the shape made so far.

The **part** is the one solid all of this makes. Every body stands on an
earlier one, so the part is one piece; a cut that would cut it in two is a
CAN'T.

## Copies

An item on a face of something with several copies goes on every copy:
four bosses each with a hole make four holes. Copies are numbered in the
order they are made (see [place.md](place.md)).
