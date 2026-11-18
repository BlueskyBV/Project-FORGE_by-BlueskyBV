# Where an item goes

Status: **draft, for your approval.**

An item's `on` names the face it stands on or cuts into. Its `place` says
where on that face it goes: a position along each axis of the face, or an
angle round a round side, or a pattern of copies, or `concentric` with
another item. What the spec leaves out is not guessed: it is centred, or
started at 0 degrees, or measured to the centre, and that is recorded as an
**assumption** you see first when you confirm.

An item's **footprint** is its outline on the face: a hole's circle (its
counterbore's or countersink's, if wider), a slot's stadium, a pocket's
rectangle, a post's base, the box round a line of letters. Its **reach
along an axis** is half the footprint's size along that axis.

A face's edges and ends are its own: the inside face of a hollow's wall runs
between the hollow's ends, so a position on it is measured from those, and
a round-ended tab's broad face is measured as the rectangle round it.

## On a flat face

A flat face has two axes in its plane, its first and its second (frame.md's
table), named in a draft by the face's own names, `u` and `v` (schema 1.4),
or by the part's axes they run along (`x`, `y`, `z`), on a face whose axes
are the part's. On a turned face (a turned item's far face, below) only `u`
and `v` name them: the part's axes don't run along them, and naming them so
is a fault. An item names its face's axes one way, in its positions and
their sides (`+u`, `-v`), its pattern's values, counts and axis (`inset_u`,
`pitch_v`), its `along` or `thickness_along`, and the way it leans
(`tilt_towards`); naming them both ways is a fault. Round a side, `u` and
`v` name nothing: an item is placed along the side's axis and by angle.

Each of the face's two axes takes one position, or none:

- **none:** the item is centred along that axis (an assumption).
- **`centred`:** the item's centre is on the face's centre line along that
  axis, as the brief says.
- **`offset`:** the item's centre is that far from the face's centre, along
  the axis; a negative offset is towards the axis's minus side.
- **`side`, `distance`, `to`:** measured from the face's edge on that side
  (`-x` is its edge at the smallest x), in towards the face:
  - `to` `centre`: the item's centre is `distance` from the edge;
  - `to` `edge`: the item's nearest edge is `distance` from the face's edge,
    so its centre is `distance` + its reach along the axis;
  - no `to`: to the centre (an assumption).

A position along an axis the face doesn't have is a fault, as is an angle on
a flat face.

### Turned in the face (`turn`)

On a flat face, `place.turn` (an angle; schema 1.2) turns the item in the
face's plane about its own point, from the face's first axis towards its
second: turned 30 degrees on a `+z` face, what ran along x runs 30 degrees
round from x towards y. None is no turn. Its footprint is its outline
turned: what it covers, its fit on the face, its copies held apart and the
material under it are all read on the turned outline, and a position
measured `to` `edge` is to the turned outline's farthest point along that
axis (its reach is half the size of the box round it there). A pattern's
copies are placed as an unturned item's would be, each turned about its own
point.

What turns: a slot, a rectangular pocket, a rib, a tab, a block, a post and
a line of letters (up the face's second axis turned; they read along their
up across outward, as unturned letters do). A round footprint turns into
itself, so a turn of a hole, a boss, a round pocket or any other kind is a
fault, as is a turn on a round side or with `concentric`.

A turned item's edges are rounded and chamfered as an upright one's are
(edges.md, "A turned item's edges"). A turned block is hollowed as it
stands upright, its walls, floor and inside faces then turned with it
(shell.md). Its far
face and, a box's, its sides take things (below).

### A turned item's far face

