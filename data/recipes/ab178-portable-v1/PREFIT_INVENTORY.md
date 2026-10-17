# Pre-fit native compatibility inventory, 2026-10-17

The new offline inventory closes an intake visibility gap: a caller can assess
compatible source yield before choosing a cohort or running any fit. It requires
external source-receipt and feature-contract pins, replays the complete native
custody verifier, and preserves every nominated exact recording ID, credit,
extractor/configuration and rejection state. It reports coordinate observation
counts for the supplied contract and separately lists clean identity-verified
version/configuration cohorts. It never combines those cohorts or selects a fold.
The supplied contract is frozen before the inventory, rather than chosen by it.

This executor has the checked-in `data/examples/native-sonic` pack, not the old
local numeric bank. A fresh replay of these approved inputs found 100 nominations:
12 joined, 21 dirty extractors, 22 version mismatches and 45 explicit HTTP 404s.
Each of the 178 coordinates is observed in all 12 joined records. Six separate
clean identity-verified cohorts contain 12, 9, 7, 3, 2 and 1 records. These are
source/configuration counts, not supported retrieval or independent musical truth.
No fit, threshold change, FMA mapping, audio acquisition or human judgment occurred.

One official homepage access attempt on this executor failed at the proxy CONNECT
stage with HTTP 403 (`curl: (56) CONNECT tunnel failed, response 403`). No origin
body was received. The attempt stopped there; no alternate route, retry, API
acquisition or paid service was used. Fresh upstream source yield is therefore
zero; this report adds no recordings to the checked-in pack.

Reproduce from repository root after `poe sync`:

```sh
.venv/bin/python scripts/inventory_ab178.py \
  --source data/examples/native-sonic \
  --source-receipt-sha256 "$(sha256sum data/examples/native-sonic/receipt.json | cut -d ' ' -f1)" \
  --contract data/recipes/ab178-portable-v1/pilot-contract.json \
  --contract-sha256 "$(sha256sum data/recipes/ab178-portable-v1/pilot-contract.json | cut -d ' ' -f1)" \
  --output .cache/ab178-prefit-20261017
```

The output directory must be fresh and outside source custody. `inventory.json`
is deterministic and includes source, contract and implementation hashes; retain
its printed SHA256 externally. The CLI uses the portable pipeline's 120-second
CPU/wall and 1 GB address-space caps and bounded artifact publication. Numeric
features remain CC0 native source metadata; descriptive uploader tags and
MusicBrainz supplementary tags are not inventory inputs. No UI/export changes.
