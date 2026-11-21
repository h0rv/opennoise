# OpenNoise

A music genre map and similar-artist explorer inspired by Glenn McDonald’s
[Every Noise at Once](https://everynoise.com/). Listening data, audio descriptors and
genre labels feed an offline Python pipeline; a TypeScript site displays the catalog.
Every Noise genre names and artist memberships are training labels.

## Setup

Requires Python 3.13+, uv and Node.js 22.

```sh
uv sync
npm --prefix web ci
npm --prefix web run dev
```

Development uses a synthetic fixture by default. Set `VITE_CATALOG_URL` to a catalog’s
`manifest.json` to use model output.

## Pipeline

TF-IDF listening neighbours are reranked with Discogs styles. Label propagation and
multiresolution Leiden supply genres; Wikidata-weighted Discogs naming and place-and-style
micro-genres name them. Naming and catalog exports reuse the cached all-label membership
fit. ALS and AcousticBrainz vectors drive the 2D map, spectral Islands and related genres.
Discogs master styles missing from Every Noise and OpenNoise are eligible as standalone
genres when at least five positioned artists have two or more master credits each.
They use the same non-music exclusions as place-and-style genres, then use the saved
map and shared catalog naming without refitting existing genres.

## Reproduce

Pages builds the site and packs the GitHub release selected by `CATALOG_RELEASE` in
[pages.yml](.github/workflows/pages.yml). To serve the same catalog locally after setup
(requires GitHub CLI and zstd):

```sh
catalog=$(awk '/^  CATALOG_RELEASE:/ {print $2}' .github/workflows/pages.yml)
gh release download "$catalog" -R h0rv/opennoise --pattern "release-$catalog.tar.zst"
tar --zstd -xf "release-$catalog.tar.zst"
npm --prefix web run build
rm -rf web/dist/catalog
uv run python src/opennoise/pages.py release web/dist/catalog
npm --prefix web run preview -- --host 127.0.0.1
```

To rebuild, retain the caches in `data/` and `runs/`, including `data/registry/genres.json`;
sources are listed in `sources.toml`.

```sh
uv run on build configs/tags.toml
uv run on eval configs/tags.toml
uv run on build configs/m2f-naming.toml
uv run on eval configs/m2f-naming.toml
uv run on export configs/m2f-naming.toml
uv run on build configs/m3.toml
uv run on audio configs/audio.toml
uv run on layout configs/layout.toml
uv run on export configs/m2f.toml
uv run on layout configs/m2e-layout.toml
uv run on export configs/one-name.toml
npm --prefix web run build
```

To extend a named model catalog with Discogs master styles, run the source ingestion
below and use its output run. Use a trusted layout bundle containing `sonic_model.pkl`,
`sonic_state.npz`, and the matching M1 `artists.parquet` in vector order.
Use the pinned Every Noise `map.html` and `enao.json` in `data/m2`.

```sh
uv run on ingest configs/discogs-masters.toml
uv run python -m opennoise.discogs_styles release "$release_id" "$tags_run" "$layout_bundle"
uv run python -m opennoise.contract release
```

Compare the input and output with `opennoise.genre_order` using the same
Wikidata and Every Noise references before publishing.

## Tests

```sh
uv run pytest
npm --prefix web test
npm --prefix web run build
```

## Experiments

Rejected or not adopted; raw numbers are in [experiments/results.tsv](experiments/results.tsv).

- **Listening blends:** Last.fm-360K/1K gave tiny similarity gains but worse naming
  (non-commercial); Echo Nest Taste Profile had low coverage and lowered every score
  (research-only). These were run in earlier sessions outside the ledger.
- **Extra graph signals:** MusicBrainz relationships recovered at most 4 more of 868 genres;
  ListenBrainz session fusion slightly improved Every Noise but lowered Wikidata scores;
  Discogs labels/co-credits gave no measurable gain and diluted styles.
- **Naming:** MusicBrainz tags, strict/lift-only Discogs (`configs/m2b.toml`) and Wikidata-only
  or equal-weight naming (`configs/m2c.toml`) lost to weighted combined naming. The sealed
  artist-label variant is retained in `configs/map-labels-naming.toml` for comparison.
- **External audio/catalogs:** Deezer related artists and album genres plateaued, with
  non-commercial, opt-in terms (`configs/deezer.toml`); EffNet preview audio uses a
  non-commercial model and stays disabled (`configs/audio.toml`).
- **Layouts and labels:** Earlier map variants lost neighbour retention (`configs/layout.toml`);
  readable labels without global name grouping remain a comparison (`configs/map-labels.toml`).
  `configs/gen.toml` runs the cross-source and layout comparisons.
