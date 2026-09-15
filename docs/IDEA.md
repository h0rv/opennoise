# OpenNoise

Build OpenNoise, an open music map from public metadata and privacy safe aggregates.

OpenNoise is the product name; the internal Python package and compatibility
identifiers remain `opennoise` during the staged migration.

The immediate product goal is coherent open music discovery: a user should be
able to traverse a catalog genre to artists, an artist to its directly observed
genres, and then to artists sharing those direct genres. These navigation links
are source-claimed membership only; `shared_direct_genre` is an explained
overlap method, not a learned similarity or an inferred membership. The local
public catalog currently has direct artist claims for, for example, post-punk
(23 artists), jazz (55), free jazz (4), electronic music (44), and folk music
(36). Important gaps remain: direct coverage is sparse and uneven, unresolved
seeds have no fabricated artist membership, and the real catalog needs bounded
query performance before these links are a usable discovery surface.

The historical Every Noise result is a local reference. It preserves 6,291
immutable genre name seeds and dated observed map output. It does not claim to
recreate Spotify's private data or McDonald's private model.

The open result keeps the source records immutable. Each source claim keeps its
source, license, snapshot, method, and observed time. A versioned derived graph
adds public identities, explicit taxonomy, overlapping review communities,
artist membership, genre similarity, and representative album and track
metadata. A derived record never replaces its source claim.

The first model is simple. Explicit parent and subclass statements provide the
hierarchy. Shared artists, public listener aggregates, and approved metadata
provide separate relation signals. Similarity combines those signals only in a
named model run. An artist can belong to several genres. A candidate relation
stays a review candidate until evidence or a human review promotes it.

The map uses stable neighborhoods. The overview shows broad connected groups.
Zooming reveals their child genres and nearby related genres. Further zooming
reveals artists and representative metadata. The map does not treat a denser
flat batch of points as a more detailed neighborhood.

The current full-corpus hierarchy checkpoint retains all 6,291 immutable names
and 66,132 directed public-evidence candidates: 160 accepted, 59,911 review,
and 6,061 abstained. The separately sealed all-seed frontier is built from the
restored public catalog snapshot. Neither artifact inherits artist memberships
through the hierarchy or uses historical data during construction.

The sealed v5 frontier receipt-binds and preserves the full Wikidata-fused v4
ledger: 2,377 MusicBrainz direct-observation seeds, 292 Wikidata seeds, 291
cross-source corroborations, and 2,378 direct-observation seeds in union. It
adds 23,497 ListenBrainz-derived review candidates across 425 seeds, all of
which already have direct observations. This adds no factual memberships and
no direct-coverage seeds. Its logical hash is
`edf01e96b8ab12d7c90b49cf9119aa5fb0a01ccdea253924b7923ed3e0ecbef8`;
the artifact byte hash is
`4c0dbc32b28d01b95ce79f988750b39db74241368a8b1257d6e2a9345c1c0db2`.

The downstream H3 check is evaluation only. It joins H3 page-member positives
through accepted receipt-bound Spotify-to-MusicBrainz bridges and never feeds
them into v5. Its artifact hash is
`7cbcd8b6859fd8207ac271c9564963f96fea9bfe57d8cc1541c125d4fa2fb6bb`.
It reports 179 top-50 hits among 15,772 positives for the 425 candidate-covered
genres (conditional recall 1.1349%), and 179 among all 120,163 bridge-resolved
unique positives (global positive-only recall 0.14896%). It abstains on 5,644
of 6,069 H3-positive genres. Precision is intentionally unavailable because
an H3 absence is unknown, not a negative.

Legacy taxonomy overlay and v6 frontier files are present locally but are
superseded and unverified under the current row-bound provenance schema. The
checked-in Poe workflow writes any replay to separate candidate directories.
Its source is the sealed catalog snapshot, not an undeclared relation-feed
path. The corresponding evaluator replays that same snapshot, so construction
and holdout evaluation share a declared immutable source boundary.
The current verified standalone replay retains all 6,291 seeds and projects
216 accepted factual edges from 853 permitted catalog P279 rows; 346 seeds have
an exact-QID mapping and 6,057 remain factual-isolated. It reports no review or
cycle rows. Its taxonomy input was
`.worktrees/open-construction-graph/data/model/genre-seed-public-taxonomy-v1.json`
(SHA-256 `5c8bac592fdbd982d529a422940b3d601c0c81b83e42d0c7641779821b03f712`)
and its logical artifact hash is
`21126aae5cf8b849edd132e9125ad12f1037474fecc1f89f6b8c1f8254efbd15`.
This is a taxonomy-only candidate, not a hierarchy, artist, or coverage
promotion.
The completed release-group candidate is local research. Its verified archive,
receipt, final evidence database, and artifact are bound in
`docs/MUSICBRAINZ_EVIDENCE_CHECKPOINT.md`. Direct artist claims and
release-group support remain separate. The prior staging SQLite database is
malformed and is not an input. MSD/Last.fm remains an offline, metadata-only
adapter awaiting the three verified SQLite files (or an already verified local
cache receipt); no live MSD result is claimed.

An optional Last.fm reverse-tag adapter is review-only. It writes its
credential-free query manifest before any network request and exits 2 without
`LASTFM_API_KEY`; no live Last.fm artifact is sealed in this checkout. A claim
requires a Last.fm-provided MusicBrainz artist ID plus exact normalized tag
corroboration for that same ID. Name-only rows and all noncorroborated results
remain review data and cannot promote identities, memberships, taxonomy, or
hierarchy facts.

The historical peer compatibility evaluator name-matches 6,289 H3 genre names.
Only 1,580 have a constructed candidate neighborhood and are peer-supported;
the other 4,709 are retained as abstentions. The 1,580 figure is an evaluation
subset, not genre, catalog, or hierarchy coverage. H3 has unranked,
positive-only samples, so this remains a neighborhood check rather than a
ground-truth reconstruction.

The separate bridge-backed membership experiment maps 120,288 of 306,136 H3
observations to 78,954 MusicBrainz artists using receipt-bound identities and
an 88,328-artist, 212,696-row open-tag matrix. Its open-only Recall@50 is
0.01582 micro and its H3 edge-holdout Recall@50 is 0.03059 micro; 1,172 whole
cold-label genres deliberately abstain. It is a local, positive-only baseline,
not complete membership, ranked relevance, Every Noise parity, or a serving
model.

The bounded representative catalog currently contains 51 retained releases
and 491 unique track records across 40 genres. These are metadata records only.
They are not claims about the defining or most important works for a genre.

OpenNoise never downloads, stores, serves, embeds, or trains on audio or music
files. Links and playback placeholders remain separate from metadata.

McDonald documented broad inputs and behavior. He described overlapping music
communities, cultural and acoustic signals, listener based discovery, human
review, and readability adjusted map positions. The public record does not
give the private feature vectors, complete source code, weights, thresholds,
candidate rules, or final layout transform. OpenNoise labels experiments as
approximations and reports what is observed, disclosed, inferred, or unknown.

The pipeline is: immutable source snapshot, typed source claim, SQLite
projection, versioned derived graph, evaluation, and public publication. Each
adapter writes provenance and each model run records its inputs, parameters,
code revision, seed, and content hash. Local object storage and future object
stores use the same small abstraction.

Keep the stack small: Python 3.13.14, uv, mise, Poe, Pydantic, SQLite, and
Cloudflare Pages. Offline tools construct source-bound artifacts, then one
static exporter writes the complete browser surface. The browser receives
precomputed HTML, JSON, CSS, and JavaScript only: it has no OpenNoise API,
application server, server-rendered route, or graph-layout calculation.
