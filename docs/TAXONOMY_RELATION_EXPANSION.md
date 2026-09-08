# Taxonomy relation expansion

`taxonomy_relation_expansion` is a narrow hierarchy adapter for independently
cached taxonomy relations. It is not an H3 construction stage and it never
reads historical geometry, historical memberships, artists, audio, or names as
relation keys.

The sealed taxonomy artifact provides the only seed bridge. A source endpoint
can reach a legacy seed only through one unambiguous canonical or alias
Wikidata QID already recorded in that artifact. MusicBrainz relations require a
separate `exact_identifier` MusicBrainz-genre-to-Wikidata-QID mapping. Normalized
names, aliases supplied by a relation feed, and fuzzy matches are rejected as
identity evidence.

The relation-feed JSON is immutable by content: every direct observation and
every MusicBrainz/QID mapping records a `source_response_sha256`, and the feed
records an `output_sha256` over canonical JSON. A feed can be made from an
official batched SPARQL response cache outside the builder, provided the raw
response hash and stable observation IDs are retained. It also needs a typed
source-custody receipt that names an immutable object-store key, byte hash, and
size for that raw response. Construction re-hashes that stored object in place
and blocks a missing, substituted, or unreceipted source. The builder itself
makes no network requests. The optional `--catalog-snapshot` path publishes the
exact local snapshot into the supplied object store and extracts only its
row-level export-permitted CC0 `genre_hierarchy` rows as direct Wikidata P279
observations; it does not invent P31, part-of, or MusicBrainz relations that
the catalog does not contain.

At this checkpoint, only direct P279 rows replayed and row-bound from the
sealed catalog snapshot can become `accepted_factual` seed edges. Generic
relation feeds, including explicit `musicbrainz_subgenre_of` observations, are
review-only and cannot promote a factual edge. P31, Wikidata part-of,
MusicBrainz part-of, and MusicBrainz related rows are likewise
`review_derived`. Multiple direct parents are retained. A deterministic
factual-first traversal prevents cycles; the row that would close one is
preserved as `abstained_cycle` with all of its original provenance.

The checked-in Poe task replays the sealed catalog snapshot at
`.cache/catalog-snapshots/sha256/240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc.sqlite`.
It writes only the distinct candidate paths in `.env.example`. Build an artifact
from cached feeds and/or that sealed catalog snapshot:

```sh
python scripts/build_taxonomy_relation_expansion.py \
  --taxonomy path/to/genre-seed-public-taxonomy.json \
  --relation-feed cache/wikidata-and-musicbrainz-relations.json \
  --catalog-snapshot cache/public-catalog.sqlite \
  --holdout-reference-candidates path/to/genre-hierarchy-candidates.json \
  --output out/taxonomy-relation-expansion.json \
  --object-store out/objects \
  --receipt out/taxonomy-relation-expansion.receipt.json
```

The current standalone replay candidate was independently verified by replaying
its receipt-rooted snapshot: 6,291 retained seeds, 853 permitted P279 source
rows, 216 projected accepted factual edges, 346 exact-QID-mapped seeds, 6,057
factual-isolated seeds, and zero review or cycle rows. It is not a hierarchy or
membership promotion. It used
`.worktrees/open-construction-graph/data/model/genre-seed-public-taxonomy-v1.json`
(SHA-256 `5c8bac592fdbd982d529a422940b3d601c0c81b83e42d0c7641779821b03f712`)
and has logical artifact hash
`21126aae5cf8b849edd132e9125ad12f1037474fecc1f89f6b8c1f8254efbd15`.

The artifact reports every input observation as projected, skipped because an
endpoint lacks an exact seed QID, or skipped because a QID maps to several
seeds. It also reports factual isolated-seed reduction from the empty 6,291-seed
graph. `evaluate_taxonomy_relation_expansion` can deterministically hide
reference factual edges and nodes *before construction*: the builder removes
all source observations that project to those exact held-out pairs or nodes,
then binds the derived training-feed hash into the artifact. The evaluator
recomputes the same split and rejects an artifact built from the unsplit feed.
It reports holdout recall. Precision is explicitly unavailable unless the
caller supplies a defensible, explicitly labelled negative edge set; source
absences are not negatives.

