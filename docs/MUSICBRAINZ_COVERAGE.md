# MusicBrainz artist genre coverage

The coverage evaluator compares the imported MusicBrainz artist genre labels
with the 6,291 retained Every Noise seed names. It reads only `genres.name`
from the seed catalog. Historical Every Noise coordinates, memberships,
representatives, and ordering are not evaluator or reconstruction inputs.

Run the repeatable local task after the research import:

```text
uv run poe evaluate-musicbrainz-coverage
```

The task writes ignored JSON artifacts under
`.cache/musicbrainz-v3-research/`. `coverage.json` records exact and
normalized label matches, positive direct artist evidence, evidence weights,
unmatched seed names, and runtime. Normalized matching applies NFKD,
casefolding, combining-mark removal, punctuation-to-space conversion, and
space collapsing.

The optional reconstruction artifact contains only direct positive
MusicBrainz artist-to-genre evidence for matched seed names. It is a typed
`ReconstructionInputs` document with a content hash. The baseline report runs
weighted Jaccard and weighted cosine similarity with ten neighbors and records
genre, pair, edge, and artist counts. No historical points or neighbors are
attached.

The imported archive is local noncommercial research data. MusicBrainz core
identity fields are CC0, while genre associations are supplementary
CC-BY-NC-SA-3.0 data. The stored policy permits local normalization, search,
display, embedding, and training, but denies metadata export, raw export, and
redistribution. Coverage and baseline outputs remain local and are not
public-exportable without a separate rights review, attribution, and
ShareAlike decision.
