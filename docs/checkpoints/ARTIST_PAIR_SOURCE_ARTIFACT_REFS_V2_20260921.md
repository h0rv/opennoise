# Artist-pair source-artifact refs v2

`PublicInputLoadSettings.artist_pair_evidence_ref_version` defaults to
`attempt_ids_v1`. That path is unchanged for sealed v1 model-input replay.

The opted-in `source_artifacts_v2` path keeps pair selection, privacy support,
window counts, permissions, and suppressions unchanged. It replaces only each
pair's provenance string with a sorted, deduplicated source-backed reference:

```text
listenbrainz:v2:source_key={percent-encoded key}&snapshot_ref={percent-encoded snapshot}&artifact_sha256={sha256}
```

The reference is derived from the completed co-listen run's immutable source
artifact, snapshot, and source. It therefore survives SQLite insertion-order
changes to surrogate attempt IDs. A v2 input has a new model-input hash and is
an experimental boundary; it does not match or amend a sealed v1 manifest.

## Superseding compact contract

The verbose v2 representation above is retained as an immutable diagnostic
contract. Its repeated source/snapshot text made the experimental artifact
38,823,505 bytes, above the 32 MiB pre-release size gate. New experimental
work must opt into `source_artifacts_v3`, which preserves the same source
identity but emits this fixed 70-character token instead:

```text
lb:v3:<sha256(canonical-json([source_key,snapshot_ref,artifact_sha256]))>
```

Tokens are resolved only against the exact attested source-artifact inventory.
An unknown or multiply matching token fails closed. V3 is a new input-hash and
receipt boundary; it does not alter, replace, or claim replay of v1 or v2.

The optional `project_phase3_candidate_public_model.py --source-artifacts-v2`
projector is likewise local-only. It keeps the detached historical binding and
fresh no-replace outputs, attests the manifest's 62 exact
source/snapshot/artifact tuples, and uses the release-sized limits of 100,000
direct memberships, 250,000 artist pairs, and 25 neighbors per genre. Its v2
receipt records the newly built model hashes and positive graph gate; it never
compares them with the sealed Phase 3 model hashes or fixed Phase 3 row counts.
