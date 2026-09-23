# MusicBrainz recording-to-release connectivity pilot

This local-only, non-serving pilot uses the exact 24-ID cohort prefix pinned by
cohort file SHA-256 `869c205921afb668585d2357ecb94302475aa90e589bec2426f85c0def2f5f6a`.
It makes no genre claim and does not choose a representative release.

The official [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API)
documents recording lookups with `releases`, `release-groups`, and
`artist-credits` inclusions. Linked entities are limited to 25, so this is a
bounded connectivity slice, not complete release history. A release group has
one primary type; compilation is a secondary type and is an ambiguity marker,
not a ranking rule.

The receipt at `.cache/listenbrainz-musicbrainz-recording-release-coverage-v1/artifact.json`
has SHA-256 `950cd2ea0fb36401ff82a662fefa7702e8acc80b4b7c6262191d2799fd3f058a`.
All 24 exact recording lookups returned a release-group link. The 25-link-capped
responses contained 197 observed release links and 58 observed distinct groups:
187 Album, 6 EP, and 3 Single primary-type links; one link had no primary type.
These are link-weighted counts, not proportions of the 24 recordings. Because a
prolific recording can have more than the API's 25 linked releases, all link and
group counts are lower bounds rather than complete release discographies.
Thirty-one observed groups had the Compilation secondary type. Thirty-seven
linked releases had an artist credit different from their recording credit,
affecting nine recordings; this is an ambiguity measurement, not a data error.

Raw JSON is held only in the bounded local content-addressed custody cache.
The safe receipt retains IDs, type fields, compilation flag, credit IDs, status,
timestamp, and object hash; it has no display names or titles. Offline replay
rehashes and reparses every cached object and matched the receipt exactly.
