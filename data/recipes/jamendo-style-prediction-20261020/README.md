# Genre-only human-style prediction: fixed study stopped

The first fixed production run stopped at fold0/electronic, its second logistic
head. It published no model, predictions, comparison scores or bootstrap results.
The preceding aggressive head passed the acceptance contract; the remaining18
heads were never attempted. No retry, alternate solver, threshold change or
fallback was used. This is a stopped experiment, not evidence of model quality.

The useful completed backend path is identity-first source extraction and a
physically pinned, role-safe availability census, plus a fixed fractional-model
contract and fail-closed implementation. All source support gates passed. The
failure was numerical acceptance, not missing source support. The original
exception combined optimizer-success, finite-value, gradient and objective checks;
its failed subcriterion and optimizer state were not retained and cannot now be
recovered without prohibited refitting. Future failures include bounded optimizer
and head diagnostics; this engineering change was tested synthetically only.

The immutable protocol was committed at `9affbb66` before any fitting, SHA256
`8624a347604e341943f5f91046c0a54b2ce5eae6042fbdbbe777a1c21d68430b`.
It fixes genre-frequency fractional logistic regression, a Beta(1,1) training
prior and cosine-weighted genre TF-IDF k=10 neighbor regression, with no parameter
search. The objective is sum artist-equal fractional BCE plus0.5 times squared
nonbias weights; L-BFGS-B and all acceptance limits remain unchanged. Planned
proper-score comparisons cannot be reported because the run aborted.

## Source and reservation

The two retained official files total9,080,731 bytes under CC BY-NC-SA4.0.
There are11,565 tracks,713 artists/components (one artist per component) and2,365
albums. Development folds0–3 contain8,849 tracks/558 artists,547 complete
five-attribute artists,446 with at least two eligible tracks for every attribute,
and11 unjudged development artists. All five fixed targets retain disagreement
and require exactly three recognized positive/explicit-negative votes per track.

Reserved fold4 contains2,716 tracks/155 artists. Role assignment precedes BOTH
uploader-genre and selected-style extraction: each accessor skips all2,716 rows.
Reserved payloads contain identity/counts and constant `reserved_skipped` only;
there are no feature, style, prediction or target-availability containers. No
reserved confirmation was attempted. Historical covariates and development
style-coherence outcomes were previously seen; this is not a fresh cohort. The
new training feature banks exclude query components and reserved fold4 entirely.
Prior negative instrument findings remain unchanged.

Count-only support was disclosed before freeze: training metadata artists per
fold416/420/424/414, complete training artists409/411/416/405, eligible queries
138/136/131/142 and robust queries119/104/106/117. Each training vocabulary has87
genre tokens, and all five positive/negative component gates pass. None of these
counts is a predictive-performance result.

Attribution: Music Technology Group; Bogdanov, Won, Tovstogan, Porter and Serra
(2019), *The MTG-Jamendo Dataset for Automatic Music Tagging*;
[annotation documentation](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/derived/music-classification-annotations/README.md)
and [source licensing](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/README.md).
Raw data, profiles, votes, weights and individual outputs remain local
noncommercial research artifacts. Only code, contracts and attributed aggregates
are committed. No acquisition, UI/default change, deployment, research-data
promotion or new cost participates ($0).

## Reproduction and custody

From the repository root, run `.venv/bin/poe sync` first. Python3.13.14,
NumPy2.5.2 and SciPy1.18.1 are checked against the frozen runtime. A fresh,
zero-fit census can be reproduced with the exact approved bytes:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/run_jamendo_style_prediction.py census \
  --metadata /workspace/jamendo-human-genre-20261019/source/autotagging-test.tsv \
  --human /workspace/jamendo-human-genre-20261019/source/music-classification-annotations-raw.tsv \
  --protocol data/recipes/jamendo-style-prediction-20261020/protocol.json \
  --protocol-sha256 8624a347604e341943f5f91046c0a54b2ce5eae6042fbdbbe777a1c21d68430b \
  --output .cache/jamendo-style-prediction-20261020/census-new
