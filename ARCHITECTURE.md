# OpenNoise: target design from scratch

Goal: an open Every Noise at Once. Thousands of genres, each with real member artists, placed on a 2D map
where position means something sonic, plus an artist lookup with good similar artists. The bar is
quality you can measure against Every Noise (ENAO), not provenance paperwork.

## 1. Why the old repo failed (design-level only)

1. **Process replaced the product.** Sealing, receipts, certification gates and abstention rules
   were built before any model existed. The result: about 300k lines, a main map with 151 genres
   and 440 artists, and an H3 recall of 0.15% against ENAO.
2. **No real modeling.** The "membership" it allowed was only what a source claimed directly. Every
   learned signal was kept as a "review candidate" and never shipped. ENAO is a model built on
   listening plus audio, and nothing short of a model gets close to it.
3. **The reference was banned as a training signal.** ENAO's 6,291 coordinates and genre-to-artist
   memberships were declared evaluation-only, so open genre names matched only 11% of ENAO names.
4. **Tiny, shifting scopes.** It jumped between FMA, a 433-artist CC0 pack, the MusicBrainz bulk
   tags and 1k Wikidata genres, so no pipeline ever ran end to end at full scale.
5. **The one good signal was left on the side.** ListenBrainz co-listening already gives good similar
   artists for about 11.9k artists on the Connections page, but genres and the map never used it, and it lives on the unmerged `ml/artist-graph-v1` branch.
6. **Docs crowded out the code.** There were 186 checkpoint docs, and the README became a list of caveats.

Rules going forward: one pipeline, full scale, every run scored. Licensing is settled once per source
(table below) and is not a runtime gate.

## 2. What ENAO actually is (what we approximate)

- **Genres** are clusters of artists found from Spotify listening, named by a person or by web and
  playlist text. That gives about 6,300 genres, most of them micro-genres.
- **Map axes** come from Echo Nest audio attributes. Down is organic and up is mechanical/electric;
  left is dense/atmospheric and right is spiky/bouncy. Color is a mix of other attributes. A genre's
  position is the mean of its artists' audio features.
- **Inside a genre**, artists are placed the same way. Clicking one plays a preview.
- **Similar artists** come from listening.

So we need three open signals: **listening (who goes with whom)**, **tags/text (what to call it)**
and **audio (where it sits)**.

## 3. Sources

| Signal | Source | Scale | Terms | Use |
|---|---|---|---|---|
| Identity spine | MusicBrainz JSON/PG dump | ~2.5M artists | CC0 core | MBIDs; URL rels give Discogs, Wikidata, Spotify, Deezer IDs |
| Similar artists | ListenBrainz labs similar-artists (`session_based_days_1800_session_300_contribution_3_threshold_10_limit_100_filter_True_skip_30`) | about 200k pairs from 3.1k seeds so far | CC0 | the proven baseline from `ml/artist-graph-v1`. Re-implement it in about 100 lines |
| Listening | ListenBrainz full listen dumps | ~1B+ listens, tens of thousands of users | CC0 | user x artist matrix, the core of the similarity graph |
| Listening (gap filler) | Last.fm API `artist.getSimilar` / `getTopTags` | per artist | API ToS, non-commercial, no bulk redistribution | fills the long tail where LB is sparse. Use derived scores only, never redistribute raw data |
| Styles | Discogs monthly dumps | ~16M releases, ~600 styles | CC0 | artist style distribution weighted by release count. This is the best open micro-genre vocabulary |
| Tags | MusicBrainz tags/genres | ~2k genres | tags CC BY-NC-SA | genre names, aliases, artist tag vectors |
| Taxonomy | Wikidata P136/P279/P737 | ~15k music genres | CC0 | parent edges, names, origins |
| Audio descriptors | AcousticBrainz dumps (frozen 2022) | ~7M recordings | CC0 | low/high-level features for the map axes |
| Audio (new) | Deezer/iTunes 30s previews -> Essentia Discogs-EffNet / MAEST / CLAP embeddings | top N tracks per artist | compute locally, never store or redistribute audio | sonic embeddings for artists AcousticBrainz lacks; also the in-app previews (fetched client side at runtime) |
| Reference | ENAO final map (quint-t, sha256 `1ac0c659…`), genre->artist map (NeroYuki `spotify_genres_artists_map.json` @88bd6f6, 6,435 genres -> Spotify artist IDs), EveryNoise-Watch 2021 coordinates | 6,291 genres | no license / CC-BY-SA | Genre vocabulary and membership labels; map coordinates are **evaluation only**, never regression targets or layout initialization. Raw ENAO data is never published |

