# Source and signal inventory

This is an implementation and receipt inventory, not a claim that every
available source is a promoted production signal. Rights and export fields are
deployment-policy metadata, not a statement that technically useful open
evidence cannot be evaluated in a separately governed research or fusion run.
Every Noise is restricted to
the immutable 6,291-name target and blind, post-freeze historical evaluation.
Its coordinates, memberships, neighbors, representatives, ordering, and any
derived feature remain forbidden construction inputs.

| Signal | Implemented adapter/cache and exact role | Latest measured coverage | Join or promotion status |
| --- | --- | --- | --- |
| Stable genre identity | `taxonomy/seeds/universe.py`, `ingest/wikidata/resolver.py`, and `adapters/wikidata.py` retain source IDs and exact normalized label/alias candidates; `taxonomy/relations/expansion.py` admits only replayable catalog QIDs. | 346 unambiguous canonical/alias QID bindings from 6,291 names. | Factual identity only when exact and receipt-replayable. 5,945 names remain unmatched. |
| Aliases | Wikidata aliases are parsed with label provenance; `serving/local/reviewed_alias_context_store.py` supplies a separately configured local review context. | No current public alias-count artifact beyond the 346 exact bindings. MusicBrainz prefix-0 archive reports zero genre aliases. | Alias candidates do not become fuzzy identity joins. Local review context is not public input. |
| Factual hierarchy | `adapters/wikidata.py` reads P279; `taxonomy/relations/expansion.py` and `structure/hierarchy_candidates.py` retain factual, review, and abstained edges separately. | 853 export-permitted catalog P279 rows; 216 accepted factual seed edges; 6,057 factual-isolated seeds. | Every accepted edge needs source-row/custody/provenance binding. Review links never become facts by score alone. |
| Artist membership, public | `serving/public/artist_membership_adapter.py` and `adapters/wikidata.py` use direct Wikidata P136 with policy/provenance checks. | 4,948 source rows, 3,049 direct pairs, 292 directly anchored names; 5,999 names explicitly abstained. | Export candidate only; no independent public gold set has promoted it. Parent-to-child inheritance is prohibited. |
| Artist membership, local | `ingest/musicbrainz/model_adapter.py` and `serving/local/musicbrainz_artist_evidence.py` retain official MusicBrainz artist genres/tags in a content-addressed cache. | Prefix-0 scan: 724 normalized seed matches, 12,481 artists, 24,363 positive edges. | Current rights/export fields govern public deployment. They do not prevent a separately governed research or fusion evaluation. |
| Releases and albums | `adapters/wikidata.py` exposes album P136; `evidence/album_genres.py` records direct versus inferred evidence; `ingest/musicbrainz/release_group_evidence.py` creates capped release-group support. | 4,499,326 release groups; 1,954 supported seed names; 1,546,265 support pairs; 193 support-only names. | Support is not an artist-direct membership claim. It is a 3,259,346,944-byte unpromoted evidence graph, not the current public map. |
| Listening/co-listen | `ingest/listenbrainz/dumps.py`, `catalog/co_listens.py`, and `pipeline/source_cache.py` cache verified dumps and persist privacy-floor artist pairs without listener IDs. | Seven-day public run: 30,903 pair days from 30,469,708 listens; public candidate has 13,175 normalized aggregate pairs. | Exportable aggregate support only after receipt and privacy checks; raw events and user IDs are not served. |
| Peer similarity, public | `ml/public_graph.py`, `peers/similarity/similarity.py`, and `ml/production_map.py` derive weighted similarity from membership plus co-listen support, separate from hierarchy. | Sealed map: 603 nodes, 3,274 similarity edges, 712 taxonomy edges, 188 communities. | Similarity is evidence-derived and non-taxonomic. Current source projection still has known boundary pileups and level-3 concentration. |
| Peer similarity, local | `peers/similarity/historical.py`, `serving/local/musicbrainz_peer_store.py`, and `serving/local/research_peer_layout.py` build receipt-bound MusicBrainz candidate peers. | 28,508 local peer edges; 1,580 placed seeds; community-packed spectral KNN preservation 0.186309523810. | Current rights/export fields control public deployment; an explicit research/fusion evaluation can use this signal without relabeling it as public-map evidence. |
| Region, era, culture | `serving/artist_metadata_context_pilot.py` is a cache-first, 50-artist MusicBrainz context pilot for country, area, begin area, aliases, and names. | No checked-in completed projection receipt or safe genre-level aggregation count. | No current geographic, cultural, or era signal joins the public graph; nationality/origin/genre inference is disclaimed. |
| Evaluation identity bridge | `ingest/spotify/bridge.py` reads MusicBrainz relations and joins only to the fixed historical H3 artist-ID universe. | Goal audit: 120,288 H3 observations mapped to 78,954 MusicBrainz artists. | H3 is a join/evaluation boundary, never construction evidence or a negative-label source. |
| Historical adapter boundary | `adapters/everynoise.py`, `history/historical_custody.py`, and `history/historical_compatibility.py` retain or compare historical material only behind custody/evaluation contracts. | Immutable target: 6,291 names. No historical coordinate, membership, neighbor, or representative count is a construction coverage measure. | Blind post-freeze evaluation only; historical output cannot tune, select, or populate an exported graph. |
| Source cache and custody | `pipeline/source_cache.py`, `storage/local.py`, and `clients/downloads.py` use SHA-256-addressed objects plus deterministic receipts; `clients/wikidata.py` provides query-response custody. | Open v2 receipt: 6,291 legacy names, 746 catalog anchors, 3,317 typed edges. | License, local/export scope, bytes, and cache identity must pass before admission. |

