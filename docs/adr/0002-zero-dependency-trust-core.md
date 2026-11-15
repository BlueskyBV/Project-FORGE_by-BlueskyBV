# ADR-0002: The trust core depends only on the standard library

**Status:** Accepted · **Date:** 2026-09-11

*Superseded in part by [ADR-0034](0034-trust-core-dependencies.md) (10 November 2026): V2's trust core may also import NumPy and Forge's own compiled crate, and V2's Python floor is ADR-0023's. V1's five packages keep this record's rule.*

## Context

The reference specification proposed Pydantic v2 for the document model, which is
the conventional and generally correct choice for a Python API.

Forge has an unusual constraint, though. Everything the system asserts about a
design — every dimension, every margin, every pass or fail — bottoms out in the
units, expression, IR and evidence packages. Those four are the trust core. A
defect or a behaviour change anywhere in their dependency tree is a defect in
every claim the product makes.

Three specific requirements pushed against a validation library:

1. **Error paths must be RFC 6901 JSON Pointers.** When a language model emits an
   invalid document, the repair role is handed the pointer to the exact offending
   node and may rewrite that subtree only. "Validation error in features" is not
   actionable, and a library's error format is not ours to fix.
2. **No coercion, anywhere.** A string where a number belongs must be an error,
   not a silent `float()` call. Silent coercion is precisely how a unit-less
   magnitude gets past a boundary that exists to stop it.
3. **The sandbox.** CAD and solver workers run with no network and a minimal
   image. Every dependency in that image is attack surface and a version to pin.

## Decision

`forge_units`, `forge_expr`, `forge_ir`, `forge_evidence` and `forge_analysis`
depend on **nothing but the Python standard library**. `forge_geom` and
`forge_kernel` depend additionally on **NumPy and nothing else**.

The document model is a hand-written reader (`forge_ir.schema.Reader`) that wraps
a JSON value with the pointer at which it was found and hands out typed accessors
that extend the pointer as they descend. A JSON Schema is *generated* from it for
external consumers; the schema is not the source of truth.

Third-party libraries remain entirely welcome above this line: FastAPI at the API
boundary, Pydantic for request models, SciPy and Optuna in the optimiser, Gmsh
and CalculiX in the solver adapters. The rule applies to the trust core only.

## Consequences

**Good.** The core is testable in any Python 3.11+ environment with no install
step, which is how the whole test suite runs in a network-isolated container.
Error messages are exactly what the repair role needs. No version drift can
change what a document means.

**Costly.** A few hundred lines of decoding that a library would have provided,
and that code is now ours to maintain and test. Contributors accustomed to
Pydantic have something unfamiliar to learn.

**Rejected alternative.** Using Pydantic and post-processing its errors into JSON
Pointers. Workable, but it inverts the dependency: the error format we depend on
would be a by-product of a library's internals rather than a designed interface.
