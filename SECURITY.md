# Security model

## Threat model

Forge processes three kinds of untrusted input, and treats all three as hostile
until validated:

1. **Model output.** ForgeIR documents and expressions proposed by a language
   model. Assume they may be adversarial, not merely wrong.
2. **Imported files.** STEP, STL, DXF, images, archives. Assume malformed,
   oversized, or crafted to exploit a parser.
3. **Retrieved documents.** Web pages, datasheets, documentation. Assume they
   contain prompt-injection attempts.

The assets worth protecting: the host filesystem, the user's credentials, the
integrity of the evidence graph, and the confidentiality of design data.

## Expressions: a structural boundary, not a filter

`eval` is never called. An expression is parsed with `ast`, walked once against a
closed allowlist of node types, and only then interpreted by a tree walker that
has no implementation for attribute access, imports, subscripting, lambdas,
comprehensions, or calls to anything outside a vetted table of 19 functions.

This matters: there is no sandbox to escape, because there is no interpreter that
could reach anything. An attempt at `__import__('os').system('id')` fails at
validation with `FE1002_DISALLOWED_CONSTRUCT`, before evaluation begins.

Budgets (512 nodes, depth 32) bound denial-of-service through pathological
expressions. `tests/test_expr.py::SecurityBoundary` exercises 18 hostile inputs.

## Generated code

ForgeIR is typed and does not execute. A `sandboxed_extension` escape hatch is
designed for operations the language cannot yet express, and may run only when
**all** of the following hold:

- the operation is genuinely not representable in current ForgeIR,
- the extension declares its inputs, outputs, bounds and expected semantic tags,
- execution is in a network-disabled, non-root container,
- filesystem access is limited to a disposable work directory,
- CPU, memory, process, output-size and wall-clock limits are enforced,
- the import allowlist excludes networking, subprocess control, host inspection
  and dynamic package installation,
- output solids pass the same deterministic gates as any other geometry,
- the report marks the feature as an escape hatch with reduced portability.

**Generated code never executes in the API or orchestrator process.** The escape
hatch is not implemented today; when it is, these conditions are the contract.

## Worker isolation

CAD and simulation workers run with a non-root user, no network, a read-only
root filesystem, a size-limited scratch directory, CPU/RAM/PID/file-size/time
limits, seccomp or AppArmor where available, an allowlisted set of binaries and
environment variables, no mounted Docker socket, no host home directory, no
credentials, and explicit process-tree termination on cancellation.

## File ingestion

Planned, not yet built, and listed so the gap is visible: extension and content
signature checks, decompression depth and size limits, path-traversal
prevention, entity/triangle/feature count limits, parser timeouts, metadata
sanitisation, and quarantine with structured error reporting.

## Prompt injection

System and project instructions outrank retrieved or imported content. Retrieved
documents are wrapped as quoted evidence carrying their source identity. The
model must never follow instructions found inside a CAD filename, a document, a
web page, an image, or model metadata.

The architecture limits the blast radius independently of whether the model is
fooled: a successful injection can at worst cause a *wrong design proposal*,
which the deterministic gates then evaluate on its merits. It cannot fabricate
evidence, because nothing in the probabilistic zone can write a `result` field
or change a `Status`.

## Secrets and data

Secrets exist only in environment or secret stores — never in the database,
logs, reports, prompts or artifacts. Model calls receive the minimum necessary
project context. A local-only mode, in which no design data leaves the
workstation, is a requirement of the design. Every run records whether an
external model provider was used.

As implemented:

- The API key is read from the environment (`ANTHROPIC_API_KEY`, or a variable
  named by `--api-key-env`) and from nowhere else. **There is deliberately no
  `--api-key` flag**: a key passed as an argument ends up in shell history and in
  `ps` output.
- The key is never serialised. It does not appear in a request log, an evidence
  node, a provenance record, a recorded fixture or a run report. A test asserts
  that nothing a run writes contains anything key-shaped.
- `ProviderInfo.is_remote` is recorded on every run, so the artefacts say whether
  the brief and the generated design left the machine. Pointing `--provider
  openai --base-url` at a local endpoint records `is_remote: false`, which is the
  local-only mode the design calls for.
- Recorded fixtures contain the full prompt and response. They are design data,
  not secrets, but a fixture library recorded from a real project should be
  treated as project-confidential and not committed to a public repository.
- Budgets are hard stops checked before a request is sent, so a runaway loop
  cannot spend past its ceiling while waiting to be noticed.

## Reporting a vulnerability

This is a pre-release research repository with no public deployment. Report
issues through the repository's normal channel.
