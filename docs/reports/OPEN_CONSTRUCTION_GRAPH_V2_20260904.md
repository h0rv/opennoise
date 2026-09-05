# Open construction graph v2 build evidence

This report records a two-run replay from the retained
`public-taxonomy-expansion-v1` artifact with logical hash
`e1a7d82a7c15008f5f7f0b0afff62a14d48ed284212b3f2dd0b91ff164133271` and byte
hash `774a7dc7c6705dadf726b9274d764b662cd673f746fd59b2f12b579cad8c4745`.
The input path was passed explicitly to the v2 command. The generated graph is
not committed; a fresh checkout must build or configure an explicit retained
artifact as documented in `OPEN_CONSTRUCTION_GRAPH_V2.md`.

Both runs produced logical hash
`9806332b9d35a0153cf150e28f2ba33ac12d5123c17c2b53d92ae25472d549cc`, byte hash
`16a7387f1edeb1b7bf0dcc7689984944363f60841a7f03b23a3065c537fec8b1`, and
8,631,724 bytes. The immutable `LocalObjectStore` key was:

```
open-construction-graph-v2/9806332b9d35a0153cf150e28f2ba33ac12d5123c17c2b53d92ae25472d549cc/16a7387f1edeb1b7bf0dcc7689984944363f60841a7f03b23a3065c537fec8b1.json
```

The gate passed complete legacy coverage, verified expansion, prohibited-input
exclusion, no review promotion, no artist-membership inference, and
deterministic replay.

| Measure | Count |
| --- | ---: |
| Retained legacy name nodes | 6,291 |
| Public catalog anchor nodes | 746 |
| Total nodes | 7,037 |
| Exact factual identity edges | 441 |
| Factual public taxonomy edges | 853 |
| Compositional review edges | 1,940 |
| Ambiguous review edges | 83 |
| Total edges | 3,317 |
| Factual connected legacy seeds | 441 |
| Review-enabled connected legacy seeds | 2,418 |
| Factual/review-enabled components | 5,893 / 3,908 |
| Inferred artist memberships | 0 |
| Review links promoted to facts or memberships | 0 |

The extra catalog anchors are intentional. Removing them would drop review
connectivity whenever a public anchor has no unique legacy-name counterpart,
so v2 keeps the expansion’s 2,418 review-connected legacy seeds without
misrepresenting a review link as a taxonomy fact.
