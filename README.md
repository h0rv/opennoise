# OpenNoise

An open Every Noise at Once: a genre map and similar artists built from open data.

M1: listening graph with TF-IDF cosine and tuned implicit ALS; held-out and labs evaluation.

M2: ENAO-supervised propagation and multiresolution Leiden, evaluated on entirely unseen genres.

```sh
uv run on ingest configs/m2.toml
uv run on build configs/m2.toml
uv run on eval configs/m2.toml
```

M2 reuses `runs/1f242e47ed38/`; no M1 recomputation. Its reference files and crosswalk
stay under `data/m2/`. Each variant writes derived `genres.parquet`, `memberships.parquet`,
metrics and probes under its run directory. The best variant maximizes held-out genre match,
then membership AP. Membership output keeps ten positive train-genre predictions per artist
plus one discovered cluster per level. No hidden-genre membership labels enter training.
Artist hit@5 measures whether any hidden train-genre label appears in the five predictions,
excluding visible labels. Recall uses the full genre size as its cutoff; AP ranks positive scores.
Parents are maximum-overlap clusters at the previous resolution, not strictly nested partitions.
Naming lift uses that parent plus child artists outside it, with three supporting artists minimum.
MusicBrainz tags carry CC BY-NC-SA terms; these named outputs are not asserted to be CC0.

```sh
uv sync
uv run on ingest configs/m1.toml
uv run on build configs/m1.toml
uv run on eval configs/m1.toml
```

Artifacts are cached in `data/` and `runs/<config hash>/`. The graph uses 90% of users;
the other 10% are evaluation-only, including catalog filtering. `artists.parquet` maps graph
item indices to MBIDs and names. Each method's Parquet contains ranked top-50 neighbors.
`best.json` selects by held-out nDCG@50. Metrics and probe names live beside it; the
tracked experiment table includes every method, including failed builds.

Labs overlap is intersection size divided by k, averaged over nonempty API responses;
coverage and errors are reported separately. Its popularity strata each contribute 100 seeds.
The labs graph can share listening data with this snapshot: agreement is not an independent test.

## Atlas UX study

```sh
npm --prefix web ci
npm --prefix web run dev
```

The study uses the shared synthetic catalog fixture, not model results. Islands, sonic map and
tree share one selection; field notes link genres and artists, and a trail saves stops locally.
Set `VITE_CATALOG_URL` to a release's `manifest.json` to use its data (cross-origin hosts need CORS).
`npm --prefix web run lint` and `npm --prefix web run build` check formatting, regenerate types
from the pipeline schema, type-check and build a static site. No preview playback is connected yet.
