# New caller-profile inference from frozen human-genre weights

This local research capsule computes four historical model distributions from **new caller-supplied genre/instrument profiles**. It contains no saved recording scores or tag profiles. Changing tags under the same exact known context changes computed NB/mapping outputs; there is no track-ID lookup. No model is fitted or selected, and no source acquisition is performed.

The [contract](protocol.json), SHA256 `41ea14ecdfe9136a6134821abae789b03e81c9bfd9958bad3680c6b9ca4ca634`, was committed before export. It preserves the [nested study's](../jamendo-genre-temperature-20261019/README.md) five original outer models and selected temperatures/fallbacks, nine-class order and literal uploader mapping. This adds an input/execution capability; it supplies no new quality evidence. The preceding study's slightly worse Brier, uncertain component Brier versus uploader tags and substantial aggregate underconfidence remain limitations.

## Context and profile contract

The full retained metadata has 11,565 native identities, 713 artists/components and 2,365 albums/observed artist–album pairs. Every exact observed pair maps to its original complete-metadata component and fixed excluded outer fold. No artist/component appears in that model's training roster. There are no multi-artist albums/components in these retained bytes, but exact observed pair membership is still required; the implementation never infers an association just because components match. A synthetic shared-component fixture tests the unobserved-pair distinction.

A request has exactly one `profiles` list of 1–100 ordered objects, each with exactly `artist_id`, `album_id`, `tags`. IDs must be positive uint32 JSON integers, excluding bool/string/float. Duplicate profiles remain distinct ordered requests, reported by zero-based `query_index`. There is no caller `track_id` or human-target field. Context checks yield `unknown_artist`, `unknown_album`, `conflicting_component`, `unobserved_artist_album_pair`, then `original_model_unavailable` or `emitted`, in that precedence. Unknown/conflicting contexts abstain all methods; there is no fuzzy match, new fold or fallback to another model.

Tags are 0–250 unique literal strings matching `^(genre|instrument)---[a-z0-9]{1,64}$`. No whitespace/case/alias conversion or duplicate tags is accepted. All 127 retained permitted literals satisfy this grammar. Empty profiles are valid and use the original full-absence model computation. New well-formed tags outside the routed vocabulary are reported as `UNSEEN_BY_NB`; the fixed mapper may independently consume a literal that NB did not learn. Outputs report current-frame recognized NB feature count, matched mapper classes, component/fold/frame hash, selected T/fallback and all four method distributions. Caller tags and claimed context are **assertions**, not verified native recording observations or genre memberships; observing a valid native pair does not verify that a caller's new track belongs to it.

The pure module imports no training, source-parser or builder modules. It reproduces presence/absence Bernoulli logits, training prior, fixed literal mapping and raw-logit temperature scaling. T=1 preserves unscaled probabilities exactly. Empty-vocabulary unscaled NB equals prior, with the same raw-prior-logit temperature softening for T>1. No clipping, score pooling, fitting, calibration selection or optimization is performed at inference.

## Artifact and actual checks

The local capsule is **184,218 bytes**: `models.json` (124,610 bytes), `routing.json` (57,311 bytes) and its closed manifest (2,297 bytes). Manifest SHA256: `4ec3238eab04d3b967ddaec8899bb5ab39bac3eb0eab26c7679c0cb811f0c1ef`. Model/routing payloads contain only five outer parameter sets/Ts/fallbacks and exact context rows. They omit human votes, saved predictions, recording/tag profiles, inner fitted data, training rosters and absolute source paths. The manifest retains hash-only source/protocol/serialization-amendment/identity-census/study/model provenance, attribution, pure runtime pins and separate builder provenance. Builder/source-parser code hashes are provenance; pure inference does not import or require those modules.

Export requires only five verified local inputs: exact metadata, outer-model payload, selected-model payload, externally pinned study receipt and this contract. It does not require original human annotations or prediction/evaluation payloads. An honest fresh study receipt is accepted when its exact selected payload, source protocol/runtime and custody pin are validated; historical absolute paths and historical receipt-envelope identity are not required. The manifest pin must come from the verified export. Loading rejects extra files/symlinks, mismatched external pins, changed physical bytes, malformed/resealed model dimensions/probabilities/mapping, invalid native joins/folds, and missing rights/provenance/runtime fields. JSON duplicate keys and coercible numeric IDs/binding sizes are rejected. Invalid requests fail before any output publication. Export/results require fresh non-overlapping paths and publish atomically.

Producer API validation passed **all 11,565 original allowed-feature profiles in batches ≤100**, reproducing **416,340 probabilities exactly** and every component/fold. This is inference parity validation, not fitting or new evaluation. Its actual CLI additionally processed three new profiles under one known pair (rock, jazz, empty), with changed tags changing NB and mapper results, plus three explicit unknown/conflict abstentions.

An independent implementation, importing no production math, matched those 416,340 retained probabilities and **900 probabilities from 25 new custom profiles**, with maximum error **zero**. It also checked 11,565 routes, 25 invalid-request rejections and explicit context abstentions. Comparison receipt: `/workspace/jamendo-genre-capsule-20261019/independent-production-comparison.json`, SHA256 `aec342c34ecb53d556eed59fa8a483f4a5a28625448266163f933e0f9dd7558c` (667 bytes).

Actual relocated CLI build/infer used only the five needed copied inputs, with original raw/human/prior-result trees denied. Pure inference additionally denied every build input, original capsule, source/training/builder imports and networking. A separately probed call guard actively denied fit/train/partial_fit calls in both stages. Explicit denial probes passed (four build, seven inference); production made **zero forbidden operations, zero fits and zero new requests/$0**. The independently exported capsule was byte-identical, and 25 new profiles/900 probabilities matched exactly. Proof: `/workspace/jamendo-genre-capsule-20261019/relocated-proof-refit-denied/proof.json`, SHA256 `a2406171dd244b76de9f154db8cca5b86f916baf8496fddaa69a7a2d5e5cc2a4` (2,286 bytes). The one local proof observed 1.014 seconds build and 0.501 seconds inference; these are host-specific execution observations, not general performance claims.

[Checked aggregates](results.json) preserve artifact, source, runtime and independent-proof hashes without distributing models/routing/profiles. Eleven focused tests cover independent multiclass math, changed/empty/unseen profiles, strict schemas/IDs/tags, exact observed-pair routing, malformed/resealed probabilities/dimensions/provenance/physical-size types, duplicate keys, atomic failures and training-free imports.

Full `poe check` passed with 2,243 Python tests in 158.725 seconds (36 skips), 166 Node tests (122 passes, 44 skips, zero failures), and format/lint/type checks. The suite includes the final strict-binding regression; all eleven focused tests pass. Independent Luna final source review found no material blockers. Full log: `/tmp/opennoise-jamendo-genre-capsule-check.log`. The audited runtime/capsule hashes are unchanged.

## Reproduce

Use Python 3.13 and `poe sync`. Run from the repository root; substitute honest copied input paths and externally verified study receipt pin where appropriate. These retained files are local noncommercial research artifacts, not checked-in fixtures. All outputs must be fresh.

```bash
.venv/bin/python scripts/run_jamendo_genre_capsule.py build \
  --metadata /workspace/jamendo-human-genre-20261019/source/autotagging-test.tsv \
  --outer-models /workspace/opennoise-jamendo-human-genre/.cache/jamendo-human-genre-20261019/results/models.json \
  --selected-models /workspace/opennoise-jamendo-genre-temperature/.cache/jamendo-genre-temperature-20261019/results/models.json \
  --study-receipt /workspace/opennoise-jamendo-genre-temperature/.cache/jamendo-genre-temperature-20261019/results/receipt.json \
  --study-receipt-sha256 7a6bc7f39e747789f027a0e2cb94e0cdd33608537f02fa80678957ade045801a \
  --protocol data/recipes/jamendo-genre-capsule-20261019/protocol.json \
  --protocol-sha256 41ea14ecdfe9136a6134821abae789b03e81c9bfd9958bad3680c6b9ca4ca634 \
  --output .cache/genre-profile-capsule
```

Then use only that capsule and new caller JSON. For example, the same observed context can receive rock, jazz and empty tag profiles; these are caller assertions, not new source observations:

```bash
.venv/bin/python - <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

query = Path('.cache/new-caller-profiles.json')
query.write_text(json.dumps({'profiles': [
    {'artist_id': 14, 'album_id': 31, 'tags': ['genre---rock']},
    {'artist_id': 14, 'album_id': 31, 'tags': ['genre---jazz']},
    {'artist_id': 14, 'album_id': 31, 'tags': []},
]}))
subprocess.run([
    sys.executable, 'scripts/run_jamendo_genre_capsule.py', 'infer',
    '--capsule', '.cache/genre-profile-capsule',
    '--capsule-sha256', '4ec3238eab04d3b967ddaec8899bb5ab39bac3eb0eab26c7679c0cb811f0c1ef',
    '--queries', str(query),
    '--queries-sha256', hashlib.sha256(query.read_bytes()).hexdigest(),
    '--output', '.cache/new-caller-results.json',
], check=True)
PY
```

The CLI sets one numerical thread, 120 seconds CPU/wall and 1 GB address space before imports. Capsule combined cap is 1 MB; request/result caps are each 2 MB. No serving endpoint or default model changes. Exact-head/main CI status belongs to the associated pull request.

## Rights and limitations

Music Technology Group; Bogdanov, Won, Tovstogan, Porter and Serra (2019), *The MTG-Jamendo Dataset for Automatic Music Tagging*; [pinned annotation documentation](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/derived/music-classification-annotations/README.md), [pinned root README/license](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/README.md). **CC-BY-NC-SA-4.0, noncommercial research only.** Models, routing, requests and per-profile results remain local; only code, contract and restrained attributed aggregates are committed. No source acquisition, model fitting, deployment, source-truth/genre-membership claim, new cohort confirmation, musical similarity, retrieval validation or EveryNoise parity claim is authorized by this artifact.
