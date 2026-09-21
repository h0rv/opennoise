# MusicBrainz credit metadata for visible artists

This checkpoint proposes a narrow publication path for MusicBrainz release and
recording credit metadata. It applies only to the 101 artists that are already
visible in the current static discovery asset and that match the local
artist-credit candidate by the same canonical MusicBrainz artist ID.

The result would add an optional metadata section to an existing artist detail
card. It would show a release or recording title and the exact ordered credited
artist names from MusicBrainz. It would label the values as MusicBrainz credit
metadata. It would not add a genre, an artist membership, a map edge, a release
selection, a representative album, a score, or a rank.

## Existing inputs

The local candidate is
`.cache/musicbrainz-catalog-expansion-v1/artist-credit-materialized-v2-final.sqlite`.
Its SHA-256 is
`100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63`.
Its report binds the candidate to the core hydration artifact, the credit
artifact, and 87 verified source cache projections.

The current static discovery asset is
`dist/assets/static-discovery.b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8.json`.
It is bound to public SQLite SHA-256
`240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc`.
The exact-ID overlap checkpoint records 101 visible artists in the intersection.

## Smallest implementation

First, add a new versioned payload next to `static-discovery`, rather than
changing its direct-claim membership schema. Its rows should contain the static
artist ID, the canonical MusicBrainz artist ID, a release or recording ID,
title, entity kind, and the ordered MusicBrainz credit members. A row must also
carry the candidate database SHA-256 and the source credit provenance ID.

Second, build rows only from `entity_artist_credits`, `artist_credit_members`,
and the local candidate's two provenance records. Join the candidate artist ID
to static discovery only by canonical MusicBrainz artist ID. Do not use artist
names, aliases, labels, or a genre relation as a fallback.

Third, update the static page builder and its browser code to load this optional
asset only from an artist detail card. The card must say "MusicBrainz credit
metadata" and link only to the already visible artist. It must not show the
metadata in a genre card or map overview. The relevant code paths are
`src/opennoise/deployment/static_discovery.py`,
`src/opennoise/deployment/semantic_pages.py`, and the static browser code
embedded by `semantic_pages.py`.

## Required publication gate

No public export should be built until a separate, versioned publication gate
approves this exact candidate database and its source provenance. The gate must
verify all of the following.

- The candidate database SHA-256 matches its materialization report, and that
  report binds the core hydration and artist-credit artifacts.
- The static discovery asset is ready, declares direct source claims, and is
  bound to the current public database hash.
- Every payload row joins one visible static artist to one candidate artist by
  the same canonical MusicBrainz ID.
- The MusicBrainz credit provenance has explicit display and export permission
  for this new metadata use. The current local candidate status is not itself a
  public publication decision.
- The output has no genre ID, catalog genre name, membership evidence, map
  coordinate, score, rank, or representative field.

The gate should write a receipt that names the candidate database, candidate
report, public database, static discovery asset, policy decision, output hash,
and row counts. A failed gate must publish no asset.

## Focused tests

- Reject a candidate report or candidate database hash mismatch.
- Reject a static discovery asset that is unavailable, has a different public
  database hash, or lacks direct-source scope.
- Export a fixture row only when the static and candidate artist IDs are the
  same canonical MusicBrainz ID. Reject a name-only match.
- Reject a row without the approved credit provenance or with a missing ordered
  credit member.
- Assert that the generated schema has no genre, membership, score, rank, or
  representative fields, and that the browser renders it only in an artist
  detail card.
