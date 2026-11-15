# What every field means

Status: **draft, for your approval.** Nothing here is final until you have
read it and said so.

These pages say, in words, what shape every field of every item kind makes.
Three programs are written from them, each on its own:

- the **compiler** (stage 4), which turns a confirmed spec into the steps
  that build the part;
- the **oracle** (stage 2), which works out from the spec alone where every
  surface of the part must be, and checks the built part against it;
- the **random-spec generator** (stage 2), which makes specs with its own
  model of their shape, so the whole pipeline can be graded against a third
  opinion.

The three share no code. What they share is this text, which is why it is
written to be read and checked by a person (plan, section 4.6). When a
program and this text disagree, the program is wrong.

A test (`tests/test_v2_definitions.py`) fails if any kind, field, choice,
face, edge set, pattern or fit in the schema has no definition here, so the
schema can't grow a field nobody has defined.

## The pages

| Page | What it covers |
|---|---|
| [frame.md](frame.md) | The frame, faces, standing on and cutting into a face, the order the part is made in, and the material under a face |
| [place.md](place.md) | Where an item goes on a face: positions, round sides, concentric items, patterns, copies and counts |
| [sizes.md](sizes.md) | Units, nominal sizes, tolerances, and sizes from standard tables |
| [edges.md](edges.md) | What rounding and chamfering an edge does, and which edges each edge set names |
| One page per item kind | The kind's shape, every field, its faces, its edge sets and its choices |

Bodies: [block](block.md), [cylinder](cylinder.md), [tube](tube.md),
[sphere](sphere.md), [cone](cone.md), [extrusion](extrusion.md),
[revolution](revolution.md).

Cuts: [hole](hole.md), [slot](slot.md), [pocket](pocket.md), [text](text.md).

Standing features: [boss](boss.md), [post](post.md), [tab](tab.md),
[rib](rib.md).

Changes to other items: [fillet](fillet.md), [chamfer](chamfer.md),
[shell](shell.md), [thread](thread.md).

Designed later: [region](region.md).

## How each kind's page is laid out

- **The shape:** the set of points the item adds to the part or takes away,
  and where it is.
- **Fields:** one section per field, with each choice of a choice field as
  its own bullet.
- **Faces:** the faces other items may stand on or cut into, by name.
- **Edges:** the edge sets a fillet or chamfer may name on it.
- **Checked as:** its verification class (plan, section 4.5): *exact* where
  every point of its surface is known, *bounded* where the surface lies
  between known limits, *constrained* where only its constraints are known.

Sizes are in millimetres and angles in degrees unless a page says
otherwise.
