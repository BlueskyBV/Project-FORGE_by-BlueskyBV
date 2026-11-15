# region

Status: **draft, for your approval.**

A shape the brief describes only by what it is for, designed later within
an envelope: the one kind the construction agent designs (stage 5).

## The shape

Not fixed by the spec. What is fixed is its **envelope**, a box standing on
the face where `place` puts it: `length` along the face's first axis,
`width` along its second, and `height` out of the face. The shape designed
for it:

- lies wholly within the envelope;
- is joined to the face it stands on;
- fills the envelope to the extent its purpose needs: how much is stated
  as a fill rule, so a small blob fails (the fill rule is set in stage 5,
  with the construction agent; until then a region is drafted and confirmed,
  not built);
- never takes the place of a fixed item: where they meet, the fixed item's
  shape wins (a region never fills a hole);
- has no wall thinner than `min_wall`.

## Fields

### `on`

The face it stands on ([frame.md](frame.md)).

### `place`

Where on the face ([place.md](place.md)).

### `length`

The envelope's size along the face's first axis.

### `width`

The envelope's size along the face's second axis.

### `height`

The envelope's size out of the face.

### `min_wall`

No wall of the shape is thinner than this.

### `describe`

What the shape is for, in the brief's words: what it is designed to.

## Faces

None: nothing stands on or is cut into a region, for now.

## Edges

None.

## Checked as

Constrained: its envelope, how much of it is filled, its thinnest wall,
and where it joins are checked; its shape is not. The ending says so.
