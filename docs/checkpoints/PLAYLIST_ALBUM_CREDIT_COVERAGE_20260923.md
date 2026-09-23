# Playlist album credit coverage

The two exact release groups reached by the local ListenBrainz playlist overlap
have exact MusicBrainz release-group artist credits in the retained
`mbdump/release-group` archive. `966a02cf-fc62-3abc-8560-c60ce115efed` credits
Mazzy Star (`c48d4327-8122-4286-af66-05e1ee6ac4d8`), and
`1477a3a0-ebb3-434c-8b29-5e986b85778b` credits Ray Charles
(`2ce02909-598b-44ef-a456-151ba0a3bd70`). Both artist IDs also have separate
direct-anchor rows in the completed local evidence database.

The completed local report is
`.cache/playlist-album-evidence-join-v2/report.json`. Its SHA-256 is
`34d4ca1bb4774e4c457a9143db5d909e71e76ca03e3daaf1ff0cf2053d2b9031`.
It requested two release groups. One has a proper genre, both have an exact
credited artist, and both credited artists have direct evidence. The Ray
Charles context has six direct rows, and the Mazzy Star context has ten.

The previous zero was a coverage limitation of `release_group_support`: that
table is populated only when a release-group genre or tag matches a seed. It is
not an artist-credit catalog, so zero support rows did not mean zero release
group credits. The bounded replay bridge reads only the two receipt-bound raw
records, verifies each record hash against the playlist overlap, retains the
ordered credit components, and queries direct-anchor evidence only by those
exact credited artist IDs.

Playlist occurrence, native release-group proper genres and positive tags,
credited artists, and direct artist genre/tag evidence remain distinct roles.
Neither the album context nor the playlist asserts artist genre membership.
This is local-only, non-serving, non-exportable, and excluded from model input.

Hard gaps remain: the sample is two release groups from unknown-curator
playlists; one group has tags but no proper genre; and direct-anchor evidence is
coverage, not a label derived from either release group. No static or model
release change follows from this checkpoint.

To reproduce the local report, run:

```bash
.venv/bin/python scripts/build_playlist_album_evidence_join.py \
  --overlap-report .cache/listenbrainz-playlist-release-group-overlap-v1/report.json \
  --evidence-database .cache/musicbrainz-release-group-evidence-candidate-v1/evidence.sqlite \
  --evidence-artifact .cache/musicbrainz-release-group-evidence-candidate-v1/artifact.json \
  --artist-credit-archive .cache/musicbrainz-release-group-source-objects/source-artifacts/sha256/6f153846228dc6034b2f8f43b472b088792cc2e242b09783a8968fa8d4bd7a43 \
  --output .cache/playlist-album-evidence-join-v2-replay/report.json
```
