# MusicBrainz artist relationships

Core dump: `20261114-002230/mbdump.tar.bz2`, pinned in `sources.toml`.
M1 catalog: `runs/1f242e47ed38`, 270,773 artists. The original M1 graph is unchanged.

## Method

`configs/m2-relations.toml` opts into core artist-artist relationships. M2 ingest
extracts `l_artist_artist`, `link`, and `link_type` alongside the existing core
tables on a fresh cache. `data/m2/relations.done` independently tracks extraction;
existing reference caches need only the missing tables. Numeric MusicBrainz artist
IDs are mapped through artist MBIDs to M1 items at both endpoints.

The cache is tied to this M1 item mapping: use a different cache path when changing
the M1 catalog. `data/m2/relations.parquet` contains unique directed typed pairs,
excluding self-edges; `relations.json` contains per-type counts and coverage.
Relationships with unmapped endpoints are excluded, with no bridging through
unmapped artists. Ended relationships are included.

The blend is `G + weight * A` after TF-IDF symmetrization, before row normalization.
`A` is binary, symmetric, and loop-free: multiple relation types or repeated rows
do not multiply a pair's weight. Omit `[relations]` or set `weight = 0` to retain
the original graph without reading a relationship cache. Optional `types` selects
exact MusicBrainz relationship names; omission selects all types.

All comparisons use `fine_k20`: k=20, one propagation hop, Leiden resolutions
256/1024/4096, unguided. Seed 42, the same 868 entirely held-out Every Noise
genres, and the same 20% hidden members of training genres are retained.
Every Noise coordinates are not model inputs. Existing MusicBrainz tags still
name clusters under their existing noncommercial terms; the new relationship
signal uses CC0 core data, not tags. No new training stage reads Wikidata P136.

Weights 0.1, 0.3, and 1.0 were preset. The subset uses member of band,
collaboration, is person, supporting musician, instrumental supporting musician,
vocal supporting musician, subgroup, and artist rename. Selection is by Every
Noise genre match, then membership AP. Wikidata is diagnostic, not used to pick
the weight. The default configs and the original graph remain unchanged.

## Reference snapshot

Wikidata ingest completed without rate limiting: 186,978 rows, 132,304 artists,
2,248 genres. Music-hierarchy restriction succeeded. SHA-256:
`9ed643ab3b78f4678baac30e2f0979871b6a843cc5bb96b66b17462c339d71c0`.

M2's sealed check covers 6,596 artists and 262 eligible Wikidata genres; the
sealed-independent slice covers 750 artists and only 27 eligible genres.
The latter is coarse: one recovered genre changes its match rate by 3.70
percentage points. Existing deterministic artist sealing is unchanged.

## Relationship inventory

57,053 directed typed pairs have both endpoints in M1. They cover 61,718 artists
(22.793%). Dump rows count original relationships; mapped pairs are deduplicated
by endpoints and type, before the graph collapses types and directions.

| Type | Dump rows | Mapped typed pairs |
|---|---:|---:|
| member of band | 663,636 | 41,608 |
| is person | 76,243 | 3,054 |
| collaboration | 9,436 | 1,916 |
| voice actor | 11,783 | 1,847 |
| conductor position | 7,163 | 1,242 |
| parent | 15,915 | 1,111 |
| sibling | 15,436 | 1,008 |
| married | 9,898 | 842 |
| teacher | 29,511 | 809 |
| founder | 8,187 | 687 |
| instrumental supporting musician | 6,084 | 593 |
| subgroup | 3,713 | 576 |
| involved with | 1,826 | 448 |
| vocal supporting musician | 2,333 | 402 |
| supporting musician | 2,701 | 301 |
| artist rename | 2,130 | 251 |
| named after artist | 1,009 | 145 |
| tribute | 3,073 | 97 |
| artistic director | 1,310 | 94 |
| composer-in-residence | 235 | 21 |
| artist-in-residence | 9 | 1 |
| personal relationship | 0 | 0 |
| musical relationships | 0 | 0 |

## Results

