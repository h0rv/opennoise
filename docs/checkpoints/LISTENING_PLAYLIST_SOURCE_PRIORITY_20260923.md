# Listening and playlist source priority

## Decision

Prioritize existing receipt-bound ListenBrainz aggregate evidence and bounded
exact-ID probes. Do not acquire a new full listening corpus, treat playlist
co-occurrence as user/curator-uncertain context rather than genre truth, and
do not acquire the 2026 collaborative knowledge-graph repackaging.

| Priority | Source and signal | Exact identity / scale | Provenance and boundary |
| --- | --- | --- | --- |
| 1 | Existing qualified ListenBrainz aggregate | 30,903 daily pairs; 13,175 normalized artist pairs already receipt-bound. | Privacy-filtered user listening aggregate; the only listening signal currently eligible where the production-map contract permits similarity. It is not factual membership. |
| 2 | Existing Last.fm 360K full aggregate | Completed local aggregate: 17,559,530 rows scanned, 160,131 strict exact artist UUIDs, and 485,840 artist pairs retained at the >=5-user floor. The observed strict-parser counts remain distinct from the source page's 359,347-user and 186,642-MBID artist population figures. | All-time user--artist play counts with hashed users, non-commercial terms, and a distinct population/time basis from ListenBrainz. It is ignored local aggregate custody only, with no user identifiers, and is ineligible for model or evaluation use. Never treat it as genre gold or merge it with ListenBrainz without a separately approved population-comparability design. |
| 3 | Public ListenBrainz playlists | JSPF MusicBrainz extensions require a recording MBID per track. The retained ten-playlist probe has 527 unique exact recording MBIDs, but every curator state is `unknown`. | Ordered playlist co-occurrence is neither a user-listening sample nor evidence of human curation. The ordinary `playlists` route is the only route-level evidence labeled `user_created`; `createdfor` and recommendations retain their distinct routes but have unknown source role. No route receipt attaches a playlist identity without retained raw-listing membership proof. See the [route classifier checkpoint](LISTENBRAINZ_PLAYLIST_SOURCE_ROLE_20260923.md). Do not use titles/descriptions as genre labels. |
| 4 | AcousticBrainz Discogs validation | 63 locally bridgeable exact recording/release-group/single-primary-artist rows. | Metadata-only positive recording-label diagnostic, never a listening signal or artist-membership label. It is conditionally usable only after an exact MusicBrainz-tag leakage exclusion audit. |

The creator-attributed [Last.fm 1K Zenodo record](https://zenodo.org/records/6090214)
is a future local only feasibility candidate, not a current priority. It lists
a 672.7 MB archive with 19,150,868 timestamped rows for 992 users and exact
MusicBrainz artist and track ID columns. A streaming audit with counts only should
verify the published MD5 `a79a6808f54f73354789a9fb02cb1e41`, record a local
SHA-256, and measure valid exact IDs before any aggregate work. The track ID
does not establish a recording bridge. Any later aggregate must use fixed user
and time splits, retain no user IDs, apply a privacy threshold, and remain out
of the model, evaluation, and public data paths until separately approved.

## Excluded duplicate: 2026 collaborative music knowledge graph

The [Zenodo v1 deposit](https://zenodo.org/records/20394102) is not a new
listening source. Its own provenance identifies `resources/lastfm` as Last.fm
user--artist playcount input and explicitly cites the Last.fm 360K dataset,
while its MusicBrainz dump inputs generate artist--genre and other graph edges.
It is a 3.1 GB generated/repackaged graph, not an independently measured
corpus. Its published defaults sample 5% with thresholds and its exported
graph has 2,226 users and 109,828 user--artist preference edges. Acquiring it
would duplicate Last.fm custody while importing MusicBrainz-derived genre
claims, so it is ineligible for independent evaluation and unnecessary for
co-listening research.

## Official source facts

- [ListenBrainz dump documentation](https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html)
  says full dumps are twice monthly and incremental dumps are twice weekly.
  Daily objects in local cache are an ingest schedule, not a documented dump
  publication cadence. Core listens are one JSON document per line. This makes them a
  high-volume raw-listen source, not a reason to bypass the existing privacy
  aggregate or download a full archive.
- [ListenBrainz playlist API documentation](https://listenbrainz.readthedocs.io/en/latest/users/api/playlist.html)
  specifies JSPF with MusicBrainz recording MBIDs for playlist tracks and
  distinguishes a user's ordinary playlist listing from `createdfor`,
  collaborator, and recommendation routes; it does not certify an ordinary
  public playlist as human-curated. In particular, the current ten-playlist
  sample remains `unknown`, not human-created.
- [MusicBrainz MLHD+ documentation](https://musicbrainz.org/doc/MLHD%2B)
  describes per-user listening histories with timestamps and artist, release,
  and recording MBIDs, using improved matching and canonicalization. Its
  archive scale does not fit the laptop-first workflow, so it is not a current
  acquisition or ingestion path.
- The [LFM-2b dataset page](https://www.cp.jku.at/datasets/LFM-2b/) says the
  dataset is no longer available for download because of license issues. It is
  not a current acquisition path.
- [UPF's Last.fm 360K source](https://www.upf.edu/web/mtg/lastfm360k) and its
  [creator-attributed Zenodo mirror](https://zenodo.org/records/6090214)
  document the exact artist-MBID field, hashed user field, scale, checksums,
  and non-commercial restriction.
- The creator-attributed [Last.fm 1K Zenodo record](https://zenodo.org/records/6090214)
  documents the timestamped row schema, 19,150,868 rows, 992 users, exact
  MusicBrainz artist and track IDs, the 672.7 MB archive, its MD5, and the
  noncommercial restriction.
- [AcousticBrainz Genre Dataset format](https://mtg.github.io/acousticbrainz-genre-dataset/data/)
  documents recording and release-group MBIDs, not artist MBIDs; the local
  bridge abstains unless the independent MusicBrainz credit relation is exact.