The face of a turned block, post, rib or square-ended tab opposite the one
it stands on (its top, or a tab's end), and a turned pocket's floor, face
the way its host's face does; its axes are turned in its plane with it, by
its turn. On a turned face
itself, a turn is the face's and the item's own together: turns in one
plane add. What is placed on such a face is placed along its own axes, `u`
and `v`, from its own edges and centre, and is turned with it: an item
turned there turns by its own turn from the face's first axis, so by both
from the part's. A round item (a hole, a boss, a round pocket, a cylinder)
is the same turned, its own faces turned with it; an item whose outline
isn't round and doesn't turn (an extrusion, a revolution, a region) waits
for a later step there.

Under it is the turned item's own height of material and, where its turned
outline lies wholly on a host with the same material under all of it
(frame.md), the host's too, under all of it: a cut right through goes
through both and comes out where a cut through the host would. Under a
turned pocket's floor is the material under its face less its depth, where
that face has the same material under all of it. Where a turned item stands
partly off its host's face, or on (or is cut into) a face without the same
material under all of it, its far face or floor takes nothing yet. A turned
cut's other faces take nothing yet, nor do a leaning item's but its far
face (below).

### A turned item's faces

A turned block's or post's sides are faces too, each turned with it. Each is named as it is with the item
upright, by the axes of the face it stands on (its length's ends `+` and `-`
the face's first axis, its width's the second), and faces the way that side
faces once the item is turned; under it is the item's own size across it,
and a cut right through it comes out on the side across. The face it is
joined by is no face: placing on it is a fault.

What is placed on such a face is placed along the face's own axes, `u` and
`v` (the part's are a fault there), as it would be on that face with the
item upright, then turned with the item: its positions, patterns, turns and
leans are all the face's own, and what is placed is any item a face of that
item upright takes (a hole, a counterbore, a slot, a pocket, letters, a
boss, a post or a block, turned there too, a cylinder, a tube, a rib, a tab,
an extrusion). What stands on it has its own faces, turned with it: a
boss's far end, a post's far face and sides (turned again where it is
turned there). A turned item's sides take things wherever it stands, as an
upright item's do; a round item on one is the same turned, and what is
placed round its side is placed as round that side upright, then moved with
it. Its edges, and those of
what is on its faces, are rounded and chamfered as an upright one's are
(edges.md, "A turned item's edges").

### Leaning on the face (`tilt`)

On a flat face, a hole, a boss or a post may lean, and so may a block or a
cylinder standing on it: `tilt` (an angle; schema 1.3, and 1.5 for a block
or a cylinder) from square to the face, towards `tilt_towards`, one of the
face's two axes, `+` or `-` (turned with the item where `place.turn` turns
it, so a post or a block leans along its own length or width). Its
**direction** is the face's outward normal turned `tilt` towards that way: a
boss, a post, a block or a cylinder stands out along it, its `height` (a
cylinder's `length`) along it from its point; a hole's way out of its mouth
is along it, so it goes in against it, its `depth` along it from its point.
Its cross-section, square to its direction, is what it would be unleaning: a
disc, or the post's or block's `length` by `width`.

Its **foot** (what it covers on the face, its fit, what it is held apart
from, and what a position `to` `edge` is measured to) is that
cross-section's section by the face's plane: drawn out along the lean by
1 / cos(`tilt`), an ellipse for a round one. A boss's or a post's foot is
where it meets the face; it is joined to the face over it, and what of its
cross-section lies under the face's plane is the face's own material.

Under the face, what leans is measured along its direction, so it leans
only on a face with **the same material under all of it** (`T` deep): a
block's face, a cylinder's end, the side of a box standing on a face. There:

- a hole right through goes on until all of its circle is past the far
  side, `(T + r sin(tilt)) / cos(tilt)` along it, and comes out there
  `T tan(tilt)` from its point, back against the lean;
- a blind hole (or a counterbore) of radius `r` and `depth` `D` stays in
  the material while `D cos(tilt) + r sin(tilt) <= T`: its floor is square
  to its direction;
- a boss or a post reaches back into the face from its foot by its half
  size along the lean times tan(`tilt`), which must be less than `T`.

A lean of 0, or of 90 degrees or more, is a fault, as is a lean without its
`tilt_towards`, a way that isn't one of the face's axes, or a lean round a
side or with `concentric`. Forge leans an item at most 75 degrees, a plain or
counterbored hole (not a countersunk one), and only on such a face, for now:
anything else that leans is CAN'T. A leaning item's far face takes things
(below); its other faces take nothing, and it is not hollowed, for now; a
leaning rod is threaded along its lean
from its far end, clear of its foot (thread.md); its far end's edges and a box's
along its lean are rounded and chamfered as with it upright, not yet where
it meets its face (edges.md, "A leaning item's edges").

### A leaning item's far face

The far face of a leaning boss, post, block or cylinder (its top, or its
far end: `+end`), not turned in its face and not hollowed, takes a hole, a
pocket, a slot or what stands on a face. It is named as with the item
upright, and what goes on it is placed along its own axes, `u` and `v`, as
on it upright, then leaned with it: about the line through the item's point
square to its face's normal and its lean, by its tilt. So its `u` runs
along the lean where the item leans along the face's first axis, tipped
with it.

The material under it is the item's own (frame.md): from each point back
along the item's axis to the face it leans on. That is its height on the
axis, and less on the side it leans towards, by tan(`tilt`) for each
millimetre that way: a blind cut must fit in the least under its mouth. A
cut right through it would come out on the face it leans on, and Forge
says it can't yet (give it a depth); so does one through everything or up
to a face, there, for now. A cut through the next face goes on along its
axis until it comes out all across its mouth, through the face it leans on
and what is under that (sizes.md, "Through the next face"), as on a turned
item's faces.

## On a round side

On a round side, an item is placed by a position along the side's axis and
an angle round it.

- **Along the axis:** as on a flat face, measured from the side's ends:
  `side` `+z` is the end at the larger z. `offset` is from the middle of the
  side; none, or `centred`, is halfway along (none is an assumption).
- **The angle** (`place.angle`) is measured round the axis, from the first
  of its reference axes towards the second:

  | side's axis | 0 degrees | 90 degrees |
  |---|---|---|
  | z | +x | +y |
  | x | +y | +z |
  | y | +z | +x |

  None is 0 degrees, an assumption.
- The item's **point** is on the side's surface at that angle and position.
  Its **direction** is along the radius through the point: outward from a
  rod's or tube's outside, inward towards the axis from a bore or the inside
  of a hollowed cylinder's wall. A hole goes in against that direction; a
  standing feature stands out along it.
- A standing feature round a side has its length running round the side
  (along the third frame axis, the one that is neither the side's axis nor
  its own direction) and its width along the side's axis. It stands at any
  angle: at one where its direction isn't a frame axis (not 0, 90, 180 or
  270 degrees) it is placed as at the frame axis at or below its angle (30
  degrees: as at 0; 200: as at 180), then turned with the side about its
  axis by the rest, its faces, its edges and what is on them turned with
  it. Its faces and its axes are named as at that frame axis (a rib's
  `along` and a tab's `thickness_along` name the axis it runs along there,
  or the side's axis), and what is put on its far face is placed along
  that face's own axes, `u` and `v`, as on a turned item's faces.
- Only holes, bosses, posts, tabs and ribs go on a round side, for now, and
  only one at a place or a `circle` or `arc` of them: no other pattern, and
  nothing `concentric`.

### On a round-ended tab's end

A round-ended tab's far end (tab.md; item 3b's fourth step, no schema
change) is a round side over its half: its axis along the tab's
`thickness_along`, as long as its thickness, its radius half the tab's
width, the half facing the way the tab sticks out. The face is named by
that way (a tab standing on +z: its `+z` end).

- A hole, a boss or a post goes on it as on a round side: by a position
  along its axis and an angle round it, measured as round a side. None is
  its middle through its thickness, and its tip (the middle of its half),
  assumptions.
- All of it stays on the half: no further round from its middle than a
  quarter turn, its reach round it from its point included. Copies go in an
  `arc` (it gives a step), not a `circle`.
- A hole is blind, no deeper than the tab holds under its mouth: on through
  the half-disc and the tab's straight part behind it, until it would come
  out of the tab's side or reach its foot. A hole right through waits, for
  now.
- Only holes, bosses and posts go on it, for now; a turned tab's end takes
  nothing yet.

## On a ball's surface

On a ball's or a dome's curved surface (sphere.md, its `surface` face;
schema 1.6), an item is placed by a **latitude** and an **angle round its
pole**:

- **Its pole** is the way the ball stands: +z for the first body (a dome),
  the way the face it stands on faces for one standing on a face. Its
  **equator** is the circle square to it through the ball's centre: a
  dome's rim, or where a whole ball standing on a face meets it.
- **`place.latitude`** is how far from the equator towards the pole, in
  degrees: 90 is the pole, 0 the equator. None is 90, an assumption.
- **`place.angle`** is how far round the pole, from the first of the
  reference axes towards the second, as round a side whose axis is the
  pole's (about z: from +x towards +y). None is 0, an assumption where it
  matters (not at the pole).
- The item's **point** is on the surface there, its **direction** the way
  out along the ball's radius. A hole goes in against it, its depth from
  its point; a boss or a post stands out along it, its height from its
  point, its foot following the ball's curve. A post's length runs round
  the pole (east), its width along the meridian.
- It is placed as at the pole, then turned about the ball's centre, down to
  its latitude and round to its angle; its faces take nothing, for now. Its
  edges, its joint with the ball and a hole's mouth are rounded or
  chamfered as edges.md, "Round a side, and on a ball's surface or a cone's
  side", says.
- A `circle` or an `arc` of copies goes round the pole at its latitude.
- What it covers must stay on the surface: above a dome's rim, above a
  standing ball's equator (below it is what it stands on). A hole goes right
  through a whole ball standing on nothing only, for now; otherwise it has a
  depth no more than the material under it.
- Only holes, bosses and posts go on a ball's surface, for now, and not on
  a hollowed ball's.

## On a cone's side

On a cone's tapered side (cone.md, its `side` face; item 3b's third step,
no schema change), an item is placed as round a round side: by a position
along the cone's axis and an angle round it.