**Main risk:** ListenBrainz has a small user base next to Spotify, so co-listening alone will
resolve broad and mid-level genres well but not micro-genres. Discogs styles, Last.fm similarity and
audio embeddings cover that gap. This is the real ceiling on ENAO-level quality and should be measured
early (see M1).

Already tried, don't repeat: topic models on MusicBrainz tags (novel-label recall 1.5%); exact-name
matching of tags to ENAO names (11-34% ceiling); building on FMA (almost no mainstream overlap).
AcousticBrainz is patchy per artist, so it needs preview embeddings beside it.

## 4. Pipeline

Every stage is a pure function from Parquet to Parquet, run by Polars or DuckDB. A run directory holds
its outputs, keyed by the config hash.

```
ingest/      raw dumps -> normalized parquet (artists, recordings, listens_agg, styles, tags, audio)
identity/    MBID crosswalk (Discogs, Wikidata, Spotify, Deezer, Last.fm); fuzzy-match only as a last resort
signals/
  colisten   LB user x artist -> min-count filter -> PPMI + implicit ALS (or item2vec) -> artist_emb_listen (d=128)
  tags       Discogs style dist + MB tags + Last.fm tags -> TF-IDF -> artist_tagvec (sparse) + artist_emb_tag (SVD)
  audio      AcousticBrainz/Essentia per recording -> artist mean over top tracks -> artist_audio (axes + emb)
fuse/        artist_emb = concat/learned weighting of listen|tag|audio; kNN graph (FAISS/hnswlib, k=50)
genres/
  supervise  ENAO memberships mapped via Spotify->MBID (MB URL rels) -> train an artist x genre
             multi-label classifier (kNN label propagation, then a linear/MLP head on artist_emb) for the
             6.3k ENAO genres; held-out artists and genres feed eval. This is the main path to parity.
  discover   Leiden on kNN graph at multiple resolutions -> nested communities (broad > mid > micro)
  name       label each community with its most enriched specific tag (lift vs parent); LLM tie-break
             for naming only; match to taxonomy/ENAO names by member and name overlap
  member     soft membership: artist x genre score; multi-label; threshold per genre
  relate     genre centroids in each space; genre-genre similarity; hierarchy = Leiden nesting
             reconciled with Wikidata P279
layout/
  axes       ALS+audio genre UMAP, orthogonally oriented to fixed AcousticBrainz feature axes.
             Train-fitted ranks and UMAP transform shared by catalog genres, artists and global groups.
             Captions describe held-out audio associations only; Every Noise coordinates are scoring only.
  islands    UMAP of genre embeddings -> density contours = islands (broad genres), labels per zoom
  tree       hierarchy JSON for the tree and radial view
similar/     artist top-k neighbors (listen-dominant, re-ranked by tag/audio agreement)
export/      PMTiles (genres, artists by zoom), per-genre and per-artist JSON shards, search index
eval/        scores every run against the benchmarks below
```

Notes:
- **Scale.** Keep artists with at least X distinct LB listeners or at least Y Discogs releases. Target
  is 200k to 500k artists in the graph and 60k to 150k on the map. One beefy box with DuckDB is
  enough; no Spark.
- **Provenance** is one `sources.toml` row per snapshot (URL, date, sha256, licence). Nothing more.
- **Fusion weights** are tuned against eval, not chosen by hand.
- **Genre count** is a dial (Leiden resolution plus minimum size). Target is 3k to 6k named genres.
- **Unnamed or weak clusters** stay out of the map but stay in the data.

