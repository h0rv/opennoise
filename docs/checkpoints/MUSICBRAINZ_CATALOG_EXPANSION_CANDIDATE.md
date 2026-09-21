# MusicBrainz catalog expansion candidate

The bounded candidate at `.cache/musicbrainz-catalog-expansion-v1/` uses only
existing exact MusicBrainz representative IDs and the MusicBrainz CC0
core-metadata endpoints. It stores no audio, previews, artwork, tags, genres,
ratings, or source database writes.

The runner selected at most 60 genres, two existing metadata examples per
genre, and one concrete release per selected example. It processed 96 seeds
with 65 upstream requests and retained one explicit stale-recording abstention
(`recording/bb318056-9a6d-4655-9ad2-dcd60cc34eca`). The resulting catalog
artifact contains 94 releases, 101 media, and 1,115 non-playable metadata
tracks: a gain of 39 releases, 43 media, and 455 tracks over the prior 55/58/660
slice. Its exact artifact hash is
`9d2a7925eddf2cbf0260e502ca2b71d0a4ec92ac953d9e630f836adc08836ce3`; the
coverage report byte hash is
`348ece6f07808d5fd3d885fba2d8838b0360a28f59ac9dc9404be38f2a89f9a7`.

An immediate offline batch replay produced the identical artifact and failure
ledger with zero upstream requests. The candidate does not materialize a
catalog database, so no sealed database was opened for writing. The reusable
runner is `scripts/run_musicbrainz_catalog_expansion_candidate.py`; existing
hydration tests cover both typed failure continuation and zero-request offline
replay.

Re-run the same bounded candidate with the retained representative and baseline
artifacts:

```sh
uv run python scripts/run_musicbrainz_catalog_expansion_candidate.py \
  --representatives .cache/objective-gates/metadata-representatives-v1.json \
  --baseline .cache/musicbrainz-72-catalog/release-tracks.json \
  --output .cache/musicbrainz-catalog-expansion-v1/release-tracks.json \
  --object-store .cache/musicbrainz-catalog-expansion-v1/objects \
  --cache-directory .cache/musicbrainz-catalog-expansion-v1/cache \
  --report .cache/musicbrainz-catalog-expansion-v1/report.json \
  --user-agent 'OpenNoise/0.1 (https://opennoise.horv.co)' \
  --max-genres 60
```

The command fails before writing the artifact if offline replay differs or
makes an upstream request. It does not alter the sealed catalog.

## AcousticBrainz genre-dataset prospect

The current 660-track catalog already retains exact MusicBrainz recording IDs:
it has 1,252 recording rows and 1,927 `musicbrainz_recording_id` identifier
rows, so an AcousticBrainz TSV `recordingmbid` join is mechanically exact and
does not need artist-name matching. No AcousticBrainz genre archive is retained
locally, so overlap has not been measured.

It is not eligible for production-model ingestion. The dataset documentation
states that its Discogs, Last.fm, and Tagtraum annotations are CC BY-NC-SA 4.0,
while AllMusic data has an additional non-commercial research-only agreement.
Any later acquired copy must therefore remain a separate, non-production
research/evaluation dataset; it must not be added to sealed model inputs or
published metadata without a new permission decision.
