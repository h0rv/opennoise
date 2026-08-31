# Public graph validation

The validation job measures whether the public genre graph stays useful when new ListenBrainz
days arrive. It uses Wikidata genre claims and privacy safe ListenBrainz artist pair counts. It
does not use Every Noise coordinates, memberships, artists, or samples. It does not use audio,
music files, or values derived from audio.

## Data split

The first experiment pins seven official ListenBrainz increments from August 24 to August 30,
2026. The manifest records the URL, byte count, and SHA256 for each file. The seven compressed
files total 1,514,835,361 bytes.

An incremental file can contain old backfilled listens, and the same listener and day can occur in
more than one file. The job therefore scans all seven verified files into one bounded transient
state. For each selected event day, it keeps a set of artists for each listener. Duplicate listens
and duplicate publication rows cannot add the same listener and artist pair twice.

The selected event days run from August 23 to August 29. The days are ordered, disjoint, and
contiguous. The first five days form the training graph. The sixth day forms the validation cutoff,
and the seventh day forms the test cutoff. The privacy floor is five distinct listeners per artist
pair and event day. Listener identifiers are discarded before any result is returned or written.

Run the validation job with this command:

```sh
uv run poe validate-public-graph -- \
  --catalog-db data/public-catalog.sqlite \
  --vault data/vault \
  --output data/model/public-graph-validation-v1.json \
  --model-output data/model/public-model-v2.json
```

The job has fixed row, archive, record, time, user, artist, window, pair, and genre bounds. It
allows at most two million transient candidate pairs in one event day. Verified
compressed files stay in the content addressed vault, so a later run does not download them again.
The manifest denies raw export and redistribution for these listener-bearing archives. The report
contains aggregate graph measurements and does not publish daily pair tables or intermediate models.

## Measurements

Temporal stability compares the training graph with the validation graph, and then compares the
validation graph with the test graph. It reports the Jaccard overlap of directed genre neighbors.
It also reports coordinate movement after centering, scaling, and an orthogonal alignment. The
alignment removes arbitrary rotation and reflection before measuring movement.

Map quality compares nearest genres in the similarity graph with nearest genres in two dimensions.
The report includes mean neighbor preservation and the fraction of directed neighbors that are
mutual. A trustworthiness score needs complete source-space ranks, which the bounded top neighbor
graph does not provide, so the job does not report one. A genre with fewer than the requested
number of graph neighbors uses its actual neighbor count as the preservation denominator.

Wikidata subclass claims remain a separate hierarchy facet. The model does not mix parent and
child links into artist similarity. Validation reports how often a direct parent or child appears
in the learned neighbor list. A low value can reveal a mismatch, but it does not prove that either
source is wrong.

Independent source holdout needs two direct membership facets with active embedding permission.
The public build currently has Wikidata P136 only, so the report marks source holdout unavailable.
MusicBrainz tags can take part in a local research run only when the local policy allows embedding.
Any such result remains local when an input policy denies export.

## Community lens

The job runs weighted label propagation with fixed seeds. Communities are layout groups, not genre
names. The report records convergence, modularity, assignments, and agreement between validation
seeds. The public community lens uses one declared seed, removes links between communities for
placement, and reports quality against the full one-hop graph. Hierarchy links stay out of
community discovery. Weighted modularity uses the standard undirected community sum. For each
community, it subtracts the squared share of total degree from the share of internal edge weight.
This includes the expected contribution from same-community nonedges and node diagonals.

## Layout choice

The default layout uses the one-hop learned genre profile and the deterministic sparse spectral
method. On the frozen seven-day run, it preserved 0.5173 of the learned top-10 neighbors. The
direct lens preserved 0.4077 against the same one-hop reference. This supports the one-hop lens as
the default while keeping the direct lens for explanation.

The community lens preserved 0.5510 against the same reference and produced different coordinates
for all 104 placed genres. It remains a separate lens because its groups are learned rather than
named facts. The taxonomy lens is separate because its edges mean subclass, not listening
similarity. No UMAP or other compiled layout dependency was added. The sparse methods complete in
milliseconds on this graph.

Historical Every Noise data may be compared after the public result hash has been fixed. It cannot
enter the build command, tune parameters, select a layout, or decide which result to publish.
