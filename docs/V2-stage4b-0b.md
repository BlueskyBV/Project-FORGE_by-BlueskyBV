# Forge V2, stage 4b.0b: a module per kind

Status: design, revision 2, 10 November 2026. Revision 1 was reviewed
adversarially the same day (17 findings; section 9 says what changed). It
is done once 4b.0a′'s OpenCascade 8.0.1 replay passes, on the Python that
replay ran on, and before the move to CPython 3.14, which is replayed on
the restructured code (ADR-0035, the owner's order). Companion to
[V2-stage4b.md](V2-stage4b.md), 2.1 and 2.2 item 6.

---

## 1. What it does, and what it must not

**Does:** every program's per-kind code moves behind registries, one
module per kind and role; dispatch on a kind outside those modules is
forbidden by a lint that ratchets to zero; slots are reserved, by name and
owner, for what later stages need. **Must not:** change anything any
program computes. It is proven by byte-identical results (section 6).
Nothing else changes, with one exception made first and on its own (6.1).

**Where things stand** (10 November 2026): 592 sites dispatch on an
item's kind, in 17 files, with about 110 per-kind handlers: the spec 209
(placement 99, views 56, compare 29, checks 23, render 2), the generator
165 (generator 151, grading 14), the checks and oracle 151 (place 68,
oracle 45, compiler 37, capabilities 1), the planner 67. `forge_occ`,
`forge_kernel`, `forge_geom` and `forge_cli` dispatch on ForgeIR ops and
surface types, never on items. Pattern modes (seven: corners, rectangle,
ends, row, grid, circle, arc, from `draft.PATTERN_FIELDS`) are a second
dispatch of the same shape.

**Step 0, before any move:** a function-level inventory, every per-kind
function and every site mapped to the protocol method that will hold it,
from which the protocols of section 3 are derived and checked complete.
**Done 10 November 2026** (kept with the 4b.0b notes, outside the project,
and lost with the cloud workspace on 11 November; made again on 14
November and kept in the project: [V2-stage4b-0b-inventory.md](V2-stage4b-0b-inventory.md),
its table remade by `tests/v2_kind_sites.py`, 734 sites in 218 functions by
its stricter count): 600 sites, not 592
(eight more in views, the planner and the generator's draw tables), in 182
dispatching functions, with 115 per-kind handlers (and render's 16
template lambdas); 148 of the sites dispatch on another item's kind (a
modifier's target, a standing item's host) and become methods the target
publishes; 22 chains have branches whose order matters, each listed.

## 2. The layout: role first, fenced

Programs that the architecture keeps apart stay apart, file by file:

| Package | Role subpackages (`<package>/items/<role>/<kind>.py`) |
|---|---|
| `forge_spec` | `solve` (the placement solver), `views` (confirmation views), `compare` (two drafts), `checks` (spec checks), `words` (the sentence template) |
| `forge_plan` | `plan` (constructions, tools, edges) |
| `forge_checks` | `oracle`, `place` (the judge's own placement), `compile` (the check compiler) |
| `forge_eval` | `draw` (the generator's draw), `brief` (the brief's words: `_draft`, `_item_said`, `_rounding_said`, `_OPTION_WORDS`), `truth` (its shape model), `grade` (spec grading) |

- **The fences follow the roles.** The import-graph test keys R2's rules on
  role paths: `forge_spec.items.solve` joins the solver modules the oracle
  (`forge_checks`) and the generator's truth (`forge_eval.items.truth`, beside
  `truth.py`) may not import; the rule that makers never read a nominal
  covers `forge_spec.items.solve` as it covers `placement.py`; the
  generator's `truth` role may not import its `grade` role or the solver;
  the oracle, place and compile roles keep today's directions (compile may
  use oracle, oracle may use place) and no others; inside `forge_spec` the
  checks, compare and views roles may use the solve role (they do today:
  `edges_of`, `height_of`, `footing_values`, `_outline`). The generator's
  draw and truth both read `OPENABLE` and `ROUNDABLE`, which live in its
  `items/_common.py`; truth still never imports grade or the solver. New:
  `forge_spec` never imports `forge_plan`, `forge_checks` or `forge_eval`.
- **A kind module names only its own kind,** enforced inside `items/` by
  the lint. What another kind needs from it (a body's edge roles and rims,
  walls, faces a standing item may host, a threadable surface, whether it
  can be hollowed) the kind publishes through its role's protocol, and
  the modifier or standing item asks through the registry. A new kind
  never edits another kind's module (2.3's "confined to its kind modules").
