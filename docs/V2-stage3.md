# Forge V2, stage 3: the exact kernel

Status: design, revision 2, 23 October 2026. Revision 1 was reviewed
adversarially; section 1.1 says what the review changed.
Companion to [V2-plan.md](V2-plan.md) (sections 4.3, 4.4, 8) and
[V2-architecture.md](V2-architecture.md) (sections 2, 4.2, 4.4, 6, 8, 9).
Where this page is more exact than those, this page holds; where it
differs, it says why (section 2).

---

## 1. What stage 3 delivers

The plan's row for stage 3:

> `forge_occ` with after-checks and error flags; references by query; the
> copying cache; exact measurement; STEP, STL and 3MF export with re-open
> checks; second-kernel agreement; install proven on the laptop's Windows
> and in Docker.
>
> **Exit test:** every V1 golden and zoo shape rebuilds in both kernels, and
> they agree where the capability table says they can. STEP opens in FreeCAD
> and Fusion. A two-part document with a mate round-trips.

**The architecture, in one paragraph.** Forge V2 is a hybrid. OpenCascade
(`forge_occ`) builds every part exactly: true arcs, cylinders, fillets,
sweeps and lofts, and the STEP file a CAD program opens. Forge's own engine,
V1's implicit kernel (`forge_geom` and `forge_kernel`), builds the same
construction a second time, independently, wherever the capability table
says it can. The two must agree, which catches OpenCascade's bugs and
Forge's translation bugs. The implicit kernel also builds what OpenCascade
can't, the organic regions (smooth blends, lattices, infill); a part with
such a region is meshed, joined with manifold3d and shipped as STL and 3MF
only. That join arrives with the first such region, in stage 5 (2.7).
Neither kernel judges the part: the checks of stage 2 do, from the spec,
through a `GeometryView`.

What "done" means, made exact:

| Deliverable | Done when |
|---|---|
| `forge_occ` builds every ForgeIR kind | All 32 V1 kinds and the two new ones of this stage (`fillet`, `chamfer`), each with build tests, after-check tests and agreement tests (section 7) |
| After-checks and error flags | Every step validated and after-checked (section 8); every boolean's error and warning flags read; each trap of section 4 reproduced in a test and caught |
| References by query | ForgeIR v2 references resolve through history, with match conditions; a match outside its condition is an error (section 9) |
| The copying cache | Keyed as the architecture says; every hit a fresh copy; proved by tests that change a hit (section 10) |
| Exact measurement | `BrepView` answers the whole `GeometryView` protocol exactly or to a stated tolerance, and the stage-2 check tests run on it (section 11) |
| Export with re-open checks | STEP (AP242, mm, names, assemblies), STL and 3MF, each re-opened and compared with the built part before it is handed over (section 12) |
| Second-kernel agreement | `ImplicitView`; an agreement table per operation; the agreement test (section 13) |
| Install proven | The laptop's Linux VM and a Docker image here pass the exact-kernel suite; on Windows, one script runs the same suite (section 15) |
| Exit test | Section 16 |

### 1.1 What the review changed

| Finding | This revision |
|---|---|
| Six recorded curved plates have holes in the bend zone, which revision 1 refused; all use `hold: middle`, which it got wrong | Bend zones that are not prisms are bent by V1's own map, each face refitted to 1e-6 mm (7.3); `hold` turns the whole part back as V1 does |
| `BRepExtrema` from a vertex gives 0 for every point inside a solid, so the agreement test could not see material V1 lacks | Distance is measured to the solid's faces (11) |
| V1's shell and offset of a union leave a plug where the true offset is hollow, outside the zone revision 1 gave | Bounded only on convex primitives; not applicable through the whole input otherwise (13.2) |
| A box with every edge chamfered: V1's corners differ from OpenCascade's chamfer by up to 0.15 mm | Every box edge option is built by V1's own construction (7.2) |
| A coil's ends: V1 squares them to its first and last chord, 5° off the wire | Ends square to the wire; a stated zone at each end (13.2) |
| V1's revolve ignores where the profile was sketched | Built as V1 reads it: radius and height from the axis, the part at positive radius (7.2) |
| Bend and hole parameters depend on V1's envelopes; V1 puts a through hole's counterbore at the first material along the axis; the counterbore tolerance was wrong | V1's envelopes are read from V1 (7.4); V1's counterbore rule; τ corrected (13.2) |
| Tolerance and zones by step box don't follow later moves and spread over the whole part | Zones and tolerances are carried by face names, so they follow every move, copy and bend, and stay local (13.3) |
| Fillets fail at V1's legal limits (a lug's full round, a cone with equal radii) | V1's constructions for the box options; degenerate primitives handled; limits tested (7.2) |
| A drafted extrusion tapers from its low end in V1, not from the sketch | Built from the low end, with V1's sign, in every mode (7.2) |
| Instance placement order was reversed | Rotate about `rotate_origin`, then translate, as V1's `transform` (6.1) |
| After-checks: a fillet bound wrong for sharp dihedrals; mirror and pipe checks that fail valid parts; "every after-check failure is OpenCascade's fault" | Corrected bounds and checks; the message says the operation failed to do what it should, not whose fault (8) |
| A cut that drops a lump would pass; a fillet running on along tangent edges unnoticed | Lower volume bound for cuts; tangent chains expanded and recorded before the count is checked (8, 9) |
| `BRepGProp`'s error estimate is not an interval | Volumes: exact formulas where they exist; elsewhere an interval padded to a tested bound (11) |
| A ruled loft is not V1's morph, and nothing checked lofts | Ruled lofts (the CAD meaning), with V1's distance from them computed per loft and stated as its zone (13.2) |
| Junction edges after merging faces include a column's outer edges | Junctions taken before merging, between faces each from one operand and meeting at a crease (9.3) |
| Names: bend faces, shell inner faces, copies, the `full_circle` example | Defined (9.2); V1 names mean the first copy; the example corrected (6.2) |
| Fillet and chamfer steps had no agreement | Down-converted to nothing, with the rounded edges' reach as a zone (13.2) |
| The converter dropped V1's document fields | v2 carries every V1 field (6.1) |
| Mixed parts are not in the stage-3 row | Deferred to stage 5, with the first implicit-only region (2.7) |
| Windows: `forge doctor` alone is weaker than the plan | A script runs the exact-kernel suite on Windows (15) |
| Shared code weakens independence | `forge_occ` writes its own profiles and constructions; what is shared is listed (3) |

## 2. Decisions, and where this page differs from the plan

**2.1 `forge_occ` calls OpenCascade directly, through OCP, not through
build123d.** The plan (4.4) says "OpenCascade, through build123d 0.13". This
stage uses the same OCP bindings build123d itself uses, and not build123d:

- Two of the plan's four traps are build123d's: it never reads the boolean
  error and warning flags, and it gives no operation history. `forge_occ`
  must reach under it for both, and for the fuzzy value and validation, so
  on the trusted path build123d would add nothing but its dependencies
  (sympy, scipy, scikit-learn, ipython, ezdxf, requests and more).
- build123d 0.13 requires Python 3.11 and OpenCascade 8.0. Forge's verified
  floor is Python 3.10, and the laptop's test VM runs 3.10.
- build123d stays the language of the stage-5 escape hatch, inside its
  Docker image, where its convenience is worth having and its solid comes
  back as a file parsed in a separate process.

**2.2 The pin: `cadquery-ocp-novtk==7.9.3.1.1` (OpenCascade 7.9.3) and
`lib3mf==2.5.0`.** OCP 7.9.3.1.1 has wheels for CPython 3.10 to 3.14 on
Windows, Linux (x86-64 and ARM) and macOS; OCP 8.0 starts at 3.11. Both are
installed by the optional extra `forge[exact]`. The kernel's identity (the
cache key, every record) carries the OpenCascade version, and `forge_occ`
refuses to run on any other (section 15).

**2.3 ForgeIR v2 is defined here.** The architecture says "components,
instances and mates are kept from V1". V1's document has components and
interfaces, but no instances and no mates. The exit test's "two-part
document with a mate" needs both, and references by query need the v2
reference format, so ForgeIR v2 (section 6) is a stage-3 deliverable. Stage
4's compiler writes it; stage 8 solves mates rather than checking them.

**2.4 The implicit kernel's meaning is the reference for V1's kinds.** V1's
documents mean what V1's implicit kernel builds, parameter for parameter,
including V1's frames, defaults and edge cases. Two exceptions, each
listed in the agreement table (13.2) with its tolerance or zone:

