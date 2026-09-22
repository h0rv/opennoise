# Phase 3 future ListenBrainz semantic completion receipt (2026-09-22)

## Scope

New offline ListenBrainz candidate replays emit a v2 candidate receipt with a
versioned completion receipt. It is a future replay contract only. It changes
no sealed v3 record, public artifact, policy, or deployment decision.

## Contract

The semantic completion identity binds the ordered content-addressed daily
source artifacts, complete fixed-window configuration, aggregation revision,
event-time coverage, and semantic result counts. Its SHA-256 is independent of
adapter module bytes, elapsed time, and peak RSS.

A separately hashed runtime-telemetry receipt binds that semantic identity to
the adapter key, adapter version, adapter-build SHA-256, elapsed milliseconds,
and peak RSS bytes. This preserves auditability of a particular execution
without treating machine-dependent telemetry or an import-path-dependent module
hash as semantic output.

Candidate replay reports remain versioned: existing v1 report schemas and
serialized content are unchanged, while new replays emit v2 receipt schemas
that require the completion receipt.

## Historical boundary

This receipt cannot reproduce or replace the sealed v3
`artist_co_listen_run` provenance. The historical completion projection still
includes its adapter-build SHA-256 and runtime telemetry in the parsed-record
fingerprint. The normalized-provenance comparator therefore remains strict and
the 2026-09-21 mismatch remains a real mismatch. See
`PHASE3_V3_LISTENBRAINZ_PROVENANCE_REPLAY_DIAGNOSIS_20260921.md`.
