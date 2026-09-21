# Phase 3 replay policy-qualification gap

Bounded read-only diagnosis of the local replay candidate. No SQLite database,
sealed release input, or public artifact was changed.

## Bound inputs

| Input | SHA-256 |
| --- | --- |
| release manifest | `795992807586432e2b285e2ddca9a24a00a16e9fc83b6c382a3e914539333232` |
| replay candidate | `6dea0c5d81e690b2ee7e9ff989f71d596f218b71dc992e2b86294381122c3972` |
| replay receipt | `e29e9962046c5fc63426b66fde86cb6172bb3f1a8367a4080c94d62193ceecf2` |
| sealed public SQLite | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |

Both databases are schema 12 and pass `integrity_check` and foreign-key
checks. They have the same 62 `(source_key, artifact_sha256)` pairs, 4,948
`artist_genre_evidence` rows, and 603
`genre_music_qualification_observations`. The candidate's current snapshot
declaration hashes differ for all 62 inputs, as expected for its replay; the
receipt directly binds the manifest hash, release ID, candidate path, schema,
and 62 object hashes. Historical declaration replay is a separate check, not a
field embedded in this receipt.

## Exact gap

The candidate has 62 sealed policy rows. Its 54 Wikidata rows (policy IDs
1--54) are `public_domain`, `local_only=1`, with
`normalize=allow`, `local_search=allow`, and
`display=embed=export=train=deny`. The eight artist shards (IDs 1--8) own all
4,948 direct P136 rows: `1021, 723, 671, 637, 572, 531, 457, 336`.
The eight qualification shards (IDs 16--23) own all 603 qualification rows:
`77, 80, 81, 81, 79, 82, 83, 40`.

Consequently the candidate has zero `modelable_music_genres` and zero
embed-authorized direct rows. The sealed public database has the same factual
rows under non-local policy rows with `display=embed=export=allow`, yielding
603 modelable genres and 4,948 embed-authorized direct rows.

The remaining eight ListenBrainz rows (IDs 55--62) are not local-only and
already allow `embed` and `export`, although they deny `display`; therefore it
is inaccurate to say every replayed policy denies all three uses. They cannot
make a model alone because the qualifying/direct Wikidata evidence remains
ineligible.

`source_vault_replay._offline_wikidata_source` deliberately creates the local
declarations. Its historical-declaration helper uses `local_only=false` and
allows display/embed/export. The regular policy bootstrap keys a source policy
as `manifest:<source_key>:<artifact_sha256>` and does `INSERT OR IGNORE`.
Thus replaying a historical declaration *into the existing candidate* cannot
correct the sealed local policy: policy version 1 already exists and is
immutable/sealed.

## Why the current projector cannot repair it

`candidate_public_projection` calls `_build_model` before it calls
`_release_policy_id`. The latter creates only `release:phase3-public-20260831-qualified`;
that policy has `normalize=deny` and is suitable for the derived model, not
for source provenance. It cannot authorize the source evidence used by model
queries.

Changing the candidate's policy rows, permissions, provenance rows, evidence,
qualification rows, snapshots, or artifacts in place is invalid even on a
copy: policies, provenance, source artifacts/snapshots, evidence, and
qualifications are append-only, and evidence/qualification policy IDs must
equal their provenance policy IDs. Cloning the facts under a new policy would
also require new provenance and fingerprints and would silently alter model
references/counts. It is not a safe release projection.

## Narrow next implementation contract

Do **not** add an effective-policy overlay. The modelable-genre SQL view and
the repository/publication permission joins intentionally read sealed policy
rows; an overlay would introduce a second, unsealed policy semantics across
those paths.

Instead, add a distinct no-replace replay mode that reconstructs the historical
Wikidata declarations with `_historical_wikidata_source` **before its first
policy bootstrap/write**, rather than replaying into this local-policy
candidate. It must:

1. Read the original manifest and require its SHA, release ID, 62 exact
   `(source_key, artifact_sha256)` rows, and all 62 historical declaration
   hashes reproduced by `replay_historical_source_declarations`. The candidate
   receipt hash is evidence for the local replay only; it must not be relabeled
   as a binding for this separate historical-declaration replay.
2. Create a previously absent destination and stage a new SQLite database
   within that destination. Bootstrap every source policy from the historical
   declaration at initial ingest, then seal it. In particular, the 54
   Wikidata policies must be non-local and allow display/embed/export as the
   historic declaration specifies. Never reuse or mutate the current candidate,
   its policy IDs, the sealed database, manifest, receipt, or vault.
3. Rehash every already manifest-bound raw object before ingest and require the
   regenerated ListenBrainz joint artifact to equal its sealed object. Bind the
   resulting experimental receipt to the manifest SHA, all declaration hashes,
   raw object hashes, schema, and database SHA; fail if any source declaration
   conflicts with the historical one.
4. Only then build the model from that separate database, require the manifest
   input/settings/logical hashes and all 62 exportable input resolutions, and
   run the existing model gate plus integrity/foreign-key checks. Create the
   derived release policy only after the model passes, for the derived output.

The outcome is a local experimental reconstruction, not public certification,
replacement of the sealed release, or a claim of SQLite byte identity. This
preserves the exact policy findings above while testing the historical policy
constructor at the only safe boundary: before initial source policy creation.