## 5. Evaluation (the "objective quality" part)

One `eval` stage, one row per run in `experiments/results.tsv`:

| Metric | Definition |
|---|---|
| genre_match | share of ENAO genres matched by a discovered genre (member Jaccard >= 0.2 via the Spotify->MBID crosswalk) |
| member_recall@k | per matched ENAO genre, its ENAO artists found in our top-k members |
| map_neighbor_overlap | per genre, overlap of its 10 nearest map neighbors with ENAO's |
| axis_corr | Spearman between our axes and ENAO's x/y for matched genres |
| similar_artist_ndcg | vs held-out LB co-listening and Last.fm getSimilar |
| coverage | artists placed, genres named, share of genres with at least 10 members |
| spot_check | fixed probe list (Aphex Twin, Boards of Canada, Four Tet; shoegaze, vapor soul, ...) rendered to a diff file and reviewed by eye |

Each run must beat the previous best on a primary metric or be logged as a failure.

## 6. Experiments, without slop

- `experiments/results.tsv`: append-only. Columns: date, commit, config hash, change, metrics, kept or
  discarded, and a one-line note. Failures stay in it.
- `configs/*.toml`: one file per pipeline variant. A run is `on run configs/x.toml`.
- `runs/<hash>/`: gitignored artifacts and eval JSON. Promoting a run copies its export to `release/`.
- Docs are `README.md` (run it) and `ARCHITECTURE.md` (this design, kept current). Nothing else.

## 7. UI/UX (last; static)

- **Map.** MapLibre GL or deck.gl over PMTiles on Cloudflare R2/Pages. Zooming out shows islands
  (broad genres, terrain-style, like Wilson Lin's HN map). Mid zoom shows genre labels sized by
  popularity. Close zoom shows the artists inside a genre at their audio positions.
- **ENAO mode.** A flat genre field on the ENAO axes, where clicking plays a preview (Deezer, fetched
  client side).
- **Tree.** Root > broad > mid > micro as a collapsible or radial tree. It is a second view of the same
  hierarchy JSON.
- **Artist page.** Its genres (with scores), similar artists, its position on the map, and outbound
  links (MB, Discogs, Spotify, Bandcamp).
- **Search.** A prebuilt static index over artist and genre names. No server.

### Pipeline / UI contract (v1)

`src/opennoise/catalog.schema.json` is the public interface. Its root is `Manifest`; `$defs`
also define `Genres`, `Search`, `GenreDetail` and `ArtistDetail`. Generate frontend types from
this schema, not from pipeline experiment files. Validate a release with
`uv run python -m opennoise.contract <release-directory>`. `tests/fixtures/catalog/` is an
explicitly synthetic release for UI development, not evidence of model quality.

| File, relative to an immutable release root | Shape |
|---|---|
| `manifest.json` | Schema version, release ID, synthetic/model flag, available layouts and model methods |
| `genres.json` | Genre summaries, including the complete navigation forest via `parent_id` |
| `search.json` | Complete artist/genre identity index with display names and aliases |
| `genres/{id}.json` | Canonical genre summary, all scored members, ranked related genres |
| `artists/{mbid}.json` | Canonical artist summary, scored genres, similar artists, signals, links, preview locator |

Artists use lowercase MBIDs, never run-local `item` indices or names. Genre IDs are persisted
slugs assigned once, not regenerated after renaming, retraining or changing hierarchy. A merge
keeps one ID and the old name as an alias; splits receive new IDs. Retired IDs are never reused;
clients show unavailable for saved IDs absent from a release. Navigation has one optional
parent per genre, no cycles and no fabricated root; multiple genre memberships remain separate
scored edges. Tree/radial views derive from that forest, not another taxonomy artifact.

Pipeline tables remain normalized Parquet; experimental filenames and columns are private.
The eventual `export` adapter joins local item/genre indices to these IDs and projects these
relations into the public schema (the M1 CLI remains unchanged):

| Relation | Key and payload |
|---|---|
| Artists / genres | MBID / genre ID, display attributes and nullable measured counts |
| Membership | `(artist_mbid, genre_id)`, soft score in `[0,1]`; both public directions use these same edges |
| Artist / genre similarity | Directed `(source_id, target_id)`, score in `[0,1]`; no self edges |
| Positions | `(entity_kind, entity_id, layout)`, nullable `x,y` in one release-wide frame |
| Identity links / preview | Artist MBID, HTTPS outbound links and optional provider track ID |

M2's concrete adapter inputs are `genres.parquet` (`id: Int64`, `name: String`, `level: Int64`,
`parent: Int64?`, `size: Int64`) and `memberships.parquet` (`artist: String` MBID,
`genre: Int64`, `score: Float64`). These IDs are local to a variant/run. Map both `id`/`genre`
and `parent` through one persisted ID registry, retaining distinct same-named communities.
Supervised genres have `level = -1`; Leiden levels are `0..N`, not a fixed UI depth. Exclude
`unnamed <id>` clusters from the public catalog and walk past excluded ancestors to the nearest
published parent (or null); `parent` is a navigation relation, not guaranteed set containment.
Project each retained `(artist, genre, score)` edge into both genre members and artist genres;
recompute `member_count` after export filtering rather than copying `size`. The M1 artist catalog
supplies names/listener counts. M2 has no positions, colors, genre similarity or previews: leave
those null until a producing stage supplies them, never derive coordinates from local indices.

