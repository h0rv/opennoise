# MusicBrainz pre-filter unplaced audit

This is a local-only research checkpoint. It did not write a public database,
asset, or membership. It reads the current semantic layout only to obtain its
unplaced seed names. No historical Every Noise data was read beyond the seed
names already retained in that layout.

## Frozen inputs

- Layout: `.cache/semantic-map-layout-v2/artifact.json`; logical output hash
  `853353cfdc4d9ad1ea2a6faaaf58eff372b760133f70d3512e8d6de185838f76`;
  byte hash `c07b6ab63818339c1f31fdc0ea43201ab3b71c53b11ac891f66098ebbf0c9166`.
- The deployed v3 layout has the same ordered unplaced seed ID list as v2.
  Its logical output hash is
  `469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38`.
  Its byte hash is
  `e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972`.
- Retained MusicBrainz seed-target artifact:
  `.cache/musicbrainz-full-seed-targets/musicbrainz-seed-targets-v1.json`;
  logical output hash
  `1cfe14b7dfce41c5f1b45c423407c7c1ad528abbafa3b3b859770e49c8debe46`;
  byte hash `481eb68f7d75d8562fe16aa1f9faef327d24e8afd5145fa5c7d136ed9ac69dfe`.

## MusicBrainz direct-tag lower bound

The layout contains 3,346 unplaced seeds. A bounded stream of the retained
seed-target artifact read 421,427 direct tag rows. It found 1,080 rows for
577 unplaced seeds and 999 supporting artists/source records. Of those, 1,029
rows for 546 seeds were literal `match_kind=exact` and spelling-identical;
51 rows used normalized or reviewed matching.

These are source-positive lower-bound claims, not artist-to-genre memberships.
The report therefore records `publishable_membership_count = 0`.

The source artifact was already filtered to the seed vocabulary by its
extractor. It cannot measure negative support or serve as the requested true
pre-filter source slice. The retained 1,187,679,180-byte MusicBrainz vault XZ
object (`a1a45e5f6f0f642e8a63455188cddc449bd248da68f1f5a1109a9183fd0a82fa`)
is a release-group dump, not an artist-tag dump, and is unusable for that
question.

Smallest bounded acquisition: one checksum-bound MusicBrainz artist JSON-dump
partition, or a derived tag-only partition, containing artist MBID, tag name,
source-record ID, and source-record hash. Stream it once against this frozen
unplaced-name set. Do not infer zero source support until that input exists.

## Peer edge cross-check

The layout builder places every seed that has a peer, co-listen, or hierarchy
edge. The local peer index has no peer edge for any of the 577 MusicBrainz
direct-tag-supported unplaced seeds. The peer candidate and directional
neighbor artifacts also have no row for any of the 577 seeds.

The peer builder did record 3,269 abstentions for 495 of the 577 seeds. Every
one has the reason `insufficient_direct_overlap`. The current source peer rule
therefore suppresses 495 seeds before edge creation. The remaining 82 have no
recorded candidate or abstention. A minimal source-backed experiment is to
replay the peer candidate builder for the 495 abstained seeds with only its
direct-overlap minimum changed, then report edge count, affected components,
and placement coverage without publishing a layout. It must retain the same
MusicBrainz source hashes and must not use the Last.fm evaluation archive.

The peer input is
`.cache/musicbrainz-full-seed-targets/pipeline/peer-similarity-local-research.sqlite`.
Its byte hash is
`3a71511755e015684b65d55c90b33fc08d0e38040e372ad52cf2731398ec7e63`.
The linked peer candidate has logical output hash
`15ce7a9a2b40caf64fa1f4050457d4a36635db132a92f9c70a5edce45d68b1cd`.
The current peer candidate setting requires at least two shared direct artists.

## Separate Last.fm exploratory count

The pinned `Lastfm-ArtistTags2007` archive is a distinct exploratory
construction-source candidate, not combined with the MusicBrainz result. Its
archive SHA-256 is
`b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f`.

Across 952,810 positive rows, literal unplaced-name matching found 1,593 rows
for 291 seeds, covering 1,463 MusicBrainz artist IDs with raw-tag-count sum
4,529. It also records `publishable_membership_count = 0`. Promoting this
archive into construction while it is retained as an independent evaluation
set would forfeit that evaluation independence.
