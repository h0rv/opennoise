# ListenBrainz public playlist probe

This is a bounded local-only research adapter. It does not affect the model,
static map, discovery asset, deployment, or source policy of the release.

## What it preserves

- A receipt for every response: endpoint URL, retrieval time, byte size, and
  SHA-256 of the exact local JSPF response.
- The bounded raw JSPF response itself at `raw/sha256/<payload SHA-256>` beside
  a bundle. The writer refuses to create a bundle when that immutable object
  is absent or differs from its receipt.
- Exact MusicBrainz playlist and recording UUIDs.
- Source playlist order, after removing repeated recording IDs.
- Curator classification as `reviewed_human`, `known_automated`, or `unknown`.
  The parser always defaults to `unknown`; a creator name is not evidence that
  a playlist is human curated.

It retains no audio files, playback links, user listening histories, genre
claims, ranking output, or serving/API artifact.

## Bounded evidence shape

The probe accepts at most 50 playlists and at most 200 distinct exact
recording IDs per playlist. A playlist with fewer than two exact MusicBrainz
recording IDs abstains. Unsupported track identifiers are counted, not joined
by title or artist name.

Each retained playlist contributes exactly one total pair-weight vote. Its
unordered recording pairs receive `1 / choose(unique recordings, 2)`, so a
500-track playlist cannot outweigh many small curated lists solely because it
is long. Duplicate recording IDs cannot inflate support.

The aggregate evaluator never expands those pairs into `PlaylistRecordingPair`
objects. It counts `choose(recordings, 2)` per already bounded playlist and
uses one total weight per playlist. It rechecks the recording cap for every
caller-supplied snapshot, so a constructed model cannot bypass the parser
limit. Batch fetch passes the same selected probe settings into every parse.

Catalog readiness is an exact recording-UUID intersection only. Fuzzy title,
artist, or release joins are intentionally absent.

An aggregate artifact accepts a receipt-bound snapshot bundle, then records a
logical SHA-256 of its canonical model content, the ordered response payload
SHA-256 values, and a SHA-256 plus count for the exact catalog recording-ID
set. The logical hash is not a hash of the pretty-printed bundle file bytes.
It is therefore not reusable as a claim about another playlist source or
another catalog join.

## Evaluation boundary

Playlist titles and descriptions are useful for finding candidates, but title
search is not independent genre evidence. The aggregate probe always records
`independent_genre_evaluation_eligible=false`; a later evaluation must use
held-out source families and direct labels, without title-derived targets.

## Next controlled experiment

Snapshot 20–50 manually reviewed public playlists from distinct curator/source
families, retain receipts, and run the exact recording-ID join against the
local MusicBrainz hydration catalog. Report join coverage, curator uncertainty,
playlist-size distribution, and normalized pair support separately from the
existing aggregate ListenBrainz co-listen experiment. Do not merge their edges
until an independent held-out evaluation shows incremental value.

`scripts/probe_listenbrainz_playlists.py` accepts repeated explicit
`--playlist-mbid` values and a new `--output` file. It fetches only the
official playlist endpoint, writes raw objects under the output's
`raw/sha256/` directory, then writes the receipt-bound bundle. It has no Poe
task and is never part of a release build.
