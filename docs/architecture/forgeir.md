# ForgeIR language reference

ForgeIR is the format of record for a design. Every CAD backend consumes it;
none of them is privileged. See [ADR-0001](../adr/0001-forgeir-as-the-format-of-record.md).

## Guarantees

1. **Every dimensional value carries a unit.** A bare number where a length
   belongs is a validation error, not an assumption about millimetres.
2. **Every error names a location** as an RFC 6901 JSON Pointer, e.g.
   `/components/0/features/3/parameters/diameter`.
3. **Unknown fields are refused**, not ignored. A silently dropped misspelled
   field loses intent while appearing to succeed. Extensions use the `x_` prefix.
4. **Geometry is referenced by meaning.** Nothing anywhere stores a face index.

## Document

```json
{
  "schema_version": "1.0.0",
  "document_id": "uuid",
  "project_id": "uuid",
  "revision": 1,
  "parent_revision_id": null,
  "name": "Bench-test clevis hinge",
  "risk_class": "low",
  "units":        { "length": "mm", "mass": "kg", "angle": "deg", ... },
  "provenance":   { "created_by": "...", "tool_version": "...", "seed": null },
  "requirements": [ ... ],
  "assumptions":  [ ... ],
  "components":   [ ... ]
}
```

The major version is checked; a future major version is refused rather than
best-effort decoded.

## Quantities

```json
{ "magnitude": 6.0, "unit": "mm" }
{ "magnitude": 20.0, "unit": "mm", "interval": { "lo": 19.95, "hi": 20.05 } }
```

Units accept compound forms with parentheses: `N/mm^2`, `kg*m/s^2`, `W/(m*K)`,
`J/(kg*K)`, `1/K`, `mm^-2`, `mm^(1/2)`. `W/(m*K)` and `W/m*K` are different
units and both parse — getting that wrong silently would produce a plausible
number with the wrong dimension.

## Expressions

A parameter or feature parameter may be an expression over other parameters:

```json
{ "expression": "ear_gap + 2 * ear_thickness", "unit": "mm" }
```

Supported: numeric literals, names, `+ - * / // % ** ^`, unary sign, comparisons,
`and`/`or`/`not`, conditional expressions, parentheses, and 19 dimensionally
aware functions (`sin cos tan asin acos atan atan2 sqrt hypot abs exp ln log10
min max clamp round_to deg rad`).

`^` means exponentiation. It is rewritten to `**` lexically *before* parsing, so
`2 * mm^2` is `2 mm²` — an AST-level rewrite would give `(2 mm)²`, because `^`
binds more loosely than `*` in Python.

Refused by name, as a security boundary rather than a heuristic: attribute
access, subscripting, lambdas, comprehensions, generators, starred arguments,
keyword arguments, assignment expressions, f-strings, string literals,
containers, `await`, and any call outside the function table. `eval` is never
invoked, so there is no sandbox to escape.

Name resolution order: named constants (`pi`, `tau`, `e`, `g0`), then declared
parameters, then unit symbols. A declared parameter **shadows** a unit of the
same name, which is what an engineer who wrote `t = 6 mm` expects. Shadowing is
reported by `ParameterGraph.shadowed_units()` rather than forbidden, because
`t`, `L` and `h` are the natural names for thickness, length and height.

## Parameters

```json
{
  "id": "ear_thickness",
  "value": { "magnitude": 6.0, "unit": "mm" },
  "bounds": { "min": {"magnitude": 4.0, "unit": "mm"},
              "max": {"magnitude": 10.0, "unit": "mm"} },
  "optimizable": true,
  "description": "Thickness of each ear; the primary structural variable"
}
```

Exactly one of `value` or `expression`. A derived parameter cannot be
`optimizable` — the optimiser would have to contradict its defining expression.
Bounds are checked three-valuedly: a value whose uncertainty straddles its own
bound is recorded as indeterminate rather than silently accepted.

## Features

A component's geometry is an **acyclic graph**, not a timeline. Two holes at
opposite ends of a bracket do not depend on each other, and a linear history
would make changing one invalidate everything after it.

