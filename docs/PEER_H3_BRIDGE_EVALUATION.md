# Bridge-resolved H3 peer evaluation

This is an evaluation-only check for a sealed genre peer candidate. It does
not use H3 or the bridge during candidate construction, and it does not
replace the default model or a public API.

The evaluator verifies the candidate input hash, the bridge receipt hash, the
bridge logical hash, and the H3 database hash. It keeps only accepted exact
Spotify to MusicBrainz artist IDs. It excludes bridge conflicts and unknown
Spotify IDs. It maps H3 genre names to one stable seed ID and keeps unknown or
ambiguous names out of the peer reference.

For each mapped genre, it builds a binary Jaccard neighborhood from H3 artist
sets. It uses the top 25 neighbors and breaks equal scores by stable seed ID.
The candidate is compared with this derived historical-membership neighborhood.
This is not an evaluation of original Every Noise neighbor blocks or layout.

Run it with Poe after setting the explicit local paths:

```bash
uv run poe evaluate-genre-peer-similarity-h3-bridge
```

The combined reviewed-alias candidate report is
`.cache/reviewed-alias-combined-model-v1/peer-h3-bridge-evaluation.json`.
Its logical hash is
`4401578e050a35a685ae585d2ace46a89c319ea1a5b64670d1c748a8b76ba893`.
It binds candidate `201a5061c2bcd0b71e7d6ac867e8a42d76b3c8cfed0318d88752cfbae12853eb`,
input `aed9ac4e8f62a1f34fe5288a569ea9c592df9b7abf662db233687896390dc36d`,
bridge `d6eadab048de250342e69383f1973d4a1469b477d17d68483ebe04d059e4733d`,
and H3 database `098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df`.

The run read 306,136 H3 observations. It mapped 120,288 rows and 120,163
unique genre and artist memberships, covering 78,954 distinct MusicBrainz
artists across 6,069 seeds. It excluded 184,783 unbridged rows and 1,065
conflict rows. The derived top-25 reference had 55,571 directed neighbor
entries across 5,574 evaluated genres. The global Micro Recall at 25 was
`0.07649673390797358`, and macro Recall at 25 was `0.04561503198333944`.
Among the 1,541 genres with both a nonempty historical reference and candidate
neighbors, the 24,380 reference entries had conditional Micro Recall at 25 of
`0.1743642329778507`.

H3 is positive-only. A candidate neighbor absent from H3 is unknown, not a
false positive, so precision is intentionally null. These numbers are not a
comparison with the earlier sparse name-crosswalk report. A fair old versus
new comparison needs both candidates evaluated under this same bridge and H3
cohort.