- **Shared helpers and constants** (`oracle._THROUGH`, placement's `EPS`,
  the box-like outline) move to leaf modules in the role
  (`items/<role>/_common.py`, family helpers `_boxes.py`), imported by
  the role's kind modules and the program, never importing either: no
  cycles. Handlers receive a narrow context object, never a program
  class's `self` (the check compiler's `_box_body`, `skip`, `tol` become
  the context's).
- **Pattern modes** are laid out as the modes of the pattern kind 4b.4
  will make an item (`items/<role>/pattern.py`, one handler per mode), so
  4b.4 extends them rather than redoing them.

## 3. Registries and protocols

- **A registry per program and role,** built by importing every kind
  module by name (no discovery at run time), its order KINDS' order, so
  every aggregate keeps its order; the per-mode entries follow (ADR-0027's
  unit is a kind and mode).
- **The machinery is one small generic class** (a registry over a
  dispatch domain, with its totality test), in an L0 package, used for
  kinds and modes now and for item 26's domains later (load types,
  solvers, meshers, calculators, optimisers, formats, derived products):
  one mechanism, not one per domain.
- **Data-defined entries:** user-defined features (item 20) are kinds that
  exist only as data. The registry takes them from the confirmed spec's
  library, hash-locked (ADR-0026), expanded into ordinary items before
  confirmation, so no module is needed for them.
- **Protocols per role,** derived from step 0's inventory, covering every
  site it finds, including the ones revision 1 missed: order (placement
  `_order`/`_make_order`, the judge's `_sequence`/`_order`, the planner's
  `_parts`), placement's shape, overlap, reach, flat-instance and the
  hole and shell pre-passes of `solve`, the planner's air boxes, the
  oracle's hollows, threads, letters and cut nodes and whether a step is
  made per item or per copy, the judge's round copies, hollows, flat cuts
  and lies-on, the compiler's main, sides, edge references and seams,
  compare's contrast and cut edges, views' inside, windows and cut spans,
  the spec checks' missing edges, and grading's four.
- **Methods reserved now, as "not yet: 4b.0c or 4b.0d"** (so those steps
  fill them, never add them): what an item acts on, its canonical order
  rank and `as_of` (item 11); its face and edge roles and their evaluation
  (item 12); its migrations (item 14); its classes per field and mode
  (item 18, replacing today's single `verification` string); composite
  expansion (item 20); its guide entry and family (item 23); the tables and
  editions it reads (item 27); what it resolves before confirmation (item
  28).
- **The generator's draw** gets a per-kind draw weight and host predicate,
  and today's weighted list is rebuilt from them in today's order, so
  every seed draws exactly as before; a kind added later is drawn from its
  own named random stream (as `_decorate` is), so adding a kind never
  re-draws an old seed and 2.4's replays stay valid.

## 4. The reserved slots: owner, layer and judge

Item 6's slots, each reserved in the package that will own it, with the
independent program that will judge it (R2). Names and owners are fixed
now; signatures are provisional until 4b.0d's conformance matrix (they
will take 4b.0c's frames and 4b.0d's bodies and roles).

| Slot | Owner (layer) | Judged by |
|---|---|---|
| Confirmation and drawing view | `forge_spec` views (L0) | stage 6's drawing re-measured by `forge_checks` |
| Print-spec rule | the print-spec package (stage 6, L1) | `forge_checks` and the generator's own transform (plan 4.8) |
| Manufacturability per process | `forge_checks` (L0), as checks | mutation-tested (plan stage 6) |
| Parametric script writer | `forge_occ` (L1) | the script rebuilt and compared by the judge |
| What a resize moves | `forge_memory` (L3) | the resize's new confirmation and the gate (item 28) |
| Interfaces for mates and actuators | `forge_spec` (L0), published in the spec | stage 8's checks in `forge_checks` |
| Analysis representation | the analysis adapters (above L0, ADR-0034) | face accounting of the FE mesh in `forge_checks` (item 26) |
| Agent operations (stage 5) | `forge_occ`'s constructions (L1) | the gate, as any construction |

## 5. The lint: a ratchet from the first day

