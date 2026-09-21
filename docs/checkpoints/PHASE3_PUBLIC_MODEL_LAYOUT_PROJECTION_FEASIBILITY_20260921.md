# Phase 3 public-model/layout projection feasibility

This is a bounded read-only audit of the completed local candidate
`/tmp/phase3-combined-replay-46cfc23.sqlite`.  It neither projects nor promotes
the candidate, writes a public/static artifact, or scans the source vault.

## Result

The projector mechanics are available for a fresh, independently writable copy
of the candidate, but the missing derived-release stage is currently blocked by
the candidate's local-only policy/qualification state (see the recorded attempt
below). No raw objects are needed for the attempted boundary check: the candidate has
the exact 62 `(source_key, artifact_sha256)` rows in
`config/releases/phase3-public-20260831/release-manifest.json`; its current
snapshot/declaration hashes intentionally differ from the historical manifest.
The combined replay receipt binds the manifest, verified raw objects, and the
completed candidate replay; historical declaration-hash verification belongs to
the separate declaration-replay report. Its source
database hash is `6dea0c5d81e690b2ee7e9ff989f71d596f218b71dc992e2b86294381122c3972`.
It is schema 12, has clean integrity and foreign-key checks, and has no public
model, layout, current-selection, or public graph rows.

The historical `build_public_release.py` command is *not* the safe direct
entry point: its `verify_manifest_against_database` intentionally requires the
manifest's schema-10 cache before it clones and migrates that cache.  It will
reject this schema-12 candidate before projection.  Do not edit the sealed
manifest's `catalog_schema_version` in a temporary copy merely to bypass that
check; that would sever the replay receipt's manifest hash.

## Existing implementation path

Use these existing functions, with the original manifest and selection files
read-only:

1. `PublicModelRepository(copy, copy).load(PublicInputLoadSettings(...))` and
   `build_public_model(...)` (also exposed by `scripts/build_public_model.py`)
   construct the model and all four layout lenses from the copied database.
   The catalogue and ListenBrainz inputs are the same candidate copy.
2. Compare `input_sha256`, `settings_sha256`, and `output_sha256` with the
   manifest through `opennoise.pipeline.public_release._require_expected_model`.
3. In the copy only, create/resolve the release policy with
   `_release_policy_id(connection, "phase3-public-20260831-qualified")`, then
   call `publish_public_model(copy, model_json, policy_id=...)`.  It persists
   provenance links, graph explainability rows, layouts, points, and current
   selections atomically in its SQLite transaction.
4. Run `scripts/evaluate_public_model_gate.py model.json --report gate.json`.

There is no existing CLI that combines steps 2--3 while allowing a
receipt-bound schema-12 candidate.  The smallest implementation change for
the next gate is a narrow candidate-projector CLI that accepts: the original
release directory, an original-candidate SHA-256, a fresh output directory,
and the candidate database; it must require schema 12 and exact manifest
`(source_key, artifact_sha256)` rows, clone before opening read-write, and
then use the functions above.
It must not accept an arbitrary manifest schema or an existing destination.

## Safe no-replace execution shape

After that thin CLI exists, use a unique directory created exclusively by
`mkdir` and keep every mutable output inside it:

```sh
out=/tmp/phase3-public-projection-46cfc23
test ! -e "$out" && mkdir -m 700 "$out" \
  && uv run python scripts/project_phase3_candidate_public_model.py \
    --release-directory config/releases/phase3-public-20260831 \
    --candidate /tmp/phase3-combined-replay-46cfc23.sqlite \
    --expected-candidate-sha256 6dea0c5d81e690b2ee7e9ff989f71d596f218b71dc992e2b86294381122c3972 \
    --replay-receipt /tmp/phase3-combined-replay-46cfc23.receipt.json \
    --expected-replay-receipt-sha256 e29e9962046c5fc63426b66fde86cb6172bb3f1a8367a4080c94d62193ceecf2 \
    --output-database "$out/candidate-serving.sqlite" \
    --model-output "$out/public-model.json" \
    --report-output "$out/projection-report.json"
```

The named projector is local-only and requires the receipt hash as well as the
candidate hash.  It uses an independent verified copy, never a hardlink to the
input, and creates each final file without replacement within `$out`.  No path
defaults to `data/public.sqlite`, `data/model`, a sealed cache, or a static-site
directory.

