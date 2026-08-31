# Public graph model report for 2026-08-31

The first real run used only Wikidata P136 claims and privacy safe ListenBrainz artist pair
counts. The run did not use Every Noise data, MusicBrainz user tags, music files, audio features,
or values derived from audio. MusicBrainz IDs served only as public artist identity links.

The Wikidata source was the bounded ListenBrainz overlap query. Its official response was
3,268,158 bytes, and its SHA256 was
`271f042f11486ff8bce76d9d47f0b2ee3a4f2c299814991df5cd5e43d882492c`. The source pipeline
accepted all 90 records and quarantined none. The catalog contained 40 artists, 50 release
groups, and 127 genres. It contained 294 artist P136 observations and 98 release group P136
observations.

The ListenBrainz input was the official 2026-08-30 incremental dump. Its SHA256 was
`d98da81fd4552521ecda22d8242ddd0b9359afb8c302e2f7b4b24c31a2f41789`. The ingestion job
stored 69,693 daily pair rows. The model combined repeated artist pairs across the day and used
69,663 unique artist pairs. The graph covered 5,733 artists.

## Output

The model combined the 294 source observations into 247 unique direct artist and genre
memberships. One graph step produced 10,400 inferred memberships. The direct and inferred
profiles covered 104 genres. The remaining 23 genres had album evidence but no artist evidence,
so the model reported them as unplaced.

The model published 7,610 directed neighbor rows. Direct profiles produced 1,205 weighted
Jaccard rows and 1,205 cosine rows. Inferred profiles produced 2,600 rows for each metric. All
104 placed genres belonged to one connected layout component.

The metadata ranking published 315 items. It included 233 artists and 82 release groups. The
source slice had no recording genre evidence, so the model published no track ranking.

The complete JSON result was 12 MiB. The first measured run took 1.294 seconds and reached
316,936,192 bytes of peak resident memory. A repeat took 1.233 seconds and reached 315,691,008
bytes. Both runs produced the same logical hashes:

```text
input_sha256    cdd8157fca33a31573c7c2a610c5a59a10fca39af27a6aca1f6c57e4a38d9694
settings_sha256 fb75fd864a19ed7405582b496587b1fe0ecdb123810c2b97dbdc5a20362068b3
output_sha256   06e9577c12cab4ba7349c1d99fa208154ffef88c0e7f141afe18bdc7bd5ce908
```

Elapsed time and peak memory remain outside the logical output hash, so the complete JSON file
hash changes between runs. The model output was exportable because both inputs allowed export.

## Validation limits

The repeated output hash verifies deterministic model content for the same inputs and settings.
All 104 graph genres received coordinates, and the direct graph formed one connected component.
The run cannot measure agreement between Wikidata and MusicBrainz tags because the exportable
policy excluded MusicBrainz user tags. The agreement report therefore records zero available
MusicBrainz tag pairs instead of treating missing evidence as perfect agreement.

The run also cannot perform a ListenBrainz time holdout because it used one daily incremental.
A later evaluation should ingest at least seven daily files, fit on the earlier days, and report
membership and neighbor stability on the held out days. Historical Every Noise memberships and
coordinates can be compared after the output hash is fixed, but they cannot enter the model
input.
