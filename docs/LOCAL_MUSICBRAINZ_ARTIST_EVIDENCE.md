# Local MusicBrainz artist evidence

This local query reads a completed MusicBrainz release-group research database. It does not add a source, parse the 714 MB artist and tag artifact again, or alter the public catalog.

The query returns two separate sections. `artists` or `seeds` comes from `direct_anchor`. A row joins one stable 6,291-name seed ID to one exact MusicBrainz artist ID. The `facet` field remains visible as either `musicbrainz_genre` or `musicbrainz_tag`. These are direct claims from the earlier artist extraction.

`album_supported_artists` or `album_supported_seeds` comes from `release_group_support`. It is release-group support through an exact credited artist MBID, not direct artist membership. Each result exposes the source facets, each facet's distinct release-group count, and a combined distinct release-group count that deduplicates the same release group when it occurs in both facets. It does not promote a support-only row to `artists` or `seeds`.

The source artifact's contextual tag rows are not copied into this database. The query reports `contextual_claims_available=false` rather than treating a direct tag match as contextual evidence.

The reconciliation sidecar supplies every stable seed ID, its source external ID, name, and disposition. A seed query accepts a stable ID or an exact reviewed search term. For example, the existing `IDM` alias resolves to `item887`, `intelligent dance music`. It does not use a new fuzzy matcher, public identity guess, or name-only artist join.

The current small sidecars are `.cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json` and `.cache/musicbrainz-full-seed-targets/pipeline/musicbrainz-model-adapter-report.json`. They verify against each other and bind the seed vocabulary to target hash `1cfe14b7dfce41c5f1b45c423407c7c1ad528abbafa3b3b859770e49c8debe46`. The candidate database and artifact paths below become usable only after the release-group builder writes both final files.

Run the query only against a completed local research database and its matching reconciliation artifact:

```sh
uv run python scripts/query_local_musicbrainz_artist_evidence.py \
  --evidence-db .cache/musicbrainz-release-group-evidence-candidate-v1/evidence.sqlite \
  --evidence-artifact .cache/musicbrainz-release-group-evidence-candidate-v1/artifact.json \
  --adapter-report .cache/musicbrainz-full-seed-targets/pipeline/musicbrainz-model-adapter-report.json \
  --reconciliation .cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json \
  --seed item887
```

The inverse query returns direct stable seed IDs and a separate album-supported seed section for one exact MusicBrainz artist ID:

```sh
uv run python scripts/query_local_musicbrainz_artist_evidence.py \
  --evidence-db .cache/musicbrainz-release-group-evidence-candidate-v1/evidence.sqlite \
  --evidence-artifact .cache/musicbrainz-release-group-evidence-candidate-v1/artifact.json \
  --adapter-report .cache/musicbrainz-full-seed-targets/pipeline/musicbrainz-model-adapter-report.json \
  --reconciliation .cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json \
  --artist-mbid 00000000-0000-4000-8000-000000000000
```

The query verifies the evidence artifact and the adapter report. The adapter report must bind both the evidence artifact's seed-target hash and the reconciliation sidecar's hash, seed source, source content hash, seed identity fingerprint, and full seed count. The query then checks the database SHA-256, byte size, and SQLite integrity before reading it. It rejects partial databases and a schema-shaped staging file that does not match the artifact.

This is a verified one-shot CLI, not an interactive service. Its JSON output reports `verification_seconds` separately from `query_seconds`. Verification reads the complete SQLite file to calculate its SHA-256 and may take much longer than the bounded SQL query. Response sections are bounded by `--limit`; the current candidate's reverse support lookup may scan its SQLite table because the live build began before an artist-leading support index was added for future builds. Record the measured SQL time after publication and do not describe it as an indexed interactive lookup. The command does not keep a service process or a verification cache.

The JSON output is local research only. It has `export_allowed=false` and `serving_allowed=false`. It is not a public API, a UI result, or an artist similarity claim.

## Candidate smoke checks

Run these checks only after both candidate files exist. The existing adapter report shows direct evidence for the first four seeds and no direct evidence for the last one.

| Stable seed ID | Seed name | Expected result |
| --- | --- | --- |
| `item5` | hip hop | Bounded direct artist list with a nonzero total. |
| `item379` | jazz | Bounded direct artist list with a nonzero total. |
| `item10` | modern rock | Smaller nonzero direct artist list. |
| `item1000` | lo-fi | Bounded direct artist list with a nonzero total. |
| `item1003` | trap baiano | Empty direct artist list and zero total. |

For each seed, run the command above with its stable ID and record the two timing fields separately. Do not add them together or describe the verification time as SQL query latency.

Choose reverse-query artist IDs only from the completed candidate database. First select a few direct-anchor IDs from the same seed IDs. Then use a public catalog name only when that same exact MusicBrainz ID has one unambiguous preferred public name. An unmatched MusicBrainz ID remains a valid reverse query and must not receive a name through fuzzy matching.
