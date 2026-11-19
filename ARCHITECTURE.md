# Architecture

## Offline pipeline

`src/opennoise/cli.py` dispatches config-driven stages. Intermediate tables and models
live in `data/` and `runs/`; configs explicitly reference their dependencies.

- **Listening** — `ingest.py` reads ListenBrainz counts and MusicBrainz artist data.
  `graph.py` builds TF-IDF cosine neighbours and implicit ALS vectors.
  `tags.py` reranks listening candidates with Discogs styles.
- **Genres** — `reference.py` maps Every Noise labels to graph artists.
  `genres.py` propagates memberships and runs multiresolution Leiden clustering.
  Evaluation holds out genres and artist memberships; export refits on all eligible labels.
- **Names** — `wikidata.py` and `naming.py` combine Wikidata genres with Discogs styles.
  `micro.py` scores place-and-style combinations and their artist memberships.
- **Geometry** — `audio.py` aggregates AcousticBrainz descriptors by artist.
  `layout.py` combines normalized ALS and audio vectors.
  `sonic.py` fits cosine UMAP, orients it toward audio descriptors, ranks axes and
  applies frozen density-repulsion fields. Islands uses a separate spectral UMAP fit.
  `placement.py` applies saved transforms to catalog artists and genres.
- **Catalog** — `catalog.py` exports JSON with stable genre IDs, hierarchy, memberships,
  coordinates, similar artists and vector-based related genres.
  `data/registry/genres.json` persists genre IDs between builds.
  `contract.py` validates the catalog against `catalog.schema.json`.

## Browser and deployment

The Vite/TypeScript app in `web/` loads a static catalog through `src/data.ts`.
Map and Islands share selection state. Deezer previews are fetched on demand by
`src/preview.ts`. The catalog contains no preview audio.

`VITE_CATALOG_URL` selects a catalog manifest; development defaults to the synthetic
fixture. Pages builds the frontend, downloads the configured release and uses
`src/opennoise/pages.py` to prepare the deployed catalog.

## Evaluation

`evaluate.py` scores held-out listening users; `genres.py` scores hidden genre
recovery and memberships. `generalization.py` evaluates held-back Wikidata labels.
`layout_metrics.py` measures layout neighbours, and `extrapolation.py` evaluates
recent artists. Results are recorded in `experiments/results.tsv`.
