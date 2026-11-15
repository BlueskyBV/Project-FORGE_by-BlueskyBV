# ADR-0032: Forge's own DXF reader re-opens every DXF it ships

**Status:** Accepted · **Date:** 2026-11-10 · Stage 4b.0a

## Context

R5 requires every shipped file to be re-opened and re-checked. Flat patterns
(4b.6) and drawings (stage 6) ship DXF, written by ezdxf. Re-reading them
with ezdxf would be the writer checking itself.

## Decision

A small DXF reader in the trust core, written from the DXF reference, for
exactly the entities Forge writes (LINE, ARC, CIRCLE, LWPOLYLINE, SPLINE,
TEXT and MTEXT, INSERT of Forge's own blocks), refusing any other. The
re-opened geometry is compared with the flat pattern's or drawing's
definition at its tolerance, as STEP and STL are today.

## Consequences

The DXF path meets R5 with an independent reader; the reader is small
because Forge controls what it writes.
