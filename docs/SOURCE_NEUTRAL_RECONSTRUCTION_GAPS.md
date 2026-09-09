# Source-neutral reconstruction checkpoint

The active objective is an open, source-neutral reconstruction over all 6,291
immutable seed names. This table distinguishes existing evidence from claims
that are still unsupported.

| Requirement | Current evidence | Gap / control |
| --- | --- | --- |
| Retain all seeds | Reconciliation and source-neutral candidate artifacts carry the full 6,291 universe. | Every evaluator must bind its candidate count to the same reconciliation. |
| Direct memberships | Public and MusicBrainz claims remain source-observed and provenance-bound. | Sparse coverage is an abstention, not inferred membership. |
| Hierarchy | Direct taxonomy relations preserve factual, review, and cycle-abstained edges separately. | Only a small factual subset is observed; no private hierarchy is reconstructed. |
| Neighborhoods | Direct and release-group overlap candidates are local, source-labeled, and non-serving. | They require source-independent, positive-only evaluation and explicit abstentions. |
| Held-out evaluation | Taxonomy relations use deterministic source-row holdouts; H3 is evaluation-only. | H3 cannot yield precision because absent positives are unknown. |
| Historical boundary | H3/legacy data are evaluation inputs only. | They must never become construction inputs or a parity claim. |

## Implemented evaluation control

The release-group support H3 evaluator now fails closed unless its candidate,
reconciliation hash, and loaded reconciliation all agree on the complete
6,291-seed universe. The report records that count. This is evaluation plumbing
only: it neither reads H3 during construction nor promotes memberships,
hierarchy edges, or serving output.