## Edge explainability and confidence

The public map contract exposes `evidence_refs` on every node, taxonomy edge,
similarity edge, and community. Similarity edges also expose `weight`, `rank`,
and `shared_artist_count`; taxonomy edges expose fixed weight and display-tree
selection. This is traceable evidence, not a calibrated probability.

Open construction v2 preserves source, expansion-edge ID, catalog IDs, an
explanatory note, and factual versus review state per edge. It deliberately has
no numerical confidence. The older v1 uses fixed factual/review settings
(0.98/0.62), not a calibrated confidence model. Hierarchy candidates instead
expose score components and `accepted`, `review`, or `abstained` disposition.

The 603-node, 3,274-similarity-edge production map and the 3,259,346,944-byte
MusicBrainz release-group candidate are different artifacts with different
contracts. The latter's 4,775,264 support rows are not map nodes, public-map
edges, or evidence of current-model parity.

## Missing joins and fusion order

1. Increase receipt-bound exact QID and P279 replay coverage. This alone can
   safely reduce the 5,945 identity and 6,057 factual-hierarchy gaps.
2. Evaluate public P136 plus privacy-safe aggregate candidates against an
   independent public gold set before promotion; retain abstention otherwise.
3. Evaluate receipt-bound local MusicBrainz release-group and peer signals
   separately for sparse supported genres, with rights review, before fusion.
4. Add a separately sourced, provenance-bound temporal/region/culture signal
   only with an explicit non-essential-semantics policy.

## Acceptance gates for later fusion

- Membership: held-out retrieval, reported separately by direct support,
  aggregate support, and whole-label cold cases.
- Peers: held-out or time-split peer recovery with support strata; no coordinate
  target can be optimized.
- Hierarchy: direction, acyclicity, multi-parent accounting, and factual-edge
  agreement, with review candidates reported separately.
- Region, era, culture: coverage and missingness before any graph effect.
- Map: neighborhood preservation only. Historical coordinate parity is never a
  construction or acceptance target.

Counts come from `WIKIDATA_GENRE_ENRICHMENT_REUSE_AUDIT_20260913.md`,
`OPEN_CONSTRUCTION_GRAPH_V2_20260904.md`,
`PUBLIC_ARTIST_MEMBERSHIP_REAL_INPUT_20260905.md`,
`MUSICBRAINZ_ARTIST_GENRE_COVERAGE_20260904.md`,
`MUSICBRAINZ_RELEASE_GROUP_CANDIDATE_20260908.md`, and
`LOCAL_RESEARCH_EVIDENCE_LAYOUT.md`. A missing count means no retained,
authoritative completed artifact is present here; it is not zero.

The codebase also contains bounded Last.fm reverse-tag/MSD readers, MusicBrainz
release hydration, ListenBrainz H3 evaluators, and Spotify artifact readers.
No checked-in receipt makes any of those a current public construction signal,
so they are intentionally absent from the measured rows rather than treated as
zero-coverage evidence.
