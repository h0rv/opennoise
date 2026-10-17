# Direct native-source portable queries

This offline command extracts up to 256 requested FMA native track IDs directly
from an already captured and verified official `features.csv` ZIP member. It
avoids materializing the full 221 MB native feature bank or hand-authoring feature
JSON. It still decompresses and verifies the complete source CSV, including rows
after the last requested ID. It is not a source-download or faster-I/O claim.

Use Python 3.13 and the repository's locked dependencies. No acquisition, audio,
training, calibration, or model selection occurs here.

```sh
python scripts/run_fma_portable_encoder.py export-source-queries \
  --bundle /path/to/current-runtime-bundle \
  --bundle-sha256 EXTERNALLY_RECORDED_BUNDLE_SHA256 \
  --source /path/to/retained-feature-source \
  --source-receipt-sha256 EXTERNALLY_RECORDED_SOURCE_RECEIPT_SHA256 \
  --track-id 2 --track-id 3 --output /path/to/fresh-query-pack

python scripts/run_fma_portable_encoder.py infer \
  --bundle /path/to/current-runtime-bundle \
  --bundle-sha256 EXTERNALLY_RECORDED_BUNDLE_SHA256 \
  --queries /path/to/fresh-query-pack \
  --query-sha256 REPORTED_QUERY_MANIFEST_SHA256 \
  --output /path/to/fresh-result.json
```

The source scan alone has the existing native-projection allowance of 300 CPU
seconds, 360 wall seconds and 1,000,000,000 address-space bytes. Query packs retain
the 2 MB/256-row limits; inference retains its 120-second/1 GB limits. The scanner
uses the existing ZIP custody verifier, checked CRC/length stream, exact ordered
518-column native schema and float32 conversion. It rejects duplicate or invalid
native IDs, malformed rows, overflow, reordered columns, truncated streams and a
full native SHA256 different from the bundle. No final manifest is published on
failure. Requested IDs absent from the source have explicit missing-row masks;
request order is preserved. Native roster and component exclusions are unchanged.

`native-source` provenance records the actual source receipt, complete CSV hash,
CRC, byte length and observed row count. It does not pretend to be a feature-bank
export. The source receipt must match the original capture receipt pinned in the
bundle, as well as the complete native CSV hash. Source metadata remains CC BY 4.0
with the existing FMA attribution; no
audio license is inferred. Query labels are never consumed.

## Runtime compatibility and relocation

Portable bundles pin the inference implementation. This new runtime therefore
requires a **new export-bundle from the unchanged frozen fitted state**, using the
existing explicit arm/fold command. Old bundle runtime pins are deliberately not
accepted or rewritten. Re-exporting copies `model.npz`; it does not fit a model.
Compare its bytes with the original fit before using the new bundle.

After export, the bundle and small query pack are sufficient for inference and
replay in a relocated directory. The retained compressed source, full native bank
and original experiment scratch directories are not inference dependencies.

## Checked bounded run

A frozen 256-request batch covered training members, heldout roles, unresolved
artists, absent features and eight unknown-ID contract fixtures. The direct-source
command verified all 106,574 source rows, 951,117,185 decompressed bytes, ZIP CRC
`e8eb7a19` and the full native SHA256 before publishing a 546,838-byte query pack.
It took 54.2 seconds and peaked at 87.0 MB RSS on this executor, while inference
took 0.509 seconds. These are observed single-run costs, not latency guarantees.

There were 208 present source feature rows: 190 produced neighbors, 16 unresolved
artist rows retained embeddings only, and two exceeded training support. The
remaining 48 requests kept explicit missing-feature masks. Every selected value
and mask matched the independently verified full-bank path. The new path avoided
materializing or reading its 221,247,624-byte feature/ID bank during query export.

An independent implementation replayed all 256 results and their relocated copies
with zero vector or distance differences. All inference behavior matched the
previous bank-based batch after excluding intentionally different provenance
pins. Model bytes, candidates and identity roster were unchanged; relocated
results were byte-identical. File traces showed no full-bank/projection reads in
the source-query stage and no original source/experiment reads during relocated
inference. The source was retained data; no new capture, audio, fitting, calibration
or model promotion occurred. Aggregate hashes and resource measurements are in
`results.json`.
