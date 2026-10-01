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

The initial verified release-context candidate was `.cache/microgenre-features-rich-v4/`.
Its feature JSONL SHA-256 was
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

The expanded research cache is `.cache/microgenre-features-rich-v5/` with
feature SHA-256
`f822fbc4395075d08ed62c9863c46bb449b517a5bd78fcaf5680843c112bbfd3`. It
adds two verified native artist metadata inputs: a 38,985-artist search-source
cohort and a disjoint 14,997-artist source expansion, plus exact native artist
genre/tag lookups for 55 release-credit identities. It contains 198,464
identities, 622,969 features, 17,420 rejected observations, 198,445 names, and
19 explicit missing-name IDs. Namespace counts are 387,452 artist genres,
162,115 artist tags, 44,431 areas, 27,331 decades, 944 release tags, and 696
release genres.

The static product variant is `.cache/microgenre-features-primary-v1/` with
feature SHA-256
`cca2fb2595b7e38f0c19f14c44acbcf51767f7134c998a540d0efff2d0a7d526`. It
uses the verified candidate catalog MBID set as its explicit identity filter
and contains 198,409 identities, 622,617 features, 17,414 rejections, 198,390
names, and 19 missing-name IDs. This filtered variant is for the current
primary product corpus; the expanded v5 input remains available for research
evaluation and the additional 55 identities are retained there.

The prespecified holdout review uses the frozen v2 feature input; v2 and v4
were preserved throughout subsequent builds. v5 and the primary-only variant
are separate offline research candidates. MusicBrainz tag and genre
associations remain CC BY-NC-SA 3.0 and are not authorized for public export.

## Metadata-noise audit refresh

A later tag audit found private/edit markers, fire-event bookkeeping,
performer/occupation labels, platform tags, personal traits, and other artists'
names in the raw tag stream. The extractor now rejects these with explicit
reasons. Exact artist-name tag references are filtered unless the normalized
value is a verified native genre name; common musical compounds such as
“singer-songwriter,” “vocal jazz,” “UK garage,” and “Brazilian rock” remain.
Bare decade tags map to `decade`; pure place and nationality values go to the
rejection stream while the artist's verified `area` remains context.

The refreshed full cache is `.cache/microgenre-features-rich-v6/` with feature
SHA-256 `580a793d7918e115e8393651cc28f0fb78e23a09ce384d8b0fbfbdaac680b5c4`.
It has 198,464 identities, 616,162 features, 24,307 explicit rejections,
198,445 names, and 19 missing-name IDs. Feature counts are 387,452 artist
genres, 155,374 artist tags, 44,431 areas, 27,331 decades, 878 release tags,
and 696 release genres. Rejections include 6,777 artist-name references,
6,402 place/nationality tags, 6,097 nonpositive counts, 4,000 other
nonmusical/technical tags, 780 exact self-name tags, 181 private/technical
markers, 56 values without letters, and 14 short values.

The matching product corpus is `.cache/microgenre-features-primary-v2/` with
feature SHA-256 `0c298b1241b03e642dbc7b13981f59b9008cb1fdc4e01186b5fe55e7f2c78748`.
It has 198,409 identities, 615,812 features, 24,299 rejections, 198,390
names, and 19 missing-name IDs. It applies the verified candidate catalog's
artist UUID set after full source replay, leaving all supplemental identities
available in the expanded v6 research cache.
