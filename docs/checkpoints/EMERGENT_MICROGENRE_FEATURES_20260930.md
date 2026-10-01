# Emergent microgenre feature cache

This checkpoint defines the metadata feature boundary for discovering artist
communities below broad seed-genre granularity. The extractor is an offline
candidate builder. It does not read historical assignments, labels, map
coordinates, or audio, and it does not create memberships or public data.

Each feature JSONL row has one artist MBID and a sorted feature list. A feature
uses one of `artist_genre`, `artist_tag`, `release_genre`, `release_tag`,
`area`, or `decade`, with a canonical NFC, whitespace-collapsed, case-folded
value, positive weight, and source evidence references. Display names remain
in a separate source-bound overlay. Release facts retain release namespaces;
they are not described as artist-record facts. Genre UUIDs are accepted only
when joined to the separately verified native MusicBrainz genre-label map.

Tag filtering writes every rejected observation with an explicit reason.
Generic favorites, owned/wanted, seen-live, technical-source, performer-role,
demographic, year-like, and exact artist-name tags are excluded. Duplicate
namespace/value observations collapse deterministically, weights use the
largest damped source count rather than summing duplicate votes, and evidence
references are unioned. The feature receipt binds source artifact hashes and
the exact output/rejection bytes.

The builder is `scripts/build_microgenre_features.py`; its pure normalization
and aggregation API is in `src/opennoise/ml/microgenre_features.py`. The
parity model consumes the JSONL contract, groups equal musical value profiles,
and requires at least two distinct musical values for sub/microgenre
communities. Facets that share a value remain distinct evidence origins, while
area and decade are context features.

The retained direct proper-genre source, rich artist search metadata, and
verified label dictionary are acquisition inputs, not discoveries. MusicBrainz
artist tags and supplemental search responses are CC BY-NC-SA 3.0, so derived
artifacts stay in local research use under that source license. The base
release-credit catalog is CC0 and supplies artist/release identity context;
it contains no release genre or tag facts by itself. Any later release genre
or tag rows must retain their own typed source evidence.

The verified combined candidate is `.cache/microgenre-features-rich-v4/`.
Its feature JSONL SHA-256 is
`99397762f18f661192914ed2c60f086e1a4d5c0934608e9ca8c5a7dbb26644c2`; its
receipt binds the feature, name, missing-name, rejection, and source bytes.
The cache contains 198,464 artist identities and 555,331 features: 387,435
artist proper-genre features, 116,873 artist tags, 31,234 areas, 18,352
decades, 696 release-group genres, and 944 release-group tags. The separate
name overlay contains 198,390 names; its 74 missing IDs are explicit. The
rejection stream contains 12,522 observations: 4,454 pure place or nationality
tags, 4,431 nonpositive counts, 2,987 nonmusical or technical tags, 578 exact
artist-name tags, 56 values without letters, and 16 too-short values.

The release context comes from 959 MusicBrainz release groups across ten
sentinel artists. It retains exact credited MBIDs and one release-group
evidence group across genres, tags, credits, and release date. Those facts stay
under `release_genre` and `release_tag`; credit context does not become an
artist-record genre observation. Bare decade tags are normalized into the
`decade` context facet; specific compounds such as “UK garage” remain tags.

The prespecified holdout review uses the frozen v2 feature input. The v4 cache
contains the later pure-place/decade cleanup and release-group context and has
not been evaluated by that holdout. It is an offline research candidate; the
MusicBrainz tag and genre associations remain CC BY-NC-SA 3.0 and are not
authorized for public export.
