# Public graph validation report for 2026-08-31

The first valid time experiment used seven official ListenBrainz increments and the exportable
Wikidata genre catalog. It used no Every Noise data, MusicBrainz user tags, music files, audio
features, or values derived from audio.

The ListenBrainz files cover publication dates from August 24 to August 30, 2026. Their exact
source IDs, byte counts, URLs, and SHA256 values are pinned in `config/data_sources.toml`. The
seven compressed files total 1,514,835,361 bytes. The Wikidata catalog contains 127 named genre
QIDs, 294 direct artist P136 observations, and 174 direct P279 hierarchy edges.

## Joint aggregation

The adapter scanned all seven ListenBrainz files before it discarded listener identities. It
selected seven disjoint event days from August 23 to August 29. For each day and listener, it kept
one set of MusicBrainz artist IDs. A repeated listen or a repeated row in another publication file
therefore could not add the same listener and artist pair twice.

The scan read 30,469,708 listen rows. Of those rows, 993,589 had a usable MusicBrainz artist ID in
the selected event days. The transient state covered 79,673 artists and 40,782 listener days. It
formed 8,420,452 candidate pair rows and emitted 30,903 pair days at the privacy floor of five
distinct listeners. One malformed row was counted and discarded without retaining its payload.

The joint scan took 246.382 seconds and reached 449,683,456 bytes of peak resident memory. The
seven verified source files remain in the local content addressed vault. The source manifest denies
raw export and redistribution. The validation output does not contain listener identities, daily
pair tables, or intermediate model artifacts.

## Graph results

The public graph placed 104 genres. Three seeded weighted label propagation runs had a mean pairwise
community agreement of 0.8162. The communities are experiment output and are not treated as genre
names.

The learned one-hop spectral layout preserved 0.5173 of the 10 nearest graph neighbors on average.
The direct-membership spectral control preserved 0.4077. Changing the spectral input to the learned
profile improved this measure by about 27 percent without adding a layout dependency. Of the
directed learned neighbor rows, 0.7481 had a reciprocal row.

The hierarchy check could evaluate 92 direct P279 edges whose endpoints both had learned profiles.
Of those edges, 0.3804 appeared within a 10-neighbor list in either direction. Hierarchy remained a
separate facet and did not change membership, similarity, communities, or coordinates.

## Event-time holdout

The first graph used five event days. Adding the sixth day produced a directed neighbor Jaccard of
0.8658 and an aligned coordinate RMS movement of 0.0130. Adding the seventh day produced a neighbor
Jaccard of 0.8766 and coordinate movement of 0.0055. Coordinate alignment removes arbitrary
rotation, reflection, translation, and scale before it measures movement.

The public catalog has only one direct membership facet with embedding permission, which is
Wikidata P136. Independent source holdout is therefore unavailable. MusicBrainz tag evidence can
be evaluated in a separate local research run, but that result cannot be exported under its active
policy.

## Hashes and limits

The learned-layout run produced these logical hashes:

```text
settings_sha256      d569f3dd8d9157f61b8935f8d6055ff30a466f6eb943f04c8cffe8bed6f1e16c
validation_sha256    b846804ce71b41dcf09db6741a71188f0421e5f8bb91b6c26c4c3945956a5e79
model_output_sha256  cb96ef20924d1f09e98261683704d32040afc429a8f31a0c4560c88720adfb13
```

The validation build itself took 4.430 seconds. Peak memory remained 449,683,456 bytes because the
process resource counter includes the preceding joint scan. The model checks its final logical
output twice in one process. A regression test also verifies that scan time and peak memory do not
change the input or output hash.

The run caps compressed bytes, records, lines, decompression, time, users, listener days, artists,
candidate pairs, published pairs, direct memberships, propagation visits, similarity visits, and
validation genres. The two dimensional validation has a hard limit of 2,000 genres because its
nearest coordinate check is quadratic. A trustworthiness score is absent because the bounded graph
does not contain complete source-space ranks.

Historical Every Noise data was outside the build and validation commands. It may be used only for
a post-freeze comparison that cannot tune or select the published result.
