# Public artist membership real-input build, 2026-09-05

This report records the bounded build from the certified public release. The
candidate is non-serving and is not promoted because no independent public gold
set was supplied.

## Inputs and custody

| Item | Value |
| --- | --- |
| Certified database | `public-release-custody-integrated/objects/cache/sha256/282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite` |
| Database SHA-256 | `c2f3168d450034ac2ec98c3a0f44c71baa4cba2836995a05eda670ba22d11cc5` |
| Name input | `data/model/open-construction-graph-v1.json` |
| Name source SHA-256 | `1ac0c659a9764536675b2fbc9b52186dd745a537a953855e97090878e74fe180` |
| Names parsed | 6,291 |
| Direct facet | Wikidata P136, CC0/export-allowed |
| Direct rows | 4,948 |
| Aggregate source | ListenBrainz joint run, privacy-safe |
| Aggregate run | 86,400-second windows, minimum 5 distinct users |
| Aggregate run observations | 30,903 |
| Normalized aggregate pairs | 13,175 |

The adapter receipt binds each direct source shard to the policy and artifact
reached through the selected row's provenance. MusicBrainz tag evidence remains
available only behind its own policy/facet pair; restricted or local-only rows
are not admitted to this export.

## Candidate partition

| State | Count |
| --- | ---: |
| Direct candidate pairs | 3,049 |
| One-hop propagated candidate pairs | 9,256 |
| Direct names | 292 |
| Aggregate-only names | 0 |
| Explicitly abstained names | 5,999 |
| No public genre identity | 5,996 |
| Ambiguous normalized identity | 3 |
| Examined bounded paths | 30,183 |

The adapter receipt file SHA-256 is
`91e03014dbe0a79673d01f83d93471f195ab0d631d443a45cdd0439b9ccd28ab`; its
approved-input model SHA-256 is
`9fed261e9218ad5ff322c344ffdb9560bfba2ec994a37077a8af985075271285`.
The output logical SHA-256 is `a951e546c4919a69ef3c1454364e27e261acdd7561420fbfcac1b81388d061e4`.
The canonical artifact file SHA-256 is
`1f4c6a787e4610a8dd42864cbd1566e5608307d5956fcee9a357b2af136c85a1`.

## Compatibility-only historical evaluation

The sealed H3 projection is evaluation-only and is not construction input or
independent public gold. It contains 306,136 rows across 6,289 genres. The
strict normalized-name benchmark crosswalk contains 1,173 names and 1,098
public artists. H3 absence is unknown, not a negative label.

The replay evaluator matched 292 unambiguous genre names. It used preferred
English primary names and built uniqueness across all public artist IDs before
filtering to candidate IDs, yielding 1,022 candidate-crosswalk names and IDs.
It mapped 1,622 H3 top-50 positives, overlapped 601, and measured
positives-only micro recall@50 of `0.37053020961775585` (6,765 ranked candidate
predictions in the matched genres). These are compatibility metrics with
explicit positive denominators, not precision, negatives, independent gold,
or a promotion decision. The evaluator binds candidate, approved-input,
public-database, and H3 file hashes and rejects input/hash tampering.
