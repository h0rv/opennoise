# Last.fm direct-custody retrieval holdout

Local-only, pinned evaluation of the same fixed MusicBrainz direct-custody
membership fold used by the ListenBrainz comparison. It uses only the
privacy-filtered Last.fm 360K exact-artist pair aggregate; no Last.fm tags,
historical data, playlists, or public artifact is read or written.

The report at `.cache/lastfm-direct-custody-holdout-v1/report.json` pins the
Last.fm artifact `6d311156…`, companion receipt `c81d9bd8…`, aggregate DB
`a63ae002…`, and the direct-custody graph receipt/database. The >=5-user
aggregate ranks candidates by summed `log(1 + distinct_user_count)` from each
seed's train artists, excluding known train artists. The fold is unchanged.
Its logical output SHA-256 is
`974a4b0c31433de1389c5e0feaa6d4977417517a9d1c32d59edc266868cb7158`
(file SHA-256 `2e83dbbdb650541e6a2fc78d5138dffebc76609e3e325c0053281ac9164fd588`).

On the full 77,206 held-out direct positives, Last.fm supports 5,639 and
recalls 610 at 20 (0.7901%). On the Last.fm endpoint-matched denominator of
6,818 positives, it recalls the same 610 (8.9469%). This is source-bound
retrieval coverage only, not precision, genre truth, factual membership,
musical similarity, model input, or promotion evidence. Last.fm and
ListenBrainz remain separate populations and graphs. On the common
endpoint-conditioned cohort of 873 positives, separately scored Last.fm
recalls 257 at 20 (29.4387%) and separately scored ListenBrainz recalls 134
(15.3494%). This shared denominator is availability conditioning, not a
source-population comparison, precision result, or merged score.
