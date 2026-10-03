# Open foundation and recovery, October 3, 2026

Recovery preceded this implementation. The original all-reference Git bundle,
metadata ZIP and 4,084,785,565-byte project-input archive were saved outside the
executor. The independent parent task additionally downloaded all 443 parts,
checked their sizes and SHA256 values, reconstructed all three originals and
confirmed their full hashes. Original recovery files and source artifacts remain
preserved. A separate new native-input archive retains subsequent source captures,
projections and FMA exports; its 48 Library parts have matching service digests.
Private Library file IDs and transfer instructions belong in the recovery Pages,
not in a public source-code distribution.

## Implemented open paths

| Path | Verified scope | Limit |
| --- | --- | --- |
| MusicBrainz core identities | 2,999,670 exact CC0 artist IDs and native names, streamed from the pinned complete artist member | Names alone supply no genres or recommendations; the whole remote archive hash is unverified |
| Portable CC0 explorer | 150 selected artists, 151 direct source-genre labels, 36 credited recording examples, source links and browser-local listening list | Selected cohort, alphabetical display, incomplete discography and no recording playback certification |
| Wikidata genre taxonomy | 1,000 native entities, 3,091 typed claims, 717 selected P279 edges; every label remains searchable | Capped source selection; no reviewed broad/sub/micro equivalence or inherited artist memberships |
| Broader Wikidata artist scan | Frozen 3,000 core-present UUIDs; 539 resolved identities with 563 direct P136 claims | HTTP 503 failures and 13 recovered bodies with unknown transport status/time; every unresolved/quarantined row retained |
| Native AcousticBrainz pilot | 100 outcomes, 55 numeric recordings with independently verified core credits, 45 missing responses | 70 fetch dates unknown; no tags used for artist joins, no musical-fit verdict |
| FMA source catalog | 109,727 raw tracks, 16,916 native artists, 164 genre definitions and complete paginated cohorts | CC BY 4.0 metadata; track annotations remain track assertions, no MusicBrainz bridge or audio rights |
| FMA acoustic foundation | 106,574 native feature rows, 44 Librosa mean channels, source/member CRC and cell replay | Independent dataset namespace; observed annotations are positive source evidence, not musical ground truth |

The [portable build recipe](../foundation/OPEN_BUILD.md),
[FMA source/catalog recipe](../foundation/FMA.md),
[native sonic custody](NATIVE_SONIC_CUSTODY_20261003.md), and
[broader artist scan](../ingest/WIKIDATA_GLOBAL_ARTIST_GENRES.md) expose source,
missingness and reproduction contracts. Default sealed build/deployment pins
retain their original boundary. Local research candidates are not deployed.

## Models and independent validation

The frozen FMA acoustic model improves test source-positive Recall@10 from
36.63% for training-only popularity to 39.59%. First-positive MRR declines from
0.31911 to 0.31296; rare recovery is 13/263 and cold recovery is 0/14. The split
contains no native training-unseen positives, so it supplies no empirical novel
label result. Artist/known-album/full-feature-duplicate connected grouping was
fixed before fitting after an independent audit found album leakage. The largest
component skews the realized partitions; no balancing or post-result tuning took
place. The [independent audit](../reports/FMA_INDEPENDENT_AUDIT_20261003.md)
replays native custody, all folds, fitted parameters, rankings and metric arms.
Saved ranks also replay offline in a fresh checkout. This is useful acoustic
source reconstruction, not calibrated artist memberships or product promotion.

The [frozen taxonomy graph experiment](OPEN_TAXONOMY_NEIGHBORHOODS_20261003.md)
underperforms its training-degree comparator: Recall@10 is 4.18% versus 17.22%.
Cold and disconnected targets stay in the denominator. Its 611 component-local
positions and 389 abstentions support source-structure inspection. Component
placement and graph edges do not establish sonic or cultural similarity.

The independent recovery patch was read and its 139,159 bytes/hash verified.
Only [distinct connected-split/custody fixes](../reports/NUMERIC_RECOVERY_PORT_20261003.md)
and current-interface skip-link behavior were ported. Generic splitting now
handles all supplied credited artists, canonical recordings, albums and duplicate
groups; replay reconstructs assignments from the original source bytes and an
independently prescribed seed. It agrees with current FMA component membership.
Training-only fitting and unlabelled held-out coverage already exist in the newer
model and have additional regression checks. The older explorer, FMA adapter,
centroid experiment and frozen unpublished branch were not substituted.

Current interfaces retain plain names, lists, search, complete cohorts, deep
links, history, reload and mobile/keyboard access. Skip links focus visible main
content without changing the selected route. Real Chromium contracts exercise
these behaviors. The [design requirements](../serving/DESIGN.md) remain binding.

## Genuine remaining acceptance gaps

The two sealed legacy inputs remain absent. The new source-only SQLite and
taxonomy outputs have their own names and receipts; they cannot recreate the
old database or semantic layout's exact provenance and bytes. The source scan
has limited coverage and capture quality, and the new FMA namespace has no exact
artist bridge into the core. More identities and candidate names do not resolve
those gaps.

Independent listening judgments, community naming/merge/split decisions, musical
membership calibration, globally representative coverage and recording/provider
availability remain required. The [musical review protocol](../foundation/MUSICAL_REVIEW.md)
specifies the missing independent evidence. Metadata license grants do not supply
audio rights or certify defining recordings.

The [ListenBrainz popularity investigation](../research/listenbrainz-aggregate-counts.md)
found that the endpoint combines ListenBrainz and MLHD+ statistics. The selected
proof does not establish redistribution rights for the blended result. Its raw
response and source proofs stay private with export, serving and model-use gates
disabled; no count values enter the unrestricted core.

All twelve full-foundation [acceptance gates](../foundation/ACCEPTANCE.md) remain
unmet. Byte custody, executable models and passing browsers provide scoped
technical evidence, not a completion percentage or a claim of Every Noise parity.
