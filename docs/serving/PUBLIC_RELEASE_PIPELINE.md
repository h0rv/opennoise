# Public release pipeline

`uv run poe release-certify` is intentionally closed while the semantic Canvas
map is local-research-only. It refuses to certify the retired production SVG;
re-enable it only with a publishable semantic artifact and the semantic Canvas
browser gate. It must fail closed if any source, model, map, renderer, or
browser evidence is missing or inconsistent.

It requires:

- `config/releases/phase3-public-20260831/release-manifest.json`
- the sealed cache passed with `--cache-database`
- Chromium at `/usr/bin/chromium`, Node, and the `opennoise` CLI

It never fetches a source, reads music or audio files, or calls a live data API.

The verified sealed cache in this checkout is
`.cache/listenbrainz-qualified-input/sha256/282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite`.
It is 153,231,360 bytes and has SHA-256
`282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866`.
The retained `.cache/release-certify` outputs are runnable evidence, not a
replacement for the sealed cache or a full source-to-publication rebuild.

## Command

```sh
uv run poe release-certify
```

When `data/phase3-public-qualified.sqlite` is absent, the command uses the
verified retained cache below automatically. Pass `--cache-database` only to
certify a different explicit cache.

The command verifies the sealed cache, materializes a serving database and
public model, builds the production map, writes acceptance evidence, starts a
local app with `OPENNOISE_PRODUCTION_MAP_PATH`, runs raw-CDP browser QA, and checks
the final evidence bundle.

Default outputs:

- `data/public.sqlite`
- `data/model/phase3-public-model.json`
- `data/release/phase3-public-receipt.json`
- `data/model/production-map-v1.json` and its acceptance, seed, browser, and
  final report sidecars under `data/model/production-map-v1*`
- `data/model/production-map-captures/`

The command accepts explicit path and port overrides:

```sh
uv run poe release-certify -- \
  --cache-database .cache/listenbrainz-qualified-input/sha256/282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite \
  --serving-database data/public.sqlite \
  --model-output data/model/phase3-public-model.json \
  --receipt-output data/release/phase3-public-receipt.json \
  --map-output data/model/production-map-v1.json \
  --acceptance-output data/model/production-map-v1.acceptance.json \
  --seed-report-output data/model/production-map-v1.seed-report.json \
  --browser-evidence-output data/model/production-map-v1.browser.json \
  --report-output data/model/production-map-v1.report.json \
  --captures-directory data/model/production-map-captures \
  --port 3001
```

The final report is the release decision. It names every input and derived
artifact by hash. A successful build does not authorize serving a different
database or map path.

`docs/ARTIST_MEMBERSHIP_EVALUATION.md` describes the optional, release-bound
artist-membership calibration evidence. It is deliberately not represented as
an independent production-quality claim until a suitable public gold set is
available.

## Serving

```sh
OPENNOISE_DATABASE_PATH=data/public.sqlite \
OPENNOISE_PRODUCTION_MAP_PATH=data/model/production-map-v1.json \
uv run poe dev
```

The application reads only local artifacts. Source adapters and object storage
are build-time concerns, not request-time dependencies.
