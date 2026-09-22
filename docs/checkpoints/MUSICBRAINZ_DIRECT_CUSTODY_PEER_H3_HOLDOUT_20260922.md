# MusicBrainz direct-custody peer H3 holdout

This is a terminal, local-only evaluation of the already constructed direct
MusicBrainz custody peer graph. H3 was not read during graph construction or
used to choose its metric, threshold, or neighbors. Nothing here authorizes
serving, export, publication, a layout, or a similarity claim.

## Fixed inputs

- Graph: `.cache/musicbrainz-direct-custody-peer-graph-v1/peer-graph.sqlite`,
  SHA-256 `1193a4e0f36ef02071fb3af417250d8496328b1e68c803bf1ab099122252ab69`.
  Its receipt is `a4ae5e59a5d7b3b46976d7379e93cdb21d6e09493e0ae113f4dd8ed13a3a14f0`;
  it records IDF-weighted Jaccard, minimum two shared artists, top 10, and no
  historical inputs.
- Historical H3 SQLite:
  `.cache/historical-custody-vault/historical-h3/membership/sha256/098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df.sqlite`,
  SHA-256 `098dc8780b3f4a8daf1240d36bec7eb7be563dc2275d998dbc7509c3fb1859df`.
- Pre-existing exact identity inputs: seed reconciliation
  `.cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json`,
  SHA-256 `c87fe5b67c0974b30d5ae1d2a9f66b22b122126230cd2561837c94897514f022`; and
  accepted MusicBrainz--Spotify bridge
  `.cache/musicbrainz-full-seed-targets/pipeline/musicbrainz-spotify-bridge-v1.json`,
  SHA-256 `abd09990751baca9f4bb1b4856d1ab00fee9bf552b3ab297403015c0e72033d6`
  (receipt SHA-256 `ad0f468aa68c366d99cf23e5e69dc000b0105b48f10ab9cbf1adbcbad686d4dd`).

## Denominator and result

All 697 graph seed IDs had one unique normalized H3-name match. The independent
H3 join retained 22,159 unique `(seed, MusicBrainz artist)` positives on 695
seeds; the other two graph seeds abstained. H3 memberships were converted only
after construction into a binary-Jaccard top-10 reference. Of 610 sources with
at least one H3 reference neighbor, this gives 4,075 directed reference edges.

The fixed graph recovered **1,840 / 4,075 = 45.1534% micro Recall@10**.
Macro Recall@10 was **48.1021%**. Four scoreable sources had no graph neighbor;
conditional on the remaining 606 sources, recovery was 1,840 / 4,066 =
45.2533%.

This is positive-only recovery, not precision: an H3 absence is unknown and a
candidate neighbor absent from H3's top 10 is not a false positive.

## Review questions

High-scoring candidate neighborhoods not present in the corresponding H3 top
10 are prompts for review, not errors: `chillwave -> boom bap` (rank 1,
IDF-Jaccard 0.846071, 4,173 shared artists), its reciprocal, and
`instrumental hip hop -> chillwave` (rank 1, 0.834531, 4,191). Do these very
large shared-artist sets reflect overly broad direct custody coverage, labels
with cross-scene usage, or a real relation not represented by the historical
positive sample?
