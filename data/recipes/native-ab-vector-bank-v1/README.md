# Native AcousticBrainz recording vector bank

This offline bank expands the retained native CC0 recording pack into 178 ordered
coordinates: 14 existing scalar fields and 164 literal MFCC, GFCC, HPCP, spectral
contrast and Bark-band coordinates. It performs no fit, normalization, artist
aggregation, FMA join, audio acquisition or genre inference. Each column records
its exact source path and array index; unspecified native units remain explicit.
Variance arrays are source values, not recomputed measurements. Three unavailable
legacy scalar paths are explicitly excluded from this version's fixed schema.

The source nomination contains 100 recordings from ten selection-associated
artists. The 55 available recordings have independent native MusicBrainz credit
proof; 45 source 404 outcomes remain present with null values and true missing
masks. Selection association never substitutes for credit. Source capture dates
remain unknown for 70 nominations. This small selected cohort is not global
coverage or an independent musical-relevance benchmark.

Run from the checkout after `poe sync`, with explicit source selection:

```sh
PYTHONPATH=src .venv/bin/python scripts/build_native_ab_vector_bank.py build \
  --source data/examples/native-sonic --output /tmp/native-ab-bank
PYTHONPATH=src .venv/bin/python scripts/build_native_ab_vector_bank.py verify \
  --source data/examples/native-sonic --output /tmp/native-ab-bank
PYTHONPATH=src .venv/bin/python scripts/build_native_ab_vector_bank.py lookup \
  --source data/examples/native-sonic --output /tmp/native-ab-bank \
  --recording-mbid 126aaa04-a746-424c-84de-01cb13a7a770
```

Build requires a new directory. Verification reconstructs all values and credit
records from the verified raw source, not only output hashes. Lookup verifies
before returning one canonical native recording ID, including missing outcomes;
an unnominated identity fails rather than borrowing a neighbor's record.

The closed output contains `bank.json` and `receipt.json`, capped at 2 MB each
and 4 MB combined. CLI stages have 120-second CPU/wall and 1 GB address-space
limits. The receipt binds the producer implementation and the original source
receipt. The original pack and its license audit remain external, unchanged
inputs. Rebuild twice to distinct directories and compare both output files to
check deterministic replay. No raw descriptive tags enter the bank.

## Retained-source validation, 2026-10-17

The actual bank contains 100 rows and 178 columns: 9,790 finite values across
55 available recordings, and 8,010 explicit missing cells across 45 source-404
recordings. Independent exact recording credits name 17 artists; the ten
selection-associated artists are a different denominator. Source replay and a
second build produce identical bank and receipt bytes. The bank is 419,754 bytes,
SHA-256 `4d5476c1b2c57da4ea788115f013fcba858e3f5a3e4def3196ee5dd55b841ce5`.

A separate native-JSON/credit audit, without producer imports, checked every
value, missing cell and exact credit. Local evidence is
`/workspace/opennoise-backend-independent-20261017/ab-bank-audit.json` with its
`audit_ab_bank.py` implementation. Execution/replay and bounded resource evidence
are `/workspace/opennoise-native-ab-bank-run-20261017/execution-final.json`.
The final stages used under 28 MB RSS and roughly one second each, within the
unchanged CLI limits. These checks establish source fidelity, not useful acoustic
similarity or musical quality.
