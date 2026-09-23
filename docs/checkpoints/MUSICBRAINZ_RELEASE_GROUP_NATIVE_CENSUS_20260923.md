# MusicBrainz release-group native census

The aggregate-only census adapter is prepared for the pinned 1,159,485,640-byte
release-group archive. Before it reads records it requires the pinned archive,
source-cache receipt, immutable 6,291-name reconciliation byte hash
`a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0`, and
the 3,346-unplaced-seed v3 layout byte hash
`e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972`.

It retains only aggregate native genre UUID/name/vote-sign counts, aggregate
credited artist-component counts, primary-type counts, and exact normalized
seed and unplaced-seed overlap counts. It never writes a release-group ID,
title, record hash, artist ID, artist membership, or a direct genre claim.

The full stream completed on 2026-09-23 in one persistent local process. It
ran for about 4 minutes 33 seconds and wrote the required create-only ignored
cache report at `.cache/musicbrainz-release-group-native-census-v1/report.json`.
The report is 385,819 bytes. Its byte SHA-256 is
`158047e949f1ca2fccbba8b64d5f4299931d3823372be6e3ebc30052102b53d4`, and
its internal output SHA-256 is
`f110353535321e9f76da91a383e957753a514422142d5c6a2dbe7e6d5592d706`.

The builder verified the pinned 1,159,485,640-byte archive SHA-256
`6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43`, the
source-cache receipt SHA-256
`2b2ae54fe057e5dd41d46a3a8ebeafad698a6ce8474135780ffd3b988c5c1dde`, the
6,291-name reconciliation hash, and the 3,346-unplaced-seed layout hash.
The stored report then passed Pydantic validation and an independent
recalculation of its internal output hash.

The full census saw 4,499,326 raw records. It rejected no over-limit records
and 40 malformed records, then parsed 4,499,286 release groups. Those groups
contained 4,596,870 proper-genre observations, 5,331,494 credited
artist-components, and 1,686 distinct native genre UUID rows. Exact normalized
names overlapped 911 of the 6,291 seeds. The unplaced seed names are within
that seed universe, and 68 of the 3,346 unplaced names overlapped the native
genre rows.

The primary-type counts were 2,315,330 Album, 1,411,480 Single, 578,901 EP,
101,851 missing type, 64,198 Other, 27,526 Broadcast. This is a completed
aggregate census, not an extrapolation from the separate 10,000-record
observation, and it remains local-only and non-serving.

## Exact unplaced-name coverage decision

A second create-only local report reads the completed census and the same
pinned reconciliation and layout inputs. It does not read the archive, tags,
release-group identities, or artist identities. The report is at
`.cache/musicbrainz-release-group-native-census-decision-v1/report.json`. Its
byte SHA-256 is `c098380d30cef71f3915289ddba819b9c873f1ec318fd8782fc26341c6a69cfb`.
Its internal output SHA-256 is
`35981cf56c6d0b9435e52b6f87573a08ea1015ac5b7090971359a52adabc9031`.
The report pins the completed census output hash
`f110353535321e9f76da91a383e957753a514422142d5c6a2dbe7e6d5592d706` and the
reconciliation and layout hashes stated above.

The native proper-genre rows exactly match 911 seed names. The 911-name scope
has 3,671,777 observations, all with positive votes, and 4,153,505 credited
artist components on the observed release groups. The positive-vote support
bins contain 911 names at one or more observations, 887 at two or more, 844 at
five or more, and 813 at ten or more.

The same exact-name comparison matches 68 of the 3,346 unplaced seed names.
The 68 names have 957 observations, all with positive votes. No matched row
has zero, negative, or missing votes. All 68 names have credited artist
components on their observed release groups, for an aggregate total of 1,076.
Their positive-vote support bins contain 68 names at one or more observations,
53 at two or more, 35 at five or more, and 26 at ten or more. The capped
aggregate-only top list begins with skweee (105), mbalax (94), zenonesque (77),
andalusian classical (72), and luk thung (68).

The measurement does not fill a map gap. A native release-group genre row does
not assert artist membership, does not create a genre-to-genre relation, and
does not authorize a coordinate or placement. Proper genres remain separate
from MusicBrainz tags. The 68 names are a local exact-name evidence frontier
for later relation research only.
