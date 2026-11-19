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

## Build the current pipeline

Keep the cached `data/`, `runs/` and `data/registry/genres.json` used by the configs.
Sources are listed in `sources.toml`. Configs reference existing artifacts rather than
automatically rebuilding dependencies.

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

Pages downloads the prebuilt catalog; `.github/workflows/pages.yml` defines deployment.

## Tests

```sh
uv run pytest
npm --prefix web test
npm --prefix web run build
```

## Experiments

Raw numbers and variant-level outcomes: [experiments/results.tsv](experiments/results.tsv).
“Adopted” means used by the current pipeline, not every historically kept variant.

| Idea | Outcome |
|---|---|
| TF-IDF and implicit ALS | Adopted: TF-IDF supplies the graph; ALS supplies layout vectors. |
| Leiden resolution variants | Adopted fine, three-resolution clustering for discovery. |
| MusicBrainz tag naming | Rejected for release naming in favour of Wikidata and Discogs. |
| Discogs style naming | Adopted weighted naming; strict and lift-only variants lost selection. |
| Wikidata-only vs combined naming | Adopted Wikidata-weighted Discogs combination for better naming scores. |
| MusicBrainz tag reranking | Replaced by Discogs style reranking in the release. |
| Discogs style reranking | Adopted at weight 0.1; improves hidden-label neighbour agreement. |
| AcousticBrainz audio | Adopted with ALS for Map and Islands vectors. |
| Discogs-EffNet preview audio | Not adopted in the release; non-commercial model, disabled by default. |
| Place + style micro-genres | Adopted to add geographically specific genres. |
| Layout variants | Adopted audio-oriented, rank-spread UMAP with repulsion; separate spectral Islands. |
| Cosine-related genres | Adopted: related lists use vectors rather than screen distance. |
| Last.fm-360K/1K listening blend | Rejected: tiny similarity gain, worse genre naming; non-commercial. |
| Echo Nest Taste Profile | Rejected: low artist coverage, every score lower; research-only terms. |
| MusicBrainz artist relationships | Rejected: genre-graph blend recovered only 4 more of 868 Every Noise genres at best. |
| ListenBrainz session similarity | Rejected: fusion with TF-IDF gave a small Every Noise gain but a lower Wikidata score. |
| Discogs labels and co-credits | Rejected: no measurable reranking gain; dilutes styles. |
| Deezer related artists and album genres | Rejected for release: plateaued; non-commercial terms, opt-in only. |
