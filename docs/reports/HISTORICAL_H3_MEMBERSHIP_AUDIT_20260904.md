# Historical H3 membership audit, 2026-09-04

The audit used the sealed local H3 projection and its H3-only signal artifact.
It did not access H2 coordinates. The compact machine-readable report is
`historical-signal-audit-v1`; it contains aggregate buckets and four examples,
not a membership export.

| Check | Result | Interpretation |
| --- | ---: | --- |
| H3 memberships | 306,136 | Matches the sealed projection count. |
| Covered genres | 6,289 / 6,291 | Two H2-name nodes have no H3 membership. |
| Zero-coverage names | 2 | `kumaoni pop`, `talentkonkurrence`; keep as nodes with explicit no-H3 evidence. |
| Distinct source artist IDs | 240,007 | Most artists are source-local to one genre. |
| Artists above degree 32 | 0 | The degree-32 hub cutoff removes no retained memberships. |
| kNN edges | 65,343 directed | 27,826 reciprocal pairs; 85.169% of directed edges are mutual. |
| Components | 167 | One 6,099-node component, 18 components of size 2–4, and 148 isolates. |
| Duplicate stable genre IDs | 0 | No ID collision. |
| Duplicate normalized genre names | 0 | No name-normalization collision. |

The isolates are expected from sparse or absent H3 memberships and should not
be hidden by synthetic bridge edges. Mutual-kNN pruning would remove 9,691
one-way edges and increase fragmentation, so it is not a quality improvement.

The four bounded explanations are internally consistent with direct H3 overlap:
rock → permanent wave (17 shared source IDs), black metal → death metal (17),
cumbia → classic Colombian pop (20), and Japanese alternative rock → j-indie
(5). The retained H3 source provides stable artist identifiers but no safe
artist-name ranking at this boundary; the audit therefore publishes at most
three lexically stable source IDs per example, not a raw artist list.