```

These absolute paths describe current executor custody, not repository inputs or
future availability. If the exact approved files are absent, report the source
blocker; do not download substitutes or assume retained custody. Input byte hashes,
protocol/runtime pins, closed physical inventories and fresh output checks fail
closed. Each stage is bounded to120 seconds CPU/wall,1GB, one thread and20MB
combined census/results including seals.

The original zero-fit census seal is `9fdf617c1245a4d20a5648bd5e5b83a14a22098c288f59ac3e6c4f03dd69e474`;
its source payload is `e4a286d6dd5c68f734acced6ea9da075ac803788b4630d30b47322c69f0ec94e`.
An independent raw-source census comparison checked all713 artists/11,565
identities, development tag counts, targets, DF/support and reserved identity-only
rows (receipt `051bb4958980ca052f0e34b6efb05f6974a971166c28dd967996056047afeb17`).
The producer requires this physical census and exact semantic replay before
fitting. The originally invoked `run` command, retained in the local guarded
proof, attempted exactly two heads and aborted before atomic publication. It
must not be rerun under this frozen study. There is no result to pass to `replay`;
planned successful-run/replay budgets were20 fits each, not a combined total20.

The local failure receipt is
`/workspace/jamendo-style-prediction-20261020/first-production-failure.json`, SHA256
`f92961a191dd8013a9e49127666872ae8a734af3dcd1affb11de59090f6af304`.
Five active denial probes established copied-input custody, blocked original
reads/network/old research models and fitting paths; production made zero
forbidden operations. Audit counts were8,849 genre accesses,8,849 style accesses
and two optimizer calls. The independent Newton verifier remains verification
only and is never substituted as a production result.

The first-run module hash was `b3727033a96d73396c98409f0459ec2885e6adb8b1b1c1cedff968ff0d1a2cca`.
The exact historical module and CLI bytes were recovered after the failure by
reversing the diagnostic/doc edits and matching both externally sealed hashes.
They are preserved in commit `5e9dbd9`; this records recovery time honestly,
without claiming a pre-run implementation commit. The original CLI hash is `61d644cda5afece82d8aa493dacb58632a4c21488d87249aa8a727195eaaad5f`.
Final diagnostic-enhanced source has separate hashes in `results.json`; it is not
represented as the failed source or as a rerun. Future diagnostics cannot explain
the original failure retrospectively.

The final diagnostic implementation was separately exercised through copied-input
CLI **census only**: seal `3bf4e2f4bee1018437924f575ccb6d176f8e5d557d3a1ea56a3c62fc3fe48b9e`,
guard proof `ae837d1fb55c170da8db92e212e1b38d32fa450c974b021cc22e280d8870b15f`.
It made zero optimizer calls and zero forbidden operations, with five denial
probes and8,849 accesses to each permitted development accessor. Independent raw
comparison checked every development track reason/vote count, all713 artists,
11,565 identities, DF and support (receipt
`6a0fe7adbcdf6858564e67bffeb6df16b85a7dd7ed25baf985bb0fc5dcc1df4f`).
This validates final source extraction, not model execution or predictive quality.

## Checks

Final `.venv/bin/poe check` passed:2,349 Python tests in192.336 seconds
(36 skips),122 Node passes (44 skips), formatting, lint and types. Luna
independently reran all14 focused tests and accepted the final source hashes.
The local full-check log is `/tmp/jamendo-style-prediction-final-check.log`.

Fourteen focused tests cover independent objective/gradient examples, fractional
losses, synthetic optimizer failure/no retry, reserved poison fields skipped
before either accessor, query-fold isolation, neighbor ties/fallbacks, physical
byte custody and atomic failure. The retained-data census test performs zero
optimizer calls. There are no real-data performance scores to validate or promote; this
slice’s PR records subsequent exact-head/main CI and custody checks.
