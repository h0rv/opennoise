# MusicBrainz open name coverage frontier

The local report at `.cache/musicbrainz-open-name-coverage-frontier-v1/report.json`
measures current open evidence against the immutable 6,291 retained names. It
uses no historical Every Noise coordinates, memberships, neighbors, or map
placement. It creates no artist membership, static data, model input, or
release change.

The broader all-seed source-anchor artifact reports 2,378 direct-observed
names. Of those, 2,377 have MusicBrainz observations, 292 have Wikidata
observations, and 291 occur in both source families. The portable MusicBrainz
artist proper-genre custody is the stricter subset. It has 387,435 exact
artist-record observations for 697 names and 198,409 artist MBIDs. It excludes
tags, release evidence, peers, and inferred rows.

The full release-group census has 911 exact proper-genre names and 4,596,870
proper-genre observations. It has no retained artist identities, so it is only
aggregate release-group context. All 911 also occur as exact release-group tag
names. Tags reach 1,954 names and 3,734,769 observations, but tags remain weak
context and do not become proper genres or artist claims. The strict custody
and native proper-name scopes overlap on 695 names.

The reconciliation has 359 names with both a resolved public identity and a
MusicBrainz identity. The strict custody scope contains 303 of them. The
current hierarchy candidate artifact has accepted edges for 223 names, and 141
also have strict custody. Accepted hierarchy evidence has its own source and
policy records. It is not an artist membership and is not a generic claim that
all hierarchy evidence is independent of MusicBrainz.

The report does not claim coverage of a defined microgenre stratum. The legacy
name map supplies immutable vocabulary but has no open, independently declared
microgenre level. Name spelling, support volume, tags, or hierarchy degree
cannot create that label. A later source must supply an open granularity
classification before a microgenre-only denominator can be measured.

Reproduce locally:

```sh
uv run python scripts/build_musicbrainz_open_name_coverage_frontier.py \
  --reconciliation .cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json \
  --custody-receipt config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json \
  --custody-object-store data/release/musicbrainz-direct-proper-genre-custody-v1/objects \
  --native-census .cache/musicbrainz-release-group-native-census-v1/report.json \
  --tag-census .cache/musicbrainz-release-group-tag-census-v1/report.json \
  --hierarchy .cache/taxonomy-relation-hierarchy-integration/artifact.json \
  --source-anchor-frontier .cache/musicbrainz-full-seed-targets/pipeline/all-seed-evidence-frontier-v4-wikidata.json \
  --output .cache/musicbrainz-open-name-coverage-frontier-v1/report.json
```

The next high-value step is a small, custody-bound open source that declares
genre granularity and has exact MusicBrainz genre or artist identifiers. A
future Wikidata P1953 to Discogs bridge could be useful only after an exact
ID bridge and a release-style custody plan are separately approved. No Discogs
data was fetched or used here.