```json
{
  "id": "pivot",
  "kind": "hole",
  "role": "pivot",
  "inputs": ["trimmed"],
  "parameters": {
    "diameter": { "expression": "pivot_diameter", "unit": "mm" },
    "position": { "vector": ["base_length / 2", "base_width / 2", "pivot_z"],
                  "unit": "mm" },
    "axis": [0, 1, 0],
    "fit": "clearance_normal"
  }
}
```

### The 33 feature kinds

| Group | Kinds |
| --- | --- |
| Datums | `datum_plane` `datum_axis` `datum_point` |
| Profiles | `profile_rectangle` `profile_circle` `profile_polygon` `profile_slot` `profile_sketch` `profile_gear` |
| From profiles | `extrude` `revolve` `sweep` `loft` |
| Primitives | `box` `cylinder` `sphere` `cone` `torus` `wedge` `pipe` `coil` |
| Booleans | `union` `subtract` `intersect` |
| Modifiers | `hole` `shell` `offset` `bend` |
| Arrays | `pattern_linear` `pattern_circular` `mirror` `transform` |

`profile_sketch` is any closed outline through a list of points, each corner
optionally rounded to its own radius, or passed through smoothly; extruded it
is a flat part of any shape, revolved a turned part of any section.
`profile_gear` is a spur gear's involute outline. `sweep` carries a profile
along a path, `pipe` is a round bar or tube along one, `coil` a helix of wire,
and `loft` passes from one profile to another on a parallel plane.

Edges are rounded or chamfered by the feature that makes them, not by a later
edge selection: a `box`'s `edge_radius` / `edge_chamfer` (with `edges` saying
which), an `extrude`'s `end_radius` / `end_chamfer` round its end faces, a
profile's `corner_radius` / `corner_chamfer`, a boolean's `blend_radius` (a
true circular fillet of exactly that radius) or `chamfer` where its operands
meet, and a `hole`'s counterbore or countersink at its entry. An `extrude`
takes a `draft_angle`. See [ADR-0007](../adr/0007-implicit-backend-first.md)
for why.

A list of points is its own parameter sort: `{"points": [[0, 0], [60, 0, 5],
[60, 20]], "unit": "mm"}`, each coordinate a number or an expression.

## Semantic outputs

Every feature *statically declares* the geometry it publishes, so the compiler
can verify a reference will resolve before running any CAD kernel.

| Feature | Publishes |
| --- | --- |
| `box` | `<role>.x_min` `.x_max` `.y_min` `.y_max` `.z_min` `.z_max` `.body` |
| `cylinder` | `<role>.lateral` `.base` `.top` `.axis` `.body` |
| `hole` | `<role>.bore` `.axis` `.entry` `.body` |
| `extrude` | `<role>.start_face` `.end_face` `.side` `.body` |
| `sphere` | `<role>.surface` `.body` |

Each is described **analytically** — a cylindrical face is an axis, a radius and
an extent — so the same entity means something to every backend.

## Interfaces

A functional port, referencing a semantic name:

```json
{
  "id": "pivot_port",
  "type": "bore",
  "geometry": "pivot.bore",
  "nominal_size": { "magnitude": 8.2, "unit": "mm" },
  "fit": "clearance_normal",
  "load_transfer": "Bearing load from the pin, reacted into both ears.",
  "allowable_motion": ["rotation_about_axis"]
}
```

Mates reference interfaces, never faces. An interface whose `geometry` names
nothing the feature graph publishes is refused at decode time.

## Requirements and assumptions

A requirement without a `verification` method is a wish, so the field is
required. A threshold without a unit is not a limit, so thresholds are
quantities.

An assumption carries `risk`, `reversible` and `approved`. High-risk or
irreversible assumptions block release until explicitly accepted — loads, safety
factors, material grades, human anatomy, environmental exposure. Only low-risk
workflow assumptions may be auto-accepted.

## Validation order

1. JSON syntax.
2. Schema major version.
3. Structural decode — types, required fields, unknown fields, enums. Sibling
   errors are collected and reported together, because a language model
   repairing a document should not pay a round trip per mistake.
4. Identifier uniqueness.
5. Cross-references — feature inputs exist and have the right product kind;
   interfaces name published geometry; feature parameters name declared
   parameters or known units.
6. Graph acyclicity, reported as the actual cycle path.
7. Exactly one terminal solid per component.

Parameter *values* are resolved at compile time, not decode time, because
overrides from an optimiser change them.
