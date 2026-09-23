# MusicBrainz release-group tag census

The tag census streamed the pinned 1,159,485,640-byte MusicBrainz
release-group archive once on 2026-09-23. It wrote the create-only ignored
local report at `.cache/musicbrainz-release-group-tag-census-v1/report.json`.
The report bytes have SHA-256
`9b52c3ba3483726802859b039d7cddcabea50f5bf084970f9c2f60cf0d34a3cb`,
and its internal output SHA-256 is
`23b62620e82941d0dd57ff68c2691faa15749b6fbac2657c9d0e283888e63b14`.

The builder verified the archive SHA-256
`6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43`,
the source-cache receipt SHA-256
`2b2ae54fe057e5dd41d46a3a8ebeafad698a6ce8474135780ffd3b988c5c1dde`,
the 6,291-seed reconciliation SHA-256
`a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0`,
and the 3,346-unplaced-seed layout SHA-256
`e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972`.
The final code validated the completed report with Pydantic and replayed its
internal hash after the stream ended.

The stream saw 4,499,326 raw records. It rejected zero over-limit records and
40 malformed records, then parsed 4,499,286 release groups. The counts match
the completed proper-genre census because both use the same archive member,
record ceiling, and `MusicBrainzReleaseGroup` parser. The matching parser
failure count does not make tags proper genres.

All parsed tag observations total 4,950,826. Every observed tag had a positive
count in this pinned archive. The zero, negative, and missing sign counts are
each zero. The 1,954 exact normalized seed-name matches account for 3,734,769
of those observations, and all of their counts are positive. Exact normalized
matches include 385 of the 3,346 unplaced seed names. The positive-tag support
bins count positive tag observations, rather than numeric vote totals. The
bins are 1,954, 1,593, 1,265, and 1,080 exact seed names at thresholds 1, 2,
5, and 10 observations. The corresponding unplaced counts are 385, 191, 76,
and 36. Every archive-exposed tag count was positive, but a threshold of five
therefore means five observed release-group tag rows, not five summed votes.

The two pinned aggregate reports and the same unplaced layout allow an
aggregate-only reach comparison. The proper-genre census has 68 exact unplaced
name matches, and every one also occurs in the tag census. Tags add 317 names
outside that proper-genre set, leaving zero proper-only names, 68 matches in
both reports, and a 385-name union. This is incremental exact-name coverage
only. Of the 317 tag-only names, 41 have at least five positive tag
observations. It does not make any tag a proper genre or add a membership claim.

The report aggregates only matching normalized seed names and vote-sign
counts, plus global tag totals. It retains no release-group IDs, titles, artist
IDs, artist names, listening records, or non-seed tag labels. Duplicate source
tag rows are counted as observations. A fixture covers positive, zero,
negative, and missing vote signs, duplicate tags, pinned-input rejection,
create-only output behavior, and report validation without entity identities.

MusicBrainz documents genres as tags from its genre list and separately notes
that the tag endpoint can include other, non-genre tags. See the official
[MusicBrainz API documentation](https://musicbrainz.org/doc/MusicBrainz_API).
The report therefore describes only observed `tags` fields from the pinned
archive. It does not treat a tag match as a proper-genre row, factual genre
membership, a genre relation, a placement, or an artist claim.