The local direct-P279 replay has no remaining independent signal for a source
row once that same row is held out. A zero recovery result in that condition
therefore records absence of independent recovery evidence; it is not a
negative judgment on the separately retained factual edges.

The corresponding CLI takes a prior hierarchy-candidate artifact as an
evaluation oracle, filters it to `accepted` `factual_public_taxonomy` rows, and
does not feed it to construction:

```sh
python scripts/evaluate_taxonomy_relation_expansion.py \
  --expansion out/taxonomy-relation-expansion.json \
  --taxonomy path/to/genre-seed-public-taxonomy.json \
  --reference-candidates path/to/genre-hierarchy-candidates.json \
  --catalog-snapshot cache/public-catalog.sqlite \
  --source-object-store out/objects \
  --output out/taxonomy-relation-expansion-evaluation.json
```

## Hierarchy integration

After standalone review, the hierarchy-builder inputs
`--taxonomy-relation-expansion`, `--taxonomy-relation-expansion-receipt`, and
`--taxonomy-relation-source-object-store` add only the artifact's
`accepted_factual` exact-ID edges. The receipt artifact and its source objects
are re-hashed before use. Existing seed pairs are deduplicated, multiple
parents remain valid, and the factual-first DAG gate abstains any cycle. The
result is a comparison candidate only; it does not seal v6 or promote review
relations.

For a large existing hierarchy artifact, use the compact
`taxonomy_relation_hierarchy_overlay` instead of rewriting the full candidate
payload. It receipt-binds the immutable base object, streams only its candidate
pair keys and accepted DAG, and stores direct factual additions or factual
upgrades plus the union pair hash and coverage deltas. Consumers must resolve
the base receipt and apply the overlay; the overlay is not itself a v6 seal.
The overlay command requires these explicit environment bindings when invoked
through Poe: `MUSIX_GENRE_HIERARCHY_CANDIDATES_OUTPUT`,
`MUSIX_GENRE_HIERARCHY_CANDIDATES_RECEIPT`,
`MUSIX_GENRE_HIERARCHY_CANDIDATES_OBJECT_STORE`,
`MUSIX_GENRE_HIERARCHY_CANDIDATES_RECEIPT_SHA256`,
`MUSIX_TAXONOMY_RELATION_EXPANSION_OUTPUT`,
`MUSIX_TAXONOMY_RELATION_EXPANSION_OBJECT_STORE`,
`MUSIX_TAXONOMY_RELATION_HIERARCHY_OVERLAY_OUTPUT`,
`MUSIX_TAXONOMY_RELATION_HIERARCHY_OVERLAY_OBJECT_STORE`, and
`MUSIX_TAXONOMY_RELATION_HIERARCHY_OVERLAY_RECEIPT`. The expected receipt hash
is a trust root, rather than a value supplied by the receipt itself; construction
also re-hashes its referenced object and streams the base logical hash replay.

## Compact v6 evidence frontier

`build-taxonomy-relation-frontier-v6` is a wrapper, not a reconstructed
frontier. It receipt-verifies the sealed v5 object and the sealed overlay object
against caller-supplied receipt-hash trust roots. It preserves the complete v5
coverage matrix (including MusicBrainz, Wikidata, ListenBrainz, and peer
coverage) by hash and exact embedded summary, then adds only a sorted 6,291-row
projection of direct factual relation parent/child incidence. It reports the
base and union hierarchy candidate/accepted counts and isolated-seed reduction.
Neither H3 nor historical data is read or used.

Legacy overlay and v6 frontier files remain at
`.cache/taxonomy-relation-hierarchy-v6-overlay-sealed-v3/overlay.json` and
`.cache/all-seed-evidence-frontier-v6-taxonomy-overlay-v2/artifact.json`, with
their sibling `objects/` directories and receipt files. They are superseded and
unverified under the current row-bound provenance schema; do not use them as
trust roots or promote their counts. Poe candidate commands do not overwrite
them: `.env.example` assigns new `*-candidate-*` output directories. The v6
task accepts the sealed v5 artifact and candidate overlay as explicit inputs,
and requires an independently recorded candidate-overlay receipt hash. A
successful candidate is not a new seal or promotion.
