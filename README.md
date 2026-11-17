# OpenNoise

An open Every Noise at Once: a genre map and similar artists built from open data.

M1: listening graph with TF-IDF cosine and tuned implicit ALS; held-out and labs evaluation.

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
