# ListenBrainz playlist JSPF embedded artist identifiers

This is a bounded, local-only parse of the ten retained raw JSPF objects in
`.cache/listenbrainz-public-playlist-probe-20260923/raw/sha256/`. It performs
no network request. It does not create a genre claim, artist-credit claim,
human-curation claim, similarity result, model input, serving input, public
export, or release artifact.

## Source and receipt

The parser reads only the documented JSPF track extension
`https://musicbrainz.org/doc/jspf#track`, specifically its
`artist_identifiers` values. An accepted value is an exact
`https://musicbrainz.org/artist/<UUID>` URI. These are source-provided
identifier claims, not MusicBrainz-verified artist credits.

It receipt-verifies every regular-file raw object against the ten snapshot
receipts before parsing. The source bundle is
`.cache/listenbrainz-public-playlist-probe-20260923/snapshots.json`, SHA-256
`2166a81d5f4f217971c38c2af6131e1c8e82b493851b3d6dab1c1b6a9466920c`.
The generated ignored local receipt is
`.cache/listenbrainz-playlist-embedded-artist-ids-20260923/receipt.json`,
SHA-256 `a56d079120d7948d9250ba8474c47bc1a7a75a4793cd0a880d7decdc6021f188`.

The parser accepts at most 200 tracks per playlist, 16 source artist URIs per
track, and one million candidate cross-track artist-pair expansions. It rejects
custody mismatches and any cohort that exceeds those limits.

## Observed source-claim coverage

| Measure | Count |
| --- | ---: |
| Raw track occurrences | 557 |
| Exact recording occurrences | 557 |
| Distinct exact recordings | 527 |
| Nonempty source artist-identifier occurrences | 557 |
| Syntactically valid source artist URIs | 603 |
| Invalid source artist URIs | 0 |
| Distinct source-claimed artist IDs | 344 |
| Multi-artist source-claim occurrences | 42 |

The JSPF playlist extension contained a creator field in all ten objects. All
557 tracks had both `added_by` and `added_at`; every retained `added_by` string
equalled that playlist extension's creator string. This is only an
account-level source-metadata observation for this one listing cohort. It does
not establish a human identity, manual selection, editorial quality, or human
curation.

## Cross-track coappearance, one account cohort only

Pairs combine claimed artists from two different recording occurrences in the
same playlist, discard self-pairs, and never count same-track collaborators as
playlist coappearance. The measurement found 24,118 cross-recording artist-pair
observations and 13,584 distinct unordered artist-pair potentials.

171 potentials occur in at least two playlists. This is a repeat-within-one-
account-cohort count, not independent-user support, curator support, or a
privacy-floor result. All ten source playlists came from one account listing.

## Comparison with retained exact MusicBrainz bridge

The existing source-pinned 24-recording bridge had 23 `exact_match` MusicBrainz
recording responses. All 23 had an unambiguous JSPF source claim, and the exact
unordered artist-ID set agreed for all 23. There were zero disagreements and
zero ambiguous source-claim recordings. This limited agreement does not turn
the other source claims into verified credits, nor does it claim coverage beyond
the retained 23 exact responses.

Run the local-only parser with
`scripts/measure_listenbrainz_playlist_embedded_artist_ids.py`; it refuses to
overwrite an existing output and has no Poe task.
