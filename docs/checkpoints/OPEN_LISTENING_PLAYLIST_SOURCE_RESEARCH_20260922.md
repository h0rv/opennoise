# Open listening and playlist source research checkpoint

This read-only research update changes no source policy, model, static asset,
deployment, or release artifact. It reconciles the existing source inventory
with current first-party documentation.

## Decision

The single actionable next experiment is a bounded, source-bound, local-only
exact-ID expansion of the already receipt-bound ten-playlist ListenBrainz
cohort: select a predeclared source-order sample of at most 50 *previously
unlooked-up* JSPF recording MBIDs, retrieve each exact MusicBrainz recording
lookup, and retain only the recording MBID, response hash, returned
artist-credit MBID set, lookup date, and abstention/error state. The sample
must exclude the already checked 24-recording bridge. Do not name-match; do not use JSPF titles,
descriptions, `creator`, `added_by`, or ordering as labels; and do not produce
co-occurrence edges, rankings, membership claims, or model/evaluation input.

This is preferable to a new corpus: the inventory already has 527 distinct
exact recording MBIDs in that cohort, but only 23 successful exact recording
responses in its 24-recording bridge. It measures a clearly bounded identity
question: how many retained playlist recording IDs map to MusicBrainz artist
credits. It does not establish human curation, independent users, listening,
or genre. The MusicBrainz API supports lookup by a supplied entity MBID, and
recordings carry an artist credit; an MBID avoids an ambiguous name search.
[MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API),
[Recording](https://musicbrainz.org/doc/Recording).

## Source assessment

| Source | Actual listening or playlist fields | ID bridge and scale/access | Bias and leakage-safe use |
| --- | --- | --- | --- |
| ListenBrainz listens | A listen supplies `listened_at` and `track_metadata`; the submitted optional `additional_info` can contain artist, release, release-group, recording, and track MBIDs. Fetched listens may additionally have server `mbid_mapping`, whose recording and artist IDs are matched results. | Public dumps contain all submitted listens as JSONL. The documented full-dump cadence is twice monthly and incremental cadence twice weekly. This is a raw, user-event corpus, not a playlist corpus. Exact IDs are optional, so absent IDs must abstain. [JSON format](https://listenbrainz.readthedocs.io/en/latest/users/json.html), [dumps](https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html). | Submitter/service population and optional-ID coverage are selection mechanisms, not population representation. Keep listener identifiers only in an in-memory, fixed-window aggregation; retain privacy-thresholded aggregate support only. Local daily cache objects do not change the published dump cadence. |
| ListenBrainz public playlists | The ordinary `GET /1/user/(playlist_user_name)/playlists` route returns playlist metadata without recordings; `createdfor` is a distinct route for playlists created for a user, and `collaborator` is distinct again. A fetched JSPF playlist has a playlist MBID; each track must identify a MusicBrainz recording MBID. JSPF track extensions can include `added_by`, `added_at`, release ID, and source-provided artist-ID URIs. | Public listing/search and exact-playlist fetch routes are documented. Exact recording IDs are a direct bridge to a MusicBrainz recording lookup; JSPF artist IDs are source claims until verified. [Playlist API](https://listenbrainz.readthedocs.io/en/latest/users/api/playlist.html), [JSPF extension](https://musicbrainz.org/doc/jspf). | A route categorizes service behavior, not whether a person manually selected tracks. Search ranks title/description similarity, so it cannot select a genre sample. Keep only source-order recording coappearance as local context; exclude all playlist text and source-claimed credits from labels, factual membership, and evaluation. |
| Last.fm 1K | The creator-attributed Zenodo record defines rows as user ID, timestamp, MusicBrainz artist ID, artist name, MusicBrainz track ID, and track name. It contains 19,150,868 rows for 992 users, collected through the Last.fm recent tracks method through 2009-05-05. | Zenodo record [6090214](https://zenodo.org/records/6090214) lists `lastfm-dataset-1K.tar.gz` at 672.7 MB with archive MD5 `a79a6808f54f73354789a9fb02cb1e41`. The artist ID is an exact artist bridge. The track ID is an exact MusicBrainz track ID, not a recording ID, so recording use needs a separate exact bridge. The record permits noncommercial use. | The archive is a feasible future local only streaming identity audit after terms review and an acquisition checked against its checksum. Do not download it for the current playlist experiment. Keep user IDs only while forming a fixed aggregate that meets a privacy threshold. Do not use names, track titles, or source order as joins or labels, and do not use the result as genre truth, artist membership, evaluation gold, or public data. |
| Last.fm 360K (already retained) | Each row is hashed user, artist MBID, artist name, and all-time play count; the companion profile has demographics and signup date. It has no event timestamp or playlist membership field. | Official page reports 17,559,530 rows, 359,347 users, 186,642 artists with MBIDs, and non-commercial terms. [UPF dataset page](https://www.upf.edu/web/mtg/lastfm360k). | A historical Last.fm top-artist sample with all-time counts. Preserve the existing local-only aggregate boundary; it is neither independent gold nor a replacement for timestamped listening data. |
| MLHD+ | One randomly UUID-named file per user; each row is timestamp, artist MBID(s), release MBID, and recording MBID. `-complete` files have recording IDs matched to canonical recordings; `-partial` can lack or contain unresolved IDs. | It is downloadable from MusicBrainz, has a direct artist/release/recording MBID bridge, and is large enough to require an explicit bounded-acquisition plan. It is a March 2023 MusicBrainz snapshot. [MLHD+](https://musicbrainz.org/doc/MLHD%2B). | Per-user history is not an independent label source and shares MusicBrainz-derived canonicalization with the catalog. If ever evaluated, split by time and user before aggregation; use exact complete-row IDs only and treat shared MusicBrainz provenance as leakage risk. No acquisition now. |
| Spotify Million Playlist Dataset | Playlist membership only: Spotify says the sample contains one million public user-created playlists (2010--2017); rows include playlist title, track list, Spotify track/artist/album URIs, position, and playlist metadata such as modification time and edit count. | Spotify reports over two million tracks and nearly 300,000 artists. Its historical re-release used AICrowd for non-commercial research, but the current [official AICrowd challenge page](https://www.aicrowd.com/challenges/spotify-million-playlist-dataset-challenge) says the dataset is no longer available for download. The documented fields are Spotify IDs, not MBIDs; an exact bridge is unproven. [Spotify Engineering schema](https://engineering.atspotify.com/2018/5/introducing-the-million-playlist-dataset-and-recsys-challenge-2018), [Spotify Research re-release](https://research.atspotify.com/2020/09/the-million-playlist-dataset-remastered). | It is a historical Spotify playlist corpus, not user listening. The official challenge page says sampling, dithering, and fictitious tracks were used, so it is nonrepresentative. Do not obtain third-party mirrors. User-created is a dataset collection description, not evidence that every item is manual, expert, or independent genre evidence. It is not the next experiment. |
| Spotify MSSD | Spotify describes approximately 150 million listening sessions with user actions and metadata/audio features for about 3.7 million unique tracks. The official page does not document a MusicBrainz-ID field. | The official research announcement establishes a historical release, but no current primary access endpoint or exact MBID bridge was verified here. [Spotify MSSD announcement](https://research.atspotify.com/publications/the-music-streaming-sessions-dataset-short-paper). | It is genuine session listening data, not playlists, but is not actionable: do not infer availability, obtain a third-party copy, name-match its tracks, or treat user actions as genre labels. |
| Melon Playlist Dataset | 148,826 playlists, 649,091 songs, 30,652 playlist tags, 30 genres, and 219 subgenres. Playlist rows carry a local playlist ID, title, tags, song-ID list, likes, and modification date; song metadata has local song/album/artist IDs, names, and genre lists. The accompanying audio representation is out of scope. | Kakao's Melon DJ service includes playlists made by contracted experts for quality assurance and user playlists filtered to Kakao quality criteria. MTG says Kakao Arena has been unavailable since 2024 and directs users to contact it for access. Its declared identifiers are Melon-local, not MBIDs, so no exact bridge is established. [MTG dataset page](https://mtg.github.io/melon-playlist-dataset/), [Kakao dataset page](https://kakao.github.io/recoteam/arena/melon). | This is a potentially strong curated-playlist signal, but it is not actionable now: no access, no exact MBID bridge, and its titles/tags/genre fields would be leakage-prone. Do not obtain third-party copies, use audio, name-match, or treat its curation path as an artist-genre label. |
| LFM-1b / LFM-2b | Historical Last.fm listening-event corpora. LFM-2b documents user, track, album, timestamp and name-based artist/track tables, but no MusicBrainz-ID field in that declared schema. | Both official JKU pages now say the datasets are unavailable for download because of license issues. [LFM-1b](https://www.cp.jku.at/datasets/LFM-1b/), [LFM-2b](https://www.cp.jku.at/datasets/LFM-2b/). | Not an acquisition path. Its name-based join would not meet the exact-ID requirement even if access returned. |

## Canonicalization boundary

For a verified playlist recording MBID, first preserve that supplied ID and
the exact MusicBrainz recording artist credit. Canonical recording mapping is
an optional, separately versioned *normalization* layer only. MusicBrainz
says its canonical-recording redirect maps each recording to a representative
recording and that canonical IDs are not guaranteed stable across dumps.
Therefore store source recording ID, canonical-map release/version/hash, and
canonical recording ID separately; never overwrite the source ID or collapse
versions before a time-aware analysis. [Canonical MusicBrainz data](https://musicbrainz.org/doc/Canonical_MusicBrainz_data).

## Local inventory check

`src/opennoise/sources/listenbrainz.py` is a bounded raw-listen adapter that
forms privacy-thresholded artist aggregates and intentionally does not emit a
listener ID. There is no public-playlist ingestion adapter. The existing
playlist artifacts are local probes, and the source inventory already bars
them from serving, membership, model, and evaluation use. This experiment
would remain in that same local-only custody lane.

## Last.fm 1K feasibility

The 672.7 MB archive is small enough for a future old laptop local streaming
feasibility audit, but no archive is being downloaded for this checkpoint. The
audit would first record the Zenodo version, download URL, published MD5, local
SHA-256, and non-commercial terms. It would then read the compressed TSV once
without extracting it, reject malformed or oversized rows, and count only
valid exact artist and track UUIDs, timestamp coverage, and exact artist-ID
overlap with the local catalog.

The first output should be a receipt with counts only. It must not retain user IDs,
names, titles, individual listens, or per-user histories. A later aggregate
experiment would need a fixed time window, a declared privacy threshold, and
separate user and time splits. It must retain only aggregate artist pair
support that meets the privacy threshold. The source's MusicBrainz track IDs
need a separately pinned exact track to recording bridge before any recording
analysis.

## Follow-up dry-run receipt

The selection-only implementation ran against the retained ten-playlist
bundle and the exact prior bridge. It wrote
`.cache/listenbrainz-playlist-artist-followup-20260922/selection.json`, SHA-256
`2bac1641dad3201d77086344de5824f39f7f6ed6ae523dd91c043a9c32ee74f1`.
The receipt pins the existing playlist-bundle SHA-256
`2166a81d5f4f217971c38c2af6131e1c8e82b493851b3d6dab1c1b6a9466920c`
and prior-bridge SHA-256
`5bcb50b190685ec6b4d9352ec1426f2f0eec1eb3edd5c45bc1ae675747f52bb7`.
It selects exactly 50 unique recording MBIDs under the predeclared
source-order round-robin rule after excluding all 24 prior IDs.

One live MusicBrainz attempt was made with only these 50 IDs, the existing
one-request-per-second and 512 KiB limits, and contact user agent
`opennoise/0.1 (https://opennoise.horv.co)`. The deterministic selection
recheck produced the same SHA-256 above, but the first request produced no
response custody object or output artifact after approximately 150 seconds.
The process was interrupted once (exit 130); it was not retried or broadened.
Thus `.cache/listenbrainz-playlist-artist-followup-20260922/raw/sha256/` has
zero files and `audit.json` is absent. The result remains dry-selection-only,
not a lookup result.

The code path is mock-tested at the one-request-per-second ceiling and retains
only local response custody objects and exact artist-credit MBIDs if a future
approved run occurs.

Offline replay revalidates those captured response objects and rederives their
safe exact-ID receipts. It does not re-read the playlist bundle, raw JSPF
objects, or prior bridge; selection creation performs that separate source
receipt verification.

## Explicit non-decisions

- Do not treat a public ListenBrainz playlist as human, manual, or editorial
  curation. `createdfor` is a service route distinct from the ordinary user
  listing, not evidence of manual authorship.

- Do not merge ListenBrainz, Last.fm, or MLHD+ aggregates or use any as a
  genre target. Their populations, collection periods, and identifier
  completeness differ; MLHD+ additionally shares MusicBrainz normalization.

- Do not download a new full listening corpus for this experiment. The
  experiment is an identity-coverage audit over retained exact IDs.
