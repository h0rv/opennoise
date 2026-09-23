# Playlist and album evidence join

This local-only report joins the retained playlist overlap report to the
completed MusicBrainz evidence database by exact MusicBrainz release-group and
artist IDs. It is `.cache/playlist-album-evidence-join-v1/report.json`, with
logical SHA-256 `da966d9e1e8241b6fff9fdac7e4027fa46bf303a7c80c988d6c223a2ea13ccb0`.

Note: v1 called rows from `release_group_support` "credited artist" evidence.
That name was limited and did not measure release-group artist credits. The
table only contains release-group genre or tag matches to a seed. The raw
archive credit bridge supersedes v1 for credit coverage. See
[Playlist album credit coverage](PLAYLIST_ALBUM_CREDIT_COVERAGE_20260923.md).
The v1 report facts below remain unchanged.

The report keeps four fields separate. A playlist occurrence remains a
ListenBrainz playlist-track occurrence. A MusicBrainz release-group proper
genre remains a release-group observation. A credited artist remains
release-group context from the support table. A direct-anchor row remains a
local MusicBrainz genre or tag facet for its exact artist MBID. No field turns
album or playlist context into artist membership.

The bounded run requested the two release groups reached by the existing
playlist report. One has native proper genres, and one has no native proper
genre. The tag-only release group remains an explicit abstention and no tag is
treated as a proper genre. Neither release group has a matching credited-artist
support row in the completed evidence database, so both exact playlist contexts
retain empty credited-artist and direct-anchor fields. This is an overlap and
coverage result, not a negative claim about the release groups or artists.

The report verifies the prior playlist-overlap receipt and the completed
evidence artifact before hashing the local SQLite database. Its output is
local only, non-exportable, non-serving, and excluded from model input. The
fixture tests cover exact IDs, separate roles, multi-artist direct-anchor
attribution, no-proper-genre abstention, deterministic output hashes, and a
rejected database hash.
