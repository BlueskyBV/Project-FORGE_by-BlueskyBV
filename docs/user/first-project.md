# Your first project

A walkthrough of the golden clevis: what the document says, what Forge does with
it, and how to read the result.

## 1. Look at the design

```console
$ forge inspect examples/clevis/clevis.forgeir.json
```

You get three things.

**Parameters, in resolution order**, with free and derived distinguished:

```
  free    base_length                          60 mm
  free    ear_thickness                         6 mm
  free    ear_gap                              12 mm
  derived ear_offset                            9 mm  = (ear_gap + ear_thickness) / 2
  derived outer_width                          24 mm  = ear_gap + 2 * ear_thickness
```

A derived parameter shows its expression. `outer_width` is not a number someone
typed; it is a consequence, and it stays a consequence when `ear_thickness`
changes.

**The feature graph**, in dependency order — a graph, not a timeline, so
independent features are genuinely independent.

**Published geometry**, with a lineage token and a status for each:

```
  pivot.bore     cylindrical_face   live     03fa8305a693   50% of the named surface lies on the boundary
  base.z_min     planar_face        live     100% of the named surface lies on the boundary
  ear_left.z_min planar_face        buried   0% remains on the boundary; 100% is now interior
```

`ear_left.z_min` is the underside of an ear, which is supposed to disappear into
the base. Forge reports it as buried rather than pretending it is still
selectable. `pivot.bore` at 50% is the bore through both ears, half of which is
the 12 mm gap between them.

## 2. Verify it

```console
$ forge verify examples/clevis/clevis.forgeir.json \
      --load 500N --arm 35mm --load-assumption ASM_DESIGN_LOAD
```

Every gate passes. The verdict is `BLOCKED`.

```
Not a release candidate because:
  - assumption ASM_DESIGN_LOAD has not been accepted
  - assumption ASM_MATERIAL has not been accepted
```

**This is the most important output in the system.** The design satisfies every
requirement it was given. It was checked against a 500 N load that nobody
accepted and a material grade nobody confirmed. Both are marked `risk: high` in
the document, and `ASM_DESIGN_LOAD` is marked irreversible, so neither can be
auto-accepted.

Reporting this as a pass with a footnote is how an unexamined assumption reaches
a released design. Set `"approved": true` on both assumptions — deliberately,
having thought about them — and the same run returns `PASS`.

## 3. Read the measurements

```
volume                : 12820.3 ± 387.7 mm^3
mass                  : 34.63 ± 1.39 g
minimum_wall          : 5.592 ± 0.007 mm
bounding_box_size     : 59.80 ± 0.25 mm, 23.92 ± 0.10 mm, 27.91 ± 0.11 mm
relative_uncertainty  : 0.055
```

Every one is an interval, and the intervals are *guarantees*: the true volume
lies inside `[12432.6, 13208.0] mm³`. The 5.5% is the residual discretisation
uncertainty at the default refinement depth, reported rather than hidden.

Raise the depth to narrow it:

```console
$ forge verify examples/clevis/clevis.forgeir.json --depth 11
```

This matters when a gate comes back `INCONCLUSIVE`. That status does not mean
the design is wrong; it means the *measurement* could not decide the question,
and refining it is the correct response.

## 4. Change something

```console
$ forge verify examples/clevis/clevis.forgeir.json --set ear_thickness=8mm
```

Two things happen, and both are the point.

The geometry changes — mass rises, the ears thicken. And **every semantic
reference still resolves**: `pivot.bore` has the same lineage token it had
before, because its identity comes from the feature graph and the feature graph
did not change shape. No face matching, no tolerance, no heuristic.

Now try breaking it properly:

```console
$ forge verify examples/clevis/clevis.forgeir.json --set ear_gap=9mm
```

```
FAIL  Clear internal spacing between the ears must be 12 mm ...  = 9 mm  (required == 12 mm)
```

Exit code 1. Compare with the `BLOCKED` run, which exits 2. A CI pipeline can
tell "this failed" from "this could not be checked", which it must.

## 5. See what a rebuild costs

```console
$ forge sweep examples/clevis/clevis.forgeir.json \
      --parameter root_blend --start 1mm --stop 5mm --steps 9
```

```
       value   built  reused       ms  part hash
    1.000 mm       3       7     12.1  a7c1...
    1.500 mm       3       7     11.8  4f92...
    ...
features built 34 of 90 a full rebuild would need (62% avoided)
```

`root_blend` only feeds the blended union and what follows it, so the base plate
and both ears are reused every time. Sweep `ear_thickness` instead and you get
17%, because that parameter feeds nearly everything. The saving depends on where
in the graph you edit — and it is what makes an optimisation campaign affordable.

## 6. Export

```console
$ forge export examples/clevis/clevis.forgeir.json -o clevis.stl --resolution 160
wrote clevis.stl  (80296 faces, watertight=True)
```

STL carries no units and no design intent. It is for printing, not for exchange.
STEP export needs the B-Rep backend, which is not built yet — the capability
matrix says so rather than the tool failing mysteriously.

## Writing your own document

Start from `examples/clevis/clevis.forgeir.json` and change it. The decoder is
strict on purpose, and its errors carry a JSON Pointer to the exact node:

```
[IR1003_UNKNOWN_FIELD] /components/0: unknown field(s); did you mean one of the
allowed names? (unknown=['colour'], allowed=['description', 'features', 'id', ...])
```

Things that will stop you, each deliberately:

- A bare number where a length belongs. Write `{"magnitude": 6.0, "unit": "mm"}`.
- A material family name. `"aluminium"` raises and lists the specific grades.
- An interface naming geometry no feature publishes.
- A parameter outside its own declared bounds.
- An equality requirement with no tolerance.

The [language reference](../architecture/forgeir.md) has the full schema.
