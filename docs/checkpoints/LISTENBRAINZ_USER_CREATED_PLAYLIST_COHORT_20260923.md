# ListenBrainz route-only user-created playlist cohort

This checkpoint records a bounded local-only feasibility result. It changes no
model, source policy, static asset, deployment, or release artifact.

## Result

The retained ListenBrainz route `GET /1/user/Isabelxxx/playlists?count=20`
does establish the service-level role `user_created`: its response is the
documented account playlist listing, and the ten source-order playlist
snapshots used by the earlier probe are all present in its 20 listed playlist
IDs. The route does **not** establish that the account is a person, that a
person selected the tracks, or that the list received editorial/manual review.

The local audit at
`.cache/listenbrainz-user-created-playlist-cohort-20260923/cohort.json` has
SHA-256 `dd1d3f8a5bcce73bdd28b16fb93acf23d73a2359417e4c76a6bdfa2f1f15610a`.
It binds:

- the 7,013-byte listing response, SHA-256
  `564cacb56623cd13b6760abcf18b9ac5c645e6e863bfc2ab9cea0891656bcfd2`;
- its first ten retained exact-playlist JSPF snapshots and raw-object receipts,
  through bundle SHA-256
  `2166a81d5f4f217971c38c2af6131e1c8e82b493851b3d6dab1c1b6a9466920c`; and
- the existing exact MusicBrainz artist-credit bridge for that exact bundle.

All ten snapshots and all bridge source pins are `unknown` curator state. The
audit therefore fixes both `human_curation_established=false` and
`manual_or_editorial_curation_established=false`.

The concrete requirement for a future human-curation claim is an
identity-bound curator attestation of manual selection, retained with a
source URL, retrieval date, and response hash for each claimed playlist. A
route, a username, playlist title, creator display text, missing
`created_for`, playlist ordering, or track content is not a substitute. Such
an attestation would establish only the declared manual-selection fact; it
would still not make a genre or quality claim.

## Exact-ID coverage only

The pre-existing bridge covers a receipt-bound round-robin selection of 24
exact recording UUIDs from this exact ten-playlist cohort: 23 successful exact
MusicBrainz lookups, 23 with artist credits, and 27 distinct cross-recording
artist-pair potentials. This quantifies identity coverage only. It is not a
co-listen result, similarity edge, curation-quality measurement, human
authorship claim, genre association, or model input.

## Decision

Public ListenBrainz user-playlist routes can form a source-bound local
**user-listed-as-created** cohort, but they do not presently carry a
trustworthy human-created curator signal. Keep this cohort local-only and
route-labelled until an independent identity-bound manual-selection attestation
is retained for every included playlist.

## Separate source-priority note

Do not broaden this ListenBrainz cohort with historical music-recommendation
corpora. The official [Spotify Million Playlist Dataset challenge
page](https://www.aicrowd.com/challenges/spotify-million-playlist-dataset-challenge)
now says that its historical user-created dataset is unavailable for download;
no third-party copy should be sought. The official JKU LFM-1b/LFM-2b pages are
also currently unavailable. The Million Song Dataset's Taste Profile is a
separate user play-count source, not a playlist-curation source, and would
need a separately validated song-to-MusicBrainz identity bridge. None is an
actionable source for this cohort.
