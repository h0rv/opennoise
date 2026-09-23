# MusicBrainz native release-group credited-artist support

This local-only replay attaches exact MusicBrainz release-group artist credits
to the already verified fixed 10,000-record native observation sample. It
retains release-group facts, not artist memberships. Every support row means
only that an exact credited artist appears on a release group with one
positive-vote native MusicBrainz genre. It cannot feed artist membership,
serving, export, or the public model.

The replay first verifies the prior native-observation logical receipt, the
source-cache receipt, and the exact archive bytes. It then requires every
valid parsed record to match the next retained record hash, byte length, and
release-group MBID in archive order. A malformed or over-limit record may be
skipped exactly as in the original observation pass; an inserted, removed, or
reordered valid record fails closed. Native proper genres must also match the
earlier receipt exactly before the release-group title, type, first-release
date, and ordered artist-credit components are retained.

The output is only
`.cache/musicbrainz-release-group-native-artist-support-v1/report.json`; it is
14,175,214 bytes with file SHA-256
`f06e2a900780321489164d348044a986e76b6d6377f2fb6e5571b755522c4876` and
logical SHA-256
`eb001457896e86c1e3dcb13e25b0a685fc840634696d6f9b2ca02e9873d77836`.

- Native observation receipt SHA-256: `b479fc9742375c2447b475a380e6afb2247febb649683d18fcff7fc63268f3c9`
- Source archive SHA-256 / bytes: `6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43` / `1,159,485,640`
- Source-cache receipt SHA-256: `2b2ae54fe057e5dd41d46a3a8ebeafad698a6ce8474135780ffd3b988c5c1dde`
- Sampled release groups: 10,000; all have exact artist credits; 530 have multiple credit components.
- Native proper-genre observations: 21,913 across 6,582 release groups and 586 distinct genre UUIDs.
- Positive-vote genre denominator: 6,582 release groups. All 6,582 have exact credits, so zero credit abstentions occurred. The other 3,418 sampled groups abstain because they have no positive native genre.
- Credited-artist contextual support rows: 23,026 for 6,055 distinct exact artist UUIDs. The rows include release-group ID, native genre UUID, source-record hash, and credit position; they are not artist-to-genre rows.
- Primary type is retained rather than filtered: 7,812 `Album`, 293 `EP`, 374 `Single`, 8 `Broadcast`, 157 `Other`, and 1,356 missing. Thus this is release-group evidence, not an album-only cohort.

For a local coverage-only diagnostic, exact normalized native genre names
overlap 439 of the retained 6,291 seed names (586 distinct native normalized
names). This is not reconciliation, a quality estimate, a membership claim,
or a reason to promote any row.

The archive sample remains first-valid-records in archive order. These counts
are not a full-corpus estimate, prevalence measure, holdout result, or a
precision/recall evaluation.
