# Last.fm ArtistTags2007 literal seed candidates

This local-only candidate is distinct from direct artist memberships and from
independent gold. It reads the pinned 2007 `ArtistTags.dat` source plus only
the 6,291 current seed IDs and names projected from a supplied
`seed-reconciliation-v3` file. It does not read any reconciliation identity
facets, historical Every Noise relationships or artist data, Wikidata,
MusicBrainz genre memberships, predictions, audio, public/model data, or an
earlier evaluation artifact.

The current vocabulary is byte-pinned to SHA-256
`c87fe5b67c0974b30d5ae1d2a9f66b22b122126230cd2561837c94897514f022`;
a same-shaped or same-revision replacement is rejected before source rows are
read.

An emitted candidate preserves the source row ordinal and SHA-256, MusicBrainz
artist ID, raw artist name, raw tag, and raw positive count. The sole mapping
rule is byte-for-byte equality between the raw tag and exactly one seed name.
Case variants, aliases, normalized labels, fuzzy matches, and duplicate seed
names are abstentions. Non-candidate raw tag/count observations are retained
as grouped abstention rows with their reason. To keep the artifact bounded,
it retains the 10,000 hash-smallest `(tag, count, reason)` abstention buckets
and reports the count represented by omitted buckets. Exact repeated
`(artist MBID, raw tag)` rows are separately counted and cannot become a
second candidate.

The current v2 public static map is optional and is read only after the
candidate is built. That terminal report measures exact artist-MBID,
map-node/seed-ID, and artist/seed-ID-pair overlap; it cannot add, remove, or
rank candidates.

The older `lastfm-artisttags2007-unplaced-exploratory-v1` report is not reused.
It was a counts-only audit against a v2 layout, reported 291 literal unplaced
seeds and 1,593 rows, and labelled the source an exploratory construction
candidate. Its layout, parser, and scope do not establish current-vocabulary
coverage or this source-backed candidate.

Run locally:

```sh
.venv/bin/python scripts/build_lastfm_artisttags2007_seed_candidates.py \
  --archive .cache/lastfm-artisttags2007/source.tar.gz \
  --seed-vocabulary .cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json \
  --output .cache/lastfm-artisttags2007/literal-seed-candidates-v1.json \
  --public-map dist/assets/static-discovery.4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c.json \
  --comparison-output .cache/lastfm-artisttags2007/literal-seed-public-map-comparison-v1.json
```

The artifact is not a factual membership claim, construction input, model
input, gold label, negative label source, quality evaluation, or release gate.

## Current local run

The pinned archive and current 6,291-row vocabulary run completed locally.
The candidate artifact is
`.cache/lastfm-artisttags2007/literal-seed-candidates-v1.json` (84 MiB), with
logical SHA-256 `d7db2213418253490a095a81ba951f89946dbe2190b7fc5eb76d53e5d8121788`.
Of 952,810 physical rows, 952,707 unique well-formed positive rows were
accepted; 103 repeated artist/tag rows were excluded. Literal matching emitted
192,614 candidates for 19,908 distinct MBIDs and 1,317 exact seed IDs. The
artifact retained 10,000 abstention buckets and reports 711,819 rows in
unretained buckets.

The terminal comparison used the current v2 public asset byte hash
`4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c`.
It found 620 candidate MBIDs among 1,126 public-map MBIDs, 236 candidate seed
IDs among public map node IDs, and 1,295 exact `(MBID, seed ID)` overlaps.
Its logical SHA-256 is
`5ef25955fd0cb661b2c874213daa675e15b2deb79ca33b50849ef3d5186fa68b`.
These are terminal coverage observations, not factual membership validation.
