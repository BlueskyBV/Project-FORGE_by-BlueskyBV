# ADR-0026: Spec schema versions, migrations and what the hash locks

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a

## Context

Stage 4b changes the spec's schema many times (frames, depth by geometry,
selections, loads, requirements, cages), and revision 5 adds derived values
resting on calculators, standard tables, material tables and solvers
(items 14, 27). A spec confirmed today must mean the same thing tomorrow.

## Decision

- **Every spec carries `schema_version`** (major.minor). A minor version
  only adds optional fields; a major version is a declared migration.
- **A migration is a pure function** from one version to the next, kept
  forever, and proven on the whole corpus and every kept part: the
  migrated spec is oracle-equal to the old (same shape, same checks). A
  migration that changes a verdict without changing geometry (a corrected
  table or calculator) lists every changed verdict, and those specs are
  judged again; none is changed silently.
- **The confirmed spec's hash covers** its content, its schema version, and
  what changes a value's meaning: calculators and the standard's edition,
  standard and material tables, files and tables it read (STEP, meshes,
  design tables), and stored proposals (item 28). The versions of the
  tools that judge (OpenCascade, meshers, solvers, external programs) go in
  each run's evidence and the cache key, so a tool update changes no
  confirmed spec (item 27).
- **Re-confirmation:** a family member (stage 7) or configuration whose
  migrated spec differs in anything shown at confirmation is confirmed
  again.

## Consequences

Old specs stay valid forever by migration, never by reinterpretation; a
correction anywhere upstream is visible as a list of changed verdicts.