- **Along the axis** and **the angle** are as on a round side (above): the
  axis is the cone's, measured from its ends; the angle from the first of
  its reference axes towards the second. None is halfway along, and 0
  degrees, assumptions.
- The item's **point** is on the side there. Its **direction** is the
  side's normal: out along the radius through the point, leaned towards the
  cone's narrower end by the cone's half angle (square to the side). A hole
  goes in against it, its depth from its point; a boss or a post stands out
  along it, its height from its point.
- A standing feature's length runs round the cone and its width up its
  slope. It is placed as at the frame axis at or below its angle, standing
  out along the radius there, then leaned with the slope about the line
  through its point round the cone, then turned with the side about its
  axis by the rest; its faces take nothing, for now. Its foot is carried
  into the cone twice as far as the side falls away under its farthest
  reach from its point, there where the cone is narrowest under it (the
  side's curve round it, square to its slope, has that radius over the
  cosine of the half angle), and all of it stays in the cone: measured
  from an end to its edge, its width up the slope counts as far along the
  axis as it reaches there.
- A `circle` or an `arc` of copies goes round the axis at its place along
  it.
- What it covers must stay on the side, short of the cone's ends; it must
  be narrower than the cone where it is; and a hole is blind, no deeper
  than the least material under its mouth (the cone is convex, so that is
  at its rim, where the far side or an end comes first). A hole right
  through a cone's side waits, for now.