- **The rule,** in `tests/test_v2_architecture.py`, over every V2 module
  (V2's modules in V1 packages included: `forge_cli/spec.py`,
  `forge_roles/spec_writer.py`, the gate in `forge_orchestrator`):
  outside the registries, the `items/` role modules and the wire and draft
  layer, no reading of an item's kind or category except as a registry's
  key (`REGISTRY[item.kind]`); no comparison of anything with an item-kind
  or pattern-mode literal, or a tuple, list, set or name bound to them, by
  `==`, `!=`, `is`, `is not`, `in`, `not in`, substring, prefix or suffix;
  no `Category` member or its `.value` compared; no `match` on them; no
  dict, set or list display (or `dict.fromkeys`, comprehension, keyword
  `dict(...)` or subscript assignment) keyed or filled by two or more of
  them; no `getattr` built from a kind; no module constant bound to a kind
  literal. The literals come from `KINDS` and `PATTERN_FIELDS`, so a new
  kind joins the rule by being added.
- **No line allowlist.** Packages that cannot see items (`forge_occ`,
  `forge_kernel`, `forge_geom`: the import-graph test keeps them from
  importing `forge_spec`'s items) are outside the rule by package. Where a
  non-item kind shares a name (the edit kind "text", the check kind
  "thread"), the comparison is written against its own enum member
  (`EditKind.TEXT`), an equivalent change the fingerprint proves.
- **A ratchet from step 1:** a test counts the remaining sites per file and
  fails if any count rises; the count reaches zero at step 7, and the rule
  is then absolute.

## 6. The proof: byte identity on every path

### 6.1 One change first

`planner.py`'s preview reports its first gap from iterating a set, so its
reason depends on Python's hash seed: a reproducibility fault (R9), fixed
on its own before the baseline, with a test, and the fingerprint run
under two hash seeds from then on.

### 6.2 What is digested, per seed and per case

Every output of every program and everything the judge consumes, in the
order emitted (order is behaviour), floats by `float.hex`:

- the spec: the solved placement, the solver's issues, assumptions and
  questions; the spec checks' problems; the rendered sentences; the
  confirmation views' SVG; the two-draft comparison's features;
- the planner: the ForgeIR document, its alternatives, and any exception
  with its message;
- the checks: the compiled check suite in order; the nominal values; the
  oracle's node tree, its expected topology and volume; the capability
  table; the judge's own placement and its comparison of layouts; the
  `Unchecked` and `Rounded` lists; the full judge's verdict and its first
  failing check;
- the generator: the plan, the brief's text, the truth, the mutants and
  impossible parts it draws, and spec grading;
- the guide and the JSON schema built from `KINDS`.

The harness calls only entry points that don't move, records its own hash
with the baseline, and pins NumPy and the machine.

### 6.3 Every path, not only valid parts

Each change set runs on: a fixed 1,000-seed sample; every mutant and
impossible part those seeds draw; the corpus; every kept regression; and
the whole test suite. (Scaled by the owner's decision, ADR-0036: a file's
change set runs the sample's first 100 seeds and its covering tests; a
role's end the whole sample, the regressions, the suite and the verdicts
on built parts of 100 seeds; the corpus, in `eval/`, is left out.)
**Coverage of each moved function's old body** is
measured: every branch is hit by those runs, or it is listed and reviewed
before the move, with a case written for it (the fault, CAN'T and question
paths: `_check_shape`, the shell faults in `solve`, `_check_exits`, fits
and severs, `_physical`, the planner's gap for a kind it doesn't serve).

### 6.4 Baseline and end

- **Baseline:** on the 8.0.1 tree after its replay and 6.1, on the Python
  that replay ran on (ADR-0035), before any move.
- **Each change set:** every digest equal under both hash seeds, or the
  change set is wrong; no difference is explained away.
- **At the end:** all 10,000 seeds with their mutants and impossible parts,
  the corpus and the regressions, every digest equal; the lint at zero;
  the totality tests green; then the review.

## 7. The order

0. The function-level inventory, the protocols derived from it, the family
   tuples' table (section 8) completed.
1. The harness and its baseline (after 6.1); the lint's ratchet on.
2. The generic registry, the role subpackages and protocols, filled with
   thin wrappers that call today's functions: the plumbing proven before
   anything moves.
3. The moves, role by role, each file a change set, each chain's
   overlapping branches listed and their order kept: the spec (words,
   checks, compare, views, solve), the planner, the checks (capabilities,
   compile, oracle, place), the generator (grade, truth, draw).
4. The family tuples, as section 8 decides.
5. Pattern modes, as the pattern kind's modes.
6. The reserved methods and slots, names and owners, with their totality
   tests.
7. The ratchet at zero, the full fingerprint, the review.

## 8. The family tuples

A tuple becomes a fact of the kind's written definition (an attribute of
`KindSpec`, which any program may read as it reads the confirmed spec)
only when the definition states it, it is something a spec may validly
say, and every program's tuple agrees; otherwise it becomes an attribute
of that program's own role modules. The generator, the third
implementation, keeps its own copies of any schema fact, diffed against
the schema by a test, so a wrong fact can't pass unseen. Decided at step 0
from the inventory, and checked by membership before and after each move:

