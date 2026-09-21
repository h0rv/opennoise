# MusicBrainz catalog materialization candidate

The source-bound local candidate is
`.cache/musicbrainz-catalog-expansion-v1/materialized-candidate.sqlite`. It is
materialized only from the replayable core-metadata artifact
`.cache/musicbrainz-catalog-expansion-v1/release-tracks.json`, whose SHA-256 is
`9d2a7925eddf2cbf0260e502ca2b71d0a4ec92ac953d9e630f836adc08836ce3`.
It is not a sealed or published database.

The artifact has 94 selected release entries, 101 medium entries, and 1,115
track entries. Exact identity normalization reduces that to 87 releases, 94
media, 1,032 tracks, and 1,031 recordings. Repeated selections were accepted
only after their release, medium, and track structures compared identically;
conflicting duplicates cause candidate construction to fail.

The candidate preserves 87 release-to-release-group links, 94 medium-to-release
links, and 1,032 track-to-medium-and-recording links. Its single provenance
record is bound to the exact artifact hash. `pragma_foreign_key_check` reports
zero violations, and an immediate second materialization inserts zero releases,
media, tracks, or recordings.

Materialization hashes and parses the artifact at its public boundary. It stages
and validates a new SQLite database before atomically publishing it only to a
previously absent, non-symlink target; an existing candidate is never reused or
mutated.

Artist credits are explicitly abstained, rather than inferred: the source
hydration artifact contains no artist-credit fields, so the candidate has zero
artist-credit relations. This is a source-bound limitation, not evidence that
the releases have no artists. No audio, previews, artwork, genres, or tags are
stored.

Run a fresh isolated candidate and report with an unused database path. The
example path below was used for the recorded run and is rejected if it already
exists; choose another unused path for a later run.

```sh
uv run python scripts/materialize_musicbrainz_catalog_candidate.py \
  --artifact .cache/musicbrainz-catalog-expansion-v1/release-tracks.json \
  --artifact-sha256 9d2a7925eddf2cbf0260e502ca2b71d0a4ec92ac953d9e630f836adc08836ce3 \
  --database .cache/musicbrainz-catalog-expansion-v1/materialized-candidate.sqlite \
  --report .cache/musicbrainz-catalog-expansion-v1/materialized-candidate-report.json
```

The report SHA-256 for the fresh first-materialization run is
`94c98cce2923d93a6d7c64aadd7666d0cc46daaa6d2298443c2b59464007100d`.
After the staging safety change, a second fresh local target reproduced the
same source and normalized relation counts, one provenance record, zero
foreign-key violations, and zero artist-credit relations.
The existing hydration candidate already proved an offline source-cache replay
with zero upstream requests; this materializer is offline-only and accepts no
network configuration.

## Artist-credit gap

The retained `release/{release_mbid}` cache entries were inspected. Their safe
payloads retain `id`, titles, release group, edition fields, media, tracks, and
recordings, but omit both the release `artist-credit` field and each nested
recording `artist-credit` field. They therefore cannot support exact artist
relations. The cache-only adapter
`scripts/build_musicbrainz_cached_artist_credit_candidate.py` emits a versioned
abstention ledger with no network client and no name matching or inference.

If a future bounded source refresh is approved, its exact request must be:

```text
GET /ws/2/release/{release_mbid}?inc=release-groups+recordings+artist-credits
```

The adapter accepts retained fields only when they provide ordered exact
`artist-credit[].artist.id`, `artist-credit[].artist.name`,
`artist-credit[].name`, and `artist-credit[].joinphrase` values. It emits the
source endpoint and response SHA-256 per relation; omitted fields remain an
explicit abstention.

The current offline run wrote
`.cache/musicbrainz-catalog-expansion-v1/artist-credit-abstentions-v1.json`
(SHA-256 `ab9614675b2d37bee77d15a5625184fcfe282a6ee4a53246e393205f0178f965`).
It has zero retained credits and 1,118 abstentions: 87 normalized releases and
1,031 normalized recordings, all because `artist-credit` was not retained.