- Only holes, bosses and posts go on a cone's side, for now.

## Concentric

`concentric` with an item puts this item's centre on that item's axis, where
the axis passes through the face. That item's axis (the direction it stands
out along, or cuts in along) must be at right angles to the face. With
several copies of either:

- concentric with the item it is on: each copy of the host takes one, on its
  own axis;
- one host copy: one copy on the axis of every copy of the other item;
- one copy of the other item: one copy on each host copy, on that one axis;
- the same number of each: copy n with copy n;
- otherwise it is a fault: the spec must say which goes with which.

`concentric` gives no position along the axes, and no pattern.

## Patterns

A pattern makes copies. Every pattern also takes `each`, how many copies
stand at each of its points: only one, for now. Positions along an axis that
a pattern itself fixes (both axes for `corners`, the `ends` axis for `ends`)
are a fault.

Where the copies go along each axis of the face:

- **centred, offset, or none:** the pattern's **centre** is where the
  position puts it;
- **from an edge** (`side`): a `row`, `grid` or `rectangle` is measured to
  its **nearest copy** along that axis, its centre or its near edge as `to`
  says, as a brief means "the first hole 5 mm from the end"; a `circle` or
  `arc` is measured to the circle's **centre**, and only to its centre.

On a flat face, a pattern's lengths run along the face's axes, named by the
frame axis (`pitch_x` runs along x). Angles are measured on the face from its
first axis towards its second.

