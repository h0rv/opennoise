# ListenBrainz account cohort pilot decision

This is a source-design note. It changes no source policy, model, static
asset, deployment, or release artifact.

## Decision

Public ListenBrainz playlists can provide true, ordered recording membership
for a bounded cohort. The exact-playlist response is JSPF. Each track in a
created playlist must carry a MusicBrainz recording MBID. A source recording
MBID can be checked through an exact MusicBrainz recording lookup, whose
artist credit is the verified artist-ID bridge. A JSPF artist URI is only a
source claim until that lookup succeeds.

They cannot provide an independently verified curator or person cohort. The
ordinary account route can establish that the service associates a playlist
with an account. Separate route receipts can establish only distinct
service-declared account strings. They cannot establish distinct people,
manual selection, editorial review, listening behavior, or genre evidence.

The official API has no global popular or recent playlist listing. Its public
search route matches playlist title and description text, which must remain
discovery-only. The prior neutral-search attempt returned browser-verification
HTML rather than the documented JSON. Independent account discovery is
therefore blocked for now. Exploratory local acquisition can proceed when that
route returns retained JSON or a public account or playlist ID is supplied.

Sources: [ListenBrainz playlist API](https://listenbrainz.readthedocs.io/en/latest/users/api/playlist.html)
and [core API playlist routes](https://listenbrainz.readthedocs.io/en/latest/users/api/core.html).

## Fixed bounded pilot

When a compliant entry point exists, make one neutral search request or accept
one independently supplied public ID. Select at most three distinct declared
account strings in source order. For each account, fetch one ordinary public
playlist listing with `count=2`, then fetch at most two listed exact playlist
IDs. This is at most ten ListenBrainz requests, including discovery.

Stop on any non-JSON response, missing or duplicate ID, rate-limit warning,
429 response, or response that cannot be retained in local raw custody. Use a
contactable User-Agent, one request per second at most, and the documented
rate-limit headers. Retain source URL, retrieval time, body hash, raw body,
playlist ID, and source-order recording membership locally. Separately select
at most 24 unique recording MBIDs for MusicBrainz lookup, in round-robin
account, playlist, and source-order position after removing duplicates. Make
at most 24 exact MusicBrainz recording requests at the documented one request
per second ceiling. Retain their receipts locally. Do not publish account
strings, playlist text, raw JSPF, or artist-credit claims that have not passed
an exact MusicBrainz lookup.

Report only exact recording coverage, playlist-size distribution, per-account
normalized pair support, cross-account pair overlap, and verified artist-credit
coverage. The report is exploratory research only. It cannot change serving,
public artifacts, or release decisions, and it must not claim human curation,
independent listeners, genre membership, similarity, or ranking quality.

## Priority

This is the best next playlist pilot because it uses true membership and exact
MusicBrainz recording IDs under a small fixed request budget. It remains
conditional on a compliant discovery response or supplied public ID. The
existing [Last.fm 360K common-cohort holdout](LASTFM_DIRECT_CUSTODY_HOLDOUT_20260923.md)
is separate listening evidence. It recalls 257 of 873 positives at 20 versus
134 for ListenBrainz on that availability-conditioned shared cohort. The
comparison does not establish population coverage, precision, or stronger
musical evidence for either source. The next listening-only pilot is the
existing checksum-pinned Last.fm 1K feasibility scan. Spotify's Million
Playlist Dataset has no verified exact MusicBrainz bridge. MLHD+ has exact IDs
but is about 272 GB compressed, so it is not laptop-bounded.
