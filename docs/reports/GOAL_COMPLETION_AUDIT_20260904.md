# Goal completion audit

Audit basis: main `260b21ebd399e2d1569480a9fe7bd740a422f580`, inspected in an
isolated worktree. Counts below were queried read-only from the retained serving
database at `/home/h0rv/projects/musix/.worktrees/final-integration/.cache/release-certify/public.sqlite`.
That database is release evidence, not a checked-in input.

The statuses describe the current Musix implementation. They do not claim that
the historical Every Noise output or any lexical label is ground truth.

| Requirement | Status | Evidence and measured result |
| --- | --- | --- |
| Open adapter pipeline | **Proven, bounded** | `docs/DATA_PIPELINE.md:47-61` separates transport, explicit adapters, lifecycle, projectors, and SQLite. `src/musix/sources/registry.py:15-60` defines and capability-checks the adapter protocol without reflection. `config/data_sources.toml` pins source URLs, snapshots, hashes, policies, and adapter keys. The release database contains 62 `data_sources`, 62 `source_artifacts`, 62 `ingest_attempts`, 37,011 `staged_records`, and 2 parser releases. The pipeline is real, but large MusicBrainz release and recording archives remain intentionally unimported (`docs/MUSICBRAINZ_CATALOG_IMPORT.md:1-12`). |
| Privacy-safe aggregate listening | **Proven** | `docs/DATA_PIPELINE.md:90-125` and `migrations/0005_artist_co_listen_evidence.sql:5-6,91-112` specify artist-pair aggregates, no listener identifiers, and a privacy floor. `tests/test_graph_validation.py:184-212` exercises the floor and rejection paths. The database has 30,903 co-listen rows across 7 windows; `distinct_user_count` is 5–38, with 1,163/1,210 distinct endpoint IDs. |
| No audio, previews, or music files | **Proven** | `docs/CONTENT_POLICY.md:3-25` defines the enforced metadata-only boundary. `tests/test_content_policy.py:46-105` covers manifest, signatures, object storage, archives, and forbidden dependencies; `tests/test_genre_discovery.py:27-90` checks preview and track-field removal. In the release database, `media`, `audio_feature_observations`, and `content_fragments` each contain 0 rows. |
| Explainable genre/artist membership and similarity | **Proven** | `docs/PUBLIC_MODEL.md:20-23,51-60` and `migrations/0011_public_model_explainability.sql:9-35` persist direct and one-hop profiles, component values, source references, metrics, scores, shared-artist counts, and ranks. `src/musix/exploration.py:132-174` exposes the typed API contract; `src/musix/genre_entry.py:127-178` reads it. Measured release counts are 4,434 direct profiles, 22,091 one-hop profiles, 26,525 total profile rows, and 34,348 neighbor rows, split across weighted Jaccard and cosine. All 26,525 profile rows have evidence and component JSON. |
| Representative albums and tracks | **Partial** | The public contract and UI exist: `src/musix/exploration.py:176-190`, `src/musix/genre_entry.py:77-178`, `src/musix/templates/genre_detail.html:12-14`, and `migrations/0002_album_genres.sql:90-160`. The release artifact contains 3,344 representative links: 1,975 artists, 871 release groups (albums), and 498 recordings (tracks), as also reported in `docs/reports/LAYOUT_LENSES_20260831.md:54-58`. Coverage is not a complete catalog chain: the measured database has 787 `release_groups`, 623 `recordings`, but 0 `releases`, 0 `tracks`, and 0 album-ranking runs/items. Complete release/track ingestion and ranking publication remain open. |
| Independent layouts | **Proven** | `src/musix/layouts.py:34-120` defines versioned strategy inputs and reproducibility metadata. `src/musix/ml/layout_lenses.py:408-477` builds separate public, direct, community, and taxonomy lenses. `migrations/0008_public_model_layout_lenses.sql:5-35` makes them immutable. The release database has 4 `public_model_layouts` and 4 `current_layouts`: `public`, `public-direct`, `public-community`, and `public-taxonomy`. `tests/test_public_graph.py:176-201` verifies the four artifacts and exact reruns. |
| Switchable visualization | **Partial** | Backend selection is implemented by `GET /api/explore/map?layout=...` and `resolve_layout` (`src/musix/routes.py:248-308,544-558`), with four published layout rows. The product shell currently exposes only Public versus historical links (`src/musix/templates/map.html:1-7`); it has no public direct/community/taxonomy selector. The tests explicitly preserve this omission (`tests/test_workspace_template.py:65-115`). Historical view is addressable but optional and unavailable without a separately configured local artifact (`tests/test_app.py:47-55`; `src/musix/routes.py:187-213`). A labelled user-facing lens selector and accepted historical wiring are the highest-value UI blocker. |
| Reproducible publication | **Partial** | The release boundary and content-addressed publication are implemented: `docs/PUBLIC_RELEASE_PIPELINE.md:1-20,28-61`, `scripts/release_certify.py:121-213`, `migrations/0007_public_model_serving.sql:5-39`, and `docs/OBJECT_STORAGE.md:3-25`. Retained evidence records cache SHA-256 `282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866`, model/map hashes, 62 input artifacts, 3,344 representatives, 26,525 profiles, and 34,348 neighbors. However, the exact 153,231,360-byte sealed cache is not retained in a fresh checkout; `docs/DATA_PIPELINE.md:179-194` explicitly says a manifest-only checkout cannot rebuild source-to-publication. Cache retention or distribution is the highest-value release blocker. |

## Retained artifact measurements

The queried release database also contains 603 `public_genre_names`, 1,331
artists, 3,487 catalog entities, 746 genre rows before qualification, 603
qualified public genre names, 712 taxonomy-related entity edges, and 37,017
provenance records. The production-map artifact
`/home/h0rv/projects/musix/.worktrees/final-integration/.cache/production-map-v1.json`
contains 603 nodes, 188 communities, 3,986 edges, 4 levels of detail, 603
profiles, 4,552 neighbors, and 603 explanations. Its acceptance report
records `accepted: true`, zero desktop/mobile label overlaps, persistent LOD,
and full region containment.

The public release receipt is
`/home/h0rv/projects/musix/.worktrees/final-integration/.cache/release-certify/receipt.json`.
The retained historical compatibility publication is separate and local-only:
`/home/h0rv/projects/musix/.cache/historical-signal-final/historical-signal-publication-v1.receipt.json`.
It must not be treated as input to the public model.

## Highest-value implementable blockers

1. Retain or distribute the exact sealed Phase 3 cache and its 62 source
   objects so a clean checkout can reproduce the serving database, model, map,
   and browser evidence.
2. Add a public-lens selector that names each versioned view and its source/model
   boundary, while keeping the historical option explicitly local-only.
3. Finish the MusicBrainz release, release, and recording/track catalog chain,
   then run the existing evidence-backed album and recording ranking tables.
4. Preserve the full-suite lifecycle check in certification. The known
   Litestar `TestClient` timeout was caused by restricted runners suppressing
   AnyIO's cross-thread socket wakeup; app tests now use a bounded polling
   selector and the full suite passes in a normal shell. The production app
   keeps its non-blocking threaded database boundary.
