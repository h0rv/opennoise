# ListenBrainz public playlist probe

This is a bounded local-only research adapter. It does not affect the model,
static map, discovery asset, deployment, or source policy of the release.

## What it preserves

- A receipt for every response: endpoint URL, retrieval time, byte size, and
  SHA-256 of the exact local JSPF response.
- The bounded raw JSPF response itself at `raw/sha256/<payload SHA-256>` beside
  a bundle. The writer refuses to create a bundle when that immutable object
  is absent or differs from its receipt.
- Exact ListenBrainz playlist and MusicBrainz recording UUIDs.
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

## Tiny observed public sample

On 2026-09-23 UTC, one real public playlist was fetched through the official
endpoint and retained only under
`.cache/listenbrainz-public-playlist-probe-20260922/`. The explicit playlist
UUID was `8abf5d92-f4c2-41d1-9378-6380b5703616`, selected from a public
MetaBrainz community JSPF/API example, not from a genre-title search. Its raw
JSPF object has SHA-256
`ba605d0161c1a697353a213cc1bd91655faa53862de6d64146b95d5c18b74c3d`; the
receipt-bound bundle has file SHA-256
`e0e261680d2f6ce744a7c96f938a00a5db78da45f9dc8709e2f297d7030360ad`.

The snapshot has 54 source-order, unique exact MusicBrainz recording UUIDs,
with zero unsupported identifiers and zero duplicate recordings. Against the
local `data/public.sqlite` catalog snapshot
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`, its 623
exact catalog recording UUIDs overlap the playlist at zero recordings (0.0%).
This is a coverage finding, not a quality, genre, or negative-identity claim.

The public response contains a creator string, but curator status remains
`unknown`; it was not manually reviewed. The explicit example selection also
means this sample is API-format and custody validation only. It cannot measure
playlist genre purity, support a genre label, establish curation quality, or
evaluate a playlist model. A later source-family/curator-reviewed sample must
be held apart from title-search discovery and evaluated against independent
direct labels.

## Bounded multi-playlist observation

One documented alternate public discovery route was used on 2026-09-23 UTC:
`GET /1/user/Isabelxxx/playlists?count=20`. Its retained local metadata response
has SHA-256 `564cacb56623cd13b6760abcf18b9ac5c645e6e863bfc2ab9cea0891656bcfd2`.
It declared 62 public playlists and exposed 20 metadata entries. The first ten
explicit UUIDs were fetched through the exact-playlist client into
`.cache/listenbrainz-public-playlist-probe-20260923/`; each full JSPF response
is content-addressed under that directory's `raw/sha256/`, and the resulting
bundle is bound logically by SHA-256
`9f20d19358786c0352268412b1e08267e27c99454ce83be37b7e9ea61bca7855`.

The ten snapshots contain 557 source tracks, 527 unique exact recording UUIDs,
zero unsupported identifiers, and one duplicate recording dropped within a
playlist. They have one distinct creator string. The listing's visible
`created_for` fields were absent, so none can be classified as
`known_automated`; a creator string and absent `created_for` do not establish
human curation. All ten remain `unknown`.

Their exact within-playlist co-occurrence projection has 21,184 distinct
unordered recording pairs. Only 27 pairs occur in two playlists and no pair
occurs in more than two, after per-playlist duplicate removal. Against the
current 623-recording local catalog snapshot
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`, 11 of
527 recordings overlap (2.0873%). The exact catalog ID-set SHA-256 is
`78be4f69291d48dea471467df7d6545fc32b50c8e6ad102a0ab9afd681b35a7e`.

This is a single discovery cohort, not a random or curator-reviewed sample.
Its title metadata was not used as a genre target, no user-versus-algorithmic
claim is made, and these pair counts do not enter modeling, the public map, or
any release artifact.
