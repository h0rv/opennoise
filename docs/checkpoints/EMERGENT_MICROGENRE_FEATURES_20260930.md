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

## MusicBrainz aggregate artist-tag dump

The new aggregate-tag projection is `.cache/musicbrainz-bulk-artist-tags-20260930-v2/`.
Its independently replayed receipt has output SHA-256
`a3cf2e7c43afff18a5942b79c507e83a171e6662242d1271a0c6d371d25a989e`; the JSONL
SHA-256 is `98fd42b141d021a6fc0eba69451e3aaaeca787ec4c93997d3a317ebdfc6d8305`.
The artifact has exactly 198,409 primary-catalog UUID rows: 198,381 present in
the current core artist dump and 28 explicit absent rows with null names and
empty genre/tag lists. It preserves 616,440 positive aggregate associations;
21,477 zero and 3,873 negative counts remain raw-only and never become model
observations. The input excludes `artist_tag_raw`; it has no release genres and
does not infer genres from credits. The source applies CC-BY-NC-SA 3.0 attribution,
NonCommercial and ShareAlike terms, permits local noncommercial research-model
input, and prohibits public export.

The extractor keeps aggregate observations in `artist_tag`, applies NFC,
whitespace and casefold normalization, rejects nonpositive source counts, and
caps duplicate namespace/value weights while merging evidence references.
Each dump-backed value carries the archive digest, core artist-row reference,
and exact aggregate association-row digest, row number and tag ID. Required
indexed input bindings are `bulk_artist_tags_0`, `_receipt`, `_core_prefix`,
`_derived_archive`, and `_selection`; the captured license and snapshot index
are bound as optional `_license` and `_source_index` inputs. The receipt also
binds the feature extractor and builder source files. Dump core names are kept
in the separate display-name overlay and only fill previously missing UUIDs;
they do not enter the model feature vocabulary or alter existing tag-name
filtering.

The first bulk projection `.cache/microgenre-features-primary-v3/` is preserved
as a pre-audit snapshot. A focused source-quality review then added exact
rejections for the occupation `conductor` and language label `english`. The
policy-matched old-source baseline is
`.cache/microgenre-features-primary-v2-policy-v2/`, SHA-256
`70f8dd0de2853b2d927eeaa8a92fbcc4a3f7c968c0d54476d473e8a347abc4b2` (receipt
file SHA-256 `5d277b3fea9994413410bbc9d5f4f7b4a21a4e7b3f39959ad096cebf819d6544`).
Relative to frozen primary-v2, this same-source policy view removes 356
artist/value pairs: `english` (207), `conductor` (144), `english composer` (3),
and `english violinist` (2), all with explicit rejection reasons.

The paired bulk-augmented primary input is
`.cache/microgenre-features-primary-v4/`, feature SHA-256
`2b6179b4c969588f1268c9837b410c9da7b16d54c094850eb13ba00514b6f252`, receipt
file SHA-256 `281a0cdcf87498bad50f6e2fe9b145cf0e010c1ed7c3b48a832ae0b8a094f6d7`.
It retains exactly the same 198,409 UUIDs as the baseline. It has 1,010,929
features, 115,535 explicit rejections, 198,391 names and 18 missing names.
Namespace counts are 387,435 artist genres, 549,412 artist tags, 44,389 areas,
28,311 decades, 605 release genres and 777 release tags. The canonical
artist/value musical feature set grows from 434,762 to 550,213 pairs, with
115,451 additions and no removals relative to the same-policy baseline. Every
added pair carries the verified aggregate association-row reference. There
are 31,917 distinct canonical musical values, of which 7,990 occur for at
least two artists and 2,247 occur for at least ten artists. Maximum row degree
is 255 features and maximum distinct musical-value degree is 228.
Under the frozen model's own canonicalization, this becomes 434,527 to 549,416
artist/value pairs (+114,889), 31,864 distinct values and zero removed pairs
or weight changes.
Of the 549,346 aggregate-backed `artist_tag` namespace/value rows, 154,928
merge same-artist tag facts from the earlier artist API with max weight and
unioned evidence refs. Another 278,967 duplicate musical values already occur
for that artist in a different facet and collapse once at the model boundary;
the other 115,451 are new artist/value pairs.
Source facets remain separately typed in the feature file, so community
vectors may still count their cross-facet evidence; paired model results
measure the complete source augmentation, not only novel values.
The high-support tags `satanism` (469 artists) and `soft visual` (468 artists)
remain source-observed `artist_tag` values only; neither is asserted as a
native genre. `satanism` remains in the semantic review queue as a thematic
annotation.
The explicit rejection summary is 36,705 artist-name references, 32,296
place/nationality values, 26,125 nonpositive counts, 17,820 nonmusical or
technical tags, 1,560 exact self-name tags, 767 private/technical markers,
211 values without letters and 51 short values.

The broader diagnostic snapshot `.cache/microgenre-features-rich-v7/` retains
198,464 identities and the initial tag policy; it is preserved but is not the
current primary-corpus fit input. Research artifacts are local-only and are
not authorized for static export or deployment.