All values are fractions, not percentages. Median Jaccard in the first table is
Every Noise's. Membership recovery hides members of training genres, whereas
genre match measures entirely held-out genres.

| Variant | EN genre match | EN median Jaccard | Member recall | Member AP | WD sealed match | WD sealed-independent match |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0.241935 | 0.131827 | 0.303405 | 0.134392 | 0.374046 | 0.444444 |
| all types, 0.1 | 0.246544 | 0.128619 | 0.304882 | 0.134925 | 0.393130 | 0.444444 |
| all types, 0.3 | 0.247696 | 0.136364 | 0.304321 | 0.134417 | 0.381679 | 0.407407 |
| all types, 1.0 | 0.232719 | 0.133333 | 0.287317 | 0.119217 | 0.377863 | 0.444444 |
| subset, 0.3 | 0.243088 | 0.133333 | 0.303506 | 0.134114 | 0.381679 | 0.407407 |

| Variant | WD sealed median Jaccard | WD sealed-independent median Jaccard | M2 run | Gen run |
|---|---:|---:|---|---|
| baseline | 0.154701 | 0.166667 | cdf51bf5da7d | 6be2edc63995 |
| all types, 0.1 | 0.166667 | 0.166667 | 183bfd78189f | 0fc9da408c84 |
| all types, 0.3 | 0.162167 | 0.166667 | 7fac3e24ecbd | 572d587627fd |
| all types, 1.0 | 0.164729 | 0.166667 | c05b5a4e862b | f4a3ef1fa44f |
| subset, 0.3 | 0.153846 | 0.166667 | 899bbb7351fe | 0df20c1e8a06 |

The baseline built all four original variants; its best was `fine_k20`.
All-types 0.3 wins the preset Every Noise criterion: 215/868 recovered genres,
versus 210/868 for baseline (+0.576 percentage points). Increasing the weight to
1.0 reverses the gain and harms membership recovery, so the search stops here.
The subset does not improve on all types. Weight 0.1 has the best sealed result,
but that diagnostic is not used to select a weight.

The outcome is a small, mixed gain, not evidence of a broad improvement:
all-types 0.3 improves sealed match from 98/262 to 100/262, but loses one
independent genre (12/27 to 11/27). No significance or multi-seed test was run.
The feature stays off by default; no existing config is promoted or overwritten.
The final comparison rows mark 0.3 kept and the alternatives discarded; earlier
append-only rows record the best available candidate at that point in the run.

The core/reference ingest took about 16 minutes; the original four-variant
baseline took about 21 minutes. Fine-k20 candidate builds took 4–5 minutes each
and were overlapped with baseline work. No disk, memory, or QLever blocker arose.
Final validation: Ruff check, Ruff format check, ty check, and 143 pytest tests
passed. No UI/layout changes or visual checks were involved.

## Reproduction

Restore the five supplied M1 artifacts to `runs/1f242e47ed38/` first. Ingest the
relationship config before the baseline to extract all core tables in one pass.
The baseline uses `configs/m2.toml` without modifications.

```sh
uv run on ingest configs/m2-relations.toml
uv run on ingest configs/gen.toml
uv run python experiments/mb_relations.py baseline
uv run python experiments/mb_relations.py 0.1
uv run python experiments/mb_relations.py 0.3
uv run python experiments/mb_relations.py 1.0
uv run python experiments/mb_relations.py 0.3 --types \
  'member of band' collaboration 'is person' 'supporting musician' \
  'instrumental supporting musician' 'vocal supporting musician' \
  subgroup 'artist rename'
```

The two ingests can run concurrently. The runner creates separate hashed configs
under `runs/mb-relations/`, builds/evaluates M2, points gen at the actual M2 run,
and appends comparative kept/discarded rows through the existing logger. It sets
thread limits for subprocesses and reuses completed build/evaluation caches.
Retain `data/gen/` to reproduce this live-endpoint reference snapshot exactly.
Summary JSON files include full metrics and run IDs. No naming, layout, or M3
artifacts are needed for the M1/M2-only generalization configs it generates.
M1 generalization uses unchanged TF-IDF edges; relation-fused M1 edges were not tested.
