# ADR-0011: A model call is reproducible, or it is not evidence

**Status:** Accepted · **Date:** 2026-09-12

## Context

The deterministic core is reproducible by construction: the same document
compiles to the same part hash and the same measurements on any machine. The AI
layer is not — a model is sampling, and no amount of care makes two calls
identical.

What *can* be made reproducible is everything around the call: the prompt that
was sent, the answer that came back, and the run that resulted from them. Without
that, a design run is an anecdote. You cannot diff two attempts, you cannot
re-examine a bad one, and you cannot test the loop without paying a provider
every time.

Two defects, both found by trying to replay a recorded run rather than by
reading the code, showed how easily this is lost.

**A random identifier inside a prompt.** The designer's message ended with
"use `document_id` `<uuid4()>`". Every call therefore had a different prompt.
Nothing failed; the cost was silent. Recorded runs could not be replayed past the
first call, two runs of the same brief produced documents that could not be
compared, and provider-side prompt caching could never hit.

**A recorder that tidied what it recorded.** Fixture files were written with
sorted keys, for readable diffs. In a single-call test that is harmless. In a
chain it is fatal: the recorded answer feeds the next prompt, so reordering its
keys changes that prompt's text and therefore its fingerprint, and replay stops
at call two with a fixture miss.

## Decision

**Prompts are a pure function of their inputs.** Identifiers the designer needs
are derived — `uuid5` over the intent and requirements — rather than drawn from a
random source, and a caller with real project identity passes one in. The same
inputs describe the same document, so they get the same identity; changed inputs
get a new one.

**A fixture is a faithful record, not a tidied one.** Recorded responses are
written byte-for-byte as they arrived. Readability of the file is worth less than
the replay it would break.

**A request's fingerprint is the hash of everything that determines the answer**
— system prompt, messages, schema, temperature, token limit. A fixture is looked
up by that fingerprint, and a miss is an error naming the purpose that missed. It
is never a fallback to a nearby response, because the usual cause of a miss is a
prompt that changed, and answering it from a stale fixture lets the change pass
tests it was never run against.

**Recording is a flag, not a mode.** `forge design --record DIR` wraps whatever
provider is in use. A real run costs money once; reproducing it costs nothing and
is identical rather than merely similar.

## Consequences

- The whole AI layer has an offline test suite. `tests/test_cli_design.py` runs
  the real CLI, orchestrator, compiler and verifier against a library recorded
  from hand-written responses — no key, no network, no flake.
- A prompt change invalidates its fixtures loudly, and re-recording is one
  command. Keeping fixtures honest is cheaper than working around them.
- Runs of the same brief are comparable. The document identity is stable, so two
  attempts differ only where the design differs.
- The stakes are stated in the run itself: `ProviderInfo.is_remote` records
  whether design data left the machine, and the API key is read from the
  environment and never written into a report, a fixture or a provenance record.
  There is deliberately no `--api-key` flag; a key on a command line ends up in
  shell history and in `ps` output.
