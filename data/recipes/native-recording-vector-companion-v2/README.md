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
