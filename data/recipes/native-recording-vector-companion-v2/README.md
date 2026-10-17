# Exact native recording vector companion

This offline backend connects verified recording observations to the retained
178-column AcousticBrainz bank by recording MBID and concordant complete native
artist credits. It does not infer identity from names or benchmark selection.
The historical 17-column companion remains unchanged.

Each source observation survives the left join, including repeated recordings.
The report distinguishes observation, unique recording and artist/recording-pair
counts. Unnominated recordings differ from nominated source failures; original
source status, dates, credit facts and selection roles remain in each row's
separate evidence. Conflicts quarantine the whole numeric vector. Nulls are not
zero, and neither missing values nor credits are imputed.

Run `scripts/build_recording_vector_companion.py build` with `--observations`,
`--source` (native-sonic), `--bank`, and a fresh `--output`. Supply the externally
reviewed SHA256 of each input receipt with `--observations-receipt-sha256`,
`--source-receipt-sha256`, and `--bank-receipt-sha256`. The same arguments with
`replay` reconstruct and compare both output files. Use an explicit worktree
`PYTHONPATH` so source receipts bind the intended module.

The CLI enforces 120-second CPU/wall and 1GB address-space limits. This contract
permits at most 1,000 observations, 2MB per JSON file and 4MB total output. It is
a bounded reusable backend contract, not a bulk ingestion or modeling service.
Both independent native source chains are replayed before materialization.

Inputs are retained CC0 MusicBrainz recording facts and AcousticBrainz numeric
analysis. No audio, network, source tags, FMA joins, fitting or musical validation
is involved. The 100 bank nominations are a selected cohort, not global source
coverage; exact credited artist counts must not be confused with selection artists.

## Retained-input execution, 2026-10-17

The checked-in `data/examples/recording-facts` observations and
`data/examples/native-sonic` source were joined with the reviewed native bank.
All 36 observations are distinct recordings and artist/recording pairs: 24 joined,
seven retained `missing_http_404`, and five were not nominated in the bank. Each
of the 178 columns has 24 observed values. No conflict or missing-credit case
occurred in these selected inputs; focused tests cover those rejection paths.

The bank still contains 100 nominations, 55 available recordings, ten selection
artists and 17 independently credited artists. This integration adds no source
records or access rights: it makes verified numeric vectors usable by the
existing recording-observation pipeline. The five unnominated IDs were not
requested, and the seven source failures were not retried. Dates and transport
limitations remain inherited evidence; no contemporary source availability is
inferred from retained captures.

The actual output has 199,519 bytes of observations (SHA256
`64ca2d179861953d385ab60300f13a78d24230d768fc2f9a0000e8abc6e3a8a6`)
and a 1,673-byte report (SHA256
`146774a2cac972f336a7bd051286e7b760d15ef16bcf00936a5150f57fa6f5ae`).
Build, native replay and a fresh second build passed with identical artifact
bytes, each below 0.5 seconds and 28MB peak RSS. Evidence is retained in
`/workspace/opennoise-native-vector-companion-run-20261017/`: `input-freeze.json`,
`execution.json`, `byte-replay.json`, `pack/` and `replay/`. Runtime module SHA256
is `54e828035de391e01fc8ae9985fcd94046ccc8b9f22608265e9dc1f128ba550c`.
