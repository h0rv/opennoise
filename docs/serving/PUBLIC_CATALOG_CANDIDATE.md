# Reproducible public-input catalog candidate

This separate candidate rebuilds the latest retained-catalog explorer from public
repository bytes. It does not restore the legacy semantic atlas, switch production,
or consume the privately delivered HTML, private annotations or benchmark results.
`poe build`, `poe deploy`, the Pages project and legacy promotion pins are unchanged.

The tracked input contract is
`config/releases/retained-public-catalog-inputs-v1.json`, SHA-256
`c2c749c5186abc42eb01ef73fb068915920cb86975729b5352277f0c87d902c8`.
All 174 members (5,382,545 bytes) were checked byte-for-byte against public commit
`3d99b97abf9ab9a533231adb8c64032f65ebc89b`. The contract lists each path, size,
digest, rights and permitted role:

- MusicBrainz's approved portable core recording/credit projection: CC0 metadata
  examples, without supplementary genres, artwork, preview URLs or audio. Original
  HTTP response custody is not claimed for this safe projection.
- Both retained Wikidata packs: CC0 exact P434 identities, direct P136 claims and
  source labels. Repeated observations are deduplicated. Benchmark-neighbor files
  are integrity-bound pack members; they are not human judgments or model targets.
- Native AcousticBrainz numeric responses and separate exact MusicBrainz core
  credits: CC0. Missing outcomes and extractor versions remain explicit. Uploader
  tags are not projected. Project documentation and license-review testimony are
  MIT, separately identified from provider data.
- The unchanged MIT AB178 crossfit protocol: fixed per-version frames, original
  component folds, abstentions and credit checks; no threshold tuning or new fit
  selection. Its frozen output manifest is checked before lifting recording links.

## Build and verify

After `poe sync`, from Python 3.13.14 with the locked dependencies:

```sh
.venv/bin/python scripts/build_public_catalog_candidate.py build --output .cache/public-candidate
.venv/bin/python scripts/build_public_catalog_candidate.py verify --output .cache/public-candidate
poe dev --directory .cache/public-candidate/site --port 3001
node scripts/capture_retained_catalog_demo.mjs http://127.0.0.1:3001 .cache/public-candidate-browser
```

Output must be fresh under checkout `.cache`. Source paths cannot traverse symlinks
or escape the checkout. Every declared source byte is checked before building;
closed pack verification rejects extra source members. No network acquisition is
implemented. Verification checks the closed static inventory and independently
rebuilds from the input contract, so rewriting payload hashes cannot bless forged
facts. The CLI keeps the existing one-thread, 120-second CPU/wall and 1 GB limits.

`site/` is the only proposed serving directory: HTML, modules, styles and source
projections. The fresh replay databases, routing artifacts and engineering reports
remain outside it. `payload-manifest.json` records all source bindings, runtime,
all implementation-tree/migration/locked-environment hashes and every static payload
member's size and SHA-256. These direct code digests include the delegated builder;
the data source commit is separate from implementation identity. It explicitly
sets `publication_authorized: false`; this candidate requires release audit before
any production selection. No generated payload or private benchmark is committed
or uploaded by the workflow.

## Exact scope

| Layer | Artists | Recordings |
| --- | ---: | ---: |
| Metadata catalog | 433 | 1,031 |
| Descriptor-bearing source | 17 | 55 |
| Strict extractor-compatible source | 13 | 34 |
| Held-out queries emitting suggestions | 6 | 11 |

The union contains 440 artist identities and 1,086 recordings. There are 151
observed genre labels, 78 artists with direct claims and 72 with shared-genre
links. Every identity remains reachable, including unplaced artists. The acoustic
cohort is electronic/ambient-heavy. Source links and acoustic suggestions are
separate; graph drawing arranges links and carries no perceptual-distance claim.
Coverage and reproducibility do not establish musical relevance or EveryNoise
parity. No audio playback is offered.

Tests copy only repository implementation code, migrations and the declared public
inputs into a clean root, deny socket connections, build under two hash seeds and
compare every payload byte. They also reject changed inputs and rehashed forged
outputs. CI repeats source checks, candidate reconstruction and desktop/mobile
browser checks without credentials. The production job still uses the old sealed
release and cannot select this candidate.

Existing CI deployment credential availability remains unverified; no secret read
was retried and no credentials were created. That connection issue is separate
from this now self-contained candidate data/build path.
