# Offline FMA backend pipeline

This runner makes the retained-source backend workflow executable from explicit inputs: verify or project the native 518-column feature bank, freeze the fixed matched experiment, fit and score its four arms in each of five component folds, then produce the aggregate summary. It does not acquire data, process audio, build a website, or select a new model from the observed results.

The fixed arms are `linear44`, `rff44`, `linear518`, and `rff518`. The source roles and the experiment protocol retain their own verification rules and evidence limitations. Completion means the declared stages completed and their artifacts are bound; it does not establish musical relevance or production readiness.

## Explicit inputs

Use a JSON object with paths relative to one input root:

```json
{
  "source": "numeric44/candidate",
  "native": "retained-native/feature-source",
  "declaration": "native-bank/declaration.json",
  "protocol": "recipes/fixed-factorial/protocol.json",
  "bank": "native-bank/bank"
}
```

`source` is the previously verified minimized numerical corpus consumed by the model loader. `native` is the retained feature-source capture directory. `declaration` is the separately reviewed native-bank declaration. `protocol` must match the experiment implementation's exact approved protocol hash. Optional `bank` names an already completed native bank; when present, the runner checks its declaration and native-source receipt associations and verifies it without repeating projection. Omit `bank` only when an explicitly authorized new projection is required.

The runner hashes only these explicit role files/subtrees, not unrelated files under the input root. Paths cannot escape the input root or traverse symlinks. Outputs must be outside every closed input role. Raw retained inputs and detailed model artifacts remain local research data; this recipe does not grant redistribution rights.

## Prepare, run, and verify

Run from the checked-out implementation with Python 3.13 and its locked environment. An explicit absolute `PYTHONPATH` avoids accidentally importing a different editable checkout. The runner also rejects an in-process module or validator resolved from another checkout.

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/run_fma_backend.py prepare \
  --inputs /absolute/retained-input-root \
  --roles /absolute/roles.json \
  --output /absolute/new-run
```

Preserve the returned `plan_sha256` outside the run directory. Preparation creates `pipeline.json`, binding the role inventories, executable Python sources and entry points, Python runtime, ordered stages, and original execution paths. It does not run models.

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/run_fma_backend.py run \
  --inputs /absolute/retained-input-root \
  --output /absolute/new-run \
  --plan-sha256 PLAN_SHA256
```

The fixed sequence contains 43 stages: bank projection/verification; experiment freeze; four fits then four scores for each of five folds; summary. All fits for a fold precede scoring because the candidate pool is shared across the four representations. The runner serializes these stages and delegates numerical work to the reviewed producer CLIs.

For a deliberate checkpoint boundary, use `--max-stages 1` (or another integer through 43). Preserve the returned `checkpoint_sha256`; the next call supplies both external pins:

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/run_fma_backend.py run \
  --inputs /absolute/retained-input-root \
  --output /absolute/new-run \
  --plan-sha256 PLAN_SHA256 \
  --checkpoint-sha256 CHECKPOINT_SHA256 \
  --max-stages 1
```

Completed stages are skipped only after the latest externally pinned checkpoint and all output bytes match. Checkpoints also bind earlier checkpoints. No successful completed fit is automatically rerun.

```sh
PYTHONPATH="$PWD/src" .venv/bin/python scripts/run_fma_backend.py verify \
  --inputs /absolute/retained-input-root \
  --output /absolute/new-run \
  --plan-sha256 PLAN_SHA256 \
  --checkpoint-sha256 FINAL_CHECKPOINT_SHA256
```

Verification returns the completed stage list, `next_stage`, and `ready`. `ready: true` means all 43 stages are committed, not an endorsement of the model.

## Outputs and limits

- `pipeline.json`: externally pinned input/code plan.
- `bank/`: newly projected bank only when no retained-bank role was supplied.
- `model-seal.json`: original producer seal, preserving its absolute input paths.
- `experiment/fold-F/ARM/fit/`: model, training roster, and producer receipt.
- `experiment/fold-F/ARM/score/`: ranks, candidates, component statistics, and producer receipt.
- `experiment/summary/`: aggregate results and receipt.
- Per-stage logs and execution JSON; numbered immutable checkpoint JSON files.

Projection retains its separately approved 300-second CPU, 360-second wall, 1,000,000,000-byte address-space guards and 240,000,000-byte bank cap. Model stages retain 120-second CPU/wall and 1,000,000,000-byte address-space guards, with a 100,000,000-byte combined model-output cap. Linear algebra is single-threaded. The orchestrator enforces child wall deadlines and caps each captured child log and pipeline JSON receipt at 1,000,000 bytes. These are per-stage limits, not permission for parallel fits or unlimited retries. Reusing a bank performs verification rather than a new projection.

A failed child, malformed receipt, changed input, changed executable source, extra output, or partial stage stops the runner. Partial outputs and logs remain intact. There is no automatic cleanup, rollback, adoption of an incomplete stage, or retry. A partial run cannot be resumed by simply supplying the last successful checkpoint; investigate and obtain an explicit recovery plan rather than removing evidence or silently repeating fits.

## Relocation

Copy the role subtrees while preserving their relative paths, and copy the complete run directory. `verify` accepts a new input root and run location with the same external plan/checkpoint hashes and exact bytes. This is portable verification only. `run` rejects moved execution paths because the underlying experiment seal binds its original absolute paths. The runner never rewrites that seal, reseals a moved model, or claims that relocated verification is numerical refitting/replay.

## Verification evidence to attach after execution

Record the immutable implementation commit, plan and final checkpoint hashes, exact input pins, actual stage resource measurements, final closed verification result, and the separately produced independent numerical replay. Keep numerical outcomes in a clearly identified results section; do not change the protocol or rank models after seeing them.

Implementation checkpoint: `7ea23b1cdf207f78beb2c0f14654e562f5668d7d`. Ten focused synthetic tests cover real producer fit/score/summary receipts across all 43 stages, deliberate resume without duplicate execution, input/output tampering, partial failure, role escape/symlinks, moved verification with moved-execution rejection, retained-bank associations, bytecode-cache stability, wrong-checkout validators, child log overflow, and wall deadlines. These synthetic tests are distinct from the actual retained-data run and its independent replay.


## Completed retained-data execution

The run completed all 43 stages under plan
`1c57c76d8986130b91f6bb7084db4395a62191e047dc0f1c061b18328425bde1`
and final checkpoint
`942c6038f4d0b1ae685e0099101c5b47df1cea3975bb1988605f43596421c75f`.
The full 518-column bank was reused without another projection or acquisition.
Independent checks validated all 273 output files and every checkpoint prefix.
Model output was 86,944,927 bytes; the maximum orchestration stage was 18.218 seconds.
Relocated verification passed with identical model-seal bytes and no fitting.
Independent numerical replay separately passed all 20 model states and 379,812
rank records. See the adjacent fixed-factorial recipe for outcomes and limitations.
The runner tests are in `tests/test_fma_backend.py` so standard discovery includes them.