All positions are normalized `[0,1]`, x increases rightward, y downward; artists and genres share
the frame within each layout. Axes metadata supplies the labels at each end (normally x: dense/
atmospheric to spiky/bouncy; y: mechanical/electric to organic). Islands are a separate embedding
with a named method, not sonic axes or a replacement for ranked similarity. Display collision
offsets never overwrite these model coordinates. Colors are `#RRGGBB` or null, not another score.

Manifest layout/method null means that capability is unavailable release-wide. A record can
still lack a position or model result when the capability exists: null means unknown/not computed;
an empty list means computed with no results, and zero is a measured zero. Never substitute a
synthetic point, member or neighbor for missing data. Lists sort by descending score then ID;
scores are strengths within their named model, not calibrated probabilities or comparable across
models/releases. Member counts count the full member list; listener counts count distinct training
listeners. Null counts are not zero. Embedded summaries must equal their canonical detail.

Preview locators identify a Deezer/iTunes track; clients fetch current playable URLs at runtime
and handle unavailability. Releases contain no audio, signed media URLs, raw reference datasets,
training matrices or embeddings. Load only manifest/indexes initially and detail shards on selection;
PMTiles and larger search/pagination formats can be added with a future schema version rather than
inventing a second entity model. This v1 validates complete unpaginated member lists. Publish
release directories atomically; the client pins one root and refuses unknown schema versions.
Change the version whenever a public shape or its meaning changes.

### UX study and direction

The Vite study in `web/` consumes the exact synthetic release in `tests/fixtures/catalog/`, not a
parallel mock model. TypeScript types are generated from the catalog schema on every check; the
loader validates every resource against that same schema, refuses unknown versions, and never
falls back to fixture data after a release fails. This is interaction exploration, not the M3 map.

- **One atlas, three lenses.** Islands for wandering, sonic axes for an audible frame of reference,
  tree for broad-to-specific navigation. Selection and field notes persist across views; each map
  retains its camera, and the tree retains collapsed branches. A URL carries the view and entity ID;
  browser back retraces exploration. Search highlights a chosen result, not an automatically fitted
  bounding box of every match. Unknown IDs get a recovery message rather than a guessed match.
- **Discover without guessing.** A genre opens field notes with a parent breadcrumb, ranked member
  artists and related genres. Artist notes show memberships, available signals, ranked similar
  artists and listening links. Keep model ranks distinct from map distance and never label strengths
  as confidence percentages. Null results say not computed; empty results say no published matches.
