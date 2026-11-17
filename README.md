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