Historical-declaration receipt v1 does not embed a candidate database SHA-256;
the CLI's explicit expected candidate SHA-256 is checked separately. The result
remains a non-certified local projection; a future receipt revision may embed
the database hash.

## Required checks and expected result

The model must match the sealed logical boundary exactly:

| Check | Expected value |
| --- | --- |
| model input SHA-256 | `70c5c40f6206eb3895203e61864b62cf361532d02c1c61535281f22ce5fced6e` |
| settings SHA-256 | `d27fa893459f5480e663253972191b5b90c3ab616cfaad49facc15c645ee22b0` |
| logical output SHA-256 | `e327045074fc6bb4e3b2e1c14410b3f337b6822e048c6038aa18703a11d2108b` |
| lenses / layout points | 4 / 2,002 |
| per-lens points | public 468; direct 468; community 468; taxonomy 598 |
| names / representatives | 603 / 3,344 |
| profile memberships / neighbors | 26,525 / 34,348 |
| input provenance | all 62 declared artifacts resolve exportably |

Also require a passing public-model gate and clean integrity/foreign-key
checks on the output copy.  The known bounded build recorded about 5.6 seconds
and 371,539,968 bytes peak RSS for the model; individual layout construction
was below 0.3 seconds each.  Reserve at least 0.5 GiB RAM and approximately
the candidate size plus a 28 MiB JSON artifact on filesystems without reflink
support (roughly 180 MiB for one mutable SQLite copy).

## Equality boundary

Logical equality is the three model hashes above; lens outputs
`7e2cae1eaee670096ba8e9ace2ef92f7bbca8599715ccbb74f1c83c16a4d1f7b`,
`6a1f6dd35fc50edac2a9dcb03a75ce733122f645cf16c545c095a911154300c4`,
`0f3b2927cedb8d2270211e3207166c3fb23fa984f5936939ec3c23bcd5bf4c06`, and
`9cb4c0b459a7a19040447f97afbbb15b8a5c1e3cc5494000b2fe1c5195c3eaf4`; the
complete persisted row/count checks; and exact provenance resolution to the 62
manifest artifacts.  The candidate source snapshot/declaration hashes are not
part of that equality criterion, because its replay intentionally creates new
current declarations.  This is sufficient to establish the previously missing
derived-release stage.

Byte identity is not an acceptance criterion.  The historical manifest records
model-file SHA-256 `ffbe49…`, whereas the currently retained deterministic
logical artifact is 28,043,097 bytes with file SHA-256 `c9964b…`; the existing
release receipt already records that distinction.  Publication also creates
timestamps, policy/provenance rows, SQLite page allocation and FTS/WAL state.
Without a separately fixed timestamp, policy-row identity, serializer, SQLite
build, journal/checkpoint, and vacuum contract, a copied candidate cannot
meaningfully be required to match the sealed database bytes.

## 2026-09-21 local projection attempt

One authorized projection invocation used the command above with the pinned
candidate hash `6dea0c5d…c3972` and receipt hash `e29e9962…ecf2`, writing only
to the previously absent `/tmp/phase3-public-projection-46cfc23` directory.
It failed before model artifact creation, publication, layout persistence, or
final output publication after 4.60 seconds (`user` 5.79 seconds, `sys` 0.62
seconds). The output directory contains no files; the candidate and receipt
still hash to their pinned values.

The source candidate remained `PRAGMA integrity_check: ok` with no
`foreign_key_check` rows after the attempt. Process peak RSS is unavailable in
this environment because `/usr/bin/time` is absent; no model-build resource
record exists because construction stopped during input loading.

`PublicModelRepository` found zero eligible genres and direct memberships, so
`PublicModelInput` rejected the empty input. Small read-only checks found
4,948 direct-source evidence rows but zero `modelable_music_genres` rows and
zero evidence rows with an allowed `embed` permission. The replayed source
policies are `local_only=1` and deny `display`, `embed`, and `export`; that is
the correct current candidate policy boundary, not a projector malfunction.

This gate is **blocked**, not a logical-equality result. No model hash, layout
hashes/counts, graph counts, public-model gate report, or serving SQLite output
exists. Do not rerun this projector until a separately approved, receipt-bound
policy/qualification projection defines how the replay candidate may acquire
the required modelable genres and public embedding permissions.
