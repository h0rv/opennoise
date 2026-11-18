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

M2d adapts that export and M1's TF-IDF top-50 into contract-v1 JSON:

```sh
uv run on export configs/m2d.toml
uv run python -m opennoise.contract runs/<hash>/release
```

Preserve `data/registry/genres.json` across builds: this persisted identity registry includes
member MBIDs and retired IDs, and is not shipped in the release. Supervised keys are canonical
ENAO names; cluster keys combine the fixed resolution namespace with a sorted-member hash.
Display names and local cluster indices never regenerate an assigned slug. Later clusters reuse
IDs at Jaccard >= .8 within the same namespace, one-to-one; contained splits get fresh IDs,
merges keep the best-overlap ID and retain prior names as aliases. Retired IDs are never minted
again. The adapter checks supervised edges against cached model predictions and audits training
labels locally, without touching the evaluation split. Public strengths are unchanged, MBIDs
replace item indices, and missing layouts/genre similarities/previews stay null. Output is
staged then renamed to `runs/<hash>/release/`; cached reruns verify IDs and input hashes.

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

### Curated tracklist experiment

The [MusicBrainz core dump](https://musicbrainz.org/doc/About/Data_License) (CC0) supplies
released DJ mixes and compilations as a proxy for user playlists. The experiment uses one
official edition per release group, deduplicates identical artist sets, and keeps lists with
3–60 artists in the listening graph. If a group is both a DJ mix and a compilation, it counts
as a DJ mix. Pairs that share at least two lists get a bonus of 0.25 times their tracklist
cosine similarity; longer lists count less. The bonus can reorder the listening graph or add
playlist-only neighbors. Neither Every Noise labels nor coordinates enter the graph.

Reuse the M1 run and M2 reference tables, and run `uv run on ingest configs/gen.toml` for the
Wikidata reference. Use the MusicBrainz core archive pinned in `sources.toml`:

```sh
echo 'da4f1afcbca8ca54eb6362ae45173543f079e8491d097a376d060551d1a03335  mbdump.tar.bz2' | sha256sum -c -
mkdir -p data/playlists
tar -xjf mbdump.tar.bz2 -C data/playlists \
  mbdump/{artist,artist_credit_name,medium,release,release_group_secondary_type,release_group_secondary_type_join,release_status,track}
uv run python experiments/playlist_signal.py baseline
uv run python experiments/playlist_signal.py dj-mix --tables data/playlists/mbdump
uv run python experiments/playlist_signal.py compilation --tables data/playlists/mbdump
```

The JSON in `runs/playlist-signal/` compares the same unsupervised M2 cluster settings on the
held-out Every Noise genres and the sealed Wikidata artists. A cluster matches a genre
when the sets of artists have at least 20% intersection over union. The independent Wikidata
slice excludes genres with an Every Noise ID. Nothing in the release reads these outputs.

Not used: [ListenBrainz](https://github.com/metabrainz/listenbrainz-server/blob/master/listenbrainz/dumps/tables.py)
has CC0 listen dumps but leaves playlists out of its public exports; [Spotify's Million Playlist
Dataset](https://www.aicrowd.com/challenges/spotify-million-playlist-dataset-challenge) is
noncommercial and cannot be redistributed. [Playlist2vec](https://zenodo.org/records/5002584)
is labeled CC BY 4.0 by the uploader, but upstream Spotify data rights were not verified.
[Art of the Mix](https://brianmcfee.net/data/aotm2011.html) has no stated license on its download page.

## Atlas UX study

```sh
npm --prefix web ci
npm --prefix web run dev
```

The study uses the shared synthetic catalog fixture, not model results. Islands, sonic map and
tree share one selection; field notes link genres and artists, and a trail saves stops locally.
Set `VITE_CATALOG_URL` to a release's `manifest.json` to use its data (cross-origin hosts need CORS).
`npm --prefix web run lint` and `npm --prefix web run build` check formatting, regenerate types
from the pipeline schema, type-check and build a static site. Clicking a genre or artist looks up
a 30-second Deezer preview on demand; nothing is stored in the catalog. Deezer's
[terms](https://developers.deezer.com/termsofuse) restrict this to non-commercial, private listening.

Audio experiments reuse the M1 run named in `configs/audio.toml`:

```sh
uv run on audio configs/audio.toml
```

The audio stage aggregates AcousticBrainz low/high-level descriptors per artist and embeds Deezer
preview clips with Discogs-EffNet (CC BY-NC-ND), keeping only vectors. Each signal is scored on
the artists it covers against `audio.listening_run`: AUC of listening neighbors vs random
artists, overlap@10, held-out co-listening of the audio graph, and reranking the listening top-100.
EffNet previews are off by default (`audio.effnet = true` enables them) because the model is
noncommercial.

`layout` uses fixed AcousticBrainz dance axes with cosine-weighted ALS fill (k=10) for missing audio.
Genres use log-listener means; artists share their rank transform. ENAO coordinates are evaluation only.
Islands use spectral UMAP on `als_2+audio_ab_all`. Run `audio` before `layout`.

M3 composes micro-genre names from a place (MusicBrainz areas, Wikidata demonyms) and a style
(Wikidata, Discogs, suffixes of visible ENAO names), with members scored from listening
neighbours and that evidence. A second model, cross-fitted on visible genres, ranks which
composed names are real genres. It needs the M2 ingest and the M2f naming ingest, whose Wikidata
vocabulary is filtered to music genres. `non_music` in `configs/m3.toml` lists Discogs non-music and
video styles (interview, audiobook, music video) that are dropped from the style candidates.

`micro` in a catalog config names an M3 run whose genres are appended to the clusters as the
`micro` level. To place them on the map, export `configs/m2f.toml`, run
`uv run on layout configs/m2e-layout.toml` on that run, then export `configs/one-name.toml`,
which reads the placement run as `layout`.

```sh
uv run on ingest configs/m3.toml
uv run on tune configs/m3.toml
uv run on build configs/m3.toml
uv run on eval configs/m3.toml
```

`runs/<hash>/` holds `genres.parquet`, `memberships.parquet` and `related.parquet` (nearest
genres by shared listening). `uv run on tune configs/m3.toml` scores the `[grid]` of `threshold`
and `negative_weight` on a fifth of the visible genres; the hidden genres are never used to pick
settings. Sealed artists' Wikidata genres are dropped, so the `[m3]` entry in `configs/gen.toml`
scores a run on them.

`micro` in `configs/one-name.toml` names an M3 run: the catalog export appends its genres to the
clusters as the `micro` level, skipping names a cluster or supervised genre already has and aliases with identical
members, with a parent where the style is a supervised genre.
