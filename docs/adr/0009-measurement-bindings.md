# ADR-0009: A requirement declares what measures it

**Status:** Accepted · **Date:** 2026-09-12

## Context

The verification pipeline started out knowing the golden clevis. `_check_structure`
looked for `resolution["pivot_diameter"]`; `_check_envelope` compared against
`base_length`. Every gate passed, the evidence looked thorough, and the pipeline
could verify exactly one design — a fact that stayed invisible for as long as
only that design was ever verified.

That is the defect this ADR exists to prevent recurring, and it is worth being
precise about why it was dangerous rather than merely limiting. A design whose
parameters happened to be named differently did not fail loudly; its structural
requirement was simply never evaluated, and the report said `PASS` on everything
it *had* checked. The pipeline's coverage was an accident of naming.

A generated design has no such names. A model asked for a shaft bracket will call
its dimensions whatever the brief suggests, and the verifier has to measure the
requirement anyway.

## Decision

A requirement carries a **measurement binding**: a short string from a closed
vocabulary naming what, on the compiled part, produces the number to compare
against its threshold.

```json
{
  "id": "REQ_BORE_DIAMETER",
  "statement": "The shaft bore shall be 20 mm in diameter.",
  "threshold": {"magnitude": 20.0, "unit": "mm"},
  "comparison": "equals",
  "measurement": "interface_size:shaft_port"
}
```

The vocabulary lives in `forge_ir.measurements` and is closed on purpose:

| Form | Measures |
| --- | --- |
| `mass`, `volume`, `surface_area` | bulk properties of the solid |
| `bounding_box_{x,y,z}`, `centre_of_mass_{x,y,z}` | measured extents and centroid |
| `minimum_wall_thickness` | sampled thinnest section |
| `parameter:<id>` | a resolved design parameter |
| `interface_size:<id>` | the nominal size of a declared interface |
| `entity:<name>:<key>` | a dimension of published geometry |
| `safety_factor:bearing`, `safety_factor:pin_shear` | screening structural margins |
| `feature_count:<kind>` | how many features of a kind exist |

`forge_pipeline.measure.resolve_measurement` turns a binding into a `Quantity` or
into a stated reason there is none. A binding naming a parameter the document
does not declare, an interface that no longer resolves, or a mass on a component
with no material produces a `BLOCKED` gate naming what was missing. **None of
them produces a number.**

A numeric requirement with no binding is reported `NOT_TESTED`. It is not quietly
dropped, and it is not guessed at.

## Consequences

- The pipeline is design-agnostic. `_check_structure`, `_check_envelope` and
  `_emit_analysis_gate` were deleted rather than generalised.
- The vocabulary is part of the generated authoring guide, so the designer role
  is told exactly which bindings exist, and the guide cannot drift from the
  resolver because both are generated from the same table.
- Adding a new kind of check means adding a binding and a resolver branch, which
  is a deliberate act with a name, rather than a new `if` in the verifier.
- The distinction between *what the document declares* and *what the part
  measures* becomes visible and checkable. `parameter:base_length` and
  `bounding_box_x` are different claims: the first says the document still says
  60 mm, the second says the object is 60 mm. The golden example now carries
  both, and the injected-fault suite checks that each catches the fault its own
  way.

## Alternatives considered

**Infer the measurement from the requirement text.** A natural-language
requirement plus a model that guesses what to measure. Rejected: the failure mode
is a confident measurement of the wrong thing, which is worse than no
measurement, and it is unfalsifiable from the report.

**An open expression language for bindings.** More flexible, and it makes the
verifier evaluate arbitrary expressions written by a model. The closed vocabulary
means an unknown binding is a loud parse error at document-decode time rather
than a surprise at measurement time.
