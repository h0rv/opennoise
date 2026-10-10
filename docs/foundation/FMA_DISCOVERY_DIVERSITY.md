# Less repetition in attached FMA suggestions

The component-diverse v2 ranking keeps the nearest suggested excerpt, then fills
up to six places with the nearest excerpt from each different native recording
component. A component connects tracks through artist, album or identical full
native features. These are source relationships, not perceptual similarity
classes. Choosing different components reduces related-source repetition; it
can increase descriptor distance and does not establish musical relevance.

The v1 attached-pool baseline was frozen at reviewed commit
`d952762e8acdcf00fd26842d78b0903a17ef4ddb`, whose tree is identical to merged main
`480728751b06a6904dd3600f5876ad7c72ee5130`. Before candidate calculation, the
independent evaluation froze the exact two audio manifests, 44-dimensional
feature projection, existing inner-fit model, native roles and comparison rule.
The declaration SHA-256 is
`f89e34892b41e50354b689a673595cb66570e2862169d0022b8459d240445af5`.
A bounded streaming Zstandard reader correction was recorded separately after
an initial input-loading failure; no candidate distances preceded that correction.

Acceptance required unchanged rosters, normalization, support gates, query
component exclusion and first suggestions; exact distance/native-ID ordering
of each component's nearest candidate; six distinct components wherever
available; and strictly fewer repeated-component lists. There was no parameter
search, label optimization, fitting, held-out tuning or listening judgment.
Squared-distance cost and retained baseline suggestions were reported as
tradeoffs, not musical-quality metrics.

| Frozen comparison | Default 92 routes | Both collections, 124 rows |
| --- | ---: | ---: |
| Lists repeating candidate components, v1 → v2 | 20 → 0 | 27 → 0 |
| First suggestion unchanged | 92/92 | 124/124 |
| Original suggestion edges retained | 524/552 | 706/744 |
| Mean squared descriptor distance, v1 → v2 | 42.5158 → 42.8889 | 42.2908 → 42.7541 |
| Maximum squared descriptor distance, v1 → v2 | 236.7804 → 246.9150 | 237.8823 → 254.9690 |

All queries remain supported, with six suggestions. The 124-row result includes
shared recordings in both pools; it is not 124 independent recordings. The root
uses the original pool for its 60 recordings and the expanded pool for 32 new
recordings. Pools are not silently joined. The 92 clips remain a licensed,
size- and coverage-selected subset, not a representative catalog sample.

The producer keeps the existing 64-clip, 120-second, one-GB and one-MB output
limits. No audio or model was acquired or refitted. Existing global retrieval
and genre starters are unchanged. The latter already expose all 92 clips among
198 starter positions; the inspected alternative would improve component
coverage in only one genre. That does not justify changing this separate rule.

The new protocol is `fma-playable-component-neighbors-v2`. The same existing
`scripts/build_fma_playable_neighbors.py` freeze/build/verify commands produce
and replay new packs. The independent calculation matches every produced row.
Portable validators and browser rendering also accept intact v1 packs using
their original policy. Numerical replay of a frozen v1 declaration requires
its archived implementation; a current v2 producer does not reinterpret it.
Baseline packs, private audition materials and their original assignments stay
unchanged. A v1 audition must not be presented as an evaluation of v2.

SQLite is already available in this project. The inspected credit catalog has
MusicBrainz identifiers and no FMA identities; migrating this small slice would
add ingestion work without improving these exact, hash-verified joins. This
change therefore keeps immutable audio/snapshots outside the database and
versioned ranking manifests in the static export. It introduces no database
server, cache service or live API dependency.

The independent pilot still needs actual listeners. Source-component diversity,
working playback and annotation agreement cannot certify musical quality,
global coverage, representative recordings or a quality score of 70.