### `corners`

One copy at each of the four corners of a rectangular face, centres
`inset_<a>` in from the face's edges along each of its axes `a`: at
(±(half the face's size along its first axis − its inset),
±(half along its second − its inset)) from the face's centre. Only on a
rectangular face.

### `rectangle`

Four copies at the corners of a rectangle `<a>` by `<b>` (the face's axes'
names: `x`, `y`): at (±a/2, ±b/2) from the pattern's centre.

### `ends`

Two copies along `axis`, centres `inset` in from each end of the face along
that axis. Along the other axis they are where the item's position puts
them. Only on a rectangular face.

### `row`

`count` copies in a line along `axis`, `pitch` apart: copy k (from 0) at
(k − (count − 1)/2) × pitch from the pattern's centre.

### `grid`

`count_<a>` × `count_<b>` copies, `pitch_<a>` and `pitch_<b>` apart along
the face's two axes: copy (i, j) at
((i − (count_a − 1)/2) × pitch_a, (j − (count_b − 1)/2) × pitch_b) from the
pattern's centre.

### `circle`

On a flat face: `count` copies equally spaced round a circle of `diameter`
about the pattern's centre, the first at `start` (0 degrees when not given,
an assumption), measured from the face's first axis towards its second;
copy k at start + k × 360/count degrees.

Round a side: `count` copies equally spaced round the side, the first at
`place.angle`. It takes only a count.

### `arc`

As a circle, but copies are `step` degrees apart rather than spread over the
whole turn ("two holes 90 degrees apart"): copy k at start + k × step. Round
a side it takes a count and a step, the first at `place.angle`.

## Copies and the order they are numbered in

Copies are numbered in the order they are made: every copy on the host's
first copy, then every copy on its second, and so on. On one host, a
pattern's copies come in this order:

- `corners`, `rectangle`: (−, −), (−, +), (+, −), (+, +), by the face's
  first axis and then its second;
- `ends`: the minus end, then the plus end;
- `row`: from the minus end of the row;
- `grid`: along the second axis for each step along the first,
  starting at the minus corner;
- `circle`, `arc`: by angle, from the first.

## Counts

An item's `count` is how many there are in the whole part. It says nothing
about where they are: it must equal the number of copies the placement
makes, or the draft is turned back (or, when the brief itself gives a count
and a pattern that disagree, you are asked).

## When it doesn't fit

Nothing is quietly moved to make it fit. Each of these is a question for
you, a fault the spec writer fixes, or a CAN'T, with the numbers that cause
it:

- a cut or a standing feature that doesn't lie wholly on its face (on a
  ring, a cut may instead cover the whole central opening: a recess round
  the bore's end, as a counterbore is);
- a cut whose outline touches the face's edge at a point from inside: a
  hole against a plate's side, or a disc's rim, or a ring's bore. The
  material between them is pinched to nothing there, an edge on which the
  part meets itself, which no kernel builds soundly. A straight side lying
  along the edge only opens the cut there (a rebate, a slot along the edge,
  its round ends meeting the edge where its side does), and is no pinch;
- a cut right through its body that comes out under something standing on
  the face across from it: through is through the body it is cut into, so
  what stands over its far mouth closes it (a hole drilled up through a
  plate under a boss ends in the boss). Drill it from the top of what
  stands there instead, through both, or give its depth. Inside a tube's
  bore it comes out into the bore, which is open;
- a body that doesn't meet the face it stands on;
- copies of a cut or a standing feature that overlap or land on each other
  (copies of a body may overlap: they join; holes round a side may meet at
  its axis, as cross-drilled holes do);
- a cut that runs off its face, or a blind one deeper than the material
  under it;
- something standing wholly over a cut's mouth, or a cut that takes away all
  that something stands on: nothing would hold it up.
