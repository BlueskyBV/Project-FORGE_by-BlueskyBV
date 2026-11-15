# thread

Status: **draft, for your approval.**

An outside thread on a round rod or boss: a change to another item.

## The shape

The rod's round side is cut, over the threaded length, into an ISO metric
thread (ISO 68-1, 60 degrees):

- its major (outside) diameter is the rod's diameter, which should be the
  designation's nominal size (an M8 thread on an 8 mm rod);
- its pitch is the designation's: the coarse pitch from the table for a
  plain size (M8 is 1.25 mm), or the pitch it names (M8x1);
- the thread's depth, from the major diameter to the minor, is the basic
  profile's: 5/8 of the height of the sharp 60 degree triangle
  (0.541 × pitch);
- it winds right-handed or left-handed, as `hand` says;
- it runs `length` from the free end (the +end of a rod or boss), or along
  the whole length when no length is given.

## Fields

### `of`

The cylinder or boss to thread.

### `designation`

The thread, such as M8, or M8x1 for a fine pitch.

### `length`

The threaded length, from the free end. None: the whole length.

### `hand`

- `right`: right-handed, tightened clockwise.
- `left`: left-handed.

## Faces

None.

## Edges

None.

## Checked as

Bounded: the threaded surface lies between the minor and major cylinders
over the threaded length (where the thread starts round the axis is left
to the build). Then exact: the built thread is held to the basic profile,
wound at its pitch and hand, at the turn it starts at; its pitch, hand,
length and diameters are measured.
