# text

Status: **draft, for your approval.**

Letters engraved into a face, or embossed on it. Text is listed with the
cuts, as engraving is; embossed letters add material.

## The shape

The letters of `text`, in Forge's one pinned font, on one line, as
outlines in the face's plane.

- **The font:** DejaVu Sans Bold, version 2.37, the file
  `packages/forge_fonts/fonts/DejaVuSans-Bold.ttf` (SHA-256
  `5c1247acef7f2b8522a31742c76d6adcb5569bacc0be7ceaa4dc39dd252ce895`),
  shipped with Forge under its own licence. Each letter is the font's glyph
  for it, set one after another by its advance width, with no kerning and no
  ligatures. A letter the font lacks, a line break or a tab can't be set: the
  run ends UNABLE, or the draft is turned back. Its metrics are in
  `packages/forge_spec/font.py`, written from the file by
  `scripts/font_metrics.py`.
- **Size:** a capital letter is `height` tall: the font is scaled so that
  its letter H is `height` tall.
- **Which way they read:** they read the right way round seen from outside
  the face. Up is the face's second axis (for a `+z` or `-z` face, +y; for a
  side face, +z), and they run from left to right along the direction
  "up × outward" (on a `+z` face, +x; on a `-z` face, -x; on a `-y` face,
  +x).
- **Where:** the line's box is centred where `place` puts it. The box runs
  along the line from where the first letter starts to where the last
  letter's advance ends (spaces count), and across it from the baseline to
  the top of a capital.

Engraved, the outlines go in from the face to `depth`, with flat floors, and
take away every point of the part inside them. Embossed, they stand out of
the face by `depth`, with flat tops. Text goes on flat faces only, for now.

## Fields

### `on`

The face the letters are on ([frame.md](frame.md)).

### `place`

Where on the face ([place.md](place.md)).

### `text`

The letters, exactly as the brief gives them, spaces included.

### `height`

The height of a capital letter.

### `depth`

How deep the letters are cut, or how high they stand.

### `mode`

- `engrave`: cut into the face.
- `emboss`: standing out of the face.

## Faces

None: nothing stands on or is cut into the letters.

## Edges

None.

## Checked as

Exact: Forge computes the letters' outlines itself, from the font file it
pins.
