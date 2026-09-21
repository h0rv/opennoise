# Phase 3 historical v3 semantic comparison (2026-09-21)

## Scope and custody

This is a read-only canonical semantic comparison of the local experimental
v3 projection at `/tmp/phase3-historical-v3-20260921` against the sealed
Phase 3 public model and `data/public.sqlite`. No model, database, static
asset, manifest, receipt, or source-vault artifact was changed.

| Artifact | SHA-256 |
| --- | --- |
| v3 model | `c430b9948b863404827dd346fed6324a38b650ab2a827608078fc145b79fd1ba` |
| v3 serving database | `1fca548fa214aae999f7b2462fd2ebf3e265a7f5195a3d6d76b5393f06bd8df9` |
| v3 receipt | `3bd6adb0d213a4e95ed06e78426f47e85b7ac20e3e0b662de7ee1097140008af` |
| sealed public model | `c9964b7a1a76ddd65b2a79eb73998168e6e4328a4f81b35f2e64c6ddd70a2d1e` |
| sealed public database | `240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc` |
| public receipt | `56cb275ca124c800e49b657a119455705b9b477205dde9d35febb43eaaf2bf96` |

The v3 receipt binds release manifest
`795992807586432e2b285e2ddca9a24a00a16e9fc83b6c382a3e914539333232`,
its model input `1ce33b37b1c3de2c415d559cb8605166e51b7b81a0c704065df2cc450eba8a37`,
and logical output `a206196014c8f4374b8c2dda4d18d9217f4ff94a328baa1a308caf05f0477b12`.

## Canonical equality

Each field below was normalized into deterministic JSON, sorted by semantic
identity, then SHA-256 hashed. Public and v3 values are exactly equal.

| Field | Count | Canonical SHA-256 |
| --- | ---: | --- |
| Source artifact identities | 62 | `5faa89fb81d69de534b985fb15b4d35cd3402191e4048569540a95778ac34f0a` |
| Genre universe (ID, name) | 603 | `a8f0249a8d8bc072446693bdbb666138ce2d9f827bb5dc907a3d536b4f44c483` |
| Direct memberships, scores, components | 4,434 | `556c166e7bbcf4f991ef2711e292c78c91e5f4049f8f812062a73a985bea586f` |
| Co-listen raw windows | 30,903 | `a2720f7ef4926ae1eeea8da640bf1e66b4f543b5e1d8f4221771ee7a8cdbd115` |
| Artist-pair supports and windows | 13,175 | `dae06d30d1be5313bcbe44e02b6dedec92bf0bf274012de1ae552f91cc41a6c6` |
| One-hop memberships, scores, components | 22,091 | `6290bbcce2b05dd2ac880c39e5cc13227eabe6deaece4e66862c9b21510c17ce` |
| Neighbors: identity, score, support, rank | 34,348 | `d519fda41760ce4a495c687559534aaefda50ebd4153376d436abf2d5e6905c0` |
| Representatives | 3,344 | `c53e9680a8a2a0ffe8a081c68f0b88202bd8f33df4a627f4b51777bdce71f3d0` |
| Layout coordinates | 2,002 | `6cb5cb6bfe31584ff6317f78956dc44b505bc8dd227d73a3f934842eae62df24` |
| Layout and unplaced semantic tuples | 4 / 410 | `a0ed216953bea74f2ee26c4d354f6602ab8e5a24af159e6e982bdc7c6730e887` |
| Combined source-neutral semantic model | — | `afa0b428910f01594a2ceb53b6d6fab3c22538aa7571a7c74fb7d2fe92e46c3e` |

## Correction (2026-09-21)

The original provenance-equality statement above is superseded by the reusable,
hash-pinned comparator. Its explicit normalized binding contract finds 37,017
rows on each side but one distinct record fingerprint per side. Model, pair,
neighbor, representative, and layout semantics remain equal under that
contract, but full semantic replay and certification are unproven. See the
[comparator discrepancy checkpoint](PHASE3_V3_SEMANTIC_COMPARATOR_DISCREPANCY_20260921.md).

## Drift and limit

One content difference is representation of one-hop evidence references: all
22,091 one-hop memberships have compacted v3 membership/component reference
strings. The public and v3 reference-inclusive hashes differ, while every
membership identity, score, component, artist-pair window/support, neighbor,
representative, and coordinate above is equal. In addition, the corrected
binding comparison finds one distinct normalized provenance-record fingerprint
per side. The remaining model differences are derived input/output hashes and
run-resource timings.

This establishes a source-neutral semantic result for this bounded comparison.
It does **not** certify v3, qualify it for publication, or assert a
byte-identical replay. No public artifact was mutated.
