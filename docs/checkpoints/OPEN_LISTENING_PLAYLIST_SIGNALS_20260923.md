# Listening and playlist signals

This checkpoint separates user listening records from playlist contents and
records what the project has already ingested. The signals answer different
questions, so the existing measurements remain separate.

## What each source records

| Source | What its records describe | Useful identifiers and signal | Current status |
| --- | --- | --- | --- |
| ListenBrainz daily data | Timestamped user submitted listens, with recording metadata. | Timestamp and optional recording MBID; raw data also has user identity. | Seven daily objects were replayed locally. The qualified aggregate has 30,903 daily pairs and 13,175 normalized artist pairs after a five user privacy floor. It is the only listening signal eligible for production similarity where the map contract permits it. |
| Last.fm 360K | All time user and artist play counts. | Hashed user value, artist MBID when present, and play count. | The full source was checksum verified and read locally. Its aggregate retains 485,840 exact artist pairs with at least five users, but remains local research custody with no model, serving, evaluation, or public use. The source is noncommercial. |
| MusicBrainz MLHD+ | Per user historical listening events. | Timestamps and artist, release, and recording MBIDs. | Future open source, not ingested. Its published archive scale is hundreds of GB, outside the current laptop sized workflow. See the [MLHD+ documentation](https://musicbrainz.org/doc/MLHD%2B) and [MetaBrainz archive note](https://blog.metabrainz.org/2022/10/28/cleaning-up-the-music-listening-histories-dataset/). |
| Last.fm 1K | Timestamped user listening rows. | Artist MBID and a separate track ID field. The track ID is not treated here as a recording MBID. | Future source, not ingested. The creator attributed archive is 672.7 MB and has noncommercial terms. See the [Zenodo record](https://zenodo.org/records/6090214). |
| ListenBrainz playlists | Ordered recording membership in public playlists. | Playlist MBID and track recording MBIDs. Embedded artist URIs remain source claims until exact recording lookup. | Ten playlists from one service declared account contain 527 unique recording MBIDs. Curator state is unknown. This is not a listening sample or production input. |

The Melon Playlist Dataset is a future playlist source with contracted expert
playlists and user playlists filtered by Kakao's quality rules, plus Melon
song, album, and artist IDs and 30 genres with 219 subgenres; these IDs are not
MusicBrainz IDs. Kakao's page still shows a download link, while MTG says
Kakao Arena has been unavailable since 2024, so access remains unclear. The
terms limit use to noncommercial research and prohibit redistribution. See
[Kakao's dataset page](https://kakao.github.io/recoteam/arena/melon) and
[MTG's dataset page](https://mtg.github.io/melon-playlist-dataset/).

Official documentation describes ListenBrainz dumps as submitted listens and
playlists as ordered recording lists. The seven daily files are the local
ingest schedule, not the documented dump cadence. Last.fm's source page
reports 17,559,530 rows, 359,347 users, and 186,642 artists with MBIDs. The
project's strict parsing counts differ slightly. See the [dump
documentation](https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html),
[playlist API](https://listenbrainz.readthedocs.io/en/latest/users/api/playlist.html),
and [UPF source page](https://www.upf.edu/web/mtg/lastfm360k).

ListenBrainz also documents a read-time `mbid_mapping` that may include
recording, release, release-group, and artist MBIDs resolved by matching
submitted metadata. These are server matches, not IDs submitted with the
listen or guaranteed truth, and this documentation does not change the fields
retained in the current aggregate. See the [JSON documentation](https://listenbrainz.readthedocs.io/en/latest/users/json.html).

ListenBrainz's popularity API also returns artist-ranked recordings and
release groups by listen count, with `total_user_count` and exact recording or
release-group MBIDs. These counts can support separate song and album ranking
probes keyed by exact artist MBIDs. They measure popularity among ListenBrainz
users. They do not supply genre labels or establish factual genre membership. A
bounded local probe could use at most 20 supplied artist MBIDs, retain the
response receipts, and inspect up to 10 recording and 10 release-group
results per artist. Join release-group results by exact MBID to retained
MusicBrainz album evidence. Report recording-ID coverage separately because
the local recording catalog is sparse. Keep the two rankings separate and the
results local; do not use titles, tags, or ranking position as genre evidence
or model input.
See the [ListenBrainz popularity API](https://listenbrainz.readthedocs.io/en/latest/users/api/popularity.html).

The Spotify Million Playlist Dataset is not a current open input because the
official challenge page says its dataset is no longer available for download.
See the [Spotify MPD challenge page](https://www.aicrowd.com/challenges/spotify-million-playlist-dataset-challenge).

## Existing evidence and limits

The seven ListenBrainz daily objects support the receipt bound aggregate and
fixed-window local holdouts. A reversed window-order run keeps a small Recall
at 10 advantage over the fixed popularity comparison. This is a retrieval
diagnostic, not proof of musical similarity or factual membership. See the
[directional holdout](LISTENBRAINZ_DIRECTIONAL_HOLDOUT_20260923.md).

The Last.fm aggregate remains in a separate source arm because its population
and time basis differ from ListenBrainz. Rank fusion was tested and rejected.
See the [Last.fm holdout](LASTFM_DIRECT_CUSTODY_HOLDOUT_20260923.md) and
[fusion holdout](LASTFM_LISTENBRAINZ_RANK_FUSION_HOLDOUT_20260923.md).

One playlist cohort produced 171 repeated artist pair potentials across
playlists. The Last.fm aggregate recovered 41 of those pairs, with Recall at
10 of 36 among 342 directed ranking events, compared with 6 for a seeded
baseline. This is a one account descriptive comparison. Unsupported pairs
are not negatives, and the result does not establish playlist quality or
independent validation. See the [matched holdout](LISTENBRAINZ_PLAYLIST_LASTFM_360K_MATCHED_HOLDOUT_20260922.md).

The search attempt produced no auditable JSON, and the retained listing
belongs to one account. There is no cross account measurement. A new cohort
requires a compliant search response or a supplied public account or playlist
identifier. See the [feasibility checkpoint](LISTENBRAINZ_CROSS_ACCOUNT_PLAYLIST_FEASIBILITY_20260923.md).

## Next bounded experiment

If a compliant discovery response or a public identifier becomes available,
run the fixed local pilot for at most three distinct service declared account
strings. Fetch one listing page with at most two playlists per account, then
retain exact playlist and recording IDs with source order and response
receipts. Verify no more than 24 selected recording IDs through exact
MusicBrainz recording lookups. Do not use playlist titles, descriptions, or
search rank as labels or scores.

Use a leave one account out check. For each account in turn, form artist pairs
from the other accounts only, then measure their recovery in the held out
account's playlists over a candidate set fixed before scoring. Keep every
playlist from a service declared account in the same fold, and report exact
recording coverage, account level pair overlap, and Recall at a fixed cutoff
alongside a seeded ranking baseline. With at most three accounts, report raw
counts as descriptive evidence and make no significance or independent person
claim. This avoids sharing an account's playlists between pair construction
and evaluation, but it cannot establish that separate account strings belong
to separate people.

Keep the report local only. Do not merge playlist pairs with either listening
aggregate, use them as genre labels, or add them to the model, serving path,
static export, or release. This experiment tests only whether exact playlist
pair membership repeats across service declared account routes under a fixed
split.
