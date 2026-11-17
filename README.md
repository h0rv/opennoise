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

M2b reuses the kept fine-k20 clusters and split, comparing MusicBrainz naming with CC0
Discogs styles ingested by the tag experiment. MusicBrainz names are evaluation-only.
The current tag cache reuses that session's completed MBID-to-styles Parquet; ingest skips it.

```sh
uv run on ingest configs/tags.toml
uv run on build configs/m2b.toml
uv run on eval configs/m2b.toml
uv run on export configs/m2b.toml
```

The lift variant requires three supporting artists and lift >= 1.25 against the parent
plus child artists outside it. Weighted variants normalize log release counts per artist,
weight artists by log listener count, and rank style share times global IDF times log(1+lift).
The strict variant requires five artists and lift >= 2. Exact/token naming agreement uses
the 210 matched genres; name@3 uses all 868 held-out genres, including unmatched ones.
Named-cluster share includes all discovery levels. Selection maximizes name@3, then exact
agreement, among Discogs variants only. All split results remain in the evaluation run.

Final files live separately in `runs/<M2b hash>/export/`. Membership is refit on every
eligible genre and all its mapped graph artists, without either holdout. Only supervised
ENAO labels and Discogs-named clusters are exported; unnamed clusters stay internal and
parent links skip excluded ancestors. No MusicBrainz-tag names enter this export.

M2c adds Wikidata P434/P136 statements, English labels/aliases and P279 links via QLever (CC0).

```sh
uv run on ingest configs/m2c.toml
uv run on build configs/m2c.toml
uv run on eval configs/m2c.toml
uv run on export configs/m2c.toml
```

Queries cover all MBID/P136 links, plus genre classes/instances and the linked genre targets.
Raw responses, normalized tables and coverage stay in `data/m2c/`; truncated responses fail.
Response hashes record this live-endpoint snapshot.
Wikidata-only naming uses English labels. Combined variants normalize each source per artist
before mixing; unambiguous Discogs label/alias matches reinforce the same Wikidata genre.
Other styles remain separate CC0 candidates. Alias variants prefer the most frequent matching
Discogs spelling, without consulting ENAO names. Selection maximizes exact + name@3 among
CC0 variants, including the kept M2b baseline. The unchanged split supplies every quality metric.
Export reuses M2b's cached all-label supervised memberships and rebuilds only named discovery
memberships and parent links. No membership refit or contract adaptation is performed.

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

Tag experiments reuse the cached M1 run named in `configs/tags.toml`:

```sh
uv run on ingest configs/tags.toml
uv run on build configs/tags.toml
uv run on eval configs/tags.toml
```

MusicBrainz artist tags and exact Discogs artist links come from its artist JSON dump; Discogs
styles count main-artist release credits. Outputs include `artist_tags.parquet`, aligned sparse
TF-IDF vectors and vocabularies, coverage, probes, and `similar.parquet`. Tags only rerank the
existing M1 top-50 candidates. Weights are selected on half the held-out users; the untouched
half compares only the selected method and baseline. Labs overlap@50 cannot change in this test.

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

M3 composes micro-genre names from a place (MusicBrainz areas, Wikidata demonyms) and a style
(Wikidata, Discogs, suffixes of visible ENAO names), with members scored from listening
neighbours and that evidence. A second model, cross-fitted on visible genres, ranks which
composed names are real genres. It needs the M2 and M2c ingests.

```sh
uv run on ingest configs/m3.toml
uv run on build configs/m3.toml
uv run on eval configs/m3.toml
```

`runs/<hash>/` holds `genres.parquet`, `memberships.parquet` and `related.parquet` (nearest
genres by shared listening). `threshold` and `negative_weight` were picked on the hidden genres.
