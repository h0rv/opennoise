# Exported-release scorer (evaluation only)

Standalone packaging of the exact scoring calculations used by external
`shipping-score.py` and `layout-retention/score.py` for release `7822a8d03434`.
`shipping-finalize.py` only assembled the ledger/report; it did not compute scores.
No layout, fitting, placement, or ENAO-based tuning runs here.

## Run

From the repository root, using its existing `uv` environment:

```sh
uv run python scratch/release-scorer/score.py runs/7822a8d03434/release
```

The release directory may be anywhere. Only its `genres.json` and `manifest.json`
are read. To get the same before/after comparison, pass both extracted releases:

```sh
uv run python scratch/release-scorer/score.py \
  /home/ubuntu/sonic-embedding-experiment/live-798d8cc1645b/release \
  runs/7822a8d03434/release
```

If needed, obtain and extract the release archive separately:

```sh
gh release download 7822a8d03434 --pattern release-7822a8d03434.tar.zst
tar --zstd -xf release-7822a8d03434.tar.zst
uv run python scratch/release-scorer/score.py release
```

Expected after: Wikidata **0.38616714512524386**, EN overlap@10
**0.028695652173913046**, retention **0.41905797101449277** (41.905797%,
rounded to **41.91%**). Before: **0.3395809284892574**, **0.024879227053140097**,
**0.29207729468599036**. Output is one JSON object per release, with overall,
development and held-out metrics. Rendered-label counts are browser measurements,
not part of this scorer.

## Inputs

All evaluation references below are committed alongside the scripts; no other
run directory, artist table, model pickle, or external reference is needed to score.
Use `--references DIRECTORY` to override their location (default: beside `score.py`).

| File | Purpose |
| --- | --- |
| `pool.json` | Ordered 4,140 unique stable IDs and **original** evaluation names |
| `heldout-ids.txt` | 815 IDs, one per line; remaining 3,325 queries are development |
| `vectors.npz` | Frozen float64 ALS+audio genre vectors, in pool order (195 columns) |
| `map.parquet` | Exact `data/m2/map.parquet` snapshot, ENAO native x/y; scoring only |
| `members.parquet` | Original observed genre labels joined to artist MBIDs, deduplicated |
| `wikidata.parquet` | Exact small Wikidata artist/genre-QID reference (about 3.4 MiB) |
| Release `genres.json` | Exported axes coordinates matched **only by stable ID** |
| Release `manifest.json` | Release ID for reporting |

`sources.json` records SHA256 hashes and original paths of the preparation inputs.
No reference exceeds 50 MB; the complete bundled references total about 12 MB.
The vector archive is selected directly from the original experiment's
`layout-retention/inputs.npz`, not recomputed from the renamed release.

Five pool IDs became merged/artist-qualified children in the cleaned live release;
canonicalizing would yield 4,138 unique IDs. This scorer deliberately does **not**
canonicalize, filter, rename-match, or drop any of the original 4,140 rows. Missing
IDs are errors. There are 217 renamed pool rows in the cleaned release.

## Metric details

This preserves the original `Scorer` calculations: chunked SciPy `cdist`, stable
NumPy argsort, ten neighbors with self excluded, and one BLAS thread. All neighbor
candidates remain the complete 4,140 pool, including for the held-out query slice.
ENAO neighbors use Euclidean distance in native reference coordinates, while raw
ALS+audio neighbors use cosine distance. Release neighbors use Euclidean distance
in stored axes coordinates, **not tall-page screen space**. The reference data is
read only by evaluation code and never fed to a model or placement path.

Wikidata vectors count distinct original observed member artists by genre QID,
then L2-normalize. The score is mean cosine to ten release neighbors. This is not
a cosine of current published memberships. Random Wikidata averages all other
pool rows; random overlap and random retention are exactly `10 / 4139`.
Spread uses per-axis min/max normalization to a 10×10 grid, as in the experiment.

Packaging changes only path/CLI handling, freezes the original artist-label join
and vector rows, and removes unrelated model-reproduction assertions. Original
Wikidata aggregation and scoring arithmetic are retained.

## Rebuild frozen references (optional)

This needs the original preparation inputs; ordinary scoring does not:

```sh
uv run python scratch/release-scorer/freeze.py \
  --inputs /home/ubuntu/sonic-embedding-experiment/layout-retention/inputs.npz \
  --original-release runs/be8d557eda65/release \
  --labels data/m2/labels.parquet \
  --artists runs/1f242e47ed38/artists.parquet \
  --wikidata /home/ubuntu/sonic-generalization/reference/wikidata.parquet \
  --map data/m2/map.parquet
```

`be8d557eda65` supplies the original name-to-ID mapping only; it is **not** the
before baseline. `freeze.py --output DIRECTORY` can write a separate bundle.

Checks:

```sh
uv run pytest scratch/release-scorer/test_score.py
uv run ruff check scratch/release-scorer
uv run ruff format --check scratch/release-scorer
```
