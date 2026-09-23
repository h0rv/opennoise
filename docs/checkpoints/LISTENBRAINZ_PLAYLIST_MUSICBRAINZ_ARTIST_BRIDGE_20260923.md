# ListenBrainz playlist exact MusicBrainz artist-credit bridge

This is a bounded local-only identity and coverage measurement. It does not
add a genre claim, curator-quality claim, listener claim, ranking, similarity
result, model input, serving input, static-export asset, or release artifact.

## Source pin and selection

The retained ten-playlist ListenBrainz snapshot bundle is
`.cache/listenbrainz-public-playlist-probe-20260923/snapshots.json`, with file
SHA-256
`2166a81d5f4f217971c38c2af6131e1c8e82b493851b3d6dab1c1b6a9466920c`.
Before selection, the bridge checked every receipt-bound raw JSPF object under
the bundle's `raw/sha256/<payload_sha256>` layout for regular-file status,
declared byte size, and SHA-256. The bundle's source order comprises its ten
explicit playlist UUIDs in retained order; all ten curator states remain
`unknown`.

The selection receipt uses the predeclared
`playlist_source_order_round_robin_unique_track_order` rule: take one next
previously unseen exact recording UUID from each source-order playlist in a
round, retaining each playlist's track order, until 24 IDs are selected. It
also records the selected IDs as they occur in each playlist. The resulting
per-playlist selected-ID counts are `4, 3, 3, 5, 2, 2, 2, 2, 2, 2`; this is a
receipt-bound selection rule, not a sample or representation claim.

Selection is global, but the later pair projection uses every retained
source-playlist occurrence of a selected ID. Thus, if a selected recording
also occurs in a later playlist, it contributes to both playlists' separate
within-playlist observations, always in that playlist's source track order.
The receipt makes those occurrences explicit; it does not assign a recording
to only the playlist that first selected it.

## Exact lookup result

The one 24-ID run requested only `GET /ws/2/recording/<exact UUID>?fmt=json&inc=artist-credits`
from MusicBrainz, sequentially at no more than one request per second. Each
response was streamed with a 512 KiB body ceiling, content-addressed into the
local custody cache, and replayed offline. The retained local artifact file
SHA-256 is `5bcb50b190685ec6b4d9352ec1426f2f0eec1eb3edd5c45bc1ae675747f52bb7`.

| Measure | Result |
| --- | ---: |
| Selected exact recording UUIDs | 24 |
| Successful exact MusicBrainz recording lookups | 23 |
| Exact lookups with an artist credit | 23 |
| Exact lookups with multiple credited artists | 2 |
| Distinct exact credited artist UUIDs | 23 |
| Cross-recording artist-pair observations within selected playlists | 30 |
| Distinct cross-recording artist-pair potential | 27 |

The pair measures use only two *different* selected recordings occurring in
the same retained playlist. They form unordered pairs from their exact credited
artist UUIDs, discard self-pairs, and count neither title nor artist display
text. The observation count may repeat a pair across distinct recording pairs
or playlists; the potential count deduplicates it globally. These values are
not within-recording collaboration pairs and do not establish similarity or
genre association.

The sole nonexact/abstained lookup is retained as its safe status and custody
receipt rather than inferred from another identifier. This 23-of-24 result is
therefore exact-response coverage for this pinned selection only, not a claim
about the 527-recording bundle, ListenBrainz playlists generally, or MusicBrainz
catalog completeness.

`scripts/measure_listenbrainz_playlist_artist_bridge.py` verifies the expected
bundle file SHA after bounded local custody verification and before opening the
HTTP client. Its output is local-only and refuses to overwrite an existing
artifact. `replay_playlist_artist_bridge` validates every stored response hash
and rederives the artifact offline.
