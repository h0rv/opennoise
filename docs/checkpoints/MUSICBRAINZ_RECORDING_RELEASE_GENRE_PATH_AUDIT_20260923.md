# MusicBrainz recording and release genre-path audit

## Decision

The retained catalog has an exact, usable identity path from a recording to
its release, release group, and ordered credited artists. It has no retained
recording- or release-level genre observation in that hydrated catalog.
Therefore the next safe design is to admit source-qualified genre facts at
their native entity level and derive only explicitly labeled support across
entities. It must not turn a song, album, EP, or credited appearance into an
artist factual genre membership.

## Retained exact path

The local-only `artist-credit-materialized-v2-final.sqlite` cohort contains
1,031 exact MusicBrainz recording IDs, 1,032 tracks, 87 releases, 87 release
groups, and 1,118 ordered artist-credit memberships. Its relational path is:

```text
recording MBID ── track ── medium ── release ── release-group MBID
      │                              │
      └──────── ordered recording credit ────── credited artist MBID
```

1,031 recordings have a hydrated track/release/release-group path; 1,030
currently resolve to one distinct retained release group and one resolves to
multiple groups. The latter must remain a multi-group observation rather than
be assigned to an arbitrary album. The separately measured conservative
single-primary-artist ceiling is 886 recordings, but one primary credit is an
identity simplification, not proof that a recording genre belongs to that
artist.

The catalog tables for `recording_genre_membership_observations`,
`album_genre_membership_observations`, and their ranking evidence are present
but contain zero rows in this materialized cohort. This is an absence of a
retained source observation, not evidence that a recording or release has no
genre.

## What MusicBrainz can state, and what is retained

The existing source adapter can parse MusicBrainz API/dump `genres` fields for
recordings, release groups, and concrete releases. A `genres` field is an
entity-level MusicBrainz proper-genre association; a broader tag is a distinct
tag facet and must retain its positive aggregate count. The current
release-group research builder has already materialized 1,546,265
release-group-to-credited-artist **support** pairs from release-group genres
and positive-count tags, capped per artist/seed/facet. It deliberately labels
them `release_group_support`; none is an artist-direct fact.

The portable proper-genre custody object is different: it contains 387,435
literal **artist** proper-genre observations. It can support a factual
artist--genre claim only under its separate custody/policy gate. It cannot be
used to backfill a recording or release genre, and release evidence cannot be
used to inflate it.

The bounded 24-recording API coverage pilot established recording/release
connectivity but deliberately did not request or retain genres. It found 58
distinct release groups, including Album, EP, Single, and compilation-marked
links; these identity/type results are not genre rows.

## Next inference design

1. Ingest one checksum-pinned MusicBrainz source partition under a separate
   noncommercial supplementary-data policy. Read exact MBIDs and preserve the
   source object and row hash. Do not use a live lookup as an unpinned
   replacement.
2. Store `recording MBID × genre MBID` from a recording `genres` field as a
   direct **recording** fact only. Store its count, snapshot, policy, and
   source record. A tag is a separate `recording_tag` support facet; do not
   silently call it a genre.
3. Store `release-group MBID × genre MBID` as a direct **album-concept** fact.
   Store `release MBID × genre MBID` as an edition fact linked to its exact
   release group. Album, EP, Single, and Compilation remain type/display
   fields, never aliases for one another. A direct release edition fact does
   not automatically label every other edition.
4. Derive `recording → release-group` coverage only after exact track/release
   enumeration: retain numerator, denominator, excluded recordings, and the
   source facet. A declared threshold may create a `track_coverage` **support**
   observation for the release group; it cannot replace a direct release-group
   genre fact. Multi-group recordings contribute separately to every exact
   group and are never arbitrarily collapsed.
5. Derive `release-group/recording → credited artist` only as support context:
   retain the exact credit, position, join phrase/role where available, and
   whether the observation is a collaboration or compilation. Never promote it
   to artist membership. An artist fact requires its own direct artist source
   row (for example, the separate proper-genre custody object or direct
   Wikidata P136).
6. Freeze source partition, label mapping, and downstream predictions before
   a held-out diagnostic. Keep MusicBrainz tags/genres out of any evaluation
   that uses AcousticBrainz/Discogs labels because the latter were imported
   into MusicBrainz tags.

This design separates factual claims (`recording`, `release`,
`release_group`, `artist`) from support-only relationships and preserves the
source level needed to explain a song, album, EP, or featured-artist result.
