# Native per-recording sonic metadata

This fresh source pack retains 100 native AcousticBrainz low-level responses:
55 descriptor-bearing recordings and 45 HTTP 404 missing outcomes. It projects
17 declared scalar paths, retaining 14 finite values and three explicit missing
fields for each available recording. Missing responses and fields never become
zero vectors. No artist medians or genre memberships are included.

AcousticBrainz's independently reviewed official declaration says:
“All of the data contained in AcousticBrainz is licensed under the CC0 license
(public domain).” [Provider statement](https://acousticbrainz.org/) and
[CC0 dedication](https://creativecommons.org/publicdomain/zero/1.0/).
The declaration covers native dataset responses, including uploader metadata.
It does not license original audio or unrelated MusicBrainz supplementary
responses. The retained evidence's hash, date, quote and scope are recorded in
`license-audit.json`; that file is review testimony rather than a legal inference
from file presence. The full homepage HTML is not assigned CC0 or distributed.

The sonic bodies are byte-for-byte copies of the 100 retained endpoint responses
from the bounded ten-artist October 1 selection. Selection used the first ten
sorted recording IDs from a bounded first page per benchmark artist. The selection
association is retained as `cohort_artist_mbid`, **not an artist credit** or a
discography/representativeness claim. Original research wrappers stay unchanged
and unpromoted. Their artist summaries, MusicBrainz search responses, NC genres,
release context and historical targets are not pack inputs.

Uploader artist/genre descriptions remain only in the raw CC0 AcousticBrainz
source. Projection reads recording identity aliases and sonic scalar fields;
it consumes no descriptive artist/genre tags. Artist joins require a separate
native MusicBrainz core exact-recording lookup with strict field allowlists,
matching recording ID and explicit artist credit. All 55 available recordings
have that proof: 24 earlier native captures were reused and 31 fresh exact core
lookups were acquired, with 25,453 bytes of core responses. These lookup bodies
contain no requested genre/tag fields or audio. MusicBrainz core metadata is
[CC0](https://musicbrainz.org/doc/About/Data_License). Release credits remain
outside this pack.

Capture dates survive for 30 reused AcousticBrainz responses. The old expanded
ledger retained no observation dates for 70 new responses, which are explicitly
`null`/`not_retained`. Original transport-complete flags are likewise unknown for
those responses. The new import date is separate and never substitutes for a
source observation date. AcousticBrainz stopped collecting data in 2022; client
capture dates do not establish feature age, source accuracy or acoustic relevance.

Verify every retained byte and reconstruct all recording outputs offline:

```sh
.venv/bin/python scripts/build_native_sonic_pack.py \
  --output data/examples/native-sonic --verify-only
```

`manifest.json` freezes every selected recording and the separate source ledgers.
`raw/sonic/` contains all 100 success/missing bodies; `raw/credits/` contains only
55 approved core lookup bodies. `projection.json` reports each source's identity,
finite descriptors, field/date missingness, credit state and source bindings.
`receipt.json` binds the complete machine artifact set; this README is separate
documentation. Extra or symlinked raw files fail verification.

This pack closes portable native source custody for this cohort. It does not
establish diverse/full-corpus acoustic coverage, calibrated neighbors, independent
musical relevance, a model fit or a product promotion. New capture budgets are
60 core lookup requests at intervals of at least 1.1 seconds and 1 MB combined
core response bytes; sonic source bytes are capped at 5 MB. No new AcousticBrainz
requests, audio downloads, Spotify requests or source-wrapper promotion occurred.