- where V1 drew a curve as straight segments (a sketch's rounded corners, a
  gear's involute, a coil's helix, a bent path's arcs), `forge_occ` builds
  the true curve;
- where V1's shape is an artefact of implicit modelling rather than of the
  design (a shell of a union that leaves a plug, a round-union swelling a
  flush face, a coil's tilted ends, a loft morphed by distance fields, an
  outward draft rounding corners), `forge_occ` builds the CAD meaning.

**2.5 FreeCAD here, Fusion with you.** The STEP check runs FreeCAD 0.19
(Ubuntu 22.04's build, with its own OpenCascade 7.5) in a chroot in the
cloud workspace, on every exit-test file. Probing showed it opens
`forge_occ`'s AP242 files: valid, one solid, the exact volume. Fusion can't
run here; opening the exit-test files in Fusion is your check (section 17).

**2.6 Docker here is built from Ubuntu's own archive.** This workspace's
network refuses every container registry, so the base image is made from
Ubuntu 24.04's archive (`debootstrap`), which it does reach. The
Dockerfile takes the base as a build argument; the default stays
`python:3.12-slim` (section 15).

**2.7 Parts with implicit regions move to stage 5.** No operation of V1 or
of this stage needs the implicit kernel to build a region `forge_occ`
can't: every V1 kind is built exactly (section 7). The first such region is
the freeform region (stage 5), then infill and lattices (stage 6). The join
(the exact part meshed, the region meshed, joined with manifold3d, STL and
3MF only) is built with the first of them, against a real region rather
than an invented one, and `manifold3d` joins the `exact` extra then.

## 3. Where it sits

```
ForgeIR v2 document ──► forge_occ.build ──► BuildResult (solid, names, traces)
        │                     │  each step: build ─► validate ─► after-check ─► name
        │                     ├──► BrepView ──────────────► the checks (stage 2)
        │                     └──► export ─► STEP / STL / 3MF ─► re-opened, compared
        └─(down-converted)─► forge_kernel ──► ImplicitView ─► agreement with BrepView
```

- `forge_occ` is layer L1. It imports OCP and lib3mf, and from L0:
  `forge_ir` (the document), `forge_kernel` (for the three things in the
  table below), `forge_checks` (the view types and the NumPy mesh view, for
  re-opening meshes). Nothing in L0 imports it.
- `forge_checks` still never imports `forge_occ` or `forge_kernel`: the
  checks see a `BrepView` only through the `ViewProxy` (R2).
- New in L0: `forge_ir/v2.py` (the format), `forge_kernel/view.py`
  (`ImplicitView`), `forge_kernel/agreement.py` (how the implicit kernel
  holds each operation), and two additive public functions in
  `forge_kernel/compiler.py` (below).

**What the two kernels share**, so what agreement can't catch (added to
the architecture's section 6 table):

| Shared | Why | What catches a fault in it instead |
|---|---|---|
| Parameter resolution (`resolve_feature_parameters`, made public) | Both kernels must read the same document the same way | The checks, from the spec; V1's own tests |
| V1's envelopes, for the parameters V1 defines by them (a bend's face and thickness when not given, a hole's margins) (`compile_products`, new) | The parameter's meaning is V1's envelope | The checks |
| The down-conversion of v2 steps to V1 features | The implicit kernel builds V1 features | Its round-trip test (6.1) |

Everything else `forge_occ` writes itself, from V1's builders read as
definitions: its own profiles, its own constructions. It does not import
`forge_geom`'s outline functions.

## 4. What probing OpenCascade 7.9.3 found

Every trap the plan lists was reproduced on the pinned version before
anything was designed round it, and each has a test in stage 3.

| Found | What `forge_occ` does |
|---|---|
| `BRepAlgoAPI_Cut` and friends have no `HasErrors` in the bindings (their error-reporting base class is missing from the binding) | Booleans run through `BOPAlgo_PaveFiller` and `BOPAlgo_BOP`, whose flags and reports are bound; errors fail the step, warnings are read and each kind is either allowed by name or fails it |
| An inward shell thicker than the part "succeeds": done, valid, the same 4000 mm³ box, 6 faces | The shell is built as offset-and-cut, never `MakeThickSolid` on its own word, and after-checked: volume, a new void, and the wall measured (8.2) |
| A fillet of 9.9 mm on a 10 mm tall box is "done" and invalid, and larger than the box | Every step is validated (`BRepCheck_Analyzer`) and every fillet after-checked |
| A mesh made at 0.01 mm stays when 1 mm is asked; `BRepTools.Clean` clears it | Exports mesh a fresh copy (the copy carries no mesh) at the export tolerance, never the built solid |
| Booleans may change their arguments' tolerances in place | `SetNonDestructive(True)` on every boolean; and the cache hands out copies |
| Two solids that don't touch, fused, give a compound of two solids and no warning | The step records its solid count, and the trace shows it |
| A cut whose tool misses the body: no error, no warning, volume unchanged | Recorded as "removed nothing" on the step's trace, for the checks and the agent; not a kernel fault |
| Touching boxes fused give 10 faces where 6 are meant | `ShapeUpgrade_UnifySameDomain` after booleans, its history merged into the names |
| A fused junction has no "section edges" when the faces touch flat | The junction is found from history (9.3) |
| `BRepExtrema_DistShapeShape` from a point inside a solid gives 0 | Distances are measured to the faces (11) |
| `BRepGProp`'s error estimate understates its error by up to 10⁵ | Volumes as in 11 |
| `shape == other` compares Python objects, not shapes | Shapes are compared only with `IsSame` and indexed only through `TopTools` maps |
| Every failure arrives as an exception of the bindings' own: each of OpenCascade's exception classes is a Python class of its own (`Standard_DomainError`, `StdFail_NotDone`, ...), none a subclass of `Standard_Failure` (found by a test: a cone of equal radii raised past a handler for `Standard_Failure` alone) | Any exception the OCP bindings define is caught at each step's boundary (`occt.boundary`, and round every step's builder and checks) and turned into an error naming the component, step and operation |
| The mesher can leave a triangle of a fitted B-spline face several times its deflection from the surface, however fine it is asked to mesh (a bent plate: 0.0078 mm at 0.0025, and at 0.0008) | Every mesh is measured, and each triangle measured too far is split, its new points on the surface (12) |
| `BRepClass3d_SolidClassifier` is wrong for about 0.5% of points 0.006 mm off a fitted B-spline face, and takes 70 ms a point on a coil | Classification asks it last (11) |
| The offset by joins refuses a stack of lofts whose faces meet partly tangent at the joints (`BRepOffset_MixedConnectivity`) | The simple offset is tried, and its wall measured: where it isn't at the thickness, the shell is refused (16) |
| A face round a seam on a surface that runs on past the seam (a bent plate's bore, its surface fitted a little beyond its outline) reads back from STEP with no area: the reader, finding the seam's place on the surface again, finds one of its two curves twice | A face that closes on itself is fitted exactly round its period, its seam on the new surface's borders (7.3) |
| FreeCAD 0.19 (on OpenCascade 7.5) reads a face whose outline crosses its surface's seam wrong: three fused balls came back one ball and two solids, a dumbbell a third short | STEP is written with each closed face split in two (12) |
| The STEP writer prints statistics to standard output | The messenger's printers are set to report failures only |
| STEP settings are process-wide (`Interface_Static`) | Set under a lock immediately before each write |
| STEP files in inches read back in mm | Reading always yields mm; the written file is checked to say millimetres |
| The XCAF writer names an unnamed instance `=>[0:1:1:2]` | Every assembly node and instance is named |
| `MakeCone` refuses equal radii; `MakeFillet` refuses a full round | The constructions of 7.2 never ask for either |

Speeds measured on this workspace (single thread): classification 38,000
points/s, ray casts 99,000/s, exact distances 10,000/s, a 1,000-triangle
tessellation extracted in 4 ms. A helical coil, a ruled loft, a fused and
filleted boss, an offset with arcs and a drafted prism all build valid,
with exact volumes where a formula exists.

## 5. The packages

| `forge_occ` (L1) | What it holds |
|---|---|
| `occt.py` | The one place OCP is imported from: the version pin, the quiet messenger, shape maps, iteration helpers, the `Standard_Failure` boundary |
| `errors.py` | `OccError` and its kinds, each naming component, step, operation and pointer |
| `geom.py` | Frames, points, directions and rigid motions between NumPy and OpenCascade |
| `profiles.py` | 2D outlines as exact wires and faces in a frame: rectangles, circles, slots, polygons, sketches (lines, arcs, closed Catmull-Rom splines), gears |
| `ops/` | One module per family: `primitives`, `sweeps` (extrude, revolve, sweep, pipe, coil, loft), `booleans`, `holes`, `modifiers` (shell, offset, fillet, chamfer), `arrays` (patterns, mirror, transform), `bend`, `warp` (V1's bend map applied to faces, 7.3) |
| `aftercheck.py` | What every step must satisfy, and what each operation must do (section 8) |
| `names.py` | Face names, carried through every operation's history (section 9) |
| `refs.py` | References by query: resolving, match conditions, errors (section 9) |
| `cache.py` | The copying cache (section 10) |
| `measure.py` | Exact mass properties, bounds, face and edge facts, distances |
| `view.py` | `BrepView` (section 11) |
| `export.py` | STEP, STL, 3MF writers and their re-open checks (section 12) |
| `step_view.py` | `StepFileView`: a STEP file read back as a view, with its assembly (section 12) |
| `agreement.py` | The second-kernel agreement test (section 13) |
| `backend.py` | `OccBackend`: build, view, export (section 7) |
| `doctor.py` | `forge doctor` (section 15) |

| Elsewhere (L0) | |
|---|---|
| `forge_ir/v2.py` | ForgeIR v2: the document, steps, references, instances, mates; the converter both ways; the generated JSON schema (section 6) |
| `forge_kernel/view.py` | `ImplicitView` (13.1) |
| `forge_kernel/agreement.py` | How the implicit kernel holds each operation: bounded (with its tolerance) or not applicable (with its zone) (13.2) |
| `forge_kernel/compiler.py` | Additive: `resolve_feature_parameters` (the existing private resolver, public) and `compile_products` (every feature's product, unvalidated) |

The parametric-script export the architecture lists under `forge_occ`
(`script_export.py`) belongs to stage 6, whose exit test it is; `mixed.py`
to stage 5 (2.7).

## 6. ForgeIR v2

ForgeIR v2 is the construction: steps, not meaning. It keeps everything V1
has and adds three things: steps that say which spec items they build,
references that are queries, and instances and mates.

### 6.1 The document

```json
{
  "schema_version": "2.0.0",
  "document_id": "...", "project_id": "...", "revision": 1, "name": "clevis and pin",
  "units": {"length": "mm", "angle": "deg", "mass": "g"},
  "components": [
    {
      "id": "clevis", "name": "Clevis", "material": "PLA",
      "parameters": [ "...exactly V1's parameter graph..." ],
      "steps": [
        {"id": "s1", "op": "box", "role": "base", "for_items": ["body"],
         "params": {"size": {"value": [40, 20, 8], "unit": "mm"}, "centered": true}},
        {"id": "s2", "op": "hole", "inputs": ["s1"], "role": "pivot", "for_items": ["pin_hole"],
         "params": {"diameter": {"magnitude": 8.2, "unit": "mm"}, "...": "..."}},
        {"id": "s3", "op": "fillet", "inputs": ["s2"], "for_items": ["outer_edges"],
         "params": {"radius": {"magnitude": 2, "unit": "mm"},
                    "edges": {"of": {"created_by": "s1", "role": "z_max"},
                              "match": {"count": [4, 4]}}}}
      ],
      "interfaces": [{"id": "pivot_bore", "type": "bore", "geometry": "pivot.bore"}]
    }
  ],
  "instances": [
    {"id": "clevis_1", "component": "clevis"},
    {"id": "pin_1", "component": "pin",
     "at": {"rotate_axis": [1, 0, 0], "rotate_angle": {"magnitude": 90, "unit": "deg"},
            "translate": {"value": [0, 0, 4], "unit": "mm"}}}
  ],
  "mates": [
    {"id": "pin_in_bore", "kind": "coaxial",
     "a": {"instance": "pin_1", "interface": "shaft"},
     "b": {"instance": "clevis_1", "interface": "pivot_bore"}}
  ]
}
```

- **Every V1 document field is kept** (identity, revision, units including
  time, force and stress, requirements, assumptions, provenance, risk
  class, parent revision, description), with V1's meaning.
- **Steps** are V1 features under their v2 names: `op` is V1's `kind`,
  `params` V1's `parameters`, with V1's value forms and units, decoded by
  V1's decoders. `role` keeps its V1 meaning (the prefix of the names a
  step publishes). `for_items` lists the spec items the step builds, so a
  failure names a spec item; it is empty in documents converted from V1.
  Step ids are Forge's own; in a converted document they are V1's feature
  ids, which are unique in their component.
- **The operation set** is V1's 32 kinds with V1's parameters and meaning,
  plus `fillet` and `chamfer` on edge references (6.2). The architecture's
  other new operations (`thread`, `text`, `draft`, `countersink`,
  `freeform`, `escape`) arrive with the stages that need them; each comes
  with its builder, its after-check and its agreement entry, or the
  decoder rejects it.
- **Instances** place components: `at` is a rigid motion with V1's
  `transform` parameters and meaning (rotate about `rotate_origin`, then
  translate). A document with no instances means one instance of each
  component where it was built, which is what every V1 document means.
- **Mates** relate two instances' interfaces. Stage 3 checks them on the
  built and the re-opened assembly; it does not solve them (stage 8 does).
  Kinds: `coaxial` (two axis-bearing interfaces share their axis),
  `contact` (two planar interfaces coplanar and facing, with an optional
  `gap`), `fixed` (the instances' relative placement is as written).
- **Validation** keeps all of V1's graph rules (one starting solid, no
  dangling input, no hole drilled twice, no boolean that undoes itself, no
  colliding names) and adds: a reference names steps among its step's
  ancestors; a mate's interfaces exist and suit its kind; instance and
  mate ids are unique.

**The converter.** `convert_v1(document) -> DocumentV2` maps every V1
document onto v2 with nothing lost: features become steps unchanged, and
`DocumentV2.to_v1()` maps back any document that uses V1's kinds alone. A
test round-trips every recorded document both ways and requires identical
JSON. The v2 JSON Schema is generated from the operation catalogue, as V1's
is (`schemas/forgeir-2.0.0.schema.json`), and a test keeps it in step.

**The down-conversion for the second kernel.** A component is handed to
the implicit kernel as V1 features; a `fillet` or `chamfer` step becomes
nothing (its input passes through) and leaves a not-applicable zone
(13.2).

### 6.2 References by query

A reference names faces or edges by what made them, never by index:

```json
{"created_by": "s14", "role": "side",
 "where": {"kind": "cylinder", "axis": [0, 0, 1], "radius_mm": 1.4},
 "match": {"count": [1, 4], "covers": "full_circle"}}
```

- **Faces**: `created_by` a step and `role` one of the names it gives its
  faces (7.2). V1's semantic names resolve the same way: `pivot.bore` is
  the faces named `bore` by the step whose role is `pivot` (its first copy:
  9.2).
- **Edges**: `{"of": <faces>}`, the edges bounding those faces;
  `{"between": [<faces>, <faces>]}`, the edges where a face of the one
  meets a face of the other; both may take `where` and `match`.
- **`where`**, a geometric test to tell pieces apart: `kind` (plane,
  cylinder, cone, sphere, torus, line, circle), `axis` (parallel to),
  `normal` (a plane facing that way), `radius_mm`, `through` (a point the
  axis or plane passes through), `side` (`max_z` and the like: the pieces
  extreme that way), to 1e-6 mm and 1e-9 rad.
- **`match`**, required: `count` is the number of pieces allowed, a range;
  `covers` optionally adds `full_circle` (the edges are arcs of one circle
  that together go all the way round: a boss's root edge where a rib
  splits the plate's face into two is two arcs, and still the whole circle)
  or `whole` (no face or edge of the name was left out by `where`).
- An edge reference for a fillet is first closed under tangency (an edge
  meeting a chosen one smoothly is added, as OpenCascade would round it
  anyway); the count is checked after, and the trace lists what was added.
- Resolution is through the names carried by every operation's history
  (9.2). A match outside its condition is a hard error, listing what was
  found and why each candidate was kept or dropped; it is never "take the
  first one". This extends ADR-0003 to split faces, which it left open.

## 7. `forge_occ`: building

### 7.1 The build

```python
class OccBackend:
    name = "occ"
    version: str                        # "occt-7.9.3/forge-occ-2"
    def build(self, doc: DocumentV2, component: str, *, cache: Cache | None = None,
              overrides: Mapping[str, Quantity] | None = None) -> BuildResult
    def view(self, result: BuildResult) -> BrepView
    def export(self, result: BuildResult, formats: Formats, tol: ExportTolerance) -> Exported
```

1. Resolve the component's parameters and each step's parameters with the
   shared resolver: lengths in mm, angles in radians, exactly as the
   implicit kernel reads them.
2. In the graph's topological order, for each step: look it up in the cache
   (section 10); else build it, validate it, after-check it, name its faces,
   and store it.
3. The component's terminal step is the part. Its published entities (V1's
   semantic names: `pivot.bore`, `base.z_max`) are resolved to faces and
   measured, so interfaces and V1's measurement records read them as
   before.
4. `BuildResult` holds the solid, the names table, each step's trace (built
   or reused, time, volume, solids, faces, warnings, notes such as "removed
   nothing", tangent edges added), the entities, and the backend identity.

The build fails closed. A step OpenCascade refuses, that is invalid, or
that fails its after-check stops the build with an `OccError` naming the
component, step, operation, the step's JSON pointer, what was asked and
what came back. Nothing is skipped, retried with other settings, or
repaired; trying another construction is the compiler's job (stage 4),
under its own proof that the alternative makes the same shape.

**Settings, fixed and recorded:** booleans exact (fuzzy value 0, inside
OpenCascade's 1e-7 mm confusion tolerance), single-threaded, non-destructive;
validation by `BRepCheck_Analyzer`; geometric tolerances 1e-6 mm and
1e-9 rad for every comparison `forge_occ` makes.

### 7.2 What each operation builds

Each row is V1's builder, read as a definition. The names are the roles a
step gives the faces it creates; V1's published names are among them.

| Operation | Built as | Face names |
|---|---|---|
| `datum_plane`, `datum_axis`, `datum_point` | Frames, as V1: XY, YZ, XZ with XZ's normal −y and its offset along +y; `Frame.from_axis`'s perpendicular for an axis | (no faces) |
| `profile_rectangle` | Lines; corners as true arcs of `corner_radius`, or chamfer lines; a side whose arcs meet leaves no zero-length line | (a profile) |
| `profile_circle`, `profile_slot` | A circle; a slot's two arcs and two lines along `rotation`, a slot as long as it is wide a circle | |
| `profile_polygon` | Sides with outward normals at `rotation + 2πi/n`, corners at `rotation + (2i+1)π/n`; `corner_radius` rounds each corner with the sides kept where they are | |
| `profile_sketch` | Lines; a corner's radius a true arc, cut back as V1 cuts it (never past half a side, the radius shrunk to fit); a closing point written twice taken once; `smooth` the closed Catmull-Rom curve through the points, exactly, as cubic Bézier pieces | |
| `profile_gear` | V1's tooth: the true involute from the base (or root) circle to the tip, as a B-spline within 1e-6 mm; V1's straight root and tip chords | |
| `box` | V1's construction for each edge option: plain; `all` rounded as V1's offset box (rounded edges, spherical corners: a fillet of all twelve edges); every other option as V1's section extruded (a footprint or an end section, its corners rounded or chamfered, the ends rounded or chamfered), intersected and joined with square parts as V1 does for `vertical_*`, `bottom_`, `top_` | `x_min` … `z_max`; `round`, `bevel` |
| `cylinder` | From the base centre along the normalised axis | `lateral`, `base`, `top` |
| `cone` | From the base centre along the axis; equal radii a cylinder; a zero radius an apex | `lateral`, `base`, `top` |
| `sphere`, `torus` | About the centre and axis; a tube as thick as the ring refused, as V1 | `surface` |
| `wedge` | The box cut by V1's sloping plane | `base`, `back`, `slope`, sides |
| `extrude` | The profile's face swept along the plane's normal over V1's span (`normal` from the plane, `symmetric` centred on it, `reverse` behind it). Ends rounded or chamfered: the edges of the end faces `ends` chooses, filleted or chamfered (V1's `start` is the sketch-plane face, whatever the mode). Draft: tapered from V1's low end (the far face in `reverse`, the back face in `symmetric`), inward for a positive angle, as V1 | `start_face` (V1's low end), `end_face`, `side`; `round`, `bevel` |
| `revolve` | As V1 reads it: the profile's u is the radius from the axis and v the height along it, from the axis's origin, whatever plane it was sketched on; only the part at u ≥ 0; the angle from `Frame.from_axis`'s x axis, turning by the right hand about the axis | `side`, `start_face`, `end_face` |
| `sweep` | V1's construction: each straight run of the path (its corners first rounded to `bend_radius` by true arcs, cut back as V1 cuts them) the profile extruded in V1's twist-free frame, lengthened at each turn by the section's reach × tan(turn/2) as V1; each arc the profile turned about the arc's axis; fused | `side`, `start_face`, `end_face` |
| `pipe` | V1's construction: a cylinder per straight run, a ball at each joint, a torus segment for each `bend_radius` arc; the bore the same, lengthened past the open ends by the outer radius as V1; fused | `surface`, `bore`, `start_face`, `end_face` |
| `coil` | A circle swept along a true helix (a line on the cylinder), starting where V1's starts (its frame's x axis: +y for an axis along z), right-handed, ends square to the wire; V1's refusal of a pitch below the wire | `surface`, `start_face`, `end_face` |
| `loft` | V1's ordering of the two outlines (the lower first, both facing one way, refused as V1 refuses), joined by a ruled loft; lofts that run on from one another fused into one | `side`, `start_face`, `end_face` |
| `union`, `subtract`, `intersect` | `BOPAlgo_BOP` with its pave filler, flags read; faces on one surface merged. `blend_radius`: the junction edges (9.3) filleted; `chamfer`: chamfered; then merged | the operands' names; `round`, `bevel` |
| `hole` | V1's construction: through as a tool reaching V1's envelope diagonal plus 2r each way; `depth`; `through: first_wall` found along the axis by exact ray crossings, with V1's margins and midpoints; counterbore and countersink at V1's surface (for a through hole, the first material along the whole axis line, or the last for `entry: end`; for `first_wall`, the wall's faces; for a blind hole, its position), each tool starting V1's margin outside it | `bore`, `counterbore_wall`, `counterbore_floor`, `countersink` |
| `shell` | Inward: the part minus its inward offset (a sealed hollow, as V1); outward: the outward offset minus the part; `both` the two half-offsets | the part's names; `inner` (the new wall's faces take only this name) |
| `offset` | `MakeOffsetShape`, joins as arcs: the true offset | the part's names |
| `pattern_linear`, `pattern_circular` | Copies by exact rigid motions; `symmetric` shifts the source as V1; `step_angle` or `total_angle` (refused together), a full circle divided by the count, an arc by the gaps; fused | each copy's names, with its index |
| `mirror` | The reflection (`BRepBuilderAPI_Transform`, orientation kept valid); `keep_original` | the names, with the image's index |
| `transform` | Rotate about `rotate_origin`, then translate | the names, moved |
| `bend` | 7.3 | the names, carried through |
| `fillet`, `chamfer` (new) | `BRepFilletAPI_MakeFillet`/`MakeChamfer` on an edge reference (6.2), one radius or distance | `round`, `bevel` |

**The limits of V1's ranges.** Where OpenCascade's own operation fails at a
limit V1 allows, the construction above avoids the operation: a lug's end
rounded to half its width is V1's rounded section extruded (no fillet); a
rim rounded through the whole thickness is the section's rounded profile
turned or extruded; a cone with equal radii is a cylinder. Each limit has a
test at it and just inside it.

### 7.3 The bend

V1's bend (`forge_geom.Bend`) is a map of space: in the bend's frame (`e1`
along, `e3` toward, `e2 = e3 × e1`), the part before the zone stays, the
zone (on the middle surface `r + t/2`, `radius × angle` long, centred on
`position`) is wrapped round the bend axis, and the part past it turns
rigidly through the angle; `hold: middle` then turns the whole bent part
back by half the angle about the axis, the middle of the zone's middle
surface kept where it was. Chains of bends stated on one flat part are
applied far end first, each fold meeting flat material, with `hold` off.
The face and thickness come from V1's envelope of the flat part (3).

`forge_occ` builds exactly that map:

1. The flat part is split at the zone's two planes (square to `e1`).
2. The part before stays; the part past turns rigidly (exact).
3. The zone:
   - if it is a prism along `e1` (every face but the two cuts unchanged by a
     shift along `e1`), it is its first cut face revolved about the bend axis
     through the angle (exact);
   - otherwise (a hole or slot crosses it) every face, edge and vertex of the
     zone is mapped by the wrap: a plane square to `e3` becomes a cylinder
     about the axis and a plane square to `e2` stays a plane, exactly; every
     other surface and curve is refitted through the mapped points as a
     B-spline in its own parameters, so its trimming curves keep their
     meaning, to 1e-6 mm, the fit's largest error measured and recorded as
     the step's tolerance. A surface is fitted a little beyond its face's
     outline, except round a face that closes on itself (a bore), which is
     fitted exactly round its period, so the new surface closes too.
   - Flat material thinner than 1e-3 mm left either side of the zone (a
     zone sized to the whole part, missing it by rounding) is dropped, the
     tolerance recorded; the part's own end faces it held are the zone's cut
     faces there, and take their names.
4. The three are fused; `hold` turns the result back as V1.

### 7.4 What V1 defines by its envelopes

Some of V1's parameters are defined by the box V1 keeps round each solid
(its envelope, which for a turned or blended solid is looser than the
solid): a bend's inside face and thickness when not given, a hole's tool
length and the margins of its counterbore, countersink and first-wall
search. `forge_occ` reads those from V1 itself (`compile_products`, 3),
since they are what the document means; where V1 can't build the input (a
v2 step upstream of it that V1 lacks), it uses the exact box and the trace
says so.

