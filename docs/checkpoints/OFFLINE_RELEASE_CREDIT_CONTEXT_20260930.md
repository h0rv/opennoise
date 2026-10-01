# Offline release and track credit context

The local source explorer can now expose retained release and track metadata
beside its exact artist identities. An offline projection verifies the portable
MusicBrainz credit source and catalog receipt, joins native release/recording
credits to the direct artist UUID cohort, and writes static metadata files.

The retained slice contains 87 releases, 87 release groups, 1,031 recordings, and
1,032 tracks. Exact joins give release context to **280 direct artists** and
credit context to **225 direct genre seeds**. All 87 releases have at least one
credited artist in the direct cohort. The static output contains 307
artist–release context rows: 89 have release-level credits, while all 307 have
recording-level credits. Recording-only contributions are explicitly identified.

The slice covers 0.1411% of the 198,409 direct artists. The remaining 198,129
artists and 472 seeds have no retained release context; absence means
`unavailable_in_retained_source_slice`, not that the artist has no releases.
This adds actual metadata browsing but does not establish complete discographies,
genre album membership, release relevance, or Every Noise parity.

## Source boundaries

`PortableMusicBrainzCreditReleaseReceipt` binds the portable source object,
hydration artifact, credit artifact, catalog, and catalog report. The new helper
inspects the source bytes, restores and verifies the catalog through
`restore_portable_musicbrainz_credit_catalog`, and reparses the typed portable
source. Every source projection, credit relation, and hydration artifact remains
hash-bound to the tracked receipt. No ignored live MusicBrainz cache or network
request is used.

Hydration metadata supplies native release/track titles, release-group UUIDs and
titles, concrete release dates, media order, track UUIDs, recording UUIDs, and
durations. Credit projections supply ordered native release and recording
credits. These source layers have separate provenance fields. Independent
recording titles were not retained and remain `null`; track titles are not
silently reused as recording titles. The year denotes the concrete release's
date, not the album's original publication date.

The direct catalog is verified before its artist observations are read. Release
credits and recording credits join only through exact artist UUIDs. Credited
artist names do not overwrite catalog names, homonyms do not merge, and native
credits outside the direct cohort remain credit labels rather than gaining
memberships in the model.

Genre payloads use the heading **“Releases credited to source artists”**. Every
example identifies the exact credited source artists and their separate direct
artist–seed observations with source record hashes and evidence references.
Examples follow release UUID order and are limited to twelve per seed, with a
remaining count. This order is not a relevance ranking. The credit artifact
contains no native album genres, so all payloads declare
`native_release_genres_available=false`, `album_supported_seed_evidence=[]`,
`release_genre_membership_inferred_from_artist=false`, and
`membership_claims_added=0`.

The CC0 core-metadata projection contains no audio, previews, artwork, embedded
players, remote album covers, native genres, or tags. It adds no source-model
training observations or geometric evidence and authorizes no public export.

## Artifact and API

The completed output is `.cache/musicbrainz-release-credit-context/`. It has 280
files under `artist-releases/<artist UUID>.json` and 225 files under
`genre-release-examples/<seed ID>.json`, totaling 17,886,651 bytes. The bounded
genre files contain 755 example rows. Across artist files, all 1,031 recordings
and 1,032 tracks in the retained slice remain accessible as metadata.

`release-context-receipt.json` contains source bindings, counts, `artist_paths`
and `genre_paths` registries, and all output byte hashes. It is 117,568 bytes.

- Logical receipt hash:
  `b0999a721a1ff44e54492c8a044ec28d9cf6a3a34ce21983d889ff20fbffdd16`
- Receipt byte hash:
  `76f6fca3bf3ca03c40ff187727392de3024990d1179ccf5e218817c30143be79`
- Portable source hash:
  `13921b94a5a0c77c625713b5e272d40d081c67de3eb5b1299c8c1c48baf6d6ba`
- Portable credit catalog hash:
  `100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63`

`write_artist_release_contexts(direct_catalog_directory=..., output_directory=...)`
in `opennoise.catalog.musicbrainz_release_context` returns this receipt and writes
the static files. It confines destinations to project `.cache` and refuses to
replace existing artifacts. Builders can use the returned path registries to
load only available contexts and avoid fetching an absent file for every artist.
`verify_artist_release_contexts` recomputes the source projection and requires
all metadata files and the complete receipt to replay exactly.

From a synchronized checkout, use a new output destination:

```sh
.venv/bin/python scripts/build_local_musicbrainz_release_context.py \
  --direct-catalog-directory .cache/musicbrainz-candidate-catalog-final \
  --output-directory .cache/musicbrainz-release-credit-context
```

The separate offline replay passed with the identical logical receipt hash:

```sh
.venv/bin/python scripts/build_local_musicbrainz_release_context.py \
  --direct-catalog-directory .cache/musicbrainz-candidate-catalog-final \
  --output-directory .cache/musicbrainz-release-credit-context --verify-only
```

Ruff formatting/lint, type checks, and six focused tests pass. Tests exercise
the real tracked portable metadata with a sealed exact-ID fixture, distinguish
recording-only credits, preserve direct source roles and original catalog bytes,
check the twelve-example bound, retain explicit missing context, reject altered
catalog source bytes before writing, independently reject rehashed metadata or
policy changes, and enforce destination, replacement, and seed-path boundaries.
