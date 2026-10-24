# Wikipedia artist atlas

This release adds a genre atlas and artist discovery from public Wikipedia
metadata. It keeps the existing listening explorer as Connections. It needs
no recordings, lyrics, account, user histories, server or paid service.

The source contains 86,253 named artist records. Of those, 78,983 have admitted
source genre claims, 55,440 have artist relationships, and 24,541 receive
shared-context suggestions. There are 1,876 source genre labels, grouped into
1,366 browsing names using exact controlled genre names or case aliases.
Artist identities are never merged by name. Counts from the two catalogs
must not be added as if they were distinct people.

The atlas provides complete genre member lists, a paginated artist directory,
search across both catalogs, genre and artist maps, keyboard navigation,
history, deep links, mobile lists and readable maps. Maps select up to 60
artists and link to the complete list. All genre names remain reachable.
Source associations and band memberships appear as Related artists. Suggested
artists are model output. Neither section claims a listener judgment.

## Source and rights

The inputs are DBpedia's official English Wikipedia 2022.12.01 mappings,
direct types, transitive types and English labels. Each download matches its
publisher manifest SHA256. The pinned source files and their manifests are
listed in [the input contract](../../config/releases/wiki-artist-atlas-inputs-v1.json).
Those per-file manifests specify CC BY 3.0. The filtered and reformatted
projection is offered under CC BY-SA 3.0, also preserving DBpedia's broader
attribution/share-alike guidance. Sources contains provider credit, the
DBpedia logo, license links, changes, snapshot date and entity backlinks.
See [DBpedia's data guidance](https://www.dbpedia.org/resources/) and the
retained per-file manifests rather than assuming every DBpedia artifact has
identical terms.

MusicBrainz contributes only 2,216 core genre-definition names under CC0.
Artist genre associations are supplementary data with different terms and
were not requested or used. See the [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API),
[core schema](https://musicbrainz.org/doc/MusicBrainz_Database/Schema) and
[data license](https://musicbrainz.org/doc/About/Data_License). The separate
ListenBrainz/MusicBrainz Connections data keeps its existing CC0 contract.

No restricted historical research, private data, model weights or experimental
source candidate is served. The original 701 JSON files and the existing 258
Connections JSON files retain their exact promotion hashes.

## Source admission

Artist records require a positive MusicalArtist or Band type, or Person plus
a source instrument statement. Relationship roles and genre claims alone
cannot establish an artist. Explicit incompatible concept types are excluded.
A genre needs a positive Genre/MusicGenre type or an exact normalized core
vocabulary name, with optional terminal `music` or `(music)` removal. Known
incompatible types are excluded unless a positive genre type exists.
Unknown labels are quarantined, not promoted as a taxonomy.

An independent audit checked every retained identity proof, all retained native
statements and 100,546 retained/quarantined English names against publisher
sources. It checked the complete quarantine of 2,892 labels and 20,048 claims.
Earlier candidates admitted concepts as artists and writers through generic
genre statements. Those candidates were blocked. Their metrics are not quality
evidence for this release. Ontology-wide rules and controlled vocabulary
validation fixed the demonstrated source failures without name blacklists.
The accepted source before navigation coordinates has SHA256
`814883b9222603e81f8bdcde504228ada847abc55795efff23a9b0bb1f7c63c9`.

## Model decision and evaluation

Use exact normalized binary artist-neighbor profiles. Dense metadata embeddings
were worse on the tested task and are not needed for serving. Known source
relationships and self are excluded from suggestions. A suggestion requires
positive cosine and at least three source neighbors; at most ten are shown.

The benchmark freezes a reciprocal pair holdout: hash the ordered native URI
pair and remove fold zero in both directions before fitting context or degree.
The source has 96,717 undirected pairs, with 19,266 withheld. Metadata fits are
transductive as declared: the complete source metadata catalog is known, while
target relationship edges are withheld. Ranking uses rounded scores and native
URI tie order. There was no model search after the protocol was frozen.

| Method | Recall at 10 | Recall at 50 |
| --- | ---: | ---: |
| Shared-neighbor context | 19.3942% | 35.3283% |
| Metadata/context mean | 14.1193% | 23.3056% |
| Exact metadata cosine | 5.8388% | 11.6115% |
| 64-dimensional metadata SVD | 2.0966% | 5.1827% |
| Training-degree popularity | 0.4392% | 1.4378% |
| Uniform expectation | 0.01167% | 0.05837% |

This comparison has 2,125 eligible queries and 81,977 metadata-bearing gallery
artists. The recall denominator retains 388 withheld positive instances that
lack metadata, giving 95.6716% positive gallery coverage. Independent replay
reconstructed the exact training graph and all query metrics without importing
the producer. Maximum per-query metric difference was 1.08e-19.

The selected context method was then checked on the actual 86,253-artist
serving gallery, including artists without metadata. This separate check has
2,162 queries and 100% positive coverage. Recall at ten is 19.1924%, versus
0.4433% for degree popularity and 0.01160% uniform expectation. Recall at fifty
is 35.7817%. Independent integer common-neighbor replay reproduced all 2,162
query metrics with zero error. All 9,090 withheld positive instances are
covered, including 37 eligible queries without metadata. Its separate ledger
accounts for all 84,091 ineligible identities. This does not imply every
artist has enough evidence for the same
quality: only 12,600 artists have at least five complete-graph connections.

The producer omitted exhaustive exclusion and stratified coverage reporting.
The independent supplement supplies all 84,128 excluded identities, overlapping
causes, degree strata and overlapping source-genre coverage. It is retained in
[this evidence directory](wiki-artist-atlas-v1/), alongside frozen protocols,
query results, scripts as audit snapshots and the independent review. The
scripts document the local research run; they are not production acquisition
jobs and do not run during the static build.

These scores measure withheld source-association recovery. They do not measure
listener preference, acoustic similarity or perceptual taxonomy quality. Genre
agreement would be circular for a model that uses those genres. English
Wikipedia coverage and a 2022 snapshot leave real gaps, including incomplete
classical and Indian music statements. Navigation coordinates summarize shared
memberships and have no claimed musical axes. Complete lists remain the
coverage reference.

## Release gates

The closed public source replay is required under two Python hash seeds with
network calls disabled. Promotion separately pins the original catalog,
Connections and the new atlas data. Source identity regressions fail before
matrix construction. The release gate checks legacy journeys, Connections,
the new HTTP atlas and the complete offline atlas in Chromium. It covers all
genre targets, actual label overlaps and clipping, directory and member-list
pagination, search, keyboard, Back/Forward, reload, 320/390-width layouts,
44-pixel map targets, touch, zoom and no external/media requests.

The complete atlas offline HTML uses lossless identifier interning and gzip.
It preserves all artist and genre pages and is below Pages' 25 MiB file limit.
The complete static payload remains bounded, with no database or runtime API.
The public site makes no Every Noise parity claim. Independent listener
judgments and current broader catalog coverage remain separate work.
