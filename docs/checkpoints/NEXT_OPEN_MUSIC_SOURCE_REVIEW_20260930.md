# Next open music-source review, 2026-09-30

This is a bounded source-availability review for independent musical evidence.
It does not change the source pipeline, labels, or any classifier. No audio was
requested, downloaded, or stored, and no credentials were requested. Public
metadata responses were limited to endpoint documentation, a few small JSON
responses, or an explicitly capped response prefix.

## Finding

AcousticBrainz is the most practical next independent sonic signal. Its public
API returns recording-level low- and high-level features by exact MusicBrainz
recording MBID, and its official project page states that submitted data is
CC0. The endpoint is currently live. Its high-level classifier output can add
sonic axes to review, but machine-generated genre/mood estimates are not genre
truth and cannot establish artist membership or guarantee full parity with a
historical genre-name list.

ListenBrainz has a no-auth artist-radio route backed by a similarity graph, but
the route is designed to return a randomized radio selection. Its response
does not expose a stable ranked neighbor list or a distinct-listener support
count, so it is not ready to become a privacy-safe similarity feature. The
repository already has a better controlled path: privacy-filtered ListenBrainz
co-listen aggregates with an explicit support policy.

## AcousticBrainz: exact recording bridge and live availability

Official pages checked on 2026-09-30:

| Resource | Checked result | Relevance |
| --- | --- | --- |
| [Project page](https://acousticbrainz.org/) | HTTP 200; page states AcousticBrainz collected crowdsourced audio feature data from 2015 to 2022 and all data is CC0. | Open derived features; collection is frozen. |
| [Download page](https://acousticbrainz.org/download) | HTTP 200; documents 29,460,584 submissions in 30 Zstandard archives of one million submissions each, with low- and high-level JSON. | Full archive is not a sensible laptop pilot; use bounded MBID lookups. |
| [Low-level API](https://acousticbrainz.org/api/v1/856d081d-320b-4b6b-8dac-4427e308296d/low-level) | HTTP 200, declared 51,956 bytes; only the first 4,096 bytes were read. | Confirms exact-recording lookup works without an audio request. |
| [High-level API](https://acousticbrainz.org/api/v1/856d081d-320b-4b6b-8dac-4427e308296d/high-level) | HTTP 200, 9,398 bytes; complete small response inspected. | Returned classifier families including `genre_dortmund`, `genre_electronic`, `genre_rosamerica`, `genre_tzanetakis`, danceability, moods, timbre, and voice/instrumental. |

The recording UUID above was independently returned by the public
ListenBrainz top-recordings endpoint for Aphex Twin. MusicBrainz's exact
recording lookup confirms it is “Avril 14th” and credits Aphex Twin's exact
artist UUID `f22942a1-6f70-4f48-866e-238cb2308fbd`. This demonstrates a
workable chain of exact recording MBID → AcousticBrainz features → MusicBrainz
artist credit; it is one verified bridge, not a coverage estimate.

The high-level response assigned this recording to different outputs across
its genre models (including `ambient`, `jaz`, and `roc`, alongside
`electronic`). That disagreement is direct evidence to retain the model family
and raw values separately, preserve uncertainty, and never collapse these
outputs into a single factual genre label.

## ListenBrainz and Last.fm availability

The official ListenBrainz server source defines the unauthenticated route
[`/1/lb-radio/artist/<seed_artist_mbid>`](https://github.com/metabrainz/listenbrainz-server/blob/master/listenbrainz/webserver/views/api.py)
and its backing query in
[`lb_radio_artist.py`](https://github.com/metabrainz/listenbrainz-server/blob/master/listenbrainz/db/lb_radio_artist.py).
The query reads a top-100 similarity set, selects radio artists by mode, then
randomly chooses recordings using ListenBrainz popularity tables. A bounded
smoke check previously called this route without credentials for ten exact
electronic benchmark artist UUIDs; all ten returned HTTP 200 with small
responses. The resulting sample had 44 directed non-seed IDs and 18 hits
within the ten-artist cohort. This is route availability only: it is a
randomized radio sample, not neighbor recall or a semantic relevance result.
The response omits similarity scores and distinct-user counts, and the route
does not apply an explicit minimum-user floor. Do not persist or expose it as
a privacy-safe graph; use the already thresholded local aggregate instead.

Last.fm's official [`artist.getSimilar` documentation](https://www.last.fm/api/show/artist.getSimilar)
requires an API key. A no-key request returned HTTP 400 with a missing
required parameter response. The [Last.fm API terms](https://www.last.fm/api/tos)
say research/academic use should contact Last.fm before use and describe a
limited, terminable licence; this is not an open-license substitute. Do not
build a Last.fm similar-artist adapter without separately cleared access and
terms.

The repository already has a checksum-verified 360K Last.fm archive and a
local aggregate, but the source checkpoint documents a non-commercial license,
not open commercial reuse. Its strict exact-MBID aggregate is useful for
bounded exploratory comparison; existing custody policy keeps it out of model,
membership, and public use. It should not be recast as genre truth.

The MSD documentation describes metadata-only SQLite files for track metadata,
Last.fm tags, and directed track similarities. Official URLs are recorded in
[`MSD_LASTFM_OFFLINE_EVIDENCE.md`](../ingest/MSD_LASTFM_OFFLINE_EVIDENCE.md),
but the official docs do not publish file checksums or sizes. On this review
date the official MSD pages and file URLs returned HTTP 503 from this
environment, so current acquisition availability could not be verified. The
adapter's exact bridge depends on the metadata database supplying a valid
artist MBID; track tags and track similarity remain track-level support, not
artist genre membership. No files were fetched.

## Bounded next experiment

Use ten already-retained recording MBIDs with exact MusicBrainz artist credits
from the existing benchmark cohort. Query only AcousticBrainz high-level
metadata first, one recording per artist, and record endpoint status, declared
size, response SHA-256, model-family keys, and missing-data rate. Keep all
classifier families distinct and separate from MusicBrainz tags and native
genres. If this small audit shows useful, stable coverage, consider low-level
features only for the same ten recordings and only as numeric descriptive
review signals. Do not download the archives or audio; do not train or promote
from this probe. Evaluate any later extension against independently reviewed
artist/recording judgments, since the acoustic model labels themselves are
not an independent gold set.

The next evidence step is therefore a small exact-MBID AcousticBrainz coverage
and schema audit. Neither this source nor the ListenBrainz radio route alone
can establish 100% semantic genre parity.
