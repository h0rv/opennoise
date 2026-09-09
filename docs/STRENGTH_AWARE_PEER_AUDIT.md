# Strength-aware peer audit

`audit_strength_aware_peer_graph.py` is a local-only, source-neutral audit of
the direct binary and filtered release-group-support candidate artifacts. It
does not use H3 or historical inputs. The nine predeclared combinations of
shared artists (2, 3, 5) and binary Jaccard (0.005, 0.01, 0.02) are all
reported; no named genre cohort selects a threshold.

Selection is preregistered to require a non-dominated grid point on coverage,
non-giant collapse, deterministic edge-drop coassignment, direct-channel
ablation coassignment, support-channel ablation coassignment, and a bounded
derived-community size. If no unique point satisfies that rule, the audit
abstains. Named cohorts are only qualitative review material.

Strong edges only shape the derived display communities. Communities are
deterministic similarity partitions, not factual genre taxonomy. Weak edges
remain counted as navigation candidates. Cross-channel overlapping pairs are
reported separately, and deterministic edge-drop coassignment is a stability
diagnostic rather than a quality certificate.

Consensus micro-neighborhoods are a separate local-only `v2` artifact. It
binds both direct and release-group-support inputs twice: the exact file-byte
SHA-256 and the producer's logical output SHA-256. It also binds the seed
reconciliation file that enumerates every stable seed, so coverage is not
inferred from candidate endpoints.

The preregistered perturbation contract is five fixed seeds (`1979`, `2027`,
`2039`, `2063`, and `2081`), deterministic SHA-256 edge buckets, and a 20%
drop (`bucket < 2000` out of 10,000) per channel and run. Each retained graph
uses deterministic score-times-supported-artist weighted label propagation
(12 iterations), recursively capped at 100 members, with lexical bisection
only when propagation cannot split a large component. An endpoint pair is
published only when its coassignment frequency is at least 0.8 (four of five
runs) in *both* channels. The artifact records both frequencies, run counts,
and the source score/support count for either channel whenever that exact
endpoint was a source candidate.

The output contains a replay SHA-256 over every byte/logical input binding and
the full configuration. It has three deliberately different views:

- `stable_pairs` are the auditable endpoint-level result.
- `ego_affiliations` give every eligible genre its own peer membership, which
  intentionally overlaps with other ego memberships.
- `derived_disjoint_components_not_taxonomy` is merely a graph projection and
  carries an explicit `not_a_taxonomy: true` marker.

Every reconciliation seed is either eligible or appears in `abstentions` with
one reason: no direct candidate endpoint, no support candidate endpoint, or no
cross-channel stable coassignment. This is not a hierarchy, taxonomy, or a
production input, and it reads no historical or H3 artifact.

The completed local replay over `full-direct-control.json`, `full-support.json`,
and the 6,291-seed reconciliation retained 2,490 endpoint pairs and 958
eligible seeds, then explicitly abstained on 5,333 seeds. The apparent delta
from the earlier aggregate-only draft is expected: v2 requires BOTH-channel
endpoint-level coassignment under the declared perturbations and accounts for
the complete reconciliation universe, rather than treating component totals as
coverage. The invariant is `958 + 5,333 = 6,291`; a second run produced
byte-identical output.

Run it locally with:

```bash
python scripts/audit_consensus_micro_neighborhoods.py \
  --direct DIRECT_PEER_ARTIFACT \
  --support RELEASE_GROUP_SUPPORT_PEER_ARTIFACT \
  --seed-reconciliation SEED_RECONCILIATION \
  --output CONSENSUS_OUTPUT
```