| Tuple | Where | Proposed fate |
|---|---|---|
| `_HOLLOWABLE` | placement | **schema fact, confirmed**: shell.md states it (a block, a cylinder or a sphere) and all seven copies agree; a new `KindSpec` attribute, the generator's copy diffed |
| `OPENABLE` | generator | the generator's own (in `items/_common.py`, read by draw and truth), its order kept (it feeds `rng.choice`); diffed as a subset of `KindSpec.faces` |
| `ROUNDABLE` | generator | the generator's own (`_common.py`); diffed as a subset of `KindSpec.edges` per kind and first or standing |
| `_RIMS` | checks `place.py` | the place role's own, each kind publishing its rims (names equal `KindSpec.edges`; the pairs are its own) |
| `_BOXES`, `_RODS`, `_ROUND` | compare | the compare role's own (none derivable: a tab's box depends on its end) |
| `_ROUND_KINDS`, `_BOX_KINDS` | views | the views role's own |
| `_OUTLINED` | views | the views role's own, diffed against a fact derived from the schema (the kinds with a profile field), which every program's copy agrees with |
| `_BODIES`, `_STANDING` | planner | the plan role's own (equal to `Category` BODY and ADD by membership) |
| `_CUTS` | planner | the plan role's own (CUT less text: not the category) |
| `_BOXES` | check compiler | the compile role's own, diffed against the schema-derived fact (the kinds whose faces include all six directions) |
| `_IMPLICIT_CANT` | capabilities | each kind's capability entry, in the compile role |
| `_SIDED` | generator | the truth role's own (`_cuts_sided`) |
| `_OPTION_WORDS` | generator | the brief role's own; each word diffed as one of its option's synonyms |

Family-shaped sets written inline (the straight box set six times, the
threadable set six, the cut set nine, the rounding set fifteen lines,
`made_last` twice) become kind-published facts of the role that uses them.
Two findings are left for 4b.0d, not changed here: placement's `edges_of`
and the judge's `body_edges` cover different kinds (item 12's roles will
make one contract), and `compile_checks` repeats its own dispatch for the
region kind.

`Category` itself stays a schema fact (what the item does to the part), but
choosing how to build or judge by it is dispatch, so it is read only as a
registry's key or inside a kind module.

## 9. What the review of revision 1 changed

| Finding | This revision |
|---|---|
| Kind modules merged code the architecture fences file by file (R2, makers never reading nominals) | Role-first layout, fences keyed on role paths, `forge_spec` forbidden to import the other programs (section 2) |
| The fingerprint left out what the judge consumes, exceptions, grading, mutants, the guide | Section 6.2: every output and every input of the verdict |
| Identity proven only on valid seeds' paths | 6.3: mutants, impossible parts, corpus, regressions, the suite, branch coverage of every moved body |
| The lint missed `is`, family names, kinds under other names, `match`, lists, comprehensions, `.value`, constants | Section 5: kind and category reads forbidden but as registry keys, every form listed, a ratchet from day one |
| Dispatch across kinds inside `items/` | A kind module names only its own kind; targets publish what modifiers need |
| Slots with no owner, layer or judge | Section 4's table; signatures provisional until 4b.0d |
| Import cycles and handlers using program internals | Leaf helper modules, a narrow context |
| Hash-seed and order dependence | 6.1's fix first; registry order KINDS' order; outputs digested in order, floats by hex, two hash seeds |
| The generator's draw table would re-draw seeds | Per-kind weights rebuilt in today's order; later kinds on their own streams |
| Protocols from a coarse inventory | Step 0: a function-level inventory first |
| Later items' needs not reserved | Section 3's reserved methods; one generic registry for every domain; data-defined kinds |
| False positives on a line allowlist | Packages that can't see items are outside by package; non-item kinds compared through their own enums |
| Family tuples' fate deferred | Section 8's table, confirmed at step 0 |
| Seven pattern modes, as the future pattern kind's | Section 2 |
| The lint last; signatures fixed too early | The ratchet at step 1; names and owners now, signatures at 4b.0d |
| One `forge_checks` module per kind mixed three programs | Roles `oracle`, `place`, `compile` |
| Lint scope | V2 modules in V1 packages included; the Rust core holds no kinds; a clone check between programs' modules, later |