- **A quieter, more usable Every Noise.** Keep the scan-and-discover character, but separate selection
  from playback. A visible search, labeled view controls, keyboard-operable labels/tree, visible focus,
  responsive stacked notes and explicit axis labels replace tiny hidden arrow targets. No autoplay;
  a future preview control must expose loading, playing, unavailable and retry states, with one
  track playing at a time. The study deliberately has no pretend play button.
- **A discovery trail, not another feed.** Save interesting genres and artists in order, locally and
  per release, without an account or imported listening history. This works with existing IDs alone.
  The study caps trails at 50 stops and tolerates blocked storage. Shareable trails can encode IDs
  later; they must not imply persistent cross-release IDs without a migration policy.

Next experiments, after real data: compare two artists using shared memberships/neighbor-list
intersections; a user-stepped sound walk along published similar-artist edges; a “less familiar”
neighbor order using published listener counts. None needs an LLM or a recommendation API. Do not
ship semantic text-to-sound search, chronology, geographic origin or cross-genre bridge claims until
the pipeline actually publishes those signals. Test whether listeners can find a familiar artist,
switch lenses without losing context, reach an unfamiliar neighbor and explain why it was suggested.

The study uses SVG points and family envelopes, explicitly not density contours or geographic land.
At production scale, replace that renderer with MapLibre/PMTiles and zoom-dependent labels; keep
the selection, detail and identity contract. V1's full search/member arrays are suitable for the
study, not a measured 500k-artist latency claim; tiling, pagination and a search worker need the next
contract version and device/network measurements. Do not invent coordinates for sparse artists.

References: [Every Noise](https://everynoise.com/) supplies the sonic-axis and click-to-discover
baseline; [Wilson Lin's Hackerverse](https://blog.wilsonl.in/hackerverse/) supplies progressive
zoom/landmark inspiration. Islands are an embedding overview, not a substitute for ranked similarity.

## 8. Stack

- **Python 3.13, uv, Polars + DuckDB, Parquet.** This is the best tool fit for dumps, ALS, Leiden and
  UMAP. Rust or Elixir would add nothing here.
- **Modeling:** `implicit` (ALS), `leidenalg`/igraph, `umap-learn`, `hnswlib`, `essentia-tensorflow`
  (audio), `torch` only if we learn fusion.
- **Orchestration:** one CLI (`on ingest|build|eval|export|run`), with stages cached by input hash.
  No Dagster or Airflow.
- **Front end:** Vite + TypeScript + MapLibre. Tiles are built with `tippecanoe`.
- **Code:** a single flat package of ~10 modules matching section 4, no comments, ruff + ty, tests
  only for the identity crosswalk and eval math. Budget: under 5k lines of Python to reach M3.

## 9. Milestones

1. **M1 Listening graph.** Ingest MB + LB. Build the ALS artist embedding and similar artists for 200k
   artists. Measure similar_artist_ndcg and the probe list. *This decides the micro-genre ceiling.*
2. **M2 Genres.** Add ENAO-supervised membership, Discogs, MB tags and Leiden + naming for genres outside ENAO. First genre_match and member_recall
   against ENAO.
3. **M3 Map.** Add AcousticBrainz and preview embeddings for the axes. Ship islands + ENAO mode +
   artist pages.
4. **M4 Quality loop.** Tune fusion weights and resolution against eval. Add the tree view and
   Last.fm gap-fill.

## 10. Decisions for Robert (defaults in bold)

1. Use ENAO names and memberships as labels, with a held-out split for evaluation; **map coordinates
   are evaluation only**, never axis targets. Publish derived outputs, never the raw ENAO files.
2. Use the Last.fm API for gap-fill (non-commercial)? **Yes, derived scores only.**
3. Audio previews: compute embeddings locally from Deezer previews? **Yes, store embeddings only.**
4. Repo: archive the old `main` as `archive/v1` and start a fresh orphan `main`. **Yes.**
