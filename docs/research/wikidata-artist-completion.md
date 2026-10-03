# Exact-artist open source completion

`scripts/build_wikidata_artist_completion.py` constructs a separately named CC0
artist-label completion experiment from the sealed Wikidata exact-identity and
native genre-context packs. It does not replace the historical database, native
artist observations, FMA annotations, or an accepted musical membership model.

The builder hashes each exact MusicBrainz artist UUID with the frozen
`opennoise-artist-completion-v1-frozen` seed before target counting: six of ten
buckets fit the model, two calibrate it, and two independently confirm it.
Every non-deprecated native P136 entity value remains an overlapping source
observation. Only training artists determine label vocabulary, label support and
co-observation counts. A label needs five training artists; a transfer pair needs
three. External graph edges are literal P279 only. P31, region, nationality and
language are not musical inference features in this experiment.

Each held-out artist has one deterministically masked *observed* label. The
remaining observed labels seed a candidate list. Zero-positive, one-positive,
cold-seed and unseen-target queries remain explicit denominators or abstentions;
no missing genre statement becomes a negative musical label. Frozen comparison
arms are training popularity, training co-observation, typed parent, and a fixed
0.75 co-observation / 0.25 parent mixture. The combined arm is specified before
inspection; test results do not choose an arm or tune parameters.

The frozen popularity arm requires supported seeds just like the other arms.
Its result is a conditional baseline. The separately named
`scripts/diagnose_wikidata_unconditional_prior.py` computes an untuned training
prior that needs no seed, on the already-inspected source splits. This diagnostic
does not change the original protocol, refit counts or provide fresh confirmation.
The original model underperforms this meaningful unconditional prior on aggregate
source recovery; see the exact report rather than claiming a general improvement.

Six fixed score bins calibrate **top-ranked masked-source target recovery** using
calibration artists only. Bins below twenty events have no probability estimate.
Wilson intervals describe the source recovery event, not musical truth.
Confirmation reports positive-only recall, sparse/cold strata and masked-event
Brier error. Unlabelled rows have no invented targets or outcomes.

Full-observation artist proposals differ from the masking protocol. Consequently
their `proposal_probability` and `musical_membership_probability` are null.
`masked_task_bin_reference_probability` is disclosed as a reference to the
separate masking experiment, not a calibrated full-observation membership.
Each proposal includes actual training pair/seed counts and any literal typed
parent support; it never overwrites a P136 assertion. UI consumers must use the
separate `source_completion_proposals` namespace and label these as suggestions
from observed labels. Musical validity still needs independent listeners.

The builder streams projections and verifies the closed source inventory,
capture status, exact requested entity sets, raw bytes, unique native P434 UUIDs,
projected P136 observations, and typed P279 against raw provider captures.
The output preserves frozen policy, code hash, source receipt hashes, fitted
counts, every artist/fold/masked-target row, confirmation ranked lists, proposals,
and an exact output inventory. Existing directories are never overwritten.

Run directly with the repository environment and a new output directory:

```sh
PYTHONPATH=src .venv/bin/python scripts/build_wikidata_artist_completion.py \
  --artists /path/to/sealed-wikidata-artist-pack \
  --genres /path/to/sealed-native-genre-context \
  --output /path/to/new-wikidata-artist-completion-output
```

Results belong to the bounded source-selected roster. Neither musical genre
completeness nor Spotify-level granularity follows from a successful replay or
good masked-source recall.
