# Public layout lenses

This report covers the qualified public build from 2026-08-31. The build used Wikidata P136
membership facts, Wikidata P279 hierarchy facts, and privacy safe ListenBrainz pair counts. It did
not use Every Noise data, audio, music files, previews, or features derived from audio.

## Inputs

The job jointly scanned seven verified ListenBrainz increments dated 2026-08-24 through
2026-08-30. The compressed inputs total 1,514,835,361 bytes. It read 30,469,708 listens, including
993,589 with an artist MusicBrainz ID. It found 79,673 artists in 40,782 listener day windows. The
bounded candidate stage considered 8,420,452 pairs and emitted 30,903 artist pairs at a privacy
floor of five. One malformed row was quarantined. Listener identities were discarded before the
job wrote the aggregate.

The public catalog preserved every raw P136 claim, but the model accepted a target only when a
nondeprecated Wikidata P31 statement classified it as Q188451, music genre. It also rejected a
target with a nondeprecated direct P279 statement to Q25379, play. The second rule removes the
cross domain item Q2743, musical play, while retaining opera, rock opera, musical comedy, and
musical drama. The rule uses exact QIDs and statement ranks, and it does not use names for
classification.

The qualification input contained 746 exact QIDs, and 603 passed. Artist evidence fell from 4,948
raw observations to 4,890 qualified observations. Album evidence fell from 1,550 to 1,530, and
recording evidence fell from 833 to 829. The model deduplicated the artist observations into 4,434
direct memberships. It included 712 direct P279 edges whose two endpoints passed the same gate.

The eight qualification queries accepted 603 entities with no quarantine. Their selection manifest
SHA-256 is `0467cab215b4dcfde5c18b99cdfd086b0f1b21eb3328287ec02b61f6932dc974`.
The model bound 62 exact source artifacts. Its input SHA-256 is
`70c5c40f6206eb3895203e61864b62cf361532d02c1c61535281f22ce5fced6e`, and its settings SHA-256 is
`d27fa893459f5480e663253972191b5b90c3ab616cfaad49facc15c645ee22b0`.

## Results

| Lens | Input | Coordinates | Connected nodes | Singleton coordinates | Unplaced | Input edges | Output SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `public` | one-hop similarity | 468 | 467 | 1 | 135 | 8,247 | `7e2cae1eaee670096ba8e9ace2ef92f7bbca8599715ccbb74f1c83c16a4d1f7b` |
| `public-direct` | direct similarity | 468 | 460 | 8 | 135 | 3,864 | `6a1f6dd35fc50edac2a9dcb03a75ce733122f645cf16c545c095a911154300c4` |
| `public-community` | one-hop communities | 468 | 467 | 1 | 135 | 8,247 | `0f3b2927cedb8d2270211e3207166c3fb23fa984f5936939ec3c23bcd5bf4c06` |
| `public-taxonomy` | P279 hierarchy | 598 | 598 | 0 | 5 | 712 | `9cb4c0b459a7a19040447f97afbbb15b8a5c1e3cc5494000b2fe1c5195c3eaf4` |

The coordinate count is the number of points the layout places. The connected node count includes
only points in components with at least two nodes. The remaining coordinate points are singleton
components, which the layout places in their own grid cell instead of marking them unplaced. For
example, the default lens has 467 connected nodes and one placed singleton, so it publishes 468
coordinates. The direct lens publishes eight placed singletons. The taxonomy lens has no
singletons.

The default lens has two components, including its singleton. The direct lens has nine components,
and the community lens has 23. The taxonomy lens has 20 connected components. The community lens
found 23 groups in six iterations and converged with modularity 0.447594727711.

The final artifact contains 603 named genres and 3,344 representative links. These links cover
1,975 artists, 871 release groups, and 498 recordings. Every published genre name and every
representative name was checked, and none is a raw QID. The five reported examples that are not
music genres are absent from every layout and representative list. They are action film,
adventure television series, hero shooter, tactical shooter, and musical play.

## Resources and artifacts

The joint ListenBrainz aggregation took 252.901 seconds and reached 368,578,560 bytes of peak
resident memory. The final build of four lenses took 3,539 milliseconds and reached 367,960,064
bytes.
The individual layout times were 165 milliseconds for the default, 114 for direct, 166 for
community, and 98 for taxonomy.

The model artifact is 28,043,096 bytes with file SHA-256
`ffbe49cb78552ee668bc7d62f829105220e2cd0dc857f72c2e8a2e2d5357416d`. Its logical output SHA-256
is `e327045074fc6bb4e3b2e1c14410b3f337b6822e048c6038aa18703a11d2108b`.

The published SQLite database is 153,231,360 bytes with file SHA-256
`282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866`. SQLite reports schema 10,
integrity `ok`, and no foreign key violations. Repeating publication returned the same logical
output hash and reported a duplicate instead of creating another model run.

The generated screenshots are `/tmp/musix-phase3-public.png` and
`/tmp/musix-phase3-taxonomy.png`. They confirm that excluded cross domain labels are gone. They
also show dense label overlap in the largest components, which remains a visualization issue and
does not change the evidence or layout hashes above.
