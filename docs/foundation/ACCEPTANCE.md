# End-to-end acceptance

The intended product is a reusable open foundation and a static explorer with
Every Noise's depth and discovery usefulness. The historical snapshot supplies
dated evaluation observations. It does not supply training targets, private
features, or a promise of identical outputs. A portable CC0 example build is
useful evidence for its declared scope; it cannot establish full-corpus parity.

Run the dossier check from a configured Python 3.13 checkout:

```sh
.venv/bin/python scripts/check_foundation_acceptance.py --json
```

Exit 1 means acceptance gaps remain. Exit 2 means malformed declarations or
invalid file bindings. Exit 0 means every gate has complete, byte-bound
`recorded_pass` review testimony. **The checker never establishes musical truth
or automatically certifies semantic equivalence.** Its JSON always reports
`automatic_semantic_pass: false`. Successful source reconstruction, vocabulary
counts, browser tests, or custody verification alone cannot pass all gates.

The checked-in [dossier](acceptance-dossier.json) records limited October 1
checkpoint evidence and leaves every full-foundation gate unmet. New October 2
artifacts require their own explicit dossier bindings and scoped review; their
creation does not silently upgrade these decisions. Recovery of a source vault
or durable Library copy does not reconstruct absent derived inputs by itself.

| Gate | Required review evidence | Current limit / next concrete evidence |
| --- | --- | --- |
| `discovery-behavior` | Actual-export genre → complete artist cohorts → observed/overlapping genres, exact identities, search and abstentions | October 1 browser testimony covers a local optional NC atlas; bind a current export and certify the intended open product's complete flows |
| `full-corpus-rebuild` | Fresh offline reconstruction with versioned source packs, hashes, code revision, seeds, parameters and independently verified outputs | Legacy canonical inputs and full research caches are absent in a clean checkout; declare a new input path and rebuild contract rather than rename a small example as the old release |
| `legal-input-boundaries` | Raw-to-projection license review, derivative scope and reference-training separation | Preserve MusicBrainz CC0 credits/identities separately from optional CC-BY-NC-SA associations; bind and review every full-model input |
| `genre-and-artist-coverage` | Reviewed broad/sub/micro communities across regions, languages and eras; exact-ID artist denominator including sparse/cold profiles | Names and neighborhoods are candidates; acquire diverse evidence and record label decisions and artist gaps rather than treating historical names as accepted genres |
| `independent-musical-relevance` | Prespecified blinded membership/neighbor judgments independent of training sources, disagreement and uncertainty accounting | Held-out source reconstruction supplies no independent musical judgments; assemble a stratified evaluation cohort and review protocol |
| `held-out-source-reconstruction` | Frozen disjoint folds, leakage checks, baselines and independently replayed metrics with cold artists/unseen labels | October 1 confirmation is limited optional source evidence; bind replay outputs for the selected full model without reusing its test folds for tuning |
| `calibrated-overlapping-memberships` | Direct facts separate from broad/sub/micro suggestions, independent calibration, abstention and stability by evidence volume | Multiple candidates do not establish calibrated membership; bind calibration evidence including sparse and unseen cases |
| `acoustic-coverage-and-retrieval` | Diverse exact-credit sonic descriptors, age, missingness and samples; independent retrieval and evaluated cultural/sonic blend | Ten selected artists and 55 descriptor-bearing recordings are a pilot; evaluate broader out-of-domain strata and retain all missing recordings |
| `genre-and-artist-maps` | Independent neighborhood relevance and stability, measured axes where interpretable, readable labels and unpositioned alternatives | Display-coordinate historical agreement and label placement are separate measurements; evaluate current open semantic maps |
| `defining-recordings` | Exact recording/release credits, discography coverage and independently assessed musical fit/diversity | Credited metadata examples are bounded examples; collect and review defining selections for the intended corpus |
| `listening-and-playlists` | Permitted provider paths with availability/missingness and independently assessed central/recent/emerging selections | Outbound artist URLs do not establish available recordings or representative playlists; bind recording/provider selections and their review |
| `plain-accessible-interface` | Actual-export search, full lists, selection, history, deep links, reload, mobile and keyboard tasks with source/inference distinctions | Historical local-export browser testimony is useful but not current-open-export certification; bind current browser receipts and accessible tasks |

Each gate's exact criteria live in `GATES` in
[acceptance.py](../../src/opennoise/pipeline/acceptance.py). Each dossier contains
all twelve gates exactly once. A review has a `missing`, `blocked`, or
`recorded_pass` decision, an explanation, artifact IDs, and `criteria_covered`.
Passing testimony also requires a named reviewer, review date, every criterion,
and nonempty evidence. Missing means necessary evidence has not been supplied;
blocked means a stated dependency or unresolved condition prevents acceptance.

Every artifact declares its relative path, exact byte length and SHA-256, source,
license, pack, construction/evaluation/review role, and scope. Missing files,
directories, symlinks, escapes and changed bytes fail verification. An explicitly
noncommercial license cannot be declared `unrestricted-core`; `every-noise`
source evidence must be `evaluation-only`. These checks catch contradictory
declarations, but do not infer licenses from file contents or replace source
legal review. License and scope fields remain review assertions.

Eight corpus-dependent gates require an artifact declared `full-corpus`:
rebuild, legal boundaries, coverage, calibration, acoustics, maps, defining recordings and
listening/playlists. Behavior and UI require `actual-export` evidence. Declared
scope does not prove scope: reviewers must assess that claim against the bound
artifact and the intended denominator. Portable/selected-cohort evidence cannot
witness a full-corpus gate. For source reconstruction and independent musical
judgments, the documented protocol must explain the full corpus' stratification
and limits, even when the actual evaluation uses a sample.

To update a review, preserve prior receipts, add the new artifacts with hashes
and sizes, explain their scope, and record the decision against every required
criterion. The report returns per-gate `binding_or_review_gaps`, evidence validity
and `all_gates_recorded_pass`; it never reports an overall completion percentage.
The [inventory](README.md) answers which inputs are available for a stage. This
contract answers which review evidence is still needed for the final goal.

The [independent musical review protocol](MUSICAL_REVIEW.md) specifies the
method-blind questions, sampling strata, independent listeners, disagreement,
listening-access failures and confirmation boundaries needed before musical
claims can pass. The October 3 portable browser receipt is bound in the dossier
as partial actual-export evidence; it does not change any full-foundation verdict.
