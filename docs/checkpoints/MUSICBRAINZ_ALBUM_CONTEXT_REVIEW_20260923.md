# MusicBrainz Album context review packet

The local review packet is `.cache/musicbrainz-album-context-review-v2/packet.json`.
It was assembled from the already-retained album example report; it does not
replay or scan the release-group archive. The report contains examples for 893
of the pinned 6,291 seeds, with a maximum of five retained albums per seed.
Those limits describe report coverage, not the MusicBrainz catalog as a whole.

The fixed sample has 20 seed questions across four strata: four broad seeds
(`rock`, `jazz`, `folk`, `metal`), five microgenre seeds (`hyperpop`, `ambient`,
`drone`, `shoegaze`, `grindcore`), six geographic or cultural seeds (`afrobeat`,
`bossa nova`, `cumbia`, `k pop`, `reggaeton`, `salsa`), and five seeds whose
reconciliation disposition is ambiguous (`pop`, `rap`, `hip hop`, `soundtrack`,
`chanson`). The strata are sample design labels, not MusicBrainz taxonomy
claims.

The packet includes the first two retained examples for each populated seed,
preserving exact release-group MBIDs, credited artist MBIDs, genre MBIDs,
positive native proper-genre vote counts, and source record content hashes.
`rap`, `soundtrack`, and `chanson` have no retained examples and remain
abstentions. A missing example means only that this bounded report retained no
candidate for that seed.

The source role is a native proper-genre observation. Credited artist IDs are
release-group credit context only. Votes and exact seed names are source
context, not reviewer conclusions or artist membership. Review judgments and
notes start empty; later reviewer annotations do not change the evidence hash.
The packet is local only, non-exportable, not serving or model input, and makes
no artist-membership, representative-album, or quintessential-album claim. No
Spotify map coordinates are used.

The packet stores hashes for the report, source archive, source-cache receipt,
seed reconciliation, and its own deterministic logical content. Rebuild from
the retained inputs with:

```sh
python scripts/build_musicbrainz_album_context_review.py
```

The create-only builder refuses to replace an existing packet. The report's
source archive SHA-256 is
`6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43`; the
reconciliation SHA-256 is
`a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0`.