## 8. After-checks

### 8.1 Every step

- The result is a solid or a compound of solids, non-empty, and
  `BRepCheck_Analyzer` finds it valid.
- Its volume is finite and positive; no shell is open; every solid's outer
  shell encloses positive volume.
- No face, edge or vertex carries a tolerance above 1e-4 mm: OpenCascade
  widens a tolerance to cover any gap it finds, and the checker passes a
  vertex whose tolerance was widened over a gap of centimetres (a bend's
  warp, before its old curves were removed, made one of 43 mm).
- For booleans: the pave filler's and the operation's error flags are
  clear; their warnings are read, and each warning kind either is on the
  short allowed list (with the reason in code) or fails the step.

### 8.2 What each operation must do

V below is volume, to the interval of section 11.

| Operation | After-check |
|---|---|
| Primitives | V equals the formula (box, cylinder, cone, sphere, torus, wedge) |
| `extrude` | No ends, no draft: V = A·h, A the profile's area and h the distance. Drafted inward: V ≤ A·h. Drafted outward: A·h ≤ V ≤ A·h + P·t·h²/2 + π·t²·h³/3 (Steiner's, P the perimeter and t the draft's tangent; equal for a convex profile: OpenCascade rounds the drafted corners, as V1's field does). Ends rounded or chamfered: the solid before them held as above, then less at most what the blends move (the blends' row) |
| `revolve` | V = section area × the centroid's radius × angle (Pappus) |
| `coil` | V = π ρ² × the helix's length (Pappus) |
| `union` | max(V_i) ≤ V ≤ ΣV_i |
| `subtract`, `hole` | V_base − ΣV_tool ≤ V ≤ V_base; the volume removed recorded ("removed nothing" noted) |
| `intersect` | V ≤ min(V_i) |
| Blends, `fillet`, `chamfer` | A face named for the blend made; the volume moved the right way and no further: V_in − R ≤ V ≤ V_in + A, R the most the ridges' blends can remove and A the most the creases' can add. An edge moves at most its section, r²(cot(α/2) − (π − α)/2) for a fillet and c² sin(α)/2 for a chamfer at the least angle α its faces meet at along it, times its length on the far side of a curve (×(1 + κ·reach), reach how far from the edge the blend's faces start); each corner where blends meet or end adds the cube four reaches wide round it. Ridge or crease is probed along the edge (a point outside one face's plane and inside the other's is air at a ridge, material in a crease); an edge that is both, or nearly flat, counts both ways. The relaxed face count: OpenCascade splits and merges blend faces at corners, so one face per edge isn't held; the edges added along tangents are listed in the trace |
| `shell` | A new void inward, or a part larger outward; and the wall measured: points spread over the new faces are at the thickness from the old surface, to 1e-4 mm |
| `offset` | Points on the new surface at the distance from the old, to 1e-4 mm |
| `transform` | V and face count unchanged |
| `mirror` | `keep_original` false: V and face count unchanged; true: V_src ≤ V ≤ 2 V_src |
| `pattern_*` | V_src ≤ V ≤ n V_src; each copy's motion checked on a point of it (its first vertex where the motion puts the original's, to 1e-9 relative), as for every moved copy (mirror, transform, a bend's far part) |
| `bend` | The wrap takes a volume element of the zone to ((f + r) − z)/m of itself, so the zone's image holds V_zone·((f + r) − z̄)/m, z̄ the zone's centroid's height (Pappus, for any zone): exactly for a prism zone, within the fit's tolerance × the image's area for a mapped one; and the bent part holds the flat material before and past the zone unchanged with it |

A failed after-check stops the build with what was expected and what was
found. It says the operation did not do what it should (for the "shell"
of 4 above: "no hollow was made; an 11 mm wall does not fit in a part
10 mm thick"), not whose fault it is: that is for the compiler or the agent
to settle.

## 9. Names, history and references

### 9.1 What is recorded

`names.py` keeps, for the current shape of the build, a table from each
face (by `IsSame`, through a `TopTools` map) to its set of names, each
name `(step id, role, copy)`. Edges are not stored; they are found from
faces when asked, by the pair of faces they lie between.

### 9.2 Through each operation

After each operation the table is rebuilt from the operation's history
(`BRepTools_History` from the BOP, the fillet and offset builders,
`UnifySameDomain`, transforms; for primitives, the builder's own faces):

- a modified face passes its names to every face it became, so a face split
  in two is two faces with one name;
- a removed face drops them, and the trace records which names were lost,
  so a later reference to them says "buried by step s7";
- a generated face takes the operation's name for it (7.2), and only that:
  a shell's new wall is `inner`, not the outer face it was offset from;
- faces merged onto one surface keep all their names (a reference to one of
  them then includes the merged face's whole outline, which is its real
  boundary);
- a bent zone's faces keep the names of the faces they were mapped from;
- pattern and mirror copies carry their copy index; V1's semantic names
  mean copy 0, the original, as V1 publishes only the original's.

The table is part of every cache entry.

### 9.3 Junctions

The junction of a boolean, which `blend_radius` rounds, is found on the
boolean's own result, before faces are merged: the edges lying between a
face that came from exactly one operand and a face that came from exactly
one other, where the two meet at a crease (not tangent). Probing showed
OpenCascade's own "section edges" list is empty when operands touch flat
(a boss standing on a plate), so it is never used; and taking the junction
after merging would count a column's outer edges, whose merged faces carry
both operands' names.

### 9.4 Resolving a reference

1. Candidates: the faces carrying `(created_by, role)`; for edges, the
   edges of those faces, or between the two sets.
2. `where` keeps the candidates that pass every test; each dropped one is
   recorded with the test it failed.
3. For a fillet or chamfer, the tangent closure (6.2).
4. `match`: the count must be in range, and `covers` hold.
5. Otherwise `RefError`, with every candidate, its geometry, and why.

## 10. The copying cache

- **Key**: SHA-256 of the canonical JSON of the step's op, its resolved
  parameters (references included), its inputs' keys, its id and role
  (which its names depend on), the backend identity with the OpenCascade
  version, the fuzzy value, and the cache scheme's version.
- **Entry**: the solid serialized with `BinTools` (no triangulation), the
  names table by face index, the trace and entities.
- **Every hit is a fresh copy**: deserialized into new shapes, so no two
  builds share a mutable shape. Probing confirmed the serialization is
  byte-for-byte deterministic; a test holds that face order survives it, and
  another changes a returned shape (meshes it, moves it, changes a
  tolerance) and requires the next hit to be untouched.
- An in-memory LRU bounded by bytes (256 MB by default), with an optional
  directory. A corrupt or unreadable entry is a miss, never an error.

This is what stops V1's "the cache served the wrong geometry".

## 11. `BrepView` and exact measurement

`BrepView` answers the stage-2 `GeometryView` protocol over a built solid.
Its source is `"brep"`; a STEP file read back is the same class with source
`"step-file"`.

| Question | How | Tolerance |
|---|---|---|
| `classify` | ON within 1e-6 mm. For a part with faces other than planes, cylinders, cones, spheres and tori, and many points: a sound fine mesh of it, measured, gives the side of every point more than twice its deviation away. Then the nearest support: `BRepExtrema` finds the nearest point in a face, and the outward normal there gives the side where the point is at least half its distance off the face's tangent plane. Only the rest go to `BRepClass3d_SolidClassifier` | exact |
| `distance` | `BRepExtrema_DistShapeShape` from a vertex to the compound of the faces (to the solid itself, a point inside is at 0) | exact |
| `crossings` | `IntCurvesFace_ShapeIntersector`: entering from the transition, checked against the face's orientation; a hit at an edge or vertex (state ON) or tangent marks the ray grazed; hits at one place from two faces merged within 1e-9 mm | exact |
| `volume` | `BRepGProp` at 1e-12 (at 1e-9 a sphere made a rational B-spline came out 2.1e-7 relative off; at 1e-12, 3e-9), as an interval of ±1e-6 relative, tested on analytic solids (spheres, tori, cones as B-splines) to hold with a margin of five | stated |
| `bounds` | `BRepBndLib.AddOptimal` without tolerances | tight to OpenCascade's tolerance |
| `coverage(radius, within)` | Per face, in its own parameters: a grid fine enough by the surface's speed bound that every point of each cell is within 0.6r of a corner (exact for planes, cylinders, cones, spheres, tori; for a B-spline, rational ones included, a bound from each span's own control net, the spans refined by knot insertion where the bound is loose; for a surface of extrusion or revolution, from its curve's; any other surface measured, at twice what is found, and said to be measured); the points inside the face kept; and the face's edges sampled 0.6r apart (an edge no longer than that by its ends). Every point of the face is then within 0.9r of a sample. Within a box: the face's parameters halved into pieces until those that may reach it (a piece's points are within (Lu·Δu + Lv·Δv)/2 of its middle's) are no wider than a quarter of it, the grid's points of every cell meeting them, and the edges' samples within r of it: the very points the whole grid has there (stage 4, docs/V2-stage4.md 13.10). Normals exact and outward; at or by a pole or an apex, the surface's own normal there facing the way it does just inside the face (a face's bounds may reach 1e-7 mm past a cone's apex, onto its other nappe, where the derivatives face the other way: generated part 244) | per face, OpenCascade's tolerance of the face |
| `topology` | Exact counts on the B-rep (11.1) | exact |
| `faces`, `edges` | Each face's surface type and parameters, area, bounds; each edge's curve type, parameters, length | exact |

**11.1 Topology, on the B-rep.** Shells; solids; voids (shells inside a
solid other than its outer one); open edges (edges with one face, seams and
degenerate edges excepted); bad edges (three or more faces, or two using it
the same way round); bad vertices (faces round a vertex not one fan); "bad
triangles" are faces with no area or that `BRepCheck` rejects;
self-intersections from `BOPAlgo_CheckerSI` at level 4 (level 5 doesn't finish on a coil), and faces sharing no vertex measured apart by `BRepExtrema`, two vertices within each other's tolerance not counted where an edge joins them (they are the ends of an edge shorter than they are held to: stage 4's exit shakedown, part 3500, a STEP reader's two 1.7e-8 mm edges where a boss's rim touches a block's edge); misnested shells;
each solid's genus from the Euler–Poincaré formula with loops. A test
requires these to equal the mesh view's counts on the same part's fine
mesh, for every part the stage-2 tests use.

**11.2 The stage-2 tests on the B-rep.** The check-kind tests, face
accounting, probes and the detection matrix ran in stage 2 on meshes made
by manifold3d from the generator's truth. The same truth is built exactly
too (`tests/v2_truth_occ.py`: each prism its outline, its chosen corners
true arcs, extruded; each frustum a cone; added and taken away in order),
and the whole judge (every compiled check, face accounting, topology,
volume, fresh probes) runs on `BrepView` over it
(`tests/test_v2_checks_brep.py`): the B-rep is the truth's shape (the same
side at 20,000 points, its volume inside the mesh's interval, the same
topology), every detector passes each part as asked, and each fault fails
the same detectors on the B-rep as on the mesh. A check that passes on a
mesh and fails on the B-rep (or the reverse) is a defect of one of them,
found here; none was.

**`measure.py`** gives the rest of exact measurement, for interfaces and
V1's measurement records: volume, area, centroid and inertia; a face's
radius, axis and extent; distances between shapes.

## 12. Export, and re-opening every file

```python
@dataclass(frozen=True)
class ExportTolerance:
    linear: float = 0.01      # mm: the most a mesh may be from the surface
    angular: float = 0.1      # rad
    finer: tuple[tuple[Box, float], ...] = ()  # stage 4: finer in these boxes
```

The tolerances come from the spec in stage 4 onward (the check compiler
says how fine a mesh must be); stage 3 takes them as given. *Stage 4
(docs/V2-stage4.md, 13.10):* a finer tolerance may hold in a box; each face
whose surface may come within `linear` of it is meshed first, and refined
and measured, to it, and a reader of the file works out each triangle's
tolerance from the spec alone: a box's where the triangle meets the box,
else `linear`.

**STEP.** AP242, millimetres, written by the XCAF writer so every part,
instance and assembly is named, with each instance's placement. Each face
that closes on itself (round a seam) is written as two halves
(`export.exchanged`: the same solid and surfaces, kept only if valid and of
the same volume), so readers older than OpenCascade 7.9 read it whole; cut
where the cut passes no corner of the part nearer than 1e-3 mm (no new edge
shorter, no two corners brought nearer; else in thirds, quarters, fifths,
sixths or sevenths: a
face is halved across the middle of its parameters, where a part's features
often sit, and stage 4's exit shakedown, part 7250, halved a tube's face
3.2e-5 mm from where a hole met it, the corner there read back held
6.2e-5 mm loosely, over its neighbour); and
kept only if the file reads back held as tightly as a step's solid must be
(section 8; stage 4's exit shakedown, part 1130: a bore halved 6e-5 mm from
where a hole met it left an edge that short, and the reader widened the
vertex there to 1.9e-4 mm, over its neighbour) and valid (stage 4's exit,
part 3500: a plane's and a cylinder's halves read back with their wires
turned against each other, though the halves were a valid solid). Where
a split reads back otherwise, the next is tried before the part is
written unsplit. Stage 4's held-out run, part 1130 rebuilt with its holes
carried (V2-stage4.md, 5.2): its halves, thirds and fifths all passed the
corners' test but read back held 1e-4 to 3.4e-4 mm loosely, where its
quarters read back tight. The halves are made of a copy, so writing a part never
changes it (part 6950: the edges the halves share with faces left whole
were made to agree with them in the part itself, 24 of its tolerances
changed). An edge's tolerance says how far its curve and its curves on its
faces may be apart; OpenCascade's STEP reader sets it, and its checker
checks it, at a few dozen points along the edge, and a curve on a face
the reader made again to follow its edge strays most between them (part
6950: a bore's 3.9e-5 mm off its edge where it meets a big hole, the edge
stating 1e-7 mm). So each edge of the halves, and of every part read back,
is measured along its whole length (`occt.widened_to_curves`, OpenCascade's
`BRepLib_ValidateEdge` by its exact method) and held as loosely as its
curves stray: no part read back is taken for nearer its true surface than
it is. The file states the loosest tolerance of the part as written or as
built, whichever is looser. The copy's edges, made again to agree with
their faces, can be held more tightly than the part's own, and a file
that stated only theirs would take the part for nearer its surface than
it is (part 0 rebuilt with its holes carried: 2e-6 mm stated, where the
part held 3.3e-6 mm). A
spindle torus (its tube wider than its ring: where a block's top edges are
rounded tighter than its vertical ones were, and more than half as much)
comes back as the surface of revolution it is, and is counted so (part
1340); an
interface's face read back is found again as the faces on its surface that
together have its area and box. Faces that
interfaces name carry their names, if the reader keeps them (probed before
it is relied on; otherwise the mate check finds them geometrically).

**STL and 3MF.** A copy of the part is meshed at the export tolerance (the
copy carries no mesh, so no old one can be reused). STL is binary. 3MF is
written with lib3mf, its unit millimetres, one object per part, the build
item placing the part on the plate: turned by the orientation given
(identity in stage 3; the spec's from stage 6) and moved so its lowest
point is at z = 0.

**12.1 The re-open checks**, before a file is handed over:

| File | Read back by | Must hold |
|---|---|---|
| STEP | OpenCascade's STEP reader, as `StepFileView` | It says millimetres; the same solids, valid; volume (both measured the same way), area and bounds equal to 1e-6 relative; the same faces by surface type; the assembly's names and placements as written; every mate holds on the re-opened geometry |
| STL | `forge_checks`' own reader and mesh view (NumPy, no OpenCascade) | Sound; volume within the mesh view's interval of the exact volume; every vertex within the tolerance of the exact surface, and every point of the exact surface's coverage at the tolerance within it of the mesh |
| 3MF | the same, through its 3MF reader | as STL; millimetres; one object per part; on the plate |

**Meshes are welded by the part's own topology**, not by where nodes are:
the k-th node along an edge is one vertex for every face the edge bounds,
an edge's end is the part's vertex there, a degenerate edge (a pole, an
apex) is its vertex throughout; a triangle the weld leaves with no area is
dropped. (A sphere's pole is two nodes otherwise, and the mesh not
watertight.) So both faces of an edge must be meshed with one
discretisation of it: faces meshed apart, before the whole part, are meshed
together where they meet (stage 4, 13.10).

**Every mesh is measured**: ten points of each triangle (its corners,
centre, sides' middles, and halfway from its centre to each corner) from
the exact surface of the face it was made from, and every point of a
coverage of the exact surface (at a fortieth of the part's size) from the
mesh. On a surface other than a plane, cylinder, cone, sphere or torus, a
point is measured from the surface's point at its triangle's parameters,
then from the nearest found by a local search from there, then, where
that still leaves it far, by OpenCascade's projection over the face's
parameters: each a point of the surface, so never nearer than the truth
(stage 4's exit shakedown, part 7470: on a letter's side, the extrusion
of a Bézier curve whose speed falls to nothing at its end, the local
search went nowhere from a sample's parameters, 0.092 mm off, and the mesh
was refused at every refinement; the sample was 1e-14 mm from the
surface). A triangle measured too far is split: each of its sides inside its
face at the side's middle, found on the surface by the middle of its ends'
parameters (a neighbour sharing a split side is split with it), or at its
centre where no side can be (each on the part's edges, a seam or a pole);
the part's edges are never split, so the faces stay welded. Splitting stops
when a round gains nothing (what is left is on the part's edges), and the
split mesh is kept only if it is sound. A mesh still too far from the
surface is made again at half the deflection, up to four times, then
refused (OpenCascade's mesher aims at its deflection but doesn't promise
it; the check does).

## 13. Second-kernel agreement

### 13.1 `ImplicitView`

The implicit kernel's own view of what it built, in `forge_kernel` (L0):

- `classify`: the sign of the field, exact for the implicit shape; ON when
  the field is within 1e-9.
- `volume`: V1's rigorous measurement, an interval sure to hold the
  implicit shape's volume.
- `bounds`: the field's refined extents.
- `distance`, `crossings`, `coverage`, `topology`: from a mesh of the field
  (V1's extraction at a resolution finer than the part's thinnest wall),
  answered by the stage-2 mesh view, with the mesh's measured distance from
  the field as its deflection.

### 13.2 How the implicit kernel holds each operation

`forge_kernel/agreement.py` fixes, per operation and its options, one of:

- **bounded by τ**: the implicit shape is within τ of the exact one, τ
  worked out from the step's resolved parameters and V1's own products,
  plus 1e-4 mm;
- **not applicable within a zone**: the implicit kernel's meaning differs
  by design there (2.4); outside the zone the step is held to the rest.

| Operation | Entry |
|---|---|
| datums; box (every edge option, built as V1); cylinder, cone, sphere, torus, wedge; rectangle, circle, slot, polygon profiles; extrude (straight; ends rounded or chamfered on a convex profile; drafted inward on a convex profile); revolve; booleans (sharp); hole (plain; blind with a counterbore or countersink); patterns, mirror, transform; bend with a prism zone | bounded by 1e-4 mm |
| `profile_sketch`, rounded corners | τ = the largest r(1 − cos(θ/20)) over its arcs (V1's ten segments) |
| `profile_sketch`, smooth | τ = the largest distance between the Catmull-Rom curve and V1's ten chords per span, computed |
| `profile_gear` | τ = the largest distance between the true involute and V1's eight segments, computed |
| `sweep`, `pipe` with `bend_radius` | τ = (R + ρ)(1 − cos(Δ/2)), R the bend radius, ρ the section's reach, Δ V1's step (the arc's turn over twelve) |
| `coil` | τ = R(1 − cos(π·turns/n)), n V1's point count (36 a turn); and within 2ρ of each end, ρ·tan(π·turns/n) more (V1's ends square to a chord) |
| `hole`, through, with a counterbore or countersink | τ = half V1's step along the axis: the envelope's extent along the axis over 511 |
| `hole`, `first_wall`, with a counterbore or countersink | τ = V1's step finding the wall's faces: the cut's length over 800 |
| `bend` with a mapped zone | τ = the fit's measured error |
| `extrude`, ends rounded on a profile with a reflex corner | not applicable within 2r of the end faces' reflex corners |
| `extrude` drafted outward, or inward on a profile with a reflex corner | not applicable within the drafted side's offset (distance × tan(draft)) of its corners |
| booleans with `blend_radius` or `chamfer` | not applicable where both operands are within 2r (2c) |
| `shell`, `offset` | bounded by 1e-4 mm where the input is one box, cylinder, sphere or convex extrusion; else not applicable through the input, grown by the thickness |
| `loft` | bounded by 1e-4 mm between two concentric circles; else not applicable within the diagonal of V1's envelope of the loft (a bound on how far V1's morph strays from the ruled loft that needs no sampling) |
| `sweep` of anything but a centred circle | not applicable within 2ρ of the sweep's faces, ρ the section's reach |
| `fillet`, `chamfer` (down-converted to nothing) | not applicable within 2r (2c) of the rounded edges |

The spec-item table of stage 2 (`forge_checks.capabilities.HOLDS`) is
derived from this one in stage 4, when items compile to operations: an item
is held as the weakest of its operations.

### 13.3 Where each entry applies

An entry applies near the faces the step made, wherever they ended up: each
τ and each zone is attached to the step's face names (9.2), so it follows
every later move, copy, mirror and bend, and it stays local: a counterbore's
τ applies within τ and a margin of the counterbore's faces, not over the
whole part. A point's τ is the largest of the entries whose faces are
within reach of it; a point in any not-applicable zone is not compared.

### 13.4 The agreement test

For a component built by both kernels:

1. **Points.** (a) the exact part's coverage, each point moved along its
   exact normal both ways by its τ and a margin δ; (b) the same from the
   implicit part's mesh; (c) uniform points in the box round both.
2. **Kept**: points whose distance from the exact part's faces is at least
   τ + δ/2 and that lie in no not-applicable zone.
3. **Every kept point must be on the same side in both kernels.** One that
   isn't is a disagreement, reported with the point, both sides, the steps
   whose faces are near, and their entries.
4. **Volume**: the exact volume within the implicit interval widened by
   Σ (area of each entry's faces × its τ) and by the volume of the
   not-applicable zones.
5. **Names**: every V1 name the implicit kernel publishes and finds in the
   part is found by `forge_occ` too; cylinders' radii and axes agree to τ.
6. **Topology**: solids, voids and genus equal, unless a not-applicable
   zone is on the part, the exact part's solids only touch (along edges or
   at points: as many solids to it, one to a mesh that can't tell a contact
   of no width from a join; the build's trace says how they meet), or the
   implicit mesh isn't sound (each reported, not counted). Where the mesh
   is sound but the counts differ, it is made again at 192 cells across,
   then 256, and the finest made is the one compared: at 96, a hole a cell
   or two across closes (generated part 190's, 1.52 mm in a block 100 mm
   long), and the counts differ for a mesh too coarse, not a part wrong
   (`forge_occ.agreement.FINER`). One that isn't sound is not made again:
   finer, it stays so (a cone's apex), and V1's extraction then needs more
   than 4 GB at 192 cells for a cone on a plate, against 0.25 GB for part
   190's block. Where the counts still differ at the finest, the exact
   part's thinnest wall and narrowest gap are measured: along the normal at
   each point of its surface, a cell apart (at most 300,000), inward to
   where its material ends and outward to where it begins again, where the
   face found there faces back to within about 25 degrees (two sides of a
   wall or a gap, not a wedge's; `BrepView.first_hits`). One under two of
   the mesh's cells (the median length of its edges) is a wall the grid
   can step over or a gap it can close, whatever the field holds, and the
   counts are reported, not counted (generated part 9530: four holes
   0.118 mm from a pocket's side, in cells of 0.47 mm: genus 8 for 4).

Points are jittered by a hundredth of δ, so none falls exactly on a plane
both kernels share, where V1's field is exactly 0. A point is kept by the
exact part's fine mesh (made at δ/4, its triangles split until within it,
and measured): far enough when its mesh distance less the mesh's measured
deviation is τ + δ/2 or more; only a point the deviation leaves undecided
is measured exactly. A name the implicit kernel finds and the exact part
lacks is excused, and the excuse reported, where V1 finds it only because
its analytic patch reaches past the face onto another face of the part,
or where a blend whose zone is not applicable rounded the face away whole,
or where the step that lost it was right to (its inside, well clear of its
rim, is nowhere on that step's part: a joined foot, a tool's face at its
mouth; the inside sampled on a grid in the face's parameters, refined from
9 to as many as 129 points a side until it finds points clear of the rim,
as a foot whose legs are 0.49 mm wide needs: stage 4, part 6820); a bent
cylinder is no cylinder, and is held by its name alone.

δ is 0.01 mm, or five times the mesh deflection of (b), whichever is
larger. The test is two-sided: (a) catches material the implicit kernel
lost, (b) material it added, (c) anything far from both surfaces. A wall
thinner than 2τ + δ gets no points of its own; the report lists such walls,
and the corpus has none.

## 14. What is tested

- **Each operation**: a build test (valid, the right volume, faces and
  names), the after-check's own test (the trap or fault it exists for,
  made to happen, and caught), and an agreement test over
  parameterisations including the limits of V1's ranges.
- **Booleans**: flags (a forced error, an allowed warning), merging,
  junctions found before merging, disjoint operands, a tool that misses, a
  cut that splits a part into lumps.
- **Bends**: prism zones and mapped zones (the six recorded curved plates),
  `hold`, chains, faces and thickness from V1's envelope, the fit's
  recorded tolerance.
- **Names and references**: every name of every operation in 7.2 on a
  built part; references through splits, merges, patterns, mirrors and
  bends; tangent closure; every failure path of `match`.
- **The cache**: hit, miss, key sensitivity (each key part changed alone
  makes a miss), copies, a changed hit, corrupt entries, the byte bound.
- **`BrepView`**: every protocol question against analytic answers,
  points inside included; the `ViewProxy` contract; coverage's guarantee
  checked against a far finer sampling; topology equal to the mesh view's;
  the stage-2 tests on the B-rep (11.2).
- **Export**: each format re-opened and checked; a forced coarse mesh
  caught; inch STEP files read in mm; assemblies with names and placements;
  FreeCAD opening every exit-test file.
- **The corpus**: all 149 recorded V1 documents (the zoo, the golden
  clevis and the recorded runs, every one of which V1 builds) are built by
  `forge_occ`, and agreement is run on each.
- **Properties**: random parameterisations of each operation in V1's
  ranges, built in both kernels, agreeing.

## 15. Install

- `pip install -e ".[exact]"`, run in the Forge folder, adds
  `cadquery-ocp-novtk==7.9.3.1.1` and `lib3mf==2.5.0` (not
  `pip install "forge[exact]"`, which Forge's messages said until
  9 November 2026: PyPI's package named `forge` is an unrelated Django
  tool). The trust core still needs only NumPy; `forge_occ` is
  imported only where it is used, and its absence is reported as "the exact
  kernel is not installed", never as a crash.
- `forge doctor` checks the Python version and the pins, builds a probe
  part (a plate with a counterbored hole, a fillet and a bend), checks its
  volume and names, writes and re-reads STEP, STL and 3MF, and prints one
  line per check.
- **The laptop**: the Linux VM (Python 3.10) runs the whole exact-kernel
  suite; OCP 7.9.3 is installed there already.
- **Windows**: `scripts/prove_exact_kernel.ps1` installs the pins into the
  Python you run Forge with, runs `forge doctor` and the exact-kernel suite
  (FreeCAD's checks skip themselves there), and prints a one-line verdict;
  `-Exit` adds the exit test. You run it once (section 17).
- **make**: `make doctor`; `make exact`, the exact kernel's suite, the exit
  test aside (about 15 minutes); `make exit-test`, the exit test (about two
  hours: both kernels on every recorded part).
- **Docker**: the Dockerfile's `solvers` stage installs the pins; its `core`
  stage stays NumPy only. Here no registry can be reached, so its base is
  made from Ubuntu 24.04's archive by `scripts/docker_base_from_archive.sh`
  (2.6; behind a proxy that re-signs TLS, its certificate bundle is given as
  `CA_BUNDLE`). In the image, run as the worker would be (`--network none
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt
  no-new-privileges`), `forge doctor` passes every check and `make exact`
  passes all nine suites (FreeCAD's two checks skip themselves: it isn't in
  the image).

## 16. The exit test

`tests/test_v2_occ_exit.py`, run on the laptop and in Docker:

1. **Every V1 golden and zoo shape** (the golden clevis and the 34 zoo
   documents): converted to v2, built by both kernels; each agrees by
   13.4, with every not-applicable zone and tolerance listed in the report.
   Then all 149 recorded documents the same way.
2. **STEP**: each of those parts exported, re-opened by OpenCascade (12.1)
   and by FreeCAD (valid, as many solids as built, volume within 1e-4 of
   the part's: FreeCAD integrates at OpenCascade's default precision, found
   up to 2.4e-5 off the exact volume; the faces' optimal box within 1e-6 of
   the part's size). The files are written to `runs/stage3_step/` for you to
   open in Fusion, with the report.
3. **A two-part document with a mate**: a clevis and its pin, a `coaxial`
   mate and a `contact` mate; the document round-trips through JSON
   unchanged; it is built, exported as one STEP assembly, re-opened, and
   both parts, their names and placements come back, and both mates hold on
   the re-opened geometry. FreeCAD opens the assembly with both parts
   (inserted as plain objects: FreeCAD 0.19 without its interface crashes
   inserting an assembly as a group of links).
4. The trap tests of section 4 pass (`tests/test_v2_occ_ops.py`).

**The one recorded design refused.** `leg_shell_thinnest_wall_at_its_webs_claude`
shells four stacked lofts 8 mm inward. OpenCascade's offset by joins
refuses the stack (`BRepOffset_MixedConnectivity`: the lofts' faces meet
partly tangent along their joints; each loft alone offsets), and its simple
offset comes out 6.13 mm from the surface at a corner, so the wall check
refuses the step, saying both. The exit test holds it to that refusal, so a
wrong part can never pass as V1's. Building it truly needs an offset of
Forge's own (the solid less every face, edge and corner grown by the
thickness: a true erosion), which no other recorded design needs.

## 17. Open questions for you

1. **Fusion**: open the files in `runs/stage3_step/` (and the assembly) in
   Fusion and say whether any fails or looks wrong.
2. **Windows**: run `scripts/prove_exact_kernel.ps1` in the PowerShell you
   use for Forge and send me its last lines. (It never reads
   `ANTHROPIC_API_KEY` and shows no secret.)
3. **The leg shell** (16): should Forge's own true offset come before
   stage 4, or wait for a design that needs it?

## 18. The order of work

1. The pin, `occt.py`, `errors.py`, `geom.py`; the trap tests of section 4.
2. ForgeIR v2 and the converter; `resolve_feature_parameters` and
   `compile_products`.
3. Profiles and primitives; `names.py`; after-checks; `BrepView` and
   `measure.py`, so every later step is tested through the view.
4. Sweeps, booleans, holes, arrays, modifiers, bend (prism, then mapped);
   then fillet and chamfer with references.
5. The cache.
6. `ImplicitView`, the agreement table and test; the corpus.
7. Export and re-open; `StepFileView`; FreeCAD; the two-part document.
8. `forge doctor`, the Windows script, Docker, the laptop; the exit test;
   sync.
